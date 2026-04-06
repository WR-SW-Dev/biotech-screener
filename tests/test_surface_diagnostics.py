"""Tests for Spec 059 Phase C — Surface Diagnostics & Anomaly Detection.

Tests written BEFORE implementation per spec template.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

# ============================================================================
# Fixtures
# ============================================================================


def _make_surface_row(
    ticker: str = "ACAD",
    front_iv: float = 1.10,
    back_iv: float = 0.70,
    atm_iv: float = 0.90,
    catalyst_days: int = 14,
    event_family: str = "CLINICAL",
    liquidity: str = "liquid",
    **kwargs,
) -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "opt_front_iv": front_iv,
        "opt_back_iv": back_iv,
        "opt_atm_iv": atm_iv,
        "opt_term_slope": (back_iv - front_iv) / front_iv if front_iv > 0 else 0,
        "opt_rr_25d": kwargs.get("rr_25d", -0.05),
        "opt_event_premium": "YES" if front_iv > back_iv else "NO",
        "opt_liquidity_state": liquidity,
        "catalyst_days": catalyst_days,
        "event_family": event_family,
        "implied_event_move": kwargs.get("implied_move", front_iv * math.sqrt(catalyst_days / 365) * 0.8),
    }


def _cross_section() -> List[Dict[str, Any]]:
    """Build a cross-section of 10 names with varying surface states."""
    rows = [
        # Normal names
        _make_surface_row("ACAD", front_iv=0.80, back_iv=0.70, atm_iv=0.75, catalyst_days=30),
        _make_surface_row("IONS", front_iv=0.85, back_iv=0.72, atm_iv=0.78, catalyst_days=25),
        _make_surface_row("ALKS", front_iv=0.90, back_iv=0.75, atm_iv=0.82, catalyst_days=20),
        _make_surface_row("SRPT", front_iv=0.82, back_iv=0.68, atm_iv=0.75, catalyst_days=35),
        _make_surface_row("BMRN", front_iv=0.78, back_iv=0.70, atm_iv=0.74, catalyst_days=40),
        _make_surface_row("JAZZ", front_iv=0.75, back_iv=0.65, atm_iv=0.70, catalyst_days=28),
        _make_surface_row("INCY", front_iv=0.88, back_iv=0.72, atm_iv=0.80, catalyst_days=22),
        _make_surface_row("UTHR", front_iv=0.70, back_iv=0.60, atm_iv=0.65, catalyst_days=45),
        # Extreme backwardation — event loaded
        _make_surface_row("PVLA", front_iv=1.80, back_iv=0.60, atm_iv=1.20, catalyst_days=7),
        # Contango near event — unusual
        _make_surface_row("CELC", front_iv=0.50, back_iv=0.80, atm_iv=0.65, catalyst_days=5),
    ]
    return rows


# ============================================================================
# Test: Surface Anomaly Detection
# ============================================================================


class TestSurfaceAnomalyDetector:
    def test_detects_extreme_backwardation(self):
        from event_ev.surface_diagnostics import detect_surface_anomalies

        rows = _cross_section()
        anomalies = detect_surface_anomalies(rows)
        # PVLA (front=1.80, back=0.60) should be flagged
        pvla = [a for a in anomalies if a["ticker"] == "PVLA"]
        assert len(pvla) == 1
        assert "backwardation_extreme" in pvla[0]["flags"]

    def test_detects_contango_near_event(self):
        from event_ev.surface_diagnostics import detect_surface_anomalies

        rows = _cross_section()
        anomalies = detect_surface_anomalies(rows)
        # CELC (front=0.50, back=0.80, catalyst_days=5) should be flagged
        celc = [a for a in anomalies if a["ticker"] == "CELC"]
        assert len(celc) == 1
        assert "contango_near_event" in celc[0]["flags"]

    def test_normal_names_not_flagged(self):
        from event_ev.surface_diagnostics import detect_surface_anomalies

        rows = _cross_section()
        anomalies = detect_surface_anomalies(rows)
        flagged_tickers = {a["ticker"] for a in anomalies}
        # Normal names should not be in anomalies
        assert "BMRN" not in flagged_tickers
        assert "UTHR" not in flagged_tickers

    def test_illiquid_excluded(self):
        from event_ev.surface_diagnostics import detect_surface_anomalies

        rows = [_make_surface_row("THIN", front_iv=2.0, back_iv=0.50, liquidity="thin")]
        anomalies = detect_surface_anomalies(rows)
        assert len(anomalies) == 0

    def test_empty_input(self):
        from event_ev.surface_diagnostics import detect_surface_anomalies

        assert detect_surface_anomalies([]) == []

    def test_anomaly_has_epr_z(self):
        """Each anomaly should include the cross-sectional z-score of event premium ratio."""
        from event_ev.surface_diagnostics import detect_surface_anomalies

        rows = _cross_section()
        anomalies = detect_surface_anomalies(rows)
        for a in anomalies:
            assert "epr_z" in a
            assert isinstance(a["epr_z"], float)


# ============================================================================
# Test: Term Structure Shape Classification
# ============================================================================


class TestTermStructureShape:
    def test_backwardation_extreme(self):
        from event_ev.surface_diagnostics import classify_term_structure

        shape = classify_term_structure(front_iv=1.80, back_iv=0.60, catalyst_days=7)
        assert shape == "backwardation_extreme"

    def test_backwardation_normal(self):
        from event_ev.surface_diagnostics import classify_term_structure

        shape = classify_term_structure(front_iv=0.90, back_iv=0.75, catalyst_days=20)
        assert shape == "backwardation"

    def test_contango_near_event(self):
        from event_ev.surface_diagnostics import classify_term_structure

        shape = classify_term_structure(front_iv=0.50, back_iv=0.80, catalyst_days=5)
        assert shape == "contango_near_event"

    def test_contango_far_event(self):
        """Contango far from event is normal — just not event-loaded."""
        from event_ev.surface_diagnostics import classify_term_structure

        shape = classify_term_structure(front_iv=0.50, back_iv=0.80, catalyst_days=90)
        assert shape == "contango"

    def test_flat_high(self):
        from event_ev.surface_diagnostics import classify_term_structure

        shape = classify_term_structure(front_iv=1.20, back_iv=1.15, catalyst_days=14)
        assert shape == "flat_high"

    def test_flat_low(self):
        from event_ev.surface_diagnostics import classify_term_structure

        shape = classify_term_structure(front_iv=0.30, back_iv=0.28, catalyst_days=14)
        assert shape == "flat_low"

    def test_invalid_inputs(self):
        from event_ev.surface_diagnostics import classify_term_structure

        assert classify_term_structure(0, 0.5, 14) is None
        assert classify_term_structure(0.5, 0, 14) is None
        assert classify_term_structure(0.5, 0.5, 0) is None


# ============================================================================
# Test: Historical Comparison
# ============================================================================


class TestHistoricalComparison:
    def test_computes_percentiles(self):
        from event_ev.surface_diagnostics import compare_to_history

        history = [
            {"atm_iv": 0.60, "event_premium_ratio": 1.05},
            {"atm_iv": 0.70, "event_premium_ratio": 1.10},
            {"atm_iv": 0.80, "event_premium_ratio": 1.15},
            {"atm_iv": 0.90, "event_premium_ratio": 1.20},
            {"atm_iv": 1.00, "event_premium_ratio": 1.25},
        ]
        result = compare_to_history(
            current_atm_iv=0.95,
            current_epr=1.22,
            history=history,
        )
        assert result is not None
        assert "atm_iv_pctile" in result
        assert "epr_pctile" in result
        # 0.95 is between 4th and 5th observation → high percentile
        assert result["atm_iv_pctile"] > 0.5
        # 1.22 is between 4th and 5th → high percentile
        assert result["epr_pctile"] > 0.5

    def test_insufficient_history(self):
        from event_ev.surface_diagnostics import compare_to_history

        result = compare_to_history(
            current_atm_iv=0.90,
            current_epr=1.15,
            history=[{"atm_iv": 0.80, "event_premium_ratio": 1.10}],
        )
        assert result is None


# ============================================================================
# Test: Belief Intensity Modifier
# ============================================================================


class TestBeliefIntensityModifier:
    def test_extreme_backwardation_increases_intensity(self):
        from event_ev.surface_diagnostics import compute_belief_intensity_modifier

        modifier = compute_belief_intensity_modifier(
            term_shape="backwardation_extreme",
            epr_z=2.5,
        )
        assert modifier > 1.0  # increases conviction

    def test_contango_near_event_decreases_intensity(self):
        from event_ev.surface_diagnostics import compute_belief_intensity_modifier

        modifier = compute_belief_intensity_modifier(
            term_shape="contango_near_event",
            epr_z=-1.5,
        )
        assert modifier < 1.0  # decreases conviction

    def test_normal_surface_neutral(self):
        from event_ev.surface_diagnostics import compute_belief_intensity_modifier

        modifier = compute_belief_intensity_modifier(
            term_shape="backwardation",
            epr_z=0.3,
        )
        assert modifier == pytest.approx(1.0, abs=0.1)

    def test_modifier_bounded(self):
        """Modifier should be bounded to prevent extreme adjustments."""
        from event_ev.surface_diagnostics import compute_belief_intensity_modifier

        high = compute_belief_intensity_modifier("backwardation_extreme", epr_z=5.0)
        low = compute_belief_intensity_modifier("contango_near_event", epr_z=-5.0)
        assert 0.5 <= low <= 1.5
        assert 0.5 <= high <= 1.5
