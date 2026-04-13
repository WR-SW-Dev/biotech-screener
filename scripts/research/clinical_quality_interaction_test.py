#!/usr/bin/env python3
"""Clinical Quality × Coinvest interaction test — Spec 057 validation.

Tests whether clinical_quality_score adds value as a filter/modifier
within the coinvest-selected cohort.

Five analyses:
  1. Standalone IC of clinical_quality_score (baseline)
  2. Decile spread (top vs bottom decile returns)
  3. 2×2 interaction grid: coinvest quintile × clinical quality quintile
  4. Conditional IC: clinical quality WITHIN top coinvest quintile
  5. Filter value: high coinvest + high quality vs high coinvest + low quality

Uses PIT snapshots (data/snapshots_pit/) with forward returns from
production_data/price_history.csv. Clinical quality is computed fresh
at each snapshot date from trial_records.json with PIT enforcement.

Usage:
    python scripts/research/clinical_quality_interaction_test.py [--from DATE] [--to DATE]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.clinical_quality_score import compute_clinical_quality_scores
from scripts.eval_forward_returns import (
    compute_forward_return,
    discover_snapshot_dates,
    load_price_series,
    load_rankings,
    resolve_trade_date,
    spearman_ic,
)

HORIZONS = [5, 20, 63]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        v = float(val)
        return v if v == v else None  # NaN check
    except (ValueError, TypeError):
        return None


def _quintile(vals: List[float], v: float) -> int:
    """Assign value to quintile 1-5 (1=lowest, 5=highest)."""
    s = sorted(vals)
    n = len(s)
    for q in range(1, 6):
        threshold_idx = min(int(n * q / 5), n - 1)
        if v <= s[threshold_idx]:
            return q
    return 5


def _decile(vals: List[float], v: float) -> int:
    """Assign value to decile 1-10 (1=lowest, 10=highest)."""
    s = sorted(vals)
    n = len(s)
    for d in range(1, 11):
        threshold_idx = min(int(n * d / 10), n - 1)
        if v <= s[threshold_idx]:
            return d
    return 10


def _ic_summary(ics: List[float]) -> Dict[str, Any]:
    if not ics:
        return {"mean_ic": None, "t_stat": None, "hit_rate": None, "n": 0}
    m = statistics.mean(ics)
    s = statistics.stdev(ics) if len(ics) >= 2 else 0
    t = m / (s / math.sqrt(len(ics))) if s > 0 else 0
    hr = sum(1 for ic in ics if ic > 0) / len(ics)
    return {
        "mean_ic": round(m, 4),
        "t_stat": round(t, 2),
        "hit_rate": round(hr, 3),
        "n": len(ics),
    }


def _grid_summary(cells: Dict[Tuple[int, int], List[float]]) -> List[Dict[str, Any]]:
    rows = []
    for (cq_q, cv_q), rets in sorted(cells.items()):
        if rets:
            rows.append(
                {
                    "clinical_q": cq_q,
                    "coinvest_q": cv_q,
                    "mean_ret": round(statistics.mean(rets) * 100, 2),  # pct
                    "median_ret": round(sorted(rets)[len(rets) // 2] * 100, 2),
                    "n_obs": len(rets),
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def run_interaction(
    snapshot_root: Path,
    price_csv: Path,
    trial_records_path: Path,
    date_from: str = "2022-01-01",
    date_to: str = "2026-03-31",
) -> Dict[str, Any]:
    # Load trial records once (PIT filtering happens per-snapshot inside the scorer)
    with open(trial_records_path) as f:
        trial_records = json.load(f)

    snap_dates = discover_snapshot_dates(snapshot_root, date_from, date_to)
    prices = load_price_series(price_csv)

    all_dates_set: set = set()
    for tp in prices.values():
        all_dates_set.update(tp.keys())
    sorted_dates = sorted(all_dates_set)

    # Accumulators
    # 1. Standalone IC
    standalone_ic: Dict[int, List[float]] = defaultdict(list)

    # 2. Decile spread
    decile_spreads: Dict[int, List[float]] = defaultdict(list)

    # 3. 2D grid: (clinical_q, coinvest_q) → [fwd_ret]
    grid_returns: Dict[int, Dict[Tuple[int, int], List[float]]] = {h: defaultdict(list) for h in HORIZONS}

    # 4. Conditional IC: clinical quality within top coinvest quintile
    cq_in_top_coinvest_ic: Dict[int, List[float]] = defaultdict(list)

    # 5. Filter comparison: high coinvest + high quality vs high coinvest + low quality
    filter_high_high: Dict[int, List[float]] = defaultdict(list)
    filter_high_low: Dict[int, List[float]] = defaultdict(list)

    # Coinvest standalone IC for reference
    coinvest_ic: Dict[int, List[float]] = defaultdict(list)

    n_dates = 0
    n_tickers_total = 0

    for snap_date in snap_dates:
        trade_date = resolve_trade_date(sorted_dates, snap_date, "next_trading_day")
        if not trade_date:
            continue

        rankings = load_rankings(snapshot_root / snap_date)
        if not rankings:
            continue

        # Extract coinvest_score_z from snapshot
        coinvest_map: Dict[str, float] = {}
        for row in rankings:
            tk = (row.get("ticker") or "").upper()
            cv = _safe_float(row.get("coinvest_score_z"))
            if tk and cv is not None:
                coinvest_map[tk] = cv

        if len(coinvest_map) < 30:
            continue

        # Compute clinical quality at this snapshot date (PIT-safe)
        cq_results = compute_clinical_quality_scores(trial_records, snap_date)
        cq_map = {tk: r.clinical_quality_score for tk, r in cq_results.items()}

        # Intersect tickers with both signals
        common_all = [t for t in coinvest_map if t in cq_map]
        if len(common_all) < 30:
            continue

        n_dates += 1
        n_tickers_total += len(common_all)

        for h in HORIZONS:
            # Compute forward returns
            fwd: Dict[str, float] = {}
            for tk in common_all:
                if tk in prices:
                    ret = compute_forward_return(prices[tk], sorted_dates, trade_date, h)
                    if ret is not None:
                        fwd[tk] = ret

            common = [t for t in common_all if t in fwd]
            if len(common) < 20:
                continue

            cq_vals = [cq_map[t] for t in common]
            cv_vals = [coinvest_map[t] for t in common]

            # Quintile assignments
            cq_quintiles = {t: _quintile(cq_vals, cq_map[t]) for t in common}
            cv_quintiles = {t: _quintile(cv_vals, coinvest_map[t]) for t in common}

            # --- Analysis 1: Standalone IC ---
            ic = spearman_ic(cq_vals, [fwd[t] for t in common])
            if ic is not None:
                standalone_ic[h].append(ic)

            # Coinvest IC for reference
            cv_ic = spearman_ic(cv_vals, [fwd[t] for t in common])
            if cv_ic is not None:
                coinvest_ic[h].append(cv_ic)

            # --- Analysis 2: Decile spread ---
            cq_deciles = {t: _decile(cq_vals, cq_map[t]) for t in common}
            top_decile = [t for t in common if cq_deciles[t] == 10]
            bot_decile = [t for t in common if cq_deciles[t] == 1]
            if top_decile and bot_decile:
                top_mean = statistics.mean([fwd[t] for t in top_decile])
                bot_mean = statistics.mean([fwd[t] for t in bot_decile])
                decile_spreads[h].append(top_mean - bot_mean)

            # --- Analysis 3: 2D grid ---
            for t in common:
                cell = (cq_quintiles[t], cv_quintiles[t])
                grid_returns[h][cell].append(fwd[t])

            # --- Analysis 4: Conditional IC within top coinvest quintile ---
            top_cv = [t for t in common if cv_quintiles[t] == 5]
            if len(top_cv) >= 10:
                cond_ic = spearman_ic(
                    [cq_map[t] for t in top_cv],
                    [fwd[t] for t in top_cv],
                )
                if cond_ic is not None:
                    cq_in_top_coinvest_ic[h].append(cond_ic)

            # --- Analysis 5: Filter value ---
            # High coinvest (Q4-5) + high quality (Q4-5) vs high coinvest + low quality (Q1-2)
            high_cv = [t for t in common if cv_quintiles[t] >= 4]
            hh = [t for t in high_cv if cq_quintiles[t] >= 4]
            hl = [t for t in high_cv if cq_quintiles[t] <= 2]
            if hh:
                filter_high_high[h].extend([fwd[t] for t in hh])
            if hl:
                filter_high_low[h].extend([fwd[t] for t in hl])

    # Compile results
    result: Dict[str, Any] = {
        "n_dates": n_dates,
        "n_tickers_avg": round(n_tickers_total / n_dates, 1) if n_dates else 0,
        "date_range": [date_from, date_to],
        "standalone_ic": {str(h): _ic_summary(ics) for h, ics in standalone_ic.items()},
        "coinvest_ic_reference": {str(h): _ic_summary(ics) for h, ics in coinvest_ic.items()},
        "decile_spread": {
            str(h): {
                "mean_spread_pct": round(statistics.mean(sps) * 100, 2) if sps else None,
                "t_stat": (
                    round(statistics.mean(sps) / (statistics.stdev(sps) / math.sqrt(len(sps))), 2)
                    if len(sps) >= 2 and statistics.stdev(sps) > 0
                    else None
                ),
                "n": len(sps),
            }
            for h, sps in decile_spreads.items()
        },
        "cq_in_top_coinvest_ic": {str(h): _ic_summary(ics) for h, ics in cq_in_top_coinvest_ic.items()},
        "grid_2d": {str(h): _grid_summary(cells) for h, cells in grid_returns.items()},
        "filter_value": {
            str(h): {
                "high_coinvest_high_quality_mean_ret_pct": (
                    round(statistics.mean(filter_high_high[h]) * 100, 2) if filter_high_high[h] else None
                ),
                "high_coinvest_low_quality_mean_ret_pct": (
                    round(statistics.mean(filter_high_low[h]) * 100, 2) if filter_high_low[h] else None
                ),
                "spread_pct": (
                    round((statistics.mean(filter_high_high[h]) - statistics.mean(filter_high_low[h])) * 100, 2)
                    if filter_high_high[h] and filter_high_low[h]
                    else None
                ),
                "n_high_high": len(filter_high_high[h]),
                "n_high_low": len(filter_high_low[h]),
            }
            for h in HORIZONS
        },
    }

    return result


def _format_report(result: Dict[str, Any]) -> str:
    """Format results as a readable report."""
    lines = []
    lines.append("=" * 70)
    lines.append("CLINICAL QUALITY × COINVEST INTERACTION TEST")
    lines.append(f"Snapshots: {result['n_dates']}, avg tickers: {result['n_tickers_avg']}")
    lines.append(f"Date range: {result['date_range'][0]} → {result['date_range'][1]}")
    lines.append("=" * 70)

    lines.append("\n--- 1. STANDALONE IC (clinical_quality_score) ---")
    for h_str, ic in sorted(result["standalone_ic"].items(), key=lambda x: int(x[0])):
        lines.append(
            f"  {h_str:>3}d: IC={ic['mean_ic']:+.4f}  t={ic['t_stat']:+.2f}  " f"hit={ic['hit_rate']:.1%}  n={ic['n']}"
        )

    lines.append("\n--- Reference: COINVEST IC ---")
    for h_str, ic in sorted(result["coinvest_ic_reference"].items(), key=lambda x: int(x[0])):
        lines.append(
            f"  {h_str:>3}d: IC={ic['mean_ic']:+.4f}  t={ic['t_stat']:+.2f}  " f"hit={ic['hit_rate']:.1%}  n={ic['n']}"
        )

    lines.append("\n--- 2. DECILE SPREAD (top 10% - bottom 10%) ---")
    for h_str, ds in sorted(result["decile_spread"].items(), key=lambda x: int(x[0])):
        spread = ds["mean_spread_pct"]
        t = ds["t_stat"]
        lines.append(
            f"  {h_str:>3}d: spread={spread:+.2f}%  t={t:+.2f}  n={ds['n']}"
            if spread is not None
            else f"  {h_str:>3}d: insufficient data"
        )

    lines.append("\n--- 3. CONDITIONAL IC (clinical quality WITHIN top coinvest Q5) ---")
    lines.append("  (Does clinical quality discriminate among high-coinvest names?)")
    for h_str, ic in sorted(result["cq_in_top_coinvest_ic"].items(), key=lambda x: int(x[0])):
        lines.append(
            f"  {h_str:>3}d: IC={ic['mean_ic']:+.4f}  t={ic['t_stat']:+.2f}  " f"hit={ic['hit_rate']:.1%}  n={ic['n']}"
        )

    lines.append("\n--- 4. FILTER VALUE (high coinvest: quality split) ---")
    lines.append("  (Do high-coinvest + high-quality names beat high-coinvest + low-quality?)")
    for h_str, fv in sorted(result["filter_value"].items(), key=lambda x: int(x[0])):
        hh = fv["high_coinvest_high_quality_mean_ret_pct"]
        hl = fv["high_coinvest_low_quality_mean_ret_pct"]
        sp = fv["spread_pct"]
        lines.append(
            f"  {h_str:>3}d: HiCoinvest+HiQuality={hh:+.2f}%  "
            f"HiCoinvest+LoQuality={hl:+.2f}%  "
            f"SPREAD={sp:+.2f}%  "
            f"(n={fv['n_high_high']}/{fv['n_high_low']})"
            if hh is not None and hl is not None
            else f"  {h_str:>3}d: insufficient data"
        )

    lines.append("\n--- 5. 2D GRID (clinical Q × coinvest Q → mean return %) ---")
    for h_str in sorted(result["grid_2d"].keys(), key=int):
        lines.append(f"\n  Horizon: {h_str}d")
        grid = result["grid_2d"][h_str]
        if not grid:
            lines.append("    (empty)")
            continue

        # Format as matrix
        lines.append("          CoinvestQ1  CoinvestQ2  CoinvestQ3  CoinvestQ4  CoinvestQ5")
        by_cell = {(r["clinical_q"], r["coinvest_q"]): r for r in grid}
        for cq in range(5, 0, -1):
            row_parts = [f"  ClinQ{cq}"]
            for cv in range(1, 6):
                cell = by_cell.get((cq, cv))
                if cell:
                    row_parts.append(f"  {cell['mean_ret']:+6.2f}%")
                else:
                    row_parts.append("     ---  ")
            lines.append("".join(row_parts))

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Clinical Quality × Coinvest interaction test")
    parser.add_argument("--from", dest="date_from", default="2022-01-01")
    parser.add_argument("--to", dest="date_to", default="2026-03-31")
    parser.add_argument("--snapshot-root", type=Path, default=PROJECT_ROOT / "data" / "snapshots_pit")
    parser.add_argument("--price-csv", type=Path, default=PROJECT_ROOT / "production_data" / "price_history.csv")
    parser.add_argument("--trial-records", type=Path, default=PROJECT_ROOT / "production_data" / "trial_records.json")
    args = parser.parse_args()

    result = run_interaction(
        args.snapshot_root,
        args.price_csv,
        args.trial_records,
        args.date_from,
        args.date_to,
    )

    # Write JSON
    out_dir = PROJECT_ROOT / "output" / "clinical_quality_interaction"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "interaction_results.json", "w") as f:
        json.dump(result, f, indent=2)

    # Print report
    report = _format_report(result)
    print(report)
    with open(out_dir / "interaction_report.txt", "w") as f:
        f.write(report)

    print(f"\nResults written to {out_dir}/")


if __name__ == "__main__":
    main()
