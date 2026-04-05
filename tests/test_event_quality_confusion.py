"""Tests for event quality confusion dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_event_quality_confusion import (
    compute_confusion,
    compute_sliced_confusion,
    detect_f1_drift,
    find_top_confusion_pairs,
)


class TestComputeConfusion:
    def test_perfect_classification(self):
        records = [
            {"event_category": "clinical", "gt_event_category": "clinical"},
            {"event_category": "regulatory", "gt_event_category": "regulatory"},
            {"event_category": "clinical", "gt_event_category": "clinical"},
        ]
        result = compute_confusion(records, "event_category", "gt_event_category")
        assert result["accuracy"] == 1.0
        assert result["n_correct"] == 3
        assert result["per_class"]["clinical"]["precision"] == 1.0
        assert result["per_class"]["clinical"]["recall"] == 1.0
        assert result["per_class"]["clinical"]["f1"] == 1.0

    def test_complete_misclassification(self):
        records = [
            {"event_category": "clinical", "gt_event_category": "regulatory"},
            {"event_category": "clinical", "gt_event_category": "regulatory"},
        ]
        result = compute_confusion(records, "event_category", "gt_event_category")
        assert result["accuracy"] == 0.0
        assert result["per_class"]["clinical"]["precision"] == 0.0

    def test_partial_confusion(self):
        records = [
            {"event_category": "clinical", "gt_event_category": "clinical"},
            {"event_category": "clinical", "gt_event_category": "regulatory"},
            {"event_category": "regulatory", "gt_event_category": "regulatory"},
        ]
        result = compute_confusion(records, "event_category", "gt_event_category")
        assert result["n_total"] == 3
        assert result["n_correct"] == 2
        # clinical: TP=1, FP=1, FN=0 → P=0.5, R=1.0
        assert result["per_class"]["clinical"]["precision"] == 0.5
        assert result["per_class"]["clinical"]["recall"] == 1.0

    def test_matrix_structure(self):
        records = [
            {"event_category": "A", "gt_event_category": "A"},
            {"event_category": "A", "gt_event_category": "B"},
            {"event_category": "B", "gt_event_category": "B"},
        ]
        result = compute_confusion(records, "event_category", "gt_event_category")
        assert result["matrix"]["a"]["a"] == 1
        assert result["matrix"]["a"]["b"] == 1
        assert result["matrix"]["b"]["b"] == 1

    def test_empty_records(self):
        result = compute_confusion([], "event_category", "gt_event_category")
        assert result["n_total"] == 0
        assert result["accuracy"] == 0.0

    def test_missing_fields_default_to_unknown(self):
        records = [{"event_category": "clinical"}, {}]
        result = compute_confusion(records, "event_category", "gt_event_category")
        assert "unknown" in result["per_class"]


class TestTopConfusionPairs:
    def test_finds_top_pairs(self):
        matrix = {
            "clinical": {"clinical": 10, "regulatory": 5, "safety": 2},
            "regulatory": {"regulatory": 8, "clinical": 1},
        }
        pairs = find_top_confusion_pairs(matrix, n_top=2)
        assert len(pairs) == 2
        assert pairs[0]["predicted"] == "clinical"
        assert pairs[0]["actual"] == "regulatory"
        assert pairs[0]["count"] == 5

    def test_no_confusion(self):
        matrix = {"clinical": {"clinical": 10}}
        pairs = find_top_confusion_pairs(matrix)
        assert pairs == []


class TestSlicedConfusion:
    def test_slices_by_field(self):
        records = [
            {"catalyst_family": "REGULATORY", "event_category": "reg", "gt_event_category": "reg"},
            {"catalyst_family": "REGULATORY", "event_category": "reg", "gt_event_category": "reg"},
            {"catalyst_family": "REGULATORY", "event_category": "reg", "gt_event_category": "reg"},
            {"catalyst_family": "CLINICAL", "event_category": "clin", "gt_event_category": "clin"},
            {"catalyst_family": "CLINICAL", "event_category": "clin", "gt_event_category": "clin"},
            {"catalyst_family": "CLINICAL", "event_category": "clin", "gt_event_category": "other"},
        ]
        result = compute_sliced_confusion(records, "catalyst_family")
        assert "regulatory" in result
        assert "clinical" in result
        assert result["regulatory"]["accuracy"] == 1.0
        assert result["clinical"]["n"] == 3

    def test_skips_tiny_slices(self):
        records = [
            {"catalyst_family": "X", "event_category": "a", "gt_event_category": "a"},
            {"catalyst_family": "X", "event_category": "a", "gt_event_category": "a"},
        ]
        result = compute_sliced_confusion(records, "catalyst_family")
        assert "x" not in result  # n=2 < 3


class TestF1Drift:
    def test_no_drift(self):
        current = {"clinical": {"f1": 0.80}}
        baseline = {"clinical": {"f1": 0.82}}
        flags = detect_f1_drift(current, baseline)
        assert flags == []

    def test_drift_detected(self):
        current = {"clinical": {"f1": 0.70}}
        baseline = {"clinical": {"f1": 0.85}}
        flags = detect_f1_drift(current, baseline, threshold_pp=5.0)
        assert len(flags) == 1
        assert flags[0]["class"] == "clinical"
        assert flags[0]["flag"] == "F1_DRIFT"

    def test_no_baseline(self):
        current = {"clinical": {"f1": 0.70}}
        flags = detect_f1_drift(current, None)
        assert flags == []
