"""Tests that alpha_raw has zero effect on sort ordering.

The alpha_modifier code path was removed after a 5-way backtest (2020-2026,
347 dates) confirmed it was inert.  The fields were removed from
DecisionRuleset.  These tests verify alpha_raw alone cannot change ordering.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine import DecisionRuleset, compute_actionable_sort_key


def _decision_fields(**overrides):
    """Minimal eligible decision fields."""
    base = {
        "eligible": "1",
        "tier_dev": "A",
        "tier_commercial": "",
        "tier_any": "A",
        "mom_state": "neutral",
        "catalyst_mode": "specific_days",
        "cat_priority": 0,
        "stage_bucket": "mid",
        "missingness_penalty": 0,
    }
    base.update(overrides)
    return base


def _sort_key(*, alpha_raw=None, ruleset=None, ticker="TEST"):
    rs = ruleset or DecisionRuleset()
    return compute_actionable_sort_key(
        _decision_fields(),
        archetype="drug_developer",
        optionality=0.65,
        composite_rank=50,
        ticker=ticker,
        tiebreaker_pct=0.65,
        alpha_raw=alpha_raw,
        ruleset=rs,
    )


class TestAlphaRawNoEffect:
    """Alpha raw alone must not affect sort ordering."""

    def test_alpha_positive_no_effect(self):
        k0 = _sort_key(alpha_raw=None)
        k1 = _sort_key(alpha_raw=0.05)
        assert k0 == k1

    def test_alpha_negative_no_effect(self):
        k0 = _sort_key(alpha_raw=None)
        k1 = _sort_key(alpha_raw=-0.05)
        assert k0 == k1

    def test_alpha_large_no_effect(self):
        k0 = _sort_key(alpha_raw=None)
        k1 = _sort_key(alpha_raw=0.50)
        assert k0 == k1


class TestCandidateRulesetLoads:
    """v1.6.0 candidate loads cleanly (alpha_modifier fields silently dropped)."""

    CANDIDATE_PATH = (
        Path(__file__).resolve().parent.parent
        / "production_data"
        / "decision_rulesets"
        / "v1.6.0_alpha_modifier_candidate.json"
    )

    def test_loads_without_error(self):
        rs = DecisionRuleset.from_json(str(self.CANDIDATE_PATH))
        assert rs.ruleset_id

    def test_rebuild_policy_if_missing(self):
        rs = DecisionRuleset.from_json(str(self.CANDIDATE_PATH))
        assert rs.alpha_table_rebuild_policy == "if_missing"

    def test_base_settings_match_production(self):
        rs = DecisionRuleset.from_json(str(self.CANDIDATE_PATH))
        assert rs.composite_engine == "alpha_cohort"
        assert rs.enable_clinical_sort_signal is True
        assert rs.sort_anchor == "alpha_cohort"
