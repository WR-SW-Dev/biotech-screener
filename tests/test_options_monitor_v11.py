"""Tests for Options Monitor v1.1 — orthogonal factor features."""

from decimal import Decimal

import pytest

from common.options_monitor_v11_features import (
    CATALYST_WEIGHTS,
    classify_monitor_verdict,
    compute_chain_quality,
    compute_composite,
    compute_confidence,
    compute_factor_dv,
    compute_factor_ep,
    compute_factor_sk,
    compute_factor_sr,
    compute_v11_features,
    cross_sectional_z,
    identify_primary_factor,
    robust_z,
)

_D = Decimal


class TestRobustZ:
    def test_normal_distribution(self):
        history = [float(i) for i in range(100)]
        z = robust_z(95.0, history)
        assert z is not None
        assert z > 1.0  # well above median

    def test_at_median(self):
        history = [float(i) for i in range(100)]
        z = robust_z(50.0, history)
        assert z is not None
        assert abs(z) < 0.5

    def test_insufficient_history(self):
        assert robust_z(1.0, [1, 2, 3]) is None

    def test_constant_history(self):
        z = robust_z(5.0, [5.0] * 20)
        assert z == 0.0


class TestCrossSectionalZ:
    def test_above_peers(self):
        z = cross_sectional_z(0.50, [0.10, 0.12, 0.15, 0.11, 0.13])
        assert z is not None
        assert z > 2.0

    def test_at_peer_median(self):
        z = cross_sectional_z(0.12, [0.10, 0.12, 0.14, 0.11, 0.13])
        assert z is not None
        assert abs(z) < 1.0

    def test_insufficient_peers(self):
        assert cross_sectional_z(0.5, [0.1, 0.2]) is None


class TestFactorEP:
    def test_all_inputs(self):
        f = compute_factor_ep(z_event_premium_ts=1.5, z_event_premium_xs=1.0, z_term_slope_ts=0.5, iv_ramp_persist_3=0.8)
        assert f > _D("0.5")
        assert f <= _D("1")

    def test_no_inputs(self):
        f = compute_factor_ep(None, None, None, 0.0)
        assert f == _D("0")

    def test_partial_inputs(self):
        f = compute_factor_ep(z_event_premium_ts=1.0, z_event_premium_xs=None, z_term_slope_ts=None)
        assert f > _D("0")


class TestFactorSR:
    def test_strong_repricing(self):
        f = compute_factor_sr(z_iv_change_3d_ts=2.0, z_iv_change_3d_xs=1.5, z_surface_move_ts=1.8, iv_accel_3=1.0)
        assert f > _D("0.6")

    def test_no_repricing(self):
        f = compute_factor_sr(z_iv_change_3d_ts=0.0, z_iv_change_3d_xs=0.0, z_surface_move_ts=0.0)
        assert f < _D("0.6")


class TestFactorSK:
    def test_extreme_skew(self):
        f = compute_factor_sk(z_skew_ts=2.0, z_skew_change_ts=1.5, skew_persist_3=0.9, backwardation_flag=True)
        assert f > _D("0.7")

    def test_flat_skew(self):
        f = compute_factor_sk(z_skew_ts=0.0, z_skew_change_ts=0.0)
        assert f < _D("0.6")


class TestFactorDV:
    def test_stock_down_iv_up(self):
        f = compute_factor_dv(stock_down_iv_up=True)
        assert f >= _D("0.30")

    def test_quiet_before_catalyst(self):
        f = compute_factor_dv(quiet_before_catalyst=True)
        assert f >= _D("0.30")

    def test_no_divergence(self):
        f = compute_factor_dv()
        assert f < _D("0.3")


class TestChainQuality:
    def test_high_quality(self):
        q = compute_chain_quality(
            bid_ask_pct_median=0.02, open_interest_total=5000,
            volume_total=1000, strike_coverage_score=0.9,
            surface_fit_r2=0.95, stale_quote_pct=0.05,
        )
        assert q > _D("0.7")

    def test_low_quality(self):
        q = compute_chain_quality(bid_ask_pct_median=0.25, open_interest_total=10, volume_total=5)
        assert q < _D("0.4")


