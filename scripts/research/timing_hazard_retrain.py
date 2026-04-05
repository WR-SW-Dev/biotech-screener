#!/usr/bin/env python3
"""Timing Hazard Model Retraining — learn from 5,918 paired records.

Takes the calibration backfill from timing_hazard_review.py and:
  1. Retrains the logistic model on realized outcomes
  2. Tests segmented models (by event family, by catalyst hardness)
  3. Tests Platt/isotonic recalibration on raw predictions
  4. Compares all variants against baselines
  5. Outputs retrained coefficients (NOT auto-promoted)

Output:
    output/timing_hazard_retrain/retrain_report.json
    output/timing_hazard_retrain/retrain_report.md
    output/timing_hazard_retrain/retrained_coefficients.json

Usage:
    python3 scripts/research/timing_hazard_retrain.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from common.stats.calibration import brier_score, expected_calibration_error
from event_ev.timing_hazard import TimingHazardModel, _sigmoid
from event_ledger import classify_catalyst_family

BACKFILL_CSV = PROJECT_ROOT / "output" / "timing_hazard_review" / "calibration_backfill.csv"
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
OUTPUT_DIR = PROJECT_ROOT / "output" / "timing_hazard_retrain"

SCHEMA_VERSION = "timing_hazard_retrain.v1"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _sf(v, default=None):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def load_training_data() -> List[Dict[str, Any]]:
    """Load paired prediction/outcome records from backfill CSV."""
    if not BACKFILL_CSV.exists():
        print(f"ERROR: {BACKFILL_CSV} not found. Run timing_hazard_review.py first.")
        sys.exit(1)

    rows = []
    with open(BACKFILL_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            # Exclude EARLY outcomes from training — they are benign (catalyst arrived sooner)
            outcome = r.get("outcome", "")
            if outcome == "EARLY":
                continue
            rows.append(
                {
                    "prediction_date": r["prediction_date"],
                    "ticker": r["ticker"],
                    "catalyst_days": _sf(r["catalyst_days"], 0),
                    "catalyst_event_type": r.get("catalyst_event_type", ""),
                    "catalyst_family": r.get("catalyst_family", "")
                    or classify_catalyst_family(r.get("catalyst_event_type", "")),
                    "is_hard_catalyst": r.get("is_hard_catalyst") == "True",
                    "on_time_prob_current": _sf(r["on_time_prob"], 0.5),
                    "timing_confidence_bucket": r.get("timing_confidence_bucket", ""),
                    "actual_on_time": int(r.get("actual_on_time", 0)),
                    "revision_drift_days": _sf(r.get("revision_drift_days"), 0),
                }
            )
    return rows


def extract_features_from_snapshot(
    ticker: str,
    snap_date: str,
) -> Optional[Dict[str, float]]:
    """Extract timing features from a snapshot using the production model."""
    from tools.compute_timing_hazard import _build_catalyst_node, _load_trial_update_dates, _parse_date

    rankings_path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    if not rankings_path.exists():
        return None

    with open(rankings_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker") == ticker:
                snap_d = _parse_date(snap_date)
                if not snap_d:
                    return None
                trial_dates = _load_trial_update_dates()
                node = _build_catalyst_node(row, snap_d, trial_dates, None)
                if not node:
                    return None
                model = TimingHazardModel()
                features = model._extract_features(node, snap_d)
                return features
    return None


# ---------------------------------------------------------------------------
# Training approaches
# ---------------------------------------------------------------------------


def train_logistic_global(
    records: List[Dict],
    features_map: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    """Train a single global logistic model on all records."""
    # Build training data for TimingHazardModel.train_on_historical
    training_data = []
    for r in records:
        key = f"{r['ticker']}_{r['prediction_date']}"
        feats = features_map.get(key)
        if not feats:
            continue
        training_data.append(
            {
                "features": feats,
                "actual_on_time": r["actual_on_time"],
            }
        )

    if len(training_data) < 20:
        return {"error": "insufficient data", "n": len(training_data)}

    model = TimingHazardModel()
    result = model.train_on_historical(training_data)

    # Evaluate on training set (in-sample — we'll note this)
    predicted = []
    actual = []
    for td in training_data:
        logit = model._compute_logit(td["features"])
        predicted.append(_sigmoid(logit))
        actual.append(float(td["actual_on_time"]))

    p = np.array(predicted)
    a = np.array(actual)

    return {
        "name": "retrained_global",
        "n_training": len(training_data),
        "coefficients": result.get("coefficients", {}),
        "training_accuracy": result.get("accuracy"),
        "training_loss": result.get("final_loss"),
        "brier": round(float(brier_score(p, a)), 4),
        "ece": round(float(expected_calibration_error(p, a, n_bins=5)), 4),
        "base_rate": round(float(np.mean(a)), 4),
        "mean_predicted": round(float(np.mean(p)), 4),
    }


def train_logistic_segmented(
    records: List[Dict],
    features_map: Dict[str, Dict[str, float]],
    segment_field: str,
    segment_values: List[str],
) -> Dict[str, Any]:
    """Train separate logistic models per segment."""
    segment_results = {}

    for seg_val in segment_values:
        if segment_field == "is_hard_catalyst":
            seg_records = [r for r in records if r[segment_field] == (seg_val == "True")]
        else:
            seg_records = [r for r in records if r.get(segment_field, "") == seg_val]

        training_data = []
        for r in seg_records:
            key = f"{r['ticker']}_{r['prediction_date']}"
            feats = features_map.get(key)
            if not feats:
                continue
            training_data.append(
                {
                    "features": feats,
                    "actual_on_time": r["actual_on_time"],
                }
            )

        if len(training_data) < 20:
            segment_results[seg_val] = {
                "n": len(training_data),
                "insufficient": True,
            }
            continue

        model = TimingHazardModel()
        result = model.train_on_historical(training_data)

        predicted = []
        actual = []
        for td in training_data:
            logit = model._compute_logit(td["features"])
            predicted.append(_sigmoid(logit))
            actual.append(float(td["actual_on_time"]))

        p = np.array(predicted)
        a = np.array(actual)

        segment_results[seg_val] = {
            "n": len(training_data),
            "coefficients": result.get("coefficients", {}),
            "accuracy": result.get("accuracy"),
            "brier": round(float(brier_score(p, a)), 4),
            "ece": round(float(expected_calibration_error(p, a, n_bins=5)), 4),
            "base_rate": round(float(np.mean(a)), 4),
            "mean_predicted": round(float(np.mean(p)), 4),
        }

    return {
        "name": f"segmented_by_{segment_field}",
        "segments": segment_results,
    }


def recalibrate_existing(records: List[Dict]) -> Dict[str, Any]:
    """Apply Platt and isotonic recalibration to current model's predictions."""
    predicted = np.array([r["on_time_prob_current"] for r in records])
    actual = np.array([float(r["actual_on_time"]) for r in records])

    # Current model baseline
    current_brier = float(brier_score(predicted, actual))
    current_ece = float(expected_calibration_error(predicted, actual, n_bins=5))

    # Naive base rate baseline
    base_rate = float(np.mean(actual))
    naive_pred = np.full_like(predicted, base_rate)
    naive_brier = float(brier_score(naive_pred, actual))

    results = {
        "n": len(records),
        "current_model": {
            "brier": round(current_brier, 4),
            "ece": round(current_ece, 4),
            "mean_predicted": round(float(np.mean(predicted)), 4),
            "base_rate": round(base_rate, 4),
        },
        "naive_base_rate": {
            "brier": round(naive_brier, 4),
            "base_rate": round(base_rate, 4),
        },
    }

    # Platt scaling
    try:
        from common.stats.calibration import platt_scaling

        platt = platt_scaling(predicted, actual)
        results["platt"] = {
            "a": platt["a"],
            "b": platt["b"],
            "brier_raw": platt["brier_raw"],
            "brier_calibrated": platt["brier_calibrated"],
            "ece_raw": platt["ece_raw"],
            "ece_calibrated": platt["ece_calibrated"],
        }
    except Exception as e:
        results["platt"] = {"error": str(e)}

    # Isotonic
    try:
        from common.stats.calibration import isotonic_calibration

        iso = isotonic_calibration(predicted, actual)
        results["isotonic"] = {
            "brier_raw": iso["brier_raw"],
            "brier_calibrated": iso["brier_calibrated"],
            "ece_raw": iso["ece_raw"],
            "ece_calibrated": iso["ece_calibrated"],
        }
    except Exception as e:
        results["isotonic"] = {"error": str(e)}

    return results


