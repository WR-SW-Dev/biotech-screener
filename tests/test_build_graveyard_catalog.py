"""Tests for graveyard catalog builder (Spec 033, Phase A)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.research.build_graveyard_catalog import (
    _days_between,
    _graveyard_id,
    _infer_failure_reason,
    _normalize_phase,
    build_graveyard_from_catalog,
)

# --- Fixtures ---


def _trial(
    ticker="TEST",
    nct_id="NCT00000001",
    status="TERMINATED",
    phase="PHASE2",
    last_update="2025-06-01",
    title="Test Trial",
    sponsor="Test Inc",
    has_results=False,
    completion_date="2025-01-01",
):
    return {
        "ticker": ticker,
        "nct_id": nct_id,
        "title": title,
        "phase": phase,
        "status": status,
        "sponsor": sponsor,
        "first_posted": "2023-01-01",
        "last_update_posted": last_update,
        "results_first_posted": last_update if has_results else None,
        "primary_completion_date": completion_date,
        "completion_date": completion_date,
        "data_available_as_of": "2023-01-01",
        "results_available_as_of": last_update if has_results else None,
        "pit_date_used": "first_posted",
        "design": {
            "enrollment": None,
            "enrollment_bucket": "unknown",
            "biomarker_selected": False,
            "endpoint_class": "other",
        },
        "lifecycle": {
            "is_completed": status == "COMPLETED",
            "is_terminated": status == "TERMINATED",
            "has_posted_results": has_results,
        },
        "provenance": {"source": "CTGOV", "collected_at": "2026-01-01"},
    }


# --- Unit tests ---


class TestNormalizePhase:
    def test_standard_phases(self):
        assert _normalize_phase("PHASE1") == "phase1"
        assert _normalize_phase("PHASE2") == "phase2"
        assert _normalize_phase("PHASE3") == "phase3"

    def test_early_phase(self):
        assert _normalize_phase("EARLY_PHASE1") == "phase1"

    def test_empty(self):
        assert _normalize_phase("") == "unknown"
        assert _normalize_phase("NA") == "unknown"


class TestGraveyardId:
    def test_deterministic(self):
        id1 = _graveyard_id("TEST", "NCT001", "TERMINATED")
        id2 = _graveyard_id("TEST", "NCT001", "TERMINATED")
        assert id1 == id2

    def test_different_inputs(self):
        id1 = _graveyard_id("TEST", "NCT001", "TERMINATED")
        id2 = _graveyard_id("TEST", "NCT002", "TERMINATED")
        assert id1 != id2

    def test_length(self):
        gid = _graveyard_id("TEST", "NCT001", "TERMINATED")
        assert len(gid) == 12


class TestDaysBetween:
    def test_normal(self):
        assert _days_between("2025-01-01", "2025-01-31") == 30

    def test_none_input(self):
        assert _days_between(None, "2025-01-01") is None
        assert _days_between("2025-01-01", None) is None


class TestInferFailureReason:
    def test_safety_keyword(self):
        trial = _trial(title="Phase 1 Safety and Tolerability of Drug X")
        assert _infer_failure_reason(trial) == "SAFETY"

    def test_terminated_unknown(self):
        trial = _trial(title="Phase 2 Efficacy Study")
        assert _infer_failure_reason(trial) == "UNKNOWN"

    def test_withdrawn_operational(self):
        trial = _trial(status="WITHDRAWN")
        assert _infer_failure_reason(trial) == "OPERATIONAL"


# --- Core builder tests ---


class TestBuildGraveyardFromCatalog:
    def test_terminated_creates_record(self):
        trials = [_trial(status="TERMINATED")]
        records = build_graveyard_from_catalog(trials, {}, [])
        assert len(records) == 1
        assert records[0]["event_type"] == "PROGRAM_TERMINATED"
        assert records[0]["confidence"] == "HIGH"
        assert records[0]["pit_safe"] is True

    def test_withdrawn_creates_record(self):
        trials = [_trial(status="WITHDRAWN")]
        records = build_graveyard_from_catalog(trials, {}, [])
        assert len(records) == 1
        assert records[0]["event_type"] == "TRIAL_WITHDRAWN"
        assert records[0]["confidence"] == "HIGH"

    def test_completed_no_results_long_lag(self):
        """Completed trials with >2yr lag and no results → MEDIUM confidence."""
        trials = [_trial(status="COMPLETED", completion_date="2022-01-01", last_update="2025-06-01", has_results=False)]
        records = build_graveyard_from_catalog(trials, {}, [])
        assert len(records) == 1
        assert records[0]["event_type"] == "COMPLETED_NO_RESULTS"
        assert records[0]["confidence"] == "MEDIUM"

    def test_completed_no_results_short_lag_excluded(self):
        """Completed trials with short lag are NOT graveyard candidates."""
        trials = [_trial(status="COMPLETED", completion_date="2025-01-01", last_update="2025-06-01", has_results=False)]
        records = build_graveyard_from_catalog(trials, {}, [])
        assert len(records) == 0

    def test_completed_with_results_excluded(self):
        """Completed trials WITH posted results are not graveyard."""
        trials = [_trial(status="COMPLETED", has_results=True)]
        records = build_graveyard_from_catalog(trials, {}, [])
        assert len(records) == 0

    def test_recruiting_excluded(self):
        """Active trials are not graveyard candidates."""
        trials = [_trial(status="RECRUITING")]
        records = build_graveyard_from_catalog(trials, {}, [])
        assert len(records) == 0

    def test_dedup(self):
        """Same trial processed twice → only one record."""
        trial = _trial()
        records = build_graveyard_from_catalog([trial, trial], {}, [])
        assert len(records) == 1

    def test_label_attached(self):
        """When outcome label exists, it's attached to the record."""
        trials = [_trial(nct_id="NCT123")]
        labels = {"NCT123": {"nct_id": "NCT123", "binary_outcome": 0, "confidence": "high"}}
        records = build_graveyard_from_catalog(trials, labels, [])
        assert records[0]["has_outcome_label"] is True
        assert records[0]["outcome_label"] == 0


