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
