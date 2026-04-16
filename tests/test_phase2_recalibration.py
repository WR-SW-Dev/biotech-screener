"""Tests for Phase 2 prior recalibration.

Verifies:
  - Phase 2 prior is recalibrated to 0.420
  - Phase 1 and Phase 3 priors are unchanged
  - Outcome model uses the new prior for Phase 2 events
  - Old prior values preserved for comparison
  - CRT calibration still excluded for Phase 2 (Herald bias)
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
        "phase": "2",
        "indication": "oncology",
    }
    defaults.update(overrides)
    return CatalystNode(**defaults)


class TestPhase2PriorValue:

    def test_phase_2_prior_recalibrated(self):
        from event_ev.outcome_model import LITERATURE_PHASE_READOUT_PRIORS

        assert LITERATURE_PHASE_READOUT_PRIORS["2"] == 0.420

    def test_phase_1_prior_unchanged(self):
        from event_ev.outcome_model import LITERATURE_PHASE_READOUT_PRIORS

        assert LITERATURE_PHASE_READOUT_PRIORS["1"] == 0.630

    def test_phase_3_prior_unchanged(self):
        from event_ev.outcome_model import LITERATURE_PHASE_READOUT_PRIORS

        assert LITERATURE_PHASE_READOUT_PRIORS["3"] == 0.580

    def test_old_values_preserved(self):
        from event_ev.outcome_model import _PHASE_2_PRIOR_AGGRESSIVE, _PHASE_2_PRIOR_NEW, _PHASE_2_PRIOR_OLD

        assert _PHASE_2_PRIOR_OLD == 0.310
        assert _PHASE_2_PRIOR_NEW == 0.420
        assert _PHASE_2_PRIOR_AGGRESSIVE == 0.492


class TestPhase2OutcomeModel:

    def test_phase2_p_hit_higher_than_old(self):
        from event_ev.outcome_model import OutcomeModel

        # New model (0.420)
        new_model = OutcomeModel()
        node = _make_node(phase="2")
        new_result = new_model.estimate(node, date(2026, 4, 15))

        # Old model (0.310)
        old_priors = dict(new_model.phase_readout_priors)
        old_priors["2"] = 0.310
        old_model = OutcomeModel(phase_readout_priors=old_priors)
        old_result = old_model.estimate(node, date(2026, 4, 15))

        assert new_result.p_hit > old_result.p_hit

    def test_phase2_prior_source(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        node = _make_node(phase="2")
        result = model.estimate(node, date(2026, 4, 15))

        assert result.prior_source == "literature_phase_readout"

    def test_phase3_unchanged(self):
        from event_ev.outcome_model import OutcomeModel

        model = OutcomeModel()
        node = _make_node(phase="3")
        result = model.estimate(node, date(2026, 4, 15))

        # Phase 3 prior = 0.580, should not have changed
        prior = result.features_used.get("prior_p_hit")
        assert abs(prior - 0.580) < 0.001

    def test_crt_still_excluded_for_phase2(self):
        """Phase 2 is Herald-biased — CRT calibration must NOT override."""
        from event_ev.outcome_model import HERALD_BIASED_PHASES

        assert "2" in HERALD_BIASED_PHASES
