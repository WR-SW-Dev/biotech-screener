"""Tests for Event EV Promotion Ladder (Spec 061).

Covers all four stages:
  - Stage 1: Tiebreaker — EV breaks ties among names with identical sort keys
  - Stage 2: Rank overlay — bounded sort contribution
  - Stage 3: Sizing overlay — multiplicative sizing tilt
  - Stage 4: Composite — NotImplementedError placeholder
Plus: default OFF behavior preserves determinism, and JSON round-trip.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine import (
    SORT_CONTRIB_KEYS,
    DecisionRuleset,
    compute_actionable_sort_key,
    compute_sort_contribs,
    compute_target_weights,
)
from event_ev.promotion_ladder import (
    EventEVPromotionStage,
    classify_ev_bucket,
    compute_cohort_ev_z_scores,
    evaluate_ev_readiness,
    load_event_ev_for_cohort,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_fields(
    eligible="1",
    tier_dev="B",
    catalyst_mode="specific_days",
    catalyst_days=60,
    mom_state="neutral",
    sponsor_tier1_count=0,
    size_band="M",
    risk_flags="",
    event_ev_score=None,
    event_ev_score_z=None,
    event_ev_bucket="no_ev",
    event_ev_analog_confidence="",
    **extra,
):
    """Build a minimal decision_fields dict for testing."""
    fields = {
        "eligible": eligible,
        "tier_dev": tier_dev,
        "catalyst_mode": catalyst_mode,
        "catalyst_days": catalyst_days,
        "mom_state": mom_state,
        "sponsor_tier1_count": sponsor_tier1_count,
        "size_band": size_band,
        "risk_flags": risk_flags,
        "event_ev_score": event_ev_score if event_ev_score is not None else "",
        "event_ev_score_z": event_ev_score_z if event_ev_score_z is not None else "",
        "event_ev_bucket": event_ev_bucket,
        "event_ev_analog_confidence": event_ev_analog_confidence,
    }
    fields.update(extra)
    return fields


def _sort_key(fields, archetype="drug_developer", optionality=0.50, composite_rank=100, ticker="TEST", **kwargs):
    return compute_actionable_sort_key(
        decision_fields=fields,
        archetype=archetype,
        optionality=optionality,
        composite_rank=composite_rank,
        ticker=ticker,
        **kwargs,
    )


# =============================================================================
# Test: Default OFF — zero behavioral change
# =============================================================================


class TestStageOff:
    """When event_ev_stage='off' (default), Event EV has zero effect."""

    def test_default_stage_is_off(self):
        rs = DecisionRuleset()
        assert rs.event_ev_stage == "off"

    def test_sort_key_identical_with_and_without_ev_data(self):
        """EV score in fields has no effect when stage is off."""
        rs = DecisionRuleset()
        fields_no_ev = _make_fields()
        fields_with_ev = _make_fields(event_ev_score=5.0)

        key_no = _sort_key(fields_no_ev, ruleset=rs)
        key_with = _sort_key(fields_with_ev, ruleset=rs)
        assert key_no == key_with

    def test_event_ev_not_in_sort_contribs_when_off(self):
        """No event_ev contribution when stage is off."""
        rs = DecisionRuleset()
        fields = _make_fields(event_ev_score_z=1.5, event_ev_analog_confidence="ok")
        _, contrib_map = compute_sort_contribs(fields, "drug_developer", ruleset=rs)
        assert contrib_map["event_ev"] == 0

    def test_sort_contrib_keys_includes_event_ev(self):
        """The event_ev key exists in SORT_CONTRIB_KEYS for deterministic CSV."""
        assert "event_ev" in SORT_CONTRIB_KEYS


# =============================================================================
# Test: Stage 1 — Tiebreaker
# =============================================================================


class TestStage1Tiebreaker:
    """Stage 1: EV breaks ties among names with identical sort keys."""

    def test_tiebreaker_breaks_identical_sort_keys(self):
        """Two names with same sort prefix: higher EV wins."""
        rs = DecisionRuleset(event_ev_stage="tiebreaker")

        fields_a = _make_fields(event_ev_score=5.0)
        fields_b = _make_fields(event_ev_score=2.0)

        key_a = _sort_key(fields_a, ticker="AAA", ruleset=rs)
        key_b = _sort_key(fields_b, ticker="BBB", ruleset=rs)

        # A has higher EV → should sort first
        assert key_a < key_b

    def test_tiebreaker_no_effect_when_primary_differs(self):
        """EV tiebreaker doesn't override primary ordering (different tiers)."""
        rs = DecisionRuleset(event_ev_stage="tiebreaker")

        # A has better tier but lower EV
        fields_a = _make_fields(tier_dev="A", event_ev_score=1.0)
        fields_b = _make_fields(tier_dev="C", event_ev_score=10.0)

        key_a = _sort_key(fields_a, ticker="AAA", ruleset=rs)
        key_b = _sort_key(fields_b, ticker="BBB", ruleset=rs)

        # A still sorts first due to tier priority
        assert key_a < key_b

    def test_tiebreaker_missing_ev_defaults_to_zero(self):
        """Names without EV data get 0.0 tiebreak (no penalty, no boost)."""
        rs = DecisionRuleset(event_ev_stage="tiebreaker")

        fields_ev = _make_fields(event_ev_score=5.0)
        fields_none = _make_fields()

        key_ev = _sort_key(fields_ev, ticker="AAA", ruleset=rs)
        key_none = _sort_key(fields_none, ticker="BBB", ruleset=rs)

        # Name with EV sorts before name without
        assert key_ev < key_none

    def test_tiebreaker_selector_score_mode(self):
        """Stage 1 works with sort_anchor=selector_score (production path)."""
        rs = DecisionRuleset(
            event_ev_stage="tiebreaker",
            sort_anchor="selector_score",
        )

        # Both names have the same final_score
        fields_a = _make_fields(event_ev_score=8.0, final_score=0.75)
        fields_b = _make_fields(event_ev_score=3.0, final_score=0.75)

        key_a = _sort_key(fields_a, ticker="AAA", ruleset=rs)
        key_b = _sort_key(fields_b, ticker="BBB", ruleset=rs)

        assert key_a < key_b  # higher EV wins the tie


