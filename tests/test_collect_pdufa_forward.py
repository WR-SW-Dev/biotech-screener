"""Tests for tools/collect_pdufa_forward.py — PDUFA provenance validation and ingestion."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from tools.collect_pdufa_forward import (
    PROVENANCE_REQUIRED,
    VALID_SOURCES,
    audit_existing,
    compute_regulatory_coverage_delta,
    dedup_candidates,
    ingest_candidates,
    validate_candidate,
    validate_candidates,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(**overrides) -> Dict[str, Any]:
    base = {
        "ticker": "TSTX",
        "drug_name": "TestDrug",
        "indication": "cancer",
        "pdufa_date": "2026-06-15",
        "event_type": "PDUFA",
        "submission_type": "NDA",
        "confidence": "HIGH",
        "source": "COMPANY_GUIDANCE",
        "source_url": "https://ir.testco.com/press-release/nda-acceptance",
        "as_of_disclosed_at": "2026-01-15",
        "notes": "NDA accepted per company press release",
    }
    base.update(overrides)
    return base


# ===========================================================================
# validate_candidate
# ===========================================================================


class TestValidateCandidate:
    def test_valid_passes(self):
        ok, errs = validate_candidate(_make_candidate())
        assert ok is True
        assert errs == []

    @pytest.mark.parametrize("field", list(PROVENANCE_REQUIRED))
    def test_missing_required_field_fails(self, field):
        rec = _make_candidate(**{field: ""})
        ok, errs = validate_candidate(rec)
        assert ok is False
        assert any(field in e for e in errs)

    def test_bad_pdufa_date_format(self):
        ok, errs = validate_candidate(_make_candidate(pdufa_date="06/15/2026"))
        assert ok is False

    def test_bad_disclosed_date_format(self):
        ok, errs = validate_candidate(_make_candidate(as_of_disclosed_at="not-a-date"))
        assert ok is False

    def test_unrecognized_source(self):
        ok, errs = validate_candidate(_make_candidate(source="TWITTER"))
        assert ok is False
        assert any("source" in e for e in errs)

    @pytest.mark.parametrize("src", sorted(VALID_SOURCES))
    def test_all_valid_sources_accepted(self, src):
        ok, _ = validate_candidate(_make_candidate(source=src))
        assert ok is True

    def test_bad_confidence(self):
        ok, errs = validate_candidate(_make_candidate(confidence="VERY_HIGH"))
        assert ok is False

    def test_bad_source_url_scheme(self):
        ok, errs = validate_candidate(_make_candidate(source_url="ftp://bad"))
        assert ok is False

    def test_disclosed_after_pdufa_fails(self):
        ok, errs = validate_candidate(_make_candidate(pdufa_date="2026-06-15", as_of_disclosed_at="2026-07-01"))
        assert ok is False
        assert any("after" in e for e in errs)

    def test_no_source_url_still_valid(self):
        """source_url is recommended but not required."""
        rec = _make_candidate()
        del rec["source_url"]
        ok, _ = validate_candidate(rec)
        assert ok is True

    def test_not_a_dict(self):
        ok, errs = validate_candidate("string")  # type: ignore
        assert ok is False


# ===========================================================================
# validate_candidates (batch)
# ===========================================================================


class TestValidateCandidates:
    def test_mixed_batch(self):
        good = _make_candidate()
        bad = _make_candidate(pdufa_date="")
        valid, invalid = validate_candidates([good, bad])
        assert len(valid) == 1
        assert len(invalid) == 1
        assert "_errors" in invalid[0]

    def test_empty(self):
        valid, invalid = validate_candidates([])
        assert valid == []
        assert invalid == []


# ===========================================================================
# Dedup
# ===========================================================================


class TestDedup:
    def test_new_passes(self):
        existing = [{"ticker": "ACAD", "pdufa_date": "2026-04-03"}]
        candidates = [_make_candidate(ticker="NEWX")]
        new, dupes = dedup_candidates(candidates, existing)
        assert len(new) == 1
        assert len(dupes) == 0

    def test_existing_match_is_dupe(self):
        existing = [{"ticker": "TSTX", "pdufa_date": "2026-06-15"}]
        candidates = [_make_candidate()]
        new, dupes = dedup_candidates(candidates, existing)
        assert len(dupes) == 1

    def test_case_insensitive(self):
        existing = [{"ticker": "tstx", "pdufa_date": "2026-06-15"}]
        candidates = [_make_candidate(ticker="TSTX")]
        _, dupes = dedup_candidates(candidates, existing)
        assert len(dupes) == 1

    def test_intra_batch_dedup(self):
        candidates = [_make_candidate(), _make_candidate()]
        new, _ = dedup_candidates(candidates, [])
        assert len(new) == 1


# ===========================================================================
# Ingestion
# ===========================================================================


class TestIngestion:
    def test_dry_run(self, tmp_path):
        (tmp_path / "pdufa_dates.json").write_text("[]")
        report = ingest_candidates([_make_candidate()], tmp_path, dry_run=True)
        assert report["accepted"] == 1
        assert report["dry_run"] is True
        assert json.loads((tmp_path / "pdufa_dates.json").read_text()) == []

    def test_ingest_writes(self, tmp_path):
        (tmp_path / "pdufa_dates.json").write_text("[]")
        report = ingest_candidates([_make_candidate()], tmp_path, dry_run=False)
        assert report["accepted"] == 1
        data = json.loads((tmp_path / "pdufa_dates.json").read_text())
        assert len(data) == 1
        assert data[0]["ticker"] == "TSTX"

    def test_rejects_invalid(self, tmp_path):
        (tmp_path / "pdufa_dates.json").write_text("[]")
        report = ingest_candidates([_make_candidate(pdufa_date="")], tmp_path, dry_run=False)
        assert report["accepted"] == 0
        assert report["rejected"] == 1

    def test_strips_internal_fields(self, tmp_path):
        (tmp_path / "pdufa_dates.json").write_text("[]")
        rec = _make_candidate()
        rec["_review_note"] = "internal"
        ingest_candidates([rec], tmp_path, dry_run=False)
        data = json.loads((tmp_path / "pdufa_dates.json").read_text())
        assert "_review_note" not in data[0]

    def test_preserves_existing(self, tmp_path):
        existing = [{"ticker": "ACAD", "pdufa_date": "2026-04-03"}]
        (tmp_path / "pdufa_dates.json").write_text(json.dumps(existing))
        ingest_candidates([_make_candidate()], tmp_path, dry_run=False)
        data = json.loads((tmp_path / "pdufa_dates.json").read_text())
        assert len(data) == 2
        assert data[0]["ticker"] == "ACAD"


# ===========================================================================
# Audit
# ===========================================================================


class TestAudit:
    def test_full_provenance(self, tmp_path):
        records = [
            {
                "ticker": "A",
                "pdufa_date": "2026-06-01",
                "source": "COMPANY_GUIDANCE",
                "source_url": "https://example.com",
                "as_of_disclosed_at": "2026-01-01",
            }
        ]
        (tmp_path / "pdufa_dates.json").write_text(json.dumps(records))
        report = audit_existing(tmp_path)
        assert report["with_full_provenance"] == 1
        assert report["gaps"] == []

    def test_missing_source_url(self, tmp_path):
        records = [
            {
                "ticker": "B",
                "pdufa_date": "2026-06-01",
                "source": "COMPANY_GUIDANCE",
                "as_of_disclosed_at": "2026-01-01",
            }
        ]
        (tmp_path / "pdufa_dates.json").write_text(json.dumps(records))
        report = audit_existing(tmp_path)
        assert report["with_full_provenance"] == 0
        assert len(report["gaps"]) == 1
        assert "source_url" in report["gaps"][0]["missing"]

    def test_empty_file(self, tmp_path):
        (tmp_path / "pdufa_dates.json").write_text("[]")
        report = audit_existing(tmp_path)
        assert report["total"] == 0


# ===========================================================================
# Coverage delta
# ===========================================================================


class TestCoverageDelta:
    def test_basic(self):
        result = compute_regulatory_coverage_delta({"A", "B", "C"}, {"B", "D"}, 100, 100)
        assert result["delta_count"] == 1
        assert sorted(result["added"]) == ["A", "C"]
        assert result["dropped"] == ["D"]

    def test_no_prior(self):
        result = compute_regulatory_coverage_delta({"A"}, set(), 100, 100)
        assert result["delta_count"] == 1
        assert result["prior_pct"] == 0.0
