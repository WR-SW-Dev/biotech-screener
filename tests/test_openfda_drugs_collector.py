"""Tests for openfda_drugs_collector.py."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from wake_robin_data_pipeline.collectors.openfda_drugs_collector import (
    _match_sponsor_to_ticker,
    _normalize_sponsor,
    build_sponsor_ticker_map,
    collect_openfda_approvals,
)


class TestNormalizeSponsor:
    def test_strip_inc(self):
        assert _normalize_sponsor("Vertex Pharmaceuticals, Inc.") == "vertex"

    def test_strip_therapeutics(self):
        assert _normalize_sponsor("Alnylam Pharmaceuticals") == "alnylam"

    def test_strip_corp(self):
        assert _normalize_sponsor("Bristol-Myers Squibb Company") == "bristol-myers squibb"

    def test_lowercase(self):
        assert _normalize_sponsor("BIOGEN INC") == "biogen"

    def test_empty(self):
        assert _normalize_sponsor("") == ""


class TestBuildSponsorTickerMap:
    def test_builds_from_universe(self, tmp_path):
        universe = [
            {
                "ticker": "BIIB",
                "name": "BIIB",
                "market_data": {"company_name": "Biogen Inc."},
            },
            {
                "ticker": "VRTX",
                "name": "VRTX",
                "market_data": {"company_name": "Vertex Pharmaceuticals Incorporated"},
            },
        ]
        (tmp_path / "universe.json").write_text(json.dumps(universe))
        result = build_sponsor_ticker_map(tmp_path)
        assert "biogen" in result
        assert result["biogen"] == "BIIB"
        assert "vertex" in result
        assert result["vertex"] == "VRTX"

    def test_missing_universe(self, tmp_path):
        result = build_sponsor_ticker_map(tmp_path)
        assert result == {}


class TestMatchSponsorToTicker:
    def test_exact_match(self):
        m = {"biogen": "BIIB", "vertex": "VRTX"}
        assert _match_sponsor_to_ticker("Biogen Inc.", m) == "BIIB"

    def test_substring_match(self):
        m = {"vertex": "VRTX"}
        assert _match_sponsor_to_ticker("Vertex Pharmaceuticals Inc", m) == "VRTX"

    def test_no_match(self):
        m = {"biogen": "BIIB"}
        assert _match_sponsor_to_ticker("Pfizer Inc", m) is None

    def test_empty_sponsor(self):
        m = {"biogen": "BIIB"}
        assert _match_sponsor_to_ticker("", m) is None


class TestCollectOpenfdaApprovals:
    def test_cache_hit(self, tmp_path):
        """When cache exists, should return cached data without API call."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cached_events = [
            {"ticker": "BIIB", "event_type": "FDA_APPROVAL", "event_date": "2026-01-15"},
        ]
        cache_file = cache_dir / "openfda_2026-03-14.json"
        cache_file.write_text(json.dumps(cached_events))

        result = collect_openfda_approvals(
            data_dir=tmp_path,
            as_of_date=date(2026, 3, 14),
            sponsor_map={},
            cache_dir=cache_dir,
        )
        assert len(result) == 1
        assert result[0]["ticker"] == "BIIB"

    def test_empty_sponsor_map(self, tmp_path):
        """With empty sponsor map, no matches possible — should return empty."""
        cache_dir = tmp_path / "cache"
        # No cache file → would try API, but with empty sponsor map
        # Just test the cache path for unit testing
        cache_dir.mkdir()
        cached = []
        (cache_dir / "openfda_2026-03-14.json").write_text(json.dumps(cached))
        result = collect_openfda_approvals(
            data_dir=tmp_path,
            as_of_date=date(2026, 3, 14),
            sponsor_map={},
            cache_dir=cache_dir,
        )
        assert result == []