# =============================================================================
# Test: Stage 2 — Rank Overlay
# =============================================================================


class TestStage2RankOverlay:
    """Stage 2: bounded sort contribution from EV z-score."""

    def test_rank_overlay_produces_sort_contribution(self):
        """EV score_z produces a nonzero contribution when stage=rank_overlay."""
        rs = DecisionRuleset(
            event_ev_stage="rank_overlay",
            event_ev_rank_overlay_weight=0.3,
            event_ev_rank_overlay_cap=0.15,
        )
        fields = _make_fields(event_ev_score_z=1.5, event_ev_analog_confidence="ok")
        _, contrib_map = compute_sort_contribs(fields, "drug_developer", ruleset=rs)
        assert float(contrib_map["event_ev"]) != 0

    def test_rank_overlay_capped(self):
        """EV contribution is bounded by event_ev_rank_overlay_cap."""
        rs = DecisionRuleset(
            event_ev_stage="rank_overlay",
            event_ev_rank_overlay_weight=1.0,
            event_ev_rank_overlay_cap=0.10,
        )
        # z-score far exceeds cap
        fields = _make_fields(event_ev_score_z=5.0, event_ev_analog_confidence="ok")
        _, contrib_map = compute_sort_contribs(fields, "drug_developer", ruleset=rs)

        delta = float(contrib_map["event_ev"])
        # delta = weight * clamp(z, -cap, cap) = 1.0 * 0.10 = 0.10
        assert abs(delta - 0.10) < 1e-6

    def test_rank_overlay_negative_ev(self):
        """Negative EV z-score produces negative contribution (sorts later)."""
        rs = DecisionRuleset(
            event_ev_stage="rank_overlay",
            event_ev_rank_overlay_weight=0.5,
            event_ev_rank_overlay_cap=0.15,
        )
        fields = _make_fields(event_ev_score_z=-2.0, event_ev_analog_confidence="ok")
        _, contrib_map = compute_sort_contribs(fields, "drug_developer", ruleset=rs)

        delta = float(contrib_map["event_ev"])
        # delta = 0.5 * clamp(-2.0, -0.15, 0.15) = 0.5 * (-0.15) = -0.075
        assert abs(delta - (-0.075)) < 1e-6

    def test_rank_overlay_blocked_by_analog_confidence(self):
        """Low analog confidence below threshold → no contribution."""
        rs = DecisionRuleset(
            event_ev_stage="rank_overlay",
            event_ev_rank_overlay_weight=0.5,
            event_ev_min_analog_confidence="ok",
        )
        fields = _make_fields(
            event_ev_score_z=2.0,
            event_ev_analog_confidence="low",  # below "ok" threshold
        )
        _, contrib_map = compute_sort_contribs(fields, "drug_developer", ruleset=rs)
        assert float(contrib_map["event_ev"]) == 0

    def test_rank_overlay_allowed_with_sufficient_confidence(self):
        """Analog confidence 'ok' meets 'ok' threshold → contribution fires."""
        rs = DecisionRuleset(
            event_ev_stage="rank_overlay",
            event_ev_rank_overlay_weight=0.3,
            event_ev_min_analog_confidence="low",  # threshold lowered
        )
        fields = _make_fields(
            event_ev_score_z=1.0,
            event_ev_analog_confidence="low",
        )
        _, contrib_map = compute_sort_contribs(fields, "drug_developer", ruleset=rs)
        assert float(contrib_map["event_ev"]) != 0

    def test_rank_overlay_zero_weight_no_effect(self):
        """Weight=0 means no contribution even at rank_overlay stage."""
        rs = DecisionRuleset(
            event_ev_stage="rank_overlay",
            event_ev_rank_overlay_weight=0.0,
        )
        fields = _make_fields(event_ev_score_z=2.0, event_ev_analog_confidence="ok")
        _, contrib_map = compute_sort_contribs(fields, "drug_developer", ruleset=rs)
        assert float(contrib_map["event_ev"]) == 0


