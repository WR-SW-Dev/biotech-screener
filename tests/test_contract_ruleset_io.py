"""Tests for DecisionRuleset.from_json() / to_json() serialization paths."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest

from decision_engine import DEFAULT_RULESET, DecisionRuleset

# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_round_trip_preserves_ruleset_id(self, tmp_path):
        """to_json then from_json gives the same ruleset_id."""
        path = str(tmp_path / "rt.json")
        DEFAULT_RULESET.to_json(path)
        loaded = DecisionRuleset.from_json(path)
        assert loaded.ruleset_id == DEFAULT_RULESET.ruleset_id

    def test_hash_is_file_content_based(self, tmp_path):
        """Same JSON content produces the same hash; different content produces a different hash."""
        path_a = str(tmp_path / "a.json")
        path_b = str(tmp_path / "b.json")
        DEFAULT_RULESET.to_json(path_a)
        DEFAULT_RULESET.to_json(path_b)

        loaded_a = DecisionRuleset.from_json(path_a)
        loaded_b = DecisionRuleset.from_json(path_b)
        assert loaded_a.ruleset_id == loaded_b.ruleset_id

        # Mutate one field and write a different file.
        path_c = str(tmp_path / "c.json")
        altered = DecisionRuleset(catalyst_near_days=999)
        altered.to_json(path_c)
        loaded_c = DecisionRuleset.from_json(path_c)
        assert loaded_c.ruleset_id != loaded_a.ruleset_id


# ---------------------------------------------------------------------------
# from_json edge cases
# ---------------------------------------------------------------------------


class TestFromJsonEdgeCases:
    def test_unknown_fields_silently_dropped(self, tmp_path):
        """Extra keys in JSON are ignored without error."""
        path = str(tmp_path / "extra.json")
        DEFAULT_RULESET.to_json(path)
        with open(path) as fh:
            d = json.load(fh)
        d["future_field"] = 42
        d["another_unknown"] = "hello"
        with open(path, "w") as fh:
            json.dump(d, fh)
        loaded = DecisionRuleset.from_json(path)
        assert not hasattr(loaded, "future_field")

    def test_sizing_weights_dict_to_tuple(self, tmp_path):
        """sizing_weights stored as dict in JSON loads back as tuple."""
        path = str(tmp_path / "sw.json")
        DEFAULT_RULESET.to_json(path)
        # Verify JSON has dict form
        with open(path) as fh:
            d = json.load(fh)
        assert isinstance(d["sizing_weights"], dict)
        loaded = DecisionRuleset.from_json(path)
        assert isinstance(loaded.sizing_weights, tuple)
        assert dict(loaded.sizing_weights) == d["sizing_weights"]

    def test_cost_haircut_buckets_list_to_tuple(self, tmp_path):
        """cost_haircut_buckets stored as list-of-lists loads as tuple-of-tuples."""
        path = str(tmp_path / "chb.json")
        DEFAULT_RULESET.to_json(path)
        with open(path) as fh:
            d = json.load(fh)
        assert isinstance(d["cost_haircut_buckets"], list)
        loaded = DecisionRuleset.from_json(path)
        assert isinstance(loaded.cost_haircut_buckets, tuple)
        for inner in loaded.cost_haircut_buckets:
            assert isinstance(inner, tuple)

    def test_catalyst_tilt_mults_list_to_tuple(self, tmp_path):
        """catalyst_tilt_mults stored as list-of-lists loads as tuple-of-tuples."""
        path = str(tmp_path / "ctm.json")
        DEFAULT_RULESET.to_json(path)
        loaded = DecisionRuleset.from_json(path)
        assert isinstance(loaded.catalyst_tilt_mults, tuple)
        for inner in loaded.catalyst_tilt_mults:
            assert isinstance(inner, tuple)

    def test_catalyst_priority_map_list_to_tuple(self, tmp_path):
        """catalyst_priority_map stored as list-of-lists loads as tuple-of-tuples."""
        path = str(tmp_path / "cpm.json")
        DEFAULT_RULESET.to_json(path)
        loaded = DecisionRuleset.from_json(path)
        assert isinstance(loaded.catalyst_priority_map, tuple)
        for inner in loaded.catalyst_priority_map:
            assert isinstance(inner, tuple)

    def test_catalyst_priority_rank_bonuses_list_to_tuple(self, tmp_path):
        """catalyst_priority_rank_bonuses stored as list-of-lists loads as tuple-of-tuples."""
        path = str(tmp_path / "cprb.json")
        DEFAULT_RULESET.to_json(path)
        loaded = DecisionRuleset.from_json(path)
        assert isinstance(loaded.catalyst_priority_rank_bonuses, tuple)
        for inner in loaded.catalyst_priority_rank_bonuses:
            assert isinstance(inner, tuple)

    def test_clinical_stage_mults_list_to_tuple(self, tmp_path):
        """clinical_stage_mults stored as list-of-lists loads as tuple-of-tuples."""
        path = str(tmp_path / "csm.json")
        DEFAULT_RULESET.to_json(path)
        loaded = DecisionRuleset.from_json(path)
        assert isinstance(loaded.clinical_stage_mults, tuple)
        for inner in loaded.clinical_stage_mults:
            assert isinstance(inner, tuple)


# ---------------------------------------------------------------------------
# Migration: enable_catalyst_priority -> catalyst_priority_mode
# ---------------------------------------------------------------------------


class TestCatalystPriorityMigration:
    def test_enable_flag_true_without_mode_migrates_to_tiebreaker(self, tmp_path):
        """enable_catalyst_priority=True with no catalyst_priority_mode -> mode='tiebreaker'."""
        path = str(tmp_path / "migrate.json")
        DEFAULT_RULESET.to_json(path)
        with open(path) as fh:
            d = json.load(fh)
        d["enable_catalyst_priority"] = True
        d.pop("catalyst_priority_mode", None)
        with open(path, "w") as fh:
            json.dump(d, fh)
        loaded = DecisionRuleset.from_json(path)
        assert loaded.catalyst_priority_mode == "tiebreaker"

    def test_mode_takes_precedence_over_enable_flag(self, tmp_path):
        """When both enable_catalyst_priority and catalyst_priority_mode exist, mode wins."""
        path = str(tmp_path / "both.json")
        DEFAULT_RULESET.to_json(path)
        with open(path) as fh:
            d = json.load(fh)
        d["enable_catalyst_priority"] = True
        d["catalyst_priority_mode"] = "blended"
        with open(path, "w") as fh:
            json.dump(d, fh)
        loaded = DecisionRuleset.from_json(path)
        assert loaded.catalyst_priority_mode == "blended"


# ---------------------------------------------------------------------------
# __post_init__ validation
# ---------------------------------------------------------------------------


class TestPostInitValidation:
    def test_invalid_catalyst_priority_mode_rejected(self):
        with pytest.raises(ValueError, match="catalyst_priority_mode"):
            DecisionRuleset(catalyst_priority_mode="invalid")

    def test_invalid_drawdown_gate_mode_rejected(self):
        with pytest.raises(ValueError, match="drawdown_gate_mode"):
            DecisionRuleset(drawdown_gate_mode="invalid")

    def test_invalid_sort_anchor_rejected(self):
        with pytest.raises(ValueError, match="sort_anchor"):
            DecisionRuleset(sort_anchor="invalid")

    def test_invalid_composite_engine_rejected(self):
        with pytest.raises(ValueError, match="composite_engine"):
            DecisionRuleset(composite_engine="invalid")
