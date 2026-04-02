#!/usr/bin/env python3
"""Regime-gated pruner recommendation — the daily execution decision.

Policy:
  Bear regime  → EW Top-30 (DEM carries, pruner hurts)
  Bull/Neutral → IDZ-pruned EW Top-20 (pruner adds +1.95-3.77pp)

Combines regime detection, pruner output, risk monitor, and rebalance plan
into a single actionable recommendation artifact.

This is the committee-ready ops pack: one artifact with the daily call.

Usage:
    python tools/build_regime_pruner_recommendation.py --as-of-date 2026-04-02
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
PRICE_CSV = REPO_ROOT / "production_data" / "price_history.csv"
REBALANCE_DIR = REPO_ROOT / "artifacts" / "rebalance_plan"
RISK_DIR = REPO_ROOT / "artifacts" / "risk_monitor"
PROMO_MONITOR_DIR = REPO_ROOT / "artifacts" / "post_promotion_monitor"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "regime_pruner"

SCHEMA = "regime_pruner_recommendation.v1"

# Regime thresholds (from regime analysis: XBI 30d return)
BEAR_THRESHOLD = -0.02
BULL_THRESHOLD = 0.02


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _xbi_30d_return(as_of_date: str) -> float | None:
    """Compute XBI 30d return from price history."""
    prices = {}
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            if row.get("ticker") == "XBI":
                try:
                    prices[row["date"]] = float(row["close"])
                except (ValueError, KeyError):
                    pass
    sorted_dates = sorted(prices.keys())
    # Find as_of_date or nearest prior
    valid = [d for d in sorted_dates if d <= as_of_date]
    if len(valid) < 22:
        return None
    current = prices[valid[-1]]
    prior = prices[valid[-22]]
    if prior > 0:
        return current / prior - 1
    return None


def build_recommendation(as_of_date: str) -> dict:
    # 1. Regime detection
    xbi_ret = _xbi_30d_return(as_of_date)
    if xbi_ret is None:
        regime = "unknown"
    elif xbi_ret < BEAR_THRESHOLD:
        regime = "bear"
    elif xbi_ret > BULL_THRESHOLD:
        regime = "bull"
    else:
        regime = "neutral"

    # 2. Policy decision
    if regime == "bear":
        recommendation = "ew_top30"
        reason = (
            f"Bear regime (XBI 30d: {xbi_ret:+.1%}). Pruner hurts in bear (-0.56pp historical). Stay with EW Top-30."
        )
    elif regime in ("bull", "neutral"):
        recommendation = "idz_pruned_top20"
        regime_spread = "+3.77pp" if regime == "bull" else "+1.95pp"
        reason = f"{regime.title()} regime (XBI 30d: {xbi_ret:+.1%}). Pruner adds {regime_spread} historical. Use IDZ Top-20."
    else:
        recommendation = "ew_top30"
        reason = "Regime unknown. Default to EW Top-30."

    # 3. Load supporting artifacts
    rebalance = _load_json(REBALANCE_DIR / f"{as_of_date}_plan.json")
    risk = _load_json(RISK_DIR / f"{as_of_date}_risk.json")
    promo = _load_json(PROMO_MONITOR_DIR / f"{as_of_date}_monitor.json")

    # 4. Risk override: if risk is CRITICAL, stay with Top-30 regardless
    risk_level = risk.get("risk_level", "NORMAL") if risk else "UNKNOWN"
    risk_override = False
    if risk_level == "CRITICAL" and recommendation == "idz_pruned_top20":
        risk_override = True
        recommendation = "ew_top30"
        reason += " OVERRIDDEN by CRITICAL risk level."

    # 5. Turnover gate
    skip_rebalance = True
    turnover = 0
    if rebalance:
        skip_rebalance = rebalance.get("skip_rebalance", True)
        turnover = rebalance.get("one_way_turnover", 0)

    # 6. Build target book
    if recommendation == "idz_pruned_top20" and rebalance:
        target_book = rebalance.get("target_book", [])
        dropped = rebalance.get("dropped", [])
        n_buys = rebalance.get("n_buys", 0)
        n_sells = rebalance.get("n_sells", 0)
    else:
        # EW Top-30: load from rankings
        target_book = []
        dropped = []
        n_buys = 0
        n_sells = 0
        rankings_path = SNAPSHOTS_DIR / as_of_date / "rankings.csv"
        if rankings_path.exists():
            with open(rankings_path) as f:
                rows = list(csv.DictReader(f))
            ranked = [r for r in rows if r.get("actionable_rank", "").strip()]
            ranked.sort(key=lambda r: int(float(r["actionable_rank"])))
            for r in ranked[:30]:
                target_book.append(
                    {
                        "ticker": r["ticker"],
                        "dem_rank": int(float(r["actionable_rank"])),
                        "target_weight_pct": round(100 / 30, 2),
                    }
                )

    # 7. Earnings warnings
    earnings_flags = rebalance.get("earnings_flags", []) if rebalance else []

    # 8. Post-promotion status
    promo_day = promo.get("days_since_promotion", "?") if promo else "?"
    promo_excess = promo.get("performance_since_promotion", {}).get("cum_excess_pct", 0) if promo else 0

    return {
        "schema": SCHEMA,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # Decision
        "recommendation": recommendation,
        "reason": reason,
        "regime": regime,
        "xbi_30d_return": round(xbi_ret, 4) if xbi_ret is not None else None,
        "risk_level": risk_level,
        "risk_override": risk_override,
        # Execution
        "skip_rebalance": skip_rebalance,
        "turnover": round(turnover, 4),
        "n_buys": n_buys,
        "n_sells": n_sells,
        "n_target": len(target_book),
        "est_trade_cost_usd": rebalance.get("est_trade_cost_usd", 0) if rebalance else 0,
        # Portfolio
        "target_book": target_book,
        "dropped": dropped,
        "earnings_flags": earnings_flags,
        # Context
        "post_promotion_day": promo_day,
        "post_promotion_excess": promo_excess,
        "risk_alerts": risk.get("alerts", []) if risk else [],
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Regime-gated pruner recommendation")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    result = build_recommendation(args.as_of_date)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{args.as_of_date}_recommendation.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    r = result
    print(f"{'='*60}")
    print(f"REGIME PRUNER — {args.as_of_date}")
    print(f"{'='*60}")
    print(
        f"  Regime:         {r['regime']} (XBI 30d: {r['xbi_30d_return']:+.1%})"
        if r["xbi_30d_return"]
        else f"  Regime: {r['regime']}"
    )
    print(f"  Risk:           {r['risk_level']}")
    print(f"  RECOMMENDATION: {r['recommendation'].upper()}")
    print(f"  Reason:         {r['reason']}")
    if r["risk_override"]:
        print("  *** RISK OVERRIDE ACTIVE ***")
    print(f"\n  Portfolio: {r['n_target']} names")
    print(f"  Turnover: {r['turnover']:.0%} | {'SKIP' if r['skip_rebalance'] else 'EXECUTE'}")
    if r["earnings_flags"]:
        print(f"  Earnings warnings: {len(r['earnings_flags'])}")
        for ef in r["earnings_flags"]:
            print(f"    {ef['ticker']}: {ef['days_to_earnings']}d")
    print(f"  Post-promo: day {r['post_promotion_day']}, excess {r['post_promotion_excess']:+.2f}%")

    if r["risk_alerts"]:
        print("\n  Risk alerts:")
        for a in r["risk_alerts"]:
            print(f"    [{a['level']}] {a['detail']}")

    print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
