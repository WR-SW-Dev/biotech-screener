"""Tests for the unified review packet builder."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_review_packet import (
    _mean_ets,
    _summarize_calibration,
    _summarize_confusion,
    _summarize_source_reliability,
    _summarize_timing_warnings,
)


class TestSummarizeTimingWarnings:
    def test_extracts_warnings(self):
        timing = {
            "catalysts": [
                {
                    "ticker": "ACME",
                    "rank": 1,
                    "catalyst_days": 15,
                    "catalyst_family": "REGULATORY",
                    "on_time_prob": 0.85,
                    "timing_confidence_bucket": "HIGH",
                    "execution_warning_flag": True,
                    "warning_reasons": [
                        {"label": "SHORT_DATED_REVISION_RISK", "reason": "Near-term pushout", "drivers": []},
                    ],
                },
                {
                    "ticker": "BETA",
                    "rank": 5,
                    "catalyst_days": 90,
                    "on_time_prob": 0.70,
                    "timing_confidence_bucket": "MEDIUM",
                    "execution_warning_flag": False,
                    "warning_reasons": [],
                },
            ]
        }
        warnings = _summarize_timing_warnings(timing)
        assert len(warnings) == 1
        assert warnings[0]["ticker"] == "ACME"
        assert "SHORT_DATED_REVISION_RISK" in warnings[0]["warnings"]

    def test_no_warnings(self):
        timing = {"catalysts": [{"execution_warning_flag": False}]}
        assert _summarize_timing_warnings(timing) == []


class TestSummarizeCalibration:
    def test_with_data(self):
        cal = {
            "n_resolved": 50,
            "overall": {"brier": 0.18, "overconfidence": 0.03},
            "horizons": {
                "NEAR": {"n": 20, "brier": 0.15, "actual_rate": 0.75},
                "FAR": {"n": 30, "brier": 0.20, "actual_rate": 0.65},
            },
            "sources": {
                "FDA": {"n": 15, "brier": 0.10},
                "CTGOV": {"n": 35, "brier": 0.22},
            },
        }
        result = _summarize_calibration(cal)
        assert result["available"] is True
        assert result["overall_brier"] == 0.18
        assert "NEAR" in result["by_horizon"]
        assert len(result["by_source_top5"]) == 2

    def test_none_input(self):
        result = _summarize_calibration(None)
        assert result["available"] is False


class TestSummarizeConfusion:
    def test_with_data(self):
        confusion = {
            "n_labeled": 100,
            "overall": {"accuracy": 0.75},
            "top_confusion_pairs": [
                {"predicted": "clin", "actual": "reg", "count": 5},
                {"predicted": "reg", "actual": "other", "count": 3},
            ],
            "drift_flags": [{"class": "clin", "flag": "F1_DRIFT"}],
        }
        result = _summarize_confusion(confusion)
        assert result["available"] is True
        assert result["accuracy"] == 0.75
        assert len(result["top_confusion_pairs"]) == 2
        assert len(result["drift_flags"]) == 1

    def test_none_input(self):
        result = _summarize_confusion(None)
        assert result["available"] is False


class TestSummarizeSourceReliability:
    def test_sorts_by_action(self):
        rel = {
            "buckets": [
                {
                    "source": "ALLOW_SRC",
                    "family": "CLINICAL",
                    "action": "ALLOW",
                    "reliability_score": 0.9,
                    "sample_count": 20,
                    "large_slip_rate": 0.05,
                },
                {
                    "source": "SUPPRESS_SRC",
                    "family": "CLINICAL",
                    "action": "SUPPRESS",
                    "reliability_score": 0.1,
                    "sample_count": 10,
                    "large_slip_rate": 0.50,
                },
                {
                    "source": "DEMOTE_SRC",
                    "family": "REGULATORY",
                    "action": "DEMOTE",
                    "reliability_score": 0.5,
                    "sample_count": 15,
                    "large_slip_rate": 0.25,
                },
            ]
        }
        result = _summarize_source_reliability(rel)
        assert result[0]["action"] == "SUPPRESS"
        assert result[1]["action"] == "DEMOTE"
        assert result[2]["action"] == "ALLOW"

    def test_none_input(self):
        assert _summarize_source_reliability(None) == []


class TestMeanETS:
    def test_computes_mean(self):
        eq = {"positions": [{"event_type_score": 3}, {"event_type_score": 1}, {"event_type_score": 2}]}
        assert _mean_ets(eq) == 2.0

    def test_none_scores(self):
        eq = {"positions": [{"event_type_score": None}]}
        assert _mean_ets(eq) is None

    def test_empty(self):
        assert _mean_ets({"positions": []}) is None
