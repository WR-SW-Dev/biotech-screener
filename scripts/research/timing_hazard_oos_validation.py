#!/usr/bin/env python3
"""Timing Hazard OOS Validation — segmented models on temporal holdout.

Trains on pre-2026 data, evaluates on 2026 data. Tests:
  1. Current default coefficients (baseline)
  2. Naive base rate
  3. Retrained global logistic
  4. Segmented by catalyst_family (CLINICAL / REGULATORY / empty)
  5. Segmented by catalyst hardness
  6. Platt recalibration of current predictions
  7. Simple rule: regulatory=1.0, hard=0.85, clinical=base_rate, empty=0.50

All evaluation is strictly out-of-sample: models see only train data,
scored only on test data.

Output:
    output/timing_hazard_oos/oos_validation.json
    output/timing_hazard_oos/oos_validation.md

Usage:
    python3 scripts/research/timing_hazard_oos_validation.py
"""

from __future__ import annotations

import csv
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from common.stats.calibration import brier_score, expected_calibration_error, reliability_curve
from event_ev.timing_hazard import TimingHazardModel, _sigmoid
from event_ledger import classify_catalyst_family

BACKFILL_CSV = PROJECT_ROOT / "output" / "timing_hazard_review" / "calibration_backfill.csv"
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
OUTPUT_DIR = PROJECT_ROOT / "output" / "timing_hazard_oos"

