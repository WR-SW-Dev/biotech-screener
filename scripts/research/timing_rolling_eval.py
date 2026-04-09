#!/usr/bin/env python3
"""Rolling-window evaluation of timing hazard models on expanded calibration ledger.

Tests whether rolling calibration beats fixed rules on 1,691 resolved outcomes.
Evaluates three approaches:
  1. Fixed rules (current production defaults)
  2. Rolling base rate by family × horizon (sliding 180d window)
  3. Rolling base rate by family × horizon × hardness (sliding 180d window)

The key insight from prior work: non-stationarity (2025 on-time=90%, 2026=62.7%)
means fixed coefficients overfit. Rolling calibration adapts.

Usage:
    python3 scripts/research/timing_rolling_eval.py
    python3 scripts/research/timing_rolling_eval.py --window 120

Output:
    output/timing_rolling_eval/rolling_eval_report.json
    output/timing_rolling_eval/rolling_eval_report.md
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from common.stats.calibration import brier_score, expected_calibration_error

LEDGER_PATH = PROJECT_ROOT / "artifacts" / "timing_hazard" / "calibration_ledger.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "output" / "timing_rolling_eval"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_ledger() -> List[Dict[str, Any]]:
    """Load resolved entries from calibration ledger."""
    entries = []
    with open(LEDGER_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("actual_outcome") not in ("ON_TIME", "SLIP"):
                continue
            e["_on_time"] = 1.0 if e["actual_outcome"] == "ON_TIME" else 0.0
            e["_pred_date"] = date.fromisoformat(e["prediction_date"])
            entries.append(e)
    entries.sort(key=lambda e: e["_pred_date"])
    return entries


# ---------------------------------------------------------------------------
# Fixed-rule baseline (current production)
# ---------------------------------------------------------------------------

# These match the constants in compute_timing_hazard.py
NEAR_TERM_DAYS = 30
NEAR_TERM_HARD_PROB = 0.85
NEAR_TERM_SOFT_PROB = 0.55
NEAR_TERM_REGULATORY_PROB = 0.92
ROLLING_FALLBACK = 0.70


def fixed_rule_prob(entry: Dict) -> float:
    """Compute the fixed-rule on-time probability."""
    cat_days = entry.get("catalyst_days", 60)
    family = entry.get("family_bucket", "")
    is_hard = entry.get("is_hard_catalyst", False)

    if cat_days <= NEAR_TERM_DAYS:
        if family == "REGULATORY":
            return NEAR_TERM_REGULATORY_PROB
        elif is_hard:
            return NEAR_TERM_HARD_PROB
        else:
            return NEAR_TERM_SOFT_PROB
    return ROLLING_FALLBACK


# ---------------------------------------------------------------------------
# Rolling base rate models
# ---------------------------------------------------------------------------


def _build_rolling_prob(
    train_entries: List[Dict],
    group_keys: List[str],
    min_samples: int = 10,
) -> Dict[tuple, float]:
    """Compute base rates by group from training window."""
    groups: Dict[tuple, List[float]] = defaultdict(list)
    for e in train_entries:
        key = tuple(str(e.get(k, "")) for k in group_keys)
        groups[key].append(e["_on_time"])

    rates = {}
    global_rate = np.mean([e["_on_time"] for e in train_entries]) if train_entries else 0.5
    for key, vals in groups.items():
        if len(vals) >= min_samples:
            rates[key] = float(np.mean(vals))
        else:
            rates[key] = global_rate
    rates[("__global__",)] = global_rate
    return rates


def rolling_eval(
    entries: List[Dict],
    window_days: int = 180,
    group_keys: List[str] = ("family_bucket", "horizon_bucket"),
    min_train: int = 30,
) -> Dict[str, Any]:
    """Evaluate rolling base-rate model with proper temporal split.

    For each test entry at date D, train on entries from [D - window, D).
    Returns per-entry predictions and aggregate metrics.
    """
    predictions = []
    actuals = []
    details = []

    for i, entry in enumerate(entries):
        test_date = entry["_pred_date"]
        window_start = test_date - timedelta(days=window_days)

        # Training window: all entries before test_date within window
        train = [e for e in entries[:i] if window_start <= e["_pred_date"] < test_date]

        if len(train) < min_train:
            continue  # skip until we have enough training data

        rates = _build_rolling_prob(train, group_keys)
        key = tuple(str(entry.get(k, "")) for k in group_keys)
        prob = rates.get(key, rates.get(("__global__",), 0.5))

        predictions.append(prob)
        actuals.append(entry["_on_time"])
        details.append(
            {
                "prediction_date": entry["prediction_date"],
                "ticker": entry.get("ticker", ""),
                "prob": round(prob, 4),
                "actual": entry["actual_outcome"],
                "train_n": len(train),
            }
        )

    if not predictions:
        return {"error": "insufficient data for rolling evaluation"}

    p = np.array(predictions)
    a = np.array(actuals)

    return {
        "n_evaluated": len(predictions),
        "n_skipped": len(entries) - len(predictions),
        "window_days": window_days,
        "group_keys": group_keys,
        "brier": round(float(brier_score(p, a)), 4),
        "ece": round(float(expected_calibration_error(p, a, n_bins=5)), 4),
        "base_rate": round(float(np.mean(a)), 4),
        "mean_predicted": round(float(np.mean(p)), 4),
        "details": details,
    }


# ---------------------------------------------------------------------------
# Yearly stability analysis
# ---------------------------------------------------------------------------


def yearly_breakdown(
    entries: List[Dict],
    prob_fn,
) -> Dict[str, Dict]:
    """Compute Brier/ECE by year."""
    by_year: Dict[str, Tuple[List, List]] = defaultdict(lambda: ([], []))
    for e in entries:
        year = e["prediction_date"][:4]
        p = prob_fn(e)
        by_year[year][0].append(p)
        by_year[year][1].append(e["_on_time"])

    results = {}
    for year in sorted(by_year):
        preds, acts = by_year[year]
        p = np.array(preds)
        a = np.array(acts)
        results[year] = {
            "n": len(preds),
            "brier": round(float(brier_score(p, a)), 4),
            "base_rate": round(float(np.mean(a)), 4),
            "mean_predicted": round(float(np.mean(p)), 4),
        }
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Rolling-window timing evaluation")
    parser.add_argument("--window", type=int, default=180, help="Rolling window days")
    args = parser.parse_args()

    print("=" * 70)
    print("ROLLING-WINDOW TIMING HAZARD EVALUATION")
    print("=" * 70)

    entries = load_ledger()
    print(f"\nLedger: {len(entries)} resolved entries")
    print(f"  Date range: {entries[0]['prediction_date']} to {entries[-1]['prediction_date']}")
    on_time = sum(1 for e in entries if e["_on_time"] == 1)
    print(f"  ON_TIME: {on_time} ({100*on_time/len(entries):.1f}%)")
    print(f"  SLIP: {len(entries)-on_time} ({100*(len(entries)-on_time)/len(entries):.1f}%)")

    # 1. Fixed rule baseline
    print("\n--- Fixed Rule Baseline ---")
    fixed_preds = np.array([fixed_rule_prob(e) for e in entries])
    fixed_acts = np.array([e["_on_time"] for e in entries])
    fixed_brier = float(brier_score(fixed_preds, fixed_acts))
    fixed_ece = float(expected_calibration_error(fixed_preds, fixed_acts, n_bins=5))
    print(f"  Brier: {fixed_brier:.4f}")
    print(f"  ECE: {fixed_ece:.4f}")

    # 2. Rolling base rate by family × horizon
    print(f"\n--- Rolling Base Rate (family × horizon, {args.window}d window) ---")
    rolling_fh = rolling_eval(entries, window_days=args.window, group_keys=["family_bucket", "horizon_bucket"])
    if "error" not in rolling_fh:
        print(f"  Evaluated: {rolling_fh['n_evaluated']} (skipped {rolling_fh['n_skipped']})")
        print(f"  Brier: {rolling_fh['brier']:.4f}")
        print(f"  ECE: {rolling_fh['ece']:.4f}")
    else:
        print(f"  {rolling_fh['error']}")

    # 3. Rolling base rate by family × horizon × hardness
    print(f"\n--- Rolling Base Rate (family × horizon × hardness, {args.window}d window) ---")
    rolling_fhh = rolling_eval(
        entries,
        window_days=args.window,
        group_keys=["family_bucket", "horizon_bucket", "hardness"],
    )
    if "error" not in rolling_fhh:
        print(f"  Evaluated: {rolling_fhh['n_evaluated']} (skipped {rolling_fhh['n_skipped']})")
        print(f"  Brier: {rolling_fhh['brier']:.4f}")
        print(f"  ECE: {rolling_fhh['ece']:.4f}")
    else:
        print(f"  {rolling_fhh['error']}")

    # 4. Rolling by family only (coarser)
    print(f"\n--- Rolling Base Rate (family only, {args.window}d window) ---")
    rolling_f = rolling_eval(entries, window_days=args.window, group_keys=["family_bucket"])
    if "error" not in rolling_f:
        print(f"  Evaluated: {rolling_f['n_evaluated']} (skipped {rolling_f['n_skipped']})")
        print(f"  Brier: {rolling_f['brier']:.4f}")
        print(f"  ECE: {rolling_f['ece']:.4f}")
    else:
        print(f"  {rolling_f['error']}")

    # 5. Yearly stability
    print("\n--- Yearly Breakdown (Fixed Rules) ---")
    yearly_fixed = yearly_breakdown(entries, fixed_rule_prob)
    for year, stats in yearly_fixed.items():
        print(f"  {year}: n={stats['n']:4d}  Brier={stats['brier']:.4f}  base_rate={stats['base_rate']:.3f}")

    # Comparison table
    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    rows = [
        ("fixed_rules", fixed_brier, fixed_ece, len(entries)),
    ]
    for name, result in [
        ("rolling_family_horizon", rolling_fh),
        ("rolling_family_horizon_hardness", rolling_fhh),
        ("rolling_family_only", rolling_f),
    ]:
        if "error" not in result:
            rows.append((name, result["brier"], result["ece"], result["n_evaluated"]))

    rows.sort(key=lambda r: r[1])
    print(f"  {'Approach':42s} {'Brier':>8s} {'ECE':>8s} {'N':>6s}")
    print(f"  {'-'*42} {'-'*8} {'-'*8} {'-'*6}")
    for name, b, e, n in rows:
        print(f"  {name:42s} {b:8.4f} {e:8.4f} {n:6d}")

    # Save results
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": str(date.today()),
        "ledger_entries": len(entries),
        "window_days": args.window,
        "fixed_rules": {"brier": round(fixed_brier, 4), "ece": round(fixed_ece, 4), "n": len(entries)},
        "rolling_family_horizon": {k: v for k, v in rolling_fh.items() if k != "details"},
        "rolling_family_horizon_hardness": {k: v for k, v in rolling_fhh.items() if k != "details"},
        "rolling_family_only": {k: v for k, v in rolling_f.items() if k != "details"},
        "yearly_fixed": yearly_fixed,
        "comparison": [{"approach": name, "brier": b, "ece": e, "n": n} for name, b, e, n in rows],
    }
    json_path = OUTPUT_DIR / "rolling_eval_report.json"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport: {json_path}")

    # Verdict
    print("\n" + "=" * 70)
    best = rows[0]
    if best[0] != "fixed_rules":
        improvement = fixed_brier - best[1]
        pct = 100 * improvement / fixed_brier
        print(f"VERDICT: {best[0]} beats fixed rules by {improvement:+.4f} Brier ({pct:.1f}%)")
    else:
        print("VERDICT: Fixed rules remain best — rolling calibration adds no value")
    print("=" * 70)


if __name__ == "__main__":
    main()
