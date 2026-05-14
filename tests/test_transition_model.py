"""Tests for event_ev.transition_model (runway chain Phase 1)."""

import numpy as np
import pytest

from event_ev.transition_model import (
    RUNWAY_STATES,
    STATE_TO_IDX,
    _normalize_transition_matrix,
    _transition_matrix_power,
    enrich_csv_rows,
    label_runway_state,
)


class TestRunwayStateLabeling:
    """Test state label assignment."""

    def test_safe_state(self):
        """Buffer >= 9 months, severity < 0.40 → SAFE."""
        state = label_runway_state(
            runway_buffer_months=10.0,
            months_to_cash_out=20.0,
            ev_severity_score=0.30,
        )
        assert state == STATE_TO_IDX["SAFE"]

    def test_watch_state(self):
        """Buffer 3–9 months → WATCH."""
        state = label_runway_state(
            runway_buffer_months=5.0,
            months_to_cash_out=12.0,
            ev_severity_score=0.40,
        )
        assert state == STATE_TO_IDX["WATCH"]

    def test_stressed_state(self):
        """Buffer 0–3 months → STRESSED."""
        state = label_runway_state(
            runway_buffer_months=1.5,
            months_to_cash_out=8.0,
            ev_severity_score=0.50,
        )
        assert state == STATE_TO_IDX["STRESSED"]

    def test_financing_likely_state(self):
        """Buffer < 0 or severity >= 0.70 → FINANCING_LIKELY."""
        state = label_runway_state(
            runway_buffer_months=-1.0,
            months_to_cash_out=5.0,
            ev_severity_score=0.65,
        )
        assert state == STATE_TO_IDX["FINANCING_LIKELY"]

    def test_distress_state(self):
        """Buffer < 0 AND months < 4 AND severity > 0.80 → DISTRESS."""
        state = label_runway_state(
            runway_buffer_months=-2.0,
            months_to_cash_out=2.0,
            ev_severity_score=0.85,
        )
        assert state == STATE_TO_IDX["DISTRESS"]

    def test_missing_data_defaults_to_watch(self):
        """None values default to WATCH (middle state)."""
        state = label_runway_state(None, None, None)
        assert state == STATE_TO_IDX["WATCH"]


class TestTransitionMatrix:
    """Test transition matrix normalization and powers."""

    def test_normalize_matrix(self):
        """Each row should sum to 1.0."""
        counts = np.array(
            [
                [5, 2, 1, 0, 0],
                [1, 6, 2, 1, 0],
                [0, 1, 8, 2, 1],
                [0, 0, 1, 5, 2],
                [0, 0, 0, 1, 4],
            ],
            dtype=int,
        )

        P = _normalize_transition_matrix(counts)

        assert P.shape == (5, 5)
        for i in range(5):
            assert abs(P[i].sum() - 1.0) < 1e-6, f"Row {i} sum = {P[i].sum()}"

    def test_matrix_power_identity(self):
        """P^0 should be identity, P^1 should be P."""
        P = np.array(
            [
                [0.7, 0.2, 0.1],
                [0.1, 0.8, 0.1],
                [0.2, 0.1, 0.7],
            ]
        )

        P0 = _transition_matrix_power(P, 0)
        assert np.allclose(P0, np.eye(3))

        P1 = _transition_matrix_power(P, 1)
        assert np.allclose(P1, P)

    def test_matrix_power_2(self):
        """P^2 should equal P @ P."""
        P = np.array(
            [
                [0.7, 0.2, 0.1],
                [0.1, 0.8, 0.1],
                [0.2, 0.1, 0.7],
            ]
        )

        P2 = _transition_matrix_power(P, 2)
        P2_expected = P @ P

        assert np.allclose(P2, P2_expected)


