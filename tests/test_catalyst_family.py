"""Tests for catalyst family classification + PDUFA confidence fix.

Validates:
  1. CATALYST_FAMILY_MAP covers all expected event types
  2. classify_catalyst_family() returns correct families
  3. PDUFA confirmed entries get MED confidence (visible to nearest-catalyst query)
  4. PDUFA unconfirmed entries stay LOW (filtered out)
  5. Backfill derives catalyst_family from catalyst_event_type
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# A) Family classification mapping
# ---------------------------------------------------------------------------


class TestCatalystFamilyMap:
    def test_regulatory_types(self):
        from event_ledger import classify_catalyst_family

        regulatory = [
            "PDUFA",
            "FDA_PDUFA_DATE",
            "FDA_ADCOM",
            "FDA_APPROVAL",
            "FDA_SUBMISSION",
            "FDA_DESIGNATION",
            "FDA_CRL",
            "FDA_RTF",
            "FDA_DECISION",
            "EMA_AGENDA",
            "EMA_OUTCOME",
            "EMA_COMMITTEE_AGENDA",
            "EMA_COMMITTEE_OUTCOME",
        ]
        for et in regulatory:
            assert classify_catalyst_family(et) == "REGULATORY", f"{et} should be REGULATORY"

    def test_clinical_types(self):
        from event_ledger import classify_catalyst_family

        clinical = [
            "CLINICAL_PCD",
            "CLINICAL_CD",
            "CT_PRIMARY_COMPLETION",
            "CT_STUDY_COMPLETION",
            "CT_RESULTS_POSTED",
            "CT_DATE_CONFIRMED_ACTUAL",
            "DATA_READOUT",
            "DATA_PRESENTATION",
            "DATA_PUBLICATION",
            "CT_STATUS_UPGRADE",
            "CT_TIMELINE_PULLIN",
            "CT_TIMELINE_PUSHOUT",
            "CT_ACTIVITY_PROXY",
        ]
        for et in clinical:
            assert classify_catalyst_family(et) == "CLINICAL", f"{et} should be CLINICAL"

    def test_safety_types(self):
        from event_ledger import classify_catalyst_family

        safety = [
            "CLINICAL_HOLD",
            "SAFETY_SIGNAL",
            "FDA_WARNING_LETTER",
            "CT_TRIAL_TERMINATED",
            "CT_TRIAL_WITHDRAWN",
            "CT_TRIAL_SUSPENDED",
            "CT_STATUS_DOWNGRADE",
            "CT_STATUS_SEVERE_NEG",
        ]
        for et in safety:
            assert classify_catalyst_family(et) == "SAFETY", f"{et} should be SAFETY"

    def test_unknown_returns_empty(self):
        from event_ledger import classify_catalyst_family

        assert classify_catalyst_family("") == ""
        assert classify_catalyst_family("EARNINGS_RELEASE") == ""
        assert classify_catalyst_family("CONFERENCE_PRESENTATION") == ""
        assert classify_catalyst_family("UNKNOWN") == ""

    def test_empty_event_type(self):
        from event_ledger import classify_catalyst_family

        assert classify_catalyst_family("") == ""


# ---------------------------------------------------------------------------
# B) PDUFA confidence fix
# ---------------------------------------------------------------------------


class TestPDUFAConfidence:
    def test_confirmed_gets_med(self, tmp_path):
        from event_ledger import _load_pdufa_events

        pdufa = [
            {
                "ticker": "CYTK",
                "drug_name": "Aficamten",
                "indication": "HCM",
                "pdufa_date": "2026-03-28",
                "submission_type": "NDA",
                "confidence": "confirmed",
                "source": "company_guidance",
                "curated_disclosed_at": None,
            }
        ]
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "pdufa_dates.json").write_text(json.dumps(pdufa))

        entries = _load_pdufa_events(data_dir)
        assert len(entries) == 1
        assert entries[0].confidence == "MED"
        assert entries[0].event_type == "PDUFA"

    def test_curated_gets_high(self, tmp_path):
        from event_ledger import _load_pdufa_events

        pdufa = [
            {
                "ticker": "CYTK",
                "drug_name": "Aficamten",
                "indication": "HCM",
                "pdufa_date": "2026-03-28",
                "submission_type": "NDA",
                "confidence": "confirmed",
                "source": "company_guidance",
                "curated_disclosed_at": "2025-09-15",
            }
        ]
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "pdufa_dates.json").write_text(json.dumps(pdufa))

        entries = _load_pdufa_events(data_dir)
        assert len(entries) == 1
        assert entries[0].confidence == "HIGH"
        assert "missing_disclosed_at" not in entries[0].tags

    def test_unconfirmed_stays_low(self, tmp_path):
        from event_ledger import _load_pdufa_events

        pdufa = [
            {
                "ticker": "FAKE",
                "drug_name": "Test",
                "indication": "Test",
                "pdufa_date": "2026-06-01",
                "submission_type": "NDA",
                "source": "rumor",
                "curated_disclosed_at": None,
            }
        ]
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "pdufa_dates.json").write_text(json.dumps(pdufa))

        entries = _load_pdufa_events(data_dir)
        assert len(entries) == 1
        assert entries[0].confidence == "LOW"

    def test_confirmed_pdufa_visible_in_nearest_query(self, tmp_path):
        """MED confidence PDUFA entries are NOT filtered by query_nearest_catalyst."""
        from datetime import date

        from event_ledger import _load_pdufa_events, query_nearest_catalyst

        pdufa = [
            {
                "ticker": "INSM",
                "drug_name": "Brensocatib",
                "indication": "Bronchiectasis",
                "pdufa_date": "2026-03-14",
                "submission_type": "NDA",
                "confidence": "confirmed",
                "source": "company_guidance",
                "curated_disclosed_at": None,
            }
        ]
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "pdufa_dates.json").write_text(json.dumps(pdufa))

        entries = _load_pdufa_events(data_dir)
        result = query_nearest_catalyst(entries, "INSM", date(2026, 3, 8))

        assert result is not None
        assert result["event_type"] == "PDUFA"
        assert result["days_to_catalyst"] == 6

    def test_unconfirmed_pdufa_filtered_by_nearest_query(self, tmp_path):
        """LOW confidence PDUFA entries ARE filtered by query_nearest_catalyst."""
        from datetime import date

        from event_ledger import _load_pdufa_events, query_nearest_catalyst

        pdufa = [
            {
                "ticker": "FAKE",
                "drug_name": "Test",
                "indication": "Test",
                "pdufa_date": "2026-04-01",
                "submission_type": "NDA",
                "source": "rumor",
                "curated_disclosed_at": None,
            }
        ]
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "pdufa_dates.json").write_text(json.dumps(pdufa))

        entries = _load_pdufa_events(data_dir)
        result = query_nearest_catalyst(entries, "FAKE", date(2026, 3, 8))

        assert result is None  # LOW confidence filtered out


# ---------------------------------------------------------------------------
# C) Backfill: catalyst_family derived from catalyst_event_type
# ---------------------------------------------------------------------------


class TestBackfillCatalystFamily:
    def test_backfill_derives_family(self):
        from common.ranking_utils import backfill_columns

        rows = [
            {"catalyst_event_type": "CT_PRIMARY_COMPLETION"},
            {"catalyst_event_type": "FDA_PDUFA_DATE"},
            {"catalyst_event_type": "DATA_READOUT"},
            {"catalyst_event_type": ""},
        ]
        backfill_columns(rows)
        assert rows[0]["catalyst_family"] == "CLINICAL"
        assert rows[1]["catalyst_family"] == "REGULATORY"
        assert rows[2]["catalyst_family"] == "CLINICAL"
        assert rows[3]["catalyst_family"] == ""

    def test_existing_family_not_overwritten(self):
        from common.ranking_utils import backfill_columns

        rows = [
            {"catalyst_event_type": "CT_PRIMARY_COMPLETION", "catalyst_family": "CUSTOM"},
        ]
        backfill_columns(rows)
        assert rows[0]["catalyst_family"] == "CUSTOM"


# ---------------------------------------------------------------------------
# D) PDUFA family classification
# ---------------------------------------------------------------------------


class TestPDUFAFamily:
    def test_pdufa_is_regulatory(self):
        from event_ledger import classify_catalyst_family

        assert classify_catalyst_family("PDUFA") == "REGULATORY"


# ---------------------------------------------------------------------------
# E) _find_nearest_catalyst_event: four-tier lookup
# ---------------------------------------------------------------------------


def _make_m3(
    ticker,
    next_date,
    source_uid="",
    events=None,
):
    """Build minimal M3 summaries dict for _find_nearest_catalyst_event."""
    return {
        ticker: {
            "integration": {
                "next_catalyst_date": next_date,
                "nearest_catalyst_source_uid": source_uid,
            },
            "events": events or [],
        }
    }


class TestFindNearestCatalystEvent:

    def test_tier1_exact_date_match(self):
        from run_screen import _find_nearest_catalyst_event

        m3 = _make_m3(
            "ACME",
            "2026-06-01",
            events=[
                {"event_date": "2026-06-01", "event_type": "DATA_READOUT", "source": "CTGOV_CALENDAR"},
                {"event_date": "2026-09-01", "event_type": "CT_PRIMARY_COMPLETION", "source": "CTGOV_CALENDAR"},
            ],
        )
        ev = _find_nearest_catalyst_event(m3, "ACME")
        assert ev["event_type"] == "DATA_READOUT"
        assert ev["event_date"] == "2026-06-01"

    def test_tier2_fuzzy_match_within_14d(self):
        from run_screen import _find_nearest_catalyst_event

        m3 = _make_m3(
            "JAZZ",
            "2026-04-01",
            events=[
                {"event_date": "2026-03-26", "event_type": "CT_PRIMARY_COMPLETION", "source": "CTGOV_CALENDAR"},
                {"event_date": "2026-09-01", "event_type": "CT_STUDY_COMPLETION", "source": "CTGOV_CALENDAR"},
            ],
        )
        ev = _find_nearest_catalyst_event(m3, "JAZZ")
        assert ev["event_type"] == "CT_PRIMARY_COMPLETION"
        assert ev["event_date"] == "2026-03-26"

    def test_tier2_picks_closest(self):
        from run_screen import _find_nearest_catalyst_event

        m3 = _make_m3(
            "TEM",
            "2026-04-01",
            events=[
                {"event_date": "2026-03-20", "event_type": "DATA_READOUT", "source": "CTGOV_CALENDAR"},
                {"event_date": "2026-03-31", "event_type": "CT_PRIMARY_COMPLETION", "source": "CTGOV_CALENDAR"},
            ],
        )
        ev = _find_nearest_catalyst_event(m3, "TEM")
        assert ev["event_type"] == "CT_PRIMARY_COMPLETION"
        assert ev["event_date"] == "2026-03-31"

    def test_tier2_outside_14d_falls_through(self):
        """Events >14d away from next_catalyst_date should not match tier 2."""
        from run_screen import _find_nearest_catalyst_event

        m3 = _make_m3(
            "VERA",
            "2026-03-15",
            source_uid="NCT05609812",
            events=[
                {"event_date": "2026-09-01", "event_type": "CT_PRIMARY_COMPLETION", "source": "CTGOV_CALENDAR"},
            ],
        )
        ev = _find_nearest_catalyst_event(m3, "VERA")
        # Should fall through to tier 3 (NCT inference), not match the distant event
        assert ev["event_type"] == "CT_PRIMARY_COMPLETION"
        assert ev.get("_inferred") is True

    def test_tier3_nct_source_uid_infers_clinical(self):
        from run_screen import _find_nearest_catalyst_event

        m3 = _make_m3("FATE", "2026-05-01", source_uid="NCT05934097", events=[])
        ev = _find_nearest_catalyst_event(m3, "FATE")
        assert ev is not None
        assert ev["event_type"] == "CT_PRIMARY_COMPLETION"
        assert ev["source"] == "CTGOV_CALENDAR"
        assert ev.get("_inferred") is True

    def test_tier3_non_nct_returns_none(self):
        from run_screen import _find_nearest_catalyst_event

        m3 = _make_m3("FAKE", "2026-05-01", source_uid="SEC_12345", events=[])
        ev = _find_nearest_catalyst_event(m3, "FAKE")
        assert ev is None

    def test_no_m3_summaries(self):
        from run_screen import _find_nearest_catalyst_event

        assert _find_nearest_catalyst_event(None, "ACME") is None
        assert _find_nearest_catalyst_event({}, "ACME") is None

    def test_no_next_catalyst_date(self):
        from run_screen import _find_nearest_catalyst_event

        m3 = {"ACME": {"integration": {}, "events": []}}
        assert _find_nearest_catalyst_event(m3, "ACME") is None

    def test_source_and_event_type_helpers(self):
        """_nearest_catalyst_source and _nearest_catalyst_event_type use the new lookup."""
        from run_screen import _nearest_catalyst_event_type, _nearest_catalyst_source

        m3 = _make_m3("FATE", "2026-05-01", source_uid="NCT05934097", events=[])
        assert _nearest_catalyst_event_type(m3, "FATE") == "CT_PRIMARY_COMPLETION"
        assert _nearest_catalyst_source(m3, "FATE") == "CTGOV_CALENDAR"

    def test_family_from_inferred_event(self):
        """classify_catalyst_family should work on the inferred event_type."""
        from event_ledger import classify_catalyst_family
        from run_screen import _nearest_catalyst_event_type

        m3 = _make_m3("FATE", "2026-05-01", source_uid="NCT05934097", events=[])
        et = _nearest_catalyst_event_type(m3, "FATE")
        assert classify_catalyst_family(et) == "CLINICAL"

    # --- Tier 0: earliest future event when next_catalyst_date is null ---

    def test_tier0_picks_earliest_future_event(self):
        """When next_catalyst_date is null, pick earliest future event."""
        from run_screen import _find_nearest_catalyst_event

        m3 = _make_m3(
            "ESPR",
            None,  # integration didn't select a date
            events=[
                {"event_date": "2026-01-15", "event_type": "DATA_READOUT", "source": "CTGOV_CALENDAR"},
                {"event_date": "2026-03-30", "event_type": "DATA_READOUT", "source": "CTGOV_CALENDAR"},
                {"event_date": "2026-07-30", "event_type": "CT_STUDY_COMPLETION", "source": "CTGOV_CALENDAR"},
            ],
        )
        ev = _find_nearest_catalyst_event(m3, "ESPR", as_of_date="2026-03-13")
        assert ev["event_date"] == "2026-03-30"
        assert ev["event_type"] == "DATA_READOUT"

    def test_tier0_skips_past_events(self):
        """Tier 0 should only consider events after as_of_date."""
        from run_screen import _find_nearest_catalyst_event

        m3 = _make_m3(
            "LENZ",
            None,
            events=[
                {"event_date": "2026-02-25", "event_type": "CT_RESULTS_POSTED", "source": "CTGOV_CALENDAR"},
            ],
        )
        ev = _find_nearest_catalyst_event(m3, "LENZ", as_of_date="2026-03-13")
        assert ev is None  # only event is in the past

    def test_tier0_no_events_returns_none(self):
        from run_screen import _find_nearest_catalyst_event

        m3 = _make_m3("FAKE", None, events=[])
        assert _find_nearest_catalyst_event(m3, "FAKE", as_of_date="2026-03-13") is None

    def test_tier0_does_not_fire_when_next_date_exists(self):
        """Tier 0 only activates when next_catalyst_date is null."""
        from run_screen import _find_nearest_catalyst_event

        m3 = _make_m3(
            "ACME",
            "2026-06-01",
            events=[
                {"event_date": "2026-04-01", "event_type": "DATA_READOUT", "source": "CTGOV_CALENDAR"},
                {"event_date": "2026-06-01", "event_type": "CT_PRIMARY_COMPLETION", "source": "CTGOV_CALENDAR"},
            ],
        )
        # Should use tier 1 (exact match), not tier 0
        ev = _find_nearest_catalyst_event(m3, "ACME", as_of_date="2026-03-13")
        assert ev["event_date"] == "2026-06-01"

    def test_tier0_family_classification(self):
        """Tier 0 result should classify into correct family."""
        from event_ledger import classify_catalyst_family
        from run_screen import _nearest_catalyst_event_type

        m3 = _make_m3(
            "ESPR",
            None,
            events=[
                {"event_date": "2026-03-30", "event_type": "DATA_READOUT", "source": "CTGOV_CALENDAR"},
            ],
        )
        et = _nearest_catalyst_event_type(m3, "ESPR", as_of_date="2026-03-13")
        assert classify_catalyst_family(et) == "CLINICAL"