class TestConfidence:
    def test_high_quality_event_window(self):
        c = compute_confidence(_D("0.8"), event_window_flag=True, hard_catalyst_flag=True)
        assert c > _D("0.7")

    def test_low_quality_no_catalyst(self):
        c = compute_confidence(_D("0.3"), event_window_flag=False, hard_catalyst_flag=False)
        assert c < _D("0.25")


class TestComposite:
    def test_regulatory_weights_ep(self):
        """Regulatory catalyst should weight Event Premium highest."""
        s = compute_composite(_D("0.8"), _D("0.3"), _D("0.3"), _D("0.3"), _D("0.9"), "regulatory")
        s_other = compute_composite(_D("0.8"), _D("0.3"), _D("0.3"), _D("0.3"), _D("0.9"), "other")
        # Regulatory weights EP at 0.35 vs other at 0.25, so regulatory should score higher
        assert s > s_other

    def test_bounded(self):
        s = compute_composite(_D("1"), _D("1"), _D("1"), _D("1"), _D("1"), "other")
        assert s <= _D("1")
        assert s >= _D("0")

    def test_zero_confidence_kills(self):
        s = compute_composite(_D("0.8"), _D("0.8"), _D("0.8"), _D("0.8"), _D("0"), "other")
        # With zero confidence, S_adj=0, but max_factor still contributes 15%
        assert s <= _D("0.15")


class TestVerdict:
    def test_high(self):
        assert classify_monitor_verdict(_D("0.75")) == "HIGH"

    def test_watch(self):
        assert classify_monitor_verdict(_D("0.55")) == "WATCH"

    def test_none(self):
        assert classify_monitor_verdict(_D("0.30")) == "NONE"

    def test_boundary_high(self):
        assert classify_monitor_verdict(_D("0.70")) == "HIGH"

    def test_boundary_watch(self):
        assert classify_monitor_verdict(_D("0.50")) == "WATCH"


class TestPrimaryFactor:
    def test_ep_dominates(self):
        assert identify_primary_factor(_D("0.8"), _D("0.3"), _D("0.2"), _D("0.1")) == "EP"

    def test_dv_dominates(self):
        assert identify_primary_factor(_D("0.1"), _D("0.1"), _D("0.1"), _D("0.9")) == "DV"


class TestCatalystWeights:
    def test_all_classes_sum_to_1(self):
        for cls, weights in CATALYST_WEIGHTS.items():
            total = sum(weights.values())
            assert total == _D("1.00"), f"{cls} weights sum to {total}"


class TestFullCompute:
    def test_returns_all_fields(self):
        result = compute_v11_features(catalyst_class="regulatory", event_window_flag=True)
        expected = {
            "om11_factor_event_premium", "om11_factor_surface_repricing",
            "om11_factor_skew_tail", "om11_factor_divergence",
            "om11_chain_quality", "om11_confidence", "om11_score_final",
            "om11_primary_factor", "om11_monitor_verdict",
            "om11_catalyst_class", "om11_event_window_flag",
        }
        assert set(result.keys()) == expected

    def test_strong_signal(self):
        result = compute_v11_features(
            z_event_premium_ts=2.0, z_event_premium_xs=1.5,
            z_iv_change_3d_ts=1.8, z_skew_ts=1.5,
            stock_down_iv_up=True,
            event_window_flag=True, hard_catalyst_flag=True,
            bid_ask_pct_median=0.02, open_interest_total=3000,
            volume_total=500, strike_coverage_score=0.8,
            catalyst_class="regulatory",
        )
        assert result["om11_monitor_verdict"] in ("HIGH", "WATCH")
        assert Decimal(result["om11_score_final"]) > _D("0.3")

    def test_no_data(self):
        result = compute_v11_features()
        assert result["om11_monitor_verdict"] == "NONE"
        assert result["om11_catalyst_class"] == "other"
