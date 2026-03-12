"""Tests for tools/import_adcom_outcomes.py — AdCom outcomes importer/normalizer."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from tools.import_adcom_outcomes import (
    VALID_FDA_OUTCOMES,
    VALID_QUESTION_TYPES,
    audit_existing,
    coverage_summary,
    dedup_candidates,
    ingest_candidates,
    normalize_record,
    validate_candidate,
    validate_candidates,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEMA = "adcom_outcomes.v3"


def _make_candidate(**overrides) -> Dict[str, Any]:
    base = {
        "meeting_date": "2023-06-15",
        "committee": "Oncologic Drugs Advisory Committee",
        "question_type": "APPROVAL",
        "vote_yes": 10,
        "vote_no": 3,
        "source_url": "https://www.fda.gov/advisory-committees/example",
        "publication_date": "2023-06-16",
        "source_doc_type": "fda_meeting_minutes",
        "drug_name": "TestDrug",
        "sponsor": "TestCo",
        "ticker": "TSTX",
        "indication": "cancer",
    }
    base.update(overrides)
    return base


def _write_outcomes(tmp_path, records, schema=_SCHEMA):
    data = {
        "schema": schema,
        "description": "test",
        "records": records,
    }
    path = tmp_path / "adcom_outcomes.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ===========================================================================
# validate_candidate
# ===========================================================================


class TestValidateCandidate:
    def test_valid_passes(self):
        ok, errs = validate_candidate(_make_candidate())
        assert ok is True
        assert errs == []

    def test_missing_required_field_fails(self):
        rec = _make_candidate()
        del rec["source_url"]
        ok, errs = validate_candidate(rec)
        assert ok is False

    def test_bad_question_type_fails(self):
        ok, errs = validate_candidate(_make_candidate(question_type="BANANA"))
        assert ok is False
        assert any("question_type" in e for e in errs)

    @pytest.mark.parametrize("qtype", sorted(VALID_QUESTION_TYPES))
    def test_all_valid_question_types_accepted(self, qtype):
        ok, _ = validate_candidate(_make_candidate(question_type=qtype))
        assert ok is True

    def test_bad_fda_outcome_fails(self):
        ok, errs = validate_candidate(_make_candidate(fda_outcome="MAYBE"))
        assert ok is False
        assert any("fda_outcome" in e for e in errs)

    @pytest.mark.parametrize("outcome", sorted(VALID_FDA_OUTCOMES))
    def test_all_valid_fda_outcomes_accepted(self, outcome):
        ok, _ = validate_candidate(_make_candidate(fda_outcome=outcome))
        assert ok is True

    def test_no_fda_outcome_is_ok(self):
        """fda_outcome is optional."""
        rec = _make_candidate()
        rec.pop("fda_outcome", None)
        ok, _ = validate_candidate(rec)
        assert ok is True

    def test_publication_before_meeting_fails(self):
        ok, errs = validate_candidate(_make_candidate(meeting_date="2023-06-15", publication_date="2023-06-10"))
        assert ok is False
        assert any("before" in e for e in errs)

    def test_publication_same_day_ok(self):
        ok, _ = validate_candidate(_make_candidate(meeting_date="2023-06-15", publication_date="2023-06-15"))
        assert ok is True

    def test_zero_votes_fails(self):
        ok, errs = validate_candidate(_make_candidate(vote_yes=0, vote_no=0))
        assert ok is False
        assert any("vote" in e.lower() for e in errs)

    def test_not_a_dict(self):
        ok, errs = validate_candidate("string")  # type: ignore
        assert ok is False


# ===========================================================================
# validate_candidates (batch)
# ===========================================================================


class TestValidateCandidates:
    def test_mixed_batch(self):
        good = _make_candidate()
        bad = _make_candidate(question_type="BANANA")
        valid, invalid = validate_candidates([good, bad])
        assert len(valid) == 1
        assert len(invalid) == 1
        assert "_errors" in invalid[0]

    def test_empty(self):
        valid, invalid = validate_candidates([])
        assert valid == []
        assert invalid == []


# ===========================================================================
# normalize_record
# ===========================================================================


class TestNormalizeRecord:
    def test_uppercases_question_type(self):
        rec = _make_candidate(question_type="approval")
        norm = normalize_record(rec)
        assert norm["question_type"] == "APPROVAL"

    def test_casts_vote_to_int(self):
        rec = _make_candidate(vote_yes="10", vote_no="3")
        norm = normalize_record(rec)
        assert norm["vote_yes"] == 10
        assert norm["vote_no"] == 3

    def test_strips_whitespace(self):
        rec = _make_candidate(drug_name="  TestDrug  ", committee="  ODAC  ")
        norm = normalize_record(rec)
        assert norm["drug_name"] == "TestDrug"
        assert norm["committee"] == "ODAC"

    def test_strips_internal_fields(self):
        rec = _make_candidate()
        rec["_review_note"] = "internal"
        rec["_errors"] = ["some error"]
        norm = normalize_record(rec)
        assert "_review_note" not in norm
        assert "_errors" not in norm

    def test_uppercases_fda_outcome(self):
        rec = _make_candidate(fda_outcome="approved")
        norm = normalize_record(rec)
        assert norm["fda_outcome"] == "APPROVED"


# ===========================================================================
# Dedup
# ===========================================================================


class TestDedup:
    def test_new_passes(self):
        existing = [_make_candidate(meeting_date="2022-01-01")]
        candidates = [_make_candidate(meeting_date="2023-06-15")]
        new, dupes = dedup_candidates(candidates, existing)
        assert len(new) == 1
        assert len(dupes) == 0

    def test_exact_match_is_dupe(self):
        existing = [_make_candidate()]
        candidates = [_make_candidate()]
        new, dupes = dedup_candidates(candidates, existing)
        assert len(dupes) == 1
        assert len(new) == 0

    def test_different_question_type_not_dupe(self):
        existing = [_make_candidate(question_type="APPROVAL")]
        candidates = [_make_candidate(question_type="SAFETY")]
        new, dupes = dedup_candidates(candidates, existing)
        assert len(new) == 1
        assert len(dupes) == 0

    def test_intra_batch_dedup(self):
        candidates = [_make_candidate(), _make_candidate()]
        new, dupes = dedup_candidates(candidates, [])
        assert len(new) == 1
        assert len(dupes) == 1

    def test_case_insensitive_question_type(self):
        existing = [_make_candidate(question_type="APPROVAL")]
        candidates = [_make_candidate(question_type="approval")]
        _, dupes = dedup_candidates(candidates, existing)
        assert len(dupes) == 1

    def test_different_drug_name_not_dupe(self):
        """v3: different drugs at the same meeting+committee+qtype are NOT dupes."""
        existing = [_make_candidate(drug_name="DrugA")]
        candidates = [_make_candidate(drug_name="DrugB")]
        new, dupes = dedup_candidates(candidates, existing)
        assert len(new) == 1
        assert len(dupes) == 0

    def test_same_drug_name_is_dupe(self):
        """v3: same drug at same meeting+committee+qtype is a dupe."""
        existing = [_make_candidate(drug_name="DrugA")]
        candidates = [_make_candidate(drug_name="DrugA")]
        new, dupes = dedup_candidates(candidates, existing)
        assert len(new) == 0
        assert len(dupes) == 1


# ===========================================================================
# Ingestion
# ===========================================================================


class TestIngestion:
    def test_dry_run(self, tmp_path):
        path = _write_outcomes(tmp_path, [])
        report = ingest_candidates([_make_candidate()], path, dry_run=True)
        assert report["accepted"] == 1
        assert report["dry_run"] is True
        # File should still be empty
        data = json.loads(path.read_text())
        assert data["records"] == []

    def test_ingest_writes(self, tmp_path):
        path = _write_outcomes(tmp_path, [])
        report = ingest_candidates([_make_candidate()], path, dry_run=False)
        assert report["accepted"] == 1
        data = json.loads(path.read_text())
        assert len(data["records"]) == 1
        assert data["schema"] == _SCHEMA

    def test_rejects_invalid(self, tmp_path):
        path = _write_outcomes(tmp_path, [])
        bad = _make_candidate(question_type="BANANA")
        report = ingest_candidates([bad], path, dry_run=False)
        assert report["accepted"] == 0
        assert report["rejected"] == 1

    def test_deduplicates(self, tmp_path):
        existing = [_make_candidate()]
        path = _write_outcomes(tmp_path, existing)
        report = ingest_candidates([_make_candidate()], path, dry_run=False)
        assert report["duplicates_skipped"] == 1
        assert report["accepted"] == 0

    def test_v2_schema_readable(self, tmp_path):
        """v2 schema files are still readable for backward compat."""
        path = _write_outcomes(tmp_path, [_make_candidate()], schema="adcom_outcomes.v2")
        report = ingest_candidates(
            [_make_candidate(meeting_date="2024-01-01", publication_date="2024-01-02")],
            path,
            dry_run=False,
        )
        assert report["accepted"] == 1
        data = json.loads(path.read_text())
        assert len(data["records"]) == 2

    def test_preserves_existing(self, tmp_path):
        existing = [_make_candidate(meeting_date="2022-01-01", publication_date="2022-01-02")]
        path = _write_outcomes(tmp_path, existing)
        new_rec = _make_candidate(meeting_date="2023-07-01", publication_date="2023-07-02")
        ingest_candidates([new_rec], path, dry_run=False)
        data = json.loads(path.read_text())
        assert len(data["records"]) == 2
        assert data["records"][0]["meeting_date"] == "2022-01-01"

    def test_normalizes_on_ingest(self, tmp_path):
        path = _write_outcomes(tmp_path, [])
        rec = _make_candidate(question_type="approval", vote_yes="10", vote_no="3")
        rec["_review_note"] = "internal"
        ingest_candidates([rec], path, dry_run=False)
        data = json.loads(path.read_text())
        assert data["records"][0]["question_type"] == "APPROVAL"
        assert data["records"][0]["vote_yes"] == 10
        assert "_review_note" not in data["records"][0]


# ===========================================================================
# Audit
# ===========================================================================


class TestAudit:
    def test_full_provenance(self, tmp_path):
        records = [_make_candidate()]
        path = _write_outcomes(tmp_path, records)
        report = audit_existing(path)
        assert report["with_full_provenance"] == 1
        assert report["gaps"] == []

    def test_missing_source_url(self, tmp_path):
        rec = _make_candidate()
        del rec["source_url"]
        # Manually write (bypassing validation)
        path = _write_outcomes(tmp_path, [rec])
        report = audit_existing(path)
        assert report["with_full_provenance"] == 0
        assert len(report["gaps"]) == 1
        assert "source_url" in report["gaps"][0]["missing"]

    def test_empty_file(self, tmp_path):
        path = _write_outcomes(tmp_path, [])
        report = audit_existing(path)
        assert report["total"] == 0

    def test_missing_file(self, tmp_path):
        report = audit_existing(tmp_path / "nonexistent.json")
        assert report["total"] == 0


# ===========================================================================
# Coverage summary
# ===========================================================================


class TestCoverage:
    def test_basic_coverage(self, tmp_path):
        records = [
            _make_candidate(meeting_date="2023-01-15", question_type="APPROVAL"),
            _make_candidate(meeting_date="2023-06-15", question_type="SAFETY"),
            _make_candidate(
                meeting_date="2024-03-10",
                committee="Cardiovascular and Renal Drugs Advisory Committee",
                question_type="APPROVAL",
            ),
        ]
        path = _write_outcomes(tmp_path, records)
        summary = coverage_summary(path)
        assert summary["total_records"] == 3
        assert summary["by_year"]["2023"] == 2
        assert summary["by_year"]["2024"] == 1
        assert "APPROVAL" in summary["by_question_type"]
        assert "SAFETY" in summary["by_question_type"]

    def test_empirical_readiness(self, tmp_path):
        # Need MIN_OBSERVATIONS (3) for a committee to be ready
        records = [_make_candidate(meeting_date=f"2023-0{i}-15") for i in range(1, 5)]  # 4 meetings
        path = _write_outcomes(tmp_path, records)
        summary = coverage_summary(path)
        emp = summary["empirical_ready"]
        assert emp["n_committee_cells"] >= 1
        assert "Oncologic Drugs Advisory Committee" in emp["committee_cells"]

    def test_below_min_not_ready(self, tmp_path):
        # Only 2 records — below MIN_OBSERVATIONS
        records = [
            _make_candidate(meeting_date="2023-01-15"),
            _make_candidate(meeting_date="2023-06-15"),
        ]
        path = _write_outcomes(tmp_path, records)
        summary = coverage_summary(path)
        emp = summary["empirical_ready"]
        assert emp["n_committee_cells"] == 0

    def test_favorable_rate(self, tmp_path):
        records = [
            _make_candidate(meeting_date="2023-01-15", vote_yes=10, vote_no=3),  # favorable
            _make_candidate(meeting_date="2023-06-15", vote_yes=3, vote_no=10),  # unfavorable
        ]
        path = _write_outcomes(tmp_path, records)
        summary = coverage_summary(path)
        assert summary["favorable_rate"] == 0.5

    def test_empty_file(self, tmp_path):
        path = _write_outcomes(tmp_path, [])
        summary = coverage_summary(path)
        assert summary["total_records"] == 0
        assert summary["empirical_ready"]["n_committee_cells"] == 0
