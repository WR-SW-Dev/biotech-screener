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

from ranker_engine import DEFAULT_RANKER_CONFIG, compute_ranker_adjustments
from ranker_v2_pairwise import RankerV2Config, config_id, train_and_evaluate
from selector_engine import DEFAULT_SELECTOR_CONFIG, compute_selector_scores

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
# Production comparator: A4 selector + clinical_50 ranker
# ---------------------------------------------------------------------------


def evaluate_production_stack(
    snapshots: Dict[str, List[Dict[str, Any]]],
    forward_horizon: str = "fwd_ret_63d",
    portfolio_top_n: int = 30,
) -> List[Dict[str, Any]]:
    """Run the actual A4 selector + clinical_50 ranker on each snapshot.

    Returns per-date OOS results in the same format as train_and_evaluate.
    """
    oos_results: List[Dict[str, Any]] = []

    for snap_date in sorted(snapshots.keys()):
        rows = snapshots[snap_date]

        # Filter to eligible
        eligible_rows = [r for r in rows if _sf(r.get("eligible"), 0.0) == 1.0]
        if len(eligible_rows) < 10:
            continue

        # Run A4 selector
        selector_results = compute_selector_scores(eligible_rows, DEFAULT_SELECTOR_CONFIG)

        # Extract scores and buckets
        sel_scores = [sr.selector_score for sr in selector_results]
        sel_buckets = [sr.selector_rank_bucket for sr in selector_results]

        # Run clinical_50 ranker
        ranker_results = compute_ranker_adjustments(eligible_rows, sel_scores, sel_buckets, DEFAULT_RANKER_CONFIG)

        # Sort by final_score descending
        indexed = sorted(
            range(len(eligible_rows)),
            key=lambda i: -ranker_results[i].final_score,
        )

        top_n = min(portfolio_top_n, len(indexed))
        top_indices = indexed[:top_n]

        # Forward returns
        fwd_col = forward_horizon
        xbi_col = fwd_col.replace("fwd_ret_", "fwd_excess_xbi_")

        top_rets = []
        top_xbi = []
        for i in top_indices:
            r = _sf(eligible_rows[i].get(fwd_col))
            if r == r:
                top_rets.append(r)
            x = _sf(eligible_rows[i].get(xbi_col))
            if x == x:
                top_xbi.append(x)

        ew_ret = sum(top_rets) / len(top_rets) if top_rets else float("nan")
        ew_excess = sum(top_xbi) / len(top_xbi) if top_xbi else float("nan")

        # Pairwise accuracy (production rank order vs returns)
        pw_correct = 0
        pw_total = 0
        for a_pos in range(len(top_indices)):
            for b_pos in range(a_pos + 1, len(top_indices)):
                i, j = top_indices[a_pos], top_indices[b_pos]
                ri = _sf(eligible_rows[i].get(fwd_col))
                rj = _sf(eligible_rows[j].get(fwd_col))
                if ri != ri or rj != rj or abs(ri - rj) < 1e-10:
                    continue
                pw_total += 1
                if ri > rj:
                    pw_correct += 1
        pw_acc = pw_correct / pw_total if pw_total > 0 else float("nan")

        # Spearman IC: final_score vs forward return
        valid_scores = []
        valid_rets = []
        for i in range(len(eligible_rows)):
            r = _sf(eligible_rows[i].get(fwd_col))
            if r == r:
                valid_scores.append(ranker_results[i].final_score)
                valid_rets.append(r)
        ic = _spearman_ic(valid_scores, valid_rets)

        # Regime
        regime = None
        for row in rows:
            r = row.get("regime_63d")
            if r:
                regime = r
                break

        # Top-N tickers
        top_tickers = [eligible_rows[i].get("ticker", "") for i in top_indices]

        oos_results.append(
            {
                "model": "production_a4_clinical50",
                "date": snap_date,
                "cohort_size": len(eligible_rows),
                "portfolio_size": len(top_rets),
                "ew_ret": _r(ew_ret, 6),
                "ew_excess_xbi": _r(ew_excess, 6),
                "pairwise_accuracy_top": _r(pw_acc, 6),
                "pairwise_accuracy_full": _r(pw_acc, 6),
                "rank_ic": _r(ic, 6),
                "quintile_spread": None,
                "cutoff_swaps": 0,
                "cutoff_improvements": 0,
                "regime": regime,
                "top_tickers": top_tickers,
            }
        )

    return oos_results


def _spearman_ic(x: List[float], y: List[float]) -> float:
    """Spearman rank correlation (local copy for this module)."""
    n = len(x)
    if n < 5:
        return float("nan")

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

    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx < 1e-9 or dy < 1e-9:
        return float("nan")
    return num / (dx * dy)


# ---------------------------------------------------------------------------
# Cutoff-zone swap analysis (ranks 20-40)
# ---------------------------------------------------------------------------


