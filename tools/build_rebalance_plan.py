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
                    "target_weight_pct": round(target_weight * 100, 2),
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
