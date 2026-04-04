#!/usr/bin/env python3
"""Timing Hazard Review Loop — first proving ground for Event EV.

Backfills timing hazard predictions across historical snapshots, detects
realized date revisions from cross-snapshot catalyst_days drift, and
scores the model's calibration with Brier/ECE.

Outcome definitions:
  ON_TIME  — no material date revision (>7d) detected in subsequent snapshots
  SLIP     — catalyst_days jumped up >7d (pushout) in a subsequent snapshot
  EARLY    — catalyst_days jumped down >7d (pullin) in a subsequent snapshot
  ROLLOVER — catalyst expired and was replaced by next pipeline event (excluded)

PIT safety: predictions use only data at prediction time; outcomes use
only subsequent snapshots. No model retraining — diagnostic only.

Output:
    output/timing_hazard_review/timing_hazard_review.json
    output/timing_hazard_review/timing_hazard_review.md
    output/timing_hazard_review/calibration_backfill.csv

Usage:
    python3 scripts/research/timing_hazard_review.py
    python3 scripts/research/timing_hazard_review.py --max-snapshots 20
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from common.stats.calibration import brier_score, expected_calibration_error, reliability_curve
from tools.compute_timing_hazard import compute_timing_hazard

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
OUTPUT_DIR = PROJECT_ROOT / "output" / "timing_hazard_review"

SCHEMA_VERSION = "timing_hazard_review.v1"

# Outcome detection parameters
DRIFT_THRESHOLD_DAYS = 7  # min drift to count as revision (excludes noise)
ROLLOVER_THRESHOLD = 30  # cd1 <= 2 and cd2 > this → rollover, not revision
OBSERVATION_WINDOW_DAYS = 90  # look forward this many calendar days for outcomes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sf(v, default=None):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _available_dates() -> List[str]:
    date_pat = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    return sorted(
        d.name
        for d in SNAPSHOTS_DIR.iterdir()
        if d.is_dir() and date_pat.match(d.name) and (d / "rankings.csv").exists()
    )


def _load_catalyst_days(snap_date: str) -> Dict[str, float]:
    """Load ticker -> catalyst_days mapping from a snapshot."""
    rpath = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    if not rpath.exists():
        return {}
    result = {}
    with open(rpath, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            cd = _sf(row.get("catalyst_days"))
            if t and cd is not None and cd > 0:
                result[t] = cd
    return result


# ---------------------------------------------------------------------------
# Step 1: Backfill predictions
# ---------------------------------------------------------------------------


def backfill_predictions(
    max_snapshots: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Run timing hazard model on each historical snapshot."""
    dates = _available_dates()
    if max_snapshots:
        dates = dates[-max_snapshots:]

    predictions = []
    for i, snap_date in enumerate(dates):
        print(f"  Backfilling {snap_date} ({i + 1}/{len(dates)})...")
        result = compute_timing_hazard(snap_date)
        if "error" in result:
            print(f"    Skipped: {result['error']}")
            continue

        for cat in result.get("catalysts", []):
            predictions.append(
                {
                    "prediction_date": snap_date,
                    "ticker": cat["ticker"],
                    "rank": cat["rank"],
                    "catalyst_days": cat["catalyst_days"],
                    "catalyst_event_type": cat["catalyst_event_type"],
                    "catalyst_family": cat["catalyst_family"],
                    "is_hard_catalyst": cat["is_hard_catalyst"],
                    "on_time_prob": cat["on_time_prob"],
                    "slip_prob_30d": cat["slip_prob_30d"],
                    "slip_prob_60d_plus": cat["slip_prob_60d_plus"],
                    "timing_confidence_bucket": cat["timing_confidence_bucket"],
                    "execution_warning_flag": cat["execution_warning_flag"],
                    "warning_reasons": cat.get("warning_reasons", []),
                    "top_driver_1": cat.get("top_driver_1"),
                    "last_update_age": cat.get("last_update_age"),
                }
            )

    print(f"  Total predictions: {len(predictions)} across {len(dates)} snapshots")
    return predictions


