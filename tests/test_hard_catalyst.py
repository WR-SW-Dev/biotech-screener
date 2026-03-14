"""Tests for common/hard_catalyst.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.hard_catalyst import classify_hard_catalyst, is_hard_catalyst


class TestClassifyHardCatalyst:
    def test_data_readout(self):
        r = classify_hard_catalyst("DATA_READOUT")
        assert r["is_hard_catalyst"] is True
        assert "hard_event_type" in r["reason"]

    def test_pdufa(self):
        assert is_hard_catalyst("PDUFA") is True
        assert is_hard_catalyst("FDA_PDUFA_DATE") is True

    def test_fda_decision(self):
        assert is_hard_catalyst("FDA_DECISION") is True
        assert is_hard_catalyst("FDA_APPROVAL") is True
        assert is_hard_catalyst("FDA_CRL") is True

    def test_adcom(self):
        assert is_hard_catalyst("ADVISORY_COMMITTEE") is True
        assert is_hard_catalyst("FDA_ADCOM") is True

    def test_ema(self):
        assert is_hard_catalyst("EMA_DECISION") is True
        assert is_hard_catalyst("EMA_AGENDA") is True

    def test_ct_primary_completion_is_soft(self):
        r = classify_hard_catalyst("CT_PRIMARY_COMPLETION")
        assert r["is_hard_catalyst"] is False
        assert "soft_event_type" in r["reason"]

    def test_ct_study_completion_is_soft(self):
        assert is_hard_catalyst("CT_STUDY_COMPLETION") is False

    def test_results_posted_is_soft(self):
        assert is_hard_catalyst("CT_RESULTS_POSTED") is False

    def test_hard_source_overrides(self):
        """SEC_8K_FILING source makes it hard regardless of event type."""
        r = classify_hard_catalyst("CT_PRIMARY_COMPLETION", source="SEC_8K_FILING")
        assert r["is_hard_catalyst"] is True
        assert "hard_source" in r["reason"]

    def test_soft_source(self):
        r = classify_hard_catalyst("", source="CTGOV_CALENDAR")
        assert r["is_hard_catalyst"] is False

    def test_abs_gap_backstop(self):
        """Large abs_gap → hard regardless of labeling."""
        r = classify_hard_catalyst("", abs_gap=0.25)
        assert r["is_hard_catalyst"] is True
        assert "backstop" in r["reason"]

    def test_small_gap_not_backstop(self):
        r = classify_hard_catalyst("", abs_gap=0.03)
        assert r["is_hard_catalyst"] is False

    def test_unknown_defaults_to_not_hard(self):
        r = classify_hard_catalyst("SOME_NEW_TYPE")
        assert r["is_hard_catalyst"] is False
        assert "unknown" in r["reason"]

    def test_case_insensitive(self):
        assert is_hard_catalyst("data_readout") is True
        assert is_hard_catalyst("Data_Readout") is True

    def test_keyword_match(self):
        r = classify_hard_catalyst("topline_data_expected")
        assert r["is_hard_catalyst"] is True
        assert "keyword" in r["reason"]

    def test_borderline_presentation_is_soft_by_default(self):
        """DATA_PRESENTATION without explicit match → not hard."""
        r = classify_hard_catalyst("DATA_PRESENTATION")
        assert r["is_hard_catalyst"] is False

    def test_empty_inputs(self):
        r = classify_hard_catalyst("")
        assert r["is_hard_catalyst"] is False

    def test_reason_always_present(self):
        for et in ["DATA_READOUT", "CT_PRIMARY_COMPLETION", "", "UNKNOWN"]:
            r = classify_hard_catalyst(et)
            assert "reason" in r
            assert r["reason"] != ""
