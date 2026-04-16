"""Tests for clinical-to-p_hit transmission layer.

Verifies that protocol/biomarker/endpoint scores transmit through
the outcome model into p_hit adjustments in a bounded, phase-aware way.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def _make_node(**overrides: Any):
    from event_ev.data_contracts import CatalystNode

    defaults = {
        "ticker": "TEST",
        "event_family": "CLINICAL",
        "event_type": "DATA_READOUT",
        "event_subtype": "TOPLINE",
        "expected_date": "2026-06-15",
        "date_range_start": "2026-06-15",
        "date_range_end": None,
        "date_precision": "MONTH",
        "date_confidence": 0.6,
        "source": "CTGOV",
        "source_uid": "NCT_TEST",
        "disclosed_at": "2026-01-15",
        "phase": "3",
        "indication": "oncology",
    }
    defaults.update(overrides)
    return CatalystNode(**defaults)


class TestTransmissionAffectsPHit:

    def test_strong_clinical_boosts_phit(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        node = _make_node(phase="3")

        base = model.estimate(node, date(2026, 4, 15), {})
        boosted = model.estimate(
            node,
            date(2026, 4, 15),
            {
                "protocol_quality_score": 0.85,
                "endpoint_quality_score": 0.95,
                "biomarker_context_score": 0.25,
            },
        )

        assert boosted.p_hit > base.p_hit

    def test_weak_clinical_lowers_phit(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        node = _make_node(phase="3")

        base = model.estimate(node, date(2026, 4, 15), {})
        weak = model.estimate(
            node,
            date(2026, 4, 15),
            {
                "protocol_quality_score": 0.10,
                "endpoint_quality_score": 0.05,
                "biomarker_context_score": 0.0,
            },
        )

        assert weak.p_hit < base.p_hit

    def test_transmission_in_features_used(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        node = _make_node(phase="2")
        result = model.estimate(
            node,
            date(2026, 4, 15),
            {
                "protocol_quality_score": 0.70,
                "endpoint_quality_score": 0.80,
            },
        )

        tx = result.features_used.get("clinical_transmission", {})
        assert "tx_clamped" in tx
        updates = result.features_used.get("log_odds_updates", {})
        assert "clinical_transmission" in updates


class TestPhaseAwareCaps:

    def test_phase1_has_tighter_cap(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        strong_ctx = {
            "protocol_quality_score": 0.90,
            "endpoint_quality_score": 0.95,
            "biomarker_context_score": 0.30,
        }

        node_p1 = _make_node(phase="1")
        node_p2 = _make_node(phase="2")

        r1 = model.estimate(node_p1, date(2026, 4, 15), strong_ctx)
        r2 = model.estimate(node_p2, date(2026, 4, 15), strong_ctx)

        tx1 = r1.features_used.get("clinical_transmission", {}).get("tx_clamped", 0)
        tx2 = r2.features_used.get("clinical_transmission", {}).get("tx_clamped", 0)

        # Phase 2 cap (0.25) is higher than Phase 1 cap (0.12)
        assert abs(tx2) >= abs(tx1) or (abs(tx1) < 0.13 and abs(tx2) < 0.26)

    def test_no_clinical_scores_no_transmission(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        node = _make_node(phase="3")
        result = model.estimate(node, date(2026, 4, 15), {})

        tx = result.features_used.get("clinical_transmission", {})
        assert tx.get("tx_clamped", 0) == 0 or "tx_clamped" not in tx


class TestSignSymmetry:

    def test_positive_and_negative_possible(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        node = _make_node(phase="3")

        pos = model.estimate(
            node,
            date(2026, 4, 15),
            {
                "protocol_quality_score": 0.90,
                "endpoint_quality_score": 0.95,
            },
        )
        neg = model.estimate(
            node,
            date(2026, 4, 15),
            {
                "protocol_quality_score": 0.10,
                "endpoint_quality_score": 0.05,
            },
        )

        tx_pos = pos.features_used.get("clinical_transmission", {}).get("tx_clamped", 0)
        tx_neg = neg.features_used.get("clinical_transmission", {}).get("tx_clamped", 0)

        assert tx_pos > 0
        assert tx_neg < 0
