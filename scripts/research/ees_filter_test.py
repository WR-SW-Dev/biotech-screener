#!/usr/bin/env python3
"""EES filter test — hard filter vs linear blend.

Tests whether using quality + trap as hierarchical hard filters
outperforms the linear v2 blend.

Arms:
  1. Baseline: all names, EW top-30
  2. v2 blend: top-30 by ees_v2_score
  3. Quality filter only: exclude bottom 20% quality, then EW top-30 by rank
  4. Quality + trap filter: exclude bottom 20% quality AND bottom 20% trap
  5. Quality + trap aggressive: exclude bottom 30% quality AND bottom 30% trap
  6. Quality filter + trap rank: exclude bottom 20% quality, rank by trap

Measures: portfolio mean return, Sharpe, hit rate at 5d/20d/63d.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from event_ev.expectation_error_model import ExpectationErrorModel
from scripts.eval_forward_returns import (
    compute_forward_return,
    discover_snapshot_dates,
    load_price_series,
    load_rankings,
    resolve_trade_date,
)

HORIZONS = [5, 20, 63]
TOP_K = 30
model = ExpectationErrorModel()


def _percentile_threshold(vals: List[float], pct: float) -> float:
    """Return the value at the given percentile (0-1)."""
    s = sorted(vals)
    idx = min(int(len(s) * pct), len(s) - 1)
    return s[idx]


def run_filter_test(
    snapshot_root: Path,
    price_csv: Path,
    date_from: str = "2022-03-18",
    date_to: str = "2026-03-31",
) -> Dict[str, Any]:
    snap_dates = discover_snapshot_dates(snapshot_root, date_from, date_to)
    prices = load_price_series(price_csv)

    all_dates_set: set = set()
    for tp in prices.values():
        all_dates_set.update(tp.keys())
    sorted_dates = sorted(all_dates_set)

    # Per-arm, per-horizon: list of portfolio returns per date
    arm_returns: Dict[str, Dict[int, List[float]]] = {
        "baseline_ew30": defaultdict(list),
        "v2_blend_top30": defaultdict(list),
        "quality_filter_20pct": defaultdict(list),
        "quality_trap_filter_20pct": defaultdict(list),
        "quality_trap_filter_30pct": defaultdict(list),
        "quality_filter_trap_rank": defaultdict(list),
    }

    n_dates = 0

    for snap_date in snap_dates:
        trade_date = resolve_trade_date(sorted_dates, snap_date, "next_trading_day")
        if not trade_date:
            continue

        rankings = load_rankings(snapshot_root / snap_date)
        if not rankings:
            continue

        scores = model.score_batch(rankings, snap_date)
        if not scores:
            continue

        # Build maps
        by_ticker = {s.ticker: s for s in scores}
        rank_map = {}
        for row in rankings:
            t = row.get("ticker", "")
            ar = row.get("actionable_rank", "")
            if t and ar and ar.strip().isdigit():
                rank_map[t] = int(ar)

        n_dates += 1

        for h in HORIZONS:
            # Forward returns for all scored tickers
            fwd: Dict[str, float] = {}
            for ticker in by_ticker:
                if ticker in prices:
                    ret = compute_forward_return(prices[ticker], sorted_dates, trade_date, h)
                    if ret is not None:
                        fwd[ticker] = ret

            if len(fwd) < TOP_K:
                continue

            eligible = [t for t in by_ticker if t in fwd]
            if len(eligible) < TOP_K:
                continue

            quality_vals = [by_ticker[t].quality_overlay_score for t in eligible]
            trap_vals = [by_ticker[t].trap_overlay_score for t in eligible]

            q_p20 = _percentile_threshold(quality_vals, 0.20)
            q_p30 = _percentile_threshold(quality_vals, 0.30)
            t_p20 = _percentile_threshold(trap_vals, 0.20)
            t_p30 = _percentile_threshold(trap_vals, 0.30)

            # --- Arm 1: Baseline EW top-30 by actionable_rank ---
            ranked = sorted(
                [t for t in eligible if t in rank_map],
                key=lambda t: rank_map[t],
            )[:TOP_K]
            if len(ranked) >= 10:
                arm_returns["baseline_ew30"][h].append(statistics.mean(fwd[t] for t in ranked))

            # --- Arm 2: v2 blend top-30 ---
            v2_sorted = sorted(eligible, key=lambda t: by_ticker[t].ees_v2_score, reverse=True)[:TOP_K]
            if len(v2_sorted) >= 10:
                arm_returns["v2_blend_top30"][h].append(statistics.mean(fwd[t] for t in v2_sorted))

            # --- Arm 3: Quality filter 20%, then top-30 by rank ---
            q_pass = [t for t in eligible if by_ticker[t].quality_overlay_score > q_p20]
            q_ranked = sorted(
                [t for t in q_pass if t in rank_map],
                key=lambda t: rank_map[t],
            )[:TOP_K]
            if len(q_ranked) >= 10:
                arm_returns["quality_filter_20pct"][h].append(statistics.mean(fwd[t] for t in q_ranked))

            # --- Arm 4: Quality 20% + Trap 20% filter, then top-30 by rank ---
            qt_pass = [
                t
                for t in eligible
                if by_ticker[t].quality_overlay_score > q_p20 and by_ticker[t].trap_overlay_score > t_p20
            ]
            qt_ranked = sorted(
                [t for t in qt_pass if t in rank_map],
                key=lambda t: rank_map[t],
            )[:TOP_K]
            if len(qt_ranked) >= 10:
                arm_returns["quality_trap_filter_20pct"][h].append(statistics.mean(fwd[t] for t in qt_ranked))

            # --- Arm 5: Quality 30% + Trap 30% filter, then top-30 by rank ---
            qt_pass_30 = [
                t
                for t in eligible
                if by_ticker[t].quality_overlay_score > q_p30 and by_ticker[t].trap_overlay_score > t_p30
            ]
            qt_ranked_30 = sorted(
                [t for t in qt_pass_30 if t in rank_map],
                key=lambda t: rank_map[t],
            )[:TOP_K]
            if len(qt_ranked_30) >= 10:
                arm_returns["quality_trap_filter_30pct"][h].append(statistics.mean(fwd[t] for t in qt_ranked_30))

            # --- Arm 6: Quality filter 20%, then rank by trap ---
            q_trap_sorted = sorted(
                q_pass,
                key=lambda t: by_ticker[t].trap_overlay_score,
                reverse=True,
            )[:TOP_K]
            if len(q_trap_sorted) >= 10:
                arm_returns["quality_filter_trap_rank"][h].append(statistics.mean(fwd[t] for t in q_trap_sorted))

    # Aggregate
    results: Dict[str, Any] = {"n_dates": n_dates, "arms": {}}

    for arm_name in arm_returns:
        arm_result: Dict[str, Any] = {}
        for h in HORIZONS:
            rets = arm_returns[arm_name][h]
            if not rets:
                arm_result[f"{h}d"] = {"mean_ret": None, "sharpe": None, "hit_rate": None, "n": 0}
                continue
            m = statistics.mean(rets)
            s = statistics.stdev(rets) if len(rets) >= 2 else 0.001
            sharpe = m / s if s > 0 else 0
            hr = sum(1 for r in rets if r > 0) / len(rets)
            arm_result[f"{h}d"] = {
                "mean_ret": round(m * 100, 4),  # percentage
                "std_ret": round(s * 100, 4),
                "sharpe": round(sharpe, 3),
                "hit_rate": round(hr, 3),
                "n": len(rets),
            }
        results["arms"][arm_name] = arm_result

    return results


def main() -> None:
    snapshot_root = PROJECT_ROOT / "data" / "snapshots"
    price_csv = PROJECT_ROOT / "production_data" / "price_history.csv"
    out_dir = PROJECT_ROOT / "output" / "ees_filter_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Running EES filter test...")
    results = run_filter_test(snapshot_root, price_csv)

    with open(out_dir / "filter_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    n = results["n_dates"]
    print(f"\nEvaluated {n} snapshot dates\n")

    arm_order = [
        "baseline_ew30",
        "v2_blend_top30",
        "quality_filter_20pct",
        "quality_trap_filter_20pct",
        "quality_trap_filter_30pct",
        "quality_filter_trap_rank",
    ]

    for h in HORIZONS:
        print(f"{'=' * 80}")
        print(f"  {h}d FORWARD RETURNS — EW Top-{TOP_K} Portfolio")
        print(f"{'=' * 80}")
        print(f"{'Arm':<32s} {'Mean%':>8s} {'Std%':>8s} {'Sharpe':>8s} {'Hit%':>7s} {'N':>5s}")
        print("-" * 80)

        for arm_name in arm_order:
            r = results["arms"][arm_name].get(f"{h}d", {})
            if r.get("mean_ret") is None:
                print(f"{arm_name:<32s}       —        —        —       —      —")
                continue
            print(
                f"{arm_name:<32s} {r['mean_ret']:>+7.3f}% {r['std_ret']:>7.3f}% "
                f"{r['sharpe']:>+7.3f} {r['hit_rate']:>6.0%} {r['n']:>5d}"
            )
        print()

    print(f"Written: {out_dir / 'filter_results.json'}")


if __name__ == "__main__":
    main()