# =============================================================================
# Test: Stage 3 — Sizing Overlay
# =============================================================================


class TestStage3SizingOverlay:
    """Stage 3: multiplicative sizing tilt based on EV bucket."""

    def test_sizing_overlay_high_ev_boost(self):
        """high_ev names get boosted weight when sizing tilt configured."""
        rs = DecisionRuleset(
            event_ev_stage="sizing_overlay",
            event_ev_sizing_tilt_mults=(
                ("high_ev", 1.15),
                ("mid_ev", 1.0),
                ("low_ev", 0.90),
                ("no_ev", 1.0),
            ),
        )
        # Two rows: one high_ev, one no_ev
        rows = [
            {"size_band": "M", "event_ev_bucket": "high_ev"},
            {"size_band": "M", "event_ev_bucket": "no_ev"},
        ]
        result = compute_target_weights(rows, ruleset=rs)
        w_high = result[0]["target_weight_pct"]
        w_none = result[1]["target_weight_pct"]
        # high_ev should get proportionally more weight
        assert w_high > w_none

    def test_sizing_overlay_default_mults_no_change(self):
        """Default sizing mults are all 1.0 → no behavioral change."""
        rs = DecisionRuleset(event_ev_stage="sizing_overlay")
        rs_off = DecisionRuleset()

        rows_on = [
            {"size_band": "M", "event_ev_bucket": "high_ev"},
            {"size_band": "M", "event_ev_bucket": "no_ev"},
        ]
        rows_off = [
            {"size_band": "M", "event_ev_bucket": "high_ev"},
            {"size_band": "M", "event_ev_bucket": "no_ev"},
        ]
        compute_target_weights(rows_on, ruleset=rs)
        compute_target_weights(rows_off, ruleset=rs_off)

        assert rows_on[0]["target_weight_pct"] == rows_off[0]["target_weight_pct"]
        assert rows_on[1]["target_weight_pct"] == rows_off[1]["target_weight_pct"]

    def test_sizing_overlay_low_ev_penalty(self):
        """low_ev names get reduced weight."""
        rs = DecisionRuleset(
            event_ev_stage="sizing_overlay",
            event_ev_sizing_tilt_mults=(
                ("high_ev", 1.10),
                ("mid_ev", 1.0),
                ("low_ev", 0.85),
                ("no_ev", 1.0),
            ),
        )
        rows = [
            {"size_band": "M", "event_ev_bucket": "low_ev"},
            {"size_band": "M", "event_ev_bucket": "mid_ev"},
        ]
        result = compute_target_weights(rows, ruleset=rs)
        w_low = result[0]["target_weight_pct"]
        w_mid = result[1]["target_weight_pct"]
        assert w_low < w_mid


