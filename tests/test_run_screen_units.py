"""Unit tests for pure/utility functions in run_screen.py.

Covers: classify_company_archetype, apply_clinical_activity_filter,
parse_catalyst_window, compute_catalyst_decay_weight, _parse_trial_date,
_clinical_proximity, _filter_price_outliers, _validate_price_splits,
_force_deterministic_generated_at, validate_as_of_date_param,
z-score computation helpers, and coverage guard logic.
"""

from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from run_screen import (
    _clinical_proximity,
    _filter_price_outliers,
    _force_deterministic_generated_at,
    _parse_trial_date,
    _validate_price_splits,
    apply_clinical_activity_filter,
    classify_company_archetype,
    compute_catalyst_decay_weight,
    parse_catalyst_window,
    validate_as_of_date_param,
)

# =============================================================================
# classify_company_archetype
# =============================================================================


class TestClassifyCompanyArchetype:
    def test_biotech_no_revenue_is_drug_developer(self):
        assert classify_company_archetype("ACME", "Biotechnology", False, "pre_revenue") == "drug_developer"

    def test_biotech_medium_revenue_is_commercial(self):
        assert classify_company_archetype("GILD", "Biotechnology", True, "medium") == "commercial_biotech"

    def test_biotech_large_revenue_is_commercial(self):
        assert classify_company_archetype("GILD", "Biotechnology", True, "large") == "commercial_biotech"

    def test_biotech_small_revenue_stays_drug_developer(self):
        assert classify_company_archetype("ACME", "Biotechnology", True, "small") == "drug_developer"

    def test_pharma_specialty(self):
        assert (
            classify_company_archetype("PFE", "Drug Manufacturers - Specialty & Generic", False, "pre_revenue")
            == "commercial_pharma"
        )

    def test_pharma_general(self):
        assert classify_company_archetype("JNJ", "Drug Manufacturers - General", True, "large") == "commercial_pharma"

    def test_diagnostics(self):
        assert classify_company_archetype("ILMN", "Diagnostics & Research", True, "medium") == "platform_diagnostics"

    def test_medical_devices(self):
        assert classify_company_archetype("MDT", "Medical Devices", True, "large") == "platform_devices"

    def test_unknown_industry_defaults_to_drug_developer(self):
        assert classify_company_archetype("XYZ", "Unknown Industry", False, "pre_revenue") == "drug_developer"

    def test_empty_industry_defaults_to_drug_developer(self):
        assert classify_company_archetype("XYZ", "", False, "pre_revenue") == "drug_developer"


# =============================================================================
# apply_clinical_activity_filter
# =============================================================================


class TestApplyClinicalActivityFilter:
    def test_drug_developer_below_min_trials_excluded(self):
        scores = [{"ticker": "ACME", "n_trials_unique": 2, "lead_phase": "phase 2"}]
        excluded, details, exemptions = apply_clinical_activity_filter(scores, min_trials=5)
        assert "ACME" in excluded
        assert len(details) == 1

    def test_drug_developer_below_min_phase_excluded(self):
        scores = [{"ticker": "ACME", "n_trials_unique": 10, "lead_phase": "preclinical"}]
        excluded, details, exemptions = apply_clinical_activity_filter(scores, min_phase="phase1")
        assert "ACME" in excluded

    def test_meeting_both_thresholds_not_excluded(self):
        scores = [{"ticker": "ACME", "n_trials_unique": 10, "lead_phase": "phase 2"}]
        excluded, _, _ = apply_clinical_activity_filter(scores, min_trials=5, min_phase="phase1")
        assert excluded == []

    def test_non_drug_developer_exempt(self):
        scores = [{"ticker": "PFE", "n_trials_unique": 1, "lead_phase": "preclinical"}]
        archetypes = {"PFE": "commercial_pharma"}
        excluded, _, exemptions = apply_clinical_activity_filter(scores, archetypes=archetypes)
        assert excluded == []
        assert len(exemptions) == 1
        assert exemptions[0]["reason"] == "clinical_gate_exempt"

    def test_empty_input(self):
        excluded, details, exemptions = apply_clinical_activity_filter([])
        assert excluded == []


# =============================================================================
# parse_catalyst_window
# =============================================================================


class TestParseCatalystWindow:
    def test_standard_window(self):
        assert parse_catalyst_window("15-45") == (15, 45)

    def test_wide_window(self):
        assert parse_catalyst_window("15-90") == (15, 90)

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid catalyst window format"):
            parse_catalyst_window("")

    def test_no_dash_raises(self):
        with pytest.raises(ValueError):
            parse_catalyst_window("1545")

    def test_negative_values_raises(self):
        with pytest.raises(ValueError):
            parse_catalyst_window("-5-45")

    def test_start_gte_end_raises(self):
        with pytest.raises(ValueError, match="start must be less than end"):
            parse_catalyst_window("45-15")

    def test_end_exceeds_365_raises(self):
        with pytest.raises(ValueError, match="exceeds 365"):
            parse_catalyst_window("15-400")


