"""Tests for common/options_construction_overlay.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.options_construction_overlay import MULT_CEILING, MULT_FLOOR, compute_31_90_weight_multiplier


def _row(**kwargs):
    defaults = {
        "options_quality_composite": "",
        "vol_classification": "",
        "market_model_disagreement": "",
        "opt_iv_regime": "",
        "opt_liquidity_state": "liquid",
        "catalyst_days": "60",
    }
    defaults.update(kwargs)
    return defaults


class TestCompute3190WeightMultiplier:
    def test_boost_oqc_cheap_vol(self):
        r = _row(options_quality_composite="0.5", opt_iv_regime="NORMAL", vol_classification="CHEAP")
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] >= 1.20
        assert result["overlay_applied"]

    def test_boost_oqc_agree(self):
        r = _row(options_quality_composite="0.5", market_model_disagreement="low")
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] == 1.10

    def test_compound_boosts(self):
        r = _row(
            options_quality_composite="0.5",
            opt_iv_regime="NORMAL",
            vol_classification="CHEAP",
            market_model_disagreement="low",
        )
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        # 1.20 * 1.10 = 1.32, within ceiling
        assert abs(result["weight_multiplier"] - 1.32) < 0.01

    def test_cap_rich_vol_near(self):
        r = _row(vol_classification="RICH", catalyst_days="60")
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] == 0.80

    def test_cap_high_disagree_near(self):
        r = _row(market_model_disagreement="high", catalyst_days="60")
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] == 0.75

    def test_cap_compound_floor(self):
        r = _row(vol_classification="RICH", market_model_disagreement="high", catalyst_days="50")
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        # 0.80 * 0.75 = 0.60 = floor
        assert result["weight_multiplier"] == MULT_FLOOR

    def test_ceiling_enforced(self):
        r = _row(
            options_quality_composite="0.9",
            opt_iv_regime="NORMAL",
            vol_classification="CHEAP",
            market_model_disagreement="low",
        )
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] <= MULT_CEILING

    def test_stale_suppresses(self):
        r = _row(options_quality_composite="0.5", vol_classification="CHEAP")
        result = compute_31_90_weight_multiplier(r, options_fresh=False)
        assert result["weight_multiplier"] == 1.0
        assert not result["overlay_applied"]

    def test_no_flags_no_adjustment(self):
        r = _row()
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] == 1.0
        assert not result["overlay_applied"]

    def test_rich_far_catalyst_no_cap(self):
        """RICH vol but catalyst_days > 75 → no cap."""
        r = _row(vol_classification="RICH", catalyst_days="80")
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] == 1.0

    def test_absent_chain_suppressed(self):
        r = _row(opt_liquidity_state="absent", options_quality_composite="0.5")
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] == 1.0
        assert not result["overlay_applied"]

    def test_thin_chain_no_boost(self):
        """Thin chains should not get boosts even with good signals."""
        r = _row(
            opt_liquidity_state="thin",
            options_quality_composite="0.5",
            opt_iv_regime="NORMAL",
            vol_classification="CHEAP",
        )
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] <= 1.0  # no boost

    def test_thin_chain_penalty_applies(self):
        """Thin chains still get penalties."""
        r = _row(opt_liquidity_state="thin", vol_classification="RICH", catalyst_days="50")
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] == 0.80

    def test_extreme_iv_thin_chain_penalty(self):
        r = _row(opt_liquidity_state="thin", opt_iv_regime="EXTREME", catalyst_days="50")
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] <= 0.70
        assert result["overlay_applied"]

    def test_extreme_iv_thin_stale_still_penalizes(self):
        """EXTREME IV + thin chain penalizes even when data is stale."""
        r = _row(opt_liquidity_state="thin", opt_iv_regime="EXTREME")
        result = compute_31_90_weight_multiplier(r, options_fresh=False)
        assert result["weight_multiplier"] == 0.70
        assert result["overlay_applied"]

    def test_implied_pctile_fallback_for_vol_class(self):
        """When vol_classification is absent, use actual_implied_move_pctile."""
        r = _row(actual_implied_move_pctile="0.90", catalyst_days="50")
        result = compute_31_90_weight_multiplier(r, options_fresh=True)
        assert result["weight_multiplier"] == 0.80  # rich fallback
