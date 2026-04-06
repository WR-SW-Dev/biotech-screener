"""Tests for Spec 059 Phase B — Branch Sensitivity & Greeks Overlay.

Tests written BEFORE implementation per spec template.
"""

from __future__ import annotations

import math
from typing import Any, Dict

import pytest

# ============================================================================
# Fixtures
# ============================================================================


def _options_surface() -> Dict[str, Any]:
    """Typical options surface for a biotech name near a PDUFA."""
    return {
        "opt_atm_iv": 0.90,  # 90% annualized IV
        "opt_front_iv": 1.10,  # front-month loaded
        "opt_back_iv": 0.70,  # back-month calmer
        "underlying_price": 25.0,
        "atm_strike": 25.0,
        "catalyst_days": 14,
        "opt_liquidity_state": "liquid",
        "event_family": "REGULATORY",
    }


def _options_surface_thin() -> Dict[str, Any]:
    """Thin liquidity surface — should produce null outputs."""
    s = _options_surface()
    s["opt_liquidity_state"] = "thin"
    return s


def _scenario_moves() -> Dict[str, float]:
    """Scenario moves from the payoff engine."""
    return {
        "upside_hit": 20.0,  # +20% if HIT
        "downside_miss": -35.0,  # -35% if MISS
        "move_mixed": -2.0,  # -2% if MIXED
    }


# ============================================================================
# Test: Branch P&L Calculator
# ============================================================================


class TestBranchPnL:
    def test_computes_hit_branch(self):
        from event_ev.branch_sensitivity import compute_branch_sensitivity

        result = compute_branch_sensitivity(
            options_surface=_options_surface(),
            scenario_moves=_scenario_moves(),
        )
        assert result is not None
        assert "hit" in result["branches"]
        hit = result["branches"]["hit"]
        assert "stock_move_pct" in hit
        assert hit["stock_move_pct"] == 20.0
        assert "post_event_price" in hit
        assert hit["post_event_price"] == pytest.approx(30.0)  # 25 * 1.20

    def test_computes_miss_branch(self):
        from event_ev.branch_sensitivity import compute_branch_sensitivity

        result = compute_branch_sensitivity(
            options_surface=_options_surface(),
            scenario_moves=_scenario_moves(),
        )
        miss = result["branches"]["miss"]
        assert miss["stock_move_pct"] == -35.0
        assert miss["post_event_price"] == pytest.approx(16.25)  # 25 * 0.65

    def test_computes_mixed_branch(self):
        from event_ev.branch_sensitivity import compute_branch_sensitivity

        result = compute_branch_sensitivity(
            options_surface=_options_surface(),
            scenario_moves=_scenario_moves(),
        )
        mixed = result["branches"]["mixed"]
        assert mixed["stock_move_pct"] == -2.0

    def test_iv_crush_in_branches(self):
        """Post-event IV should be lower than pre-event IV."""
        from event_ev.branch_sensitivity import compute_branch_sensitivity

        result = compute_branch_sensitivity(
            options_surface=_options_surface(),
            scenario_moves=_scenario_moves(),
        )
        for branch_name in ("hit", "miss", "mixed"):
            branch = result["branches"][branch_name]
            assert "post_event_iv" in branch
            # Post-event IV should be crushed relative to pre-event
            assert branch["post_event_iv"] < _options_surface()["opt_atm_iv"]

    def test_greeks_present(self):
        """Each branch should have post-event delta and vega."""
        from event_ev.branch_sensitivity import compute_branch_sensitivity

        result = compute_branch_sensitivity(
            options_surface=_options_surface(),
            scenario_moves=_scenario_moves(),
        )
        for branch_name in ("hit", "miss"):
            branch = result["branches"][branch_name]
            assert "post_delta" in branch
            assert "post_vega" in branch
            # Delta should be finite
            assert not math.isnan(branch["post_delta"])

    def test_thin_liquidity_returns_null(self):
        """Thin liquidity should return null branch sensitivity."""
        from event_ev.branch_sensitivity import compute_branch_sensitivity

        result = compute_branch_sensitivity(
            options_surface=_options_surface_thin(),
            scenario_moves=_scenario_moves(),
        )
        assert result is None

    def test_absent_liquidity_returns_null(self):
        from event_ev.branch_sensitivity import compute_branch_sensitivity

        surface = _options_surface()
        surface["opt_liquidity_state"] = "absent"
        result = compute_branch_sensitivity(
            options_surface=surface,
            scenario_moves=_scenario_moves(),
        )
        assert result is None

    def test_missing_iv_returns_null(self):
        from event_ev.branch_sensitivity import compute_branch_sensitivity

        surface = _options_surface()
        surface["opt_atm_iv"] = None
        result = compute_branch_sensitivity(
            options_surface=surface,
            scenario_moves=_scenario_moves(),
        )
        assert result is None


