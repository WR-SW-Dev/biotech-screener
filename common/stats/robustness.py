"""Leave-one-slice-out robustness harness.

Re-evaluates a model/signal while holding out key slices to detect
whether results are carried by one narrow pocket.

Usage:
    from common.stats.robustness import leave_one_slice_out

    result = leave_one_slice_out(
        snapshots, signal, y_col,
        slice_col="regime_63d",
        eval_fn=selector_delta_fn,
    )
"""
from __future__ import annotations

import math
import statistics
from typing import Any


def leave_one_slice_out(
    snapshots: dict[str, list[dict]],
    signal: str,
    y_col: str = "fwd_excess_xbi_63d",
    slice_col: str = "regime_63d",
    higher_is_better: bool = True,
    top_n: int = 30,
    eligible_col: str = "eligible",
) -> dict[str, Any]:
    """Leave-one-slice-out robustness test.

    For each unique value of slice_col, re-runs the signal evaluation
    with that slice removed. Reports held-out performance for each slice.

    Args:
        snapshots: {date: [row_dicts]}
        signal: signal column to evaluate
        y_col: forward return column
        slice_col: column to slice on (regime, year, mcap bucket, etc.)
        higher_is_better: signal direction
        top_n: top-N for selector evaluation
        eligible_col: eligibility filter column

    Returns:
        dict with per-slice results and stability verdict
    """
    # Collect all slices
    slice_values = set()
    for rows in snapshots.values():
        for r in rows:
            v = r.get(slice_col, "")
            if v and v != "":
                slice_values.add(v)

    if not slice_values:
        return {"error": f"no slice values found for {slice_col}"}

    # Full-sample evaluation
    full_result = _eval_selector_delta(
        snapshots, signal, y_col, higher_is_better,
        top_n, eligible_col, exclude_slice=None, slice_col=None,
    )

    # Per-slice leave-out evaluation
    slice_results = {}
    for sv in sorted(slice_values):
        result = _eval_selector_delta(
            snapshots, signal, y_col, higher_is_better,
            top_n, eligible_col, exclude_slice=sv, slice_col=slice_col,
        )
        slice_results[sv] = result

    # Stability analysis
    full_delta = full_result.get("mean_improvement_pp", 0) or 0
    deltas = {
        sv: (r.get("mean_improvement_pp", 0) or 0)
        for sv, r in slice_results.items()
    }
    worst_slice = min(deltas, key=deltas.get) if deltas else None
    best_slice = max(deltas, key=deltas.get) if deltas else None

    # Verdict
    if worst_slice and full_delta != 0:
        worst_delta = deltas[worst_slice]
        if full_delta > 0 and worst_delta <= 0:
            verdict = "UNSTABLE — worst slice turns negative"
        elif full_delta > 0 and worst_delta < full_delta * 0.5:
            verdict = "MODERATE — worst slice < 50% of full"
        elif full_delta > 0:
            verdict = "STABLE — robust across slices"
        else:
            verdict = "NEGATIVE — full sample is negative"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "signal": signal,
        "slice_col": slice_col,
        "full_sample": full_result,
        "leave_one_out": slice_results,
        "worst_slice": worst_slice,
        "worst_slice_delta": _round(deltas.get(worst_slice)),
        "best_slice": best_slice,
        "best_slice_delta": _round(deltas.get(best_slice)),
        "full_delta": _round(full_delta),
        "stability_verdict": verdict,
    }


def multi_slice_robustness(
    snapshots: dict[str, list[dict]],
    signal: str,
    y_col: str = "fwd_excess_xbi_63d",
    higher_is_better: bool = True,
    top_n: int = 30,
) -> dict[str, Any]:
    """Run leave-one-slice-out across all standard slice dimensions.

    Tests: year, regime, market_cap_bucket, catalyst_family,
    catalyst_bucket, stage_bucket.
    """
    slice_cols = {
        "year": "_year",  # synthetic: snapshot_date[:4]
        "regime": "regime_63d",
        "market_cap": "market_cap_bucket",
        "catalyst_family": "catalyst_family",
        "catalyst_bucket": "catalyst_bucket",
        "stage": "stage_bucket",
    }

    # Add synthetic year column
    augmented = {}
    for snap_date, rows in snapshots.items():
        new_rows = []
        for r in rows:
            r2 = dict(r)
            r2["_year"] = snap_date[:4]
            new_rows.append(r2)
        augmented[snap_date] = new_rows

    results = {}
    for label, col in slice_cols.items():
        result = leave_one_slice_out(
            augmented, signal, y_col,
            slice_col=col,
            higher_is_better=higher_is_better,
            top_n=top_n,
        )
        results[label] = result

    # Overall verdict
    verdicts = {
        label: r.get("stability_verdict", "")
        for label, r in results.items()
    }
    n_unstable = sum(
        1 for v in verdicts.values() if "UNSTABLE" in v
    )
    n_moderate = sum(
        1 for v in verdicts.values() if "MODERATE" in v
    )

    if n_unstable >= 2:
        overall = "FRAGILE — unstable across multiple dimensions"
    elif n_unstable == 1:
        overall = "CAUTIOUS — unstable in one dimension"
    elif n_moderate >= 2:
        overall = "MODERATE — some sensitivity"
    else:
        overall = "ROBUST — stable across all dimensions"

    return {
        "signal": signal,
        "slices": results,
        "verdicts": verdicts,
        "overall_verdict": overall,
    }


def _eval_selector_delta(
    snapshots, signal, y_col, higher_is_better,
    top_n, eligible_col, exclude_slice, slice_col,
) -> dict[str, Any]:
    """Compute selector delta for a signal, optionally excluding a slice."""
    improvements = []
    for snap_date, rows in sorted(snapshots.items()):
        # Filter
        eligible = []
        for r in rows:
            if _sf(r.get(eligible_col)) != 1.0:
                continue
            if exclude_slice and slice_col and r.get(slice_col) == exclude_slice:
                continue
            sv = _sf(r.get(signal))
            fwd = _sf(r.get(y_col))
            rank = _sf(r.get("actionable_rank"))
            if sv is not None and fwd is not None and rank is not None:
                eligible.append({
                    "signal": sv, "fwd": fwd, "rank": rank,
                })

        if len(eligible) < top_n:
            continue

        by_rank = sorted(eligible, key=lambda x: x["rank"])[:top_n]
        baseline = statistics.mean(e["fwd"] for e in by_rank)

        if higher_is_better:
            by_signal = sorted(eligible, key=lambda x: -x["signal"])
        else:
            by_signal = sorted(eligible, key=lambda x: x["signal"])
        selected = by_signal[:top_n]
        sel_ret = statistics.mean(e["fwd"] for e in selected)
        improvements.append(sel_ret - baseline)

    if not improvements:
        return {"mean_improvement_pp": None, "n_periods": 0}

    mean_imp = statistics.mean(improvements)
    return {
        "mean_improvement_pp": _round(mean_imp * 100),
        "t_stat": _round(_safe_tstat([v * 100 for v in improvements])),
        "hit_rate": _round(
            sum(1 for v in improvements if v > 0) / len(improvements)
        ),
        "n_periods": len(improvements),
    }


def _sf(v):
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return f if not math.isnan(f) else None
    except (ValueError, TypeError):
        return None


def _safe_tstat(vals):
    if len(vals) < 2:
        return None
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    return m / (s / len(vals) ** 0.5) if s > 1e-9 else None


def _round(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, d)
