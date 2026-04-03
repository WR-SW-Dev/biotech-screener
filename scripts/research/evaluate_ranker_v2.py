#!/usr/bin/env python3
"""Spec 051 — Ranker v2 evaluation harness.

Runs all 3 model variants × 3 cohort definitions on the research panel,
plus ablation by feature block. Produces:
  - output/signals/ranker_v2_results.json     (full structured results)
  - output/signals/ranker_v2_research_memo.md  (human-readable summary)

Usage:
    python3 scripts/research/evaluate_ranker_v2.py
    python3 scripts/research/evaluate_ranker_v2.py --variants pairwise_logistic
    python3 scripts/research/evaluate_ranker_v2.py --cohorts C1
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ranker_v2_pairwise import RankerV2Config, config_id, train_and_evaluate

PANEL_CSV = PROJECT_ROOT / "output" / "signals" / "research_panel.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "signals"

# Cost model (same as test_ranker_bundles.py)
RW_EXTRA_COST_BPS_YR = 65
MONTHLY_COST_DRAG = RW_EXTRA_COST_BPS_YR / 12 / 10_000

# ---------------------------------------------------------------------------
# Cohort definitions
# ---------------------------------------------------------------------------

COHORT_CONFIGS = {
    "C1": {"cohort_top_n": 60, "require_catalyst_window": False},
    "C2": {"cohort_top_n": 60, "require_catalyst_window": True},
    "C3": {"cohort_top_n": 30, "require_catalyst_window": True},
}

# Model variants
MODEL_VARIANTS = ["baseline_bounded", "pointwise_logistic", "pairwise_logistic"]

# Ablation configs (drop one block at a time)
ABLATION_BLOCKS = ["institutional", "clinical", "options", "risk"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if f == f else default
    except (ValueError, TypeError):
        return default


def _safe_mean(vals):
    return statistics.mean(vals) if vals else None


def _safe_stdev(vals):
    return statistics.stdev(vals) if len(vals) >= 2 else None


def _safe_tstat(vals):
    if len(vals) < 2:
        return None
    m, s = statistics.mean(vals), statistics.stdev(vals)
    return m / (s / len(vals) ** 0.5) if s > 1e-9 else None


def _hit_rate(vals):
    return sum(1 for x in vals if x > 0) / len(vals) if vals else None


def _r(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, d)


def _pp(v):
    return v * 100 if v is not None else None


def _fmt(v, d=2):
    return f"{v:.{d}f}" if v is not None else "—"


def _fmt_pct(v):
    if v is None:
        return "—"
    return f"{v * 100:.1f}%"


# ---------------------------------------------------------------------------
# Load research panel
# ---------------------------------------------------------------------------


def load_panel(path: Path) -> Dict[str, List[Dict[str, str]]]:
    """Load research panel CSV grouped by snapshot_date."""
    snapshots: Dict[str, list] = defaultdict(list)
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row.get("snapshot_date", "")
            if date:
                snapshots[date].append(row)
    return dict(snapshots)


# ---------------------------------------------------------------------------
# Aggregate OOS results
# ---------------------------------------------------------------------------


def aggregate_results(oos_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-date OOS results into summary statistics."""
    if not oos_results:
        return {"n_periods": 0}

    ew_rets = [r["ew_ret"] for r in oos_results if _is_valid(r.get("ew_ret"))]
    ew_excess = [r["ew_excess_xbi"] for r in oos_results if _is_valid(r.get("ew_excess_xbi"))]
    pw_acc_top = [r.get("pairwise_accuracy_top", r.get("pairwise_accuracy")) for r in oos_results]
    pw_acc_top = [x for x in pw_acc_top if _is_valid(x)]
    pw_acc_full = [r["pairwise_accuracy_full"] for r in oos_results if _is_valid(r.get("pairwise_accuracy_full"))]
    rank_ics = [r["rank_ic"] for r in oos_results if _is_valid(r.get("rank_ic"))]
    q_spreads = [r["quintile_spread"] for r in oos_results if _is_valid(r.get("quintile_spread"))]

    # Turnover: compare consecutive top-30 rosters
    turnover_vals = []
    for i in range(1, len(oos_results)):
        prev = set(oos_results[i - 1].get("top_tickers", []))
        curr = set(oos_results[i].get("top_tickers", []))
        if prev and curr:
            overlap = len(prev & curr)
            turnover_vals.append(1.0 - overlap / max(len(prev), len(curr)))

    # Cutoff zone
    total_swaps = sum(r.get("cutoff_swaps", 0) for r in oos_results)
    total_improvements = sum(r.get("cutoff_improvements", 0) for r in oos_results)

    # Regime breakdown
    regime_excess = defaultdict(list)
    for r in oos_results:
        regime = r.get("regime")
        if regime and _is_valid(r.get("ew_excess_xbi")):
            regime_excess[regime].append(r["ew_excess_xbi"])

    # Year breakdown
    year_excess = defaultdict(list)
    for r in oos_results:
        date = r.get("date", "")
        if date and _is_valid(r.get("ew_excess_xbi")):
            year_excess[date[:4]].append(r["ew_excess_xbi"])

    # Baseline roster overlap (for non-baseline models)
    baseline_overlaps = []
    for r in oos_results:
        if "baseline_overlap" in r:
            baseline_overlaps.append(r["baseline_overlap"])

    return {
        "n_periods": len(oos_results),
        "ew_ret_mean_pp": _r(_pp(_safe_mean(ew_rets))),
        "ew_ret_tstat": _r(_safe_tstat(ew_rets)),
        "ew_excess_xbi_mean_pp": _r(_pp(_safe_mean(ew_excess))),
        "ew_excess_xbi_tstat": _r(_safe_tstat(ew_excess)),
        "ew_excess_xbi_cum_pp": _r(_pp(sum(ew_excess))) if ew_excess else None,
        "hit_rate": _r(_hit_rate(ew_excess)),
        "pairwise_accuracy_top": _r(_safe_mean(pw_acc_top)),
        "pairwise_accuracy_full": _r(_safe_mean(pw_acc_full)),
        "rank_ic_mean": _r(_safe_mean(rank_ics)),
        "rank_ic_tstat": _r(_safe_tstat(rank_ics)),
        "quintile_spread_mean_pp": _r(_pp(_safe_mean(q_spreads))),
        "turnover_mean": _r(_safe_mean(turnover_vals)),
        "turnover_stdev": _r(_safe_stdev(turnover_vals)),
        "cutoff_swaps_total": total_swaps,
        "cutoff_improvements_total": total_improvements,
        "cutoff_improvement_rate": _r(total_improvements / total_swaps) if total_swaps > 0 else None,
        "regime": {
            regime: {
                "n": len(vals),
                "mean_excess_pp": _r(_pp(_safe_mean(vals))),
                "tstat": _r(_safe_tstat(vals)),
            }
            for regime, vals in sorted(regime_excess.items())
        },
        "by_year": {
            year: {
                "n": len(vals),
                "mean_excess_pp": _r(_pp(_safe_mean(vals))),
            }
            for year, vals in sorted(year_excess.items())
        },
    }