# ============================================================================
# Test: Breakeven Straddle
# ============================================================================


class TestBreakevenStraddle:
    def test_breakeven_positive(self):
        """Breakeven move should be positive."""
        from event_ev.branch_sensitivity import compute_breakeven_straddle

        result = compute_breakeven_straddle(
            underlying_price=25.0,
            atm_iv=0.90,
            catalyst_days=14,
            event_family="REGULATORY",
        )
        assert result is not None
        assert result["breakeven_move_pct"] > 0

    def test_breakeven_increases_with_iv(self):
        """Higher IV should mean larger breakeven."""
        from event_ev.branch_sensitivity import compute_breakeven_straddle

        low_iv = compute_breakeven_straddle(
            underlying_price=25.0,
            atm_iv=0.50,
            catalyst_days=14,
        )
        high_iv = compute_breakeven_straddle(
            underlying_price=25.0,
            atm_iv=1.50,
            catalyst_days=14,
        )
        assert high_iv["breakeven_move_pct"] > low_iv["breakeven_move_pct"]

    def test_breakeven_increases_with_dte(self):
        """More time to expiry should mean larger breakeven (more theta)."""
        from event_ev.branch_sensitivity import compute_breakeven_straddle

        short_dte = compute_breakeven_straddle(
            underlying_price=25.0,
            atm_iv=0.90,
            catalyst_days=7,
        )
        long_dte = compute_breakeven_straddle(
            underlying_price=25.0,
            atm_iv=0.90,
            catalyst_days=30,
        )
        assert long_dte["breakeven_move_pct"] > short_dte["breakeven_move_pct"]

    def test_straddle_cost_pct(self):
        """Should report straddle cost as % of underlying."""
        from event_ev.branch_sensitivity import compute_breakeven_straddle

        result = compute_breakeven_straddle(
            underlying_price=25.0,
            atm_iv=0.90,
            catalyst_days=14,
        )
        assert "straddle_cost_pct" in result
        assert result["straddle_cost_pct"] > 0
        assert result["straddle_cost_pct"] < 1.0  # less than 100%

    def test_invalid_inputs_return_none(self):
        from event_ev.branch_sensitivity import compute_breakeven_straddle

        assert compute_breakeven_straddle(0, 0.9, 14) is None
        assert compute_breakeven_straddle(25.0, 0, 14) is None
        assert compute_breakeven_straddle(25.0, 0.9, 0) is None

    def test_market_over_under_pricing(self):
        """Should flag whether market is over/under-pricing the event."""
        from event_ev.branch_sensitivity import compute_breakeven_straddle

        result = compute_breakeven_straddle(
            underlying_price=25.0,
            atm_iv=0.90,
            catalyst_days=14,
            expected_move_pct=0.25,  # 25% expected
        )
        # If breakeven < expected, market is underpricing the event
        if result["breakeven_move_pct"] < 0.25:
            assert result["market_pricing"] == "underpriced"
        else:
            assert result["market_pricing"] == "overpriced"


# ============================================================================
# Test: Integration with EventEV
# ============================================================================


class TestBranchSensitivityOnEventEV:
    def test_attaches_to_event_ev_dict(self):
        """branch_sensitivity should serialize into EventEV.to_dict()."""
        from event_ev.data_contracts import EventEV

        # EventEV now has an optional branch_sensitivity field
        assert hasattr(EventEV, "branch_sensitivity")
