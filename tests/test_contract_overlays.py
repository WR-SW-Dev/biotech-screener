"""Contract tests for decision_engine overlay, decay, and entry-point logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine import (
    DecisionRuleset,
    _compute_missing_components,
    _compute_overlays,
    _has_flag,
    _logistic_decay,
    compute_decision_fields,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _rec(**overrides):
    base = {
        "ticker": "TEST",
        "severity": "NONE",
        "confidence_overall": 0.7,
        "fundamental_red_flag": False,
        "fundamental_red_flag_reasons": [],
        "flags": [],
        "attn_flags": [],
        "catalyst_decay": {"days_to_catalyst": 45, "in_optimal_window": True},
        "smart_money_signal": {
            "tier1_holders": 3,
            "holders_increasing": [1, 2],
            "holders_decreasing": [],
            "overlap_count": 1,
            "tier_breakdown": {},
        },
        "coinvest": {"tier1_count": 3},
        "defensive_features": {
            "drawdown": -0.15,
            "vol_60d": 0.40,
            "beta_xbi_60d": 1.1,
            "rsi_14d": 55.0,
        },
        "score_breakdown": {"enhancements": {"momentum": {"alpha_60d": 0.03}}},
        "momentum_signal": {"alpha_60d": 0.03},
        "survivability_signal": {
            "coverage": [],
            "metrics": {"cash_total": 500_000_000, "burn_ttm": 50_000_000},
        },
        "composite_rank": 50,
        "composite_score": 7.5,
        "score_rank_pct": 0.65,
    }
    base.update(overrides)
    return base


RS = DecisionRuleset()


# ===========================================================================
# TestLogisticDecay
# ===========================================================================


class TestLogisticDecay:
    def test_days_zero_near_one(self):
        val = _logistic_decay(0, midpoint=150, scale=30)
        assert val > 0.99

    def test_days_at_midpoint_near_half(self):
        val = _logistic_decay(150, midpoint=150, scale=30)
        assert abs(val - 0.5) < 0.01

    def test_days_very_large_near_zero(self):
        val = _logistic_decay(1000, midpoint=150, scale=30)
        assert val < 0.01

    def test_days_none_returns_zero(self):
        assert _logistic_decay(None, midpoint=150, scale=30) == 0.0

    def test_days_negative_returns_zero(self):
        assert _logistic_decay(-1, midpoint=150, scale=30) == 0.0


# ===========================================================================
# TestHasFlag
# ===========================================================================


class TestHasFlag:
    def test_flag_present_pipe(self):
        assert _has_flag("high_vol|deep_dd", "high_vol") is True

    def test_flag_absent(self):
        assert _has_flag("high_vol", "deep_dd") is False

    def test_empty_string(self):
        assert _has_flag("", "high_vol") is False

    def test_none(self):
        assert _has_flag(None, "high_vol") is False

    def test_comma_separated(self):
        assert _has_flag("high_vol,deep_dd", "deep_dd") is True


# ===========================================================================
# TestMissingComponents
# ===========================================================================


class TestMissingComponents:
    def test_all_present(self):
        fields = {
            "catalyst_mode": "specific_days",
            "sponsor_tier1_count": 5,
            "risk_flags": "",
        }
        assert _compute_missing_components(fields) == []

    def test_catalyst_missing(self):
        fields = {
            "catalyst_mode": "missing",
            "sponsor_tier1_count": 5,
            "risk_flags": "",
        }
        assert "catalyst" in _compute_missing_components(fields)

    def test_sponsor_missing(self):
        fields = {
            "catalyst_mode": "specific_days",
            "sponsor_tier1_count": "",
            "risk_flags": "",
        }
        assert "sponsor" in _compute_missing_components(fields)

    def test_drawdown_missing(self):
        fields = {
            "catalyst_mode": "specific_days",
            "sponsor_tier1_count": 5,
            "risk_flags": "drawdown_data_missing",
        }
        assert "drawdown" in _compute_missing_components(fields)

    def test_all_missing(self):
        fields = {
            "catalyst_mode": "missing",
            "sponsor_tier1_count": "",
            "risk_flags": "drawdown_data_missing",
        }
        result = _compute_missing_components(fields)
        assert len(result) == 3
        assert set(result) == {"catalyst", "sponsor", "drawdown"}


# ===========================================================================
# TestComputeOverlays
# ===========================================================================


class TestComputeOverlays:
    def test_sponsor_fields_populated(self):
        rec = _rec(
            smart_money_signal={
                "tier1_holders": 5,
                "holders_increasing": [],
                "holders_decreasing": [],
                "overlap_count": 2,
                "tier_breakdown": {},
            },
            coinvest={"tier1_count": 5},
        )
        out = _compute_overlays(rec, RS)
        assert out["sponsor_tier1_count"] == 5
        assert out["sponsor_overlap_count"] == 2

    def test_sponsor_net_buying(self):
        rec = _rec(
            smart_money_signal={
                "tier1_holders": 3,
                "holders_increasing": ["a", "b"],
                "holders_decreasing": ["c"],
                "overlap_count": 1,
                "tier_breakdown": {},
            },
        )
        out = _compute_overlays(rec, RS)
        assert out["sponsor_net_buying"] == "buying"

    def test_sponsor_net_selling(self):
        rec = _rec(
            smart_money_signal={
                "tier1_holders": 3,
                "holders_increasing": ["a"],
                "holders_decreasing": ["b", "c", "d"],
                "overlap_count": 1,
                "tier_breakdown": {},
            },
        )
        out = _compute_overlays(rec, RS)
        assert out["sponsor_net_buying"] == "selling"

    def test_catalyst_specific_days_near(self):
        rec = _rec(catalyst_decay={"days_to_catalyst": 30, "in_optimal_window": True})
        rs = DecisionRuleset(catalyst_near_days=120)
        out = _compute_overlays(rec, rs)
        assert out["catalyst_strength"] == "near"
        assert out["catalyst_mode"] == "specific_days"

    def test_catalyst_blended_window(self):
        rec = _rec(catalyst_decay={"days_to_catalyst": 0, "in_optimal_window": True})
        out = _compute_overlays(rec, RS)
        assert out["catalyst_mode"] == "blended_window"

    def test_catalyst_missing(self):
        rec = _rec(catalyst_decay={})
        out = _compute_overlays(rec, RS)
        assert out["catalyst_mode"] == "missing"

    def test_catalyst_logistic_decay_computed(self):
        rec = _rec(catalyst_decay={"days_to_catalyst": 60, "in_optimal_window": False})
        rs = DecisionRuleset(catalyst_time_decay_mode="logistic")
        out = _compute_overlays(rec, rs)
        assert out["catalyst_mode"] == "specific_days"
        assert 0.0 < out["catalyst_decay_w"] < 1.0

    def test_runway_bucket_critical(self):
        rec = _rec(severity="SEV3")
        out = _compute_overlays(rec, RS)
        assert out["runway_bucket"] == "critical"

    def test_runway_bucket_adequate(self):
        rec = _rec(severity="NONE")
        out = _compute_overlays(rec, RS)
        assert out["runway_bucket"] == "adequate"

    def test_momentum_tailwind(self):
        rec = _rec(
            score_breakdown={"enhancements": {"momentum": {"alpha_60d": 0.10}}},
        )
        out = _compute_overlays(rec, RS)
        assert out["mom_state"] == "tailwind"

    def test_momentum_headwind(self):
        rec = _rec(
            score_breakdown={"enhancements": {"momentum": {"alpha_60d": -0.10}}},
        )
        out = _compute_overlays(rec, RS)
        assert out["mom_state"] == "headwind"

    def test_risk_flags_high_vol(self):
        rec = _rec(
            defensive_features={
                "drawdown": -0.15,
                "vol_60d": 2.0,
                "beta_xbi_60d": 1.0,
                "rsi_14d": 50.0,
            },
        )
        out = _compute_overlays(rec, RS)
        assert "high_vol" in out["risk_flags"]

    def test_coinvest_conviction_fields(self):
        rec = _rec(
            coinvest={
                "tier1_count": 4,
                "conviction_overlap": 0.75,
                "tier1_conviction_overlap": 0.50,
                "max_tier1_position_pct": 3.2,
                "days_since_latest_filing": 45,
            },
        )
        out = _compute_overlays(rec, RS)
        assert out["coinvest_conviction"] == 0.75
        assert out["coinvest_tier1_conviction"] == 0.50
        assert out["coinvest_max_position_pct"] == 3.2
        assert out["coinvest_filing_age_days"] == 45
        assert out["coinvest_recency_state"] == "fresh"


# ===========================================================================
# TestComputeDecisionFields
# ===========================================================================


class TestComputeDecisionFields:
    def test_returns_all_decision_columns(self):
        result = compute_decision_fields(
            rec=_rec(),
            archetype="drug_developer",
            optionality_pct_dev=0.70,
            ruleset=RS,
        )
        expected_keys = {
            "decision_engine_version",
            "decision_engine_ruleset_id",
            "eligible",
            "ineligible_reasons",
            "sponsor_tier1_count",
            "sponsor_overlap_count",
            "sponsor_net_buying",
            "catalyst_days",
            "catalyst_in_window",
            "catalyst_mode",
            "catalyst_strength",
            "catalyst_decay_w",
            "runway_bucket",
            "mom_state",
            "risk_flags",
            "size_band",
            "size_reasons",
            "tier_dev",
            "tier_reason",
            "tier_commercial",
            "tier_any",
            "tier_any_reason",
            "cost_mult",
            "cost_bucket",
            "cost_haircut_applied",
            "catalyst_tilt_mult",
            "catalyst_tilt_applied",
            "mom_state_tilt_mult",
            "mom_state_tilt_applied",
            "dd_rel_margin_rescued",
            "missing_components",
            "missingness_penalty",
        }
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_eligible_rec_has_tier(self):
        result = compute_decision_fields(
            rec=_rec(),
            archetype="drug_developer",
            optionality_pct_dev=0.70,
            ruleset=RS,
        )
        assert result["eligible"] == "1"
        assert result["tier_dev"] in ("A", "B", "C", "D")

    def test_ineligible_rec_red_flag(self):
        rec = _rec(fundamental_red_flag=True)
        result = compute_decision_fields(
            rec=rec,
            archetype="drug_developer",
            optionality_pct_dev=0.70,
            ruleset=RS,
        )
        assert result["eligible"] == "0"
        assert result["tier_dev"] == "D"

    def test_financials_bypassed_risk_flag(self):
        rec = _rec(
            survivability_signal={
                "coverage": ["missing_cash", "missing_burn_data"],
                "metrics": {"cash_total": 0, "burn_ttm": 0},
            },
        )
        rs = DecisionRuleset(financials_missing_bypass_market_cap=1_000_000_000)
        result = compute_decision_fields(
            rec=rec,
            archetype="drug_developer",
            optionality_pct_dev=0.70,
            ruleset=rs,
            market_cap=50_000_000_000,
        )
        assert "financials_partial" in result["risk_flags"]

    def test_catalyst_tilt_applied(self):
        rec = _rec(catalyst_decay={"days_to_catalyst": 30, "in_optimal_window": True})
        rs = DecisionRuleset(
            enable_catalyst_tilt=True,
            catalyst_time_decay_mode="logistic",
        )
        result = compute_decision_fields(
            rec=rec,
            archetype="drug_developer",
            optionality_pct_dev=0.70,
            ruleset=rs,
        )
        assert result["catalyst_tilt_mult"] != 1.0
        assert result["catalyst_tilt_applied"] == "1"

    def test_mom_state_tilt_applied(self):
        rec = _rec(
            score_breakdown={"enhancements": {"momentum": {"alpha_60d": 0.10}}},
        )
        rs = DecisionRuleset(
            enable_mom_state_tilt=True,
            mom_state_tilt_mults=(
                ("tailwind", 1.10),
                ("neutral", 1.00),
                ("headwind", 0.90),
            ),
        )
        result = compute_decision_fields(
            rec=rec,
            archetype="drug_developer",
            optionality_pct_dev=0.70,
            ruleset=rs,
        )
        assert result["mom_state_tilt_mult"] == 1.10
        assert result["mom_state_tilt_applied"] == "1"