# =============================================================================
# compute_catalyst_decay_weight
# =============================================================================


class TestComputeCatalystDecayWeight:
    def test_past_event_zero(self):
        assert compute_catalyst_decay_weight(-10, 15, 45, "step") == 0.0

    def test_in_window_full_weight(self):
        assert compute_catalyst_decay_weight(30, 15, 45, "step") == 1.0
        assert compute_catalyst_decay_weight(30, 15, 45, "linear") == 1.0
        assert compute_catalyst_decay_weight(30, 15, 45, "exp") == 1.0

    def test_step_outside_window_zero(self):
        assert compute_catalyst_decay_weight(60, 15, 45, "step") == 0.0
        assert compute_catalyst_decay_weight(5, 15, 45, "step") == 0.0

    def test_linear_before_window(self):
        w = compute_catalyst_decay_weight(7, 15, 45, "linear")
        assert 0.0 < w < 1.0

    def test_linear_beyond_window(self):
        w = compute_catalyst_decay_weight(60, 15, 45, "linear")
        assert 0.0 <= w < 1.0

    def test_exp_beyond_window(self):
        w = compute_catalyst_decay_weight(100, 15, 45, "exp", half_life_days=30)
        assert 0.0 < w < 1.0

    def test_exp_decays_with_distance(self):
        w1 = compute_catalyst_decay_weight(50, 15, 45, "exp", half_life_days=30)
        w2 = compute_catalyst_decay_weight(100, 15, 45, "exp", half_life_days=30)
        assert w1 > w2

    def test_unknown_mode_behaves_like_step(self):
        assert compute_catalyst_decay_weight(30, 15, 45, "unknown") == 1.0
        assert compute_catalyst_decay_weight(60, 15, 45, "unknown") == 0.0

    def test_at_window_boundaries(self):
        assert compute_catalyst_decay_weight(15, 15, 45, "step") == 1.0
        assert compute_catalyst_decay_weight(45, 15, 45, "step") == 1.0


# =============================================================================
# _parse_trial_date
# =============================================================================


class TestParseTrialDate:
    def test_valid_date(self):
        assert _parse_trial_date("2026-03-06") == date(2026, 3, 6)

    def test_date_with_extra_chars(self):
        assert _parse_trial_date("2026-03-06T12:00:00") == date(2026, 3, 6)

    def test_empty_string(self):
        assert _parse_trial_date("") is None

    def test_none(self):
        assert _parse_trial_date(None) is None

    def test_invalid_date(self):
        assert _parse_trial_date("not-a-date") is None


# =============================================================================
# _clinical_proximity
# =============================================================================


class TestClinicalProximity:
    def test_none_days_returns_zero(self):
        assert _clinical_proximity(None) == 0.0

    def test_zero_days_returns_one(self):
        assert _clinical_proximity(0) == 1.0

    def test_negative_days_returns_one(self):
        assert _clinical_proximity(-5) == 1.0

    def test_positive_days_decays(self):
        p90 = _clinical_proximity(90)
        assert abs(p90 - math.exp(-1)) < 1e-10

    def test_monotonically_decreasing(self):
        assert _clinical_proximity(30) > _clinical_proximity(60) > _clinical_proximity(180)


# =============================================================================
# _filter_price_outliers
# =============================================================================


class TestFilterPriceOutliers:
    def test_empty_series(self):
        filtered, warnings = _filter_price_outliers([])
        assert filtered == []
        assert warnings == []

    def test_single_point(self):
        series = [(date(2026, 1, 1), 10.0)]
        filtered, warnings = _filter_price_outliers(series)
        assert filtered == series
        assert warnings == []

    def test_no_outliers(self):
        series = [(date(2026, 1, i), 10.0 + i * 0.1) for i in range(1, 10)]
        filtered, warnings = _filter_price_outliers(series)
        assert len(filtered) == len(series)
        assert warnings == []

    def test_reverse_split_detected(self):
        series = [
            (date(2026, 1, 1), 5.0),
            (date(2026, 1, 2), 5.1),
            (date(2026, 1, 3), 50.0),  # 10x jump = reverse split
            (date(2026, 1, 4), 50.5),
        ]
        filtered, warnings = _filter_price_outliers(series)
        assert len(filtered) == 2  # only post-split retained
        assert filtered[0][1] == 50.0
        assert len(warnings) == 1
        assert warnings[0]["flag"] == "reverse_split"

    def test_forward_split_detected(self):
        series = [
            (date(2026, 1, 1), 100.0),
            (date(2026, 1, 2), 10.0),  # -90% = forward split
            (date(2026, 1, 3), 10.5),
        ]
        filtered, warnings = _filter_price_outliers(series)
        assert len(filtered) == 2
        assert filtered[0][1] == 10.0
        assert warnings[0]["flag"] == "forward_split"


