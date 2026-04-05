#!/usr/bin/env python3
"""Timing Hazard OOS v2 — artifact-corrected validation.

Fixes two artifacts that contaminated v1 OOS results:
  1. Snapshot density: deduplicates to one observation per ticker per ISO week
  2. Horizon composition: conditions models on catalyst_days bucket

Tests:
  A. Rolling base rate anchor (trailing 90-day on-time rate as intercept)
  B. Horizon-stratified models (separate coefficients per catalyst_days bucket)
  C. Regime-conditional intercept (if regime data available)
  D. Simple rule baseline (regulatory=0.98, hard=0.85, else=rolling_base)

All evaluation is strictly OOS with deduplication applied uniformly.

Output:
    output/timing_hazard_oos_v2/oos_v2_validation.json
    output/timing_hazard_oos_v2/oos_v2_validation.md

Usage:
    python3 scripts/research/timing_hazard_oos_v2.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from common.stats.calibration import brier_score, expected_calibration_error, reliability_curve
from event_ev.timing_hazard import TimingHazardModel, _sigmoid
from event_ledger import classify_catalyst_family
from tools.compute_timing_hazard import _build_catalyst_node, _load_trial_update_dates

BACKFILL_CSV = PROJECT_ROOT / "output" / "timing_hazard_review" / "calibration_backfill.csv"
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
OUTPUT_DIR = PROJECT_ROOT / "output" / "timing_hazard_oos_v2"

SCHEMA_VERSION = "timing_hazard_oos_v2.v1"
SPLIT_DATE = "2026-01-01"
ROLLING_WINDOW_DAYS = 90

HORIZON_BUCKETS = [
    ("near", 0, 30),
    ("medium", 31, 90),
    ("far", 91, 180),
    ("very_far", 181, 9999),
]


def _sf(v, default=None):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def horizon_bucket(catalyst_days: float) -> str:
    for label, lo, hi in HORIZON_BUCKETS:
        if lo <= catalyst_days <= hi:
            return label
    return "unknown"


# ---------------------------------------------------------------------------
# Data loading with deduplication
# ---------------------------------------------------------------------------


def load_deduped() -> tuple[list[dict], list[dict]]:
    """Load backfill, deduplicate to one obs per ticker per ISO week, split."""
    raw = []
    with open(BACKFILL_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("outcome") == "EARLY":
                continue
            family = r.get("catalyst_family", "") or classify_catalyst_family(r.get("catalyst_event_type", ""))
            cd = _sf(r["catalyst_days"], 0)
            raw.append(
                {
                    "prediction_date": r["prediction_date"],
                    "ticker": r["ticker"],
                    "catalyst_days": cd,
                    "horizon_bucket": horizon_bucket(cd),
                    "catalyst_event_type": r.get("catalyst_event_type", ""),
                    "catalyst_family": family,
                    "is_hard_catalyst": r.get("is_hard_catalyst") == "True",
                    "on_time_prob_current": _sf(r["on_time_prob"], 0.5),
                    "timing_confidence_bucket": r.get("timing_confidence_bucket", ""),
                    "actual_on_time": int(r.get("actual_on_time", 0)),
                }
            )

    # Deduplicate: keep first observation per (ticker, ISO week)
    seen = set()
    deduped = []
    for r in raw:
        d = date.fromisoformat(r["prediction_date"])
        iso_week = d.isocalendar()[:2]
        key = (r["ticker"], iso_week)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    train = [r for r in deduped if r["prediction_date"] < SPLIT_DATE]
    test = [r for r in deduped if r["prediction_date"] >= SPLIT_DATE]
    return train, test


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def extract_features_batch(records: list[dict]) -> dict[str, dict[str, float]]:
    trial_dates = _load_trial_update_dates()
    features_map = {}

    by_date: dict[str, list[str]] = {}
    for r in records:
        by_date.setdefault(r["prediction_date"], []).append(r["ticker"])

    for i, (snap_date, tickers) in enumerate(sorted(by_date.items())):
        if (i + 1) % 50 == 0:
            print(f"    {snap_date} ({i + 1}/{len(by_date)})...")
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
# Rolling base rate
# ---------------------------------------------------------------------------


def compute_rolling_base_rates(
    train: list[dict],
    test: list[dict],
) -> dict[str, float]:
    """For each test date, compute trailing 90-day base rate from available data."""
    # Build a time-sorted ledger of all outcomes (train + test up to each date)
    all_records = sorted(train + test, key=lambda r: r["prediction_date"])
    rolling = {}

    for r in test:
        test_date = r["prediction_date"]
        # Use all data up to (but not including) test_date
        prior = [x["actual_on_time"] for x in all_records if x["prediction_date"] < test_date]
        # Take last ROLLING_WINDOW_DAYS worth of prior outcomes
        # (approximate: use last N records where N ~ what fits in 90 days)
        # For simplicity, use last 200 records as proxy for 90-day window
        recent = prior[-200:] if len(prior) > 200 else prior
        if recent:
            rolling[test_date] = sum(recent) / len(recent)
        else:
            rolling[test_date] = 0.5  # fallback

    return rolling


def compute_horizon_base_rates(
    train: list[dict],
) -> dict[str, float]:
    """Compute train-set base rate per horizon bucket."""
    from collections import defaultdict

    by_bucket = defaultdict(list)
    for r in train:
        by_bucket[r["horizon_bucket"]].append(r["actual_on_time"])

    result = {}
    for bucket, vals in by_bucket.items():
        result[bucket] = sum(vals) / len(vals) if vals else 0.5
    return result


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------


def train_model_on(records, features_map) -> Optional[TimingHazardModel]:
    training_data = []
    for r in records:
        key = f"{r['ticker']}_{r['prediction_date']}"
        feats = features_map.get(key)
        if feats:
            training_data.append({"features": feats, "actual_on_time": r["actual_on_time"]})
    if len(training_data) < 20:
        return None
    model = TimingHazardModel()
    model.train_on_historical(training_data)
    return model


def predict_with_model(model, records, features_map) -> list[float]:
    preds = []
    for r in records:
        key = f"{r['ticker']}_{r['prediction_date']}"
        feats = features_map.get(key)
        if feats:
            logit = model._compute_logit(feats)
            preds.append(_sigmoid(logit))
        else:
            preds.append(0.5)
    return preds


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def evaluate(predicted, actual, label) -> dict[str, Any]:
    p = np.array(predicted)
    a = np.array(actual, dtype=float)
    n = len(p)
    if n < 5:
        return {"label": label, "n": n, "insufficient": True}
    n_bins = min(5, max(2, n // 20))
    return {
        "label": label,
        "n": n,
        "brier": round(float(brier_score(p, a)), 4),
        "ece": round(float(expected_calibration_error(p, a, n_bins=n_bins)), 4),
        "base_rate": round(float(np.mean(a)), 4),
        "mean_predicted": round(float(np.mean(p)), 4),
        "overconfidence": round(float(np.mean(p)) - float(np.mean(a)), 4),
        "reliability_curve": reliability_curve(p, a, n_bins=n_bins),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 70)
    print("TIMING HAZARD OOS v2 — ARTIFACT-CORRECTED")
    print("Deduplication: one obs per ticker per ISO week")
    print(f"Split: train < {SPLIT_DATE}, test >= {SPLIT_DATE}")
    print("=" * 70)

    # Load
    print("\nLoading and deduplicating...")
    train, test = load_deduped()
    train_base = sum(r["actual_on_time"] for r in train) / len(train)
    test_base = sum(r["actual_on_time"] for r in test) / len(test)
    print(f"  Train: {len(train)} (base rate: {train_base:.1%})")
    print(f"  Test:  {len(test)} (base rate: {test_base:.1%})")
    print(f"  Gap:   {(train_base - test_base)*100:+.1f}pp")

    # Horizon distribution
    from collections import Counter

    train_hz = Counter(r["horizon_bucket"] for r in train)
    test_hz = Counter(r["horizon_bucket"] for r in test)
    print(f"  Train horizons: {dict(sorted(train_hz.items()))}")
    print(f"  Test horizons:  {dict(sorted(test_hz.items()))}")

    # Extract features
    print("\nExtracting features...")
    all_records = train + test
    features_map = extract_features_batch(all_records)
    print(f"  Got {len(features_map)} feature vectors")

    test_actual = [r["actual_on_time"] for r in test]
    results = []

    # --- Baseline: current defaults ---
    print("\nEvaluating on test set...")
    current_pred = [r["on_time_prob_current"] for r in test]
    results.append(evaluate(current_pred, test_actual, "current_defaults"))
    print(f"  current_defaults:    Brier={results[-1].get('brier')}")

    # --- Naive base rate (train) ---
    naive_pred = [train_base] * len(test)
    results.append(evaluate(naive_pred, test_actual, "naive_train_base"))
    print(f"  naive_train_base:    Brier={results[-1].get('brier')}")

    # --- A. Rolling base rate anchor ---
    print("  Computing rolling base rates...")
    rolling_rates = compute_rolling_base_rates(train, test)
    rolling_pred = [rolling_rates.get(r["prediction_date"], train_base) for r in test]
    results.append(evaluate(rolling_pred, test_actual, "rolling_base_rate_90d"))
    print(f"  rolling_base_90d:    Brier={results[-1].get('brier')}")

    # --- B. Horizon-stratified base rate ---
    horizon_rates = compute_horizon_base_rates(train)
    horizon_pred = [horizon_rates.get(r["horizon_bucket"], train_base) for r in test]
    results.append(evaluate(horizon_pred, test_actual, "horizon_stratified_base"))
    print(f"  horizon_stratified:  Brier={results[-1].get('brier')}")

    # --- C. Rolling + horizon combined ---
    # Use horizon-specific rolling rates
    combined_pred = []
    for r in test:
        # Start with rolling base, adjust by horizon deviation from global
        rolling_global = rolling_rates.get(r["prediction_date"], train_base)
        hz_rate = horizon_rates.get(r["horizon_bucket"], train_base)
        hz_adjustment = hz_rate - train_base
        combined = max(0.01, min(0.99, rolling_global + hz_adjustment))
        combined_pred.append(combined)
    results.append(evaluate(combined_pred, test_actual, "rolling_plus_horizon"))
    print(f"  rolling+horizon:     Brier={results[-1].get('brier')}")

    # --- D. Retrained global logistic (on deduped train) ---
    print("  Training global logistic...")
    global_model = train_model_on(train, features_map)
    if global_model:
        global_pred = predict_with_model(global_model, test, features_map)
        results.append(evaluate(global_pred, test_actual, "retrained_global_deduped"))
        print(f"  retrained_global:    Brier={results[-1].get('brier')}")

    # --- E. Horizon-segmented logistic ---
    print("  Training horizon-segmented logistic...")
    horizon_models = {}
    for hz_label, _, _ in HORIZON_BUCKETS:
        hz_train = [r for r in train if r["horizon_bucket"] == hz_label]
        if len(hz_train) >= 20:
            m = train_model_on(hz_train, features_map)
            if m:
                horizon_models[hz_label] = m

    if horizon_models:
        hz_seg_pred = []
        for r in test:
            hz = r["horizon_bucket"]
            if hz in horizon_models:
                key = f"{r['ticker']}_{r['prediction_date']}"
                feats = features_map.get(key)
                if feats:
                    logit = horizon_models[hz]._compute_logit(feats)
                    hz_seg_pred.append(_sigmoid(logit))
                else:
                    hz_seg_pred.append(horizon_rates.get(hz, train_base))
            else:
                hz_seg_pred.append(horizon_rates.get(hz, train_base))
        results.append(evaluate(hz_seg_pred, test_actual, "horizon_segmented_logistic"))
        print(f"  hz_seg_logistic:     Brier={results[-1].get('brier')}")

    # --- F. Simple rule with rolling base ---
    rule_pred = []
    for r in test:
        rolling_global = rolling_rates.get(r["prediction_date"], train_base)
        if r["catalyst_family"] == "REGULATORY":
            rule_pred.append(0.98)
        elif r["is_hard_catalyst"]:
            rule_pred.append(0.85)
        else:
            # Use horizon-adjusted rolling rate
            hz_rate = horizon_rates.get(r["horizon_bucket"], train_base)
            hz_adj = hz_rate - train_base
            rule_pred.append(max(0.01, min(0.99, rolling_global + hz_adj)))
    results.append(evaluate(rule_pred, test_actual, "rule_rolling_horizon"))
    print(f"  rule+rolling+hz:     Brier={results[-1].get('brier')}")

    # --- Per-horizon evaluation of best approaches ---
    print("\n  Per-horizon breakdown:")
    for hz_label, _, _ in HORIZON_BUCKETS:
        hz_test = [i for i, r in enumerate(test) if r["horizon_bucket"] == hz_label]
        if len(hz_test) < 5:
            continue
        hz_actual = [test_actual[i] for i in hz_test]
        hz_base = sum(hz_actual) / len(hz_actual)

        # Current defaults on this horizon
        hz_current = [current_pred[i] for i in hz_test]
        r_cur = evaluate(hz_current, hz_actual, f"current_{hz_label}")

        # Rolling+horizon on this horizon
        hz_rh = [combined_pred[i] for i in hz_test]
        r_rh = evaluate(hz_rh, hz_actual, f"rolling_hz_{hz_label}")

        # Rule on this horizon
        hz_rule = [rule_pred[i] for i in hz_test]
        r_rule = evaluate(hz_rule, hz_actual, f"rule_{hz_label}")

        results.extend([r_cur, r_rh, r_rule])
        print(
            f"    {hz_label:10s} n={len(hz_test):4d} base={hz_base:.1%}  "
            f"current={r_cur.get('brier', '?'):.4f}  "
            f"rolling_hz={r_rh.get('brier', '?'):.4f}  "
            f"rule={r_rule.get('brier', '?'):.4f}"
        )

    # Rank all global approaches
    global_labels = {
        "current_defaults",
        "naive_train_base",
        "rolling_base_rate_90d",
        "horizon_stratified_base",
        "rolling_plus_horizon",
        "retrained_global_deduped",
        "horizon_segmented_logistic",
        "rule_rolling_horizon",
    }
    ranked = sorted(
        [r for r in results if r["label"] in global_labels and not r.get("insufficient")],
        key=lambda r: r.get("brier", 999),
    )

    # Assemble report
    report = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "split_date": SPLIT_DATE,
        "deduplication": "one per ticker per ISO week",
        "n_train": len(train),
        "n_test": len(test),
        "train_base_rate": round(train_base, 4),
        "test_base_rate": round(test_base, 4),
        "horizon_base_rates": {k: round(v, 4) for k, v in horizon_rates.items()},
        "ranked_global": ranked,
        "all_results": [r for r in results if not r.get("insufficient")],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "oos_v2_validation.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    md_text = format_md(report)
    md_path = OUTPUT_DIR / "oos_v2_validation.md"
    md_path.write_text(md_text, encoding="utf-8")

    print(f"\n  JSON: {json_path}")
    print(f"  Markdown: {md_path}")

    print("\n" + "=" * 70)
    print("GLOBAL RANKING (artifact-corrected, deduped)")
    print("=" * 70)
    for r in ranked:
        print(
            f"  {r['label']:35s} Brier={r['brier']:.4f}  ECE={r['ece']:.4f}  "
            f"overconf={r['overconfidence']:+.4f}  n={r['n']}"
        )

    if ranked:
        best = ranked[0]
        current = next((r for r in ranked if r["label"] == "current_defaults"), None)
        if current and best["label"] != "current_defaults":
            imp = current["brier"] - best["brier"]
            print(f"\n  WINNER: {best['label']} (Brier improvement vs current: {imp:+.4f})")
        else:
            print("\n  Current defaults still win.")


def format_md(report: dict) -> str:
    lines = []
    lines.append("# Timing Hazard OOS v2 — Artifact-Corrected Validation")
    lines.append("")
    lines.append(f"**Deduplication:** {report['deduplication']}")
    lines.append(f"**Split:** train < {report['split_date']}, test >= {report['split_date']}")
    lines.append(f"**Train:** {report['n_train']} records (base rate: {report['train_base_rate']:.1%})")
    lines.append(f"**Test:** {report['n_test']} records (base rate: {report['test_base_rate']:.1%})")
    lines.append("")

    hz = report.get("horizon_base_rates", {})
    if hz:
        lines.append("## Horizon Base Rates (train set)")
        lines.append("")
        lines.append("| Horizon | Base Rate |")
        lines.append("|---------|-----------|")
        for k in ["near", "medium", "far", "very_far"]:
            if k in hz:
                lines.append(f"| {k} | {hz[k]:.1%} |")
        lines.append("")

    ranked = report.get("ranked_global", [])
    if ranked:
        lines.append("## Global Approaches (ranked by Brier)")
        lines.append("")
        lines.append("| Approach | Brier | ECE | Base Rate | Mean Pred | Overconf | N |")
        lines.append("|----------|-------|-----|-----------|-----------|----------|---|")
        for r in ranked:
            lines.append(
                f"| {r['label']} | {r['brier']:.4f} | {r['ece']:.4f} | "
                f"{r['base_rate']:.3f} | {r['mean_predicted']:.3f} | "
                f"{r['overconfidence']:+.3f} | {r['n']} |"
            )
        lines.append("")

    # Per-horizon results
    all_r = report.get("all_results", [])
    hz_results = [r for r in all_r if any(r["label"].endswith(f"_{h}") for h, _, _ in HORIZON_BUCKETS)]
    if hz_results:
        lines.append("## Per-Horizon Breakdown")
        lines.append("")
        lines.append("| Approach | Brier | Base Rate | N |")
        lines.append("|----------|-------|-----------|---|")
        for r in sorted(hz_results, key=lambda x: x["label"]):
            lines.append(f"| {r['label']} | {r['brier']:.4f} | {r['base_rate']:.3f} | {r['n']} |")
        lines.append("")

    if ranked:
        best = ranked[0]
        current = next((r for r in ranked if r["label"] == "current_defaults"), None)
        if current and best["label"] != "current_defaults":
            imp = current["brier"] - best["brier"]
            lines.append(f"**Winner: {best['label']}** (improvement: {imp:+.4f} Brier vs current)")
        else:
            lines.append("**Current defaults still win on artifact-corrected data.**")
        lines.append("")

    lines.append(f"*Generated: {report.get('generated_at', '')}*")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
