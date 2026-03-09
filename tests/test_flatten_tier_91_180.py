"""Tests for binary_91_180_flatten_tier_sort ruleset flag."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from decision_engine import DecisionRuleset, compute_actionable_sort_key


def _make_fields(
    eligible="1",
    tier_dev="B",
    catalyst_mode="specific_days",
    catalyst_days=120,
    mom_state="neutral",
    sponsor_tier1_count=0,
    catalyst_bucket="less_binary",
    **extra,
):
    d = {
        "eligible": eligible,
        "tier_dev": tier_dev,
        "catalyst_mode": catalyst_mode,
        "catalyst_days": str(catalyst_days),
        "mom_state": mom_state,
        "sponsor_tier1_count": str(sponsor_tier1_count),
        "catalyst_bucket": catalyst_bucket,
    }
    d.update(extra)
    return d


def _sort_key(fields, ruleset=None, optionality=50.0, ticker="TEST"):
    return compute_actionable_sort_key(
        decision_fields=fields,
        archetype="drug_developer",
        optionality=optionality,
        composite_rank=100,
        ticker=ticker,
        ruleset=ruleset,
        tiebreaker_pct=optionality,
    )


# ---------------------------------------------------------------------------
# Default flag (OFF): tier still discriminates within less_binary
# ---------------------------------------------------------------------------
class TestFlattenTierOff:
    def test_default_flag_is_false(self):
        rs = DecisionRuleset()
        assert rs.binary_91_180_flatten_tier_sort is False

    def test_tier_a_sorts_before_tier_b(self):
        rs = DecisionRuleset(sort_anchor="optionality_pct")
        a = _make_fields(tier_dev="A", catalyst_bucket="less_binary")
        b = _make_fields(tier_dev="B", catalyst_bucket="less_binary")
        key_a = _sort_key(a, ruleset=rs, ticker="AAA")
        key_b = _sort_key(b, ruleset=rs, ticker="BBB")
        assert key_a < key_b  # A sorts first

    def test_tier_b_cannot_beat_tier_a_with_higher_optionality(self):
        """Without flatten, B-tier can't beat A-tier even with better optionality."""
        rs = DecisionRuleset(sort_anchor="optionality_pct")
        a = _make_fields(tier_dev="A", catalyst_bucket="less_binary")
        b = _make_fields(tier_dev="B", catalyst_bucket="less_binary")
        key_a = _sort_key(a, ruleset=rs, optionality=30.0, ticker="AAA")
        key_b = _sort_key(b, ruleset=rs, optionality=90.0, ticker="BBB")
        assert key_a < key_b  # A still wins despite lower optionality


