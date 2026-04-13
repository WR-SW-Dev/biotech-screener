"""Tests for Options Expression Layer (Spec 062, Phase 1).

Covers: classification, overlay mapping, tradeability gates, sizing,
surface quality, confidence computations, governance, serialization.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from event_ev.data_contracts import (
    CatalystNode,
    CrowdBelief,
    ExpectationErrorScore,
    OutcomeProbabilities,
    ScenarioPayoffs,
    TimingEstimate,
)
from event_ev.expression_layer import (
    MISPRICING_TYPES,
    OVERLAY_CLASSES,
    ExpressionRecommendation,
    build_recommendation,
    check_tradeability_gates,
    classify_mispricing,
    compute_belief_strength,
    compute_execution_risk,
    compute_sizing,
    compute_surface_quality,
    compute_timing_confidence,
    compute_variance_confidence,
    select_overlay_class,
)

# ============================================================================
# Test fixtures
# ============================================================================


def _make_node(**overrides: Any) -> CatalystNode:
    defaults = {
        "ticker": "ACAD",
        "event_family": "CLINICAL",
        "event_type": "DATA_READOUT",
        "event_subtype": "TOPLINE",
        "expected_date": "2026-05-15",
        "date_range_start": "2026-05-15",
        "date_range_end": None,
        "date_precision": "MONTH",
        "date_confidence": 0.6,
        "source": "CTGOV",
        "source_uid": "NCT12345678",
        "disclosed_at": "2026-01-15",
        "phase": "3",
        "indication": "oncology",
    }
    defaults.update(overrides)
    return CatalystNode(**defaults)


def _make_outcome(**overrides: Any) -> OutcomeProbabilities:
    defaults = {
        "node_id": "abc123",
        "as_of_date": "2026-04-13",
        "p_hit": 0.55,
        "p_miss": 0.35,
        "p_mixed": 0.10,
        "confidence": 0.65,
        "prior_source": "v2_empirical",
    }
    defaults.update(overrides)
    return OutcomeProbabilities(**defaults)


def _make_crowd(**overrides: Any) -> CrowdBelief:
    defaults = {
        "node_id": "abc123",
        "as_of_date": "2026-04-13",
        "implied_p_hit": 0.40,
        "belief_direction": "BEARISH",
        "belief_intensity": 0.5,
        "priced_move_pct": 25.0,
        "mispricing_score": 0.15,
    }
    defaults.update(overrides)
    return CrowdBelief(**defaults)


def _make_payoff(**overrides: Any) -> ScenarioPayoffs:
    defaults = {
        "node_id": "abc123",
        "as_of_date": "2026-04-13",
        "upside_hit": 40.0,
        "downside_miss": -30.0,
        "move_mixed": 5.0,
        "scenario_ev": 8.0,
        "asymmetry_ratio": 1.33,
        "downside_adjusted_ev": 5.0,
        "kelly_fraction": 0.10,
        "analog_count": 35,
        "analog_confidence": "ok",
    }
    defaults.update(overrides)
    return ScenarioPayoffs(**defaults)


def _make_ees(**overrides: Any) -> ExpectationErrorScore:
    defaults = {
        "ticker": "ACAD",
        "as_of_date": "2026-04-13",
        "base_rate_gap_score": 0.10,
        "conditional_misprice_score": 0.20,
        "slippage_penalty_score": 0.15,
        "divergence_score": 0.10,
        "crowding_bias_score": 0.05,
        "timing_decay_risk_score": 0.10,
        "expectation_error_score": 0.15,
        "expectation_confidence": 0.70,
        "expectation_notes": "",
        "quality_overlay_score": -0.10,
        "trap_overlay_score": -0.15,
        "ees_v2_score": -0.12,
    }
    defaults.update(overrides)
    return ExpectationErrorScore(**defaults)


def _make_timing(**overrides: Any) -> TimingEstimate:
    defaults = {
        "node_id": "abc123",
        "as_of_date": "2026-04-13",
        "prob_on_time": 0.60,
        "prob_slip": 0.30,
        "prob_early": 0.10,
        "expected_delay_days": 15.0,
        "median_arrival_days": 32.0,
        "hazard_rate": 0.03,
    }
    defaults.update(overrides)
    return TimingEstimate(**defaults)


def _classify(**kw: Any):
    """Shorthand for classify_mispricing with sensible defaults."""
    defaults = {
        "mispricing_score": 0.0,
        "scenario_ev": 0.0,
        "analog_confidence": "ok",
        "outcome_confidence": 0.65,
        "p_hit": 0.55,
        "p_miss": 0.35,
        "base_rate_gap_score": 0.0,
        "conditional_misprice_score": 0.0,
        "crowding_bias_score": 0.0,
        "timing_decay_risk_score": 0.0,
        "divergence_score": 0.0,
        "ees_confidence": 0.70,
        "prob_slip": 0.10,
        "prob_on_time": 0.80,
        "date_precision": "MONTH",
        "priced_move_pct": 25.0,
        "opt_rr_25d": None,
        "term_structure_shape": None,
        "surface_quality_score": 75.0,
        "base_rate_n": 30,
    }
    defaults.update(kw)
    return classify_mispricing(**defaults)


def _full_recommendation(**kw: Any) -> ExpressionRecommendation:
    """Build a recommendation with full default fixtures."""
    defaults = {
        "node": _make_node(),
        "outcome": _make_outcome(),
        "crowd": _make_crowd(),
        "payoff": _make_payoff(),
        "ees": _make_ees(),
        "timing": _make_timing(),
        "as_of_date": "2026-04-13",
        "opt_liquidity_state": "liquid",
        "opt_front_iv": 0.90,
        "opt_back_iv": 0.50,
        "bid_ask_spread_pct": 0.02,
        "priced_move_pct": 25.0,
        "quote_fresh": True,
    }
    defaults.update(kw)
    return build_recommendation(**defaults)


# ============================================================================
# Classification tests
# ============================================================================


class TestDirectionalClassification:
    def test_directional_bullish(self):
        mp_type, mp_sub = _classify(
            mispricing_score=0.20,
            scenario_ev=5.0,
            outcome_confidence=0.60,
            conditional_misprice_score=0.15,
        )
        assert mp_type == "DIRECTIONAL"
        assert mp_sub == "bullish_underpriced"

    def test_directional_bearish(self):
        mp_type, mp_sub = _classify(
            mispricing_score=-0.20,
            scenario_ev=-5.0,
            outcome_confidence=0.60,
            conditional_misprice_score=-0.15,
        )
        assert mp_type == "DIRECTIONAL"
        assert mp_sub == "bearish_underpriced"

    def test_directional_requires_alignment(self):
        """mispricing_score and conditional_misprice_score must agree on sign."""
        mp_type, _ = _classify(
            mispricing_score=0.20,
            scenario_ev=5.0,
            outcome_confidence=0.60,
            conditional_misprice_score=-0.15,  # disagrees
        )
        assert mp_type != "DIRECTIONAL"

    def test_directional_below_threshold(self):
        mp_type, _ = _classify(
            mispricing_score=0.10,  # below 0.15
            scenario_ev=5.0,
            outcome_confidence=0.60,
            conditional_misprice_score=0.10,
        )
        assert mp_type != "DIRECTIONAL"


class TestVarianceClassification:
    def test_variance_underpriced(self):
        mp_type, mp_sub = _classify(
            base_rate_gap_score=-0.35,
            divergence_score=-0.20,
            priced_move_pct=20.0,
            mispricing_score=0.05,  # below directional threshold
            ees_confidence=0.70,
            surface_quality_score=80.0,
            analog_confidence="ok",
            base_rate_n=30,
        )
        assert mp_type == "VARIANCE"
        assert mp_sub == "vol_underpriced"

    def test_variance_overpriced(self):
        mp_type, mp_sub = _classify(
            base_rate_gap_score=0.35,
            divergence_score=0.20,
            priced_move_pct=20.0,
            mispricing_score=0.05,
            ees_confidence=0.70,
            surface_quality_score=80.0,
            analog_confidence="ok",
            base_rate_n=30,
        )
        assert mp_type == "VARIANCE"
        assert mp_sub == "vol_overpriced"

    def test_variance_suppressed_by_directional(self):
        """Variance does not trigger when directional mispricing is strong."""
        mp_type, _ = _classify(
            base_rate_gap_score=-0.35,
            divergence_score=-0.20,
            priced_move_pct=20.0,
            mispricing_score=0.20,  # above directional threshold
            scenario_ev=5.0,
            conditional_misprice_score=0.15,
            outcome_confidence=0.60,
            ees_confidence=0.70,
            surface_quality_score=80.0,
        )
        # Should classify as DIRECTIONAL, not VARIANCE
        assert mp_type == "DIRECTIONAL"

    def test_variance_confidence_suppression(self):
        """variance_confidence < 0.55 suppresses VARIANCE."""
        mp_type, _ = _classify(
            base_rate_gap_score=-0.35,
            divergence_score=-0.20,
            priced_move_pct=20.0,
            mispricing_score=0.05,
            ees_confidence=0.40,  # low → low variance confidence
            surface_quality_score=50.0,
            analog_confidence="low",
            base_rate_n=5,
        )
        assert mp_type != "VARIANCE"

    def test_variance_small_sample_penalty(self):
        """Small base_rate_n penalises variance confidence."""
        conf = compute_variance_confidence(0.70, 80.0, "ok", base_rate_n=5)
        assert conf < 0.55  # should be penalised below threshold


class TestSkewClassification:
    def test_skew_put_rich(self):
        mp_type, mp_sub = _classify(
            crowding_bias_score=0.40,
            p_hit=0.60,
            p_miss=0.30,
            opt_rr_25d=-5.0,
            mispricing_score=0.05,  # below dir threshold
            base_rate_gap_score=0.10,  # below var threshold
        )
        assert mp_type == "SKEW"
        assert mp_sub == "put_skew_rich"

    def test_skew_requires_rr_data(self):
        mp_type, _ = _classify(
            crowding_bias_score=0.40,
            p_hit=0.60,
            p_miss=0.30,
            opt_rr_25d=None,  # no skew data
        )
        assert mp_type != "SKEW"


class TestTimingClassification:
    def test_timing_near_term_overpriced(self):
        mp_type, mp_sub = _classify(
            prob_slip=0.35,
            timing_decay_risk_score=0.50,
            term_structure_shape="backwardation",
            date_precision="MONTH",
            ees_confidence=0.80,
            surface_quality_score=85.0,
            prob_on_time=0.55,
        )
        assert mp_type == "TIMING"
        assert mp_sub == "near_term_overpriced"

    def test_timing_confidence_suppression(self):
        """timing_confidence < 0.60 suppresses TIMING."""
        mp_type, _ = _classify(
            prob_slip=0.30,
            timing_decay_risk_score=0.45,
            term_structure_shape="backwardation",
            date_precision="DAY",  # low precision factor (0.3) → low timing_conf
            ees_confidence=0.50,
            surface_quality_score=50.0,
            prob_on_time=0.50,
        )
        assert mp_type != "TIMING"

    def test_timing_requires_backwardation(self):
        mp_type, _ = _classify(
            prob_slip=0.35,
            timing_decay_risk_score=0.50,
            term_structure_shape="contango",  # wrong shape
            date_precision="MONTH",
            ees_confidence=0.80,
            surface_quality_score=85.0,
            prob_on_time=0.55,
        )
        assert mp_type != "TIMING"


class TestMixedClassification:
    def test_mixed_two_types_reduced(self):
        """Two types at reduced thresholds, none at full → MIXED."""
        mp_type, mp_sub = _classify(
            # Directional at reduced (0.7x) but not full
            mispricing_score=0.12,  # >= 0.15*0.7=0.105, < 0.15
            scenario_ev=2.5,  # >= 3.0*0.7=2.1, < 3.0
            outcome_confidence=0.40,  # >= 0.50*0.7=0.35, < 0.50
            conditional_misprice_score=0.10,
            # Skew at reduced
            crowding_bias_score=0.25,  # >= 0.30*0.7=0.21
            p_hit=0.60,
            p_miss=0.30,
            opt_rr_25d=-5.0,
        )
        assert mp_type == "MIXED"
        assert mp_sub != ""


class TestNoneClassification:
    def test_none_when_below_threshold(self):
        mp_type, mp_sub = _classify()  # all defaults are below thresholds
        assert mp_type == "NONE"
        assert mp_sub == ""


# ============================================================================
# Expression mapping tests
# ============================================================================


class TestExpressionMapping:
    def test_directional_bull_to_debit(self):
        cls, structs, _ = select_overlay_class("DIRECTIONAL", "bullish_underpriced")
        assert cls == "DIRECTIONAL_DEBIT"
        assert "bull_call_spread" in structs

    def test_variance_under_to_debit(self):
        cls, structs, _ = select_overlay_class("VARIANCE", "vol_underpriced")
        assert cls == "VARIANCE_DEBIT"
        assert "long_straddle" in structs

    def test_variance_over_to_credit(self):
        cls, _, _ = select_overlay_class("VARIANCE", "vol_overpriced", p_hit=0.50, p_miss=0.30)
        assert cls == "DEFINED_RISK_CREDIT"

    def test_timing_to_calendar(self):
        cls, structs, _ = select_overlay_class("TIMING", "near_term_overpriced")
        assert cls == "TIMING_CALENDAR"
        assert "calendar_spread" in structs

    def test_none_to_no_trade(self):
        cls, structs, _ = select_overlay_class("NONE", "")
        assert cls == "NO_TRADE"
        assert structs == []

    def test_mixed_to_manual_review(self):
        cls, _, _ = select_overlay_class("MIXED", "bullish_underpriced")
        assert cls == "MANUAL_REVIEW"

    def test_asymmetry_override(self):
        """High asymmetry overrides VARIANCE/vol_underpriced → DIRECTIONAL_DEBIT."""
        cls, _, rationale = select_overlay_class("VARIANCE", "vol_underpriced", asymmetry_ratio=3.0)
        assert cls == "DIRECTIONAL_DEBIT"
        assert "symmetry" in rationale.lower()

    def test_binary_gate_blocks_iron_condor(self):
        """p_hit + p_miss > 0.90 forbids DEFINED_RISK_CREDIT."""
        cls, _, _ = select_overlay_class("VARIANCE", "vol_overpriced", p_hit=0.60, p_miss=0.35)
        assert cls == "MANUAL_REVIEW"

    def test_timing_uncertainty_demotes_straddle(self):
        """Coarse date_precision demotes VARIANCE_DEBIT."""
        cls, _, _ = select_overlay_class("VARIANCE", "vol_underpriced", date_precision="QUARTER")
        assert cls in ("TIMING_CALENDAR", "MANUAL_REVIEW")

    def test_belief_permission_split(self):
        """High belief + low permission → MANUAL_REVIEW."""
        cls, _, rationale = select_overlay_class(
            "DIRECTIONAL",
            "bullish_underpriced",
            belief_strength=0.70,
            permission_to_express=0.30,
        )
        assert cls == "MANUAL_REVIEW"
        assert "watch" in rationale.lower()

    def test_belief_permission_both_high(self):
        """Both high → original mapping preserved."""
        cls, _, _ = select_overlay_class(
            "DIRECTIONAL",
            "bullish_underpriced",
            belief_strength=0.70,
            permission_to_express=0.70,
        )
        assert cls == "DIRECTIONAL_DEBIT"

    def test_belief_low_permission_high(self):
        """Low belief + high permission → no override (original mapping stands)."""
        cls, _, _ = select_overlay_class(
            "DIRECTIONAL",
            "bullish_underpriced",
            belief_strength=0.40,
            permission_to_express=0.80,
        )
        # Belief-permission split only triggers when belief>=0.60 AND permission<0.40
        assert cls == "DIRECTIONAL_DEBIT"


# ============================================================================
# Surface quality tests
# ============================================================================


class TestSurfaceQuality:
    def test_liquid_fresh_tight(self):
        sq = compute_surface_quality("liquid", 0.02, True)
        assert sq >= 70

    def test_illiquid(self):
        sq = compute_surface_quality("illiquid", 0.02, True)
        assert sq < 50

    def test_surface_quality_gate(self):
        """surface_quality < 50 → NO_TRADE, is_tradeable=False."""
        rec = _full_recommendation(opt_liquidity_state="illiquid")
        assert not rec.is_tradeable
        assert "illiquid_options" in rec.gate_failures or "invalid_surface" in rec.gate_failures

    def test_surface_quality_confidence_penalty(self):
        """surface_quality=60 reduces permission (and thus confidence)."""
        # Good surface
        rec_good = _full_recommendation(
            opt_liquidity_state="liquid",
            bid_ask_spread_pct=0.01,
        )
        # Worse surface (stale quote)
        rec_bad = _full_recommendation(
            opt_liquidity_state="liquid",
            bid_ask_spread_pct=0.01,
            quote_fresh=False,
        )
        assert rec_bad.permission_to_express <= rec_good.permission_to_express


# ============================================================================
# Confidence tests
# ============================================================================


class TestConfidence:
    def test_belief_strength_bounds(self):
        b = compute_belief_strength(0.70, 0.80, 1.0, 1.0)
        assert 0 <= b <= 1

    def test_belief_data_completeness(self):
        full = compute_belief_strength(0.70, 0.80, 1.0, 1.0)
        partial = compute_belief_strength(0.70, 0.80, 1.0, 0.6)
        assert partial < full

    def test_variance_confidence_ok(self):
        c = compute_variance_confidence(0.80, 85.0, "ok", 30)
        assert c >= 0.55

    def test_variance_confidence_insufficient(self):
        c = compute_variance_confidence(0.80, 85.0, "insufficient", 30)
        assert c < 0.55

    def test_timing_confidence_month(self):
        c = compute_timing_confidence(0.60, 0.30, 85.0, "MONTH")
        assert c >= 0.60

    def test_timing_confidence_day_low(self):
        """DAY precision → low precision factor → low timing confidence."""
        c = compute_timing_confidence(0.60, 0.30, 85.0, "DAY")
        assert c < 0.60

    def test_mispricing_confidence_is_min(self):
        """mispricing_confidence = min(belief, permission)."""
        rec = _full_recommendation()
        assert rec.mispricing_confidence == pytest.approx(
            min(rec.belief_strength, rec.permission_to_express), abs=0.001
        )


# ============================================================================
# Tradeability gate tests
# ============================================================================


def _base_gate_args(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "opt_liquidity_state": "liquid",
        "surface_quality_score": 75.0,
        "days_to_event": 30,
        "analog_confidence": "ok",
        "outcome_confidence": 0.65,
        "ees_confidence": 0.70,
        "priced_move_pct": 25.0,
        "mispricing_type": "DIRECTIONAL",
        "overlay_class": "DIRECTIONAL_DEBIT",
        "bid_ask_spread_pct": 0.02,
        "opt_rr_25d": None,
        "p_hit": 0.55,
        "p_miss": 0.35,
        "prob_slip": 0.20,
        "variance_confidence": 0.60,
        "timing_confidence": 0.65,
        "execution_risk": "moderate",
    }
    defaults.update(overrides)
    return defaults


class TestTradeabilityGates:
    def test_all_pass(self):
        failures = check_tradeability_gates(**_base_gate_args())
        assert failures == []

    def test_liquidity_gate(self):
        failures = check_tradeability_gates(**_base_gate_args(opt_liquidity_state="illiquid"))
        assert "illiquid_options" in failures

    def test_surface_gate(self):
        failures = check_tradeability_gates(**_base_gate_args(surface_quality_score=40.0))
        assert "invalid_surface" in failures

    def test_days_too_far(self):
        failures = check_tradeability_gates(**_base_gate_args(days_to_event=90))
        assert "event_too_far" in failures

    def test_days_too_near(self):
        failures = check_tradeability_gates(**_base_gate_args(days_to_event=1))
        assert "event_too_near" in failures

    def test_days_none(self):
        failures = check_tradeability_gates(**_base_gate_args(days_to_event=None))
        assert "event_too_far" in failures

    def test_insufficient_analogs(self):
        failures = check_tradeability_gates(**_base_gate_args(analog_confidence="insufficient"))
        assert "insufficient_analogs" in failures

    def test_low_model_confidence(self):
        failures = check_tradeability_gates(**_base_gate_args(outcome_confidence=0.30))
        assert "low_model_confidence" in failures

    def test_low_ees_confidence(self):
        failures = check_tradeability_gates(**_base_gate_args(ees_confidence=0.40))
        assert "low_ees_confidence" in failures

    def test_no_priced_move(self):
        failures = check_tradeability_gates(**_base_gate_args(priced_move_pct=None))
        assert "no_priced_move" in failures

    def test_no_mispricing(self):
        failures = check_tradeability_gates(**_base_gate_args(mispricing_type="NONE"))
        assert "no_mispricing" in failures

    def test_spread_too_wide(self):
        failures = check_tradeability_gates(**_base_gate_args(bid_ask_spread_pct=0.10))
        assert "spread_too_wide" in failures

    def test_spread_width_single_leg(self):
        """Straddle (VARIANCE_DEBIT): max 8% spread."""
        failures = check_tradeability_gates(
            **_base_gate_args(
                overlay_class="VARIANCE_DEBIT",
                bid_ask_spread_pct=0.09,
            )
        )
        assert "spread_too_wide" in failures

    def test_spread_width_multi_leg(self):
        """DIRECTIONAL_DEBIT: max 6% per leg."""
        failures = check_tradeability_gates(
            **_base_gate_args(
                overlay_class="DIRECTIONAL_DEBIT",
                bid_ask_spread_pct=0.07,
            )
        )
        assert "spread_too_wide" in failures

    def test_spread_width_four_leg(self):
        """DEFINED_RISK_CREDIT: max 4% per leg."""
        failures = check_tradeability_gates(
            **_base_gate_args(
                overlay_class="DEFINED_RISK_CREDIT",
                bid_ask_spread_pct=0.05,
                surface_quality_score=75.0,
            )
        )
        assert "spread_too_wide" in failures

    def test_binary_blocks_credit(self):
        failures = check_tradeability_gates(
            **_base_gate_args(
                overlay_class="DEFINED_RISK_CREDIT",
                p_hit=0.60,
                p_miss=0.35,
                surface_quality_score=75.0,
                bid_ask_spread_pct=0.01,
            )
        )
        assert "binary_event" in failures

    def test_low_delay_probability(self):
        failures = check_tradeability_gates(
            **_base_gate_args(
                overlay_class="TIMING_CALENDAR",
                prob_slip=0.10,
            )
        )
        assert "low_delay_probability" in failures

    def test_low_timing_confidence(self):
        failures = check_tradeability_gates(
            **_base_gate_args(
                overlay_class="TIMING_CALENDAR",
                timing_confidence=0.50,
            )
        )
        assert "low_timing_confidence" in failures

    def test_low_variance_confidence_gate(self):
        failures = check_tradeability_gates(
            **_base_gate_args(
                overlay_class="VARIANCE_DEBIT",
                variance_confidence=0.40,
            )
        )
        assert "low_variance_confidence" in failures

    def test_execution_risk_high_demotes(self):
        """4-leg + high exec risk + weak surface → gate failure."""
        failures = check_tradeability_gates(
            **_base_gate_args(
                overlay_class="DEFINED_RISK_CREDIT",
                execution_risk="high",
                surface_quality_score=60.0,
                bid_ask_spread_pct=0.01,
            )
        )
        assert "high_execution_risk" in failures


# ============================================================================
# Sizing tests
# ============================================================================


class TestSizing:
    def test_high_confidence(self):
        premium, basis = compute_sizing(0.75)
        assert premium == 0.50
        assert basis == "kelly_capped"

    def test_medium_confidence(self):
        premium, basis = compute_sizing(0.55)
        assert premium == 0.30
        assert basis == "fixed_notional"

    def test_low_confidence(self):
        premium, basis = compute_sizing(0.40)
        assert premium == 0.0
        assert basis == "no_size"

    def test_sizing_kelly_cap(self):
        """Even at max confidence, premium capped at 0.50%."""
        premium, _ = compute_sizing(1.0)
        assert premium == 0.50

    def test_sizing_tiers(self):
        """Check boundary values."""
        assert compute_sizing(0.70)[0] == 0.50
        assert compute_sizing(0.69)[0] == 0.30
        assert compute_sizing(0.50)[0] == 0.30
        assert compute_sizing(0.49)[0] == 0.0


# ============================================================================
# Execution risk
# ============================================================================


class TestExecutionRisk:
    def test_low(self):
        assert compute_execution_risk(1) == "low"

    def test_moderate(self):
        assert compute_execution_risk(2) == "moderate"

    def test_high(self):
        assert compute_execution_risk(4) == "high"

    def test_leg_count_mapping(self):
        """Each overlay_class maps to correct leg_count."""
        from event_ev.expression_layer import _LEG_COUNTS

        assert _LEG_COUNTS["VARIANCE_DEBIT"] == 1
        assert _LEG_COUNTS["DIRECTIONAL_DEBIT"] == 2
        assert _LEG_COUNTS["TIMING_CALENDAR"] == 2
        assert _LEG_COUNTS["DEFINED_RISK_CREDIT"] == 4


# ============================================================================
# Graceful degradation
# ============================================================================


class TestGracefulDegradation:
    def test_no_options(self):
        """Missing options data → NO_TRADE, no crash."""
        rec = _full_recommendation(
            opt_liquidity_state="",
            opt_front_iv=None,
            opt_back_iv=None,
            bid_ask_spread_pct=None,
            priced_move_pct=None,
        )
        assert not rec.is_tradeable
        assert len(rec.gate_failures) > 0

    def test_no_ees_restricts(self):
        """Low EES confidence restricts classification."""
        rec = _full_recommendation(
            ees=_make_ees(expectation_confidence=0.20),
        )
        # Should still produce a valid recommendation (no crash)
        assert rec.mispricing_type in MISPRICING_TYPES
        # Low EES confidence should show up as gate failure
        assert "low_ees_confidence" in rec.gate_failures


# ============================================================================
# Determinism, governance, serialization
# ============================================================================


class TestDeterminism:
    def test_same_inputs_same_output(self):
        rec1 = _full_recommendation()
        rec2 = _full_recommendation()
        assert rec1.to_dict() == rec2.to_dict()


class TestGovernance:
    def test_governance_metadata_always_present(self):
        rec = _full_recommendation()
        assert rec.governance_class == "overlay_only"
        assert "not_alpha" in rec.policy_flags
        assert "not_ranking" in rec.policy_flags
        assert "operator_review_required" in rec.policy_flags

    def test_no_trade_has_governance(self):
        rec = _full_recommendation(opt_liquidity_state="illiquid")
        assert rec.governance_class == "overlay_only"

    def test_overlay_class_closed_enum(self):
        """Only 6 valid values accepted."""
        with pytest.raises(ValueError, match="overlay_class"):
            ExpressionRecommendation(
                ticker="X",
                node_id="x",
                as_of_date="2026-01-01",
                mispricing_type="NONE",
                mispricing_subtype="",
                belief_strength=0.0,
                permission_to_express=0.0,
                mispricing_confidence=0.0,
                priced_move_pct=None,
                scenario_ev=0.0,
                opt_atm_iv=None,
                overlay_class="INVALID_CLASS",
                example_structures=(),
                overlay_rationale="",
                max_premium_pct_nav=0.0,
                sizing_basis="no_size",
                surface_quality_score=0.0,
                execution_risk="low",
                leg_count=0,
                max_spread_pct=0.0,
                is_tradeable=False,
                gate_failures=(),
            )


class TestSerialization:
    def test_to_dict_roundtrip(self):
        rec = _full_recommendation()
        d = rec.to_dict()
        assert isinstance(d, dict)
        assert d["ticker"] == "ACAD"
        assert d["overlay_class"] in OVERLAY_CLASSES
        assert isinstance(d["example_structures"], list)
        assert isinstance(d["gate_failures"], list)
        assert isinstance(d["policy_flags"], list)

    def test_attribution_snapshot_fields(self):
        """priced_move_pct, scenario_ev, opt_atm_iv are first-class in to_dict."""
        rec = _full_recommendation(opt_atm_iv=0.85)
        d = rec.to_dict()
        assert "priced_move_pct" in d
        assert "scenario_ev" in d
        assert "opt_atm_iv" in d
        assert d["priced_move_pct"] == pytest.approx(25.0, abs=0.01)
        assert d["scenario_ev"] == pytest.approx(8.0, abs=0.01)
        assert d["opt_atm_iv"] == pytest.approx(0.85, abs=0.01)

    def test_attribution_snapshot_none(self):
        """Missing options data → None in snapshot fields, no crash."""
        rec = _full_recommendation(opt_atm_iv=None, priced_move_pct=None)
        d = rec.to_dict()
        assert d["opt_atm_iv"] is None
        assert d["priced_move_pct"] is None

    def test_to_dict_json_serializable(self):
        import json

        rec = _full_recommendation()
        s = json.dumps(rec.to_dict())
        assert isinstance(s, str)


# ============================================================================
# Decision log tests (what gets recorded)
# ============================================================================


class TestDecisionLog:
    def test_rejection_has_gate_failures(self):
        rec = _full_recommendation(opt_liquidity_state="illiquid")
        assert not rec.is_tradeable
        assert len(rec.gate_failures) > 0

    def test_tradeable_has_no_failures(self):
        rec = _full_recommendation()
        if rec.is_tradeable:
            assert rec.gate_failures == ()


# ============================================================================
# Import barrier test
# ============================================================================


class TestImportBarrier:
    def test_expression_not_imported_by_selector(self):
        """selector_engine.py must NOT import from expression_layer."""
        import ast
        from pathlib import Path

        sel_path = Path("selector_engine.py")
        if not sel_path.exists():
            sel_path = Path("/mnt/c/Projects/biotech_screener/biotech-screener/selector_engine.py")
        if sel_path.exists():
            tree = ast.parse(sel_path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod = getattr(node, "module", "") or ""
                    if "expression_layer" in mod:
                        pytest.fail("selector_engine.py imports expression_layer")
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if "expression_layer" in alias.name:
                                pytest.fail("selector_engine.py imports expression_layer")

    def test_expression_not_imported_by_ranker(self):
        """ranker_engine.py must NOT import from expression_layer."""
        import ast
        from pathlib import Path

        rk_path = Path("ranker_engine.py")
        if not rk_path.exists():
            rk_path = Path("/mnt/c/Projects/biotech_screener/biotech-screener/ranker_engine.py")
        if rk_path.exists():
            tree = ast.parse(rk_path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod = getattr(node, "module", "") or ""
                    if "expression_layer" in mod:
                        pytest.fail("ranker_engine.py imports expression_layer")
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if "expression_layer" in alias.name:
                                pytest.fail("ranker_engine.py imports expression_layer")

    def test_expression_not_imported_by_decision(self):
        """decision_engine.py must NOT import from expression_layer."""
        import ast
        from pathlib import Path

        de_path = Path("decision_engine.py")
        if not de_path.exists():
            de_path = Path("/mnt/c/Projects/biotech_screener/biotech-screener/decision_engine.py")
        if de_path.exists():
            tree = ast.parse(de_path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod = getattr(node, "module", "") or ""
                    if "expression_layer" in mod:
                        pytest.fail("decision_engine.py imports expression_layer")
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if "expression_layer" in alias.name:
                                pytest.fail("decision_engine.py imports expression_layer")
