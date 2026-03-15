"""Tests for common/options_surface_signals.py (Spec 020)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.options_surface_signals import (
    compute_actual_implied_move_pctile,
    compute_atm_iv_change_5d,
    compute_surface_signal_quality,
    derive_iv_ramp_flag,
    derive_surface_move_extreme,
    enrich_row_with_surface_signals,
)


def _hist(n, base_iv=0.5, base_move=0.05):
    """Generate n historical rows with ascending dates."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "date": f"2026-01-{i + 1:02d}",
                "atm_iv": base_iv + i * 0.001,
                "actual_implied_move": base_move + i * 0.001,
                "rr_25d": 0.0,
            }
        )
    return rows


class TestAtmIvChange5d:
    def test_basic(self):
        hist = _hist(40, base_iv=0.50)
        current_iv = 0.60
        result = compute_atm_iv_change_5d(current_iv, hist, "2026-02-15")
        assert result is not None
        # Change should be current - lag_5 (5th from end)
        lag_iv = hist[-5]["atm_iv"]
        assert abs(result - (current_iv - lag_iv)) < 1e-6

    def test_insufficient_history(self):
        hist = _hist(10)
        result = compute_atm_iv_change_5d(0.55, hist, "2026-02-15")
        assert result is None

    def test_nan_current(self):
        hist = _hist(40)
        result = compute_atm_iv_change_5d(float("nan"), hist, "2026-02-15")
        assert result is None


class TestActualImpliedMovePctile:
    def test_at_exactly_30_rows(self):
        hist = _hist(30, base_move=0.01)
        # Current move higher than all history
        result = compute_actual_implied_move_pctile(0.999, hist, "2026-02-15", min_history_rows=30)
        assert result is not None
        assert result == 1.0

    def test_current_excluded(self):
        hist = _hist(35, base_move=0.01)
        # Add a row at the current date — should be excluded
        hist.append({"date": "2026-02-15", "atm_iv": 0.5, "actual_implied_move": 0.999, "rr_25d": 0.0})
        result = compute_actual_implied_move_pctile(0.02, hist, "2026-02-15", min_history_rows=30)
        assert result is not None
        # Should be a low percentile since 0.02 is near the bottom of 0.01-0.045 range

    def test_insufficient(self):
        hist = _hist(20, base_move=0.01)
        result = compute_actual_implied_move_pctile(0.05, hist, "2026-02-15", min_history_rows=30)
        assert result is None

    def test_nan_current(self):
        hist = _hist(40, base_move=0.01)
        result = compute_actual_implied_move_pctile(float("nan"), hist, "2026-02-15")
        assert result is None


class TestSurfaceMoveExtreme:
    def test_high(self):
        assert derive_surface_move_extreme(0.80) == "high"
        assert derive_surface_move_extreme(0.95) == "high"

    def test_med(self):
        assert derive_surface_move_extreme(0.60) == "med"
        assert derive_surface_move_extreme(0.79) == "med"

    def test_low(self):
        assert derive_surface_move_extreme(0.59) == "low"
        assert derive_surface_move_extreme(0.0) == "low"

    def test_none(self):
        assert derive_surface_move_extreme(None) == ""


class TestIvRampFlag:
    def test_rising(self):
        assert derive_iv_ramp_flag(0.05) == "rising"
        assert derive_iv_ramp_flag(0.15) == "rising"

    def test_flat(self):
        assert derive_iv_ramp_flag(0.049) == "flat"
        assert derive_iv_ramp_flag(-0.049) == "flat"
        assert derive_iv_ramp_flag(0.0) == "flat"

    def test_falling(self):
        assert derive_iv_ramp_flag(-0.05) == "falling"
        assert derive_iv_ramp_flag(-0.20) == "falling"

    def test_none(self):
        assert derive_iv_ramp_flag(None) == ""


class TestSignalQuality:
    def test_ok(self):
        assert compute_surface_signal_quality(0.8, 0.05, True, 40) == "ok"

    def test_partial(self):
        assert compute_surface_signal_quality(0.8, None, True, 40) == "partial"
        assert compute_surface_signal_quality(None, 0.05, True, 40) == "partial"

    def test_insufficient_history(self):
        assert compute_surface_signal_quality(None, None, True, 10) == "insufficient_history"

    def test_missing_surface(self):
        assert compute_surface_signal_quality(None, None, False, 40) == "missing_current_surface"


class TestEnrichRow:
    def test_enriches_with_signals(self):
        hist = _hist(40, base_iv=0.50, base_move=0.03)
        row = {"ticker": "BIIB", "opt_atm_iv": "0.70", "implied_event_move": "0.10"}
        enrich_row_with_surface_signals(row, hist, "2026-02-15")

        assert row["surface_move_extreme"] == "high"  # 0.10 > all history
        assert row["iv_ramp_flag"] == "rising"  # 0.70 - 0.535 = 0.165
        assert row["surface_signal_quality"] == "ok"

    def test_missing_iv(self):
        hist = _hist(40)
        row = {"ticker": "BIIB", "opt_atm_iv": "", "implied_event_move": ""}
        enrich_row_with_surface_signals(row, hist, "2026-02-15")
        assert row["surface_signal_quality"] == "missing_current_surface"
