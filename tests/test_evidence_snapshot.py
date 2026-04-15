"""Tests for EventEvidenceSnapshot builder and PIT safety.

Covers:
  - Snapshot construction from trial records + CatalystNode
  - PIT filtering (collected_at / resolution_date gates)
  - Missing-field tolerance (all fields nullable)
  - Designation flag extraction
  - Prior readout counting from CRT
  - Evidence confidence scoring
  - Serialization round-trip
  - Expectation-field verification (short_interest_pct, close_price,
    market_cap_mm, priced_move_pct in feature registry)
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_node(**overrides: Any):
    from event_ev.data_contracts import CatalystNode

    defaults = {
        "ticker": "ACAD",
        "event_family": "CLINICAL",
        "event_type": "DATA_READOUT",
        "event_subtype": "TOPLINE",
        "expected_date": "2026-06-15",
        "date_range_start": "2026-06-15",
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


def _make_trial(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "nct_id": "NCT12345678",
        "ticker": "ACAD",
        "phase": "PHASE3",
        "allocation": "RANDOMIZED",
        "masking": "DOUBLE",
        "intervention_model": "PARALLEL",
        "enrollment": 450,
        "primary_endpoints": ["Overall Survival at 24 months"],
        "status": "ACTIVE_NOT_RECRUITING",
        "study_type": "INTERVENTIONAL",
        "primary_purpose": "TREATMENT",
        "collected_at": "2026-04-01",
        "conditions": ["Non-Small Cell Lung Cancer"],
    }
    defaults.update(overrides)
    return defaults


def _make_resolution(**overrides: Any) -> Dict[str, Any]:
    defaults = {
        "ticker": "ACAD",
        "catalyst_date": "2025-11-15",
        "catalyst_type": "PHASE_3_READOUT",
        "resolution_date": "2025-11-15",
        "outcome": "HIT",
        "outcome_detail": "Met primary endpoint",
        "source_type": "PRESS_RELEASE",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Core construction
# ---------------------------------------------------------------------------


class TestEvidenceSnapshotConstruction:

    def test_full_trial_match(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id="NCT12345678")
        trial = _make_trial()
        snap = build_evidence_snapshot(node, date(2026, 4, 15), [trial])

        assert snap.node_id == node.node_id
        assert snap.as_of_date == "2026-04-15"
        assert snap.phase == "3"
        assert snap.randomized_flag is True
        assert snap.blinded_flag is True
        assert snap.control_arm_flag is True
        assert snap.enrollment_n == 450
        assert snap.primary_endpoint_text == "Overall Survival at 24 months"
        assert snap.endpoint_type == "SURVIVAL"
        assert snap.ctgov_study_id == "NCT12345678"
        assert "ctgov:NCT12345678" in snap.source_refs

    def test_no_trial_match(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id=None)
        snap = build_evidence_snapshot(node, date(2026, 4, 15), [])

        assert snap.randomized_flag is None
        assert snap.blinded_flag is None
        assert snap.enrollment_n is None
        assert snap.phase == "3"  # falls back to node phase

    def test_all_fields_nullable(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id=None, designations=[])
        snap = build_evidence_snapshot(node, date(2026, 4, 15))

        # Should not raise — all fields nullable
        d = snap.to_dict()
        assert d["randomized_flag"] is None
        assert d["orphan_flag"] is None
        assert d["literature_support_score"] is None
        assert d["prior_positive_readouts_n"] is None

    def test_frozen(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        snap = build_evidence_snapshot(_make_node(), date(2026, 4, 15))
        with pytest.raises(AttributeError):
            snap.phase = "2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PIT safety
# ---------------------------------------------------------------------------


class TestPITSafety:

    def test_trial_pit_filtered_by_collected_at(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id="NCT12345678")
        future_trial = _make_trial(collected_at="2026-05-01")
        snap = build_evidence_snapshot(node, date(2026, 4, 15), [future_trial])

        # Future trial should not match
        assert snap.randomized_flag is None

    def test_trial_pit_passes_when_collected_before_as_of(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id="NCT12345678")
        past_trial = _make_trial(collected_at="2026-03-01")
        snap = build_evidence_snapshot(node, date(2026, 4, 15), [past_trial])

        assert snap.randomized_flag is True

    def test_crt_resolution_pit_filtered(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node()
        future_res = _make_resolution(resolution_date="2026-05-01")
        snap = build_evidence_snapshot(node, date(2026, 4, 15), crt_resolutions=[future_res])

        assert snap.prior_positive_readouts_n is None

    def test_crt_resolution_pit_passes(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node()
        past_res = _make_resolution(resolution_date="2025-11-15", outcome="HIT")
        snap = build_evidence_snapshot(node, date(2026, 4, 15), crt_resolutions=[past_res])

        assert snap.prior_positive_readouts_n == 1
        assert snap.prior_negative_readouts_n == 0


# ---------------------------------------------------------------------------
# Designation flags
# ---------------------------------------------------------------------------


class TestDesignationFlags:

    def test_orphan_flag(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(designations=["ODD", "FT"])
        snap = build_evidence_snapshot(node, date(2026, 4, 15))

        assert snap.orphan_flag is True
        assert snap.fast_track_flag is True
        assert snap.breakthrough_flag is False

    def test_breakthrough_flag(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(designations=["BTD"])
        snap = build_evidence_snapshot(node, date(2026, 4, 15))

        assert snap.breakthrough_flag is True
        assert snap.orphan_flag is False

    def test_empty_designations(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(designations=[])
        snap = build_evidence_snapshot(node, date(2026, 4, 15))

        assert snap.orphan_flag is None
        assert snap.fast_track_flag is None
        assert snap.breakthrough_flag is None


# ---------------------------------------------------------------------------
# Prior readout counting
# ---------------------------------------------------------------------------


class TestPriorReadoutCounting:

    def test_multiple_resolutions(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node()
        resolutions = [
            _make_resolution(resolution_date="2025-06-01", outcome="HIT"),
            _make_resolution(resolution_date="2025-09-01", outcome="MISS"),
            _make_resolution(resolution_date="2025-11-15", outcome="HIT"),
        ]
        snap = build_evidence_snapshot(node, date(2026, 4, 15), crt_resolutions=resolutions)

        assert snap.prior_positive_readouts_n == 2
        assert snap.prior_negative_readouts_n == 1

    def test_no_resolutions_returns_none(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node()
        snap = build_evidence_snapshot(node, date(2026, 4, 15), crt_resolutions=[])

        assert snap.prior_positive_readouts_n is None
        assert snap.prior_negative_readouts_n is None

    def test_different_ticker_excluded(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(ticker="ACAD")
        resolutions = [
            _make_resolution(ticker="XYZZ", resolution_date="2025-06-01", outcome="HIT"),
        ]
        snap = build_evidence_snapshot(node, date(2026, 4, 15), crt_resolutions=resolutions)

        assert snap.prior_positive_readouts_n is None


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


class TestEvidenceConfidence:

    def test_full_evidence(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id="NCT12345678", designations=["BTD"])
        trial = _make_trial()
        resolutions = [_make_resolution()]
        snap = build_evidence_snapshot(node, date(2026, 4, 15), [trial], resolutions)

        # trial (0.35) + nct_id (0.10) + designations (0.20) + crt (0.20) = 0.85
        # (literature not provided → 0.85 out of 1.0)
        assert snap.evidence_confidence == 0.85

    def test_full_evidence_with_literature(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id="NCT12345678", designations=["BTD"])
        trial = _make_trial()
        resolutions = [_make_resolution()]
        snap = build_evidence_snapshot(
            node,
            date(2026, 4, 15),
            [trial],
            resolutions,
            literature_scores={"ACAD": 0.5},
        )

        # trial (0.35) + nct_id (0.10) + designations (0.20) + crt (0.20) + lit (0.15) = 1.0
        assert snap.evidence_confidence == 1.0

    def test_trial_only(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id="NCT12345678", designations=[])
        trial = _make_trial()
        snap = build_evidence_snapshot(node, date(2026, 4, 15), [trial])

        # trial (0.35) + nct_id (0.10) = 0.45
        assert snap.evidence_confidence == 0.45

    def test_no_evidence(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id=None, designations=[])
        snap = build_evidence_snapshot(node, date(2026, 4, 15))

        assert snap.evidence_confidence == 0.0


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:

    def test_to_dict_round_trip(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id="NCT12345678", designations=["ODD"])
        trial = _make_trial()
        snap = build_evidence_snapshot(node, date(2026, 4, 15), [trial])
        d = snap.to_dict()

        assert d["node_id"] == snap.node_id
        assert d["randomized_flag"] is True
        assert d["orphan_flag"] is True
        assert d["model_version"] == "evidence_v1.0"

    def test_field_coverage(self):
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node(nct_id="NCT12345678", designations=["ODD"])
        trial = _make_trial()
        snap = build_evidence_snapshot(node, date(2026, 4, 15), [trial])

        # Most fields populated with trial + designations
        assert snap.field_coverage > 0.5


# ---------------------------------------------------------------------------
# Batch builder
# ---------------------------------------------------------------------------


class TestBatchBuilder:

    def test_build_multiple_nodes(self):
        from event_ev.evidence_snapshot import build_evidence_snapshots

        nodes = [
            _make_node(ticker="ACAD", nct_id="NCT12345678"),
            _make_node(ticker="PVLA", nct_id=None, source_uid="pdufa_1"),
        ]
        trials = [_make_trial(ticker="ACAD", nct_id="NCT12345678")]
        result = build_evidence_snapshots(nodes, date(2026, 4, 15), trials)

        assert len(result) == 2
        assert all(s.as_of_date == "2026-04-15" for s in result.values())


# ---------------------------------------------------------------------------
# Expectation field verification
# ---------------------------------------------------------------------------


class TestExpectationFieldsInRegistry:
    """Verify the four newly wired expectation fields are in the feature registry."""

    def test_short_interest_pct_in_registry(self):
        from common.feature_registry import FEATURE_REGISTRY

        names = {f.name for f in FEATURE_REGISTRY}
        assert "short_interest_pct" in names

    def test_close_price_in_registry(self):
        from common.feature_registry import FEATURE_REGISTRY

        names = {f.name for f in FEATURE_REGISTRY}
        assert "close_price" in names

    def test_market_cap_mm_in_registry(self):
        from common.feature_registry import FEATURE_REGISTRY

        names = {f.name for f in FEATURE_REGISTRY}
        assert "market_cap_mm" in names

    def test_priced_move_pct_in_registry(self):
        from common.feature_registry import FEATURE_REGISTRY

        names = {f.name for f in FEATURE_REGISTRY}
        assert "priced_move_pct" in names

    def test_coinvest_still_in_registry(self):
        """Guard: coinvest_score_z must NOT be removed from the expectation model."""
        from common.feature_registry import FEATURE_REGISTRY

        names = {f.name for f in FEATURE_REGISTRY}
        assert "coinvest_score_z" in names

    def test_inst_delta_still_in_registry(self):
        """Guard: inst_delta_z must NOT be removed from the expectation model."""
        from common.feature_registry import FEATURE_REGISTRY

        names = {f.name for f in FEATURE_REGISTRY}
        assert "inst_delta_z" in names

    def test_insider_not_blocking(self):
        """insider_net_buy_value_90d should NOT be in the registry (lane closed)."""
        from common.feature_registry import FEATURE_REGISTRY

        names = {f.name for f in FEATURE_REGISTRY}
        assert "insider_net_buy_value_90d" not in names


# ---------------------------------------------------------------------------
# Expectation model guard tests
# ---------------------------------------------------------------------------


class TestExpectationModelPreserved:
    """Guard: the expectation model must retain coinvest and inst_delta as dominant features."""

    def test_coinvest_weight_dominant(self):
        from event_ev.expectation_model import _DEFAULT_FEATURE_WEIGHTS

        assert _DEFAULT_FEATURE_WEIGHTS.get("coinvest_score_z", 0) >= 0.20

    def test_inst_delta_weight_present(self):
        from event_ev.expectation_model import _DEFAULT_FEATURE_WEIGHTS

        assert _DEFAULT_FEATURE_WEIGHTS.get("inst_delta_z", 0) >= 0.10

    def test_feature_count_unchanged(self):
        from event_ev.expectation_model import _DEFAULT_FEATURE_WEIGHTS

        assert len(_DEFAULT_FEATURE_WEIGHTS) == 8


# ---------------------------------------------------------------------------
# EventEV composite includes evidence
# ---------------------------------------------------------------------------


class TestEventEVEvidenceSlot:

    def test_evidence_in_to_dict(self):
        from event_ev.data_contracts import CrowdBelief, EventEV, OutcomeProbabilities, ScenarioPayoffs, TimingEstimate
        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = _make_node()
        evidence = build_evidence_snapshot(node, date(2026, 4, 15))
        ev = EventEV(
            node=node,
            timing=TimingEstimate(
                node_id=node.node_id,
                as_of_date="2026-04-15",
                prob_on_time=0.7,
                prob_slip=0.2,
                prob_early=0.1,
                expected_delay_days=0,
                median_arrival_days=60,
                hazard_rate=0.01,
            ),
            outcome=OutcomeProbabilities(
                node_id=node.node_id,
                as_of_date="2026-04-15",
                p_hit=0.58,
                p_miss=0.30,
                p_mixed=0.12,
                confidence=0.7,
                prior_source="wong_et_al",
            ),
            expectation=CrowdBelief(
                node_id=node.node_id,
                as_of_date="2026-04-15",
                implied_p_hit=0.55,
                belief_direction="NEUTRAL",
                belief_intensity=0.5,
                priced_move_pct=25.0,
                mispricing_score=0.03,
            ),
            payoff=ScenarioPayoffs(
                node_id=node.node_id,
                as_of_date="2026-04-15",
                upside_hit=20.0,
                downside_miss=-40.0,
                move_mixed=-2.0,
                scenario_ev=3.5,
                asymmetry_ratio=0.5,
                downside_adjusted_ev=1.0,
                kelly_fraction=0.05,
                analog_count=50,
                analog_confidence="ok",
            ),
            evidence=evidence,
        )

        d = ev.to_dict()
        assert "evidence" in d
        assert d["evidence"]["node_id"] == node.node_id

    def test_evidence_none_not_in_dict(self):
        from event_ev.data_contracts import CrowdBelief, EventEV, OutcomeProbabilities, ScenarioPayoffs, TimingEstimate

        node = _make_node()
        ev = EventEV(
            node=node,
            timing=TimingEstimate(
                node_id=node.node_id,
                as_of_date="2026-04-15",
                prob_on_time=0.7,
                prob_slip=0.2,
                prob_early=0.1,
                expected_delay_days=0,
                median_arrival_days=60,
                hazard_rate=0.01,
            ),
            outcome=OutcomeProbabilities(
                node_id=node.node_id,
                as_of_date="2026-04-15",
                p_hit=0.58,
                p_miss=0.30,
                p_mixed=0.12,
                confidence=0.7,
                prior_source="wong_et_al",
            ),
            expectation=CrowdBelief(
                node_id=node.node_id,
                as_of_date="2026-04-15",
                implied_p_hit=0.55,
                belief_direction="NEUTRAL",
                belief_intensity=0.5,
                priced_move_pct=25.0,
                mispricing_score=0.03,
            ),
            payoff=ScenarioPayoffs(
                node_id=node.node_id,
                as_of_date="2026-04-15",
                upside_hit=20.0,
                downside_miss=-40.0,
                move_mixed=-2.0,
                scenario_ev=3.5,
                asymmetry_ratio=0.5,
                downside_adjusted_ev=1.0,
                kelly_fraction=0.05,
                analog_count=50,
                analog_confidence="ok",
            ),
        )

        d = ev.to_dict()
        assert "evidence" not in d