def compute_cutoff_swaps(
    prod_tickers: List[str],
    challenger_tickers: List[str],
    rows: List[Dict[str, Any]],
    fwd_col: str,
) -> Dict[str, Any]:
    """Compare name choices in the cutoff zone (positions 20-40).

    Returns swap count, improvement count, and specific swap details.
    """
    # Build return lookup
    ret_map = {}
    for r in rows:
        ticker = r.get("ticker", "")
        ret = _sf(r.get(fwd_col))
        if ret == ret:
            ret_map[ticker] = ret

    # Names in challenger top-30 but not production top-30
    prod_30 = set(prod_tickers[:30])
    chal_30 = set(challenger_tickers[:30])
    added = chal_30 - prod_30
    dropped = prod_30 - chal_30

    # For each swap: did the added name outperform the dropped name?
    swap_details = []
    improvements = 0
    for a in sorted(added):
        for d in sorted(dropped):
            r_add = ret_map.get(a, float("nan"))
            r_drop = ret_map.get(d, float("nan"))
            if r_add == r_add and r_drop == r_drop:
                improved = r_add > r_drop
                if improved:
                    improvements += 1
                swap_details.append(
                    {
                        "added": a,
                        "dropped": d,
                        "ret_added": _r(r_add, 4),
                        "ret_dropped": _r(r_drop, 4),
                        "improved": improved,
                    }
                )

    return {
        "n_swaps": len(added),
        "n_swap_pairs": len(swap_details),
        "n_improvements": improvements,
        "improvement_rate": _r(improvements / len(swap_details)) if swap_details else None,
        "overlap_30": len(prod_30 & chal_30),
        "overlap_pct": _r(len(prod_30 & chal_30) / max(len(prod_30), 1)),
    }


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
    parser.add_argument("--feature-set", default="expanded", help="Feature set: minimal, expanded, ablation_drop_*")
    parser.add_argument("--max-pairs", type=int, default=200, help="Max pairs per date")
    parser.add_argument("--train-window", type=int, default=24, help="Rolling training window (0=expanding)")
    parser.add_argument(
        "--benchmark", action="store_true", help="Run production benchmark: A4+clinical_50 vs pairwise challenger"
    )
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
                feature_set=args.feature_set,
                cohort_top_n=cohort_cfg["cohort_top_n"],
                require_catalyst_window=cohort_cfg["require_catalyst_window"],
                forward_horizon=args.horizon,
                n_epochs=args.epochs,
                learning_rate=args.lr,
                max_pairs_per_date=args.max_pairs,
                train_window=args.train_window,
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

    # --- Production benchmark ---
    if args.benchmark:
        print("\n" + "=" * 60)
        print("Production Benchmark: A4+clinical_50 vs Pairwise Challenger")
        print("=" * 60)

        # 1. Run production stack
        print("\n  Production (A4 + clinical_50) ...", end=" ", flush=True)
        prod_oos = evaluate_production_stack(snapshots, args.horizon)
        prod_agg = aggregate_results(prod_oos)
        all_results["benchmark_production"] = {"aggregate": prod_agg}
        print(
            f"{prod_agg.get('n_periods', 0)} periods, "
            f"excess={_fmt(prod_agg.get('ew_excess_xbi_mean_pp'))}pp, "
            f"t={_fmt(prod_agg.get('ew_excess_xbi_tstat'))}"
        )

        # 2. Run challenger: pairwise C1 minimal
        print("  Challenger (pairwise C1 minimal) ...", end=" ", flush=True)
        chal_config = RankerV2Config(
            model_variant="pairwise_logistic",
            feature_set="minimal",
            cohort_top_n=60,
            require_catalyst_window=False,
            forward_horizon=args.horizon,
            n_epochs=args.epochs,
            learning_rate=args.lr,
            max_pairs_per_date=args.max_pairs,
            train_window=args.train_window,
        )
        chal_result = train_and_evaluate(snapshots, chal_config)
        chal_agg = aggregate_results(chal_result.oos_results)
        all_results["benchmark_challenger"] = {
            "config_id": config_id(chal_config),
            "aggregate": chal_agg,
        }
        print(
            f"{chal_agg.get('n_periods', 0)} periods, "
            f"excess={_fmt(chal_agg.get('ew_excess_xbi_mean_pp'))}pp, "
            f"t={_fmt(chal_agg.get('ew_excess_xbi_tstat'))}"
        )

        # 3. Head-to-head comparison: cutoff swaps, overlap, roster diffs
        print("\n  Computing head-to-head ...", flush=True)
        prod_by_date = {r["date"]: r for r in prod_oos}
        chal_by_date = {r["date"]: r for r in chal_result.oos_results}
        common_dates = sorted(set(prod_by_date.keys()) & set(chal_by_date.keys()))

        overlap_vals = []
        swap_totals = {"n_swaps": 0, "n_improvements": 0, "n_pairs": 0}
        per_date_diffs = []
        for date in common_dates:
            p = prod_by_date[date]
            c = chal_by_date[date]
            pt = p.get("top_tickers", [])
            ct = c.get("top_tickers", [])

            # Overlap
            p30 = set(pt[:30])
            c30 = set(ct[:30])
            if p30 and c30:
                overlap_vals.append(len(p30 & c30) / 30.0)

            # Cutoff swaps
            fwd_col = args.horizon
            all_rows = snapshots.get(date, [])
            swaps = compute_cutoff_swaps(pt, ct, all_rows, fwd_col)
            swap_totals["n_swaps"] += swaps["n_swaps"]
            swap_totals["n_improvements"] += swaps["n_improvements"]
            swap_totals["n_pairs"] += swaps["n_swap_pairs"]

            # Per-date excess diff
            pe = _sf(str(p.get("ew_excess_xbi", "")))
            ce = _sf(str(c.get("ew_excess_xbi", "")))
            if pe == pe and ce == ce:
                per_date_diffs.append(ce - pe)

        h2h = {
            "common_dates": len(common_dates),
            "overlap_mean": _r(_safe_mean(overlap_vals)),
            "overlap_min": _r(min(overlap_vals)) if overlap_vals else None,
            "overlap_max": _r(max(overlap_vals)) if overlap_vals else None,
            "total_swaps": swap_totals["n_swaps"],
            "total_improvements": swap_totals["n_improvements"],
            "total_swap_pairs": swap_totals["n_pairs"],
            "swap_improvement_rate": (
                _r(swap_totals["n_improvements"] / swap_totals["n_pairs"]) if swap_totals["n_pairs"] > 0 else None
            ),
            "challenger_minus_prod_mean_pp": _r(_pp(_safe_mean(per_date_diffs))),
            "challenger_minus_prod_tstat": _r(_safe_tstat(per_date_diffs)),
            "challenger_wins": sum(1 for d in per_date_diffs if d > 0),
            "prod_wins": sum(1 for d in per_date_diffs if d < 0),
        }
        all_results["benchmark_h2h"] = h2h

        # 4. Print benchmark summary
        print("\n  === HEAD-TO-HEAD RESULTS ===")
        print(f"  Common dates: {h2h['common_dates']}")
        print(
            f"  Roster overlap (30): {_fmt_pct(h2h['overlap_mean'])} avg "
            f"(min {_fmt_pct(h2h['overlap_min'])}, max {_fmt_pct(h2h['overlap_max'])})"
        )
        print(
            f"  Cutoff swaps: {h2h['total_swaps']} names swapped, "
            f"{h2h['total_improvements']}/{h2h['total_swap_pairs']} improved "
            f"({_fmt_pct(h2h['swap_improvement_rate'])})"
        )
        print(
            f"  Challenger - Production excess: {_fmt(h2h['challenger_minus_prod_mean_pp'])}pp/mo "
            f"(t={_fmt(h2h['challenger_minus_prod_tstat'])})"
        )
        print(f"  Challenger wins: {h2h['challenger_wins']}, Production wins: {h2h['prod_wins']}")

        print("\n  --- Production ---")
        print(
            f"  Excess XBI: {_fmt(prod_agg.get('ew_excess_xbi_mean_pp'))}pp/mo "
            f"(t={_fmt(prod_agg.get('ew_excess_xbi_tstat'))})"
        )
        print(f"  Hit rate: {_fmt_pct(prod_agg.get('hit_rate'))}")
        print(f"  Turnover: {_fmt(prod_agg.get('turnover_mean'))}")
        pr = prod_agg.get("regime", {})
        print(
            f"  Regime: bear={_fmt(pr.get('bear', {}).get('mean_excess_pp'))}pp, "
            f"neutral={_fmt(pr.get('neutral', {}).get('mean_excess_pp'))}pp, "
            f"bull={_fmt(pr.get('bull', {}).get('mean_excess_pp'))}pp"
        )

        print("\n  --- Challenger (pairwise minimal) ---")
        print(
            f"  Excess XBI: {_fmt(chal_agg.get('ew_excess_xbi_mean_pp'))}pp/mo "
            f"(t={_fmt(chal_agg.get('ew_excess_xbi_tstat'))})"
        )
        print(f"  Hit rate: {_fmt_pct(chal_agg.get('hit_rate'))}")
        print(f"  Turnover: {_fmt(chal_agg.get('turnover_mean'))}")
        cr = chal_agg.get("regime", {})
        print(
            f"  Regime: bear={_fmt(cr.get('bear', {}).get('mean_excess_pp'))}pp, "
            f"neutral={_fmt(cr.get('neutral', {}).get('mean_excess_pp'))}pp, "
            f"bull={_fmt(cr.get('bull', {}).get('mean_excess_pp'))}pp"
        )

        # Year-by-year comparison
        print("\n  --- Year-by-Year ---")
        print("  Year  | Production | Challenger | Delta")
        print("  ------|------------|------------|------")
        prod_yy = prod_agg.get("by_year", {})
        chal_yy = chal_agg.get("by_year", {})
        all_years = sorted(set(list(prod_yy.keys()) + list(chal_yy.keys())))
        for yr in all_years:
            pe = prod_yy.get(yr, {}).get("mean_excess_pp")
            ce = chal_yy.get(yr, {}).get("mean_excess_pp")
            delta = None
            if pe is not None and ce is not None:
                delta = round(ce - pe, 2)
            print(f"  {yr}  | {_fmt(pe):>8}pp | {_fmt(ce):>8}pp | {_fmt(delta):>5}pp")

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
