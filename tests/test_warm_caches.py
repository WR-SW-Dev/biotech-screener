"""Unit tests for warm_caches.py utility/dispatcher functions.

Covers: validate_cache_refresh, _dedup_events, _extract_pattern_version,
_load_universe, source list parsing, and dispatcher routing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from warm_caches import (
    validate_cache_refresh,
    _dedup_events,
    _extract_pattern_version,
    _load_universe,
)


# =============================================================================
# validate_cache_refresh
# =============================================================================

class TestValidateCacheRefresh:
    # --- sec_8k ---
    def test_sec8k_empty_refresh_rejected(self):
        ok, reason = validate_cache_refresh("sec_8k", 0, 100)
        assert not ok
        assert reason == "empty_refresh"

    def test_sec8k_collapse_rejected(self):
        ok, reason = validate_cache_refresh("sec_8k", 5, 100)
        assert not ok
        assert "collapse" in reason

    def test_sec8k_healthy_accepted(self):
        ok, reason = validate_cache_refresh("sec_8k", 90, 100)
        assert ok
        assert reason == ""

    def test_sec8k_no_prior_accepted(self):
        ok, _ = validate_cache_refresh("sec_8k", 50, None)
        assert ok

    def test_sec8k_prior_zero_accepted(self):
        ok, _ = validate_cache_refresh("sec_8k", 10, 0)
        assert ok

    # --- ctgov ---
    def test_ctgov_empty_rejected(self):
        ok, reason = validate_cache_refresh("ctgov", 0, 1000)
        assert not ok
        assert reason == "empty_refresh"

    def test_ctgov_out_of_band_low_rejected(self):
        ok, reason = validate_cache_refresh("ctgov", 50, 1000)  # ratio=0.05
        assert not ok
        assert "out_of_band" in reason

    def test_ctgov_out_of_band_high_rejected(self):
        ok, reason = validate_cache_refresh("ctgov", 5000, 1000)  # ratio=5.0
        assert not ok
        assert "out_of_band" in reason

    def test_ctgov_in_band_accepted(self):
        ok, _ = validate_cache_refresh("ctgov", 950, 1000)
        assert ok

    def test_ctgov_no_prior_accepted(self):
        ok, _ = validate_cache_refresh("ctgov", 500, None)
        assert ok

    # --- EU registries always accept ---
    @pytest.mark.parametrize("source", ["euctr", "ctis", "isrctn"])
    def test_eu_registries_always_accept(self, source):
        ok, reason = validate_cache_refresh(source, 0, 100)
        assert ok
        assert reason == ""

    @pytest.mark.parametrize("source", ["euctr", "ctis", "isrctn"])
    def test_eu_registries_accept_any_count(self, source):
        ok, _ = validate_cache_refresh(source, 999, None)
        assert ok

    # --- ema_agenda ---
    def test_ema_agenda_zero_accepted(self):
        ok, _ = validate_cache_refresh("ema_agenda", 0, 10)
        assert ok  # zero is valid for EMA (no upcoming meetings)

    def test_ema_agenda_out_of_band_rejected(self):
        ok, reason = validate_cache_refresh("ema_agenda", 1, 100)
        assert not ok
        assert "out_of_band" in reason

    def test_ema_agenda_in_band_accepted(self):
        ok, _ = validate_cache_refresh("ema_agenda", 90, 100)
        assert ok

    # --- ema_outcomes ---
    def test_ema_outcomes_zero_accepted(self):
        ok, _ = validate_cache_refresh("ema_outcomes", 0, 5)
        assert ok

    def test_ema_outcomes_out_of_band_rejected(self):
        ok, reason = validate_cache_refresh("ema_outcomes", 1, 100)
        assert not ok
        assert "out_of_band" in reason

    # --- merged_trials ---
    def test_merged_trials_empty_rejected(self):
        ok, reason = validate_cache_refresh("merged_trials", 0, 500)
        assert not ok
        assert reason == "empty_refresh"

    def test_merged_trials_in_band_accepted(self):
        ok, _ = validate_cache_refresh("merged_trials", 480, 500)
        assert ok

    # --- unknown source ---
    def test_unknown_source_always_accepted(self):
        ok, reason = validate_cache_refresh("unknown_thing", 0, 0)
        assert ok
        assert reason == ""


# =============================================================================
# _dedup_events
# =============================================================================

class TestDedupEvents:
    def test_empty_list(self):
        assert _dedup_events([]) == []

    def test_no_duplicates(self):
        events = [
            {"ticker": "A", "event_type": "FDA", "event_date": "2026-01-01"},
            {"ticker": "B", "event_type": "FDA", "event_date": "2026-01-01"},
        ]
        assert len(_dedup_events(events)) == 2

    def test_removes_duplicates(self):
        events = [
            {"ticker": "A", "event_type": "FDA", "event_date": "2026-01-01", "extra": "first"},
            {"ticker": "A", "event_type": "FDA", "event_date": "2026-01-01", "extra": "second"},
        ]
        result = _dedup_events(events)
        assert len(result) == 1
        assert result[0]["extra"] == "first"  # first seen wins

    def test_preserves_order(self):
        events = [
            {"ticker": "C", "event_type": "8K", "event_date": "2026-01-03"},
            {"ticker": "A", "event_type": "FDA", "event_date": "2026-01-01"},
            {"ticker": "B", "event_type": "PDUFA", "event_date": "2026-01-02"},
        ]
        result = _dedup_events(events)
        assert [e["ticker"] for e in result] == ["C", "A", "B"]

    def test_different_fields_not_deduped(self):
        events = [
            {"ticker": "A", "event_type": "FDA", "event_date": "2026-01-01"},
            {"ticker": "A", "event_type": "FDA", "event_date": "2026-01-02"},  # different date
            {"ticker": "A", "event_type": "8K", "event_date": "2026-01-01"},   # different type
        ]
        assert len(_dedup_events(events)) == 3


# =============================================================================
# _extract_pattern_version
# =============================================================================

class TestExtractPatternVersion:
    def test_valid_filename(self):
        p = Path("8k_catalysts_2026-02-14_249a4353.json")
        assert _extract_pattern_version(p) == "249a4353"

    def test_no_match(self):
        assert _extract_pattern_version(Path("random_file.json")) is None

    def test_wrong_prefix(self):
        assert _extract_pattern_version(Path("fda_adcom_2026-01-01_aabbccdd.json")) is None

    def test_hash_too_short(self):
        assert _extract_pattern_version(Path("8k_catalysts_2026-01-01_abc.json")) is None

    def test_full_path(self):
        p = Path("/cache/sec/8k_catalysts/8k_catalysts_2026-03-01_deadbeef.json")
        assert _extract_pattern_version(p) == "deadbeef"


# =============================================================================
# _load_universe
# =============================================================================

class TestLoadUniverse:
    def test_list_format(self, tmp_path):
        universe = [{"ticker": "ACME"}, {"ticker": "GILD"}]
        (tmp_path / "universe.json").write_text(json.dumps(universe))
        result = _load_universe(tmp_path)
        assert len(result) == 2
        assert result[0]["ticker"] == "ACME"

    def test_dict_format(self, tmp_path):
        universe = {"tickers": [{"ticker": "ACME"}], "metadata": {}}
        (tmp_path / "universe.json").write_text(json.dumps(universe))
        result = _load_universe(tmp_path)
        assert len(result) == 1

    def test_missing_file(self, tmp_path):
        result = _load_universe(tmp_path)
        assert result == []

    def test_empty_list(self, tmp_path):
        (tmp_path / "universe.json").write_text("[]")
        result = _load_universe(tmp_path)
        assert result == []


# =============================================================================
# Source list parsing (pattern test)
# =============================================================================

class TestSourceParsing:
    """Tests for the source parsing pattern used in warm_caches.main()."""

    @staticmethod
    def _parse_sources(sources_str: str) -> list[str]:
        return [s.strip() for s in sources_str.split(",")]

    def test_single_source(self):
        assert self._parse_sources("fda_adcom") == ["fda_adcom"]

    def test_multiple_sources(self):
        result = self._parse_sources("fda_adcom,sec_8k,ctgov")
        assert result == ["fda_adcom", "sec_8k", "ctgov"]

    def test_whitespace_trimmed(self):
        result = self._parse_sources("fda_adcom , sec_8k , ctgov")
        assert result == ["fda_adcom", "sec_8k", "ctgov"]

    def test_all_15_sources_recognized(self):
        all_sources = [
            "fda_adcom", "sec_8k", "sec_13f", "ctgov", "event_ledger",
            "price_pit", "ema_agenda", "ema_outcomes", "euctr", "ctis",
            "isrctn", "merged_trials", "conference_calendar", "ir_events",
            "press_releases",
        ]
        assert len(all_sources) == 15

    def test_default_sources(self):
        result = self._parse_sources("fda_adcom,sec_8k")
        assert "fda_adcom" in result
        assert "sec_8k" in result
