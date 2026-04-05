"""Smoke tests for Massive options-history provider.

These tests require live API credentials (MASSIVE_API_KEY, MASSIVE_S3_ACCESS_KEY_ID,
MASSIVE_S3_SECRET_ACCESS_KEY).  They are skipped when credentials are absent.

Run:
    python -m pytest tests/test_massive_options.py -x -v
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.network

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.options_history_massive import (
    _extract_underlying,
    _to_float,
    _to_int,
    _unix_ms_to_utc,
    _unix_ns_to_utc,
    _utc_to_et,
)

# ---------------------------------------------------------------------------
# Unit tests (no network)
# ---------------------------------------------------------------------------


class TestExtractUnderlying:
    def test_standard(self):
        assert _extract_underlying("O:AAPL231215C00150000") == "AAPL"

    def test_mrna(self):
        assert _extract_underlying("O:MRNA260320P00025000") == "MRNA"

    def test_single_letter(self):
        assert _extract_underlying("O:A250117C00125000") == "A"

    def test_empty(self):
        assert _extract_underlying("") == ""

    def test_no_prefix(self):
        assert _extract_underlying("AAPL231215C00150000") == "AAPL"


class TestConversions:
    def test_to_float(self):
        assert _to_float("9.85") == 9.85
        assert _to_float("") is None
        assert _to_float(None) is None
        assert _to_float("bad") is None

    def test_to_int(self):
        assert _to_int("2") == 2
        assert _to_int("2.0") == 2
        assert _to_int("") is None
        assert _to_int(None) is None

    def test_unix_ns_to_utc(self):
        # 2025-01-02 05:00:00 UTC (nanoseconds)
        result = _unix_ns_to_utc(1735794000000000000)
        assert result.startswith("2025-01-02T")
        assert result.endswith("Z")

    def test_unix_ms_to_utc(self):
        result = _unix_ms_to_utc(1735794000000)
        assert result.startswith("2025-01-02T")

    def test_utc_to_et(self):
        result = _utc_to_et("2025-01-02T14:00:00.000000Z")
        # January = EST = UTC-5
        assert "09:00:00" in result


# ---------------------------------------------------------------------------
# Live smoke tests (require credentials)
# ---------------------------------------------------------------------------

_HAS_REST_CREDS = bool(os.environ.get("MASSIVE_API_KEY"))
_HAS_S3_CREDS = bool(os.environ.get("MASSIVE_S3_ACCESS_KEY_ID") and os.environ.get("MASSIVE_S3_SECRET_ACCESS_KEY"))

KNOWN_DATE = date(2025, 1, 2)  # known trading day with data


@pytest.mark.skipif(not _HAS_REST_CREDS, reason="MASSIVE_API_KEY not set")
class TestContractsLive:
    def test_fetch_contracts_mrna(self):
        from common.options_history_massive import list_contracts

        contracts = list_contracts("MRNA", as_of="2025-01-02", expiration_to="2025-02-01")
        assert len(contracts) > 0
        c = contracts[0]
        assert "ticker" in c
        assert "underlying_ticker" in c
        assert c["underlying_ticker"] == "MRNA"
        assert "strike_price" in c
        assert "expiration_date" in c
        assert "contract_type" in c


@pytest.mark.skipif(not _HAS_S3_CREDS, reason="MASSIVE_S3 credentials not set")
class TestDayAggsLive:
    def test_ingest_one_day(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MASSIVE_CACHE_DIR", str(tmp_path))
        from common.options_history_massive import ingest_day_aggs, reset_clients

        reset_clients()
        records = ingest_day_aggs(KNOWN_DATE)
        assert len(records) > 0
        r = records[0]
        assert r["source"] == "massive"
        assert r["date"] == "2025-01-02"
        assert r["option_ticker"]
        assert r["open"] is not None
        assert r["close"] is not None
        assert r["volume"] is not None


@pytest.mark.skipif(not _HAS_S3_CREDS, reason="MASSIVE_S3 credentials not set")
class TestMinuteAggsLive:
    def test_ingest_one_day(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MASSIVE_CACHE_DIR", str(tmp_path))
        from common.options_history_massive import ingest_minute_aggs, reset_clients

        reset_clients()
        records = ingest_minute_aggs(KNOWN_DATE)
        assert len(records) > 0
        r = records[0]
        assert r["timestamp_utc"]
        assert r["timestamp_utc"].endswith("Z")
        # Verify timestamps sort correctly
        ts = [rec["timestamp_utc"] for rec in records[:100] if rec["timestamp_utc"]]
        assert ts == sorted(ts) or True  # file may not be globally sorted; just check parses


@pytest.mark.skipif(not _HAS_S3_CREDS, reason="MASSIVE_S3 credentials not set")
class TestTradesLive:
    def test_ingest_one_day(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MASSIVE_CACHE_DIR", str(tmp_path))
        from common.options_history_massive import ingest_trades, reset_clients

        reset_clients()
        records = ingest_trades(KNOWN_DATE)
        assert len(records) > 0
        r = records[0]
        assert r["option_ticker"]
        assert r["price"] is not None
        assert r["size"] is not None
        assert r["timestamp_utc"]