# ---------------------------------------------------------------------------
# Flag ON: tier flattened within less_binary
# ---------------------------------------------------------------------------
class TestFlattenTierOn:
    @pytest.fixture()
    def rs(self):
        return DecisionRuleset(
            sort_anchor="optionality_pct",
            binary_91_180_flatten_tier_sort=True,
        )

    def test_flag_loads(self, rs):
        assert rs.binary_91_180_flatten_tier_sort is True

    def test_b_tier_beats_a_tier_with_higher_optionality(self, rs):
        """With flatten, B-tier with higher optionality sorts before A-tier."""
        a = _make_fields(tier_dev="A", catalyst_bucket="less_binary")
        b = _make_fields(tier_dev="B", catalyst_bucket="less_binary")
        key_a = _sort_key(a, ruleset=rs, optionality=30.0, ticker="AAA")
        key_b = _sort_key(b, ruleset=rs, optionality=90.0, ticker="BBB")
        assert key_b < key_a  # B wins with higher optionality

    def test_same_optionality_same_tier_ord(self, rs):
        """A and B with same optionality should sort by tiebreakers (ticker)."""
        a = _make_fields(tier_dev="A", catalyst_bucket="less_binary")
        b = _make_fields(tier_dev="B", catalyst_bucket="less_binary")
        key_a = _sort_key(a, ruleset=rs, optionality=50.0, ticker="AAA")
        key_b = _sort_key(b, ruleset=rs, optionality=50.0, ticker="BBB")
        # Both get tier_ord=1, so subsequent tiebreakers decide
        # Ticker "AAA" < "BBB" alphabetically
        assert key_a < key_b

    def test_c_tier_also_flattened(self, rs):
        """C-tier within less_binary is also flattened."""
        a = _make_fields(tier_dev="A", catalyst_bucket="less_binary")
        c = _make_fields(tier_dev="C", catalyst_bucket="less_binary")
        key_a = _sort_key(a, ruleset=rs, optionality=30.0, ticker="AAA")
        key_c = _sort_key(c, ruleset=rs, optionality=90.0, ticker="CCC")
        assert key_c < key_a  # C wins with much higher optionality

    def test_only_affects_less_binary_bucket(self, rs):
        """Names in other buckets are NOT affected by the flag."""
        a_core = _make_fields(tier_dev="A", catalyst_bucket="core")
        b_core = _make_fields(tier_dev="B", catalyst_bucket="core")
        key_a = _sort_key(a_core, ruleset=rs, optionality=30.0, ticker="AAA")
        key_b = _sort_key(b_core, ruleset=rs, optionality=90.0, ticker="BBB")
        # Core bucket: A still beats B (tier not flattened)
        assert key_a < key_b

    def test_binary_now_not_affected(self, rs):
        """binary_now bucket is NOT affected."""
        a = _make_fields(tier_dev="A", catalyst_bucket="binary_now", catalyst_days=15)
        b = _make_fields(tier_dev="B", catalyst_bucket="binary_now", catalyst_days=15)
        key_a = _sort_key(a, ruleset=rs, optionality=30.0, ticker="AAA")
        key_b = _sort_key(b, ruleset=rs, optionality=90.0, ticker="BBB")
        assert key_a < key_b  # A still wins

    def test_ineligible_not_flattened(self, rs):
        """Ineligible names in less_binary are NOT tier-flattened."""
        a = _make_fields(eligible="0", tier_dev="A", catalyst_bucket="less_binary")
        b = _make_fields(eligible="0", tier_dev="B", catalyst_bucket="less_binary")
        key_a = _sort_key(a, ruleset=rs, optionality=30.0, ticker="AAA")
        key_b = _sort_key(b, ruleset=rs, optionality=90.0, ticker="BBB")
        # Ineligible: tier_ord not flattened (is_eligible=1, not 0)
        assert key_a < key_b


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------
class TestRulesetJson:
    def test_round_trip(self, tmp_path):
        rs = DecisionRuleset(binary_91_180_flatten_tier_sort=True)
        path = tmp_path / "test.json"
        rs.to_json(str(path))
        loaded = DecisionRuleset.from_json(str(path))
        assert loaded.binary_91_180_flatten_tier_sort is True

    def test_backward_compat_missing_field(self, tmp_path):
        """Old JSON without the field should default to False."""
        import json

        path = tmp_path / "old.json"
        path.write_text(json.dumps({"sort_anchor": "optionality_pct"}))
        loaded = DecisionRuleset.from_json(str(path))
        assert loaded.binary_91_180_flatten_tier_sort is False

    def test_new_field_changes_ruleset_id(self, tmp_path):
        """Setting the flag should produce a different ruleset_id."""
        rs_off = DecisionRuleset(binary_91_180_flatten_tier_sort=False)
        rs_on = DecisionRuleset(binary_91_180_flatten_tier_sort=True)
        p_off = tmp_path / "off.json"
        p_on = tmp_path / "on.json"
        rs_off.to_json(str(p_off))
        rs_on.to_json(str(p_on))
        loaded_off = DecisionRuleset.from_json(str(p_off))
        loaded_on = DecisionRuleset.from_json(str(p_on))
        assert loaded_off.ruleset_id != loaded_on.ruleset_id
