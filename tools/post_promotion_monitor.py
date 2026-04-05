"""30-day post-promotion monitor for EW Top-30 construction.

Compares active EW30 vs legacy sleeve construction, tracking:
  - Cumulative excess vs XBI
  - Realized turnover and cost drag
  - Bull/bear regime label
  - Overlap with regime shadow
  - Position count stability

Run daily as part of production pipeline.

Usage:
    python tools/post_promotion_monitor.py --as-of-date 2026-04-01
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SHADOW_POSITIONS_DIR = PROJECT_ROOT / "artifacts" / "live_shadow" / "positions"
SHADOW_PERF_CSV = PROJECT_ROOT / "artifacts" / "live_shadow" / "performance.csv"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "post_promotion_monitor"

PROMOTION_DATE = "2026-04-01"
MONITOR_WINDOW_DAYS = 30
COST_BPS_PER_TURN = 16.7  # from txn_cost_model


def load_shadow_positions(as_of_date: str) -> List[Dict]:
    """Load shadow positions for a date."""
    path = SHADOW_POSITIONS_DIR / f"{as_of_date}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("positions", [])


def load_perf_csv(path: Path, since: str) -> List[Dict]:
    """Load performance rows since a date."""
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("date", "")
            if d >= since:
                try:
                    rows.append(
                        {
                            "date": d,
                            "pnl_pct": float(row.get("pnl_pct") or 0),
                            "xbi_pct": float(row.get("xbi_return_pct") or 0),
                            "excess": float(row.get("excess_vs_xbi_pct") or 0),
                            "n_held": int(float(row.get("n_held") or 0)),
                            "turnover": float(row.get("turnover") or 0),
                        }
                    )
                except (ValueError, TypeError):
                    pass
    return rows


def compute_monitor(as_of_date: str) -> Dict[str, Any]:
    """Compute post-promotion monitor metrics."""
    days_since = (date.fromisoformat(as_of_date) - date.fromisoformat(PROMOTION_DATE)).days
    in_window = 0 <= days_since <= MONITOR_WINDOW_DAYS

    # Load positions
    positions = load_shadow_positions(as_of_date)
    tickers = {p["ticker"] for p in positions}

    # Position stats
    n_positions = len(positions)
    modes = {p.get("size_band", "") for p in positions}
    is_ew_mode = "EW" in modes

    # Turnover from performance
    perf_rows = load_perf_csv(SHADOW_PERF_CSV, PROMOTION_DATE)
    post_promo_perf = [r for r in perf_rows if r["date"] >= PROMOTION_DATE]

    cum_excess = sum(r["excess"] for r in post_promo_perf)
    cum_pnl = sum(r["pnl_pct"] for r in post_promo_perf)
    cum_xbi = sum(r["xbi_pct"] for r in post_promo_perf)
    total_turnover = sum(r["turnover"] for r in post_promo_perf)
    n_periods = len(post_promo_perf)

    # Realized cost drag estimate
    realized_cost_drag_bps = total_turnover * COST_BPS_PER_TURN * 2  # round-trip

    # Regime classification (simple: XBI cumulative since promotion)
    if cum_xbi < -2:
        regime = "bear"
    elif cum_xbi > 2:
        regime = "bull"
    else:
        regime = "neutral"

    # Alerts
    alerts = []
    if n_positions < 25:
        alerts.append(f"LOW_POSITIONS: only {n_positions} positions (expected ~30)")
    if n_periods > 0 and cum_excess < -5:
        alerts.append(f"EXCESS_DRAWDOWN: {cum_excess:+.1f}% since promotion")
    if regime == "bull" and n_periods > 10:
        alerts.append("BULL_REGIME: known weakness zone — monitor closely")
    if realized_cost_drag_bps > 50:
        alerts.append(f"HIGH_COST_DRAG: {realized_cost_drag_bps:.0f} bps realized since promotion")

    return {
        "schema": "post_promotion_monitor.v1",
        "as_of_date": as_of_date,
        "promotion_date": PROMOTION_DATE,
        "days_since_promotion": days_since,
        "in_monitor_window": in_window,
        "construction_mode": "ew_top_n" if is_ew_mode else "sleeve",
        "n_positions": n_positions,
        "performance_since_promotion": {
            "n_periods": n_periods,
            "cum_pnl_pct": round(cum_pnl, 2),
            "cum_xbi_pct": round(cum_xbi, 2),
            "cum_excess_pct": round(cum_excess, 2),
            "total_turnover": round(total_turnover, 4),
            "realized_cost_drag_bps": round(realized_cost_drag_bps, 1),
        },
        "regime": regime,
        "alerts": alerts,
        "position_tickers": sorted(tickers),
    }


def print_monitor(m: Dict):
    print(f"\n{'='*60}")
    print(f"POST-PROMOTION MONITOR — Day {m['days_since_promotion']}")
    print(f"{'='*60}")
    print(f"  Mode:       {m['construction_mode']}")
    print(f"  Positions:  {m['n_positions']}")
    print(f"  Regime:     {m['regime']}")
    p = m["performance_since_promotion"]
    print(f"\n  Since {m['promotion_date']}:")
    print(f"    PnL:      {p['cum_pnl_pct']:+.2f}%")
    print(f"    XBI:      {p['cum_xbi_pct']:+.2f}%")
    print(f"    Excess:   {p['cum_excess_pct']:+.2f}%")
    print(f"    Turnover: {p['total_turnover']:.1%}")
    print(f"    Cost:     {p['realized_cost_drag_bps']:.0f} bps")

    if m["alerts"]:
        print("\n  ALERTS:")
        for a in m["alerts"]:
            print(f"    - {a}")
    else:
        print("\n  No alerts.")

    status = "IN WINDOW" if m["in_monitor_window"] else "MONITOR COMPLETE"
    print(f"\n  Status: {status}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    result = compute_monitor(args.as_of_date)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{args.as_of_date}_monitor.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print_monitor(result)
    print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
