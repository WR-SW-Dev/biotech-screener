"""Tests for common/options_risk_controls.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.options_risk_controls import compute_0_30_risk_controls, compute_rv_30d


def _row(**kwargs):
    defaults = {
        "catalyst_days": "15",
        "catalyst_family": "REGULATORY",
        "opt_atm_iv": "0.50",
        "opt_liquidity_state": "liquid",
        "pos_divergence": "0.3",
        "options_volume_ratio": "",
        "near_term_volume_share": "",
    }
    defaults.update(kwargs)
    return defaults


class TestComputeRv30d:
    def test_sufficient_data(self):
        # 25 trading days of stable prices
        prices = {f"2026-03-{d:02d}": 100.0 + d * 0.1 for d in range(1, 26)}
        rv = compute_rv_30d(prices, "2026-03-25")
        assert rv is not None
        assert rv > 0

    def test_insufficient_data(self):
        prices = {"2026-03-01": 100.0, "2026-03-02": 101.0}
        rv = compute_rv_30d(prices, "2026-03-02")
        assert rv is None


class TestCrowdingControl:
    def test_crowding_fires(self):
        r = _row(catalyst_days="15", options_volume_ratio="3.0", near_term_volume_share="0.70")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=True, crowding_panel_populated=True)
        assert result["crowding_flag"] is True
        assert result["hard_cap_multiplier"] == 0.75

    def test_crowding_dormant_no_panel(self):
        r = _row(catalyst_days="15", options_volume_ratio="3.0", near_term_volume_share="0.70")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=True, crowding_panel_populated=False)
        assert result["crowding_flag"] is False

    def test_crowding_not_near_term(self):
        r = _row(catalyst_days="25", options_volume_ratio="3.0", near_term_volume_share="0.70")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=True, crowding_panel_populated=True)
        assert result["crowding_flag"] is False


class TestComplacencyControl:
    def test_complacency_fires(self):
        # IV/RV = 0.40/0.50 = 0.80 < 1.15
        r = _row(catalyst_days="15", catalyst_family="REGULATORY", opt_atm_iv="0.40")
        result = compute_0_30_risk_controls(r, rv_30d=0.50, options_fresh=True)
        assert result["complacency_flag"] is True
        assert result["review_required"] is True

    def test_complacency_not_regulatory(self):
        r = _row(catalyst_days="15", catalyst_family="CLINICAL", opt_atm_iv="0.40")
        result = compute_0_30_risk_controls(r, rv_30d=0.50, options_fresh=True)
        assert result["complacency_flag"] is False

    def test_complacency_elevated_iv(self):
        # IV/RV = 0.80/0.50 = 1.60 > 1.15 → no complacency
        r = _row(catalyst_days="15", catalyst_family="REGULATORY", opt_atm_iv="0.80")
        result = compute_0_30_risk_controls(r, rv_30d=0.50, options_fresh=True)
        assert result["complacency_flag"] is False

    def test_complacency_missing_rv(self):
        r = _row(catalyst_days="15", catalyst_family="REGULATORY", opt_atm_iv="0.40")
        result = compute_0_30_risk_controls(r, rv_30d=None, options_fresh=True)
        assert result["complacency_flag"] is False


class TestGapRiskControl:
    def test_gap_risk_fires(self):
        r = _row(catalyst_days="10", pos_divergence="1.5")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=True)
        assert result["gap_risk_cap_reduction"] == 0.25
        assert result["hard_cap_multiplier"] == 0.75

    def test_gap_risk_low_divergence(self):
        r = _row(catalyst_days="10", pos_divergence="0.5")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=True)
        assert result["gap_risk_cap_reduction"] == 0.0

    def test_gap_risk_not_near_enough(self):
        r = _row(catalyst_days="20", pos_divergence="1.5")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=True)
        assert result["gap_risk_cap_reduction"] == 0.0


class TestCheapSurfaceControl:
    def test_cheap_surface_fires(self):
        r = _row(catalyst_days="15", actual_implied_move_pctile="0.10")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=True)
        assert result["cheap_surface_flag"] is True
        assert result["review_required"] is True

    def test_cheap_surface_not_on_thin(self):
        r = _row(catalyst_days="15", actual_implied_move_pctile="0.10", opt_liquidity_state="thin")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=True)
        assert result["cheap_surface_flag"] is False

    def test_cheap_surface_not_far(self):
        """Cheap surface only fires within 30d."""
        r = _row(catalyst_days="45", actual_implied_move_pctile="0.10")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=True)
        assert result["cheap_surface_flag"] is False


class TestLiquidityStateGating:
    def test_absent_suppresses_all(self):
        r = _row(opt_liquidity_state="absent", catalyst_days="10", pos_divergence="2.0")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=True)
        assert result["hard_cap_multiplier"] == 1.0
        assert "absent_options_data" in result["control_reasons"]

    def test_extreme_iv_thin_stale_penalizes(self):
        r = _row(opt_liquidity_state="thin", opt_iv_regime="EXTREME")
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=False)
        assert result["hard_cap_multiplier"] == 0.75


class TestStaleDataSuppression:
    def test_all_suppressed_when_stale(self):
        r = _row(
            catalyst_days="10",
            pos_divergence="2.0",
            options_volume_ratio="5.0",
            near_term_volume_share="0.80",
            opt_atm_iv="0.30",
            catalyst_family="REGULATORY",
        )
        result = compute_0_30_risk_controls(r, rv_30d=0.5, options_fresh=False, crowding_panel_populated=True)
        assert result["crowding_flag"] is False
        assert result["complacency_flag"] is False
        assert result["gap_risk_cap_reduction"] == 0.0
        assert result["hard_cap_multiplier"] == 1.0
