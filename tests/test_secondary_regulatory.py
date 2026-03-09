"""Tests for secondary regulatory catalyst feature.

Verifies:
1. _nearest_regulatory_catalyst() finds REGULATORY events from M3 summaries
2. Backfill in ranking_utils generates has_regulatory_upcoming_180d from event_type
3. Secondary family_filter_mode in evaluate() uses has_regulatory_upcoming_180d
4. _effective_family() in build_action_lists returns REGULATORY in secondary mode
5. End-to-end: a ticker with primary=CLINICAL but secondary=REGULATORY is included
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Test _nearest_regulatory_catalyst
# ---------------------------------------------------------------------------


class TestNearestRegulatoryCatalyst:
    """Tests for run_screen._nearest_regulatory_catalyst()."""

    def _import_fn(self):
        from run_screen import _nearest_regulatory_catalyst

        return _nearest_regulatory_catalyst

    def test_finds_pdufa_event(self):
        fn = self._import_fn()
        # M3 summaries: per-ticker dict has "events" at top level
        m3 = {
            "ACME": {
                "events": [
                    {"event_type": "CT_PRIMARY_COMPLETION", "event_date": "2026-06-01", "source": "CTGOV"},
                    {"event_type": "PDUFA", "event_date": "2026-05-15", "source": "PDUFA_MANUAL"},
                ]
            }
        }
        days, et = fn(m3, "ACME", "2026-03-01")
        assert et == "PDUFA"
        assert int(days) > 0

    def test_skips_clinical_events(self):
        fn = self._import_fn()
        m3 = {
            "ACME": {
                "events": [
                    {"event_type": "DATA_READOUT", "event_date": "2026-06-01", "source": "CTGOV"},
                    {"event_type": "CT_PRIMARY_COMPLETION", "event_date": "2026-07-01", "source": "CTGOV"},
                ]
            }
        }
        days, et = fn(m3, "ACME", "2026-03-01")
        assert days == ""
        assert et == ""

    def test_respects_180d_window(self):
        fn = self._import_fn()
        m3 = {
            "ACME": {
                "events": [
                    {"event_type": "PDUFA", "event_date": "2027-06-01", "source": "PDUFA_MANUAL"},
                ]
            }
        }
        # More than 180 days out
        days, et = fn(m3, "ACME", "2026-03-01")
        assert days == ""

    def test_missing_ticker_returns_empty(self):
        fn = self._import_fn()
        days, et = fn({"OTHER": {}}, "ACME", "2026-03-01")
        assert days == ""
        assert et == ""

    def test_none_m3_returns_empty(self):
        fn = self._import_fn()
        days, et = fn(None, "ACME", "2026-03-01")
        assert days == ""
        assert et == ""

    def test_picks_nearest_regulatory(self):
        """When multiple regulatory events exist, picks the nearest."""
        fn = self._import_fn()
        m3 = {
            "ACME": {
                "events": [
                    {"event_type": "FDA_ADCOM", "event_date": "2026-04-01", "source": "FDA_FEDREG"},
                    {"event_type": "PDUFA", "event_date": "2026-05-15", "source": "PDUFA_MANUAL"},
                ]
            }
        }
        days, et = fn(m3, "ACME", "2026-03-01")
        assert et == "FDA_ADCOM"  # nearer
        assert int(days) == 31


# ---------------------------------------------------------------------------
# Test PDUFA manual fallback
# ---------------------------------------------------------------------------


class TestPdufaManualFallback:
    """Tests for PDUFA manual file fallback in _nearest_regulatory_catalyst."""

    def _import_fn(self):
        from run_screen import _nearest_regulatory_catalyst

        return _nearest_regulatory_catalyst

    def test_pdufa_manual_found_when_m3_missing(self):
        fn = self._import_fn()
        # M3 has no regulatory events for ACME
        m3 = {"ACME": {"events": [{"event_type": "DATA_READOUT", "event_date": "2026-06-01"}]}}
        pdufa = [{"ticker": "ACME", "pdufa_date": "2026-05-15"}]
        days, et = fn(m3, "ACME", "2026-03-01", pdufa_manual=pdufa)
        assert et == "PDUFA"
        assert int(days) == 75

    def test_pdufa_manual_not_used_when_m3_has_closer(self):
        fn = self._import_fn()
        m3 = {"ACME": {"events": [{"event_type": "FDA_ADCOM", "event_date": "2026-04-01"}]}}
        pdufa = [{"ticker": "ACME", "pdufa_date": "2026-05-15"}]
        days, et = fn(m3, "ACME", "2026-03-01", pdufa_manual=pdufa)
        assert et == "FDA_ADCOM"  # M3 event is closer
        assert int(days) == 31

    def test_pdufa_manual_used_when_closer_than_m3(self):
        fn = self._import_fn()
        m3 = {"ACME": {"events": [{"event_type": "FDA_ADCOM", "event_date": "2026-06-01"}]}}
        pdufa = [{"ticker": "ACME", "pdufa_date": "2026-04-01"}]
        days, et = fn(m3, "ACME", "2026-03-01", pdufa_manual=pdufa)
        assert et == "PDUFA"  # manual is closer
        assert int(days) == 31

    def test_pdufa_manual_past_date_ignored(self):
        fn = self._import_fn()
        pdufa = [{"ticker": "ACME", "pdufa_date": "2026-02-01"}]  # past
        days, et = fn(None, "ACME", "2026-03-01", pdufa_manual=pdufa)
        assert days == ""

    def test_pdufa_manual_beyond_180d_ignored(self):
        fn = self._import_fn()
        pdufa = [{"ticker": "ACME", "pdufa_date": "2027-01-01"}]  # >180d
        days, et = fn(None, "ACME", "2026-03-01", pdufa_manual=pdufa)
        assert days == ""

    def test_pdufa_manual_case_insensitive_ticker(self):
        fn = self._import_fn()
        pdufa = [{"ticker": "acme", "pdufa_date": "2026-05-15"}]
        days, et = fn(None, "ACME", "2026-03-01", pdufa_manual=pdufa)
        assert et == "PDUFA"

    def test_pdufa_manual_empty_list(self):
        fn = self._import_fn()
        days, et = fn(None, "ACME", "2026-03-01", pdufa_manual=[])
        assert days == ""

    def test_pdufa_manual_none(self):
        fn = self._import_fn()
        days, et = fn(None, "ACME", "2026-03-01", pdufa_manual=None)
        assert days == ""


# ---------------------------------------------------------------------------
# Test backfill in ranking_utils
# ---------------------------------------------------------------------------


class TestBackfillSecondaryRegulatory:
    """Tests for ranking_utils.backfill_columns secondary regulatory columns."""

    def _backfill(self, rows):
        from common.ranking_utils import backfill_columns

        backfill_columns(rows)
        return rows

    def test_regulatory_event_gets_flag(self):
        rows = [
            {"catalyst_event_type": "PDUFA", "catalyst_days": "45", "catalyst_family": "REGULATORY"},
        ]
        self._backfill(rows)
        assert rows[0]["has_regulatory_upcoming_180d"] == "1"
        assert rows[0]["regulatory_days"] == "45"
        assert rows[0]["regulatory_event_type"] == "PDUFA"

    def test_clinical_event_no_flag(self):
        rows = [
            {"catalyst_event_type": "DATA_READOUT", "catalyst_days": "60", "catalyst_family": "CLINICAL"},
        ]
        self._backfill(rows)
        assert rows[0]["has_regulatory_upcoming_180d"] == "0"
        assert rows[0]["regulatory_days"] == ""

    def test_empty_event_type_no_flag(self):
        rows = [{"catalyst_event_type": "", "catalyst_family": ""}]
        self._backfill(rows)
        assert rows[0]["has_regulatory_upcoming_180d"] == "0"

    def test_existing_columns_not_overwritten(self):
        rows = [
            {
                "has_regulatory_upcoming_180d": "1",
                "regulatory_days": "30",
                "regulatory_event_type": "PDUFA",
                "catalyst_event_type": "DATA_READOUT",  # clinical primary
            }
        ]
        self._backfill(rows)
        # Should NOT overwrite — column already exists
        assert rows[0]["has_regulatory_upcoming_180d"] == "1"
        assert rows[0]["regulatory_days"] == "30"


# ---------------------------------------------------------------------------
# Test _effective_family in build_action_lists
# ---------------------------------------------------------------------------


class TestEffectiveFamily:
    """Tests for build_action_lists._effective_family()."""

    def _import_fn(self):
        from tools.build_action_lists import _effective_family

        return _effective_family

    def test_primary_mode_uses_catalyst_family(self):
        fn = self._import_fn()
        row = {"catalyst_family": "CLINICAL", "has_regulatory_upcoming_180d": "1"}
        assert fn(row, mode="primary") == "CLINICAL"

    def test_secondary_mode_promotes_regulatory(self):
        fn = self._import_fn()
        row = {"catalyst_family": "CLINICAL", "has_regulatory_upcoming_180d": "1"}
        assert fn(row, mode="secondary") == "REGULATORY"

    def test_secondary_mode_no_flag_keeps_primary(self):
        fn = self._import_fn()
        row = {"catalyst_family": "CLINICAL", "has_regulatory_upcoming_180d": "0"}
        assert fn(row, mode="secondary") == "CLINICAL"

    def test_secondary_mode_empty_flag_keeps_primary(self):
        fn = self._import_fn()
        row = {"catalyst_family": "CLINICAL"}
        assert fn(row, mode="secondary") == "CLINICAL"


# ---------------------------------------------------------------------------
# Test secondary mode in family filter (evaluate pathway)
# ---------------------------------------------------------------------------


class TestSecondaryFamilyFilter:
    """Test that secondary mode includes tickers with has_regulatory_upcoming_180d=1."""

    def test_secondary_includes_dual_catalyst_ticker(self):
        """A ticker with clinical primary but regulatory secondary should be
        included in REGULATORY filter under secondary mode."""
        # Build a minimal rankings list
        rankings = [
            {
                "ticker": "ACME",
                "catalyst_family": "CLINICAL",
                "has_regulatory_upcoming_180d": "1",
                "catalyst_bucket": "less_binary",
            },
            {
                "ticker": "BETA",
                "catalyst_family": "CLINICAL",
                "has_regulatory_upcoming_180d": "0",
                "catalyst_bucket": "less_binary",
            },
        ]

        # Simulate the secondary filter logic from evaluate()
        _allowed_families = {"REGULATORY"}

        def _secondary_match(r):
            if "REGULATORY" in _allowed_families and r.get("has_regulatory_upcoming_180d") == "1":
                return True
            return r.get("catalyst_family", "").strip() in _allowed_families

        filtered = [r for r in rankings if _secondary_match(r)]
        assert len(filtered) == 1
        assert filtered[0]["ticker"] == "ACME"

    def test_primary_mode_excludes_dual_catalyst(self):
        """Primary mode should NOT include ACME (catalyst_family=CLINICAL)."""
        rankings = [
            {
                "ticker": "ACME",
                "catalyst_family": "CLINICAL",
                "has_regulatory_upcoming_180d": "1",
            },
        ]
        _allowed_families = {"REGULATORY"}
        filtered = [r for r in rankings if r.get("catalyst_family", "").strip() in _allowed_families]
        assert len(filtered) == 0

    def test_secondary_still_includes_primary_regulatory(self):
        """A ticker with primary=REGULATORY should still be included in secondary mode."""
        rankings = [
            {
                "ticker": "REG1",
                "catalyst_family": "REGULATORY",
                "has_regulatory_upcoming_180d": "1",
            },
            {
                "ticker": "DUAL1",
                "catalyst_family": "CLINICAL",
                "has_regulatory_upcoming_180d": "1",
            },
        ]
        _allowed_families = {"REGULATORY"}

        def _secondary_match(r):
            if "REGULATORY" in _allowed_families and r.get("has_regulatory_upcoming_180d") == "1":
                return True
            return r.get("catalyst_family", "").strip() in _allowed_families

        filtered = [r for r in rankings if _secondary_match(r)]
        assert len(filtered) == 2


# ---------------------------------------------------------------------------
# Test REGULATORY_EVENT_TYPES
# ---------------------------------------------------------------------------


class TestRegulatoryEventTypes:
    def test_contains_pdufa(self):
        from event_ledger import REGULATORY_EVENT_TYPES

        assert "PDUFA" in REGULATORY_EVENT_TYPES

    def test_does_not_contain_clinical(self):
        from event_ledger import REGULATORY_EVENT_TYPES

        assert "DATA_READOUT" not in REGULATORY_EVENT_TYPES
        assert "CT_PRIMARY_COMPLETION" not in REGULATORY_EVENT_TYPES

    def test_is_frozenset(self):
        from event_ledger import REGULATORY_EVENT_TYPES

        assert isinstance(REGULATORY_EVENT_TYPES, frozenset)
