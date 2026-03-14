"""Tests for common/pos_divergence.py."""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.pos_divergence import (
    compute_implied_event_move,
    compute_iv_premium_ratio,
    compute_pos_divergence_panel,
    z_score_array,
)


class TestComputeImpliedEventMove:
    def test_normal_case(self):
        # 80% IV, 30 days out → 0.80 × sqrt(30/365) ≈ 0.229
        result = compute_implied_event_move(0.80, 30)
        assert abs(result - 0.229) < 0.01

    def test_high_iv_near_catalyst(self):
        # 200% IV, 7 days → 0.277
        result = compute_implied_event_move(2.0, 7)
        assert abs(result - 2.0 * math.sqrt(7 / 365)) < 0.001

    def test_zero_iv(self):
        assert math.isnan(compute_implied_event_move(0.0, 30))

    def test_negative_days(self):
        assert math.isnan(compute_implied_event_move(0.80, -5))

    def test_nan_iv(self):
        assert math.isnan(compute_implied_event_move(float("nan"), 30))


class TestComputeIvPremiumRatio:
    def test_elevated(self):
        assert compute_iv_premium_ratio(1.0, 0.4) == 2.5

    def test_compressed(self):
        assert compute_iv_premium_ratio(0.5, 0.5) == 1.0

    def test_zero_rv(self):
        assert math.isnan(compute_iv_premium_ratio(0.8, 0.0))

    def test_nan(self):
        assert math.isnan(compute_iv_premium_ratio(float("nan"), 0.5))


class TestZScoreArray:
    def test_basic(self):
        result = z_score_array([1.0, 2.0, 3.0])
        # Mean=2, std≈0.816
        assert len(result) == 3
        assert abs(result[0] + result[2]) < 1e-10  # symmetric
        assert abs(result[1]) < 1e-10  # middle = 0

    def test_with_nan(self):
        result = z_score_array([1.0, float("nan"), 3.0])
        assert len(result) == 3
        assert not math.isnan(result[0])
        assert math.isnan(result[1])
        assert not math.isnan(result[2])

    def test_all_nan(self):
        result = z_score_array([float("nan"), float("nan")])
        assert all(math.isnan(v) for v in result)

    def test_constant(self):
        result = z_score_array([5.0, 5.0, 5.0])
        assert all(v == 0.0 for v in result)


class TestComputePosDivergencePanel:
    def test_basic_panel(self):
        rows = [
            {"ticker": "A", "opt_atm_iv": 0.80, "catalyst_days": 30, "composite_score": 60.0},
            {"ticker": "B", "opt_atm_iv": 1.50, "catalyst_days": 30, "composite_score": 40.0},
            {"ticker": "C", "opt_atm_iv": 0.50, "catalyst_days": 30, "composite_score": 50.0},
        ]
        result = compute_pos_divergence_panel(rows)
        assert len(result) == 3
        for r in result:
            assert "pos_divergence" in r
            assert "pos_divergence_z" in r
            assert "implied_event_move" in r
            assert not math.isnan(r["pos_divergence"])

    def test_divergence_direction(self):
        """High model score + low IV → positive divergence (model more bullish)."""
        rows = [
            {"ticker": "HIGH_MODEL", "opt_atm_iv": 0.30, "catalyst_days": 30, "composite_score": 80.0},
            {"ticker": "LOW_MODEL", "opt_atm_iv": 1.50, "catalyst_days": 30, "composite_score": 20.0},
        ]
        result = compute_pos_divergence_panel(rows)
        # HIGH_MODEL: high model_z, low implied_z → positive divergence
        # LOW_MODEL: low model_z, high implied_z → negative divergence
        assert result[0]["pos_divergence"] > result[1]["pos_divergence"]

    def test_missing_data(self):
        rows = [
            {"ticker": "A", "opt_atm_iv": "", "catalyst_days": 30, "composite_score": 50.0},
            {"ticker": "B", "opt_atm_iv": 0.80, "catalyst_days": 30, "composite_score": 50.0},
        ]
        result = compute_pos_divergence_panel(rows)
        assert math.isnan(result[0]["pos_divergence"])

    def test_empty_panel(self):
        assert compute_pos_divergence_panel([]) == []

    def test_custom_signal_col(self):
        rows = [
            {"ticker": "A", "opt_atm_iv": 0.80, "catalyst_days": 30, "my_signal": 70.0},
            {"ticker": "B", "opt_atm_iv": 0.80, "catalyst_days": 30, "my_signal": 30.0},
        ]
        result = compute_pos_divergence_panel(rows, model_signal_col="my_signal")
        assert not math.isnan(result[0]["pos_divergence"])
