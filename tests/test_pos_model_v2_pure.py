"""Unit tests for pure math functions in pos_model_v2.py.

Covers: enhanced_stage_score, pos_to_catalyst_ev_weight.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pos_model_v2 import enhanced_stage_score, pos_to_catalyst_ev_weight

# =============================================================================
# enhanced_stage_score
# =============================================================================


class TestEnhancedStageScore:
    def test_median_pos_unchanged(self):
        """PoS == median → multiplier=1 → score unchanged."""
        result = enhanced_stage_score(Decimal("50"), Decimal("0.50"))
        assert result == Decimal("50")

    def test_above_median_boosts(self):
        """PoS > median → multiplier > 1 → score increases."""
        result = enhanced_stage_score(Decimal("50"), Decimal("0.75"))
        assert result > Decimal("50")

    def test_below_median_penalizes(self):
        """PoS < median → multiplier < 1 → score decreases."""
        result = enhanced_stage_score(Decimal("50"), Decimal("0.25"))
        assert result < Decimal("50")

    def test_zero_pos_zero_score(self):
        """PoS=0 → multiplier=0 → score=0 (clamped floor)."""
        result = enhanced_stage_score(Decimal("80"), Decimal("0"))
        assert result == Decimal("0")

    def test_clamped_at_100(self):
        """Very high PoS relative to median → capped at 100."""
        result = enhanced_stage_score(Decimal("80"), Decimal("1.0"), Decimal("0.25"))
        assert result == Decimal("100")

    def test_clamped_at_0(self):
        """Score cannot go below 0."""
        result = enhanced_stage_score(Decimal("0"), Decimal("0.10"))
        assert result == Decimal("0")

    def test_custom_median(self):
        """Custom median_pos shifts the comparison point."""
        # PoS=0.30 with median=0.30 → no change
        result = enhanced_stage_score(Decimal("60"), Decimal("0.30"), Decimal("0.30"))
        assert result == Decimal("60")

    def test_high_base_score_high_pos(self):
        """High base + high PoS → capped at 100."""
        result = enhanced_stage_score(Decimal("90"), Decimal("0.80"), Decimal("0.50"))
        assert result == Decimal("100")


# =============================================================================
# pos_to_catalyst_ev_weight
# =============================================================================


class TestPosToCatalystEvWeight:
    def test_pos_1_full_ev(self):
        """PoS=1.0 → EV_adjusted = base_EV."""
        result = pos_to_catalyst_ev_weight(Decimal("1.0"), Decimal("100"))
        assert result == Decimal("100")

    def test_pos_0_minimum_ev(self):
        """PoS=0.0 → EV_adjusted = base_EV * 0.30 (with default blend=0.70)."""
        result = pos_to_catalyst_ev_weight(Decimal("0"), Decimal("100"))
        assert result == Decimal("30")

    def test_pos_half_blended(self):
        """PoS=0.5 → EV_adjusted = base_EV * 0.65."""
        result = pos_to_catalyst_ev_weight(Decimal("0.5"), Decimal("100"))
        assert result == Decimal("65")

    def test_custom_blend_factor(self):
        """Non-default blend_factor changes the weight."""
        # blend=1.0: floor=0%, PoS=0.5 → 50%
        result = pos_to_catalyst_ev_weight(Decimal("0.5"), Decimal("100"), Decimal("1.0"))
        assert result == Decimal("50")

    def test_blend_zero_no_pos_effect(self):
        """blend=0 → PoS has no effect, always full EV."""
        result = pos_to_catalyst_ev_weight(Decimal("0"), Decimal("100"), Decimal("0"))
        assert result == Decimal("100")

    def test_returns_decimal(self):
        """Result is always a Decimal."""
        result = pos_to_catalyst_ev_weight(Decimal("0.3"), Decimal("50"))
        assert isinstance(result, Decimal)

    def test_monotonically_increasing_with_pos(self):
        """Higher PoS → higher EV weight."""
        ev_low = pos_to_catalyst_ev_weight(Decimal("0.2"), Decimal("100"))
        ev_mid = pos_to_catalyst_ev_weight(Decimal("0.5"), Decimal("100"))
        ev_high = pos_to_catalyst_ev_weight(Decimal("0.8"), Decimal("100"))
        assert ev_low < ev_mid < ev_high
