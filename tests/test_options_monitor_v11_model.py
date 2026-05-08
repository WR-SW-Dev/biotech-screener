"""Tests for Options Monitor v1.1 — trade verdict + probability model."""

import json
import tempfile
from pathlib import Path

import pytest

from common.options_monitor_v11_model import (
    OM11ProbabilityModel,
    compute_full_verdict,
    compute_trade_verdict,
    track_state,
)


class TestTradeVerdict:
    def test_long_gamma_event_window(self):
        tv = compute_trade_verdict(
            s_final=0.75,
            f_ep=0.70,
            f_sr=0.40,
            f_sk=0.30,
            f_dv=0.20,
            chain_quality=0.8,
            event_window_flag=True,
            hard_catalyst_flag=True,
        )
        assert tv.bias == "LONG_GAMMA"
        assert tv.confidence > 0.5

    def test_no_action_weak_signal(self):
        tv = compute_trade_verdict(
            s_final=0.30,
            f_ep=0.20,
            f_sr=0.10,
            f_sk=0.10,
            f_dv=0.10,
            chain_quality=0.5,
        )
        assert tv.bias == "NO_ACTION"
        assert tv.confidence == 0.0

    def test_short_premium_avoid_low_quality(self):
        tv = compute_trade_verdict(
            s_final=0.60,
            f_ep=0.65,
            f_sr=0.30,
            f_sk=0.20,
            f_dv=0.10,
            chain_quality=0.3,  # low quality
        )
        assert tv.bias == "SHORT_PREMIUM_AVOID"

    def test_short_premium_avoid_high_divergence(self):
        tv = compute_trade_verdict(
            s_final=0.60,
            f_ep=0.65,
            f_sr=0.30,
            f_sk=0.20,
            f_dv=0.55,
            chain_quality=0.7,
        )
        assert tv.bias == "SHORT_PREMIUM_AVOID"

    def test_short_premium_financing_skew(self):
        tv = compute_trade_verdict(
            s_final=0.50,
            f_ep=0.20,
            f_sr=0.20,
            f_sk=0.65,
            f_dv=0.20,
            chain_quality=0.6,
            catalyst_class="financing",
        )
        assert tv.bias == "SHORT_PREMIUM_AVOID"

    def test_post_event_short_vol(self):
        tv = compute_trade_verdict(
            s_final=0.50,
            f_ep=0.55,
            f_sr=0.20,
            f_sk=0.20,
            f_dv=0.10,
            chain_quality=0.7,
            post_event=True,
        )
        assert tv.bias == "POST_EVENT_SHORT_VOL"

    def test_probability_override_long_gamma(self):
        tv = compute_trade_verdict(
            s_final=0.50,
            f_ep=0.30,
            f_sr=0.30,
            f_sk=0.20,
            f_dv=0.10,
            chain_quality=0.5,
            p_move_gt_implied=0.70,
            p_false_positive=0.20,
            p_iv_crush=None,
        )
        assert tv.bias == "LONG_GAMMA"

    def test_probability_override_post_event(self):
        tv = compute_trade_verdict(
            s_final=0.40,
            f_ep=0.30,
            f_sr=0.20,
            f_sk=0.20,
            f_dv=0.10,
            chain_quality=0.5,
            post_event=True,
            p_move_gt_implied=0.30,
            p_false_positive=0.50,
            p_iv_crush=0.70,
        )
        assert tv.bias == "POST_EVENT_SHORT_VOL"

    def test_primary_factor_identified(self):
        tv = compute_trade_verdict(
            s_final=0.30,
            f_ep=0.10,
            f_sr=0.10,
            f_sk=0.80,
            f_dv=0.10,
            chain_quality=0.5,
        )
        assert tv.primary_factor == "SK"


