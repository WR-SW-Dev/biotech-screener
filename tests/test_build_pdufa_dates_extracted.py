#!/usr/bin/env python3
"""Tests for tools.build_pdufa_dates_extracted (Phase 1 sidecar)."""

from datetime import date, timedelta

from tools.build_pdufa_dates_extracted import (
    MAX_PER_TICKER,
    _extract_submission_type,
    _find_latest_cache,
    classify_diff,
    filter_and_dedupe,
    to_sidecar_record,
    write_diff_artifacts,
)

AS_OF = date(2026, 4, 27)


def _evt(
    ticker="ABCD",
    event_date="2026-06-15",
    event_type="FDA_PDUFA_DATE",
    date_precision="DAY",
    confidence="HIGH",
    event_status="upcoming",
    disclosed_at="2026-04-01",
    event_name="8-K: PDUFA date of June 15, 2026",
    **kw,
):
    base = {
        "ticker": ticker,
        "event_type": event_type,
        "event_date": event_date,
        "date_precision": date_precision,
        "confidence": confidence,
        "event_status": event_status,
        "disclosed_at": disclosed_at,
        "event_name": event_name,
        "tags": kw.pop("tags", ["sec_8k"]),
        "source": kw.pop("source", "SEC_8K_FILING"),
    }
    base.update(kw)
    return base


class TestFilterAndDedupe:
    def test_keeps_high_day_pdufa(self):
        events = [_evt(ticker="ARVN", event_date="2026-06-05")]
        out = filter_and_dedupe(events, AS_OF)
        assert len(out) == 1
        assert out[0]["ticker"] == "ARVN"

    def test_drops_quarter_precision(self):
        events = [_evt(date_precision="QUARTER", confidence="MED")]
        assert filter_and_dedupe(events, AS_OF) == []

    def test_drops_low_confidence(self):
        events = [_evt(confidence="LOW")]
        assert filter_and_dedupe(events, AS_OF) == []

    def test_drops_non_pdufa_event_types(self):
        events = [_evt(event_type="DATA_READOUT"), _evt(event_type="FDA_ADCOM")]
        assert filter_and_dedupe(events, AS_OF) == []

    def test_drops_stale_events(self):
        old = (AS_OF - timedelta(days=45)).isoformat()
        events = [_evt(event_date=old)]
        assert filter_and_dedupe(events, AS_OF) == []

    def test_dedup_extended_beats_upcoming(self):
        events = [
            _evt(ticker="LNTH", event_date="2026-06-29", event_status="upcoming", disclosed_at="2026-03-30"),
            _evt(ticker="LNTH", event_date="2026-06-29", event_status="extended", disclosed_at="2026-04-01"),
        ]
        out = filter_and_dedupe(events, AS_OF)
        assert len(out) == 1
        assert out[0]["event_status"] == "extended"

    def test_dedup_resubmission_beats_upcoming(self):
        events = [
            _evt(ticker="X", event_date="2026-06-05", event_status="upcoming"),
            _evt(ticker="X", event_date="2026-06-05", event_status="resubmission_accepted"),
        ]
        out = filter_and_dedupe(events, AS_OF)
        assert len(out) == 1
        assert out[0]["event_status"] == "resubmission_accepted"

    def test_dedup_high_beats_med(self):
        events = [
            _evt(ticker="Y", event_date="2026-06-15", confidence="MED", disclosed_at="2026-04-15"),
            _evt(ticker="Y", event_date="2026-06-15", confidence="HIGH", disclosed_at="2026-04-01"),
        ]
        out = filter_and_dedupe(events, AS_OF)
        assert len(out) == 1
        assert out[0]["confidence"] == "HIGH"

    def test_per_ticker_cap(self):
        events = [_evt(ticker="NUVL", event_date=f"2026-{m:02d}-15") for m in range(5, 12)]
        out = filter_and_dedupe(events, AS_OF)
        nuvl = [r for r in out if r["ticker"] == "NUVL"]
        assert len(nuvl) == MAX_PER_TICKER
        # Earliest 3 should be kept (nearest-future first)
        assert [r["event_date"] for r in nuvl] == [
            "2026-05-15",
            "2026-06-15",
            "2026-07-15",
        ]

    def test_two_distinct_dates_per_ticker_both_kept(self):
        events = [
            _evt(ticker="DNLI", event_date="2026-05-01"),
            _evt(ticker="DNLI", event_date="2026-08-15"),
        ]
        out = filter_and_dedupe(events, AS_OF)
        assert {r["event_date"] for r in out} == {"2026-05-01", "2026-08-15"}

    def test_output_sorted_by_date(self):
        events = [
            _evt(ticker="B", event_date="2026-09-01"),
            _evt(ticker="A", event_date="2026-05-01"),
            _evt(ticker="C", event_date="2026-07-15"),
        ]
        out = filter_and_dedupe(events, AS_OF)
        assert [r["event_date"] for r in out] == [
            "2026-05-01",
            "2026-07-15",
            "2026-09-01",
        ]


