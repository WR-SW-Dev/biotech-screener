"""Tests for common.adcom_empirical — provenance validation and posterior scoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from common.adcom_empirical import (
    ALL_REQUIRED_FIELDS,
    MIN_OBSERVATIONS,
    OUTCOMES_SCHEMA,
    VALID_SOURCE_DOC_TYPES,
    build_posterior_table,
    load_outcomes,
    score_empirical,
    validate_outcomes_file,
    validate_record,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(**overrides: Any) -> Dict[str, Any]:
    """Build a valid record with all required fields, applying overrides."""
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


def _write_outcomes_file(
    tmp_dir: Path,
    records: List[Dict[str, Any]],
    schema: str = OUTCOMES_SCHEMA,
) -> Path:
    """Write an outcomes JSON file and return its path."""
    path = tmp_dir / "adcom_outcomes.json"
    data = {"schema": schema, "records": records}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ===========================================================================
# validate_record
# ===========================================================================


class TestValidateRecord:
    """Tests for single-record provenance validation."""

    def test_valid_record_passes(self):
        ok, errs = validate_record(_make_record())
        assert ok is True
        assert errs == []

    @pytest.mark.parametrize("field", list(ALL_REQUIRED_FIELDS))
    def test_missing_required_field_fails(self, field):
        rec = _make_record()
        del rec[field]
        ok, errs = validate_record(rec)
        assert ok is False
        assert any(field in e for e in errs)

    @pytest.mark.parametrize("field", list(ALL_REQUIRED_FIELDS))
    def test_empty_string_required_field_fails(self, field):
        rec = _make_record(**{field: ""})
        ok, errs = validate_record(rec)
        assert ok is False

    def test_bad_source_url_rejected(self):
        rec = _make_record(source_url="ftp://not-http.com/file")
        ok, errs = validate_record(rec)
        assert ok is False
        assert any("http" in e for e in errs)

    def test_unrecognized_source_doc_type_rejected(self):
        rec = _make_record(source_doc_type="blog_post")
        ok, errs = validate_record(rec)
        assert ok is False
        assert any("source_doc_type" in e for e in errs)

    @pytest.mark.parametrize("doc_type", sorted(VALID_SOURCE_DOC_TYPES))
    def test_all_valid_doc_types_accepted(self, doc_type):
        ok, _ = validate_record(_make_record(source_doc_type=doc_type))
        assert ok is True

    def test_negative_vote_count_rejected(self):
        ok, errs = validate_record(_make_record(vote_yes=-1))
        assert ok is False
        assert any("non-negative" in e for e in errs)

    def test_non_integer_vote_rejected(self):
        ok, errs = validate_record(_make_record(vote_no="abc"))
        assert ok is False
        assert any("integer" in e for e in errs)

    def test_bad_date_format_rejected(self):
        ok, errs = validate_record(_make_record(meeting_date="06/15/2023"))
        assert ok is False
        assert any("YYYY-MM-DD" in e for e in errs)

    def test_not_a_dict_rejected(self):
        ok, errs = validate_record("not a dict")  # type: ignore
        assert ok is False
        assert any("not a dict" in e for e in errs)


# ===========================================================================
# validate_outcomes_file
# ===========================================================================


class TestValidateOutcomesFile:
    """Tests for batch validation."""

    def test_all_valid(self):
        recs = [_make_record(meeting_date=f"2023-0{i}-01") for i in range(1, 4)]
        valid, invalid = validate_outcomes_file(recs)
        assert len(valid) == 3
        assert len(invalid) == 0

    def test_mixed_valid_invalid(self):
        good = _make_record()
        bad = _make_record()
        del bad["source_url"]
        valid, invalid = validate_outcomes_file([good, bad])
        assert len(valid) == 1
        assert len(invalid) == 1
        assert "_errors" in invalid[0]

    def test_empty_list(self):
        valid, invalid = validate_outcomes_file([])
        assert valid == []
        assert invalid == []


# ===========================================================================
# load_outcomes
# ===========================================================================


class TestLoadOutcomes:
    """Tests for load_outcomes with provenance gating."""

    def test_loads_valid_records(self, tmp_path):
        recs = [_make_record(), _make_record(meeting_date="2023-07-01")]
        path = _write_outcomes_file(tmp_path, recs)
        result = load_outcomes(path)
        assert len(result) == 2

    def test_excludes_invalid_records(self, tmp_path):
        good = _make_record()
        bad = _make_record()
        del bad["source_url"]
        path = _write_outcomes_file(tmp_path, [good, bad])
        result = load_outcomes(path)
        assert len(result) == 1

    def test_schema_mismatch_returns_empty(self, tmp_path):
        path = _write_outcomes_file(tmp_path, [_make_record()], schema="wrong.v99")
        result = load_outcomes(path)
        assert result == []

    def test_missing_file_returns_empty(self, tmp_path):
        result = load_outcomes(tmp_path / "nonexistent.json")
        assert result == []

    def test_empty_records_returns_empty(self, tmp_path):
        path = _write_outcomes_file(tmp_path, [])
        result = load_outcomes(path)
        assert result == []

    def test_corrupt_json_returns_empty(self, tmp_path):
        path = tmp_path / "adcom_outcomes.json"
        path.write_text("{bad json", encoding="utf-8")
        result = load_outcomes(path)
        assert result == []


# ===========================================================================
# build_posterior_table
# ===========================================================================


class TestBuildPosteriorTable:
    """Tests for posterior table construction."""

    def _bulk_records(self, committee, qtype, n_favorable, n_unfavorable):
        """Generate n records for a committee/qtype combo."""
        recs = []
        for i in range(n_favorable):
            recs.append(
                _make_record(
                    meeting_date=f"2023-{(i % 12) + 1:02d}-15",
                    committee=committee,
                    question_type=qtype,
                    vote_yes=12,
                    vote_no=3,
                )
            )
        for i in range(n_unfavorable):
            recs.append(
                _make_record(
                    meeting_date=f"2022-{(i % 12) + 1:02d}-15",
                    committee=committee,
                    question_type=qtype,
                    vote_yes=3,
                    vote_no=12,
                )
            )
        return recs

    def test_empty_records_empty_table(self):
        table = build_posterior_table([], "2024-01-01")
        assert table == {}

    def test_below_min_observations_excluded(self):
        recs = self._bulk_records("TestCommittee", "APPROVAL", 2, 0)
        table = build_posterior_table(recs, "2024-01-01")
        assert "TestCommittee|APPROVAL" not in table
        assert "TestCommittee|*" not in table

    def test_at_min_observations_included(self):
        recs = self._bulk_records("TestCommittee", "APPROVAL", MIN_OBSERVATIONS, 0)
        table = build_posterior_table(recs, "2024-01-01")
        assert "TestCommittee|APPROVAL" in table
        assert "TestCommittee|*" in table

    def test_pit_safety_excludes_future(self):
        recs = self._bulk_records("TestCommittee", "APPROVAL", 5, 0)
        # All records are in 2022-2023; as_of_date before them
        table = build_posterior_table(recs, "2020-01-01")
        assert table == {}

    def test_posterior_score_range(self):
        recs = self._bulk_records("TestCommittee", "APPROVAL", 4, 1)
        table = build_posterior_table(recs, "2024-01-01")
        entry = table["TestCommittee|APPROVAL"]
        assert 0.0 < entry["score"] < 1.0
        assert entry["n"] == 5
        assert entry["basis"] == "empirical_committee_question"

    def test_committee_wildcard_aggregates_qtypes(self):
        recs = self._bulk_records("TestCommittee", "APPROVAL", 2, 0) + self._bulk_records(
            "TestCommittee", "SAFETY", 2, 0
        )
        table = build_posterior_table(recs, "2024-01-01")
        # Neither qtype alone hits MIN_OBSERVATIONS=3
        assert "TestCommittee|APPROVAL" not in table
        assert "TestCommittee|SAFETY" not in table
        # But committee-level does (4 total)
        assert "TestCommittee|*" in table
        assert table["TestCommittee|*"]["n"] == 4


# ===========================================================================
# score_empirical
# ===========================================================================


class TestScoreEmpirical:
    """Tests for the scoring hierarchy."""

    def test_level1_committee_question(self):
        table = {
            "C|Q": {"score": 0.85, "n": 5, "basis": "empirical_committee_question"},
            "C|*": {"score": 0.75, "n": 10, "basis": "empirical_committee"},
        }
        score, n, basis = score_empirical("C", "Q", table, 0.70)
        assert score == 0.85
        assert basis == "empirical_committee_question"

    def test_level2_committee_fallback(self):
        table = {
            "C|*": {"score": 0.75, "n": 10, "basis": "empirical_committee"},
        }
        score, n, basis = score_empirical("C", "Q", table, 0.70)
        assert score == 0.75
        assert basis == "empirical_committee"

    def test_level3_prior_fallback(self):
        table = {}
        score, n, basis = score_empirical("C", "Q", table, 0.70)
        assert score == 0.70
        assert n == 0
        assert basis == "committee_prior"

    def test_empty_table_always_prior(self):
        score, n, basis = score_empirical("Anything", "APPROVAL", {}, 0.63)
        assert score == 0.63
        assert basis == "committee_prior"


# ===========================================================================
# Integration: empty production file
# ===========================================================================


class TestProductionFileEmpty:
    """Verify that the current production adcom_outcomes.json (v2, empty records)
    results in no empirical scoring — committee_prior only."""

    def test_production_file_yields_no_empirical(self):
        prod_path = Path(__file__).resolve().parent.parent / "production_data" / "adcom_outcomes.json"
        if not prod_path.exists():
            pytest.skip("production adcom_outcomes.json not found")
        records = load_outcomes(prod_path)
        assert records == [], "Production file should have 0 validated records"
        table = build_posterior_table(records, "2026-03-11")
        assert table == {}, "Empty records should produce empty posterior table"
        # Scoring must always fall through to committee_prior
        score, n, basis = score_empirical(
            "Oncologic Drugs Advisory Committee",
            "APPROVAL",
            table,
            0.63,
        )
        assert basis == "committee_prior"
        assert n == 0
