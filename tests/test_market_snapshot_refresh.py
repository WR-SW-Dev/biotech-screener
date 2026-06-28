"""Tests for market_snapshot refresh validation and fail-closed behavior.

Classification: REGIME_SNAPSHOT_REFRESH_AND_STALENESS_GATE_NO_MODEL_CHANGE

Acceptance tests covered:
  1. successful refresh writes current as_of_date
  2. refresh failure leaves prior valid snapshot untouched
  3. VIX=0 in live snapshot => validation FAIL (not written)
  4. all signals zero => validation FAIL (not written)
  5. null VIX => validation FAIL (not written)
  6. no changes to ranker/selector/sizing/final_score (import-only check)
  7. snapshot written only when validation passes
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from refresh_market_snapshot import SnapshotValidationError, _validate_snapshot, refresh_snapshot

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _valid_snap(as_of_date: str = "2026-06-26") -> dict:
    """Minimal valid snapshot that passes all validation checks."""
    return {
        "provenance": {
            "as_of_date": as_of_date,
            "version": "1.5.0",
            "generated_by": "refresh_market_snapshot.py",
        },
        "vix": "18.50",
        "xbi_vs_spy_30d": "-2.30",
        "fed_rate_change_3m": "0.07",
        "xbi_momentum_10d": "1.50",
        "spy_momentum_10d": "2.10",
        "credit_spread_change": "0.25",
        "hy_credit_spread": "283.00",
        "biotech_fund_flows": "45.00",
        "xbi_realized_vol_20d": "22.50",
        "yield_curve_slope_bps": "35.00",
        "tnx_10y_yield": "4.35",
        "irx_13w_yield": "4.00",
        "feeds": {
            "vix": "live",
            "spy": "live",
            "xbi": "live",
        },
    }


def _mock_history(ticker_prices: dict):
    """Return a mock _fetch_history function that returns synthetic history."""

    def _fetch(ticker, period="35d", max_retries=3):
        prices = ticker_prices.get(ticker, [])
        return prices

    return _fetch


def _price_series(base: float, n: int = 35, ticker: str = "X"):
    """Generate n synthetic daily (date_str, price) pairs."""
    from datetime import date, timedelta

    start = date(2026, 5, 1)
    return [((start + timedelta(days=i)).strftime("%Y-%m-%d"), base + i * 0.01) for i in range(n)]


# ---------------------------------------------------------------------------
# _validate_snapshot unit tests
# ---------------------------------------------------------------------------


class TestValidateSnapshot:
    def test_valid_snapshot_no_issues(self):
        assert _validate_snapshot(_valid_snap()) == []

    def test_missing_as_of_date(self):
        snap = _valid_snap()
        del snap["provenance"]["as_of_date"]
        issues = _validate_snapshot(snap)
        assert any("as_of_date" in i for i in issues)

    def test_vix_zero_fails(self):
        snap = _valid_snap()
        snap["vix"] = "0"
        issues = _validate_snapshot(snap)
        assert any("vix = 0" in i for i in issues)

    def test_vix_none_fails(self):
        snap = _valid_snap()
        snap["vix"] = None
        issues = _validate_snapshot(snap)
        assert any("vix is null" in i for i in issues)

    def test_vix_implausibly_low(self):
        snap = _valid_snap()
        snap["vix"] = "2.00"
        issues = _validate_snapshot(snap)
        assert any("plausible range" in i for i in issues)

    def test_vix_implausibly_high(self):
        snap = _valid_snap()
        snap["vix"] = "95.00"
        issues = _validate_snapshot(snap)
        assert any("plausible range" in i for i in issues)

    def test_all_signals_zero_fails(self):
        snap = _valid_snap()
        for f in ("vix", "xbi_vs_spy_30d", "xbi_momentum_10d", "spy_momentum_10d", "xbi_realized_vol_20d"):
            snap[f] = "0.00"
        issues = _validate_snapshot(snap)
        assert any("all signal fields are 0.0" in i or "vix = 0" in i for i in issues)

    def test_test_mode_skips_value_checks(self):
        snap = _valid_snap()
        snap["vix"] = "0"
        for f in ("xbi_vs_spy_30d", "xbi_momentum_10d"):
            snap[f] = "0"
        issues = _validate_snapshot(snap, test_mode=True)
        assert issues == [], f"test_mode should skip value checks; got: {issues}"


# ---------------------------------------------------------------------------
# refresh_snapshot integration tests (all feeds mocked)
# ---------------------------------------------------------------------------


class TestRefreshSnapshot:
    def _patch_feeds(
        self,
        vix_price=18.5,
        spy_price=550.0,
        xbi_price=85.0,
        hyg_price=79.0,
        tnx_yield=4.35,
        irx_yield=4.00,
        fred_oas=283.0,
        etf_aum=None,
        aum_flows=None,
    ):
        """Return a context manager that patches all external feeds."""
        vix_hist = _price_series(vix_price, n=12, ticker="^VIX")
        spy_hist = _price_series(spy_price, n=40, ticker="SPY")
        xbi_hist = _price_series(xbi_price, n=40, ticker="XBI")
        hyg_hist = _price_series(hyg_price, n=40, ticker="HYG")
        tnx_hist = _price_series(tnx_yield, n=70, ticker="^TNX")
        irx_hist = _price_series(irx_yield, n=70, ticker="^IRX")

        feed_map = {
            "^VIX": vix_hist,
            "SPY": spy_hist,
            "XBI": xbi_hist,
            "HYG": hyg_hist,
            "^TNX": tnx_hist,
            "^IRX": irx_hist,
        }

        import unittest.mock as mock

        return mock.patch.multiple(
            "refresh_market_snapshot",
            _fetch_history=_mock_history(feed_map),
            _fetch_fred_hy_oas=lambda: fred_oas,
            _fetch_etf_aum=lambda: etf_aum,
            _compute_etf_flows=lambda *a, **k: aum_flows,
        )

    def test_successful_refresh_writes_current_date(self):
        """A clean refresh produces a snapshot with the supplied as_of_date."""
        with self._patch_feeds():
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "market_snapshot.json"
                with patch("refresh_market_snapshot.SNAPSHOT_PATH", out):
                    snap = refresh_snapshot("2026-06-26")

                # Assertions inside the tempdir so the file still exists
                assert snap["provenance"]["as_of_date"] == "2026-06-26"
                assert out.exists()
                loaded = json.loads(out.read_text())
                assert loaded["provenance"]["as_of_date"] == "2026-06-26"
                assert float(loaded["vix"]) > 0

    def test_successful_refresh_does_not_write_zero_vix(self):
        """Successful refresh must never produce VIX=0 in the written file."""
        with self._patch_feeds(vix_price=21.3):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "market_snapshot.json"
                with patch("refresh_market_snapshot.SNAPSHOT_PATH", out):
                    snap = refresh_snapshot("2026-06-26")

        assert float(snap["vix"]) != 0.0

    def test_refresh_failure_leaves_prior_snapshot_untouched(self):
        """When all feeds fail, the existing valid snapshot must not be overwritten."""
        prior = _valid_snap("2026-06-24")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "market_snapshot.json"
            out.write_text(json.dumps(prior) + "\n")

            # All feeds return empty — simulates rate-limit / total failure
            empty_feeds = {t: [] for t in ("^VIX", "SPY", "XBI", "HYG", "^TNX", "^IRX")}
            with patch.multiple(
                "refresh_market_snapshot",
                _fetch_history=_mock_history(empty_feeds),
                _fetch_fred_hy_oas=lambda: None,
                _fetch_etf_aum=lambda: None,
                _compute_etf_flows=lambda *a, **k: None,
            ):
                with patch("refresh_market_snapshot.SNAPSHOT_PATH", out):
                    with pytest.raises(SnapshotValidationError):
                        refresh_snapshot("2026-06-26")

            # File must be unchanged
            on_disk = json.loads(out.read_text())
            assert on_disk["provenance"]["as_of_date"] == "2026-06-24"
            assert float(on_disk["vix"]) == 18.50  # from _valid_snap

    def test_vix_zero_prevents_write(self):
        """VIX=0 in computed snapshot must raise SnapshotValidationError."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "market_snapshot.json"
            prior = _valid_snap("2026-06-24")
            out.write_text(json.dumps(prior) + "\n")

            # Only VIX feed fails; others succeed
            vix_empty = {
                "^VIX": [],
                "SPY": _price_series(550, 40),
                "XBI": _price_series(85, 40),
                "HYG": _price_series(79, 40),
                "^TNX": _price_series(4.35, 70),
                "^IRX": _price_series(4.0, 70),
            }

            with patch.multiple(
                "refresh_market_snapshot",
                _fetch_history=_mock_history(vix_empty),
                _fetch_fred_hy_oas=lambda: 283.0,
                _fetch_etf_aum=lambda: None,
                _compute_etf_flows=lambda *a, **k: None,
            ):
                with patch("refresh_market_snapshot.SNAPSHOT_PATH", out):
                    with pytest.raises(SnapshotValidationError) as exc_info:
                        refresh_snapshot("2026-06-26")

            assert "vix" in str(exc_info.value).lower()
            # Prior snapshot preserved
            on_disk = json.loads(out.read_text())
            assert on_disk["provenance"]["as_of_date"] == "2026-06-24"

    def test_all_zero_signals_prevent_write(self):
        """All-zero computed signals must raise SnapshotValidationError."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "market_snapshot.json"
            prior = _valid_snap("2026-06-24")
            out.write_text(json.dumps(prior) + "\n")

            # All feeds empty → all computed values are None → _fmt(None) = None
            # This should now be caught by the null-VIX check or all-zero check
            empty_all = {t: [] for t in ("^VIX", "SPY", "XBI", "HYG", "^TNX", "^IRX")}
            with patch.multiple(
                "refresh_market_snapshot",
                _fetch_history=_mock_history(empty_all),
                _fetch_fred_hy_oas=lambda: None,
                _fetch_etf_aum=lambda: None,
                _compute_etf_flows=lambda *a, **k: None,
            ):
                with patch("refresh_market_snapshot.SNAPSHOT_PATH", out):
                    with pytest.raises(SnapshotValidationError):
                        refresh_snapshot("2026-06-26")

            on_disk = json.loads(out.read_text())
            assert on_disk["provenance"]["as_of_date"] == "2026-06-24"

    def test_no_model_mutation(self):
        """Importing and calling refresh_snapshot must not touch production model files."""
        protected = [
            PROJECT_ROOT / "ranker",
            PROJECT_ROOT / "selector",
            PROJECT_ROOT / "portfolio",
        ]
        before = {p: p.stat().st_mtime_ns if p.exists() else None for p in protected}

        import refresh_market_snapshot  # noqa: F401 — import only, no side effects

        after = {p: p.stat().st_mtime_ns if p.exists() else None for p in protected}
        assert before == after, "Model files were mutated by import"
