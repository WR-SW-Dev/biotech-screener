#!/usr/bin/env python3
"""Transaction cost model for ranker promotion bar.

Estimates round-trip costs per rebalance and annualized cost drag
for EW Top-30 vs hypothetical rank-weighted alternatives.

Cost components:
  1. Spread cost: f(ADV) — smaller names have wider spreads
  2. Market impact: f(trade_size / ADV) — Almgren-Chriss square-root model
  3. Commission: flat rate per trade

Uses actual turnover from weekly snapshots to measure real portfolio churn.

Usage:
    python3 scripts/research/txn_cost_model.py
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "txn_cost_model"

ACCOUNT_USD = 500_000
TOP_N = 30

# --- Cost parameters (calibrated for small/mid-cap biotech) ---
# Spread model: spread_bps = base_bps + scale / sqrt(adv_usd)
SPREAD_BASE_BPS = 5.0
SPREAD_SCALE = 8000.0  # higher for illiquid names

# Market impact: impact_bps = eta * sqrt(participation_rate)
# participation_rate = trade_usd / adv_usd
IMPACT_ETA_BPS = 30.0  # Almgren-Chriss eta for small biotech

# Commission
COMMISSION_PER_TRADE_USD = 1.0  # negligible at $500k


def load_adv(snap_date: str, lookback_days: int = 20) -> Dict[str, float]:
    """Compute 20-day average daily volume in USD from price_history.csv.

    Returns {ticker: adv_usd}.
    """
    # Load relevant price/volume data
    target = date.fromisoformat(snap_date)
    cutoff = (target - timedelta(days=lookback_days * 2)).isoformat()

    vol_data: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            d = row.get("date", "")
            if d < cutoff or d > snap_date:
                continue
            t = row.get("ticker", "")
            close = row.get("close", "")
            volume = row.get("volume", "")
            if t and close and volume:
                try:
                    dollar_vol = float(close) * float(volume)
                    vol_data[t].append((d, dollar_vol))
                except ValueError:
                    pass

    adv: Dict[str, float] = {}
    for ticker, entries in vol_data.items():
        recent = sorted(entries, key=lambda x: x[0])[-lookback_days:]
        if recent:
            adv[ticker] = statistics.mean([v for _, v in recent])
    return adv


def spread_cost_bps(adv_usd: float) -> float:
    """Estimated half-spread in bps given ADV in USD."""
    if adv_usd <= 0:
        return 50.0  # penalty for no volume data
    return SPREAD_BASE_BPS + SPREAD_SCALE / math.sqrt(adv_usd)


def impact_cost_bps(trade_usd: float, adv_usd: float) -> float:
    """Market impact in bps using square-root model."""
    if adv_usd <= 0:
        return 50.0
    participation = trade_usd / adv_usd
    return IMPACT_ETA_BPS * math.sqrt(min(participation, 1.0))


def round_trip_cost_bps(trade_usd: float, adv_usd: float) -> float:
    """Total round-trip cost in bps (entry + exit)."""
    spread = spread_cost_bps(adv_usd)
    impact = impact_cost_bps(trade_usd, adv_usd)
    # Round trip = 2 × (half-spread + impact)
    return 2 * (spread + impact)


def get_weekly_snapshots(start: str = "2024-01-01") -> List[str]:
    """Get weekly snapshot dates (all available, not monthly)."""
    dates = []
    for d in SNAPSHOTS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if d.name < start:
            continue
        if (d / "rankings.csv").exists():
            dates.append(d.name)
    return sorted(dates)


def load_top_n(snap_date: str) -> List[str]:
    """Load top-N tickers from a snapshot."""
    path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    tickers = []
    with open(path) as f:
        for row in csv.DictReader(f):
            try:
                rank = int(float(row.get("actionable_rank", "9999")))
            except ValueError:
                continue
            if rank <= TOP_N:
                tickers.append(row["ticker"])
    return tickers


def main():
    print("Transaction Cost Model for DEM Top-30")
    print("=" * 60)

    dates = get_weekly_snapshots("2024-01-01")
    print(f"Weekly snapshots: {len(dates)} ({dates[0]} to {dates[-1]})")

    # --- Measure turnover ---
    prev_set: Optional[Set[str]] = None
    turnover_records: List[Dict[str, Any]] = []

    for snap_date in dates:
        current = load_top_n(snap_date)
        current_set = set(current)

        if prev_set is not None:
            entries = current_set - prev_set
            exits = prev_set - current_set
            one_way_turnover = len(entries) / TOP_N  # fraction of portfolio traded
            turnover_records.append(
                {
                    "date": snap_date,
                    "entries": len(entries),
                    "exits": len(exits),
                    "one_way_turnover": round(one_way_turnover, 4),
                    "names_in": sorted(entries),
                    "names_out": sorted(exits),
                }
            )

        prev_set = current_set

    if not turnover_records:
        print("No turnover data")
        return

    turnovers = [r["one_way_turnover"] for r in turnover_records]
    mean_weekly_turnover = statistics.mean(turnovers)
    annual_one_way = mean_weekly_turnover * 52
    annual_two_way = annual_one_way * 2  # buy + sell

    print("\n--- TURNOVER (EW Top-30, weekly rebalance) ---")
    print(f"  Mean weekly one-way:  {mean_weekly_turnover:.1%}")
    print(f"  Annual one-way:       {annual_one_way:.0%}")
    print(f"  Annual two-way:       {annual_two_way:.0%}")
    print(f"  Avg names traded/wk:  {statistics.mean([r['entries'] for r in turnover_records]):.1f}")

    # --- Estimate per-trade costs ---
    # Use a recent snapshot for ADV calibration
    print("\nLoading ADV for cost calibration...")
    calib_date = dates[-2] if len(dates) > 1 else dates[-1]
    adv = load_adv(calib_date)
    calib_tickers = load_top_n(calib_date)

    position_size = ACCOUNT_USD / TOP_N

    cost_per_name: List[Dict[str, Any]] = []
    for ticker in calib_tickers:
        adv_usd = adv.get(ticker, 0)
        rt_bps = round_trip_cost_bps(position_size, adv_usd)
        cost_per_name.append(
            {
                "ticker": ticker,
                "adv_usd": round(adv_usd),
                "position_usd": round(position_size),
                "spread_bps": round(spread_cost_bps(adv_usd), 1),
                "impact_bps": round(impact_cost_bps(position_size, adv_usd), 1),
                "round_trip_bps": round(rt_bps, 1),
            }
        )

    cost_per_name.sort(key=lambda x: -x["round_trip_bps"])

    print(f"\n--- PER-NAME COSTS (position=${position_size:,.0f}) ---")
    print(f"{'Ticker':<8} {'ADV $':>12} {'Spread':>8} {'Impact':>8} {'RT bps':>8}")
    print("-" * 48)
    for c in cost_per_name[:10]:
        print(
            f"{c['ticker']:<8} {c['adv_usd']:>12,} {c['spread_bps']:>7.1f} {c['impact_bps']:>7.1f} {c['round_trip_bps']:>7.1f}"
        )
    print(f"  ... ({len(cost_per_name)} total)")

    median_rt_bps = statistics.median([c["round_trip_bps"] for c in cost_per_name])
    mean_rt_bps = statistics.mean([c["round_trip_bps"] for c in cost_per_name])
    worst_rt_bps = max(c["round_trip_bps"] for c in cost_per_name)

    print(f"\n  Median RT cost:  {median_rt_bps:.1f} bps")
    print(f"  Mean RT cost:    {mean_rt_bps:.1f} bps")
    print(f"  Worst RT cost:   {worst_rt_bps:.1f} bps")

    # --- Annual cost drag ---
    # Each week, we turn over mean_weekly_turnover fraction of portfolio
    # Each turned-over name pays round-trip cost
    weekly_cost_drag_bps = mean_weekly_turnover * mean_rt_bps
    annual_cost_drag_bps = weekly_cost_drag_bps * 52
    annual_cost_drag_pct = annual_cost_drag_bps / 100

    print("\n--- ANNUAL COST DRAG (EW Top-30) ---")
    print(f"  Weekly drag:   {weekly_cost_drag_bps:.1f} bps")
    print(f"  Annual drag:   {annual_cost_drag_bps:.0f} bps  ({annual_cost_drag_pct:.2f}%)")
    print(f"  Dollar drag:   ${ACCOUNT_USD * annual_cost_drag_pct / 100:,.0f}/yr")

    # --- Rank-weighted incremental cost ---
    # Rank-weighting increases turnover because weight changes even when
    # membership doesn't change. Estimate ~1.5x turnover multiplier.
    rw_turnover_mult = 1.5
    rw_annual_drag_bps = annual_cost_drag_bps * rw_turnover_mult
    incremental_rw_cost_bps = rw_annual_drag_bps - annual_cost_drag_bps

    print("\n--- RANK-WEIGHTED INCREMENTAL COST ---")
    print(f"  RW turnover multiplier:   {rw_turnover_mult}x")
    print(f"  RW annual drag:           {rw_annual_drag_bps:.0f} bps")
    print(f"  Incremental vs EW:        {incremental_rw_cost_bps:.0f} bps")
    print(f"  → Ranker must add >{incremental_rw_cost_bps:.0f} bps/yr to justify RW over EW")

    # --- Promotion bar ---
    # Convert to monthly excess return needed
    monthly_bar_pp = incremental_rw_cost_bps / 100 / 12
    print(f"\n{'='*60}")
    print("PROMOTION BAR")
    print(f"{'='*60}")
    print("  Any ranker using rank-weighting must produce")
    print(f"  >{monthly_bar_pp:.3f}pp/month excess vs EW Top-30")
    print(f"  (>{incremental_rw_cost_bps:.0f} bps/year) net of costs to justify adoption.")
    print(f"  At current turnover ({annual_one_way:.0%} annual one-way), EW is the")
    print("  default unless ranker clears this bar with t>1.5.")

    # --- Turnover distribution ---
    print("\n--- TURNOVER DISTRIBUTION ---")
    pctiles = [0, 25, 50, 75, 90, 100]
    sorted_t = sorted(turnovers)
    for p in pctiles:
        idx = min(int(len(sorted_t) * p / 100), len(sorted_t) - 1)
        print(f"  P{p:<3}: {sorted_t[idx]:.1%} one-way ({sorted_t[idx] * TOP_N:.0f} names)")

    # --- Save ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    packet = {
        "schema": "txn_cost_model.v1",
        "account_usd": ACCOUNT_USD,
        "top_n": TOP_N,
        "rebalance_cadence": "weekly",
        "n_weeks": len(turnover_records),
        "date_range": [turnover_records[0]["date"], turnover_records[-1]["date"]],
        "turnover": {
            "mean_weekly_one_way": round(mean_weekly_turnover, 4),
            "annual_one_way": round(annual_one_way, 2),
            "annual_two_way": round(annual_two_way, 2),
        },
        "costs": {
            "median_rt_bps": round(median_rt_bps, 1),
            "mean_rt_bps": round(mean_rt_bps, 1),
            "annual_ew_drag_bps": round(annual_cost_drag_bps),
            "annual_rw_drag_bps": round(rw_annual_drag_bps),
            "incremental_rw_bps": round(incremental_rw_cost_bps),
        },
        "promotion_bar": {
            "monthly_excess_pp": round(monthly_bar_pp, 3),
            "annual_excess_bps": round(incremental_rw_cost_bps),
            "required_t_stat": 1.5,
        },
        "parameters": {
            "spread_base_bps": SPREAD_BASE_BPS,
            "spread_scale": SPREAD_SCALE,
            "impact_eta_bps": IMPACT_ETA_BPS,
            "rw_turnover_multiplier": rw_turnover_mult,
        },
        "per_name_costs": cost_per_name,
        "weekly_turnover": turnover_records,
    }
    out_path = OUTPUT_DIR / "txn_cost_model.json"
    with open(out_path, "w") as f:
        json.dump(packet, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
