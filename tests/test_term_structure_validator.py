"""Tests for common/term_structure_validator.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.term_structure_validator import (
    detect_blind_spot_candidate,
    detect_catalyst_date_mismatch,
    validate_term_structure,
)


class TestDetectCatalystDateMismatch:
    def test_market_sees_sooner(self):
        """Front IV elevated but model says catalyst > 90d."""
        result = detect_catalyst_date_mismatch(catalyst_days=120, opt_term_slope=-0.25, opt_atm_iv=1.5, baseline_iv=0.6)
        assert result["flag"] is True
        assert result["flag_type"] == "MARKET_SEES_SOONER"
        assert result["requires_review"] is True

    def test_no_flag_near_catalyst(self):
        """Front elevated but catalyst within 90d — expected, no flag."""
        result = detect_catalyst_date_mismatch(catalyst_days=30, opt_term_slope=-0.25, opt_atm_iv=1.5, baseline_iv=0.6)
        assert result["flag"] is False

    def test_market_not_pricing_event(self):
        """Flat term structure + near catalyst + low IV = stale date."""
        result = detect_catalyst_date_mismatch(catalyst_days=20, opt_term_slope=0.05, opt_atm_iv=0.5, baseline_iv=0.6)
        assert result["flag"] is True
        assert result["flag_type"] == "MARKET_NOT_PRICING_EVENT"

    def test_no_flag_elevated_iv_near(self):
        """Near catalyst + elevated IV = market IS pricing it."""
        result = detect_catalyst_date_mismatch(catalyst_days=20, opt_term_slope=0.05, opt_atm_iv=1.0, baseline_iv=0.6)
        assert result["flag"] is False

    def test_no_flag_neutral(self):
        """Neutral term structure, mid-range catalyst."""
        result = detect_catalyst_date_mismatch(catalyst_days=60, opt_term_slope=-0.05, opt_atm_iv=0.8, baseline_iv=0.6)
        assert result["flag"] is False

    def test_missing_slope(self):
        result = detect_catalyst_date_mismatch(catalyst_days=120, opt_term_slope=None, opt_atm_iv=1.0, baseline_iv=0.6)
        assert result["flag"] is False

    def test_nan_slope(self):
        result = detect_catalyst_date_mismatch(
            catalyst_days=120, opt_term_slope=float("nan"), opt_atm_iv=1.0, baseline_iv=0.6
        )
        assert result["flag"] is False

    def test_no_catalyst(self):
        result = detect_catalyst_date_mismatch(
            catalyst_days=None, opt_term_slope=-0.25, opt_atm_iv=1.0, baseline_iv=0.6
        )
        assert result["flag"] is False


class TestDetectBlindSpotCandidate:
    def test_blind_spot_fires(self):
        """No catalyst + strong backwardation + elevated IV."""
        result = detect_blind_spot_candidate(
            catalyst_days=None,
            catalyst_mode="no_upcoming",
            opt_term_slope=-0.20,
            opt_atm_iv=1.2,
            baseline_iv=0.6,
        )
        assert result["flag"] is True
        assert result["flag_type"] == "BLIND_SPOT"

    def test_no_flag_has_catalyst(self):
        """Has a catalyst — blind spot doesn't apply."""
        result = detect_blind_spot_candidate(
            catalyst_days=45,
            catalyst_mode="specific_days",
            opt_term_slope=-0.20,
            opt_atm_iv=1.2,
            baseline_iv=0.6,
        )
        assert result["flag"] is False

    def test_no_flag_flat_slope(self):
        """No backwardation — no blind spot."""
        result = detect_blind_spot_candidate(
            catalyst_days=None,
            catalyst_mode="missing",
            opt_term_slope=0.05,
            opt_atm_iv=1.2,
            baseline_iv=0.6,
        )
        assert result["flag"] is False

    def test_no_flag_low_iv(self):
        """Backwardation but IV not elevated enough."""
        result = detect_blind_spot_candidate(
            catalyst_days=None,
            catalyst_mode="no_upcoming",
            opt_term_slope=-0.20,
            opt_atm_iv=0.7,
            baseline_iv=0.6,
        )
        assert result["flag"] is False

    def test_missing_baseline(self):
        result = detect_blind_spot_candidate(
            catalyst_days=None,
            catalyst_mode="missing",
            opt_term_slope=-0.20,
            opt_atm_iv=1.2,
            baseline_iv=None,
        )
        assert result["flag"] is False

    def test_far_window_treated_as_no_catalyst(self):
        """far_window mode should NOT trigger blind spot (has a PCD)."""
        result = detect_blind_spot_candidate(
            catalyst_days=300,
            catalyst_mode="far_window",
            opt_term_slope=-0.20,
            opt_atm_iv=1.2,
            baseline_iv=0.6,
        )
        assert result["flag"] is False


class TestValidateTermStructure:
    def test_mismatch_takes_priority(self):
        """If both could fire, mismatch wins."""
        result = validate_term_structure(
            catalyst_days=120,
            catalyst_mode="specific_days",
            opt_term_slope=-0.25,
            opt_atm_iv=1.5,
            baseline_iv=0.6,
        )
        assert result["flag_type"] == "MARKET_SEES_SOONER"

    def test_blind_spot_when_no_catalyst(self):
        result = validate_term_structure(
            catalyst_days=None,
            catalyst_mode="no_upcoming",
            opt_term_slope=-0.20,
            opt_atm_iv=1.2,
            baseline_iv=0.6,
        )
        assert result["flag_type"] == "BLIND_SPOT"

    def test_no_flag_clean(self):
        result = validate_term_structure(
            catalyst_days=60,
            catalyst_mode="specific_days",
            opt_term_slope=-0.05,
            opt_atm_iv=0.8,
            baseline_iv=0.6,
        )
        assert result["flag"] is False
        assert result["flag_type"] == ""