# =============================================================================
# _validate_price_splits
# =============================================================================


class TestValidatePriceSplits:
    def test_no_splits(self):
        prices = {
            "ACME": [(date(2026, 1, i), 10.0 + i * 0.01) for i in range(1, 5)],
        }
        assert _validate_price_splits(prices) == {}

    def test_split_detected(self):
        prices = {
            "ACME": [(date(2026, 1, 1), 5.0), (date(2026, 1, 2), 50.0)],
            "SAFE": [(date(2026, 1, 1), 10.0), (date(2026, 1, 2), 10.1)],
        }
        result = _validate_price_splits(prices)
        assert "ACME" in result
        assert "SAFE" not in result


# =============================================================================
# _force_deterministic_generated_at
# =============================================================================


class TestForceDeterministicGeneratedAt:
    def test_overwrites_provenance(self):
        obj = {"provenance": {"generated_at": "old_time"}, "data": 1}
        _force_deterministic_generated_at(obj, "2026-01-01T00:00:00")
        assert obj["provenance"]["generated_at"] == "2026-01-01T00:00:00"

    def test_nested_provenance(self):
        obj = {
            "results": [
                {"provenance": {"generated_at": "old"}},
                {"provenance": {"generated_at": "old2"}},
            ]
        }
        _force_deterministic_generated_at(obj, "fixed")
        assert obj["results"][0]["provenance"]["generated_at"] == "fixed"
        assert obj["results"][1]["provenance"]["generated_at"] == "fixed"

    def test_no_provenance_noop(self):
        obj = {"data": 1}
        _force_deterministic_generated_at(obj, "time")
        assert obj == {"data": 1}


# =============================================================================
# validate_as_of_date_param
# =============================================================================


class TestValidateAsOfDateParam:
    def test_valid_date(self):
        validate_as_of_date_param("2026-03-06")  # should not raise

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            validate_as_of_date_param("03-06-2026")

    def test_injection_attempt_raises(self):
        with pytest.raises(ValueError):
            validate_as_of_date_param("2026-03-06; rm -rf /")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            validate_as_of_date_param("")


# =============================================================================
# Z-score computation logic (extracted pattern tests)
# =============================================================================


