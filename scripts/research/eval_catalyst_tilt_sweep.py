#!/usr/bin/env python3
"""Catalyst-tilt sweep: analytical L3 sizing evaluation.

Since catalyst tilt is a pure L3 sizing change (multiplies target_weight_pct
by bucket-specific multipliers without changing membership or sort order),
we can evaluate all grid points analytically from existing baseline snapshots.

For each snapshot date:
  1. Read rankings.csv (has catalyst_strength and target_weight_pct)
  2. For each tilt variant, recompute weights: w' = w * tilt_mult[bucket]
  3. Re-normalize weights to sum to 100%
  4. Compute weighted forward returns vs baseline (equal-weight and original weights)

Usage:
    python scripts/research/eval_catalyst_tilt_sweep.py \
        --snapshot-root data/snapshots \
        --price-csv production_data/price_history.csv \
        --out-dir output/research/catalyst_tilt_sweep \
        --date-from 2025-06-01 --date-to 2025-12-31 \
        --horizons 63,84 --top-k 20
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Grid definition ──────────────────────────────────────────────────────────

NEAR_VALUES = [1.05, 1.10]
MID_VALUES = [1.02, 1.05]
FAR_VALUES = [0.95, 1.00]
MISSING_VALUES = [0.90, 0.95]

BASELINE_MULTS = {"near": 1.0, "mid": 1.0, "far": 1.0, "missing": 1.0}


def _build_grid() -> List[Tuple[str, Dict[str, float]]]:
    """Build all grid combinations. Returns [(label, {bucket: mult}), ...]."""
    variants = []
    for near, mid, far, miss in itertools.product(NEAR_VALUES, MID_VALUES, FAR_VALUES, MISSING_VALUES):
        label = f"N{near:.2f}_M{mid:.2f}_F{far:.2f}_X{miss:.2f}"
        mults = {"near": near, "mid": mid, "far": far, "missing": miss}
        variants.append((label, mults))
    return variants


# ── Price loading ────────────────────────────────────────────────────────────


def _load_prices(price_csv: Path) -> Dict[str, Dict[str, float]]:
    """Load price_history.csv → {ticker: {date: close}}."""
    prices: Dict[str, Dict[str, float]] = {}
    with open(price_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker") or row.get("Ticker") or ""
            date_str = row.get("date") or row.get("Date") or ""
            close_str = row.get("close") or row.get("Close") or ""
            if ticker and date_str and close_str:
                try:
                    prices.setdefault(ticker, {})[date_str] = float(close_str)
                except ValueError:
                    pass
    return prices


def _sorted_dates_from_prices(prices: Dict[str, Dict[str, float]]) -> List[str]:
    all_dates = set()
    for ticker_prices in prices.values():
        all_dates.update(ticker_prices.keys())
    return sorted(all_dates)


def _forward_return(
    ticker_prices: Dict[str, float],
    sorted_dates: List[str],
    snap_date: str,
    horizon: int,
) -> Optional[float]:
    import bisect

    idx = bisect.bisect_left(sorted_dates, snap_date)
    if idx >= len(sorted_dates) or sorted_dates[idx] != snap_date:
        return None
    target = idx + horizon
    if target >= len(sorted_dates):
        return None
    p0 = ticker_prices.get(snap_date)
    p1 = ticker_prices.get(sorted_dates[target])
    if p0 is None or p1 is None or p0 <= 0 or p1 <= 0:
        return None
    return p1 / p0 - 1.0


# ── Snapshot reading ─────────────────────────────────────────────────────────


def _read_holdings(rankings_csv: Path, top_k: int) -> List[Dict[str, object]]:
    """Read top-K eligible holdings with catalyst_strength and weight."""
    rows = []
    with open(rankings_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("eligible", "1").lower() in ("false", "0", "no"):
                continue
            try:
                rank = int(row.get("actionable_rank", 9999))
            except (ValueError, TypeError):
                continue
            ticker = row.get("ticker", "")
            try:
                weight = float(row.get("target_weight_pct", 0))
            except (ValueError, TypeError):
                weight = 0.0
            strength = row.get("catalyst_strength", "missing").lower()
            if strength not in ("near", "mid", "far", "missing"):
                strength = "missing"
            if ticker and weight > 0:
                rows.append({"rank": rank, "ticker": ticker, "weight": weight, "bucket": strength})
    rows.sort(key=lambda x: x["rank"])
    return rows[:top_k]


def _apply_tilt(holdings: List[Dict[str, object]], mults: Dict[str, float]) -> List[Tuple[str, float]]:
    """Apply tilt multipliers and re-normalize weights."""
    tilted = []
    for h in holdings:
        new_w = h["weight"] * mults.get(h["bucket"], 1.0)
        tilted.append((h["ticker"], new_w))
    total = sum(w for _, w in tilted)
    if total <= 0:
        return tilted
    # Normalize to same total as original
    orig_total = sum(h["weight"] for h in holdings)
    factor = orig_total / total
    return [(t, w * factor) for t, w in tilted]


# ── Sweep engine ─────────────────────────────────────────────────────────────


def _discover_dates(snapshot_root: Path, date_from: str, date_to: str) -> List[str]:
    import re

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    all_dirs = sorted(d.name for d in snapshot_root.iterdir() if d.is_dir() and date_re.match(d.name))
    return [d for d in all_dirs if date_from <= d <= date_to]


def run_sweep(
    snapshot_root: Path,
    price_csv: Path,
    dates: List[str],
    horizons: List[int],
    top_k: int,
) -> Dict[str, Dict[int, Dict[str, float]]]:
    """Run analytical tilt sweep.

    Returns {variant_label: {horizon: {metric: value}}}.
    """
    print(f"Loading prices from {price_csv}...")
    prices = _load_prices(price_csv)
    sorted_price_dates = _sorted_dates_from_prices(prices)
    print(f"  {len(prices)} tickers, {len(sorted_price_dates)} dates")

    grid = _build_grid()
    # Add baseline (no tilt)
    all_variants = [("BASELINE", BASELINE_MULTS)] + grid
    print(f"\nGrid: {len(grid)} tilt variants + 1 baseline = {len(all_variants)} total")

    # Pre-load all holdings and forward returns
    print(f"Loading {len(dates)} snapshots...")
    snap_data = {}  # {date: holdings}
    fwd_rets_cache = {}  # {date: {ticker: {horizon: ret}}}

    for snap_date in dates:
        csv_path = snapshot_root / snap_date / "rankings.csv"
        if not csv_path.exists():
            continue
        holdings = _read_holdings(csv_path, top_k)
        if not holdings:
            continue
        snap_data[snap_date] = holdings

        # Precompute forward returns for all tickers in this snapshot
        tickers = {h["ticker"] for h in holdings}
        date_rets = {}
        for ticker in tickers:
            if ticker not in prices:
                continue
            for h in horizons:
                ret = _forward_return(prices[ticker], sorted_price_dates, snap_date, h)
                if ret is not None:
                    date_rets.setdefault(ticker, {})[h] = ret
        fwd_rets_cache[snap_date] = date_rets

    valid_dates = sorted(snap_data.keys())
    print(f"  {len(valid_dates)} valid snapshots")

    # Evaluate each variant
    results: Dict[str, Dict[int, Dict[str, float]]] = {}
    for label, mults in all_variants:
        horizon_data: Dict[int, List[float]] = {h: [] for h in horizons}
        bucket_alloc: Dict[str, List[float]] = {"near": [], "mid": [], "far": [], "missing": []}
        turnover_vs_baseline: List[float] = []

        for snap_date in valid_dates:
            holdings = snap_data[snap_date]
            date_rets = fwd_rets_cache[snap_date]

            # Apply tilt
            tilted = _apply_tilt(holdings, mults)
            baseline_tilted = _apply_tilt(holdings, BASELINE_MULTS)

            # Track bucket allocation (% of weight per bucket)
            total_w = sum(w for _, w in tilted)
            if total_w > 0:
                for h_item in holdings:
                    bucket = h_item["bucket"]
                    ticker_w = next((w for t, w in tilted if t == h_item["ticker"]), 0)
                    bucket_alloc.setdefault(bucket, []).append(ticker_w / total_w)

            # Turnover: sum of absolute weight differences vs baseline
            base_weights = {t: w for t, w in baseline_tilted}
            tilt_weights = {t: w for t, w in tilted}
            all_tickers = set(base_weights) | set(tilt_weights)
            turnover = sum(abs(tilt_weights.get(t, 0) - base_weights.get(t, 0)) for t in all_tickers)
            turnover_vs_baseline.append(turnover)

            for h in horizons:
                # Weighted return
                pairs = [(w, date_rets.get(t, {}).get(h)) for t, w in tilted if date_rets.get(t, {}).get(h) is not None]
                if not pairs:
                    continue
                total_w_h = sum(w for w, _ in pairs)
                if total_w_h <= 0:
                    continue
                w_ret = sum(w * r for w, r in pairs) / total_w_h
                horizon_data[h].append(w_ret)

        # Summarize
        variant_summary: Dict[int, Dict[str, float]] = {}
        for h in horizons:
            rets = horizon_data[h]
            if not rets:
                continue
            entry = {
                "n_dates": len(rets),
                "mean_ret": statistics.mean(rets),
                "median_ret": statistics.median(rets),
            }
            if len(rets) >= 3:
                entry["std_ret"] = statistics.stdev(rets)
            variant_summary[h] = entry

        # Add turnover and bucket alloc to first horizon entry
        if turnover_vs_baseline and horizons and horizons[0] in variant_summary:
            variant_summary[horizons[0]]["mean_turnover_pct"] = statistics.mean(turnover_vs_baseline)

        results[label] = variant_summary

    return results


def _print_results(
    results: Dict[str, Dict[int, Dict[str, float]]],
    horizons: List[int],
    out_dir: Path,
):
    """Print formatted results table and save JSON."""
    baseline = results.get("BASELINE", {})

    for h in horizons:
        b = baseline.get(h, {})
        b_ret = b.get("mean_ret", 0)

        print(f"\n{'='*90}")
        print(f"  Horizon: {h}d  |  Baseline mean return: {b_ret:+.3%}  |  N dates: {b.get('n_dates', 0)}")
        print(f"{'='*90}")
        print(f"  {'Variant':<36s}  {'MeanRet':>9s}  {'Delta':>9s}  {'Median':>9s}  {'StdDev':>8s}  {'Turnover':>9s}")
        print(f"  {'-'*36}  {'-'*9}  {'-'*9}  {'-'*9}  {'-'*8}  {'-'*9}")

        # Sort by delta descending
        rows = []
        for label, variant in sorted(results.items()):
            if label == "BASELINE":
                continue
            d = variant.get(h, {})
            if not d:
                continue
            delta = d.get("mean_ret", 0) - b_ret
            rows.append((label, d, delta))

        rows.sort(key=lambda x: -x[2])

        for label, d, delta in rows:
            turnover_str = (
                f"{d.get('mean_turnover_pct', 0):>8.2f}%"
                if "mean_turnover_pct" in d or h == horizons[0]
                else "      N/A"
            )
            # Get turnover from first horizon if not in current
            if h != horizons[0] and "mean_turnover_pct" not in d:
                first_h = results.get(label, {}).get(horizons[0], {})
                if "mean_turnover_pct" in first_h:
                    turnover_str = f"{first_h['mean_turnover_pct']:>8.2f}%"

            print(
                f"  {label:<36s}  {d['mean_ret']:>+9.3%}  {delta:>+9.3%}  "
                f"{d.get('median_ret', 0):>+9.3%}  {d.get('std_ret', 0):>8.3%}  {turnover_str}"
            )

    # Promotability assessment
    print(f"\n{'='*90}")
    print("  PROMOTABILITY ASSESSMENT")
    print(f"{'='*90}")

    best_label = None
    best_delta = -999
    for h in horizons:
        b_ret = baseline.get(h, {}).get("mean_ret", 0)
        for label, variant in results.items():
            if label == "BASELINE":
                continue
            d = variant.get(h, {})
            delta = d.get("mean_ret", 0) - b_ret
            if delta > best_delta:
                best_delta = delta
                best_label = label

    if best_label:
        print(f"\n  Best variant: {best_label}")
        for h in horizons:
            b_ret = baseline.get(h, {}).get("mean_ret", 0)
            d = results[best_label].get(h, {})
            delta = d.get("mean_ret", 0) - b_ret
            n = d.get("n_dates", 0)
            std = d.get("std_ret", 0)
            t_stat = delta / (std / n**0.5) if std > 0 and n > 1 else 0
            print(f"    {h}d: delta={delta:+.3%}, t={t_stat:.2f}, n={n}")

        # Check if any variant beats baseline at all horizons
        all_positive = all(
            results[best_label].get(h, {}).get("mean_ret", 0) > baseline.get(h, {}).get("mean_ret", 0) for h in horizons
        )
        if all_positive and best_delta > 0.001:
            print("\n  VERDICT: PROMOTABLE — positive delta at all horizons")
        elif best_delta > 0:
            print("\n  VERDICT: MARGINAL — positive at some horizons, needs more data")
        else:
            print("\n  VERDICT: NOT PROMOTABLE — no variant beats baseline")
    else:
        print("\n  VERDICT: NOT PROMOTABLE — no valid variants")

    # Save JSON
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "catalyst_tilt_sweep.json"
    # Convert int keys to str for JSON
    json_results = {}
    for label, variant in results.items():
        json_results[label] = {str(h): d for h, d in variant.items()}
    with open(out_path, "w") as f:
        json.dump(json_results, f, indent=2)
    print(f"\n  Full results: {out_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot-root", default="data/snapshots", help="Baseline snapshot root")
    parser.add_argument(
        "--price-csv",
        default="production_data/price_history.csv",
        help="Price history CSV",
    )
    parser.add_argument(
        "--out-dir",
        default="output/research/catalyst_tilt_sweep",
        help="Output directory",
    )
    parser.add_argument("--date-from", default="2025-06-01", help="Start date")
    parser.add_argument("--date-to", default="2025-12-31", help="End date")
    parser.add_argument("--horizons", default="63,84", help="Forward-return horizons")
    parser.add_argument("--top-k", type=int, default=20, help="Top-K holdings")
    args = parser.parse_args()

    snapshot_root = Path(args.snapshot_root)
    price_csv = Path(args.price_csv)
    out_dir = Path(args.out_dir)
    horizons = [int(h) for h in args.horizons.split(",")]

    dates = _discover_dates(snapshot_root, args.date_from, args.date_to)
    print(f"Catalyst tilt sweep: {len(dates)} dates, {args.date_from} to {args.date_to}")
    print(f"  Grid: NEAR={NEAR_VALUES} × MID={MID_VALUES} × FAR={FAR_VALUES} × MISSING={MISSING_VALUES}")
    print(f"  = {len(NEAR_VALUES)*len(MID_VALUES)*len(FAR_VALUES)*len(MISSING_VALUES)} variants + baseline")
    print(f"  Horizons: {horizons}, Top-K: {args.top_k}")

    results = run_sweep(snapshot_root, price_csv, dates, horizons, args.top_k)
    _print_results(results, horizons, out_dir)


if __name__ == "__main__":
    main()