# ---------------------------------------------------------------------------
# Step 2: Detect outcomes
# ---------------------------------------------------------------------------


def detect_outcomes(
    predictions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Scan forward snapshots for date revisions and classify outcomes."""
    dates = _available_dates()
    date_to_idx = {d: i for i, d in enumerate(dates)}

    # Pre-load all catalyst_days maps
    print("  Loading catalyst_days for all snapshots...")
    all_catalyst_days: Dict[str, Dict[str, float]] = {}
    for d in dates:
        all_catalyst_days[d] = _load_catalyst_days(d)

    matched = []
    for pred in predictions:
        pred_date = pred["prediction_date"]
        ticker = pred["ticker"]
        pred_idx = date_to_idx.get(pred_date)
        if pred_idx is None:
            continue

        outcome = "ON_TIME"
        revision_drift = 0.0
        revision_date = None

        # Scan forward snapshots
        for j in range(pred_idx + 1, len(dates)):
            fwd_date = dates[j]
            # Check observation window
            elapsed = (date.fromisoformat(fwd_date) - date.fromisoformat(pred_date)).days
            if elapsed > OBSERVATION_WINDOW_DAYS:
                break

            fwd_cd = all_catalyst_days.get(fwd_date, {}).get(ticker)
            if fwd_cd is None:
                continue  # ticker dropped from rankings

            # Prior snapshot for drift calculation
            prior_date = dates[j - 1]
            prior_cd = all_catalyst_days.get(prior_date, {}).get(ticker)
            if prior_cd is None:
                continue

            prior_elapsed = (date.fromisoformat(fwd_date) - date.fromisoformat(prior_date)).days
            expected_cd = prior_cd - prior_elapsed
            drift = fwd_cd - expected_cd

            # Rollover detection: catalyst expired and got replaced
            if prior_cd <= 2 and fwd_cd > ROLLOVER_THRESHOLD:
                outcome = "ROLLOVER"
                revision_drift = drift
                revision_date = fwd_date
                break

            # Material revision detection
            if drift > DRIFT_THRESHOLD_DAYS:
                outcome = "SLIP"
                revision_drift = drift
                revision_date = fwd_date
                break
            elif drift < -DRIFT_THRESHOLD_DAYS:
                outcome = "EARLY"
                revision_drift = drift
                revision_date = fwd_date
                break

        record = {**pred}
        record["outcome"] = outcome
        record["revision_drift_days"] = round(revision_drift, 1)
        record["revision_date"] = revision_date
        record["actual_on_time"] = 1 if outcome == "ON_TIME" else 0
        matched.append(record)

    # Filter out rollovers for scoring
    scoreable = [m for m in matched if m["outcome"] != "ROLLOVER"]
    rollovers = [m for m in matched if m["outcome"] == "ROLLOVER"]
    print(f"  Matched: {len(matched)} total, {len(scoreable)} scoreable, {len(rollovers)} rollovers excluded")
    return matched


# ---------------------------------------------------------------------------
# Step 3: Score calibration
# ---------------------------------------------------------------------------


def score_calibration(matched: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Score timing hazard predictions against realized outcomes."""
    scoreable = [m for m in matched if m["outcome"] != "ROLLOVER"]
    if not scoreable:
        return {"error": "no scoreable records"}

    predicted = np.array([m["on_time_prob"] for m in scoreable])
    actual = np.array([m["actual_on_time"] for m in scoreable])

    # Overall calibration
    brier = float(brier_score(predicted, actual))
    ece = float(expected_calibration_error(predicted, actual, n_bins=5))
    rel_curve = reliability_curve(predicted, actual, n_bins=5)

    # Base rate
    base_rate = float(np.mean(actual))
    mean_predicted = float(np.mean(predicted))

    # Verdict
    if ece < 0.05:
        verdict = "GOOD — calibrated for sizing"
    elif ece < 0.10:
        verdict = "FAIR — calibrated for ranking"
    elif ece < 0.15:
        verdict = "MARGINAL — directional only"
    else:
        verdict = "POOR — needs recalibration"

    # Breakdowns
    breakdowns = {}

    # By confidence bucket
    bucket_results = {}
    for bucket in ["HIGH", "MEDIUM", "LOW", "STALE"]:
        subset = [m for m in scoreable if m["timing_confidence_bucket"] == bucket]
        if len(subset) >= 5:
            p = np.array([m["on_time_prob"] for m in subset])
            a = np.array([m["actual_on_time"] for m in subset])
            bucket_results[bucket] = {
                "n": len(subset),
                "brier": round(float(brier_score(p, a)), 4),
                "base_rate": round(float(np.mean(a)), 4),
                "mean_predicted": round(float(np.mean(p)), 4),
            }
        else:
            bucket_results[bucket] = {"n": len(subset), "insufficient": True}
    breakdowns["by_confidence_bucket"] = bucket_results

    # By event family
    family_results = {}
    for family in ["CLINICAL", "REGULATORY"]:
        subset = [m for m in scoreable if m["catalyst_family"] == family]
        if len(subset) >= 5:
            p = np.array([m["on_time_prob"] for m in subset])
            a = np.array([m["actual_on_time"] for m in subset])
            family_results[family] = {
                "n": len(subset),
                "brier": round(float(brier_score(p, a)), 4),
                "base_rate": round(float(np.mean(a)), 4),
                "mean_predicted": round(float(np.mean(p)), 4),
            }
        else:
            family_results[family] = {"n": len(subset), "insufficient": True}
    breakdowns["by_family"] = family_results

    # By hard vs soft catalyst
    for label, is_hard in [("hard_catalyst", True), ("soft_catalyst", False)]:
        subset = [m for m in scoreable if m["is_hard_catalyst"] == is_hard]
        if len(subset) >= 5:
            p = np.array([m["on_time_prob"] for m in subset])
            a = np.array([m["actual_on_time"] for m in subset])
            breakdowns[label] = {
                "n": len(subset),
                "brier": round(float(brier_score(p, a)), 4),
                "base_rate": round(float(np.mean(a)), 4),
                "mean_predicted": round(float(np.mean(p)), 4),
            }
        else:
            breakdowns[label] = {"n": len(subset), "insufficient": True}

    # Warning flag accuracy
    warned = [m for m in scoreable if m["execution_warning_flag"]]
    if warned:
        warn_slip_rate = sum(1 for m in warned if m["outcome"] == "SLIP") / len(warned)
        breakdowns["warning_flag"] = {
            "n_warned": len(warned),
            "slip_rate_of_warned": round(warn_slip_rate, 4),
            "precision": round(warn_slip_rate, 4),
        }
    else:
        breakdowns["warning_flag"] = {"n_warned": 0}

    # Outcome distribution
    outcome_dist = Counter(m["outcome"] for m in matched)

    return {
        "n_scoreable": len(scoreable),
        "n_total": len(matched),
        "outcome_distribution": dict(outcome_dist),
        "brier_score": round(brier, 4),
        "ece": round(ece, 4),
        "base_rate": round(base_rate, 4),
        "mean_predicted": round(mean_predicted, 4),
        "overconfidence": round(mean_predicted - base_rate, 4),
        "reliability_curve": rel_curve,
        "verdict": verdict,
        "breakdowns": breakdowns,
    }


# ---------------------------------------------------------------------------
# Step 4: Feature attribution
# ---------------------------------------------------------------------------


def feature_attribution(matched: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare feature distributions between ON_TIME and SLIP outcomes."""
    scoreable = [m for m in matched if m["outcome"] != "ROLLOVER"]
    on_time = [m for m in scoreable if m["outcome"] == "ON_TIME"]
    slips = [m for m in scoreable if m["outcome"] == "SLIP"]

    if not on_time or not slips:
        return {"error": "insufficient data for attribution"}

    features = [
        ("catalyst_days", "catalyst_days"),
        ("on_time_prob", "on_time_prob"),
        ("is_hard_catalyst", "is_hard_catalyst"),
        ("last_update_age", "last_update_age"),
    ]

    comparisons = {}
    for label, field in features:
        ot_vals = [_sf(m.get(field)) for m in on_time]
        sl_vals = [_sf(m.get(field)) for m in slips]
        ot_vals = [v for v in ot_vals if v is not None]
        sl_vals = [v for v in sl_vals if v is not None]

        if ot_vals and sl_vals:
            comparisons[label] = {
                "on_time_mean": round(statistics.mean(ot_vals), 2),
                "slip_mean": round(statistics.mean(sl_vals), 2),
                "delta": round(statistics.mean(sl_vals) - statistics.mean(ot_vals), 2),
                "on_time_n": len(ot_vals),
                "slip_n": len(sl_vals),
            }

    # Top driver frequency for slips vs on_time
    driver_freq_slip = Counter()
    driver_freq_ontime = Counter()
    for m in slips:
        d1 = m.get("top_driver_1")
        if d1 and isinstance(d1, dict):
            driver_freq_slip[d1.get("feature", "?")] += 1
    for m in on_time:
        d1 = m.get("top_driver_1")
        if d1 and isinstance(d1, dict):
            driver_freq_ontime[d1.get("feature", "?")] += 1

    return {
        "feature_comparisons": comparisons,
        "top_driver_frequency_slip": dict(driver_freq_slip.most_common(10)),
        "top_driver_frequency_ontime": dict(driver_freq_ontime.most_common(10)),
    }


# ---------------------------------------------------------------------------
# Step 5: Failure cases
# ---------------------------------------------------------------------------


def find_failure_cases(matched: List[Dict[str, Any]], n: int = 15) -> List[Dict[str, Any]]:
    """Find worst calibration misses: high P(on_time) that slipped, and low P that were on time."""
    scoreable = [m for m in matched if m["outcome"] != "ROLLOVER"]

    # High confidence slips (worst failures)
    confident_slips = sorted(
        [m for m in scoreable if m["outcome"] == "SLIP"],
        key=lambda m: -m["on_time_prob"],
    )[:n]

    # Low confidence on-time (model was pessimistic but catalyst was fine)
    pessimistic_hits = sorted(
        [m for m in scoreable if m["outcome"] == "ON_TIME"],
        key=lambda m: m["on_time_prob"],
    )[:n]

    return {
        "confident_slips": [
            {
                "ticker": m["ticker"],
                "prediction_date": m["prediction_date"],
                "on_time_prob": m["on_time_prob"],
                "catalyst_days": m["catalyst_days"],
                "confidence_bucket": m["timing_confidence_bucket"],
                "revision_drift": m["revision_drift_days"],
                "revision_date": m["revision_date"],
            }
            for m in confident_slips
        ],
        "pessimistic_hits": [
            {
                "ticker": m["ticker"],
                "prediction_date": m["prediction_date"],
                "on_time_prob": m["on_time_prob"],
                "catalyst_days": m["catalyst_days"],
                "confidence_bucket": m["timing_confidence_bucket"],
            }
            for m in pessimistic_hits
        ],
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_report_md(results: Dict[str, Any]) -> str:
    lines = []
    cal = results["calibration"]
    lines.append("# Timing Hazard Review — First Calibration Assessment")
    lines.append("")
    lines.append(f"**Verdict: {cal['verdict']}**")
    lines.append("")

    # Summary
    lines.append("## Calibration Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Scoreable records | {cal['n_scoreable']:,} |")
    lines.append(f"| Brier score | {cal['brier_score']:.4f} |")
    lines.append(f"| ECE | {cal['ece']:.4f} |")
    lines.append(f"| Base rate (actual on-time %) | {cal['base_rate']:.1%} |")
    lines.append(f"| Mean predicted P(on_time) | {cal['mean_predicted']:.1%} |")
    lines.append(f"| Overconfidence | {cal['overconfidence']:+.1%} |")
    lines.append("")

    # Outcome distribution
    lines.append("## Outcome Distribution")
    lines.append("")
    lines.append("| Outcome | Count |")
    lines.append("|---------|-------|")
    for outcome, count in sorted(cal["outcome_distribution"].items()):
        lines.append(f"| {outcome} | {count:,} |")
    lines.append("")

    # Reliability curve
    rc = cal.get("reliability_curve", {})
    bins = rc.get("bins", [])
    if bins:
        lines.append("## Reliability Curve")
        lines.append("")
        lines.append("| Bin | Predicted | Actual | Gap | Count |")
        lines.append("|-----|-----------|--------|-----|-------|")
        for b in bins:
            lines.append(
                f"| {b['bin_idx']} | {b['mean_predicted']:.3f} | "
                f"{b['mean_actual']:.3f} | {b['gap']:.3f} | {b['count']} |"
            )
        lines.append("")

    # Breakdowns
    bkd = cal.get("breakdowns", {})

    lines.append("## Breakdowns")
    lines.append("")

    # By confidence bucket
    lines.append("### By Confidence Bucket")
    lines.append("")
    lines.append("| Bucket | N | Brier | Base Rate | Mean Pred |")
    lines.append("|--------|---|-------|-----------|-----------|")
    for bucket in ["HIGH", "MEDIUM", "LOW", "STALE"]:
        info = bkd.get("by_confidence_bucket", {}).get(bucket, {})
        if info.get("insufficient"):
            lines.append(f"| {bucket} | {info.get('n', 0)} | — | — | — |")
        elif "brier" in info:
            lines.append(
                f"| {bucket} | {info['n']} | {info['brier']:.4f} | "
                f"{info['base_rate']:.3f} | {info['mean_predicted']:.3f} |"
            )
    lines.append("")

    # By family
    lines.append("### By Event Family")
    lines.append("")
    lines.append("| Family | N | Brier | Base Rate | Mean Pred |")
    lines.append("|--------|---|-------|-----------|-----------|")
    for fam in ["CLINICAL", "REGULATORY"]:
        info = bkd.get("by_family", {}).get(fam, {})
        if info.get("insufficient"):
            lines.append(f"| {fam} | {info.get('n', 0)} | — | — | — |")
        elif "brier" in info:
            lines.append(
                f"| {fam} | {info['n']} | {info['brier']:.4f} | "
                f"{info['base_rate']:.3f} | {info['mean_predicted']:.3f} |"
            )
    lines.append("")

    # Hard vs soft
    lines.append("### By Catalyst Hardness")
    lines.append("")
    lines.append("| Type | N | Brier | Base Rate | Mean Pred |")
    lines.append("|------|---|-------|-----------|-----------|")
    for label in ["hard_catalyst", "soft_catalyst"]:
        info = bkd.get(label, {})
        if info.get("insufficient"):
            lines.append(f"| {label} | {info.get('n', 0)} | — | — | — |")
        elif "brier" in info:
            lines.append(
                f"| {label} | {info['n']} | {info['brier']:.4f} | "
                f"{info['base_rate']:.3f} | {info['mean_predicted']:.3f} |"
            )
    lines.append("")

    # Warning flag
    wf = bkd.get("warning_flag", {})
    if wf.get("n_warned", 0) > 0:
        lines.append("### Warning Flag Accuracy")
        lines.append("")
        lines.append(f"- Warned: {wf['n_warned']}")
        lines.append(f"- Slip rate of warned: {wf.get('slip_rate_of_warned', 0):.1%}")
        lines.append("")

    # Feature attribution
    attr = results.get("attribution", {})
    comps = attr.get("feature_comparisons", {})
    if comps:
        lines.append("## Feature Attribution (ON_TIME vs SLIP)")
        lines.append("")
        lines.append("| Feature | ON_TIME mean | SLIP mean | Delta |")
        lines.append("|---------|-------------|-----------|-------|")
        for feat, info in comps.items():
            lines.append(
                f"| {feat} | {info['on_time_mean']:.2f} | " f"{info['slip_mean']:.2f} | {info['delta']:+.2f} |"
            )
        lines.append("")

    # Failure cases
    failures = results.get("failure_cases", {})
    confident_slips = failures.get("confident_slips", [])
    if confident_slips:
        lines.append("## Worst Failures: High-Confidence Slips")
        lines.append("")
        lines.append("| Ticker | Date | P(on_time) | Days | Bucket | Drift | Revision |")
        lines.append("|--------|------|-----------|------|--------|-------|----------|")
        for f in confident_slips[:10]:
            lines.append(
                f"| {f['ticker']} | {f['prediction_date']} | "
                f"{f['on_time_prob']:.2f} | {f['catalyst_days']} | "
                f"{f['confidence_bucket']} | {f['revision_drift']:+.0f}d | "
                f"{f['revision_date'] or '?'} |"
            )
        lines.append("")

    lines.append(f"*Generated: {results.get('generated_at', '')}*")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Timing Hazard Review Loop")
    parser.add_argument(
        "--max-snapshots",
        type=int,
        default=None,
        help="Limit number of snapshots to process (default: all)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("TIMING HAZARD REVIEW LOOP")
    print("=" * 70)

    # Step 1: Backfill
    print("\nStep 1: Backfilling predictions...")
    predictions = backfill_predictions(max_snapshots=args.max_snapshots)
    if not predictions:
        print("ERROR: No predictions generated")
        sys.exit(1)

    # Step 2: Detect outcomes
    print("\nStep 2: Detecting outcomes...")
    matched = detect_outcomes(predictions)
    if not matched:
        print("ERROR: No matched records")
        sys.exit(1)

    # Step 3: Score calibration
    print("\nStep 3: Scoring calibration...")
    calibration = score_calibration(matched)
    if "error" in calibration:
        print(f"ERROR: {calibration['error']}")
        sys.exit(1)

    # Step 4: Feature attribution
    print("\nStep 4: Computing feature attribution...")
    attribution = feature_attribution(matched)

    # Step 5: Failure cases
    print("\nStep 5: Finding failure cases...")
    failure_cases = find_failure_cases(matched)

    # Assemble results
    results = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_snapshots": len(set(m["prediction_date"] for m in matched)),
        "n_predictions": len(predictions),
        "n_matched": len(matched),
        "calibration": calibration,
        "attribution": attribution,
        "failure_cases": failure_cases,
    }

    # Write outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "timing_hazard_review.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  JSON: {json_path}")

    md_path = OUTPUT_DIR / "timing_hazard_review.md"
    md_text = format_report_md(results)
    md_path.write_text(md_text, encoding="utf-8")
    print(f"  Markdown: {md_path}")

    # Write CSV panel
    csv_path = OUTPUT_DIR / "calibration_backfill.csv"
    scoreable = [m for m in matched if m["outcome"] != "ROLLOVER"]
    if scoreable:
        fields = [
            "prediction_date",
            "ticker",
            "catalyst_days",
            "catalyst_event_type",
            "catalyst_family",
            "is_hard_catalyst",
            "on_time_prob",
            "timing_confidence_bucket",
            "execution_warning_flag",
            "outcome",
            "actual_on_time",
            "revision_drift_days",
            "revision_date",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(scoreable)
        print(f"  CSV: {csv_path} ({len(scoreable)} rows)")

    # Print summary
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"  Verdict: {calibration['verdict']}")
    print(f"  Brier:   {calibration['brier_score']:.4f}")
    print(f"  ECE:     {calibration['ece']:.4f}")
    print(f"  Base rate (actual on-time): {calibration['base_rate']:.1%}")
    print(f"  Mean predicted:             {calibration['mean_predicted']:.1%}")
    print(f"  Overconfidence:             {calibration['overconfidence']:+.1%}")
    print(f"  Outcomes: {calibration['outcome_distribution']}")


if __name__ == "__main__":
    main()