# --- PIT safety tests ---


class TestPITSafety:
    def test_future_event_filtered(self):
        """Events after as_of_date are excluded."""
        trials = [_trial(last_update="2026-06-01")]
        records = build_graveyard_from_catalog(trials, {}, [], as_of_date="2026-01-01")
        assert len(records) == 0

    def test_past_event_included(self):
        """Events before as_of_date are included."""
        trials = [_trial(last_update="2025-06-01")]
        records = build_graveyard_from_catalog(trials, {}, [], as_of_date="2026-01-01")
        assert len(records) == 1

    def test_manual_event_without_timestamp_rejected(self):
        """Manual events without data_available_as_of are skipped."""
        manual = [{"ticker": "TEST", "event_type": "DELISTED"}]
        records = build_graveyard_from_catalog([], {}, manual)
        assert len(records) == 0

    def test_manual_event_with_timestamp_accepted(self):
        """Manual events with proper timestamp are included."""
        manual = [
            {
                "ticker": "TEST",
                "event_type": "DELISTED",
                "event_date": "2025-06-01",
                "data_available_as_of": "2025-06-01",
                "source_ref": "manual",
                "confidence": "HIGH",
            }
        ]
        records = build_graveyard_from_catalog([], {}, manual)
        assert len(records) == 1
        assert records[0]["pit_safe"] is True

    def test_manual_event_future_filtered(self):
        """Manual events after as_of_date are excluded."""
        manual = [
            {
                "ticker": "TEST",
                "event_type": "DELISTED",
                "event_date": "2026-06-01",
                "data_available_as_of": "2026-06-01",
                "source_ref": "manual",
            }
        ]
        records = build_graveyard_from_catalog([], {}, manual, as_of_date="2026-01-01")
        assert len(records) == 0


# --- Multiple tickers ---


class TestMultipleTickers:
    def test_multiple_tickers_multiple_records(self):
        trials = [
            _trial(ticker="AAA", nct_id="NCT001"),
            _trial(ticker="BBB", nct_id="NCT002"),
            _trial(ticker="AAA", nct_id="NCT003"),
        ]
        records = build_graveyard_from_catalog(trials, {}, [])
        assert len(records) == 3
        tickers = {r["ticker"] for r in records}
        assert tickers == {"AAA", "BBB"}