class TestSubmissionTypeExtraction:
    def test_nda(self):
        assert _extract_submission_type("8-K: NDA accepted, PDUFA date of June 15, 2026") == "NDA"

    def test_bla(self):
        assert _extract_submission_type("8-K: BLA priority review PDUFA date Aug 22, 2026") == "BLA"

    def test_snda(self):
        assert _extract_submission_type("8-K: sNDA PDUFA date of April 30, 2026") == "sNDA"

    def test_sbla(self):
        assert _extract_submission_type("8-K: sBLA PDUFA date of June 1, 2026") == "sBLA"

    def test_no_match(self):
        assert _extract_submission_type("8-K: PDUFA date of June 15, 2026") == ""

    def test_empty_event_name(self):
        assert _extract_submission_type("") == ""


class TestSidecarRecordSchema:
    def test_required_fields_present(self):
        r = to_sidecar_record(_evt(), pattern_version="abc12345", extracted_at_iso="2026-04-27T10:00:00+00:00")
        for f in (
            "ticker",
            "pdufa_date",
            "event_type",
            "event_status",
            "submission_type",
            "review_type",
            "confidence",
            "date_precision",
            "prior_date",
            "source",
            "source_url",
            "accession",
            "filing_form",
            "as_of_disclosed_at",
            "extracted_at",
            "drug_name",
            "indication",
            "notes",
        ):
            assert f in r

    def test_drug_and_indication_empty_phase_1(self):
        r = to_sidecar_record(_evt(), pattern_version=None, extracted_at_iso="2026-04-27T10:00:00+00:00")
        assert r["drug_name"] == ""
        assert r["indication"] == ""

    def test_event_type_normalized_to_pdufa(self):
        r = to_sidecar_record(_evt(), pattern_version=None, extracted_at_iso="2026-04-27T10:00:00+00:00")
        assert r["event_type"] == "PDUFA"

    def test_prior_date_passthrough(self):
        r = to_sidecar_record(
            _evt(prior_date="2026-03-29"),
            pattern_version=None,
            extracted_at_iso="2026-04-27T10:00:00+00:00",
        )
        assert r["prior_date"] == "2026-03-29"

    def test_notes_carries_pattern_version(self):
        r = to_sidecar_record(_evt(), pattern_version="937b38db", extracted_at_iso="2026-04-27T10:00:00+00:00")
        assert "937b38db" in r["notes"]