SCHEMA_VERSION = "timing_hazard_oos.v1"
SPLIT_DATE = "2026-01-01"  # train < this, test >= this


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _sf(v, default=None):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def load_and_split() -> tuple[list[dict], list[dict]]:
    """Load backfill CSV and split into train/test."""
    rows = []
    with open(BACKFILL_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("outcome") == "EARLY":
                continue
            family = r.get("catalyst_family", "") or classify_catalyst_family(r.get("catalyst_event_type", ""))
            rows.append(
                {
                    "prediction_date": r["prediction_date"],
                    "ticker": r["ticker"],
                    "catalyst_days": _sf(r["catalyst_days"], 0),
                    "catalyst_event_type": r.get("catalyst_event_type", ""),
                    "catalyst_family": family,
                    "is_hard_catalyst": r.get("is_hard_catalyst") == "True",
                    "on_time_prob_current": _sf(r["on_time_prob"], 0.5),
                    "timing_confidence_bucket": r.get("timing_confidence_bucket", ""),
                    "actual_on_time": int(r.get("actual_on_time", 0)),
                }
            )

    train = [r for r in rows if r["prediction_date"] < SPLIT_DATE]
    test = [r for r in rows if r["prediction_date"] >= SPLIT_DATE]
    return train, test


def extract_features_batch(
    records: list[dict],
) -> dict[str, dict[str, float]]:
    """Extract timing model features for a set of records."""
    from tools.compute_timing_hazard import _build_catalyst_node, _load_trial_update_dates

    trial_dates = _load_trial_update_dates()
    features_map = {}

    by_date: dict[str, list[str]] = {}
    for r in records:
        by_date.setdefault(r["prediction_date"], []).append(r["ticker"])

    for i, (snap_date, tickers) in enumerate(sorted(by_date.items())):
        if (i + 1) % 50 == 0:
            print(f"    Features: {snap_date} ({i + 1}/{len(by_date)})...")
        rankings_path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
        if not rankings_path.exists():
            continue
        with open(rankings_path, encoding="utf-8") as f:
            rows_by_ticker = {r["ticker"]: r for r in csv.DictReader(f)}

        snap_d = date.fromisoformat(snap_date)
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

    return features_map


# ---------------------------------------------------------------------------
# Model training (train set only)
# ---------------------------------------------------------------------------


def train_model(
    records: list[dict],
    features_map: dict[str, dict],
) -> dict[str, Any]:
    """Train logistic model on records, return model + in-sample metrics."""
    training_data = []
    for r in records:
        key = f"{r['ticker']}_{r['prediction_date']}"
        feats = features_map.get(key)
        if not feats:
            continue
        training_data.append({"features": feats, "actual_on_time": r["actual_on_time"]})

    if len(training_data) < 20:
        return {"error": "insufficient", "n": len(training_data)}

    model = TimingHazardModel()
    result = model.train_on_historical(training_data)
    return {"model": model, "coefficients": result.get("coefficients", {}), "n": len(training_data)}


def predict_with_model(
    model: TimingHazardModel,
    records: list[dict],
    features_map: dict[str, dict],
) -> list[float]:
    """Generate predictions for records using a trained model."""
    predictions = []
    for r in records:
        key = f"{r['ticker']}_{r['prediction_date']}"
        feats = features_map.get(key)
        if feats:
            logit = model._compute_logit(feats)
            predictions.append(_sigmoid(logit))
        else:
            predictions.append(0.5)  # fallback
    return predictions


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate(
    predicted: list[float],
    actual: list[int],
    label: str,
) -> dict[str, Any]:
    """Score predictions against actuals."""
    p = np.array(predicted)
    a = np.array(actual, dtype=float)
    n = len(p)
    if n < 5:
        return {"label": label, "n": n, "insufficient": True}

    brier = float(brier_score(p, a))
    n_bins = min(5, max(2, n // 20))
    ece = float(expected_calibration_error(p, a, n_bins=n_bins))
    rel = reliability_curve(p, a, n_bins=n_bins)

    base_rate = float(np.mean(a))
    mean_pred = float(np.mean(p))

    return {
        "label": label,
        "n": n,
        "brier": round(brier, 4),
        "ece": round(ece, 4),
        "base_rate": round(base_rate, 4),
        "mean_predicted": round(mean_pred, 4),
        "overconfidence": round(mean_pred - base_rate, 4),
        "reliability_curve": rel,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 70)
    print("TIMING HAZARD OOS VALIDATION")
    print(f"Split: train < {SPLIT_DATE}, test >= {SPLIT_DATE}")
    print("=" * 70)

    # Load and split
    print("\nLoading data...")
    train, test = load_and_split()
    print(
        f"  Train: {len(train)} (ON_TIME: {sum(1 for r in train if r['actual_on_time'])}, SLIP: {sum(1 for r in train if not r['actual_on_time'])})"
    )
    print(
        f"  Test:  {len(test)} (ON_TIME: {sum(1 for r in test if r['actual_on_time'])}, SLIP: {sum(1 for r in test if not r['actual_on_time'])})"
    )

    # Extract features
    print("\nExtracting features...")
    print("  Train features...")
    train_features = extract_features_batch(train)
    print(f"    Got {len(train_features)} feature vectors")
    print("  Test features...")
    test_features = extract_features_batch(test)
    print(f"    Got {len(test_features)} feature vectors")

    test_actual = [r["actual_on_time"] for r in test]
    test_base_rate = sum(test_actual) / len(test_actual)

    results = []

    # --- Baseline 1: Current default coefficients ---
    print("\nEvaluating approaches on test set...")
    current_pred = [r["on_time_prob_current"] for r in test]
    results.append(evaluate(current_pred, test_actual, "current_default_coefficients"))
    print(f"  current_default:  Brier={results[-1].get('brier', '?')}")

    # --- Baseline 2: Naive base rate (from TRAIN set) ---
    train_base = sum(r["actual_on_time"] for r in train) / len(train)
    naive_pred = [train_base] * len(test)
    results.append(evaluate(naive_pred, test_actual, "naive_base_rate_from_train"))
    print(f"  naive_base_rate:  Brier={results[-1].get('brier', '?')}")

    # --- Approach 1: Retrained global logistic ---
    print("\n  Training global logistic on train set...")
    global_trained = train_model(train, train_features)
    if "model" in global_trained:
        global_pred = predict_with_model(global_trained["model"], test, test_features)
        results.append(evaluate(global_pred, test_actual, "retrained_global_logistic"))
        print(f"  retrained_global: Brier={results[-1].get('brier', '?')}")
    else:
        print(f"  retrained_global: SKIP ({global_trained.get('error')})")

    # --- Approach 2: Segmented by catalyst_family ---
    families = ["CLINICAL", "REGULATORY", ""]
    family_models = {}
    for fam in families:
        fam_train = [r for r in train if r["catalyst_family"] == fam]
        if len(fam_train) < 20:
            print(f"  segment_{fam or 'empty'}: SKIP (n={len(fam_train)})")
            continue
        trained = train_model(fam_train, train_features)
        if "model" in trained:
            family_models[fam] = trained["model"]
            print(f"  segment_{fam or 'empty'}: trained on {trained['n']}")

    # Apply segmented family predictions to test
    if family_models:
        seg_family_pred = []
        for r in test:
            fam = r["catalyst_family"]
            if fam in family_models:
                key = f"{r['ticker']}_{r['prediction_date']}"
                feats = test_features.get(key)
                if feats:
                    logit = family_models[fam]._compute_logit(feats)
                    seg_family_pred.append(_sigmoid(logit))
                else:
                    seg_family_pred.append(train_base)
            else:
                # Fallback to train base rate for unseen families
                seg_family_pred.append(train_base)
        results.append(evaluate(seg_family_pred, test_actual, "segmented_by_family"))
        print(f"  segmented_family: Brier={results[-1].get('brier', '?')}")

    # --- Per-family OOS evaluation ---
    for fam in families:
        fam_test = [r for r in test if r["catalyst_family"] == fam]
        if len(fam_test) < 5:
            continue
        fam_actual = [r["actual_on_time"] for r in fam_test]
        fam_label = fam or "empty"

        # Current model on this family
        fam_current = [r["on_time_prob_current"] for r in fam_test]
        results.append(evaluate(fam_current, fam_actual, f"current_{fam_label}"))

        # Segmented model on this family (if trained)
        if fam in family_models:
            fam_seg_pred = []
            for r in fam_test:
                key = f"{r['ticker']}_{r['prediction_date']}"
                feats = test_features.get(key)
                if feats:
                    logit = family_models[fam]._compute_logit(feats)
                    fam_seg_pred.append(_sigmoid(logit))
                else:
                    fam_seg_pred.append(0.5)
            results.append(evaluate(fam_seg_pred, fam_actual, f"segmented_{fam_label}"))

    # --- Approach 3: Segmented by hardness ---
    for is_hard in [True, False]:
        label = "hard" if is_hard else "soft"
        hard_train = [r for r in train if r["is_hard_catalyst"] == is_hard]
        hard_test = [r for r in test if r["is_hard_catalyst"] == is_hard]
        if len(hard_train) < 20 or len(hard_test) < 5:
            print(f"  segment_{label}: SKIP (train={len(hard_train)}, test={len(hard_test)})")
            continue
        trained = train_model(hard_train, train_features)
        if "model" in trained:
            hard_pred = predict_with_model(trained["model"], hard_test, test_features)
            hard_actual = [r["actual_on_time"] for r in hard_test]
            results.append(evaluate(hard_pred, hard_actual, f"segmented_{label}_oos"))
            # Also current model on this segment
            hard_current = [r["on_time_prob_current"] for r in hard_test]
            results.append(evaluate(hard_current, hard_actual, f"current_{label}"))

    # --- Approach 4: Simple rule-based ---
    rule_pred = []
    for r in test:
        if r["catalyst_family"] == "REGULATORY":
            rule_pred.append(0.98)
        elif r["is_hard_catalyst"]:
            rule_pred.append(0.85)
        elif r["catalyst_family"] == "CLINICAL":
            rule_pred.append(train_base)
        else:
            rule_pred.append(0.50)
    results.append(evaluate(rule_pred, test_actual, "simple_rule_based"))
    print(f"  simple_rule:      Brier={results[-1].get('brier', '?')}")

    # --- Approach 5: Platt recalibration (fit on train, apply to test) ---
    try:
        train_pred_current = np.array([r["on_time_prob_current"] for r in train])
        train_actual_arr = np.array([float(r["actual_on_time"]) for r in train])

        from scipy.optimize import minimize
        from scipy.special import expit

        def neg_ll(params):
            a, b = params
            logits = np.clip(a * train_pred_current + b, -30, 30)
            probs = np.clip(expit(logits), 1e-10, 1 - 1e-10)
            return -np.sum(train_actual_arr * np.log(probs) + (1 - train_actual_arr) * np.log(1 - probs))

        opt = minimize(neg_ll, x0=[1.0, 0.0], method="Nelder-Mead")
        a_opt, b_opt = opt.x

        test_pred_current = np.array([r["on_time_prob_current"] for r in test])
        platt_pred = expit(a_opt * test_pred_current + b_opt).tolist()
        results.append(evaluate(platt_pred, test_actual, "platt_recalibration_oos"))
        print(f"  platt_oos:        Brier={results[-1].get('brier', '?')} (a={a_opt:.3f}, b={b_opt:.3f})")
    except Exception as e:
        print(f"  platt_oos: ERROR ({e})")

    # --- Assemble report ---
    ranked = sorted(
        [r for r in results if not r.get("insufficient")],
        key=lambda r: r.get("brier", 999),
    )

    report = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "split_date": SPLIT_DATE,
        "n_train": len(train),
        "n_test": len(test),
        "test_base_rate": round(test_base_rate, 4),
        "train_base_rate": round(train_base, 4),
        "results": ranked,
        "global_coefficients": global_trained.get("coefficients") if "model" in global_trained else None,
    }

    # Write
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "oos_validation.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    md_text = format_md(report)
    md_path = OUTPUT_DIR / "oos_validation.md"
    md_path.write_text(md_text, encoding="utf-8")

    print(f"\n  JSON: {json_path}")
    print(f"  Markdown: {md_path}")

    # Print ranked results
    print("\n" + "=" * 70)
    print("OOS RESULTS (ranked by Brier)")
    print("=" * 70)
    for r in ranked:
        b = f"{r['brier']:.4f}" if r.get("brier") is not None else "—"
        e = f"{r['ece']:.4f}" if r.get("ece") is not None else "—"
        oc = f"{r['overconfidence']:+.4f}" if r.get("overconfidence") is not None else "—"
        print(f"  {r['label']:40s} Brier={b}  ECE={e}  overconf={oc}  n={r.get('n', '?')}")

    # Winner
    if ranked:
        best = ranked[0]
        current = next((r for r in ranked if r["label"] == "current_default_coefficients"), None)
        if current:
            improvement = (current.get("brier", 0) or 0) - (best.get("brier", 0) or 0)
            print(f"\n  WINNER: {best['label']} (Brier improvement vs current: {improvement:+.4f})")


def format_md(report: dict) -> str:
    lines = []
    lines.append("# Timing Hazard OOS Validation")
    lines.append("")
    lines.append(f"**Split:** train < {report['split_date']}, test >= {report['split_date']}")
    lines.append(f"**Train:** {report['n_train']} records (base rate: {report['train_base_rate']:.1%})")
    lines.append(f"**Test:** {report['n_test']} records (base rate: {report['test_base_rate']:.1%})")
    lines.append("")

    ranked = report.get("results", [])
    lines.append("## Results (ranked by Brier)")
    lines.append("")
    lines.append("| Approach | Brier | ECE | Base Rate | Mean Pred | Overconf | N |")
    lines.append("|----------|-------|-----|-----------|-----------|----------|---|")
    for r in ranked:
        if r.get("insufficient"):
            continue
        b = f"{r['brier']:.4f}" if r.get("brier") is not None else "—"
        e = f"{r['ece']:.4f}" if r.get("ece") is not None else "—"
        br = f"{r['base_rate']:.3f}" if r.get("base_rate") is not None else "—"
        mp = f"{r['mean_predicted']:.3f}" if r.get("mean_predicted") is not None else "—"
        oc = f"{r['overconfidence']:+.3f}" if r.get("overconfidence") is not None else "—"
        n = str(r.get("n", ""))
        lines.append(f"| {r['label']} | {b} | {e} | {br} | {mp} | {oc} | {n} |")
    lines.append("")

    # Interpretation
    if ranked:
        best = ranked[0]
        current = next((r for r in ranked if r["label"] == "current_default_coefficients"), None)
        if current and best["label"] != "current_default_coefficients":
            imp = (current.get("brier", 0) or 0) - (best.get("brier", 0) or 0)
            lines.append(f"**Winner: {best['label']}** (Brier improvement: {imp:+.4f} vs current)")
        else:
            lines.append("**Current model is the best tested approach on OOS data.**")
    lines.append("")

    lines.append(f"*Generated: {report.get('generated_at', '')}*")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
