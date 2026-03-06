"""Unit tests for internal helper functions in module_3_scoring.py.

Covers: _proximity_time_weight, compute_velocity,
_compute_catalyst_confidence, _select_top_3_events.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from module_3_scoring import (
    _proximity_time_weight,
    compute_velocity,
    _compute_catalyst_confidence,
    _select_top_3_events,
)
from module_3_schema import (
    CatalystEventV2,
    EventType,
    EventSeverity,
    ConfidenceLevel,
)


def _make_event(
    ticker="ACME",
    event_date="2026-03-15",
    event_type=EventType.CT_STATUS_UPGRADE,
    severity=EventSeverity.POSITIVE,
    confidence=ConfidenceLevel.HIGH,
    **kwargs,
) -> CatalystEventV2:
    """Helper to create a CatalystEventV2 with sensible defaults."""
    return CatalystEventV2(
        ticker=ticker,
        nct_id="NCT00000001",
        event_type=event_type,
        event_severity=severity,
        event_date=event_date,
        field_changed="overall_status",
        prior_value="Recruiting",
        new_value="Completed",
        source="ctgov",
        confidence=confidence,
        disclosed_at="2026-03-01",
        **kwargs,
    )


# =============================================================================
# _proximity_time_weight — piecewise-linear kernel
# =============================================================================

class TestProximityTimeWeight:
    def test_past_event_zero(self):
        assert _proximity_time_weight(-5) == Decimal("0")

    def test_same_day_zero(self):
        assert _proximity_time_weight(0) == Decimal("0")

    def test_ramp_start(self):
        """d=1 → 1/15."""
        result = _proximity_time_weight(1)
        expected = Decimal("1") / Decimal("15")
        assert abs(result - expected) < Decimal("0.001")

    def test_ramp_end(self):
        """d=15 → 1.0 (end of ramp)."""
        assert _proximity_time_weight(15) == Decimal("1")

    def test_plateau(self):
        """15 < d <= 45 → 1.0."""
        assert _proximity_time_weight(30) == Decimal("1")
        assert _proximity_time_weight(45) == Decimal("1")

    def test_decay_midpoint(self):
        """d=67.5 (midpoint of 45-90 decay) → ~0.5."""
        result = _proximity_time_weight(67)
        assert Decimal("0.4") < result < Decimal("0.6")

    def test_near_horizon(self):
        """d=89 → small positive value."""
        result = _proximity_time_weight(89)
        assert result > Decimal("0")
        assert result < Decimal("0.1")

    def test_at_horizon(self):
        """d=90 → 0."""
        assert _proximity_time_weight(90) == Decimal("0")

    def test_beyond_horizon(self):
        """d=180 → 0."""
        assert _proximity_time_weight(180) == Decimal("0")

    def test_monotonic_ramp(self):
        """Values increase from d=1 to d=15."""
        prev = _proximity_time_weight(1)
        for d in range(2, 16):
            curr = _proximity_time_weight(d)
            assert curr >= prev, f"Not monotonic at d={d}"
            prev = curr

    def test_monotonic_decay(self):
        """Values decrease from d=45 to d=90."""
        prev = _proximity_time_weight(45)
        for d in range(46, 91):
            curr = _proximity_time_weight(d)
            assert curr <= prev, f"Not monotonic at d={d}"
            prev = curr


# =============================================================================
# compute_velocity
# =============================================================================

class TestComputeVelocity:
    def test_insufficient_history_returns_none(self):
        assert compute_velocity(Decimal("0.5"), [Decimal("0.4"), Decimal("0.3")]) is None
        assert compute_velocity(Decimal("0.5"), []) is None

    def test_exactly_4_history(self):
        hist = [Decimal("0.4"), Decimal("0.5"), Decimal("0.3"), Decimal("0.6")]
        result = compute_velocity(Decimal("0.7"), hist)
        assert result is not None
        # median of [0.3, 0.4, 0.5, 0.6] = (0.4 + 0.5) / 2 = 0.45
        assert result == Decimal("0.25")  # 0.7 - 0.45

    def test_positive_velocity(self):
        hist = [Decimal("0.2"), Decimal("0.2"), Decimal("0.2"), Decimal("0.2")]
        result = compute_velocity(Decimal("0.5"), hist)
        assert result > Decimal("0")

    def test_negative_velocity(self):
        hist = [Decimal("0.8"), Decimal("0.8"), Decimal("0.8"), Decimal("0.8")]
        result = compute_velocity(Decimal("0.3"), hist)
        assert result < Decimal("0")

    def test_zero_velocity_when_equal(self):
        hist = [Decimal("0.5"), Decimal("0.5"), Decimal("0.5"), Decimal("0.5")]
        result = compute_velocity(Decimal("0.5"), hist)
        assert result == Decimal("0")

    def test_uses_only_first_4(self):
        hist = [Decimal("0.4"), Decimal("0.4"), Decimal("0.4"), Decimal("0.4"),
                Decimal("99"), Decimal("99")]
        result = compute_velocity(Decimal("0.5"), hist)
        assert result == Decimal("0.10")  # 0.5 - 0.4


# =============================================================================
# _compute_catalyst_confidence
# =============================================================================

class TestComputeCatalystConfidence:
    def test_no_next_date_returns_med(self):
        events = [_make_event()]
        assert _compute_catalyst_confidence(events, None) == ConfidenceLevel.MED

    def test_matching_high_confidence(self):
        events = [_make_event(event_date="2026-04-01", confidence=ConfidenceLevel.HIGH)]
        result = _compute_catalyst_confidence(events, "2026-04-01")
        assert result == ConfidenceLevel.HIGH

    def test_multiple_confidences_returns_highest(self):
        events = [
            _make_event(event_date="2026-04-01", confidence=ConfidenceLevel.LOW),
            _make_event(event_date="2026-04-01", confidence=ConfidenceLevel.HIGH),
        ]
        result = _compute_catalyst_confidence(events, "2026-04-01")
        assert result == ConfidenceLevel.HIGH

    def test_no_matching_events_returns_med(self):
        events = [_make_event(event_date="2026-05-01")]
        result = _compute_catalyst_confidence(events, "2026-04-01")
        assert result == ConfidenceLevel.MED


# =============================================================================
# _select_top_3_events
# =============================================================================

class TestSelectTop3Events:
    def test_empty_events(self):
        assert _select_top_3_events([], date(2026, 3, 6)) == []

    def test_fewer_than_3(self):
        events = [_make_event(), _make_event(event_date="2026-03-20")]
        result = _select_top_3_events(events, date(2026, 3, 6))
        assert len(result) == 2

    def test_returns_max_3(self):
        events = [_make_event(event_date=f"2026-03-{10+i:02d}") for i in range(5)]
        result = _select_top_3_events(events, date(2026, 3, 6))
        assert len(result) == 3

    def test_severe_negative_prioritized(self):
        e_positive = _make_event(severity=EventSeverity.POSITIVE, event_date="2026-03-10")
        e_severe = _make_event(severity=EventSeverity.SEVERE_NEGATIVE, event_date="2026-03-20")
        result = _select_top_3_events([e_positive, e_severe], date(2026, 3, 6))
        assert result[0].event_severity == EventSeverity.SEVERE_NEGATIVE

    def test_more_recent_prioritized_within_severity(self):
        e_old = _make_event(event_date="2026-01-01")
        e_new = _make_event(event_date="2026-03-01")
        result = _select_top_3_events([e_old, e_new], date(2026, 3, 6))
        assert result[0].event_date == "2026-03-01"

    def test_higher_confidence_breaks_ties(self):
        e_low = _make_event(event_date="2026-03-01", confidence=ConfidenceLevel.LOW)
        e_high = _make_event(event_date="2026-03-01", confidence=ConfidenceLevel.HIGH)
        result = _select_top_3_events([e_low, e_high], date(2026, 3, 6))
        assert result[0].confidence == ConfidenceLevel.HIGH