# ---------------------------------------------------------------------------
# Comparison table
# ---------------------------------------------------------------------------


def build_comparison(
    recal: Dict,
    global_result: Dict,
    segmented_family: Dict,
    segmented_hardness: Dict,
) -> List[Dict[str, Any]]:
    """Build a ranked comparison of all approaches."""
    rows = []

    # Current model
    cm = recal.get("current_model", {})
    rows.append(
        {
            "approach": "current_default_coefficients",
            "brier": cm.get("brier"),
            "ece": cm.get("ece"),
            "n": recal.get("n"),
        }
    )

    # Naive base rate
    nb = recal.get("naive_base_rate", {})
    rows.append({"approach": "naive_base_rate", "brier": nb.get("brier"), "ece": None, "n": recal.get("n")})

    # Platt
    pl = recal.get("platt", {})
    if "brier_calibrated" in pl:
        rows.append(
            {
                "approach": "platt_recalibration",
                "brier": pl["brier_calibrated"],
                "ece": pl.get("ece_calibrated"),
                "n": recal.get("n"),
            }
        )

    # Isotonic
    iso = recal.get("isotonic", {})
    if "brier_calibrated" in iso:
        rows.append(
            {
                "approach": "isotonic_recalibration",
                "brier": iso["brier_calibrated"],
                "ece": iso.get("ece_calibrated"),
                "n": recal.get("n"),
            }
        )

    # Retrained global
    if "brier" in global_result:
        rows.append(
            {
                "approach": "retrained_global_logistic",
                "brier": global_result["brier"],
                "ece": global_result.get("ece"),
                "n": global_result.get("n_training"),
                "note": "in-sample",
            }
        )

    # Segmented by family
    for seg_val, seg_info in segmented_family.get("segments", {}).items():
        if not seg_info.get("insufficient") and "brier" in seg_info:
            rows.append(
                {
                    "approach": f"segmented_family_{seg_val}",
                    "brier": seg_info["brier"],
                    "ece": seg_info.get("ece"),
                    "n": seg_info.get("n"),
                    "note": "in-sample",
                }
            )

    # Segmented by hardness
    for seg_val, seg_info in segmented_hardness.get("segments", {}).items():
        if not seg_info.get("insufficient") and "brier" in seg_info:
            rows.append(
                {
                    "approach": f"segmented_hard_{seg_val}",
                    "brier": seg_info["brier"],
                    "ece": seg_info.get("ece"),
                    "n": seg_info.get("n"),
                    "note": "in-sample",
                }
            )

    rows.sort(key=lambda r: r.get("brier") or 999)
    return rows


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_report_md(results: Dict[str, Any]) -> str:
    lines = []
    lines.append("# Timing Hazard Retraining Report")
    lines.append("")
    lines.append(f"*Generated: {results.get('generated_at', '')}*")
    lines.append("")

    # Comparison table
    comp = results.get("comparison", [])
    if comp:
        lines.append("## Approach Comparison (ranked by Brier)")
        lines.append("")
        lines.append("| Approach | Brier | ECE | N | Note |")
        lines.append("|----------|-------|-----|---|------|")
        for r in comp:
            b = f"{r['brier']:.4f}" if r.get("brier") is not None else "—"
            e = f"{r['ece']:.4f}" if r.get("ece") is not None else "—"
            n = str(r.get("n", "")) if r.get("n") else "—"
            note = r.get("note", "")
            lines.append(f"| {r['approach']} | {b} | {e} | {n} | {note} |")
        lines.append("")

    # Recalibration details
    recal = results.get("recalibration", {})
    cm = recal.get("current_model", {})
    lines.append("## Current Model Baseline")
    lines.append("")
    lines.append(f"- Brier: {cm.get('brier', '?')}")
    lines.append(f"- ECE: {cm.get('ece', '?')}")
    lines.append(f"- Base rate: {cm.get('base_rate', '?')}")
    lines.append(f"- Mean predicted: {cm.get('mean_predicted', '?')}")
    lines.append("")

    # Platt
    pl = recal.get("platt", {})
    if "brier_calibrated" in pl:
        lines.append("## Platt Recalibration")
        lines.append("")
        lines.append(f"- Parameters: a={pl.get('a')}, b={pl.get('b')}")
        lines.append(f"- Brier: {pl['brier_raw']} -> {pl['brier_calibrated']}")
        lines.append(f"- ECE: {pl['ece_raw']} -> {pl['ece_calibrated']}")
        lines.append("")

    # Isotonic
    iso = recal.get("isotonic", {})
    if "brier_calibrated" in iso:
        lines.append("## Isotonic Recalibration")
        lines.append("")
        lines.append(f"- Brier: {iso['brier_raw']} -> {iso['brier_calibrated']}")
        lines.append(f"- ECE: {iso['ece_raw']} -> {iso['ece_calibrated']}")
        lines.append("")

    # Retrained global
    gl = results.get("retrained_global", {})
    if "coefficients" in gl:
        lines.append("## Retrained Global Coefficients")
        lines.append("")
        lines.append(f"- N training: {gl.get('n_training')}")
        lines.append(f"- Accuracy: {gl.get('training_accuracy')}")
        lines.append(f"- Brier (in-sample): {gl.get('brier')}")
        lines.append(f"- ECE (in-sample): {gl.get('ece')}")
        lines.append("")
        lines.append("| Feature | Coefficient |")
        lines.append("|---------|------------|")
        for feat, coef in sorted(gl["coefficients"].items(), key=lambda x: -abs(x[1])):
            lines.append(f"| {feat} | {coef:+.4f} |")
        lines.append("")

    # Segmented
    seg_fam = results.get("segmented_by_family", {})
    if seg_fam.get("segments"):
        lines.append("## Segmented by Event Family")
        lines.append("")
        for seg_val, info in seg_fam["segments"].items():
            if info.get("insufficient"):
                lines.append(f"### {seg_val}: insufficient data (n={info.get('n', 0)})")
            else:
                lines.append(f"### {seg_val} (n={info.get('n')})")
                lines.append(f"- Brier: {info.get('brier')}, ECE: {info.get('ece')}")
                lines.append(f"- Base rate: {info.get('base_rate')}, Mean pred: {info.get('mean_predicted')}")
            lines.append("")

    # Recommendation
    lines.append("## Recommendation")
    lines.append("")
    if comp:
        best = comp[0]
        current = next((r for r in comp if r["approach"] == "current_default_coefficients"), None)
        if current and best["approach"] != "current_default_coefficients":
            improvement = (current.get("brier", 0) or 0) - (best.get("brier", 0) or 0)
            lines.append(f"**Best approach: {best['approach']}** (Brier improvement: {improvement:+.4f})")
        else:
            lines.append("**Current model is already the best tested approach.**")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 70)
    print("TIMING HAZARD RETRAINING")
    print("=" * 70)

    # Load data
    print("\nLoading training data...")
    records = load_training_data()
    print(f"  Records: {len(records)} (excluding EARLY outcomes)")
    print(f"  ON_TIME: {sum(1 for r in records if r['actual_on_time'] == 1)}")
    print(f"  SLIP: {sum(1 for r in records if r['actual_on_time'] == 0)}")

    # Extract features for each record (slow — reads snapshots)
    print("\nExtracting features from snapshots...")
    features_map: Dict[str, Dict[str, float]] = {}
    unique_pairs = set()
    for r in records:
        unique_pairs.add((r["ticker"], r["prediction_date"]))

    # Batch by snapshot date
    by_date: Dict[str, List[str]] = {}
    for ticker, snap_date in unique_pairs:
        by_date.setdefault(snap_date, []).append(ticker)

    n_dates = len(by_date)
    for i, (snap_date, tickers) in enumerate(sorted(by_date.items())):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"  Processing {snap_date} ({i + 1}/{n_dates})...")
        rankings_path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
        if not rankings_path.exists():
            continue

        # Load rankings once per date
        with open(rankings_path, encoding="utf-8") as f:
            rows_by_ticker = {r["ticker"]: r for r in csv.DictReader(f)}

        from datetime import date

        from tools.compute_timing_hazard import _build_catalyst_node, _load_trial_update_dates

        snap_d = date.fromisoformat(snap_date)
        trial_dates = _load_trial_update_dates()
        model = TimingHazardModel()

        for ticker in tickers:
            row = rows_by_ticker.get(ticker)
            if not row:
                continue
            node = _build_catalyst_node(row, snap_d, trial_dates, None)
            if not node:
                continue
            features = model._extract_features(node, snap_d)
            features_map[f"{ticker}_{snap_date}"] = features

    print(f"  Extracted features for {len(features_map)} records")

    # Step 1: Recalibrate existing predictions
    print("\nStep 1: Recalibrating existing predictions...")
    recal = recalibrate_existing(records)
    print(f"  Current Brier: {recal['current_model']['brier']}")
    pl = recal.get("platt", {})
    if "brier_calibrated" in pl:
        print(f"  Platt Brier: {pl['brier_calibrated']}")
    iso = recal.get("isotonic", {})
    if "brier_calibrated" in iso:
        print(f"  Isotonic Brier: {iso['brier_calibrated']}")

    # Step 2: Retrain global
    print("\nStep 2: Retraining global logistic model...")
    global_result = train_logistic_global(records, features_map)
    if "error" not in global_result:
        print(f"  Retrained Brier: {global_result['brier']}")
        print(f"  Retrained ECE: {global_result['ece']}")
    else:
        print(f"  Error: {global_result['error']}")

    # Step 3: Segmented by event family
    print("\nStep 3: Segmented by event family...")
    seg_family = train_logistic_segmented(
        records,
        features_map,
        "catalyst_family",
        ["CLINICAL", "REGULATORY", ""],
    )
    for seg_val, info in seg_family.get("segments", {}).items():
        label = seg_val or "(empty)"
        if info.get("insufficient"):
            print(f"  {label}: insufficient (n={info.get('n', 0)})")
        else:
            print(f"  {label}: Brier={info.get('brier')}, n={info.get('n')}")

    # Step 4: Segmented by hardness
    print("\nStep 4: Segmented by catalyst hardness...")
    seg_hard = train_logistic_segmented(
        records,
        features_map,
        "is_hard_catalyst",
        ["True", "False"],
    )
    for seg_val, info in seg_hard.get("segments", {}).items():
        if info.get("insufficient"):
            print(f"  hard={seg_val}: insufficient (n={info.get('n', 0)})")
        else:
            print(f"  hard={seg_val}: Brier={info.get('brier')}, n={info.get('n')}")

    # Build comparison
    comparison = build_comparison(recal, global_result, seg_family, seg_hard)

    # Assemble results
    results = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": len(records),
        "n_features_extracted": len(features_map),
        "recalibration": recal,
        "retrained_global": global_result,
        "segmented_by_family": seg_family,
        "segmented_by_hardness": seg_hard,
        "comparison": comparison,
    }

    # Write outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "retrain_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  JSON: {json_path}")

    md_path = OUTPUT_DIR / "retrain_report.md"
    md_text = format_report_md(results)
    md_path.write_text(md_text, encoding="utf-8")
    print(f"  Markdown: {md_path}")

    # Write retrained coefficients separately
    if "coefficients" in global_result:
        coeff_path = OUTPUT_DIR / "retrained_coefficients.json"
        coeff_data = {
            "schema": "timing_hazard_coefficients.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "timing_hazard_retrain.py",
            "n_training": global_result.get("n_training"),
            "in_sample_brier": global_result.get("brier"),
            "in_sample_ece": global_result.get("ece"),
            "status": "CANDIDATE — requires OOS validation before promotion",
            "coefficients": global_result["coefficients"],
        }
        with open(coeff_path, "w", encoding="utf-8") as f:
            json.dump(coeff_data, f, indent=2)
        print(f"  Coefficients: {coeff_path}")

    # Print comparison
    print("\n" + "=" * 70)
    print("COMPARISON (ranked by Brier)")
    print("=" * 70)
    for r in comparison:
        b = f"{r['brier']:.4f}" if r.get("brier") is not None else "—"
        e = f"{r['ece']:.4f}" if r.get("ece") is not None else "—"
        note = f" ({r['note']})" if r.get("note") else ""
        print(f"  {r['approach']:40s} Brier={b}  ECE={e}  n={r.get('n', '?')}{note}")


if __name__ == "__main__":
    main()
