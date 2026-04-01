"""Tests for build_price_action_watch.py — alert classification + output schema."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_price_action_watch import classify_alerts, compute_alert_confidence


class TestStockMoveAlerts:
    def test_big_move_up(self):
        alerts = classify_alerts("TEST", {"return_1d_pct": 12.0}, {})
        assert "STOCK_BIG_MOVE_UP" in alerts

    def test_move_up(self):
        alerts = classify_alerts("TEST", {"return_1d_pct": 6.0}, {})
        assert "STOCK_MOVE_UP" in alerts
        assert "STOCK_BIG_MOVE_UP" not in alerts

    def test_big_move_down(self):
        alerts = classify_alerts("TEST", {"return_1d_pct": -15.0}, {})
        assert "STOCK_BIG_MOVE_DOWN" in alerts

    def test_move_down(self):
        alerts = classify_alerts("TEST", {"return_1d_pct": -6.0}, {})
        assert "STOCK_MOVE_DOWN" in alerts
        assert "STOCK_BIG_MOVE_DOWN" not in alerts

    def test_no_move(self):
        alerts = classify_alerts("TEST", {"return_1d_pct": 1.0}, {})
        stock_alerts = [a for a in alerts if a.startswith("STOCK_")]
        assert len(stock_alerts) == 0

    def test_missing_return(self):
        alerts = classify_alerts("TEST", {}, {})
        stock_alerts = [a for a in alerts if a.startswith("STOCK_")]
        assert len(stock_alerts) == 0


class TestMoveIntensity:
    def test_intensity_spike(self):
        alerts = classify_alerts("TEST", {"move_intensity": 3.0}, {})
        assert "MOVE_INTENSITY_SPIKE" in alerts

    def test_normal_intensity(self):
        alerts = classify_alerts("TEST", {"move_intensity": 1.5}, {})
        assert "MOVE_INTENSITY_SPIKE" not in alerts


class TestOptionsSurfaceAlerts:
    def test_iv_ramp(self):
        alerts = classify_alerts("TEST", {}, {"atm_iv_change_5d": "0.15"})
        assert "IV_RAMP_HIGH" in alerts

    def test_iv_crush(self):
        alerts = classify_alerts("TEST", {}, {"atm_iv_change_5d": "-0.12"})
        assert "IV_CRUSH" in alerts

    def test_surface_move_high(self):
        alerts = classify_alerts("TEST", {}, {"actual_implied_move_pctile": "0.90"})
        assert "OPTIONS_SURFACE_MOVE_HIGH" in alerts

    def test_no_options_data(self):
        alerts = classify_alerts("TEST", {}, {})
        opts_alerts = [a for a in alerts if a.startswith("IV_") or a.startswith("OPTIONS_")]
        assert len(opts_alerts) == 0


class TestSkewExtreme:
    def test_skew_extreme_with_history(self):
        rr_history = [0.05, 0.04, 0.06, 0.03, 0.05, 0.04]
        alerts = classify_alerts("TEST", {}, {"opt_rr_25d": "0.35"}, rr_history=rr_history)
        assert "SKEW_EXTREME" in alerts

    def test_skew_not_extreme(self):
        rr_history = [0.05, 0.04, 0.06, 0.03, 0.05, 0.04]
        alerts = classify_alerts("TEST", {}, {"opt_rr_25d": "0.06"}, rr_history=rr_history)
        assert "SKEW_EXTREME" not in alerts

    def test_skew_insufficient_history_below_fallback(self):
        # With <5 history items, falls back to abs threshold of 0.50
        # RR=0.30 is below fallback threshold, so no alert
        rr_history = [0.05, 0.04]
        alerts = classify_alerts("TEST", {}, {"opt_rr_25d": "0.30"}, rr_history=rr_history)
        assert "SKEW_EXTREME" not in alerts

    def test_skew_insufficient_history_above_fallback(self):
        # With <5 history, RR=0.55 hits the abs fallback (>=0.50)
        rr_history = [0.05, 0.04]
        alerts = classify_alerts("TEST", {}, {"opt_rr_25d": "0.55"}, rr_history=rr_history)
        assert "SKEW_EXTREME" in alerts

    def test_skew_below_abs_floor(self):
        rr_history = [0.01, 0.02, 0.01, 0.02, 0.01, 0.02]
        alerts = classify_alerts("TEST", {}, {"opt_rr_25d": "0.05"}, rr_history=rr_history)
        assert "SKEW_EXTREME" not in alerts


class TestCombinedAlerts:
    def test_multiple_alerts(self):
        alerts = classify_alerts(
            "TEST",
            {"return_1d_pct": 12.0, "move_intensity": 4.0},
            {"atm_iv_change_5d": "0.15"},
        )
        assert "STOCK_BIG_MOVE_UP" in alerts
        assert "MOVE_INTENSITY_SPIKE" in alerts
        assert "IV_RAMP_HIGH" in alerts
        assert len(alerts) == 3


class TestAlertConfidence:
    def test_no_alerts(self):
        c = compute_alert_confidence([], {})
        assert c["alert_confidence"] == 0.0
        assert c["trigger_mode"] == "none"

    def test_stock_only_alerts(self):
        c = compute_alert_confidence(["STOCK_BIG_MOVE_UP"], {})
        assert c["trigger_mode"] == "stock_only"
        assert c["alert_confidence"] > 0.5

    def test_history_based_high_confidence(self):
        opts = {"opt_has_data": "1", "opt_liquidity_ok": "1", "opt_use_for_judgment": "YES"}
        rr_hist = [0.05, 0.04, 0.06, 0.03, 0.05, 0.04]
        c = compute_alert_confidence(["SKEW_EXTREME"], opts, rr_history=rr_hist)
        assert c["trigger_mode"] == "history_based"
        assert c["alert_confidence"] >= 0.7

    def test_abs_fallback_lower_confidence(self):
        opts = {"opt_has_data": "1", "opt_liquidity_ok": "0"}
        c = compute_alert_confidence(["SKEW_EXTREME"], opts, rr_history=[])
        assert c["trigger_mode"] == "low_liquidity_fallback"
        assert c["alert_confidence"] < 0.5

    def test_chain_quality_gate(self):
        opts_good = {"opt_has_data": "1", "opt_liquidity_ok": "1"}
        opts_bad = {"opt_has_data": "1", "opt_liquidity_ok": "0"}
        c_good = compute_alert_confidence(["IV_RAMP_HIGH"], opts_good)
        c_bad = compute_alert_confidence(["IV_RAMP_HIGH"], opts_bad)
        assert c_good["chain_quality_gate_pass"] is True
        assert c_bad["chain_quality_gate_pass"] is False

    def test_has_required_fields(self):
        c = compute_alert_confidence(["STOCK_MOVE_UP"], {})
        assert "alert_confidence" in c
        assert "trigger_mode" in c
        assert "history_depth" in c
        assert "chain_quality_gate_pass" in c
        assert "spread_gate_pass" in c


class TestOutputSchema:
    def test_existing_artifacts_valid(self):
        """Validate all existing price_action_watch artifacts."""
        artifacts_dir = Path(__file__).resolve().parents[1] / "artifacts" / "price_action_watch"
        if not artifacts_dir.exists():
            return
        for f in artifacts_dir.glob("*_watch.json"):
            with open(f) as fh:
                data = json.load(fh)
            assert data.get("schema") == "price_action_watch.v1"
            assert "as_of_date" in data
            assert "n_alerted" in data or "n_total" in data
            assert isinstance(data.get("rows", data.get("names", [])), list)
