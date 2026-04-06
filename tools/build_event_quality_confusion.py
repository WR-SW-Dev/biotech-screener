#!/usr/bin/env python3
"""Event quality confusion dashboard.

Reads ground truth labels and Herald predictions, computes confusion matrices
and per-category P/R/F1 broken down by family, source, and horizon.
Flags drift when F1 drops > 5pp from trailing average.

Mirrors the pattern of build_herald_precision_dashboard.py.

Usage:
    python tools/build_event_quality_confusion.py
    python tools/build_event_quality_confusion.py --as-of-date 2026-04-05
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

GT_DIR = PROJECT_ROOT / "data" / "ground_truth"
LEGACY_GT_DIR = PROJECT_ROOT / "artifacts" / "herald_ground_truth"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "event_quality"

SCHEMA = "event_quality_confusion.v1"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ground truth loading
# ---------------------------------------------------------------------------


def load_ground_truth(gt_dir: Path = GT_DIR, legacy_dir: Path = LEGACY_GT_DIR) -> list[dict]:
    """Load all labeled ground truth records from batch files."""
    records = []

    for d in (gt_dir, legacy_dir):
        if not d.exists():
            continue
        for f in sorted(d.glob("*.jsonl")):
            try:
                for line in f.read_text().splitlines():
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        # Only include records that have some ground truth
                        if rec.get("gt_label_source") and rec["gt_label_source"] != "unlabeled":
                            records.append(rec)
            except Exception as e:
                logger.warning("Error reading %s: %s", f, e)

    logger.info("Loaded %d labeled ground truth records", len(records))
    return records


# ---------------------------------------------------------------------------
# Confusion matrix computation
# ---------------------------------------------------------------------------


def compute_confusion(records: list[dict], pred_field: str, truth_field: str) -> dict:
    """Compute confusion matrix and P/R/F1 per class.

    Returns dict with:
    - matrix: {predicted: {actual: count}}
    - per_class: {class: {tp, fp, fn, precision, recall, f1, support}}
    - n_total, n_correct, accuracy
    """
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    all_classes: set[str] = set()

    for r in records:
        pred = (r.get(pred_field) or "unknown").lower()
        truth = (r.get(truth_field) or "unknown").lower()
        matrix[pred][truth] += 1
        all_classes.add(pred)
        all_classes.add(truth)

    # Per-class metrics
    per_class = {}
    for cls in sorted(all_classes):
        tp = matrix[cls].get(cls, 0)
        fp = sum(matrix[cls].get(other, 0) for other in all_classes if other != cls)
        fn = sum(matrix[other].get(cls, 0) for other in all_classes if other != cls)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        per_class[cls] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support": tp + fn,
        }

    n_total = sum(sum(v.values()) for v in matrix.values())
    n_correct = sum(matrix[c].get(c, 0) for c in all_classes)

    return {
        "matrix": {k: dict(v) for k, v in matrix.items()},
        "per_class": per_class,
        "n_total": n_total,
        "n_correct": n_correct,
        "accuracy": round(n_correct / max(n_total, 1), 3),
    }


def find_top_confusion_pairs(matrix: dict, n_top: int = 5) -> list[dict]:
    """Find the most common misclassification pairs."""
    pairs = []
    for pred, actuals in matrix.items():
        for actual, count in actuals.items():
            if pred != actual and count > 0:
                pairs.append(
                    {
                        "predicted": pred,
                        "actual": actual,
                        "count": count,
                    }
                )
    pairs.sort(key=lambda x: x["count"], reverse=True)
    return pairs[:n_top]


# ---------------------------------------------------------------------------
# Sliced confusion (by family, source, etc.)
# ---------------------------------------------------------------------------


def compute_sliced_confusion(
    records: list[dict],
    slice_field: str,
    pred_field: str = "event_category",
    truth_field: str = "gt_event_category",
) -> dict[str, dict]:
    """Compute confusion metrics per slice of a grouping field."""
    by_slice: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        key = (r.get(slice_field) or "unknown").lower()
        by_slice[key].append(r)

    results = {}
    for key, recs in sorted(by_slice.items()):
        if len(recs) < 3:
            continue  # skip tiny slices
        confusion = compute_confusion(recs, pred_field, truth_field)
        results[key] = {
            "n": len(recs),
            "accuracy": confusion["accuracy"],
            "per_class": confusion["per_class"],
        }
    return results


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def detect_f1_drift(
    current_per_class: dict,
    baseline_per_class: dict | None,
    threshold_pp: float = 5.0,
) -> list[dict]:
    """Flag classes where F1 dropped > threshold_pp from baseline."""
    if not baseline_per_class:
        return []

    flags = []
    for cls in current_per_class:
        if cls not in baseline_per_class:
            continue
        curr_f1 = current_per_class[cls]["f1"]
        base_f1 = baseline_per_class[cls]["f1"]
        delta_pp = (curr_f1 - base_f1) * 100
        if delta_pp < -threshold_pp:
            flags.append(
                {
                    "class": cls,
                    "current_f1": curr_f1,
                    "baseline_f1": base_f1,
                    "delta_pp": round(delta_pp, 1),
                    "flag": "F1_DRIFT",
                }
            )
    return flags


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_confusion_dashboard(as_of_date: str = "") -> dict:
    """Build the complete event quality confusion dashboard."""
    records = load_ground_truth()

    if not records:
        return {
            "schema": SCHEMA,
            "as_of_date": as_of_date or date.today().isoformat(),
            "n_labeled": 0,
            "error": "No labeled ground truth records found",
        }

    # Overall confusion: Herald event_category vs ground truth
    overall = compute_confusion(records, "event_category", "gt_event_category")
    top_pairs = find_top_confusion_pairs(overall["matrix"])

    # Sliced confusion
    by_family = compute_sliced_confusion(records, "catalyst_family")
    by_source = compute_sliced_confusion(records, "source_type")

    # Label source distribution
    label_dist: dict[str, int] = defaultdict(int)
    for r in records:
        label_dist[r.get("gt_label_source", "unknown")] += 1

    # Load prior dashboard for drift detection (if exists)
    prior_per_class = None
    prior_path = OUTPUT_DIR / "confusion_dashboard.json"
    if prior_path.exists():
        try:
            prior = json.loads(prior_path.read_text())
            prior_per_class = prior.get("overall", {}).get("per_class")
        except Exception:
            pass

    drift_flags = detect_f1_drift(overall["per_class"], prior_per_class)

    return {
        "schema": SCHEMA,
        "as_of_date": as_of_date or date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_labeled": len(records),
        "label_source_dist": dict(sorted(label_dist.items())),
        "overall": {
            "accuracy": overall["accuracy"],
            "n_total": overall["n_total"],
            "n_correct": overall["n_correct"],
            "per_class": overall["per_class"],
            "matrix": overall["matrix"],
        },
        "top_confusion_pairs": top_pairs,
        "by_family": by_family,
        "by_source": by_source,
        "drift_flags": drift_flags,
    }


def main():
    parser = argparse.ArgumentParser(description="Event quality confusion dashboard")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    result = build_confusion_dashboard(args.as_of_date)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "confusion_dashboard.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    print(f"EVENT QUALITY CONFUSION DASHBOARD -- {result['as_of_date']}")
    print(f"  Labeled records: {result['n_labeled']}")
    if result.get("overall"):
        print(f"  Accuracy: {result['overall']['accuracy']}")
        print("  Per-class:")
        for cls, m in sorted(result["overall"].get("per_class", {}).items()):
            print(f"    {cls}: P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} (n={m['support']})")
    if result.get("top_confusion_pairs"):
        print("  Top confusion pairs:")
        for p in result["top_confusion_pairs"]:
            print(f"    {p['predicted']} -> {p['actual']}: {p['count']}")
    if result.get("drift_flags"):
        print(f"  DRIFT FLAGS: {len(result['drift_flags'])}")
        for f in result["drift_flags"]:
            print(f"    {f['class']}: F1 {f['baseline_f1']:.2f} -> {f['current_f1']:.2f} ({f['delta_pp']:+.1f}pp)")
    print(f"  Saved: {out_path}")


def build_outlier_review_queue(as_of_date: str = "") -> dict:
    """Identify misclassification outliers needing human review.

    Finds: false-informational cases (informational_only but large move),
    top confusion pairs, low-confidence auto-labels.
    """
    records = load_ground_truth()
    if not records:
        return {"n_outliers": 0, "queue": []}

    queue = []
    for r in records:
        urgency = 0
        reasons = []

        # False informational: labeled informational but had large return
        ret = r.get("gt_return_pct")
        if r.get("gt_informational_only") and ret is not None and abs(ret) > 10:
            urgency += 4
            reasons.append(f"FALSE_INFORMATIONAL(ret={ret:+.1f}%)")

        # Herald/GT category disagreement
        herald = (r.get("event_category") or "").lower()
        gt = (r.get("gt_event_category") or "").lower()
        if herald and gt and herald != gt:
            urgency += 3
            reasons.append(f"CATEGORY_MISMATCH({herald}→{gt})")

        # Low auto-label confidence
        conf = r.get("gt_auto_confidence", 1.0)
        if r.get("gt_label_source") == "price_reaction_low_conf":
            urgency += 2
            reasons.append(f"LOW_AUTO_CONFIDENCE({conf:.2f})")

        if urgency > 0:
            queue.append(
                {
                    "ticker": r.get("ticker", "?"),
                    "date": r.get("published_at_utc", "")[:10],
                    "headline": r.get("headline", "")[:80],
                    "herald_category": herald,
                    "gt_category": gt,
                    "label_source": r.get("gt_label_source", "?"),
                    "return_pct": ret,
                    "urgency": urgency,
                    "reasons": reasons,
                    "suggested_action": "MANUAL_REVIEW",
                }
            )

    queue.sort(key=lambda x: -x["urgency"])

    result = {
        "schema": "outlier_review_queue.v1",
        "as_of_date": as_of_date or date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_outliers": len(queue),
        "queue": queue[:50],  # top 50
    }

    out_path = OUTPUT_DIR / "outlier_review_queue.json"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    main()