class TestZScoreComputationPatterns:
    """Tests for the z-score computation patterns used in run_screen.py.

    These test the mathematical properties rather than calling the embedded code
    directly, since the z-score blocks are inline in save_validation_snapshot().
    """

    @staticmethod
    def _compute_z_scores(values: list[float], ddof: int = 0) -> list[float]:
        """Replicate the z-score pattern used in run_screen.py."""
        n = len(values)
        if n == 0:
            return []
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / n
        std = var**0.5
        if std == 0:
            return [0.0] * n
        return [round((v - mean) / std, 4) for v in values]

    def test_z_scores_sum_to_zero(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        zs = self._compute_z_scores(values)
        assert abs(sum(zs)) < 1e-3

    def test_z_scores_unit_variance(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        zs = self._compute_z_scores(values)
        var = sum(z**2 for z in zs) / len(zs)
        assert abs(var - 1.0) < 0.01

    def test_constant_values_all_zero(self):
        values = [5.0, 5.0, 5.0]
        zs = self._compute_z_scores(values)
        assert all(z == 0.0 for z in zs)

    def test_single_value_zero(self):
        zs = self._compute_z_scores([42.0])
        assert zs == [0.0]

    def test_empty_list(self):
        assert self._compute_z_scores([]) == []

    def test_ddof0_population_std(self):
        values = [2.0, 4.0]
        zs = self._compute_z_scores(values, ddof=0)
        assert zs[0] == -zs[1]  # symmetric around mean


# =============================================================================
# Coverage guard logic (pattern test)
# =============================================================================


class TestCoverageGuardPattern:
    """Tests for the coverage guard pattern used in run_screen.py."""

    @staticmethod
    def _apply_coverage_guard(
        rows: list[dict],
        min_pct: float = 10.0,
    ) -> tuple[float, bool]:
        """Replicate the coverage guard logic from run_screen.py."""
        nonzero_count = sum(1 for r in rows if r.get("inst_delta_net", 0) != 0)
        nonzero_pct = round(100.0 * nonzero_count / len(rows), 2) if rows else 0.0
        guard_triggered = nonzero_pct < min_pct
        if guard_triggered:
            for r in rows:
                r["inst_delta_z"] = 0.0
        return nonzero_pct, guard_triggered

    def test_guard_triggers_below_threshold(self):
        rows = [{"inst_delta_net": 0, "inst_delta_z": 1.5}] * 95
        rows += [{"inst_delta_net": 3, "inst_delta_z": 2.0}] * 5  # 5% nonzero
        pct, triggered = self._apply_coverage_guard(rows, min_pct=10.0)
        assert triggered
        assert pct == 5.0
        assert all(r["inst_delta_z"] == 0.0 for r in rows)

    def test_guard_does_not_trigger_above_threshold(self):
        rows = [{"inst_delta_net": 0, "inst_delta_z": 0.0}] * 80
        rows += [{"inst_delta_net": 5, "inst_delta_z": 2.0}] * 20  # 20% nonzero
        pct, triggered = self._apply_coverage_guard(rows, min_pct=10.0)
        assert not triggered
        assert pct == 20.0
        # z-scores preserved
        assert rows[-1]["inst_delta_z"] == 2.0

    def test_guard_at_exact_threshold(self):
        rows = [{"inst_delta_net": 0, "inst_delta_z": 0.5}] * 90
        rows += [{"inst_delta_net": 1, "inst_delta_z": 1.0}] * 10  # exactly 10%
        _, triggered = self._apply_coverage_guard(rows, min_pct=10.0)
        assert not triggered  # at threshold = passes

    def test_guard_with_empty_rows(self):
        pct, triggered = self._apply_coverage_guard([], min_pct=10.0)
        assert pct == 0.0
        assert triggered

    def test_guard_all_nonzero(self):
        rows = [{"inst_delta_net": i + 1, "inst_delta_z": 0.5} for i in range(100)]
        pct, triggered = self._apply_coverage_guard(rows, min_pct=10.0)
        assert pct == 100.0
        assert not triggered


# =============================================================================
# SNAPSHOT_COLUMNS integrity
# =============================================================================


class TestSnapshotColumnsIntegrity:
    def test_no_duplicate_columns(self):
        from run_screen import SNAPSHOT_COLUMNS

        seen = set()
        for col in SNAPSHOT_COLUMNS:
            assert col not in seen, f"Duplicate column: {col}"
            seen.add(col)

    def test_required_columns_present(self):
        from run_screen import SNAPSHOT_COLUMNS

        required = [
            "ticker",
            "actionable_rank",
            "tier_any",
            "tier_dev",
            "eligible",
            "inst_delta_z",
            "inst_delta_nonzero_pct",
            "clinical_score_z",
            "clinical_score_z_tier",
            "clinical_score_v2_z",
            "archetype",
        ]
        for col in required:
            assert col in SNAPSHOT_COLUMNS, f"Missing required column: {col}"

    def test_all_columns_are_strings(self):
        from run_screen import SNAPSHOT_COLUMNS

        for col in SNAPSHOT_COLUMNS:
            assert isinstance(col, str), f"Non-string column: {col}"


class TestSnapshotPhaseHelpers:
    """Tests for the extracted save_validation_snapshot phase helpers."""

    def test_enrich_market_data_fields(self):
        from run_screen import _enrich_market_data_fields

        rows = [{"ticker": "ACME"}]
        market = {"ACME": {"short_percent": 0.15, "price": 50.0, "market_cap": 5e9}}
        _enrich_market_data_fields(rows, market)
        assert rows[0]["short_interest_pct"] == 0.15
        assert rows[0]["close_price"] == 50.0
        assert rows[0]["market_cap_mm"] == 5000.0

    def test_enrich_market_data_none_safe(self):
        from run_screen import _enrich_market_data_fields

        rows = [{"ticker": "ACME"}]
        _enrich_market_data_fields(rows, None)  # should not crash

    def test_enrich_applicability_flags(self):
        from run_screen import _enrich_applicability_flags

        rows = [
            {"ticker": "A", "archetype": "drug_developer"},
            {"ticker": "B", "archetype": "commercial"},
        ]
        _enrich_applicability_flags(rows)
        assert rows[0]["has_clinical_optionality_dev"] == 1
        assert rows[0]["has_commercial_quality"] == 0
        assert rows[1]["has_clinical_optionality_dev"] == 0
        assert rows[1]["has_commercial_quality"] == 1

    def test_finalize_priced_move(self):
        """priced_move_pct is now percentage points (straddle × 100) to match
        EES base-rate tables and conditional model units."""
        from run_screen import _finalize_priced_move

        rows = [
            {"ticker": "A", "straddle_price": "0.25", "priced_move_pct": ""},
            {"ticker": "B", "straddle_price": "0.30", "priced_move_pct": "0.30"},
            {"ticker": "C", "straddle_price": "", "priced_move_pct": ""},
        ]
        _finalize_priced_move(rows)
        assert rows[0]["priced_move_pct"] == 25.0  # straddle 0.25 → 25.0 pct pts
        assert rows[1]["priced_move_pct"] == "0.30"  # preserved existing (not overwritten)
        assert rows[2]["priced_move_pct"] == ""  # no straddle, stays empty
