#!/usr/bin/env python3
"""DEM selection benchmark — monthly granularity.

Measures whether being in the DEM top-30 predicts forward excess returns
vs the biotech universe (XBI) and vs all eligible names.

Outputs:
  - Monthly IC of actionable_rank vs forward returns (20d, 63d)
  - Top-30 EW vs XBI excess return per month
  - Top-30 EW vs eligible-universe EW per month
  - Hit rate, IR, cumulative excess

Usage:
    python3 scripts/research/selection_benchmark.py
    python3 scripts/research/selection_benchmark.py --start 2023-01-01
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "selection_benchmark"
IPO_DATES_PATH = PROJECT_ROOT / "production_data" / "ipo_dates.json"

# Module-level PIT state
_ipo_dates: Dict[str, str] = {}
_pit_mode: str = "off"


def _load_ipo_dates() -> Dict[str, str]:
    """Load ipo_dates.json → flat {ticker: first_price_date}."""
    if not IPO_DATES_PATH.exists():
        return {}
    with open(IPO_DATES_PATH) as f:
        raw = json.load(f)
    tickers = raw.get("tickers", {})
    return {t: v.get("first_price_date", "") for t, v in tickers.items()}


def _filter_pit(rows: List[Dict[str, str]], snap_date: str) -> List[Dict[str, str]]:
    """Remove pre-IPO tickers when PIT mode is active."""
    if _pit_mode == "off" or not _ipo_dates:
        return rows
    return [r for r in rows if _ipo_dates.get(r.get("ticker", ""), "0000") <= snap_date]


def load_prices() -> Dict[str, Dict[str, float]]:
    """Load price_history.csv → {ticker: {date_str: close}}."""
    series: Dict[str, Dict[str, float]] = {}
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return series


def forward_return(prices: Dict[str, float], snap_date: str, horizon_days: int) -> Optional[float]:
    """Forward return from snap_date over horizon trading days."""
    sorted_dates = sorted(prices.keys())
    # Find start index
    candidates = [d for d in sorted_dates if d >= snap_date]
    if not candidates:
        return None
    idx = sorted_dates.index(candidates[0])
    target_idx = idx + horizon_days
    if target_idx >= len(sorted_dates):
        return None
    p0 = prices.get(sorted_dates[idx])
    p1 = prices.get(sorted_dates[target_idx])
    if p0 and p1 and p0 > 0:
        return (p1 - p0) / p0
    return None


def spearman_ic(x: List[float], y: List[float]) -> Optional[float]:
    """Spearman rank correlation."""
    n = len(x)
    if n < 5:
        return None

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vals[indexed[j + 1]] == vals[indexed[j]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k]] = avg
            i = j + 1
        return ranks

    rx = _rank(x)
    ry = _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx < 1e-9 or dy < 1e-9:
        return None
    return num / (dx * dy)


def get_snapshot_dates(start: str) -> List[str]:
    """Get sorted snapshot dates with rankings.csv, filtered by start."""
    dates = []
    for d in SNAPSHOTS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if d.name < start:
            continue
        if (d / "rankings.csv").exists():
            dates.append(d.name)
    return sorted(dates)


def load_rankings(snap_date: str) -> List[Dict[str, str]]:
    path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return _filter_pit(rows, snap_date)


def dedupe_monthly(dates: List[str]) -> List[str]:
    """Keep one snapshot per calendar month (last available)."""
    by_month: Dict[str, str] = {}
    for d in dates:
        month_key = d[:7]  # YYYY-MM
        by_month[month_key] = d  # last wins since sorted
    return sorted(by_month.values())


def main():
    parser = argparse.ArgumentParser(description="DEM selection benchmark")
    parser.add_argument("--start", default="2020-06-01", help="Start date for evaluation")
    parser.add_argument("--monthly", action="store_true", default=True, help="One snapshot per month")
    parser.add_argument(
        "--pit-mode",
        choices=["off", "survivorship", "full"],
        default="off",
        help="PIT filtering: off/survivorship/full (default: off)",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=None,
        help="Override snapshot directory (default: data/snapshots)",
    )
    args = parser.parse_args()

    # Initialize PIT state
    global _pit_mode, _ipo_dates, SNAPSHOTS_DIR
    _pit_mode = args.pit_mode
    if _pit_mode != "off":
        _ipo_dates = _load_ipo_dates()
        print(f"PIT mode: {_pit_mode} ({len(_ipo_dates)} IPO dates loaded)")
    if args.snapshot_dir is not None:
        SNAPSHOTS_DIR = args.snapshot_dir.resolve()
        print(f"Using snapshot dir: {SNAPSHOTS_DIR}")

    horizons = [20, 63]
    top_n = 30

    print("Loading prices...")
    prices = load_prices()
    xbi_prices = prices.get("XBI", {})
    print(f"  {len(prices)} tickers, XBI dates: {len(xbi_prices)}")

    all_dates = get_snapshot_dates(args.start)
    if args.monthly:
        eval_dates = dedupe_monthly(all_dates)
    else:
        eval_dates = all_dates
    print(f"Evaluation dates: {len(eval_dates)} ({eval_dates[0]} to {eval_dates[-1]})")

    # --- Per-date evaluation ---
    monthly_records: List[Dict[str, Any]] = []

    # IC tracking
    ic_by_horizon: Dict[int, List[float]] = {h: [] for h in horizons}

    for snap_date in eval_dates:
        rows = load_rankings(snap_date)

        # Parse eligible and top-N
        eligible = []
        top_set = []
        for r in rows:
            rank_str = r.get("actionable_rank", "")
            elig = r.get("eligible", "")
            ticker = r.get("ticker", "")
            if not ticker:
                continue

            try:
                rank = int(float(rank_str)) if rank_str else 9999
            except ValueError:
                rank = 9999

            is_eligible = elig in ("1", "True", "true")
            if is_eligible:
                eligible.append({"ticker": ticker, "rank": rank})
            if rank <= top_n:
                top_set.append({"ticker": ticker, "rank": rank})

        if len(top_set) < 10:
            continue

        record: Dict[str, Any] = {
            "date": snap_date,
            "n_eligible": len(eligible),
            "n_top": len(top_set),
        }

        for horizon in horizons:
            h_key = f"h{horizon}"

            # Top-N returns
            top_returns = []
            for t in top_set:
                ret = forward_return(prices.get(t["ticker"], {}), snap_date, horizon)
                if ret is not None:
                    top_returns.append(ret)

            # Eligible universe returns
            elig_returns = []
            for t in eligible:
                ret = forward_return(prices.get(t["ticker"], {}), snap_date, horizon)
                if ret is not None:
                    elig_returns.append(ret)

            # XBI return
            xbi_ret = forward_return(xbi_prices, snap_date, horizon)

            if len(top_returns) < 10 or not elig_returns:
                continue

            top_ew = statistics.mean(top_returns)
            elig_ew = statistics.mean(elig_returns)

            record[f"{h_key}_top_ew"] = round(top_ew * 100, 2)
            record[f"{h_key}_elig_ew"] = round(elig_ew * 100, 2)
            record[f"{h_key}_excess_vs_elig"] = round((top_ew - elig_ew) * 100, 2)

            if xbi_ret is not None:
                record[f"{h_key}_xbi"] = round(xbi_ret * 100, 2)
                record[f"{h_key}_excess_vs_xbi"] = round((top_ew - xbi_ret) * 100, 2)

            record[f"{h_key}_n_top"] = len(top_returns)
            record[f"{h_key}_n_elig"] = len(elig_returns)

            # IC: rank (lower=better) vs forward return (higher=better) → expect negative IC
            # We negate rank so higher=better aligns with higher return → expect positive IC
            ranks_neg = []
            returns_for_ic = []
            for t in eligible:
                ret = forward_return(prices.get(t["ticker"], {}), snap_date, horizon)
                if ret is not None:
                    ranks_neg.append(-t["rank"])
                    returns_for_ic.append(ret)

            ic = spearman_ic(ranks_neg, returns_for_ic)
            if ic is not None:
                ic_by_horizon[horizon].append(ic)
                record[f"{h_key}_ic"] = round(ic, 4)

        monthly_records.append(record)

    # --- Aggregate ---
    print(f"\n{'='*80}")
    print(f"DEM SELECTION BENCHMARK — {len(monthly_records)} months evaluated")
    print(f"{'='*80}\n")

    for horizon in horizons:
        h_key = f"h{horizon}"
        excess_vs_elig = [r[f"{h_key}_excess_vs_elig"] for r in monthly_records if f"{h_key}_excess_vs_elig" in r]
        excess_vs_xbi = [r[f"{h_key}_excess_vs_xbi"] for r in monthly_records if f"{h_key}_excess_vs_xbi" in r]
        ics = ic_by_horizon[horizon]

        print(f"--- {horizon}d horizon ---")

        if excess_vs_elig:
            mean_ex = statistics.mean(excess_vs_elig)
            hit = sum(1 for x in excess_vs_elig if x > 0) / len(excess_vs_elig)
            std_ex = statistics.stdev(excess_vs_elig) if len(excess_vs_elig) > 1 else 0
            ir = mean_ex / std_ex if std_ex > 0 else 0
            cum_ex = sum(excess_vs_elig)
            t_stat = mean_ex / (std_ex / len(excess_vs_elig) ** 0.5) if std_ex > 0 else 0
            print("  Top-30 vs Eligible EW:")
            print(f"    Mean excess:  {mean_ex:+.2f}pp/mo")
            print(f"    Cumulative:   {cum_ex:+.1f}pp")
            print(f"    Hit rate:     {hit:.1%}")
            print(f"    IR:           {ir:.2f}")
            print(f"    t-stat:       {t_stat:.2f}")
            print(f"    N months:     {len(excess_vs_elig)}")

        if excess_vs_xbi:
            mean_xbi = statistics.mean(excess_vs_xbi)
            hit_xbi = sum(1 for x in excess_vs_xbi if x > 0) / len(excess_vs_xbi)
            std_xbi = statistics.stdev(excess_vs_xbi) if len(excess_vs_xbi) > 1 else 0
            ir_xbi = mean_xbi / std_xbi if std_xbi > 0 else 0
            cum_xbi = sum(excess_vs_xbi)
            t_xbi = mean_xbi / (std_xbi / len(excess_vs_xbi) ** 0.5) if std_xbi > 0 else 0
            print("  Top-30 vs XBI:")
            print(f"    Mean excess:  {mean_xbi:+.2f}pp/mo")
            print(f"    Cumulative:   {cum_xbi:+.1f}pp")
            print(f"    Hit rate:     {hit_xbi:.1%}")
            print(f"    IR:           {ir_xbi:.2f}")
            print(f"    t-stat:       {t_xbi:.2f}")
            print(f"    N months:     {len(excess_vs_xbi)}")

        if ics:
            mean_ic = statistics.mean(ics)
            std_ic = statistics.stdev(ics) if len(ics) > 1 else 0
            pos_pct = sum(1 for x in ics if x > 0) / len(ics)
            t_ic = mean_ic / (std_ic / len(ics) ** 0.5) if std_ic > 0 else 0
            print("  Rank IC (neg_rank vs return):")
            print(f"    Mean IC:      {mean_ic:+.4f}")
            print(f"    Positive%:    {pos_pct:.1%}")
            print(f"    t-stat:       {t_ic:.2f}")
            print(f"    N months:     {len(ics)}")
        print()

    # --- Yearly breakdown ---
    print(f"{'='*80}")
    print("YEARLY BREAKDOWN — Top-30 EW excess vs Eligible EW (63d)")
    print(f"{'='*80}")
    by_year: Dict[str, List[float]] = defaultdict(list)
    for r in monthly_records:
        if "h63_excess_vs_elig" in r:
            year = r["date"][:4]
            by_year[year].append(r["h63_excess_vs_elig"])

    print(f"{'Year':>6} {'N':>4} {'Mean':>8} {'Cum':>8} {'Hit%':>6} {'IR':>6}")
    print("-" * 42)
    for year in sorted(by_year.keys()):
        vals = by_year[year]
        mean_v = statistics.mean(vals)
        cum_v = sum(vals)
        hit_v = sum(1 for x in vals if x > 0) / len(vals)
        std_v = statistics.stdev(vals) if len(vals) > 1 else 0
        ir_v = mean_v / std_v if std_v > 0 else 0
        print(f"{year:>6} {len(vals):>4} {mean_v:>+7.2f} {cum_v:>+7.1f} {hit_v:>5.0%} {ir_v:>+5.2f}")

    # --- Regime split ---
    print(f"\n{'='*80}")
    print("REGIME SPLIT — by XBI 63d return sign")
    print(f"{'='*80}")
    bear_excess = []
    bull_excess = []
    for r in monthly_records:
        if "h63_excess_vs_xbi" in r and "h63_xbi" in r:
            if r["h63_xbi"] < 0:
                bear_excess.append(r["h63_excess_vs_xbi"])
            else:
                bull_excess.append(r["h63_excess_vs_xbi"])

    for label, vals in [("Bear (XBI<0)", bear_excess), ("Bull (XBI>=0)", bull_excess)]:
        if vals:
            mean_v = statistics.mean(vals)
            hit_v = sum(1 for x in vals if x > 0) / len(vals)
            std_v = statistics.stdev(vals) if len(vals) > 1 else 0
            ir_v = mean_v / std_v if std_v > 0 else 0
            print(f"  {label}: mean={mean_v:+.2f}pp, hit={hit_v:.0%}, IR={ir_v:+.2f}, N={len(vals)}")

    # --- Save ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _pit_version = 2 if _pit_mode != "off" else 1
    packet = {
        "schema": "selection_benchmark.v1",
        "pseudo_pit_version": _pit_version,
        "pit_mode": _pit_mode,
        "start_date": args.start,
        "n_months": len(monthly_records),
        "date_range": [monthly_records[0]["date"], monthly_records[-1]["date"]] if monthly_records else [],
        "summary": {},
        "per_month": monthly_records,
    }

    for horizon in horizons:
        h_key = f"h{horizon}"
        excess_vs_elig = [r[f"{h_key}_excess_vs_elig"] for r in monthly_records if f"{h_key}_excess_vs_elig" in r]
        ics = ic_by_horizon[horizon]
        if excess_vs_elig:
            std_ex = statistics.stdev(excess_vs_elig) if len(excess_vs_elig) > 1 else 0
            mean_ex = statistics.mean(excess_vs_elig)
            packet["summary"][h_key] = {
                "mean_excess_vs_elig_pp": round(mean_ex, 2),
                "cum_excess_pp": round(sum(excess_vs_elig), 1),
                "hit_rate": round(sum(1 for x in excess_vs_elig if x > 0) / len(excess_vs_elig), 3),
                "ir": round(mean_ex / std_ex, 2) if std_ex > 0 else None,
                "t_stat": round(mean_ex / (std_ex / len(excess_vs_elig) ** 0.5), 2) if std_ex > 0 else None,
                "n_months": len(excess_vs_elig),
            }
        if ics:
            std_ic = statistics.stdev(ics) if len(ics) > 1 else 0
            mean_ic = statistics.mean(ics)
            packet["summary"][f"{h_key}_ic"] = {
                "mean_ic": round(mean_ic, 4),
                "positive_pct": round(sum(1 for x in ics if x > 0) / len(ics), 3),
                "t_stat": round(mean_ic / (std_ic / len(ics) ** 0.5), 2) if std_ic > 0 else None,
            }

    out_path = OUTPUT_DIR / "selection_benchmark.json"
    with open(out_path, "w") as f:
        json.dump(packet, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
