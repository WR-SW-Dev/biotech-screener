"""Tests for common/corporate_actions.py — corporate action registry loader and queries."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.corporate_actions import (
    cumulative_split_factor,
    death_date,
    get_splits_only,
    is_dead,
    list_dead_tickers,
    load_actions,
    resolve_ticker,
    resolve_ticker_reverse,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ACTIONS = [
    {
        "ticker": "TEST",
        "action": "reverse_split",
        "effective_date": "2024-06-15",
        "ratio": "1:5",
        "factor": 5.0,
    },
    {
        "ticker": "TEST",
        "action": "forward_split",
        "effective_date": "2023-01-10",
        "ratio": "3:1",
        "factor": 0.333,
    },
    {
        "ticker": "DEAD",
        "action": "acquisition",
        "effective_date": "2025-03-01",
        "acquirer": "BigPharma",
        "deal_price": 50.0,
    },
    {
        "ticker": "GONE",
        "action": "delisted",
        "effective_date": "2024-12-01",
    },
    {
        "ticker": "NEW",
        "action": "ticker_change",
        "effective_date": "2025-01-15",
        "old_ticker": "OLD",
        "new_ticker": "NEW",
    },
    {
        "ticker": "LATEST",
        "action": "ticker_change",
        "effective_date": "2025-06-01",
        "old_ticker": "NEW",
        "new_ticker": "LATEST",
        "notes": "Second rename in chain: OLD -> NEW -> LATEST",
    },
]


@pytest.fixture
def sample_registry(tmp_path):
    """Build a registry from sample data."""
    p = tmp_path / "corporate_actions.json"
    p.write_text(json.dumps({"actions": SAMPLE_ACTIONS}))
    return load_actions(p)


@pytest.fixture
def production_registry():
    """Load the real production registry."""
    return load_actions()


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class TestLoader:
    def test_loads_production_file(self, production_registry):
        assert len(production_registry.actions) > 30

    def test_missing_file_returns_empty(self, tmp_path):
        reg = load_actions(tmp_path / "nonexistent.json")
        assert len(reg.actions) == 0

    def test_indices_built(self, sample_registry):
        assert "TEST" in sample_registry._by_ticker
        assert "OLD" in sample_registry._rename_map

    def test_unknown_action_type_skipped(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text(
            json.dumps(
                {
                    "actions": [
                        {
                            "ticker": "X",
                            "action": "unicorn_event",
                            "effective_date": "2025-01-01",
                        }
                    ]
                }
            )
        )
        reg = load_actions(p)
        assert len(reg.actions) == 0


# ---------------------------------------------------------------------------
# Split queries
# ---------------------------------------------------------------------------


class TestSplitQueries:
    def test_get_splits_all(self, sample_registry):
        splits = get_splits_only("TEST", sample_registry)
        assert len(splits) == 2

    def test_get_splits_pit_filtered(self, sample_registry):
        splits = get_splits_only("TEST", sample_registry, as_of="2023-06-01")
        assert len(splits) == 1
        assert splits[0].action == "forward_split"

    def test_cumulative_factor_single(self, sample_registry):
        f = cumulative_split_factor("TEST", "2024-01-01", "2025-01-01", sample_registry)
        assert f == pytest.approx(5.0, rel=0.01)

    def test_cumulative_factor_both(self, sample_registry):
        f = cumulative_split_factor("TEST", "2022-01-01", "2025-01-01", sample_registry)
        # forward_split (0.333) then reverse_split (5.0) → 0.333 * 5.0 = 1.665
        assert f == pytest.approx(0.333 * 5.0, rel=0.01)

    def test_cumulative_factor_no_splits(self, sample_registry):
        f = cumulative_split_factor("DEAD", "2020-01-01", "2026-01-01", sample_registry)
        assert f == 1.0

    def test_production_aktx_split(self, production_registry):
        """AKTX had a 1:40 reverse split on 2026-03-31."""
        splits = get_splits_only("AKTX", production_registry)
        assert len(splits) >= 1
        assert any(s.factor and s.factor > 40 for s in splits)


# ---------------------------------------------------------------------------
# Death queries
# ---------------------------------------------------------------------------


class TestDeathQueries:
    def test_is_dead_after_acquisition(self, sample_registry):
        assert is_dead("DEAD", "2025-04-01", sample_registry)

    def test_is_not_dead_before_acquisition(self, sample_registry):
        assert not is_dead("DEAD", "2025-02-01", sample_registry)

    def test_is_dead_delisted(self, sample_registry):
        assert is_dead("GONE", "2025-01-01", sample_registry)

    def test_alive_ticker(self, sample_registry):
        assert not is_dead("TEST", "2026-01-01", sample_registry)

    def test_death_date(self, sample_registry):
        assert death_date("DEAD", sample_registry) == "2025-03-01"
        assert death_date("GONE", sample_registry) == "2024-12-01"
        assert death_date("TEST", sample_registry) is None

    def test_list_dead_tickers(self, sample_registry):
        dead = list_dead_tickers("2025-06-01", sample_registry)
        assert "DEAD" in dead
        assert "GONE" in dead
        assert "TEST" not in dead

    def test_production_cnta_dead(self, production_registry):
        """CNTA was acquired by Lilly in March 2026."""
        assert is_dead("CNTA", "2026-04-01", production_registry)
        assert not is_dead("CNTA", "2026-03-01", production_registry)


# ---------------------------------------------------------------------------
# Rename resolution
# ---------------------------------------------------------------------------


class TestRenameResolution:
    def test_resolve_old_to_new(self, sample_registry):
        """Before the second rename, OLD should resolve to NEW (not LATEST)."""
        assert resolve_ticker("OLD", "2025-03-01", sample_registry) == "NEW"

    def test_resolve_chain(self, sample_registry):
        """OLD -> NEW -> LATEST should resolve through the chain."""
        assert resolve_ticker("OLD", "2025-07-01", sample_registry) == "LATEST"

    def test_resolve_before_rename(self, sample_registry):
        """Before the rename date, OLD should stay OLD."""
        assert resolve_ticker("OLD", "2024-12-01", sample_registry) == "OLD"

    def test_resolve_unknown_ticker(self, sample_registry):
        assert resolve_ticker("UNKNOWN", "2025-01-01", sample_registry) == "UNKNOWN"

    def test_reverse_resolve(self, sample_registry):
        preds = resolve_ticker_reverse("NEW", "2025-06-01", sample_registry)
        assert "OLD" in preds

    def test_reverse_resolve_chain(self, sample_registry):
        preds = resolve_ticker_reverse("LATEST", "2025-07-01", sample_registry)
        assert "NEW" in preds
        assert "OLD" in preds

    def test_production_bgne_to_onc(self, production_registry):
        """BGNE renamed to ONC on 2025-01-02."""
        assert resolve_ticker("BGNE", "2025-06-01", production_registry) == "ONC"
        assert resolve_ticker("BGNE", "2024-12-01", production_registry) == "BGNE"


# ---------------------------------------------------------------------------
# Production data integrity
# ---------------------------------------------------------------------------


class TestProductionDataIntegrity:
    def test_all_actions_have_dates(self, production_registry):
        for a in production_registry.actions:
            assert a.effective_date, f"{a.ticker} missing effective_date"
            assert len(a.effective_date) == 10, f"{a.ticker} bad date format: {a.effective_date}"

    def test_splits_have_factors(self, production_registry):
        for a in production_registry.actions:
            if a.action in ("forward_split", "reverse_split"):
                assert a.factor is not None, f"{a.ticker} split on {a.effective_date} missing factor"
                assert a.factor > 0

    def test_renames_have_both_tickers(self, production_registry):
        for a in production_registry.actions:
            if a.action == "ticker_change":
                assert a.old_ticker, f"Rename {a.ticker} missing old_ticker"
                assert a.new_ticker, f"Rename {a.ticker} missing new_ticker"

    def test_no_duplicate_actions(self, production_registry):
        """Same (ticker, action, date) should not appear twice."""
        seen = set()
        for a in production_registry.actions:
            key = (a.ticker, a.action, a.effective_date)
            assert key not in seen, f"Duplicate action: {key}"
            seen.add(key)
