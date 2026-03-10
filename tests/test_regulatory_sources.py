"""Tests for multi-source regulatory coverage in _nearest_regulatory_catalyst."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from event_ledger import REGULATORY_EVENT_TYPES

# Import the function under test from run_screen
from run_screen import _nearest_regulatory_catalyst


@dataclass(frozen=True)
class FakeLedgerEntry:
    """Lightweight stand-in for LedgerEntry."""

    event_id: str = "e1"
    ticker: str = ""
    event_type: str = ""
    event_date: Optional[str] = None
    event_date_end: Optional[str] = None
    date_precision: str = "DAY"
    disclosed_at: str = "2026-01-01"
    source: str = "FDA_ADCOM"
    source_uid: str = ""
    confidence: str = "HIGH"
    extractor_version: str = "1.0"
    event_name: str = ""
    field_changed: str = ""
    value: str = ""
    tags: Tuple[str, ...] = ()


class TestM3Source:
    """Source 1: M3 scored events."""

    def test_m3_pdufa_found(self):
        m3 = {"ACME": {"events": [{"event_type": "PDUFA", "event_date": "2026-04-01"}]}}
        days, et = _nearest_regulatory_catalyst(m3, "ACME", "2026-03-01")
        assert days == "31"
        assert et == "PDUFA"

    def test_m3_non_regulatory_skipped(self):
        m3 = {"ACME": {"events": [{"event_type": "DATA_READOUT", "event_date": "2026-04-01"}]}}
        days, et = _nearest_regulatory_catalyst(m3, "ACME", "2026-03-01")
        assert days == ""
        assert et == ""

    def test_m3_past_event_ignored(self):
        m3 = {"ACME": {"events": [{"event_type": "PDUFA", "event_date": "2026-02-01"}]}}
        days, et = _nearest_regulatory_catalyst(m3, "ACME", "2026-03-01")
        assert days == ""

    def test_m3_none_summaries(self):
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01")
        assert days == ""


class TestLedgerSource:
    """Source 2: Event ledger entries (FDA ADCOM, EMA, etc.)."""

    def test_ledger_fda_adcom(self):
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="FDA_ADCOM",
                event_date="2026-04-15",
                confidence="HIGH",
            )
        ]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == "45"
        assert et == "FDA_ADCOM"

    def test_ledger_ema_committee(self):
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="EMA_COMMITTEE_AGENDA",
                event_date="2026-05-01",
                confidence="MED",
            )
        ]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == "61"
        assert et == "EMA_COMMITTEE_AGENDA"

    def test_ledger_low_confidence_skipped(self):
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="PDUFA",
                event_date="2026-04-01",
                confidence="LOW",
            )
        ]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == ""

    def test_ledger_wrong_ticker_skipped(self):
        ledger = [
            FakeLedgerEntry(
                ticker="OTHER",
                event_type="FDA_ADCOM",
                event_date="2026-04-01",
                confidence="HIGH",
            )
        ]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == ""

    def test_ledger_beyond_max_days_skipped(self):
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="FDA_ADCOM",
                event_date="2027-01-01",
                confidence="HIGH",
            )
        ]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == ""  # >180 days


class TestPDUFAManualSource:
    """Source 3: PDUFA manual fallback."""

    def test_pdufa_manual_found(self):
        pdufa = [{"ticker": "ACME", "pdufa_date": "2026-05-15"}]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", pdufa_manual=pdufa)
        assert days == "75"
        assert et == "PDUFA"

    def test_pdufa_manual_case_insensitive(self):
        pdufa = [{"ticker": "acme", "pdufa_date": "2026-05-15"}]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", pdufa_manual=pdufa)
        assert days == "75"


class TestMultiSourcePriority:
    """When multiple sources have events, the nearest wins."""

    def test_ledger_beats_pdufa_when_closer(self):
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="FDA_ADCOM",
                event_date="2026-03-15",
                confidence="HIGH",
            )
        ]
        pdufa = [{"ticker": "ACME", "pdufa_date": "2026-05-15"}]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", pdufa_manual=pdufa, event_ledger=ledger)
        assert days == "14"
        assert et == "FDA_ADCOM"

    def test_pdufa_beats_ledger_when_closer(self):
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="FDA_ADCOM",
                event_date="2026-06-01",
                confidence="HIGH",
            )
        ]
        pdufa = [{"ticker": "ACME", "pdufa_date": "2026-03-15"}]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", pdufa_manual=pdufa, event_ledger=ledger)
        assert days == "14"
        assert et == "PDUFA"

    def test_m3_and_ledger_nearest_wins(self):
        m3 = {"ACME": {"events": [{"event_type": "FDA_SUBMISSION", "event_date": "2026-04-01"}]}}
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="FDA_ADCOM",
                event_date="2026-03-10",
                confidence="HIGH",
            )
        ]
        days, et = _nearest_regulatory_catalyst(m3, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == "9"
        assert et == "FDA_ADCOM"

    def test_all_three_sources(self):
        m3 = {"ACME": {"events": [{"event_type": "PDUFA", "event_date": "2026-06-01"}]}}
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="EMA_OUTCOME",
                event_date="2026-05-01",
                confidence="HIGH",
            )
        ]
        pdufa = [{"ticker": "ACME", "pdufa_date": "2026-04-01"}]
        days, et = _nearest_regulatory_catalyst(m3, "ACME", "2026-03-01", pdufa_manual=pdufa, event_ledger=ledger)
        assert days == "31"
        assert et == "PDUFA"  # PDUFA manual is closest


class TestPITSafety:
    """Ensure PIT discipline: no future-looking data leakage."""

    def test_event_on_as_of_date_excluded(self):
        """Events ON the as_of_date are past, not future."""
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="FDA_ADCOM",
                event_date="2026-03-01",
                confidence="HIGH",
            )
        ]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == ""

    def test_event_one_day_ahead_included(self):
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="FDA_ADCOM",
                event_date="2026-03-02",
                confidence="HIGH",
            )
        ]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == "1"


class TestEdgeCases:
    def test_empty_event_date_skipped(self):
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="FDA_ADCOM",
                event_date="",
                confidence="HIGH",
            )
        ]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == ""

    def test_none_event_date_skipped(self):
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="FDA_ADCOM",
                event_date=None,
                confidence="HIGH",
            )
        ]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == ""

    def test_non_regulatory_ledger_type_skipped(self):
        ledger = [
            FakeLedgerEntry(
                ticker="ACME",
                event_type="CLINICAL_TRIAL_START",
                event_date="2026-04-01",
                confidence="HIGH",
            )
        ]
        days, et = _nearest_regulatory_catalyst(None, "ACME", "2026-03-01", event_ledger=ledger)
        assert days == ""

    def test_regulatory_event_types_frozenset(self):
        """Sanity: key regulatory types are in the set."""
        for et in ("PDUFA", "FDA_ADCOM", "FDA_APPROVAL", "EMA_COMMITTEE_AGENDA"):
            assert et in REGULATORY_EVENT_TYPES