class TestClassifyDiff:
    def _rec(self, ticker="ABCD", pdufa_date="2026-06-15", event_status="upcoming"):
        return {
            "ticker": ticker,
            "pdufa_date": pdufa_date,
            "event_status": event_status,
        }

    def test_new_candidate(self):
        cls, cano = classify_diff(self._rec("NEW"), {})
        assert cls == "NEW_CANDIDATE"
        assert cano is None

    def test_matches_canonical(self):
        canonical = {"ARVN": {"ticker": "ARVN", "pdufa_date": "2026-06-05"}}
        cls, cano = classify_diff(self._rec("ARVN", "2026-06-05"), canonical)
        assert cls == "MATCHES_CANONICAL"
        assert cano == "2026-06-05"

    def test_conflicts_canonical(self):
        canonical = {"AXSM": {"ticker": "AXSM", "pdufa_date": "2026-04-30"}}
        cls, cano = classify_diff(self._rec("AXSM", "2025-12-31"), canonical)
        assert cls == "CONFLICTS_CANONICAL"
        assert cano == "2026-04-30"

    def test_extended_not_in_canonical(self):
        cls, cano = classify_diff(self._rec("OMER", "2025-12-26", event_status="extended"), {})
        assert cls == "EXTENDED_NOT_IN_CANONICAL"
        assert cano is None

    def test_extended_matches_canonical(self):
        canonical = {"X": {"ticker": "X", "pdufa_date": "2026-06-29"}}
        cls, _ = classify_diff(self._rec("X", "2026-06-29", event_status="extended"), canonical)
        assert cls == "EXTENDED_MATCHES_CANONICAL"

    def test_extended_conflicts_canonical(self):
        canonical = {"X": {"ticker": "X", "pdufa_date": "2026-03-29"}}
        cls, _ = classify_diff(self._rec("X", "2026-06-29", event_status="extended"), canonical)
        assert cls == "EXTENDED_CONFLICTS_CANONICAL"


class TestCacheLookup:
    def test_finds_latest_within_window(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "8k_catalysts_2026-04-20_pv1.json").write_text("[]")
        (cache_dir / "8k_catalysts_2026-04-25_pv2.json").write_text("[]")
        latest = _find_latest_cache(cache_dir, AS_OF, max_stale_days=7)
        assert latest is not None
        assert "2026-04-25" in latest.name

    def test_skips_files_older_than_window(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "8k_catalysts_2026-04-10_pv1.json").write_text("[]")
        latest = _find_latest_cache(cache_dir, AS_OF, max_stale_days=7)
        assert latest is None

    def test_skips_future_dated_files(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "8k_catalysts_2026-05-30_pv1.json").write_text("[]")
        latest = _find_latest_cache(cache_dir, AS_OF, max_stale_days=7)
        assert latest is None

    def test_handles_missing_directory(self, tmp_path):
        latest = _find_latest_cache(tmp_path / "nonexistent", AS_OF, max_stale_days=7)
        assert latest is None


class TestDiffArtifactWriting:
    def test_writes_csv_and_md_with_records(self, tmp_path):
        records = [
            to_sidecar_record(
                _evt(ticker="ARVN", event_date="2026-06-05"),
                pattern_version="abc12345",
                extracted_at_iso="2026-04-27T10:00:00+00:00",
            )
        ]
        canonical = {"ARVN": {"ticker": "ARVN", "pdufa_date": "2026-06-05"}}
        buckets = write_diff_artifacts(records, canonical, AS_OF, tmp_path)
        assert buckets.get("MATCHES_CANONICAL") == 1
        assert (tmp_path / f"pdufa_extracted_vs_canonical_{AS_OF.isoformat()}.csv").exists()
        assert (tmp_path / f"pdufa_extracted_vs_canonical_{AS_OF.isoformat()}.md").exists()

    def test_writes_artifacts_when_empty(self, tmp_path):
        buckets = write_diff_artifacts([], {}, AS_OF, tmp_path)
        assert buckets == {}
        # Should still produce a header-only CSV and an MD with summary
        assert (tmp_path / f"pdufa_extracted_vs_canonical_{AS_OF.isoformat()}.csv").exists()
        assert (tmp_path / f"pdufa_extracted_vs_canonical_{AS_OF.isoformat()}.md").exists()