class TestEnrichment:
    """Test CSV enrichment pipeline."""

    def test_enrich_csv_rows_adds_columns(self):
        """Enrichment should add transition shadow columns."""
        csv_rows = [
            {
                "ticker": "ABCD",
                "runway_buffer_months": 10.0,
                "months_to_cash_out": 20.0,
                "ev_severity_score": 0.30,
            },
            {
                "ticker": "EFGH",
                "runway_buffer_months": 1.0,
                "months_to_cash_out": 6.0,
                "ev_severity_score": 0.60,
            },
        ]

        overlays = enrich_csv_rows(csv_rows, as_of_date="2026-05-14")

        # Check columns added
        assert "transition_runway_state" in csv_rows[0]
        assert "transition_p_runway_worse_60d" in csv_rows[0]
        assert "transition_p_financing_90d" in csv_rows[0]
        assert "transition_p_distress_90d" in csv_rows[0]

        # Check values are reasonable
        assert csv_rows[0]["transition_runway_state"] == "SAFE"
        assert 0.0 <= csv_rows[0]["transition_p_runway_worse_60d"] <= 1.0
        assert 0.0 <= csv_rows[0]["transition_p_financing_90d"] <= 1.0
        assert 0.0 <= csv_rows[0]["transition_p_distress_90d"] <= 1.0

        # Check overlay objects
        assert len(overlays) == 2
        assert overlays[0].ticker == "ABCD"
        assert overlays[0].current_state == "SAFE"
        assert overlays[0].is_pooled_estimate  # should be True in v0 (no history loading)

    def test_enrich_preserves_original_columns(self):
        """Enrichment should not modify existing columns."""
        original = {
            "ticker": "TEST",
            "price": 45.50,
            "runway_buffer_months": 5.0,
            "months_to_cash_out": 12.0,
            "ev_severity_score": 0.40,
        }
        csv_rows = [original.copy()]

        enrich_csv_rows(csv_rows, as_of_date="2026-05-14")

        assert csv_rows[0]["ticker"] == "TEST"
        assert csv_rows[0]["price"] == 45.50
        assert csv_rows[0]["runway_buffer_months"] == 5.0

    def test_enrich_handles_missing_data(self):
        """Enrichment should handle None/missing values gracefully."""
        csv_rows = [
            {
                "ticker": "SPARSE",
                "runway_buffer_months": None,
                "months_to_cash_out": None,
                "ev_severity_score": None,
            }
        ]

        overlays = enrich_csv_rows(csv_rows, as_of_date="2026-05-14")

        # Should not crash and should emit shadow columns
        assert overlays[0].current_state == "WATCH"  # default state
        assert "transition_runway_state" in csv_rows[0]


class TestPITSafety:
    """Test that model respects PIT safety (no lookahead)."""

    def test_no_future_data_in_v0(self):
        """V0 uses only pooled estimate — no ticker-specific history to lookahead."""
        # In v0, enrich_csv_rows with snap_dir=None should not load any data
        csv_rows = [
            {
                "ticker": "TEST",
                "runway_buffer_months": 5.0,
                "months_to_cash_out": 12.0,
                "ev_severity_score": 0.40,
            }
        ]

        # Calling with snap_dir=None (default) should use only uniform fallback
        overlays = enrich_csv_rows(csv_rows, as_of_date="2026-05-14", snap_dir=None)

        # No lookahead possible with uniform matrix
        assert overlays[0].is_pooled_estimate

    def test_as_of_date_included_in_overlay(self):
        """Overlay should track as_of_date for audit purposes."""
        csv_rows = [
            {
                "ticker": "TEST",
                "runway_buffer_months": 5.0,
                "months_to_cash_out": 12.0,
                "ev_severity_score": 0.40,
            }
        ]

        overlays = enrich_csv_rows(csv_rows, as_of_date="2026-05-14")

        assert overlays[0].as_of_date == "2026-05-14"


class TestMatrixProperties:
    """Test mathematical properties of transition matrices."""

    def test_stochastic_matrix_rows_sum_to_1(self):
        """All rows of a stochastic matrix should sum to 1."""
        counts = np.array(
            [
                [10, 5, 2],
                [3, 12, 5],
                [1, 2, 8],
            ],
            dtype=int,
        )

        P = _normalize_transition_matrix(counts)

        for i in range(P.shape[0]):
            assert abs(P[i].sum() - 1.0) < 1e-9

    def test_ergodic_matrix_converges(self):
        """Ergodic matrix should converge to stationary distribution."""
        # Simple 2-state system with stable transitions
        P = np.array(
            [
                [0.8, 0.2],
                [0.3, 0.7],
            ]
        )

        # High powers should converge
        P_large = _transition_matrix_power(P, 100)

        # Each row should still sum to 1 (stochastic property preserved)
        assert abs(P_large[0].sum() - 1.0) < 1e-9
        assert abs(P_large[1].sum() - 1.0) < 1e-9

        # Successive powers should stabilize (converging behavior)
        P_90 = _transition_matrix_power(P, 90)
        assert np.allclose(P_large, P_90, atol=1e-6)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
