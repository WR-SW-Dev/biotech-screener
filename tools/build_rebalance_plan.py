#!/usr/bin/env python3
"""Rebalance plan builder for the IDZ pruner portfolio.

Given the current Top-30 DEM rankings + inst_delta_z, computes:
  1. Target portfolio: EW Top-20 (pruned by inst_delta_z)
  2. Diff vs current shadow holdings
  3. Trade list with cost estimates
  4. Turnover threshold gate (skip if turnover < threshold)
  5. Earnings proximity flag (names reporting within 5 days)

Usage:
    python tools/build_rebalance_plan.py --as-of-date 2026-04-02
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
SHADOW_POS_DIR = REPO_ROOT / "artifacts" / "live_shadow" / "positions"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "rebalance_plan"

SCHEMA = "rebalance_plan.v1"
TOP_N_DEM = 30
TOP_N_PRUNED = 20
ACCOUNT_USD = 500_000
TURNOVER_THRESHOLD = 0.05  # skip rebalance if < 5% one-way turnover
EARNINGS_PROXIMITY_DAYS = 5  # flag names reporting within N days


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _compute_drawdowns(
    price_csv: Path,
    as_of_date: str,
    portfolio_tickers: list[str],
    lookback: int = 20,
) -> tuple[float, dict[str, float]]:
    """Compute trailing drawdowns from price history for C4.

    Returns (portfolio_dd_from_high, {ticker: dd_from_high}).
    Uses XBI as portfolio proxy. DD is negative (e.g., -0.12 = 12% below high).
    """
    tickers_needed = set(portfolio_tickers) | {"XBI"}

    # Load prices: {ticker: [(date_str, close), ...]}
    prices: dict[str, list[tuple[str, float]]] = {}
    with open(price_csv, newline="") as f:
        for row in csv.DictReader(f):
            tk = row.get("ticker", "")
            if tk not in tickers_needed:
                continue
            d = row.get("date", "")
            c = _sf(row.get("close"), default=None)
            if d and c is not None:
                prices.setdefault(tk, []).append((d, c))

    # Sort by date, take last `lookback` entries up to as_of_date
    def _trailing(ticker: str) -> tuple[float, float] | None:
        """Returns (high, current) for trailing window, or None."""
        pts = prices.get(ticker, [])
        pts = [(d, c) for d, c in pts if d <= as_of_date]
        pts.sort(key=lambda x: x[0])
        if len(pts) < 2:
            return None
        window = pts[-lookback:]
        high = max(c for _, c in window)
        current = window[-1][1]
        return high, current

    # Portfolio-level DD (XBI proxy)
    xbi = _trailing("XBI")
    portfolio_dd = 0.0
    if xbi and xbi[0] > 0:
        portfolio_dd = (xbi[1] - xbi[0]) / xbi[0]  # negative when below high

    # Single-name DDs
    name_dds: dict[str, float] = {}
    for tk in portfolio_tickers:
        result = _trailing(tk)
        if result and result[0] > 0:
            dd = (result[1] - result[0]) / result[0]
            name_dds[tk] = dd

    return portfolio_dd, name_dds


def build_plan(as_of_date: str) -> dict[str, Any]:
    rankings_path = SNAPSHOTS_DIR / as_of_date / "rankings.csv"
    if not rankings_path.exists():
        return {"error": f"No rankings for {as_of_date}"}

    with open(rankings_path) as f:
        rows = list(csv.DictReader(f))

    # Get Top-30 by DEM
    ranked = [r for r in rows if r.get("actionable_rank", "").strip()]
    ranked.sort(key=lambda r: int(float(r["actionable_rank"])))
    top30 = ranked[:TOP_N_DEM]

    # Prune to Top-20 by inst_delta_z
    for r in top30:
        r["_idz"] = _sf(r.get("inst_delta_z"))

    with_signal = [r for r in top30 if not math.isnan(r["_idz"])]
    if len(with_signal) >= TOP_N_PRUNED:
        with_signal.sort(key=lambda r: r["_idz"], reverse=True)
        target_tickers = {r["ticker"] for r in with_signal[:TOP_N_PRUNED]}
    else:
        target_tickers = {r["ticker"] for r in top30[:TOP_N_PRUNED]}

    target_weight = 1.0 / len(target_tickers) if target_tickers else 0

    # Apply risk layer constraints
    from portfolio_risk_layer import MarketSnapshot, PortfolioPolicy
    from portfolio_risk_layer import Position as RiskPosition
    from portfolio_risk_layer import apply_risk_layer

    policy_path = REPO_ROOT / "production_data" / "portfolio_policy.json"
    policy_data = json.loads(policy_path.read_text()) if policy_path.exists() else {}

    risk_positions = []
    for r in top30:
        if r["ticker"] not in target_tickers:
            continue
        risk_positions.append(
            RiskPosition(
                ticker=r["ticker"],
                rank=int(float(r["actionable_rank"])),
                weight=target_weight,
                therapeutic_area=r.get("therapeutic_area"),
                primary_indication=r.get("primary_indication"),
                lead_program_phase=r.get("lead_program_phase"),
                adv_usd_20d=_sf(r.get("adv_usd_20d"), default=None),
            )
        )

    vt = policy_data.get("vol_target", {})
    ccl = policy_data.get("corr_cluster_limit", {})
    risk_policy = PortfolioPolicy(
        risk_layer_enabled=policy_data.get("risk_layer_enabled", True),
        global_name_cap_pct=policy_data.get("global_name_cap", {}).get("cap_pct", 0.03),
        therapeutic_area_cap_pct=policy_data.get("therapeutic_area_cap_pct", 0.40),
        liquidity_max_adv_pct=policy_data.get("liquidity_max_adv_pct", 0.05),
        account_usd=policy_data.get("account_usd", 500_000),
        drawdown_breaker_enabled=policy_data.get("drawdown_breaker", {}).get("enabled", True),
        portfolio_dd_threshold=policy_data.get("drawdown_breaker", {}).get("portfolio_dd_threshold", 0.15),
        portfolio_dd_cap_multiplier=policy_data.get("drawdown_breaker", {}).get("portfolio_dd_cap_multiplier", 0.75),
        single_name_dd_threshold=policy_data.get("drawdown_breaker", {}).get("single_name_dd_threshold", 0.40),
        correlated_pair_enabled=policy_data.get("correlated_pair_limit", {}).get("enabled", True),
        max_same_indication_phase=policy_data.get("correlated_pair_limit", {}).get("max_same_indication_phase", 2),
        vol_target_enabled=vt.get("enabled", False),
        vol_target_annualized=vt.get("target_annualized", 0.50),
        vol_target_action=vt.get("action", "WARN"),
        corr_cluster_enabled=ccl.get("enabled", False),
        corr_cluster_max_names=ccl.get("max_names_per_cluster", 3),
    )

    # Build market snapshot for risk layer
    snapshot = MarketSnapshot()
    price_csv = REPO_ROOT / "production_data" / "price_history.csv"

    # C4: Populate drawdown data from price history
    try:
        if price_csv.exists():
            portfolio_tks = [p.ticker for p in risk_positions]
            portfolio_dd, name_dds = _compute_drawdowns(price_csv, as_of_date, portfolio_tks)
            snapshot.portfolio_dd_from_high = portfolio_dd
            snapshot.single_name_dds = name_dds
    except Exception:
        pass  # graceful degradation — C4 skips with default (0.0)

    # C6/C7: Build vol/corr snapshot
    try:
        from portfolio_vol_corr_layer import build_vol_corr_snapshot

        if price_csv.exists() and (risk_policy.vol_target_enabled or risk_policy.corr_cluster_enabled):
            portfolio_tks = [p.ticker for p in risk_positions]
            ew_w = 1.0 / max(len(portfolio_tks), 1)
            snapshot.vol_corr_snapshot = build_vol_corr_snapshot(
                price_csv,
                portfolio_tks,
                {t: ew_w for t in portfolio_tks},
                vol_target=risk_policy.vol_target_annualized,
                corr_threshold=0.70,
                lookback_days=ccl.get("lookback_days", 60),
                as_of_date=as_of_date,
            )
    except Exception:
        pass  # graceful degradation -- C6/C7 skip with WARN flags

    risk_result = apply_risk_layer(risk_positions, risk_policy, snapshot)
    risk_weights = {p.ticker: p.weight for p in risk_result.positions}
    risk_breaches = risk_result.breaches
    risk_flags = risk_result.flags

    # Update target_tickers to reflect any positions dropped by C5
    target_tickers = {p.ticker for p in risk_result.positions}

    # Load current shadow positions
    pos_path = SHADOW_POS_DIR / f"{as_of_date}.json"
    current_holdings: set[str] = set()
    if pos_path.exists():
        pos_data = json.loads(pos_path.read_text())
        for p in pos_data.get("positions", []):
            current_holdings.add(p.get("ticker", ""))

    # Compute trades
    buys = sorted(target_tickers - current_holdings)
    sells = sorted(current_holdings - target_tickers)
    holds = sorted(target_tickers & current_holdings)
    one_way_turnover = len(buys) / len(target_tickers) if target_tickers else 0

    # Earnings proximity
    earnings_flags = []
    as_of = date.fromisoformat(as_of_date)
    for r in top30:
        if r["ticker"] not in target_tickers:
            continue
        ed = r.get("next_earnings_date", "")
        if ed:
            try:
                edate = date.fromisoformat(ed)
                days_to = (edate - as_of).days
                if 0 <= days_to <= EARNINGS_PROXIMITY_DAYS:
                    earnings_flags.append(
                        {
                            "ticker": r["ticker"],
                            "earnings_date": ed,
                            "days_to_earnings": days_to,
                        }
                    )
            except ValueError:
                pass

    # Cost estimate
    position_usd = ACCOUNT_USD / len(target_tickers) if target_tickers else 0
    est_spread_per_trade_bps = 20  # conservative small-cap biotech
    est_cost_per_trade_usd = position_usd * est_spread_per_trade_bps / 10000
    total_trade_cost = est_cost_per_trade_usd * (len(buys) + len(sells))

    # Gate decision
    skip = one_way_turnover < TURNOVER_THRESHOLD
    gate_reason = f"turnover {one_way_turnover:.0%} < {TURNOVER_THRESHOLD:.0%} threshold" if skip else ""

    # Build target book with IDZ values
    target_book = []
    for r in top30:
        if r["ticker"] in target_tickers:
            target_book.append(
                {
                    "ticker": r["ticker"],
                    "dem_rank": int(float(r["actionable_rank"])),
                    "inst_delta_z": round(r["_idz"], 4) if not math.isnan(r["_idz"]) else None,
                    "target_weight_pct": round(risk_weights.get(r["ticker"], target_weight) * 100, 2),
                    "action": "HOLD" if r["ticker"] in current_holdings else "BUY",
                    "next_earnings_date": r.get("next_earnings_date", ""),
                }
            )
    target_book.sort(key=lambda x: -(x.get("inst_delta_z") or -999))

    # Dropped names with reason
    dropped = []
    for r in top30:
        if r["ticker"] not in target_tickers:
            dropped.append(
                {
                    "ticker": r["ticker"],
                    "dem_rank": int(float(r["actionable_rank"])),
                    "inst_delta_z": round(r["_idz"], 4) if not math.isnan(r["_idz"]) else None,
                    "reason": "pruned_by_inst_delta_z",
                }
            )

    return {
        "schema": SCHEMA,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "architecture": "DEM Top-30 → IDZ prune → EW Top-20",
        "target_count": len(target_tickers),
        "current_count": len(current_holdings),
        "buys": buys,
        "sells": sells,
        "holds": holds,
        "n_buys": len(buys),
        "n_sells": len(sells),
        "n_holds": len(holds),
        "one_way_turnover": round(one_way_turnover, 4),
        "skip_rebalance": skip,
        "skip_reason": gate_reason,
        "earnings_flags": earnings_flags,
        "est_trade_cost_usd": round(total_trade_cost, 2),
        "target_book": target_book,
        "dropped": dropped,
        "risk_layer": {
            "effective_cap_pct": risk_result.effective_cap_pct,
            "n_breaches": len(risk_breaches),
            "breaches": risk_breaches,
            "flags": risk_flags,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Build rebalance plan")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    result = build_plan(args.as_of_date)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{args.as_of_date}_plan.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    print(f"REBALANCE PLAN — {args.as_of_date}")
    print(f"  Architecture: {result['architecture']}")
    print(f"  Target: {result['target_count']} names | Current: {result['current_count']}")
    print(f"  Buys: {result['n_buys']} | Sells: {result['n_sells']} | Holds: {result['n_holds']}")
    print(f"  Turnover: {result['one_way_turnover']:.0%}")
    if result["skip_rebalance"]:
        print(f"  SKIP: {result['skip_reason']}")
    else:
        print(f"  EXECUTE: est cost ${result['est_trade_cost_usd']:.0f}")

    if result["earnings_flags"]:
        print(f"\n  EARNINGS WARNING ({len(result['earnings_flags'])} names):")
        for ef in result["earnings_flags"]:
            print(f"    {ef['ticker']}: reports in {ef['days_to_earnings']}d ({ef['earnings_date']})")

    print("\n  Target book (by IDZ):")
    for t in result["target_book"][:10]:
        idz = f"{t['inst_delta_z']:+.3f}" if t["inst_delta_z"] is not None else "  N/A"
        print(
            f"    {t['action']:4s} {t['ticker']:6s}  DEM#{t['dem_rank']:<3d}  IDZ={idz}  {t['target_weight_pct']:.1f}%"
        )

    if result["dropped"]:
        print(f"\n  Dropped ({len(result['dropped'])}):")
        for d in result["dropped"]:
            idz = f"{d['inst_delta_z']:+.3f}" if d["inst_delta_z"] is not None else "  N/A"
            print(f"    DROP {d['ticker']:6s}  DEM#{d['dem_rank']:<3d}  IDZ={idz}")

    print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
