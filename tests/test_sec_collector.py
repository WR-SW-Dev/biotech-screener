"""Tests for SEC EDGAR collector."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_facts(namespace: str, metrics: dict) -> dict:
    """Build a minimal SEC company-facts payload.

    ``metrics`` maps metric_name -> list of {val, end, ...} dicts.
    """
    return {"facts": {namespace: {name: {"units": {"USD": entries}} for name, entries in metrics.items()}}}


def _mock_response(status_code: int = 200, json_data: dict | None = None, raise_for_status: bool = False):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if raise_for_status:
        from requests.exceptions import HTTPError

        resp.raise_for_status.side_effect = HTTPError(response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Imports (after path setup)
# ---------------------------------------------------------------------------

from wake_robin_data_pipeline.collectors.sec_collector import (
    collect_batch,
    collect_sec_data,
    detect_accounting_standard,
    extract_latest_metric,
    fetch_sec_financials,
    get_cache_dir,
    get_cache_path,
    is_cache_valid,
    ticker_to_cik,
)

# ===========================================================================
# Cache path construction
# ===========================================================================


class TestGetCacheDir:
    """Tests for get_cache_dir()."""

    def test_returns_path_object(self):
        result = get_cache_dir()
        assert isinstance(result, Path)

    def test_env_override(self, tmp_path):
        custom = tmp_path / "custom_cache"
        with patch.dict("os.environ", {"SEC_CACHE_DIR": str(custom)}):
            result = get_cache_dir()
            assert result == custom
            assert custom.exists()

    def test_creates_directory(self, tmp_path):
        new_dir = tmp_path / "nested" / "cache"
        with patch.dict("os.environ", {"SEC_CACHE_DIR": str(new_dir)}):
            get_cache_dir()
            assert new_dir.is_dir()


class TestGetCachePath:
    """Tests for get_cache_path()."""

    def test_default_data_type(self, tmp_path):
        with patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}):
            p = get_cache_path("VRTX")
            assert p.name == "VRTX_financials.json"

    def test_custom_data_type(self, tmp_path):
        with patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}):
            p = get_cache_path("GILD", "cik_mapping")
            assert p.name == "GILD_cik_mapping.json"


# ===========================================================================
# Cache validity
# ===========================================================================


class TestIsCacheValid:
    """Tests for is_cache_valid() -- existence-only check."""

    def test_existing_file(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text("{}")
        assert is_cache_valid(f) is True

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nonexistent.json"
        assert is_cache_valid(f) is False

    def test_max_age_param_ignored(self, tmp_path):
        """max_age_hours param exists for compat but has no effect."""
        f = tmp_path / "old.json"
        f.write_text("{}")
        assert is_cache_valid(f, max_age_hours=0) is True


# ===========================================================================
# ticker_to_cik
# ===========================================================================


class TestTickerToCik:
    """Tests for ticker_to_cik()."""

    def test_resolved_ticker(self, tmp_path):
        sec_data = {"0": {"cik_str": 885590, "ticker": "VRTX", "title": "VERTEX PHARMACEUTICALS INC"}}
        mock_resp = _mock_response(json_data=sec_data)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            cik = ticker_to_cik("VRTX")
            assert cik == "0000885590"

    def test_case_insensitive(self, tmp_path):
        sec_data = {"0": {"cik_str": 1, "ticker": "GILD", "title": "GILEAD"}}
        mock_resp = _mock_response(json_data=sec_data)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            assert ticker_to_cik("gild") == "0000000001"

    def test_not_found_returns_none(self, tmp_path):
        sec_data = {"0": {"cik_str": 1, "ticker": "AAPL", "title": "APPLE"}}
        mock_resp = _mock_response(json_data=sec_data)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            assert ticker_to_cik("ZZZZ") is None

    def test_cached_cik_returned(self, tmp_path):
        cache_file = tmp_path / "VRTX_cik_mapping.json"
        cache_file.write_text(json.dumps({"cik": "0000885590", "ticker": "VRTX"}))

        with patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}):
            cik = ticker_to_cik("VRTX")
            assert cik == "0000885590"

    def test_network_error_returns_none(self, tmp_path):
        mock_session = MagicMock()
        mock_session.get.side_effect = ConnectionError("no network")

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            assert ticker_to_cik("VRTX") is None


# ===========================================================================
# extract_latest_metric
# ===========================================================================


class TestExtractLatestMetric:
    """Tests for extract_latest_metric()."""

    def test_basic_extraction(self):
        facts = _make_facts(
            "us-gaap",
            {
                "Assets": [
                    {"val": 1_000_000, "end": "2024-12-31"},
                    {"val": 900_000, "end": "2024-06-30"},
                ]
            },
        )
        val, dt = extract_latest_metric(facts, "Assets")
        assert val == 1_000_000.0
        assert dt == "2024-12-31"

    def test_returns_most_recent(self):
        facts = _make_facts(
            "us-gaap",
            {
                "Cash": [
                    {"val": 100, "end": "2023-01-01"},
                    {"val": 300, "end": "2025-06-30"},
                    {"val": 200, "end": "2024-06-30"},
                ]
            },
        )
        val, dt = extract_latest_metric(facts, "Cash")
        assert val == 300.0
        assert dt == "2025-06-30"

    def test_missing_metric_returns_none(self):
        facts = _make_facts("us-gaap", {})
        val, dt = extract_latest_metric(facts, "NonExistent")
        assert val is None and dt is None

    def test_empty_facts(self):
        val, dt = extract_latest_metric({}, "Assets")
        assert val is None and dt is None

    def test_ifrs_namespace(self):
        facts = _make_facts("ifrs-full", {"CashAndCashEquivalents": [{"val": 500, "end": "2024-09-30"}]})
        val, dt = extract_latest_metric(facts, "CashAndCashEquivalents", namespace="ifrs-full")
        assert val == 500.0

    def test_staleness_filter_rejects_old_data(self):
        """Data older than max_age_days relative to as_of_dt is rejected."""
        facts = _make_facts("us-gaap", {"Assets": [{"val": 100, "end": "2023-01-01"}]})
        val, dt = extract_latest_metric(
            facts,
            "Assets",
            max_age_days=180,
            as_of_dt=datetime(2025, 1, 1),
        )
        assert val is None

    def test_staleness_filter_accepts_recent_data(self):
        facts = _make_facts("us-gaap", {"Assets": [{"val": 100, "end": "2024-12-01"}]})
        val, dt = extract_latest_metric(
            facts,
            "Assets",
            max_age_days=180,
            as_of_dt=datetime(2025, 1, 1),
        )
        assert val == 100.0

    def test_staleness_needs_both_params(self):
        """max_age_days alone (without as_of_dt) does NOT filter."""
        facts = _make_facts("us-gaap", {"Assets": [{"val": 100, "end": "2020-01-01"}]})
        val, _ = extract_latest_metric(facts, "Assets", max_age_days=30)
        assert val == 100.0  # Not filtered because as_of_dt is None

    def test_fallback_to_usd_unit(self):
        """When requested unit missing, falls back to USD."""
        facts = {"facts": {"us-gaap": {"Revenue": {"units": {"USD": [{"val": 42, "end": "2024-01-01"}]}}}}}
        val, _ = extract_latest_metric(facts, "Revenue", unit="shares")
        assert val == 42.0

    def test_fallback_to_first_available_unit(self):
        facts = {
            "facts": {"us-gaap": {"SharesOutstanding": {"units": {"shares": [{"val": 1000, "end": "2024-01-01"}]}}}}
        }
        val, _ = extract_latest_metric(facts, "SharesOutstanding", unit="USD")
        assert val == 1000.0


# ===========================================================================
# detect_accounting_standard
# ===========================================================================


class TestDetectAccountingStandard:
    """Tests for detect_accounting_standard()."""

    def test_us_gaap_default(self):
        facts = {"facts": {"us-gaap": {"A": {}, "B": {}}, "ifrs-full": {}}}
        assert detect_accounting_standard(facts) == "us-gaap"

    def test_ifrs_when_more_metrics(self):
        facts = {"facts": {"us-gaap": {}, "ifrs-full": {"A": {}, "B": {}}}}
        assert detect_accounting_standard(facts) == "ifrs-full"

    def test_ifrs_when_gaap_absent(self):
        facts = {"facts": {"ifrs-full": {"A": {}}}}
        assert detect_accounting_standard(facts) == "ifrs-full"

    def test_empty_facts(self):
        assert detect_accounting_standard({"facts": {}}) == "us-gaap"

    def test_equal_counts_prefers_gaap(self):
        facts = {"facts": {"us-gaap": {"A": {}}, "ifrs-full": {"B": {}}}}
        assert detect_accounting_standard(facts) == "us-gaap"


# ===========================================================================
# fetch_sec_financials
# ===========================================================================


class TestFetchSecFinancials:
    """Tests for fetch_sec_financials()."""

    @pytest.fixture()
    def full_facts(self):
        """A realistic-ish company facts payload."""
        return {
            "facts": {
                "us-gaap": {
                    "CashAndCashEquivalentsAtCarryingValue": {
                        "units": {"USD": [{"val": 5_000_000_000, "end": "2025-09-30"}]}
                    },
                    "LongTermDebt": {"units": {"USD": [{"val": 1_000_000_000, "end": "2025-09-30"}]}},
                    "Revenues": {"units": {"USD": [{"val": 2_000_000_000, "end": "2025-09-30"}]}},
                    "Assets": {"units": {"USD": [{"val": 20_000_000_000, "end": "2025-09-30"}]}},
                    "Liabilities": {"units": {"USD": [{"val": 8_000_000_000, "end": "2025-09-30"}]}},
                    "StockholdersEquity": {"units": {"USD": [{"val": 12_000_000_000, "end": "2025-09-30"}]}},
                }
            }
        }

    def test_successful_fetch(self, full_facts, tmp_path):
        mock_resp = _mock_response(json_data=full_facts)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            result = fetch_sec_financials("VRTX", cik="0000885590")

        assert result["success"] is True
        assert result["financials"]["cash"] == 5_000_000_000
        assert result["financials"]["debt"] == 1_000_000_000
        assert result["financials"]["revenue_ttm"] == 2_000_000_000
        assert result["financials"]["assets"] == 20_000_000_000

    def test_coverage_pct(self, full_facts, tmp_path):
        mock_resp = _mock_response(json_data=full_facts)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            result = fetch_sec_financials("VRTX", cik="0000885590")

        assert result["coverage"]["pct_complete"] == 100.0
        assert result["coverage"]["has_balance_sheet"] is True

    def test_net_debt_calculation(self, full_facts, tmp_path):
        mock_resp = _mock_response(json_data=full_facts)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            result = fetch_sec_financials("VRTX", cik="0000885590")

        # net_debt = debt - total_liquidity (total_liquidity = cash when no marketable_securities)
        assert result["financials"]["net_debt"] == 1_000_000_000 - 5_000_000_000

    def test_debt_free_imputation(self, tmp_path):
        """When assets & liabilities exist but no debt metric, debt set to 0."""
        facts = _make_facts(
            "us-gaap",
            {
                "CashAndCashEquivalentsAtCarryingValue": [{"val": 100, "end": "2025-06-30"}],
                "Assets": [{"val": 500, "end": "2025-06-30"}],
                "Liabilities": [{"val": 200, "end": "2025-06-30"}],
            },
        )
        mock_resp = _mock_response(json_data=facts)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            result = fetch_sec_financials("TEST", cik="0000000001")

        assert result["financials"]["debt"] == 0.0
        assert result["coverage"]["has_debt"] is True

    def test_404_returns_failure(self, tmp_path):
        mock_resp = _mock_response(status_code=404, raise_for_status=True)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            result = fetch_sec_financials("BAD", cik="0000000000")

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_auto_resolves_cik(self, full_facts, tmp_path):
        mock_resp = _mock_response(json_data=full_facts)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
            patch("wake_robin_data_pipeline.collectors.sec_collector.ticker_to_cik", return_value="0000885590"),
        ):
            result = fetch_sec_financials("VRTX")

        assert result["success"] is True

    def test_cik_resolve_failure(self, tmp_path):
        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector.ticker_to_cik", return_value=None),
        ):
            result = fetch_sec_financials("BAD")

        assert result["success"] is False
        assert "Could not resolve" in result["error"]

    def test_provenance_fields(self, full_facts, tmp_path):
        mock_resp = _mock_response(json_data=full_facts)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            result = fetch_sec_financials("VRTX", cik="0000885590")

        prov = result["provenance"]
        assert prov["source"] == "SEC EDGAR Company Facts API"
        assert prov["accounting_standard"] == "us-gaap"
        assert "0000885590" in prov["url"]

    def test_staleness_flags_critical(self, tmp_path):
        """Data >180 days old gets critical staleness flag when as_of_date given."""
        facts = _make_facts(
            "us-gaap",
            {
                "CashAndCashEquivalentsAtCarryingValue": [{"val": 100, "end": "2024-01-01"}],
                "Assets": [{"val": 500, "end": "2024-01-01"}],
                "Liabilities": [{"val": 200, "end": "2024-01-01"}],
            },
        )
        mock_resp = _mock_response(json_data=facts)
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector._get_session", return_value=mock_session),
        ):
            result = fetch_sec_financials("OLD", cik="0000000001", as_of_date="2025-06-01")

        freshness = result["data_freshness"]
        assert freshness["as_of_date_used"] == "2025-06-01"


# ===========================================================================
# collect_sec_data (entry point with caching)
# ===========================================================================


class TestCollectSecData:
    """Tests for collect_sec_data()."""

    def test_returns_cached(self, tmp_path):
        cache_file = tmp_path / "VRTX_financials.json"
        cached = {"ticker": "VRTX", "success": True, "financials": {"cash": 1}}
        cache_file.write_text(json.dumps(cached))

        with patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}):
            result = collect_sec_data("VRTX")

        assert result["from_cache"] is True
        assert result["financials"]["cash"] == 1

    def test_force_refresh_skips_cache(self, tmp_path):
        cache_file = tmp_path / "VRTX_financials.json"
        cache_file.write_text(json.dumps({"ticker": "VRTX", "success": True}))

        fresh = {"ticker": "VRTX", "success": True, "financials": {"cash": 999}}
        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector.fetch_sec_financials", return_value=fresh),
        ):
            result = collect_sec_data("VRTX", force_refresh=True)

        assert result["from_cache"] is False
        assert result["financials"]["cash"] == 999

    def test_failed_fetch_not_cached(self, tmp_path):
        failed = {"ticker": "BAD", "success": False, "error": "oops"}

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector.fetch_sec_financials", return_value=failed),
        ):
            result = collect_sec_data("BAD", force_refresh=True)

        assert result["success"] is False
        cache_file = tmp_path / "BAD_financials.json"
        assert not cache_file.exists()


# ===========================================================================
# collect_batch
# ===========================================================================


class TestCollectBatch:
    """Tests for collect_batch()."""

    def test_batch_returns_all_tickers(self, tmp_path):
        def fake_collect(ticker, force_refresh=False):
            return {
                "ticker": ticker,
                "success": True,
                "financials": {"total_liquidity": 1e9},
                "coverage": {"pct_complete": 75.0},
                "from_cache": True,
            }

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector.collect_sec_data", side_effect=fake_collect),
        ):
            results = collect_batch(["VRTX", "GILD"])

        assert set(results.keys()) == {"VRTX", "GILD"}
        assert all(r["success"] for r in results.values())

    def test_batch_handles_failure(self, tmp_path):
        def fake_collect(ticker, force_refresh=False):
            if ticker == "BAD":
                return {"ticker": "BAD", "success": False, "error": "nope", "from_cache": False}
            return {
                "ticker": ticker,
                "success": True,
                "financials": {"total_liquidity": 1e9},
                "coverage": {"pct_complete": 100.0},
                "from_cache": True,
            }

        with (
            patch.dict("os.environ", {"SEC_CACHE_DIR": str(tmp_path)}),
            patch("wake_robin_data_pipeline.collectors.sec_collector.collect_sec_data", side_effect=fake_collect),
        ):
            results = collect_batch(["VRTX", "BAD"])

        assert results["VRTX"]["success"] is True
        assert results["BAD"]["success"] is False
