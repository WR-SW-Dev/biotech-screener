"""Tests for common/regulatory_calendar.py loader + validator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.regulatory_calendar import get_calendar_telemetry, load_and_validate, normalize_record, validate_record

# ── fixtures ──────────────────────────────────────────────────────────


def _old_schema_record():
    """Old schema: curated_disclosed_at, confidence='confirmed'."""
    return {
        "ticker": "ACME",
        "drug_name": "DrugX",
        "indication": "Disease Y",
        "pdufa_date": "2026-05-01",
        "submission_type": "NDA",
        "confidence": "confirmed",
        "source": "company_guidance",
        "curated_disclosed_at": None,
    }


def _new_schema_record():
    """New v2 schema with as_of_disclosed_at."""
    return {
        "ticker": "ACME",
        "drug_name": "DrugX",
        "indication": "Disease Y",
        "pdufa_date": "2026-05-01",
        "event_type": "PDUFA",
        "submission_type": "NDA",
        "confidence": "HIGH",
        "source": "COMPANY_GUIDANCE",
        "as_of_disclosed_at": "2025-11-01",
        "notes": "NDA accepted",
        "program": "DrugX — Disease Y",
    }


def _write_calendar(tmp_path, records):
    p = tmp_path / "pdufa_dates.json"
    p.write_text(json.dumps(records), encoding="utf-8")
    return p


# ── normalize_record ──────────────────────────────────────────────────


class TestNormalizeRecord:
    def test_old_schema_confidence_mapping(self):
        rec = normalize_record(_old_schema_record())
        assert rec["confidence"] == "HIGH"  # "confirmed" → HIGH

    def test_old_schema_source_mapping(self):
        rec = normalize_record(_old_schema_record())
        assert rec["source"] == "COMPANY_GUIDANCE"

    def test_old_schema_event_type_default(self):
        rec = normalize_record(_old_schema_record())
        assert rec["event_type"] == "PDUFA"

    def test_old_schema_disclosed_at_empty(self):
        rec = normalize_record(_old_schema_record())
        assert rec["as_of_disclosed_at"] == ""

    def test_old_schema_program_built(self):
        rec = normalize_record(_old_schema_record())
        assert rec["program"] == "DrugX — Disease Y"

    def test_new_schema_passthrough(self):
        rec = normalize_record(_new_schema_record())
        assert rec["confidence"] == "HIGH"
        assert rec["source"] == "COMPANY_GUIDANCE"
        assert rec["event_type"] == "PDUFA"
        assert rec["as_of_disclosed_at"] == "2025-11-01"

    def test_estimated_maps_to_med(self):
        old = _old_schema_record()
        old["confidence"] = "estimated"
        rec = normalize_record(old)
        assert rec["confidence"] == "MED"

    def test_curated_disclosed_at_fallback(self):
        old = _old_schema_record()
        old["curated_disclosed_at"] = "2025-10-01"
        rec = normalize_record(old)
        assert rec["as_of_disclosed_at"] == "2025-10-01"


# ── validate_record ───────────────────────────────────────────────────


class TestValidateRecord:
    def test_valid_record_no_errors(self):
        rec = normalize_record(_new_schema_record())
        assert validate_record(rec) == []

    def test_missing_ticker(self):
        rec = normalize_record(_new_schema_record())
        rec["ticker"] = ""
        errs = validate_record(rec)
        assert any("missing ticker" in e for e in errs)

    def test_missing_date(self):
        rec = normalize_record(_new_schema_record())
        rec["pdufa_date"] = ""
        errs = validate_record(rec)
        assert any("missing pdufa_date" in e for e in errs)

    def test_invalid_date_format(self):
        rec = normalize_record(_new_schema_record())
        rec["pdufa_date"] = "May 1 2026"
        errs = validate_record(rec)
        assert any("invalid pdufa_date format" in e for e in errs)

    def test_invalid_disclosed_at_format(self):
        rec = normalize_record(_new_schema_record())
        rec["as_of_disclosed_at"] = "not-a-date"
        errs = validate_record(rec)
        assert any("invalid as_of_disclosed_at" in e for e in errs)


# ── load_and_validate ─────────────────────────────────────────────────


class TestLoadAndValidate:
    def test_loads_old_schema(self, tmp_path):
        p = _write_calendar(tmp_path, [_old_schema_record()])
        records, errors = load_and_validate(path=p)
        assert len(records) == 1
        assert records[0]["confidence"] == "HIGH"

    def test_loads_new_schema(self, tmp_path):
        p = _write_calendar(tmp_path, [_new_schema_record()])
        records, errors = load_and_validate(path=p)
        assert len(records) == 1
        assert records[0]["as_of_disclosed_at"] == "2025-11-01"

    def test_pit_filter_includes_before(self, tmp_path):
        rec = _new_schema_record()
        rec["as_of_disclosed_at"] = "2025-11-01"
        p = _write_calendar(tmp_path, [rec])
        records, _ = load_and_validate(path=p, as_of_date="2026-01-01")
        assert len(records) == 1

    def test_pit_filter_excludes_future(self, tmp_path):
        rec = _new_schema_record()
        rec["as_of_disclosed_at"] = "2026-06-01"
        p = _write_calendar(tmp_path, [rec])
        records, _ = load_and_validate(path=p, as_of_date="2026-03-09")
        assert len(records) == 0

    def test_pit_filter_undated_included_by_default(self, tmp_path):
        p = _write_calendar(tmp_path, [_old_schema_record()])
        records, _ = load_and_validate(path=p, as_of_date="2026-03-09")
        assert len(records) == 1  # undated included by default

    def test_pit_filter_undated_excluded_when_disabled(self, tmp_path):
        p = _write_calendar(tmp_path, [_old_schema_record()])
        records, _ = load_and_validate(path=p, as_of_date="2026-03-09", include_undated=False)
        assert len(records) == 0

    def test_dedupe(self, tmp_path):
        rec = _new_schema_record()
        p = _write_calendar(tmp_path, [rec, rec])  # exact duplicate
        records, errors = load_and_validate(path=p)
        assert len(records) == 1
        assert any("duplicate" in e for e in errors)

    def test_invalid_record_skipped(self, tmp_path):
        bad = {"ticker": "", "pdufa_date": ""}
        good = _new_schema_record()
        p = _write_calendar(tmp_path, [bad, good])
        records, errors = load_and_validate(path=p)
        assert len(records) == 1
        assert len(errors) > 0

    def test_empty_file(self, tmp_path):
        p = _write_calendar(tmp_path, [])
        records, errors = load_and_validate(path=p)
        assert records == []
        assert errors == []

    def test_missing_file_no_crash(self, tmp_path, monkeypatch):
        """When explicit path doesn't exist, loader falls through gracefully."""
        # Patch the fallback to avoid hitting production file
        import common.regulatory_calendar as mod

        monkeypatch.setattr(mod, "load_regulatory_calendar", lambda **kw: [])
        records, errors = load_and_validate(path=tmp_path / "nonexistent.json")
        assert records == []


