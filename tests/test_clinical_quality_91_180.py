"""Tests for clinical 91-180 quality features + decision engine integration.

Covers:
  1. Feature computation: precision, confidence, design, depth, composite
  2. Determinism: same inputs → same outputs
  3. Non-CLINICAL family returns empty/neutral
  4. Backfill fills new columns for legacy snapshots
  5. Decision engine contribution only applies in binary_91_180 + CLINICAL
  6. Degenerate/default fields → contribution is zero (no-op)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.event_quality_features import (
    CLINICAL_91_180_QUALITY_COLUMNS,
    compute_clinical_91_180_quality,
    compute_clinical_date_confidence,
    compute_clinical_days_precision,
    compute_clinical_design_quality,
    compute_clinical_program_depth,
    compute_clinical_quality_composite,
)
from common.ranking_utils import backfill_columns
from decision_engine import SORT_CONTRIB_KEYS, DecisionRuleset, _build_sort_contributions

# ---------------------------------------------------------------------------
# 1. Feature computation
# ---------------------------------------------------------------------------


class TestClinicalDaysPrecision:
    def test_specific_days_sec8k(self):
        assert compute_clinical_days_precision("specific_days", "SEC_8K_FILING") == "DAY"

    def test_specific_days_ctgov(self):
        assert compute_clinical_days_precision("specific_days", "CTGOV_CALENDAR") == "DAY"

    def test_blended_window_no_source(self):
        assert compute_clinical_days_precision("blended_window", "") == "MONTH"

    def test_far_window(self):
        assert compute_clinical_days_precision("far_window", "") == "QUARTER"

    def test_missing_mode(self):
        assert compute_clinical_days_precision("missing", "") == "UNKNOWN"

    def test_no_upcoming(self):
        assert compute_clinical_days_precision("no_upcoming", "") == "UNKNOWN"

    def test_source_overrides_mode(self):
        # SEC_8K source should override blended_window → DAY
        assert compute_clinical_days_precision("blended_window", "SEC_8K_FILING") == "DAY"

    def test_corporate_calendar(self):
        assert compute_clinical_days_precision("specific_days", "CORPORATE_CALENDAR") == "DAY"


class TestClinicalDateConfidence:
    def test_day_precision(self):
        conf = compute_clinical_date_confidence("DAY", "CTGOV_CALENDAR")
        assert conf == 0.95

    def test_day_with_sec8k_bonus(self):
        conf = compute_clinical_date_confidence("DAY", "SEC_8K_FILING")
        assert conf == 1.0

    def test_month_precision(self):
        conf = compute_clinical_date_confidence("MONTH", "")
        assert conf == 0.60

    def test_unknown_precision(self):
        conf = compute_clinical_date_confidence("UNKNOWN", "")
        assert conf == 0.10


class TestClinicalDesignQuality:
    def test_high_quality_row(self):
        row = {
            "design_quality_score": "0.80",
            "lead_program_phase": "3.0",
            "endpoint_strength_score": "0.85",
        }
        q = compute_clinical_design_quality(row)
        assert 0.7 < q <= 1.0

    def test_low_quality_row(self):
        row = {
            "design_quality_score": "0.10",
            "lead_program_phase": "1.0",
            "endpoint_strength_score": "0.30",
        }
        q = compute_clinical_design_quality(row)
        assert 0.0 < q < 0.5

    def test_missing_fields_uses_defaults(self):
        row = {}
        q = compute_clinical_design_quality(row)
        assert 0.0 < q < 1.0  # should not crash, returns neutral default


class TestClinicalProgramDepth:
    def test_multi_program(self):
        row = {"program_count": "4", "single_asset_risk": "0"}
        d = compute_clinical_program_depth(row)
        assert d == 1.0

    def test_single_program(self):
        row = {"program_count": "1", "single_asset_risk": "1"}
        d = compute_clinical_program_depth(row)
        # count_score = 0.25, penalty = 0.3, result = 0.0 (clipped)
        assert d == 0.0

    def test_two_programs(self):
        row = {"program_count": "2", "single_asset_risk": "0"}
        d = compute_clinical_program_depth(row)
        assert d == 0.5

    def test_missing_defaults(self):
        row = {}
        d = compute_clinical_program_depth(row)
        assert 0.0 <= d <= 1.0


class TestClinicalQualityComposite:
    def test_all_max(self):
        c = compute_clinical_quality_composite(1.0, 1.0, 1.0)
        assert c == 1.0

    def test_all_zero(self):
        c = compute_clinical_quality_composite(0.0, 0.0, 0.0)
        assert c == 0.0

    def test_weighted(self):
        c = compute_clinical_quality_composite(0.5, 0.5, 0.5)
        assert c == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 2. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_same_outputs(self):
        row = {
            "catalyst_family": "CLINICAL",
            "catalyst_mode": "specific_days",
            "catalyst_source": "CTGOV_CALENDAR",
            "design_quality_score": "0.65",
            "lead_program_phase": "2.5",
            "endpoint_strength_score": "0.70",
            "program_count": "3",
            "single_asset_risk": "0",
        }
        r1 = compute_clinical_91_180_quality(row)
        r2 = compute_clinical_91_180_quality(row)
        assert r1 == r2


# ---------------------------------------------------------------------------
# 3. Non-CLINICAL returns empty
# ---------------------------------------------------------------------------


class TestNonClinical:
    def test_regulatory_family(self):
        row = {"catalyst_family": "REGULATORY", "catalyst_mode": "specific_days"}
        result = compute_clinical_91_180_quality(row)
        assert result["clinical_quality_composite"] == ""
        assert result["clinical_days_precision"] == ""

    def test_empty_family(self):
        row = {"catalyst_family": "", "catalyst_mode": "specific_days"}
        result = compute_clinical_91_180_quality(row)
        assert result["clinical_quality_composite"] == ""

    def test_clinical_family_returns_values(self):
        row = {
            "catalyst_family": "CLINICAL",
            "catalyst_mode": "specific_days",
            "catalyst_source": "CTGOV_CALENDAR",
        }
        result = compute_clinical_91_180_quality(row)
        assert result["clinical_days_precision"] == "DAY"
        assert float(result["clinical_date_confidence"]) > 0
        assert float(result["clinical_quality_composite"]) > 0


# ---------------------------------------------------------------------------
# 4. Backfill
# ---------------------------------------------------------------------------


class TestBackfill:
    def test_backfill_adds_columns(self):
        rows = [
            {
                "ticker": "ABC",
                "catalyst_family": "CLINICAL",
                "catalyst_mode": "specific_days",
                "catalyst_source": "CTGOV_CALENDAR",
                "design_quality_score": "0.5",
                "lead_program_phase": "2.0",
                "endpoint_strength_score": "0.6",
                "program_count": "2",
                "single_asset_risk": "0",
                "clinical_score": "50",
                "archetype": "drug_developer_preclinical",
            }
        ]
        backfill_columns(rows)
        for col in CLINICAL_91_180_QUALITY_COLUMNS:
            assert col in rows[0], f"Missing column: {col}"
        assert rows[0]["clinical_days_precision"] == "DAY"

    def test_backfill_skips_if_present(self):
        rows = [
            {
                "ticker": "ABC",
                "clinical_quality_composite": "0.75",
                "clinical_days_precision": "DAY",
                "clinical_date_confidence": "0.95",
                "clinical_design_quality": "0.70",
                "clinical_program_depth": "0.50",
                "clinical_score": "50",
                "archetype": "drug_developer",
            }
        ]
        backfill_columns(rows)
        assert rows[0]["clinical_quality_composite"] == "0.75"


# ---------------------------------------------------------------------------
# 5. Decision engine: contribution only in less_binary + CLINICAL
# ---------------------------------------------------------------------------


class TestDEContribution:
    def _make_fields(self, bucket="less_binary", family="CLINICAL", composite="0.70"):
        return {
            "catalyst_bucket": bucket,
            "catalyst_family": family,
            "clinical_quality_composite": composite,
            "binary_quality_score": "0.5",
            "catalyst_mode": "specific_days",
            "catalyst_days": "120",
            "stage_bucket": "mid",
            "clinical_score_z_tier": "0",
            "inst_delta_z": "0",
            "clinical_score_v2_z": "0",
            "alpha_cohort_pct": "0",
        }

    def test_clinical_quality_mode_adds_contribution(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="clinical_quality",
            binary_91_180_clinical_quality_weight=1.0,
        )
        fields = self._make_fields()
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "clinical_quality_91_180" in names
        cq = [c for c in contribs if c.name == "clinical_quality_91_180"][0]
        assert cq.delta == pytest.approx(0.70)

    def test_baseline_mode_no_contribution(self):
        rs = DecisionRuleset(binary_91_180_sort_mode="baseline")
        fields = self._make_fields()
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "clinical_quality_91_180" not in names

    def test_wrong_bucket_no_contribution(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="clinical_quality",
            binary_91_180_clinical_quality_weight=1.0,
        )
        fields = self._make_fields(bucket="build_window")
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "clinical_quality_91_180" not in names

    def test_regulatory_family_no_contribution(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="clinical_quality",
            binary_91_180_clinical_quality_weight=1.0,
        )
        fields = self._make_fields(family="REGULATORY")
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "clinical_quality_91_180" not in names

    def test_weight_scales_contribution(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="clinical_quality",
            binary_91_180_clinical_quality_weight=0.5,
        )
        fields = self._make_fields(composite="0.80")
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        cq = [c for c in contribs if c.name == "clinical_quality_91_180"][0]
        assert cq.delta == pytest.approx(0.40)


# ---------------------------------------------------------------------------
# 6. Degenerate/default → no-op
# ---------------------------------------------------------------------------


class TestDegenerateNoop:
    def test_zero_composite_zero_contribution(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="clinical_quality",
            binary_91_180_clinical_quality_weight=1.0,
        )
        fields = {
            "catalyst_bucket": "less_binary",
            "catalyst_family": "CLINICAL",
            "clinical_quality_composite": "0.0",
            "binary_quality_score": "0",
        }
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        cq = [c for c in contribs if c.name == "clinical_quality_91_180"]
        assert len(cq) == 1
        assert cq[0].delta == 0.0

    def test_missing_composite_zero_contribution(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="clinical_quality",
            binary_91_180_clinical_quality_weight=1.0,
        )
        fields = {
            "catalyst_bucket": "less_binary",
            "catalyst_family": "CLINICAL",
            "clinical_quality_composite": "",
            "binary_quality_score": "0",
        }
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        cq = [c for c in contribs if c.name == "clinical_quality_91_180"]
        assert len(cq) == 1
        assert cq[0].delta == 0.0

    def test_zero_weight_zero_contribution(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="clinical_quality",
            binary_91_180_clinical_quality_weight=0.0,
        )
        fields = {
            "catalyst_bucket": "less_binary",
            "catalyst_family": "CLINICAL",
            "clinical_quality_composite": "0.80",
            "binary_quality_score": "0",
        }
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        cq = [c for c in contribs if c.name == "clinical_quality_91_180"]
        assert len(cq) == 1
        assert cq[0].delta == 0.0

    def test_sort_contrib_keys_includes_clinical_quality(self):
        assert "clinical_quality_91_180" in SORT_CONTRIB_KEYS


# ---------------------------------------------------------------------------
# 7. Options quality DE contribution (REGULATORY family, options_quality mode)
# ---------------------------------------------------------------------------


class TestOptionsQualityDEContribution:
    def _make_fields(self, bucket="less_binary", family="REGULATORY", composite="0.70"):
        return {
            "catalyst_bucket": bucket,
            "catalyst_family": family,
            "options_quality_composite": composite,
            "binary_quality_score": "0.5",
            "catalyst_mode": "specific_days",
            "catalyst_days": "120",
            "stage_bucket": "mid",
            "clinical_score_z_tier": "0",
            "inst_delta_z": "0",
            "clinical_score_v2_z": "0",
            "alpha_cohort_pct": "0",
        }

    def test_options_quality_contribution_regulatory(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="options_quality",
            binary_91_180_options_quality_weight=1.0,
        )
        fields = self._make_fields()
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "options_quality_91_180" in names
        oq = [c for c in contribs if c.name == "options_quality_91_180"][0]
        assert oq.delta == pytest.approx(0.70)

    def test_options_quality_contribution_clinical_ignored(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="options_quality",
            binary_91_180_options_quality_weight=1.0,
        )
        fields = self._make_fields(family="CLINICAL")
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "options_quality_91_180" not in names

    def test_options_quality_contribution_wrong_bucket(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="options_quality",
            binary_91_180_options_quality_weight=1.0,
        )
        fields = self._make_fields(bucket="binary_0_30")
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "options_quality_91_180" not in names

    def test_options_quality_contribution_baseline_mode(self):
        rs = DecisionRuleset(binary_91_180_sort_mode="baseline")
        fields = self._make_fields()
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "options_quality_91_180" not in names

    def test_options_quality_weight_scales(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="options_quality",
            binary_91_180_options_quality_weight=0.5,
        )
        fields = self._make_fields(composite="0.80")
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        oq = [c for c in contribs if c.name == "options_quality_91_180"][0]
        assert oq.delta == pytest.approx(0.40)

    def test_sort_contrib_keys_includes_options_quality(self):
        assert "options_quality_91_180" in SORT_CONTRIB_KEYS


# ---------------------------------------------------------------------------
# 8. Combined clinical_plus_options mode
# ---------------------------------------------------------------------------


class TestClinicalPlusOptionsMode:
    """Verify that clinical_plus_options fires CLINICAL quality for CLINICAL
    family AND options quality for REGULATORY family simultaneously."""

    def test_clinical_fires_in_combined_mode(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="clinical_plus_options",
            binary_91_180_clinical_quality_weight=0.5,
            binary_91_180_options_quality_weight=0.5,
        )
        fields = {
            "catalyst_bucket": "less_binary",
            "catalyst_family": "CLINICAL",
            "clinical_quality_composite": "0.80",
            "options_quality_composite": "0.70",
            "binary_quality_score": "0.5",
            "catalyst_mode": "specific_days",
            "catalyst_days": "120",
            "stage_bucket": "mid",
            "clinical_score_z_tier": "0",
            "inst_delta_z": "0",
            "clinical_score_v2_z": "0",
            "alpha_cohort_pct": "0",
        }
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "clinical_quality_91_180" in names
        assert "options_quality_91_180" not in names  # CLINICAL family → no options contrib

    def test_regulatory_fires_in_combined_mode(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="clinical_plus_options",
            binary_91_180_clinical_quality_weight=0.5,
            binary_91_180_options_quality_weight=0.5,
        )
        fields = {
            "catalyst_bucket": "less_binary",
            "catalyst_family": "REGULATORY",
            "clinical_quality_composite": "0.80",
            "options_quality_composite": "0.70",
            "binary_quality_score": "0.5",
            "catalyst_mode": "specific_days",
            "catalyst_days": "120",
            "stage_bucket": "mid",
            "clinical_score_z_tier": "0",
            "inst_delta_z": "0",
            "clinical_score_v2_z": "0",
            "alpha_cohort_pct": "0",
        }
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "options_quality_91_180" in names
        assert "clinical_quality_91_180" not in names  # REGULATORY family → no clinical contrib
        oq = [c for c in contribs if c.name == "options_quality_91_180"][0]
        assert oq.delta == pytest.approx(0.35)  # 0.5 * 0.70

    def test_combined_mode_wrong_bucket_no_fire(self):
        rs = DecisionRuleset(
            binary_91_180_sort_mode="clinical_plus_options",
            binary_91_180_clinical_quality_weight=0.5,
            binary_91_180_options_quality_weight=0.5,
        )
        fields = {
            "catalyst_bucket": "build_window",
            "catalyst_family": "CLINICAL",
            "clinical_quality_composite": "0.80",
            "options_quality_composite": "0.70",
            "binary_quality_score": "0.5",
            "catalyst_mode": "specific_days",
            "catalyst_days": "60",
            "stage_bucket": "mid",
            "clinical_score_z_tier": "0",
            "inst_delta_z": "0",
            "clinical_score_v2_z": "0",
            "alpha_cohort_pct": "0",
        }
        contribs = _build_sort_contributions(fields, rs, alpha_raw=0.0, catalyst_bonus=0.0)
        names = [c.name for c in contribs]
        assert "clinical_quality_91_180" not in names
        assert "options_quality_91_180" not in names