class TestStateTracking:
    def test_new_tickers(self):
        current = {"PVLA": {"om11_monitor_verdict": "HIGH"}}
        result = track_state(current)
        assert result["PVLA"]["state"] == "NEW"

    def test_ongoing_tickers(self, tmp_path):
        prior_path = tmp_path / "prior_state.json"
        prior_path.write_text(json.dumps({"active": [{"ticker": "PVLA", "om11_monitor_verdict": "WATCH"}]}))
        current = {"PVLA": {"om11_monitor_verdict": "HIGH"}}
        result = track_state(current, prior_state_path=prior_path)
        assert result["PVLA"]["state"] == "ONGOING"

    def test_resolved_tickers(self, tmp_path):
        prior_path = tmp_path / "prior_state.json"
        prior_path.write_text(
            json.dumps({"active": [{"ticker": "OLD", "om11_monitor_verdict": "HIGH", "om11_score_final": "0.75"}]})
        )
        current = {"PVLA": {"om11_monitor_verdict": "HIGH"}}
        result = track_state(current, prior_state_path=prior_path)
        assert result["PVLA"]["state"] == "NEW"
        assert result["OLD"]["state"] == "RESOLVED"

    def test_no_prior_state(self):
        current = {"PVLA": {"om11_monitor_verdict": "HIGH"}}
        result = track_state(current, prior_state_path=Path("/nonexistent"))
        assert result["PVLA"]["state"] == "NEW"


class TestProbabilityModel:
    def test_untrained_returns_none(self):
        model = OM11ProbabilityModel()
        assert not model.is_trained
        probs = model.predict({"om11_score_final": "0.7"})
        assert probs["p_move_gt_implied"] is None
        assert probs["p_post_event_iv_crush"] is None
        assert probs["p_false_positive"] is None

    def test_train_insufficient_data(self, tmp_path):
        labels_path = tmp_path / "labels.json"
        labels_path.write_text(json.dumps({"n_observations": 50}))
        model = OM11ProbabilityModel()
        assert not model.train(labels_path, min_observations=100)

    def test_save_load_round_trip(self, tmp_path):
        model = OM11ProbabilityModel()
        path = tmp_path / "model.json"
        model.save(path)
        assert path.exists()

        loaded = OM11ProbabilityModel()
        assert not loaded.load(path)  # not trained

    def test_missing_labels_path(self):
        model = OM11ProbabilityModel()
        assert not model.train(Path("/nonexistent"))


class TestFullVerdict:
    def test_returns_all_fields(self):
        features = {
            "om11_factor_event_premium": "0.65",
            "om11_factor_surface_repricing": "0.30",
            "om11_factor_skew_tail": "0.20",
            "om11_factor_divergence": "0.10",
            "om11_chain_quality": "0.70",
            "om11_confidence": "0.60",
            "om11_score_final": "0.55",
            "om11_primary_factor": "EP",
            "om11_monitor_verdict": "WATCH",
            "om11_catalyst_class": "regulatory",
            "om11_event_window_flag": "1",
        }
        result = compute_full_verdict(features)
        assert "om11_trade_bias" in result
        assert "om11_trade_confidence" in result
        assert "om11_trade_reason" in result
        assert "om11_p_move_gt_implied" in result
        assert result["om11_trade_bias"] in ("LONG_GAMMA", "SHORT_PREMIUM_AVOID", "POST_EVENT_SHORT_VOL", "NO_ACTION")

    def test_with_untrained_model(self):
        features = {
            "om11_score_final": "0.40",
            "om11_factor_event_premium": "0.30",
            "om11_factor_surface_repricing": "0.20",
            "om11_factor_skew_tail": "0.15",
            "om11_factor_divergence": "0.10",
            "om11_chain_quality": "0.50",
            "om11_confidence": "0.40",
            "om11_catalyst_class": "other",
            "om11_event_window_flag": "0",
        }
        model = OM11ProbabilityModel()
        result = compute_full_verdict(features, model=model)
        assert result["om11_p_move_gt_implied"] == ""  # untrained → empty
        assert result["om11_trade_bias"] == "NO_ACTION"