def _is_valid(v):
    if v is None:
        return False
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return False
    return True


# ---------------------------------------------------------------------------
# Compute baseline overlap for non-baseline results
# ---------------------------------------------------------------------------


def add_baseline_overlap(
    baseline_oos: List[Dict[str, Any]],
    model_oos: List[Dict[str, Any]],
) -> None:
    """Add baseline_overlap field to model OOS results."""
    baseline_by_date = {r["date"]: set(r.get("top_tickers", [])) for r in baseline_oos}
    for r in model_oos:
        date = r.get("date", "")
        bl = baseline_by_date.get(date, set())
        ml = set(r.get("top_tickers", []))
        if bl and ml:
            r["baseline_overlap"] = len(bl & ml) / max(len(bl), len(ml))


# ---------------------------------------------------------------------------
# Research memo generation
# ---------------------------------------------------------------------------


def generate_memo(all_results: Dict[str, Any], output_path: Path) -> None:
    """Generate human-readable research memo."""
    lines = [
        "# Ranker v2 Research Memo — Spec 051",
        "",
        f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "---",
        "",
        "## Summary",
        "",
        "Three model variants tested across three cohort definitions:",
        "",
        "| Variant | Description |",
        "|---------|-------------|",
        "| **baseline_bounded** | Current production ranker (actionable_rank ordering) |",
        "| **pointwise_logistic** | Logistic regression predicting positive return |",
        "| **pairwise_logistic** | Bradley-Terry pairwise ranking model |",
        "",
        "| Cohort | Definition |",
        "|--------|------------|",
        "| **C1** | Eligible + top-60 by actionable_rank |",
        "| **C2** | C1 + catalyst_in_window |",
        "| **C3** | Eligible + top-30 + catalyst_in_window |",
        "",
    ]

    # Main results table
    lines.append("## Portfolio-Level Results (63d forward, EW Top-30)")
    lines.append("")
    lines.append(
        "| Cohort | Variant | Periods | Excess XBI (pp/mo) | t-stat | Hit Rate | Pairwise Acc | Rank IC | Turnover |"
    )
    lines.append(
        "|--------|---------|---------|-------------------|--------|----------|-------------|---------|----------|"
    )

    for key, res in sorted(all_results.get("main", {}).items()):
        agg = res.get("aggregate", {})
        cohort, variant = key.split("__")
        lines.append(
            f"| {cohort} | {variant} | {agg.get('n_periods', 0)} | "
            f"{_fmt(agg.get('ew_excess_xbi_mean_pp'))} | "
            f"{_fmt(agg.get('ew_excess_xbi_tstat'))} | "
            f"{_fmt_pct(agg.get('hit_rate'))} | "
            f"{_fmt(agg.get('pairwise_accuracy_top'))} | "
            f"{_fmt(agg.get('rank_ic_mean'))} | "
            f"{_fmt(agg.get('turnover_mean'))} |"
        )

    lines.append("")

    # Regime breakdown
    lines.append("## Regime Breakdown (C1 cohort, 63d)")
    lines.append("")
    lines.append("| Variant | Bear (pp) | Neutral (pp) | Bull (pp) |")
    lines.append("|---------|-----------|-------------|-----------|")

    for key, res in sorted(all_results.get("main", {}).items()):
        if not key.startswith("C1__"):
            continue
        agg = res.get("aggregate", {})
        _, variant = key.split("__")
        regimes = agg.get("regime", {})
        bear = regimes.get("bear", {}).get("mean_excess_pp")
        neutral = regimes.get("neutral", {}).get("mean_excess_pp")
        bull = regimes.get("bull", {}).get("mean_excess_pp")
        lines.append(f"| {variant} | {_fmt(bear)} | {_fmt(neutral)} | {_fmt(bull)} |")

    lines.append("")

    # Ablation
    if "ablation" in all_results:
        lines.append("## Feature Block Ablation (pairwise_logistic, C1)")
        lines.append("")
        lines.append("| Dropped Block | Excess XBI (pp/mo) | t-stat | Rank IC | Δ vs full |")
        lines.append("|---------------|-------------------|--------|---------|-----------|")

        full_key = "C1__pairwise_logistic"
        full_excess = all_results.get("main", {}).get(full_key, {}).get("aggregate", {}).get("ew_excess_xbi_mean_pp")

        for block, res in sorted(all_results.get("ablation", {}).items()):
            agg = res.get("aggregate", {})
            excess = agg.get("ew_excess_xbi_mean_pp")
            delta = None
            if excess is not None and full_excess is not None:
                delta = excess - full_excess
            lines.append(
                f"| {block} | {_fmt(excess)} | "
                f"{_fmt(agg.get('ew_excess_xbi_tstat'))} | "
                f"{_fmt(agg.get('rank_ic_mean'))} | "
                f"{_fmt(delta, d=2)} |"
            )

        lines.append("")

    # Year-by-year
    lines.append("## Year-by-Year (pairwise_logistic, C1)")
    lines.append("")
    full_key = "C1__pairwise_logistic"
    full_agg = all_results.get("main", {}).get(full_key, {}).get("aggregate", {})
    by_year = full_agg.get("by_year", {})
    if by_year:
        lines.append("| Year | N | Mean Excess XBI (pp/mo) |")
        lines.append("|------|---|------------------------|")
        for year, data in sorted(by_year.items()):
            lines.append(f"| {year} | {data.get('n', 0)} | {_fmt(data.get('mean_excess_pp'))} |")
        lines.append("")

    # Recommendation
    lines.append("## Recommendation")
    lines.append("")
    lines.append("**[PLACEHOLDER — to be filled after reviewing results]**")
    lines.append("")
    lines.append("### Key questions:")
    lines.append("")
    lines.append("1. **Is the bounded-adjustment architecture the bottleneck?**")
    lines.append("   Compare pairwise_logistic vs baseline_bounded on portfolio excess and rank IC.")
    lines.append("")
    lines.append("2. **Does pairwise ranking improve actual portfolio decisions?**")
    lines.append("   Check cutoff-zone swap quality and top-30 roster differences.")
    lines.append("")
    lines.append("3. **Should Ranker v2 remain shadow, replace current ranker, or be abandoned?**")
    lines.append("   Requires pairwise to beat baseline on excess, not worsen turnover,")
    lines.append("   and show interpretable reorderings.")
    lines.append("")

    output_path.write_text("\n".join(lines))
    print(f"  Memo: {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Ranker v2 evaluation harness (Spec 051)")
    parser.add_argument("--variants", nargs="+", default=MODEL_VARIANTS, help="Model variants to test")
    parser.add_argument("--cohorts", nargs="+", default=list(COHORT_CONFIGS.keys()), help="Cohort IDs")
    parser.add_argument("--no-ablation", action="store_true", help="Skip ablation tests")
    parser.add_argument("--horizon", default="fwd_ret_63d", help="Forward return column")
    parser.add_argument("--epochs", type=int, default=200, help="Training epochs")
    parser.add_argument("--lr", type=float, default=0.01, help="Learning rate")
    args = parser.parse_args()

    print("=" * 60)
    print("Ranker v2 Evaluation — Spec 051")
    print("=" * 60)

    # Load panel
    print(f"\nLoading research panel: {PANEL_CSV}")
    snapshots = load_panel(PANEL_CSV)
    n_dates = len(snapshots)
    n_rows = sum(len(v) for v in snapshots.values())
    print(f"  {n_dates} snapshot dates, {n_rows} total rows")

    all_results: Dict[str, Any] = {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "panel_dates": n_dates,
            "panel_rows": n_rows,
            "horizon": args.horizon,
            "epochs": args.epochs,
        },
        "main": {},
    }

    # Collect baseline OOS results per cohort for overlap computation
    baseline_oos_by_cohort: Dict[str, List[Dict]] = {}

    # --- Main evaluation grid ---
    for cohort_id in args.cohorts:
        cohort_cfg = COHORT_CONFIGS[cohort_id]
        print(
            f"\n--- Cohort {cohort_id}: top-{cohort_cfg['cohort_top_n']}, "
            f"catalyst_window={cohort_cfg['require_catalyst_window']} ---"
        )

        for variant in args.variants:
            print(f"  Model: {variant} ...", end=" ", flush=True)

            config = RankerV2Config(
                model_variant=variant,
                cohort_top_n=cohort_cfg["cohort_top_n"],
                require_catalyst_window=cohort_cfg["require_catalyst_window"],
                forward_horizon=args.horizon,
                n_epochs=args.epochs,
                learning_rate=args.lr,
            )

            result = train_and_evaluate(snapshots, config)
            agg = aggregate_results(result.oos_results)

            key = f"{cohort_id}__{variant}"
            all_results["main"][key] = {
                "config_id": config_id(config),
                "config": {
                    "model_variant": config.model_variant,
                    "feature_set": config.feature_set,
                    "cohort_top_n": config.cohort_top_n,
                    "require_catalyst_window": config.require_catalyst_window,
                    "forward_horizon": config.forward_horizon,
                    "portfolio_top_n": config.portfolio_top_n,
                },
                "aggregate": agg,
            }

            if variant == "baseline_bounded":
                baseline_oos_by_cohort[cohort_id] = result.oos_results

            # Add baseline overlap for non-baseline
            if variant != "baseline_bounded" and cohort_id in baseline_oos_by_cohort:
                add_baseline_overlap(baseline_oos_by_cohort[cohort_id], result.oos_results)
                # Recompute aggregate with overlap
                overlaps = [r["baseline_overlap"] for r in result.oos_results if "baseline_overlap" in r]
                if overlaps:
                    agg["baseline_overlap_mean"] = _r(_safe_mean(overlaps))

            n = agg.get("n_periods", 0)
            excess = agg.get("ew_excess_xbi_mean_pp")
            tstat = agg.get("ew_excess_xbi_tstat")
            ic = agg.get("rank_ic_mean")
            print(f"{n} periods, excess={_fmt(excess)}pp, t={_fmt(tstat)}, IC={_fmt(ic)}")

    # --- Ablation (pairwise_logistic on C1 only) ---
    if not args.no_ablation and "pairwise_logistic" in args.variants and "C1" in args.cohorts:
        print("\n--- Ablation (pairwise_logistic, C1) ---")
        all_results["ablation"] = {}

        for block in ABLATION_BLOCKS:
            print(f"  Drop {block} ...", end=" ", flush=True)

            config = RankerV2Config(
                model_variant="pairwise_logistic",
                feature_set=f"ablation_drop_{block}",
                cohort_top_n=60,
                require_catalyst_window=False,
                forward_horizon=args.horizon,
                n_epochs=args.epochs,
                learning_rate=args.lr,
            )

            result = train_and_evaluate(snapshots, config)
            agg = aggregate_results(result.oos_results)

            all_results["ablation"][block] = {
                "config_id": config_id(config),
                "aggregate": agg,
            }

            n = agg.get("n_periods", 0)
            excess = agg.get("ew_excess_xbi_mean_pp")
            print(f"{n} periods, excess={_fmt(excess)}pp")

    # --- Minimal feature set ---
    if "pairwise_logistic" in args.variants and "C1" in args.cohorts:
        print("\n  Minimal features ...", end=" ", flush=True)
        config = RankerV2Config(
            model_variant="pairwise_logistic",
            feature_set="minimal",
            cohort_top_n=60,
            require_catalyst_window=False,
            forward_horizon=args.horizon,
            n_epochs=args.epochs,
            learning_rate=args.lr,
        )
        result = train_and_evaluate(snapshots, config)
        agg = aggregate_results(result.oos_results)
        all_results["minimal"] = {"config_id": config_id(config), "aggregate": agg}
        n = agg.get("n_periods", 0)
        excess = agg.get("ew_excess_xbi_mean_pp")
        print(f"{n} periods, excess={_fmt(excess)}pp")

    # --- Save results ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results_path = OUTPUT_DIR / "ranker_v2_results.json"
    with open(results_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults: {results_path}")

    # --- Generate memo ---
    memo_path = OUTPUT_DIR / "ranker_v2_research_memo.md"
    generate_memo(all_results, memo_path)

    print("\nDone.")


if __name__ == "__main__":
    main()