# ── get_calendar_telemetry ────────────────────────────────────────────


class TestCalendarTelemetry:
    def test_telemetry_counts(self):
        recs = [
            {"event_type": "PDUFA", "confidence": "HIGH", "source": "COMPANY_GUIDANCE"},
            {"event_type": "PDUFA", "confidence": "MED", "source": "ANALYST_ESTIMATE"},
            {"event_type": "AdCom", "confidence": "HIGH", "source": "COMPANY_GUIDANCE"},
        ]
        tel = get_calendar_telemetry(recs)
        assert tel["manual_calendar_n_records"] == 3
        assert tel["manual_calendar_by_event_type"] == {"PDUFA": 2, "AdCom": 1}
        assert tel["manual_calendar_by_confidence"] == {"HIGH": 2, "MED": 1}
        assert tel["manual_calendar_by_source"] == {"COMPANY_GUIDANCE": 2, "ANALYST_ESTIMATE": 1}

    def test_empty(self):
        tel = get_calendar_telemetry([])
        assert tel["manual_calendar_loaded"] is False
        assert tel["manual_calendar_n_records"] == 0


# ── production file loads correctly ──────────────────────────────────


class TestProductionFile:
    def test_production_pdufa_dates_loads(self):
        """Smoke test: the actual production file loads without errors."""
        records, errors = load_and_validate()
        assert len(records) > 0
        # All records should have ticker and pdufa_date
        for rec in records:
            assert rec.get("ticker")
            assert rec.get("pdufa_date")
        # No validation errors expected
        assert errors == []

    def test_production_all_have_disclosed_at(self):
        """After schema upgrade, all production records should have as_of_disclosed_at."""
        records, _ = load_and_validate()
        for rec in records:
            assert rec.get("as_of_disclosed_at"), f"{rec['ticker']} missing as_of_disclosed_at"
