"""Tests for find_pdufa_candidates_from_sec.py ingestion format and helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.find_pdufa_candidates_from_sec import (
    _PDUFA_KEYWORDS,
    _extract_submission_type,
    format_for_ingestion,
)
from tools.collect_pdufa_forward import validate_candidate

# ---------------------------------------------------------------------------
# Submission type extraction
# ---------------------------------------------------------------------------


class TestExtractSubmissionType:

    def test_nda(self):
        assert _extract_submission_type("FDA accepted NDA for review") == "NDA"

    def test_bla(self):
        assert _extract_submission_type("BLA submission accepted") == "BLA"

    def test_snda(self):
        assert _extract_submission_type("sNDA for new indication") == "sNDA"

    def test_sbla(self):
        assert _extract_submission_type("filed sBLA supplement") == "sBLA"

    def test_case_insensitive(self):
        assert _extract_submission_type("nda accepted") == "NDA"
        assert _extract_submission_type("Bla filing") == "BLA"

    def test_snda_before_nda(self):
        """sNDA should match before NDA when both substrings are present."""
        assert _extract_submission_type("sNDA supplement for drug") == "sNDA"

    def test_no_match(self):
        assert _extract_submission_type("Phase 3 data readout") == ""

    def test_empty(self):
        assert _extract_submission_type("") == ""


# ---------------------------------------------------------------------------
# Ingestion format
# ---------------------------------------------------------------------------


def _make_discovery(
    ticker="ACME",
    event_type="FDA_NDA_ACCEPTANCE",
    event_date="2026-08-15",
    disclosed_at="2026-03-01",
    confidence="HIGH",
    keyword_excerpt="8-K: FDA accepted NDA for AcmeDrug with PDUFA date August 15, 2026",
    dates_found="August 15, 2026",
    source_file="8k_catalysts_2026-03-01_abc123.json",
):
    return {
        "ticker": ticker,
        "event_type": event_type,
        "event_date": event_date,
        "disclosed_at": disclosed_at,
        "confidence": confidence,
        "keyword_excerpt": keyword_excerpt,
        "dates_found": dates_found,
        "source_file": source_file,
    }


class TestFormatForIngestion:

    def test_field_mapping(self):
        records = format_for_ingestion([_make_discovery()], as_of_date="2026-03-13")
        assert len(records) == 1
        r = records[0]
        assert r["ticker"] == "ACME"
        assert r["pdufa_date"] == "2026-08-15"
        assert r["as_of_disclosed_at"] == "2026-03-01"
        assert r["source"] == "SEC_8K"
        assert r["event_type"] == "PDUFA"

    def test_submission_type_extracted(self):
        records = format_for_ingestion([_make_discovery()])
        assert records[0]["submission_type"] == "NDA"

    def test_source_url_empty_for_review(self):
        records = format_for_ingestion([_make_discovery()])
        assert records[0]["source_url"] == ""

    def test_drug_name_empty_for_review(self):
        records = format_for_ingestion([_make_discovery()])
        assert records[0]["drug_name"] == ""

    def test_review_status_marker(self):
        records = format_for_ingestion([_make_discovery()])
        assert records[0]["_review_status"] == "NEEDS_REVIEW"

    def test_notes_contain_keyword_excerpt(self):
        records = format_for_ingestion([_make_discovery()])
        assert "NDA for AcmeDrug" in records[0]["notes"]

    def test_notes_contain_dates_found(self):
        records = format_for_ingestion([_make_discovery()])
        assert "August 15, 2026" in records[0]["notes"]

    def test_notes_contain_source_file(self):
        records = format_for_ingestion([_make_discovery()])
        assert "8k_catalysts_2026-03-01" in records[0]["notes"]

    def test_multiple_candidates(self):
        candidates = [
            _make_discovery(ticker="ACME"),
            _make_discovery(ticker="BETA", keyword_excerpt="BLA filed for Beta"),
        ]
        records = format_for_ingestion(candidates)
        assert len(records) == 2
        assert records[0]["ticker"] == "ACME"
        assert records[1]["ticker"] == "BETA"
        assert records[1]["submission_type"] == "BLA"

    def test_empty_input(self):
        assert format_for_ingestion([]) == []


# ---------------------------------------------------------------------------
# Round-trip: ingestion record validates via collect_pdufa_forward
# ---------------------------------------------------------------------------


class TestIngestionRoundTrip:
    """After a reviewer fills in source_url, the record should pass validation."""

    def test_reviewed_record_passes_validation(self):
        records = format_for_ingestion([_make_discovery()], as_of_date="2026-03-13")
        r = records[0]
        # Simulate reviewer filling in required fields
        r["source_url"] = "https://www.sec.gov/Archives/edgar/data/12345/filing.htm"
        r["drug_name"] = "AcmeDrug"
        r["indication"] = "cancer"
        ok, errors = validate_candidate(r)
        assert ok, f"Validation failed: {errors}"

    def test_unreviewed_record_passes_required_fields(self):
        """Even without source_url, required fields should be present."""
        records = format_for_ingestion([_make_discovery()], as_of_date="2026-03-13")
        r = records[0]
        ok, errors = validate_candidate(r)
        # Should pass — source_url is recommended, not required
        assert ok, f"Validation failed: {errors}"

    def test_missing_event_date_fails_validation(self):
        """If scanner has no event_date, pdufa_date will be empty → fail."""
        records = format_for_ingestion(
            [_make_discovery(event_date="")],
            as_of_date="2026-03-13",
        )
        r = records[0]
        ok, errors = validate_candidate(r)
        assert not ok
        assert any("pdufa_date" in e for e in errors)

    def test_internal_fields_stripped_by_ingest(self):
        """_review_status and _source_file should be stripped during ingest."""
        records = format_for_ingestion([_make_discovery()])
        r = records[0]
        assert "_review_status" in r
        assert "_source_file" in r
        # collect_pdufa_forward.ingest_candidates strips _ prefix fields
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        assert "_review_status" not in clean
        assert "_source_file" not in clean
        assert "ticker" in clean


# ---------------------------------------------------------------------------
# Keyword regex coverage
# ---------------------------------------------------------------------------


class TestKeywordRegex:
    """Verify _PDUFA_KEYWORDS matches all intended phrases."""

    @pytest.mark.parametrize(
        "text",
        [
            # Original keywords
            "PDUFA date set for August",
            "NDA accepted for filing",
            "BLA submission",
            "sNDA supplement filed",
            "sBLA for new formulation",
            "action date of August 15",
            "target date is Q3 2026",
            "user fee act",
            "prescription drug user fee",
            "priority review granted",
            "standard review timeline",
            "complete response letter received",
            "accepted for filing",
            "acceptance for review",
            # Expanded keywords (B.A)
            "FDA action date is August 15, 2026",
            "target action date set for July",
            "DUFA date extended",
            "filing accepted by FDA",
            "advisory committee meeting scheduled",
            "ADCOM panel convened",
            "complete response from FDA",
        ],
    )
    def test_keyword_matches(self, text):
        assert _PDUFA_KEYWORDS.search(text), f"Expected match for: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "Phase 3 topline data readout",
            "quarterly earnings report",
            "stock split announced",
            "board meeting scheduled",
        ],
    )
    def test_keyword_no_false_positives(self, text):
        assert not _PDUFA_KEYWORDS.search(text), f"Unexpected match for: {text!r}"