# =============================================================================
# Test: Stage 4 — Composite (placeholder)
# =============================================================================


class TestStage4Composite:
    """Stage 4: composite raises NotImplementedError."""

    def test_composite_raises_not_implemented(self):
        rs = DecisionRuleset(event_ev_stage="composite")
        fields = _make_fields()
        with pytest.raises(NotImplementedError, match="composite"):
            _sort_key(fields, ruleset=rs)


# =============================================================================
# Test: Ruleset validation
# =============================================================================


class TestRulesetValidation:
    """DecisionRuleset validates Spec 061 fields correctly."""

    def test_invalid_stage_raises(self):
        with pytest.raises(ValueError, match="event_ev_stage"):
            DecisionRuleset(event_ev_stage="invalid")

    def test_valid_stages_accepted(self):
        for stage in ("off", "tiebreaker", "rank_overlay", "sizing_overlay", "composite"):
            rs = DecisionRuleset(event_ev_stage=stage)
            assert rs.event_ev_stage == stage

    def test_overlay_weight_out_of_range(self):
        with pytest.raises(ValueError, match="event_ev_rank_overlay_weight"):
            DecisionRuleset(event_ev_rank_overlay_weight=1.5)

    def test_overlay_cap_out_of_range(self):
        with pytest.raises(ValueError, match="event_ev_rank_overlay_cap"):
            DecisionRuleset(event_ev_rank_overlay_cap=-0.1)

    def test_invalid_analog_confidence(self):
        with pytest.raises(ValueError, match="event_ev_min_analog_confidence"):
            DecisionRuleset(event_ev_min_analog_confidence="high")

    def test_invalid_sizing_bucket(self):
        with pytest.raises(ValueError, match="event_ev_sizing_tilt_mults"):
            DecisionRuleset(event_ev_sizing_tilt_mults=(("bad_bucket", 1.0),))

    def test_sizing_mult_must_be_positive(self):
        with pytest.raises(ValueError, match="event_ev_sizing_tilt_mults"):
            DecisionRuleset(event_ev_sizing_tilt_mults=(("high_ev", -1.0),))

    def test_json_round_trip(self):
        """New fields survive JSON write → read cycle."""
        rs = DecisionRuleset(
            event_ev_stage="rank_overlay",
            event_ev_rank_overlay_weight=0.3,
            event_ev_rank_overlay_cap=0.12,
            event_ev_min_analog_confidence="low",
            event_ev_sizing_tilt_mults=(
                ("high_ev", 1.10),
                ("mid_ev", 1.0),
                ("low_ev", 0.90),
                ("no_ev", 1.0),
            ),
            event_ev_sizing_high_threshold=4.0,
            event_ev_sizing_low_threshold=-2.0,
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_name = f.name
        try:
            rs.to_json(tmp_name)
            loaded = DecisionRuleset.from_json(tmp_name)
        finally:
            os.unlink(tmp_name)

        assert loaded.event_ev_stage == "rank_overlay"
        assert loaded.event_ev_rank_overlay_weight == 0.3
        assert loaded.event_ev_rank_overlay_cap == 0.12
        assert loaded.event_ev_min_analog_confidence == "low"
        assert dict(loaded.event_ev_sizing_tilt_mults) == {
            "high_ev": 1.10,
            "mid_ev": 1.0,
            "low_ev": 0.90,
            "no_ev": 1.0,
        }
        assert loaded.event_ev_sizing_high_threshold == 4.0
        assert loaded.event_ev_sizing_low_threshold == -2.0


# =============================================================================
# Test: Promotion Ladder Module
# =============================================================================


class TestPromotionLadderModule:
    """Tests for event_ev/promotion_ladder.py utilities."""

    def test_stage_enum_from_str(self):
        assert EventEVPromotionStage.from_str("off") == EventEVPromotionStage.OFF
        assert EventEVPromotionStage.from_str("tiebreaker") == EventEVPromotionStage.TIEBREAKER
        assert EventEVPromotionStage.from_str("rank_overlay") == EventEVPromotionStage.RANK_OVERLAY
        assert EventEVPromotionStage.from_str("sizing_overlay") == EventEVPromotionStage.SIZING_OVERLAY
        assert EventEVPromotionStage.from_str("composite") == EventEVPromotionStage.COMPOSITE
        assert EventEVPromotionStage.from_str("unknown") == EventEVPromotionStage.OFF

    def test_stage_ordering(self):
        assert EventEVPromotionStage.OFF < EventEVPromotionStage.TIEBREAKER
        assert EventEVPromotionStage.TIEBREAKER < EventEVPromotionStage.RANK_OVERLAY
        assert EventEVPromotionStage.RANK_OVERLAY < EventEVPromotionStage.SIZING_OVERLAY
        assert EventEVPromotionStage.SIZING_OVERLAY < EventEVPromotionStage.COMPOSITE

    def test_classify_ev_bucket(self):
        assert classify_ev_bucket(5.0) == "high_ev"
        assert classify_ev_bucket(1.0) == "mid_ev"
        assert classify_ev_bucket(-2.0) == "low_ev"
        assert classify_ev_bucket(None) == "no_ev"
        assert classify_ev_bucket(3.0) == "high_ev"  # at boundary
        assert classify_ev_bucket(-1.0) == "low_ev"  # at boundary

    def test_classify_ev_bucket_custom_thresholds(self):
        assert classify_ev_bucket(2.0, high_threshold=5.0) == "mid_ev"
        assert classify_ev_bucket(6.0, high_threshold=5.0) == "high_ev"
        assert classify_ev_bucket(0.0, low_threshold=0.5) == "low_ev"

    def test_compute_cohort_ev_z_scores_basic(self):
        lookup = {
            "AAAA": {"event_ev_score": 10.0},
            "BBBB": {"event_ev_score": 5.0},
            "CCCC": {"event_ev_score": 0.0},
        }
        z = compute_cohort_ev_z_scores(lookup)
        assert "AAAA" in z
        assert "BBBB" in z
        assert "CCCC" in z
        # AAAA should have highest z, CCCC lowest
        assert z["AAAA"] > z["BBBB"] > z["CCCC"]

    def test_compute_cohort_ev_z_scores_single_ticker(self):
        """Single ticker → raw score returned (can't z-score)."""
        lookup = {"AAAA": {"event_ev_score": 5.0}}
        z = compute_cohort_ev_z_scores(lookup)
        assert z["AAAA"] == 5.0

    def test_compute_cohort_ev_z_scores_missing_scores(self):
        """None scores are excluded from z-scoring."""
        lookup = {
            "AAAA": {"event_ev_score": 10.0},
            "BBBB": {"event_ev_score": None},
        }
        z = compute_cohort_ev_z_scores(lookup)
        assert "AAAA" in z
        assert "BBBB" not in z

    def test_load_event_ev_missing_dir(self):
        """No artifacts → empty result."""
        result = load_event_ev_for_cohort(
            as_of_date=__import__("datetime").date(2026, 4, 8),
            tickers=["AAAA"],
            artifacts_dir=Path("/nonexistent/path"),
        )
        assert result == {}

    def test_evaluate_ev_readiness_empty_dir(self):
        """Empty artifacts dir → no stages ready."""
        with tempfile.TemporaryDirectory() as td:
            result = evaluate_ev_readiness(artifacts_dir=Path(td))
            assert result["tiebreaker"]["ready"] is False
            assert result["composite"]["ready"] is False
            assert "off" in result["summary"]

    def test_evaluate_ev_readiness_with_artifacts(self):
        """Sufficient artifacts → tiebreaker ready."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            # Create 10 daily artifact files
            import datetime

            base = datetime.date(2026, 4, 1)
            for i in range(10):
                d = base + datetime.timedelta(days=i)
                artifact = [
                    {"node": {"ticker": "AAAA"}, "payoff": {"downside_adjusted_ev": 5.0, "analog_confidence": "ok"}},
                    {"node": {"ticker": "BBBB"}, "payoff": {"downside_adjusted_ev": 2.0, "analog_confidence": "ok"}},
                ]
                fpath = td_path / f"{d.isoformat()}_event_ev_scores.json"
                with open(fpath, "w") as f:
                    json.dump(artifact, f)

            result = evaluate_ev_readiness(artifacts_dir=td_path, min_days_tiebreaker=5)
            assert result["tiebreaker"]["ready"] is True
            assert result["rank_overlay"]["ready"] is False  # need 15 days
