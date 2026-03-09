"""Tests for event quality features (regulatory_quality, clinical_quality, etc.)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.event_quality_features import EVENT_QUALITY_COLUMNS, compute_event_quality_features


class TestRegulatoryQuality:
    def test_pdufa_regulatory_high(self):
        row = {
            "catalyst_family": "REGULATORY",
            "catalyst_event_type": "PDUFA",
            "catalyst_source": "SEC_8K_FILING",
        }
        f = compute_event_quality_features(row)
        assert f["regulatory_quality"] > 0.8

    def test_adcom_regulatory(self):
        row = {
            "catalyst_family": "REGULATORY",
            "catalyst_event_type": "FDA_ADCOM",
            "catalyst_source": "FDA_FEDREG",
        }
        f = compute_event_quality_features(row)
        assert f["regulatory_quality"] > 0.7
        assert f["has_adcom"] == 1

    def test_non_regulatory_gets_zero(self):
        row = {
            "catalyst_family": "CLINICAL",
            "catalyst_event_type": "DATA_READOUT",
            "catalyst_source": "CTGOV_CALENDAR",
        }
        f = compute_event_quality_features(row)
        assert f["regulatory_quality"] == 0.0

    def test_submission_lower_than_pdufa(self):
        pdufa = compute_event_quality_features(
            {"catalyst_family": "REGULATORY", "catalyst_event_type": "PDUFA", "catalyst_source": "PDUFA_MANUAL"}
        )
        sub = compute_event_quality_features(
            {
                "catalyst_family": "REGULATORY",
                "catalyst_event_type": "FDA_SUBMISSION",
                "catalyst_source": "CTGOV_CALENDAR",
            }
        )
        assert pdufa["regulatory_quality"] > sub["regulatory_quality"]


class TestClinicalQuality:
    def test_data_readout_phase3(self):
        row = {
            "catalyst_family": "CLINICAL",
            "catalyst_event_type": "DATA_READOUT",
            "lead_program_phase": "3.0",
            "design_quality_score": "0.8",
            "program_count": "3",
        }
        f = compute_event_quality_features(row)
        assert f["clinical_quality"] > 0.7

    def test_pcd_phase1_lower(self):
        row = {
            "catalyst_family": "CLINICAL",
            "catalyst_event_type": "CT_PRIMARY_COMPLETION",
            "lead_program_phase": "1.0",
            "design_quality_score": "0.3",
            "program_count": "1",
        }
        f = compute_event_quality_features(row)
        assert f["clinical_quality"] < 0.5

    def test_non_clinical_gets_zero(self):
        row = {
            "catalyst_family": "REGULATORY",
            "catalyst_event_type": "PDUFA",
        }
        f = compute_event_quality_features(row)
        assert f["clinical_quality"] == 0.0

    def test_more_programs_higher_quality(self):
        base = {
            "catalyst_family": "CLINICAL",
            "catalyst_event_type": "DATA_READOUT",
            "lead_program_phase": "2.0",
            "design_quality_score": "0.5",
        }
        one = compute_event_quality_features({**base, "program_count": "1"})
        five = compute_event_quality_features({**base, "program_count": "5"})
        assert five["clinical_quality"] > one["clinical_quality"]


class TestHasAdcom:
    def test_adcom_flagged(self):
        f = compute_event_quality_features({"catalyst_family": "REGULATORY", "catalyst_event_type": "FDA_ADCOM"})
        assert f["has_adcom"] == 1

    def test_pdufa_not_adcom(self):
        f = compute_event_quality_features({"catalyst_family": "REGULATORY", "catalyst_event_type": "PDUFA"})
        assert f["has_adcom"] == 0

    def test_empty_not_adcom(self):
        f = compute_event_quality_features({})
        assert f["has_adcom"] == 0


class TestSingleAssetRisk:
    def test_single_program(self):
        f = compute_event_quality_features(
            {"catalyst_family": "CLINICAL", "catalyst_event_type": "DATA_READOUT", "program_count": "1"}
        )
        assert f["single_asset_risk"] == 1

    def test_multi_program(self):
        f = compute_event_quality_features(
            {"catalyst_family": "CLINICAL", "catalyst_event_type": "DATA_READOUT", "program_count": "3"}
        )
        assert f["single_asset_risk"] == 0

    def test_missing_program_count(self):
        f = compute_event_quality_features({"catalyst_family": "CLINICAL", "catalyst_event_type": "DATA_READOUT"})
        # missing → 0 (not single asset)
        assert f["single_asset_risk"] == 0


class TestEventQualityColumns:
    def test_all_columns_present(self):
        f = compute_event_quality_features({})
        for col in EVENT_QUALITY_COLUMNS:
            assert col in f

    def test_columns_list(self):
        assert "regulatory_quality" in EVENT_QUALITY_COLUMNS
        assert "clinical_quality" in EVENT_QUALITY_COLUMNS
        assert "has_adcom" in EVENT_QUALITY_COLUMNS
        assert "single_asset_risk" in EVENT_QUALITY_COLUMNS
