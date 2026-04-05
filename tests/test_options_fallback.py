"""Tests for options DTE relaxation and Massive fallback chain."""

from datetime import date

from common.options_diagnostics import select_front_back_expiries


class TestDTERelaxation:
    def test_default_min_dte_7_rejects_short(self):
        """Default min_dte=7 rejects expiries < 7 days out."""
        expiry_ivs = [
            {"expiration_date": "2026-01-10", "implied_volatility": 0.50},  # 5 DTE
        ]
        front, back = select_front_back_expiries(expiry_ivs, date(2026, 1, 5), min_dte=7)
        assert front is None

    def test_min_dte_3_accepts_weekly(self):
        """min_dte=3 accepts a 5-DTE expiry."""
        expiry_ivs = [
            {"expiration_date": "2026-01-10", "implied_volatility": 0.50},  # 5 DTE
        ]
        front, back = select_front_back_expiries(expiry_ivs, date(2026, 1, 5), min_dte=3)
        assert front is not None
        assert front["dte"] == 5

    def test_min_dte_3_still_rejects_1dte(self):
        """min_dte=3 still rejects 1-DTE expiries."""
        expiry_ivs = [
            {"expiration_date": "2026-01-06", "implied_volatility": 0.50},  # 1 DTE
        ]
        front, back = select_front_back_expiries(expiry_ivs, date(2026, 1, 5), min_dte=3)
        assert front is None

    def test_selects_nearest_above_threshold(self):
        """With multiple expiries, selects the nearest above min_dte."""
        expiry_ivs = [
            {"expiration_date": "2026-01-07", "implied_volatility": 0.40},  # 2 DTE
            {"expiration_date": "2026-01-12", "implied_volatility": 0.50},  # 7 DTE
            {"expiration_date": "2026-01-19", "implied_volatility": 0.45},  # 14 DTE
        ]
        front, back = select_front_back_expiries(expiry_ivs, date(2026, 1, 5), min_dte=7)
        assert front is not None
        assert front["dte"] == 7
        assert back is not None
        assert back["dte"] == 14

    def test_front_back_with_relaxed_dte(self):
        """Relaxed DTE finds front (4d) and back (11d)."""
        expiry_ivs = [
            {"expiration_date": "2026-01-09", "implied_volatility": 0.55},  # 4 DTE
            {"expiration_date": "2026-01-16", "implied_volatility": 0.48},  # 11 DTE
        ]
        front, back = select_front_back_expiries(expiry_ivs, date(2026, 1, 5), min_dte=3)
        assert front is not None
        assert front["dte"] == 4
        assert back is not None
        assert back["dte"] == 11

    def test_empty_expiries(self):
        front, back = select_front_back_expiries([], date(2026, 1, 5))
        assert front is None
        assert back is None

    def test_no_iv_data_skipped(self):
        expiry_ivs = [
            {"expiration_date": "2026-01-15", "implied_volatility": None},
        ]
        front, back = select_front_back_expiries(expiry_ivs, date(2026, 1, 5))
        assert front is None

    def test_backward_compat_default_is_7(self):
        """Calling without min_dte uses default of 7."""
        expiry_ivs = [
            {"expiration_date": "2026-01-10", "implied_volatility": 0.50},  # 5 DTE
            {"expiration_date": "2026-01-15", "implied_volatility": 0.45},  # 10 DTE
        ]
        front, back = select_front_back_expiries(expiry_ivs, date(2026, 1, 5))
        assert front is not None
        assert front["dte"] == 10  # Skipped 5-DTE, took 10-DTE
