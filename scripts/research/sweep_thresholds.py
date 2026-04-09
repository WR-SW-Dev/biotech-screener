#!/usr/bin/env python3
"""Threshold sensitivity sweep — measure impact of key parameter changes.

For each parameter in the sweep grid, creates a variant ruleset, reranks
a sample of snapshots, and measures top-K overlap and rank shift vs baseline.

Read-only research tool — does not modify production rulesets.

Output:
    output/research/threshold_sweep/{param}_sweep.json
    output/research/threshold_sweep/summary.md

Usage:
    python scripts/research/sweep_thresholds.py
    python scripts/research/sweep_thresholds.py --params tier_a_optionality_floor,rebalance_buffer_ranks
    python scripts/research/sweep_thresholds.py --top-k 60 --sample-dates 20
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sweep_thresholds")

# ---------------------------------------------------------------------------
# Sweep grid: param -> list of values to test
# ---------------------------------------------------------------------------
SWEEP_GRID = {
    "tier_a_optionality_floor": [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75],
    "tier_b_optionality_floor": [0.15, 0.20, 0.25, 0.30, 0.35, 0.40],
    "catalyst_near_days": [60, 90, 120, 150, 180],
    "catalyst_mid_days": [120, 150, 180, 210, 240],
    "rebalance_buffer_ranks": [0, 10, 20, 30, 40, 50],
    "institutional_sort_weight": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
    "calendar_alpha_sort_weight": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
    "binary_91_180_clinical_quality_weight": [0.0, 0.25, 0.5, 0.75, 1.0],
}


def _is_promoted(name: str) -> bool:
    return len(name) == 10 and not name.startswith("_") and name != "state"


def _sample_dates(snapshots_dir: Path, n: int) -> List[str]:
    """Sample n evenly spaced promoted snapshot dates."""
    all_dates = sorted(d.name for d in snapshots_dir.iterdir() if d.is_dir() and _is_promoted(d.name))
    if len(all_dates) <= n:
        return all_dates
    step = max(1, len(all_dates) // n)
    return all_dates[::step][:n]


def _load_rankings(snap_dir: Path) -> List[Dict[str, str]]:
    path = snap_dir / "rankings.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _get_top_k(rows: List[Dict[str, str]], k: int) -> List[str]:
    """Get top-k tickers by actionable_rank."""
    ranked = []
    for r in rows:
        rank_str = r.get("actionable_rank", "")
        try:
            ranked.append((float(rank_str), r.get("ticker", "")))
        except (ValueError, TypeError):
            pass
    ranked.sort()
    return [t for _, t in ranked[:k]]


def _compute_overlap(baseline_top: List[str], candidate_top: List[str]) -> float:
    """Compute overlap fraction between two top-K lists."""
    if not baseline_top:
        return 1.0
    return len(set(baseline_top) & set(candidate_top)) / len(baseline_top)


def _compute_max_rank_shift(
    baseline_rows: List[Dict[str, str]],
    candidate_rows: List[Dict[str, str]],
    k: int,
) -> int:
    """Compute max rank shift for names in baseline top-K."""
    baseline_ranks = {}
    for r in baseline_rows:
        try:
            baseline_ranks[r["ticker"]] = float(r["actionable_rank"])
        except (ValueError, TypeError, KeyError):
            pass

    candidate_ranks = {}
    for r in candidate_rows:
        try:
            candidate_ranks[r["ticker"]] = float(r["actionable_rank"])
        except (ValueError, TypeError, KeyError):
            pass

    baseline_top = sorted(baseline_ranks, key=baseline_ranks.get)[:k]
    max_shift = 0
    for t in baseline_top:
        if t in candidate_ranks:
            shift = abs(candidate_ranks[t] - baseline_ranks[t])
            max_shift = max(max_shift, shift)
    return int(max_shift)


def sweep_one_param(
    param: str,
    values: List[Any],
    baseline_ruleset: dict,
    snapshots_dir: Path,
    sample_dates: List[str],
    top_k: int,
) -> Dict[str, Any]:
    """Sweep one parameter and measure impact."""
    import tempfile

    from decision_engine import DecisionRuleset
    from scripts.research.rerank_snapshots import rerank

    baseline_value = baseline_ruleset.get(param)
    results = []

    for value in values:
        is_baseline = value == baseline_value

        # Create variant ruleset
        variant = deepcopy(baseline_ruleset)
        variant[param] = value

        # Handle coupled params
        if param == "calendar_alpha_sort_weight":
            variant["enable_calendar_alpha_sort"] = value > 0
        if param == "institutional_sort_weight":
            variant["enable_institutional_sort_signal"] = value > 0

        # Write to temp file and load via from_json
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as tf:
                json.dump(variant, tf, indent=2)
                tf_path = tf.name
            variant_rs = DecisionRuleset.from_json(tf_path)
            Path(tf_path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Skipping %s=%s: %s", param, value, e)
            continue

        overlaps = []
        max_shifts = []

        for date in sample_dates:
            baseline_rows = _load_rankings(snapshots_dir / date)
            if len(baseline_rows) < 20:
                continue

            baseline_top = _get_top_k(baseline_rows, top_k)

            # Rerank
            candidate_rows = deepcopy(baseline_rows)
            try:
                candidate_rows = rerank(candidate_rows, variant_rs)
            except Exception:
                continue

            candidate_top = _get_top_k(candidate_rows, top_k)

            overlap = _compute_overlap(baseline_top, candidate_top)
            max_shift = _compute_max_rank_shift(baseline_rows, candidate_rows, top_k)

            overlaps.append(overlap)
            max_shifts.append(max_shift)

        if overlaps:
            mean_overlap = sum(overlaps) / len(overlaps)
            mean_shift = sum(max_shifts) / len(max_shifts)
            min_overlap = min(overlaps)
        else:
            mean_overlap = None
            mean_shift = None
            min_overlap = None

        results.append(
            {
                "value": value,
                "is_baseline": is_baseline,
                "mean_top_k_overlap": round(mean_overlap, 4) if mean_overlap is not None else None,
                "min_top_k_overlap": round(min_overlap, 4) if min_overlap is not None else None,
                "mean_max_rank_shift": round(mean_shift, 1) if mean_shift is not None else None,
                "n_dates": len(overlaps),
            }
        )

        label = " ← BASELINE" if is_baseline else ""
        logger.info(
            "  %s=%s: overlap=%.3f shift=%.1f%s",
            param,
            value,
            mean_overlap or 0,
            mean_shift or 0,
            label,
        )

    return {
        "param": param,
        "baseline_value": baseline_value,
        "grid": results,
    }


def format_sweep_md(all_results: List[Dict[str, Any]], top_k: int) -> str:
    lines = []
    lines.append("# Threshold Sensitivity Sweep")
    lines.append("")
    lines.append(f"Top-K: {top_k}")
    lines.append("")

    for param_result in all_results:
        param = param_result["param"]
        baseline = param_result["baseline_value"]
        lines.append(f"## {param} (baseline={baseline})")
        lines.append("")
        lines.append("| Value | Overlap | Min Overlap | Max Shift | Baseline? |")
        lines.append("|-------|---------|-------------|-----------|-----------|")

        for g in param_result["grid"]:
            overlap = f"{g['mean_top_k_overlap']:.3f}" if g["mean_top_k_overlap"] is not None else "n/a"
            min_ov = f"{g['min_top_k_overlap']:.3f}" if g["min_top_k_overlap"] is not None else "n/a"
            shift = f"{g['mean_max_rank_shift']:.1f}" if g["mean_max_rank_shift"] is not None else "n/a"
            marker = "**yes**" if g["is_baseline"] else ""
            lines.append(f"| {g['value']} | {overlap} | {min_ov} | {shift} | {marker} |")
        lines.append("")

        # Classify sensitivity
        overlaps = [g["mean_top_k_overlap"] for g in param_result["grid"] if g["mean_top_k_overlap"] is not None]
        if overlaps:
            spread = max(overlaps) - min(overlaps)
            if spread < 0.02:
                sensitivity = "INSENSITIVE"
            elif spread < 0.05:
                sensitivity = "LOW"
            elif spread < 0.10:
                sensitivity = "MODERATE"
            else:
                sensitivity = "HIGH"
            lines.append(f"Sensitivity: **{sensitivity}** (overlap spread: {spread:.3f})")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Threshold sensitivity sweep")
    parser.add_argument("--params", help="Comma-separated params to sweep (default: all)")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--sample-dates", type=int, default=20)
    parser.add_argument("--snapshots-dir", type=Path, default=REPO_ROOT / "data" / "snapshots")
    parser.add_argument(
        "--ruleset",
        type=Path,
        default=REPO_ROOT / "production_data" / "decision_rulesets" / "v1.11.0_b91_clinical_quality_w05_candidate.json",
    )
    args = parser.parse_args()

    with open(args.ruleset, encoding="utf-8") as f:
        baseline_ruleset = json.load(f)

    params = args.params.split(",") if args.params else list(SWEEP_GRID.keys())
    dates = _sample_dates(args.snapshots_dir, args.sample_dates)
    logger.info("Sweeping %d params over %d sample dates (top-%d)", len(params), len(dates), args.top_k)

    out_dir = REPO_ROOT / "output" / "research" / "threshold_sweep"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_results = []
    for param in params:
        if param not in SWEEP_GRID:
            logger.warning("Unknown param: %s, skipping", param)
            continue
        logger.info("Sweeping %s ...", param)
        result = sweep_one_param(
            param,
            SWEEP_GRID[param],
            baseline_ruleset,
            args.snapshots_dir,
            dates,
            args.top_k,
        )
        all_results.append(result)

        with open(out_dir / f"{param}_sweep.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)

    # Write summary
    md = format_sweep_md(all_results, args.top_k)
    (out_dir / "summary.md").write_text(md, encoding="utf-8")
    logger.info("Summary → %s", out_dir / "summary.md")

    with open(out_dir / "all_sweeps.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, default=str)


if __name__ == "__main__":
    main()
