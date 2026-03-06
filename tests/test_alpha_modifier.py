"""Tests for alpha modifier sort key behavior (tiebreak / within_tier modes)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine import DecisionRuleset, compute_actionable_sort_key, _safe_float


# =============================================================================
# Helpers
# =============================================================================

def _decision_fields(**overrides):
    """Minimal eligible decision fields."""
    df = {
        "eligible": "1",
        "tier_dev": "A",
        "catalyst_mode": "specific_days",
        "catalyst_days": "30",
        "sponsor_tier1_count": "2",
        "mom_state": "neutral",
        "missingness_penalty": "0",
    }
    df.update(overrides)
    return df


def _sort_key(df=None, *, alpha_raw=None, ruleset=None, ticker="TEST",
              composite_rank=10, optionality=0.50):
    """Shorthand: compute sort key with sensible defaults."""
    if df is None:
        df = _decision_fields()
    return compute_actionable_sort_key(
        decision_fields=df,
        archetype="drug_developer",
        optionality=optionality,
        composite_rank=composite_rank,
        ticker=ticker,
        ruleset=ruleset,
        alpha_raw=alpha_raw,
    )


# =============================================================================
# mode=off — alpha_raw should have zero effect
# =============================================================================

class TestModeOff:
    """When alpha_modifier_mode='off', alpha_raw must not affect ordering."""

    @pytest.fixture
    def rs(self):
        return DecisionRuleset(alpha_modifier_mode="off")

    def test_alpha_positive_no_effect(self, rs):
        k0 = _sort_key(alpha_raw=None, ruleset=rs)
        k1 = _sort_key(alpha_raw=0.05, ruleset=rs)
        assert k0 == k1

    def test_alpha_negative_no_effect(self, rs):
        k0 = _sort_key(alpha_raw=None, ruleset=rs)
        k1 = _sort_key(alpha_raw=-0.05, ruleset=rs)
        assert k0 == k1

    def test_default_ruleset_is_off(self):
        """DEFAULT_RULESET has alpha_modifier_mode=off."""
        k0 = _sort_key(alpha_raw=None)
        k1 = _sort_key(alpha_raw=0.10)
        assert k0 == k1


# =============================================================================
# mode=tiebreak — alpha as last sort key before ticker
# =============================================================================

class TestAlphaModifierDeprecated:
    """Alpha modifier code path removed — fields accepted for backward compat
    but have zero effect on sort order regardless of mode/weight."""

    @pytest.mark.parametrize("mode", ["off", "tiebreak", "within_tier"])
    def test_no_effect_any_mode(self, mode):
        """alpha_modifier has zero effect in all modes (code path removed)."""
        rs = DecisionRuleset(
            alpha_modifier_mode=mode,
            alpha_modifier_weight=0.20,
        )
        k_alpha = _sort_key(alpha_raw=0.10, ruleset=rs, ticker="AAA")
        k_none = _sort_key(alpha_raw=0.0, ruleset=rs, ticker="AAA")
        assert k_alpha == k_none

    @pytest.mark.parametrize("mode", ["tiebreak", "within_tier"])
    def test_none_alpha_no_crash(self, mode):
        """None alpha produces no crash in any mode."""
        rs = DecisionRuleset(alpha_modifier_mode=mode, alpha_modifier_weight=0.20)
        k = _sort_key(alpha_raw=None, ruleset=rs)
        assert k is not None

    def test_fields_still_accepted(self):
        """Deprecated fields still load without error."""
        rs = DecisionRuleset(
            alpha_modifier_mode="within_tier",
            alpha_modifier_weight=0.25,
        )
        assert rs.alpha_modifier_mode == "within_tier"
        assert rs.alpha_modifier_weight == 0.25


# =============================================================================
# Candidate ruleset loads cleanly
# =============================================================================

class TestCandidateRuleset:
    """v1.6.0_alpha_modifier_candidate.json loads and has expected overrides."""

    CANDIDATE_PATH = (
        Path(__file__).resolve().parent.parent
        / "production_data" / "decision_rulesets"
        / "v1.6.0_alpha_modifier_candidate.json"
    )

    def test_loads(self):
        rs = DecisionRuleset.from_json(str(self.CANDIDATE_PATH))
        assert rs.alpha_modifier_mode == "tiebreak"
        assert rs.alpha_modifier_weight == 0.05

    def test_rebuild_policy_if_missing(self):
        rs = DecisionRuleset.from_json(str(self.CANDIDATE_PATH))
        assert rs.alpha_table_rebuild_policy == "if_missing"

    def test_train_mode_trailing_6(self):
        rs = DecisionRuleset.from_json(str(self.CANDIDATE_PATH))
        assert rs.alpha_train_mode == "trailing-6"
        assert rs.alpha_train_horizon == 84

    def test_base_settings_match_production(self):
        """Core settings should match v1.5.1 production (coinvest off, alpha_cohort engine)."""
        rs = DecisionRuleset.from_json(str(self.CANDIDATE_PATH))
        assert rs.composite_engine == "alpha_cohort"
        assert rs.coinvest_sort_weight == 0.0
        assert rs.enable_clinical_sort_signal is True
        assert rs.enable_missingness_sort_penalty is True
        assert rs.catalyst_priority_mode == "tiebreaker"
        assert rs.sort_anchor == "alpha_cohort"


# =============================================================================
# Telemetry fields from DecisionRuleset
# =============================================================================

class TestAlphaTelemetryFields:
    """Verify DecisionRuleset exposes correct alpha modifier fields for telemetry."""

    def test_telemetry_fields_default_ruleset(self):
        """Default ruleset has mode=off, weight=0.0, policy=never."""
        rs = DecisionRuleset()
        assert rs.alpha_modifier_mode == "off"
        assert rs.alpha_modifier_weight == 0.0
        assert rs.alpha_table_rebuild_policy == "never"

    def test_telemetry_fields_candidate(self):
        """v1.6.0 candidate has mode=tiebreak, weight=0.05, policy=if_missing."""
        candidate = (
            Path(__file__).resolve().parent.parent
            / "production_data" / "decision_rulesets"
            / "v1.6.0_alpha_modifier_candidate.json"
        )
        rs = DecisionRuleset.from_json(str(candidate))
        assert rs.alpha_modifier_mode == "tiebreak"
        assert rs.alpha_modifier_weight == 0.05
        assert rs.alpha_table_rebuild_policy == "if_missing"
