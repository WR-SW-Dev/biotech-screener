"""Tests for AACT trial ingest agent — fetch_aact_snapshot.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.fetch_aact_snapshot import (
    _normalize_phase,
    _normalize_status,
    _parse_date_safe,
    _parse_int_safe,
    build_health_report,
    compute_deltas,
    link_sponsors,
)


class TestStatusNormalization:
    def test_screaming_snake(self):
        assert _normalize_status("RECRUITING") == "Recruiting"
        assert _normalize_status("COMPLETED") == "Completed"
        assert _normalize_status("TERMINATED") == "Terminated"
        assert _normalize_status("ACTIVE_NOT_RECRUITING") == "Active, not recruiting"

    def test_title_case(self):
        assert _normalize_status("recruiting") == "Recruiting"
        assert _normalize_status("completed") == "Completed"

    def test_unknown_passthrough(self):
        assert _normalize_status("SomethingNew") == "SomethingNew"


class TestPhaseNormalization:
    def test_screaming_snake(self):
        assert _normalize_phase("PHASE1") == "Phase 1"
        assert _normalize_phase("PHASE2") == "Phase 2"
        assert _normalize_phase("PHASE3") == "Phase 3"
        assert _normalize_phase("PHASE1/PHASE2") == "Phase 1/2"

    def test_title_case(self):
        assert _normalize_phase("Phase 1") == "Phase 1"
        assert _normalize_phase("Phase 2/Phase 3") == "Phase 2/3"

    def test_na(self):
        assert _normalize_phase("N/A") == "Not Applicable"
        assert _normalize_phase("NOT_APPLICABLE") == "Not Applicable"


class TestDateParsing:
    def test_iso(self):
        assert _parse_date_safe("2026-04-01") == "2026-04-01"

    def test_us_format(self):
        assert _parse_date_safe("04/01/2026") == "2026-04-01"

    def test_empty(self):
        assert _parse_date_safe("") is None
        assert _parse_date_safe(None) is None
        assert _parse_date_safe("N/A") is None

    def test_month_year(self):
        result = _parse_date_safe("April 2026")
        assert result == "2026-04-01"


class TestIntParsing:
    def test_normal(self):
        assert _parse_int_safe("100") == 100

    def test_empty(self):
        assert _parse_int_safe("") is None
        assert _parse_int_safe(None) is None

    def test_na(self):
        assert _parse_int_safe("N/A") is None


class TestSponsorLinkage:
    def test_exact_match(self):
        trials = {"NCT001": {"lead_sponsor_name": "Regeneron Pharmaceuticals"}}
        sponsor_map = {"Regeneron Pharmaceuticals": "REGN"}
        link_sponsors(trials, sponsor_map, {})
        assert trials["NCT001"]["mapped_ticker"] == "REGN"
        assert trials["NCT001"]["mapping_confidence"] == "high"
        assert trials["NCT001"]["mapping_method"] == "exact"

    def test_case_insensitive_match(self):
        trials = {"NCT001": {"lead_sponsor_name": "regeneron pharmaceuticals"}}
        sponsor_map = {"Regeneron Pharmaceuticals": "REGN"}
        link_sponsors(trials, sponsor_map, {})
        assert trials["NCT001"]["mapped_ticker"] == "REGN"
        assert trials["NCT001"]["mapping_confidence"] == "high"

    def test_override(self):
        trials = {"NCT001": {"lead_sponsor_name": "Unknown Sponsor"}}
        sponsor_map = {}
        overrides = {"NCT001": {"ticker": "TEST"}}
        link_sponsors(trials, sponsor_map, overrides)
        assert trials["NCT001"]["mapped_ticker"] == "TEST"
        assert trials["NCT001"]["mapping_method"] == "override"

    def test_unmatched(self):
        trials = {"NCT001": {"lead_sponsor_name": "Totally Unknown Corp"}}
        sponsor_map = {"Regeneron": "REGN"}
        link_sponsors(trials, sponsor_map, {})
        assert trials["NCT001"]["mapped_ticker"] is None
        assert trials["NCT001"]["mapping_confidence"] == "none"

    def test_no_sponsor(self):
        trials = {"NCT001": {"lead_sponsor_name": ""}}
        link_sponsors(trials, {}, {})
        assert trials["NCT001"]["mapped_ticker"] is None
        assert trials["NCT001"]["mapping_method"] == "unmatched"


class TestDeltaDetection:
    def test_new_trial(self):
        current = {"NCT001": {"overall_status": "Recruiting"}}
        prior = {}
        deltas = compute_deltas(current, prior)
        assert len(deltas) == 1
        assert deltas[0]["delta_type"] == "new_trial"

    def test_removed_trial(self):
        current = {}
        prior = {"NCT001": {"overall_status": "Recruiting", "mapped_ticker": "TEST"}}
        deltas = compute_deltas(current, prior)
        assert len(deltas) == 1
        assert deltas[0]["delta_type"] == "trial_removed_or_missing"
        assert deltas[0]["materiality_flag"] is True

    def test_status_change_material(self):
        current = {
            "NCT001": {
                "overall_status": "Completed",
                "primary_completion_date": "2026-01-01",
                "enrollment": 100,
                "results_first_posted_date": None,
                "mapped_ticker": "TEST",
            }
        }
        prior = {
            "NCT001": {
                "overall_status": "Recruiting",
                "primary_completion_date": "2026-01-01",
                "enrollment": 100,
                "results_first_posted_date": None,
                "mapped_ticker": "TEST",
            }
        }
        deltas = compute_deltas(current, prior)
        status_deltas = [d for d in deltas if d["delta_type"] == "status_change"]
        assert len(status_deltas) == 1
        assert status_deltas[0]["materiality_flag"] is True  # Completed is terminal

    def test_pcd_shift_material(self):
        current = {
            "NCT001": {
                "overall_status": "Recruiting",
                "primary_completion_date": "2026-06-01",
                "enrollment": 100,
                "results_first_posted_date": None,
                "mapped_ticker": "TEST",
            }
        }
        prior = {
            "NCT001": {
                "overall_status": "Recruiting",
                "primary_completion_date": "2026-03-01",
                "enrollment": 100,
                "results_first_posted_date": None,
                "mapped_ticker": "TEST",
            }
        }
        deltas = compute_deltas(current, prior)
        pcd_deltas = [d for d in deltas if d["delta_type"] == "primary_completion_change"]
        assert len(pcd_deltas) == 1
        assert pcd_deltas[0]["materiality_flag"] is True  # 92 day shift

    def test_pcd_shift_immaterial(self):
        current = {
            "NCT001": {
                "overall_status": "Recruiting",
                "primary_completion_date": "2026-03-10",
                "enrollment": 100,
                "results_first_posted_date": None,
                "mapped_ticker": "TEST",
            }
        }
        prior = {
            "NCT001": {
                "overall_status": "Recruiting",
                "primary_completion_date": "2026-03-01",
                "enrollment": 100,
                "results_first_posted_date": None,
                "mapped_ticker": "TEST",
            }
        }
        deltas = compute_deltas(current, prior)
        pcd_deltas = [d for d in deltas if d["delta_type"] == "primary_completion_change"]
        assert len(pcd_deltas) == 1
        assert pcd_deltas[0]["materiality_flag"] is False  # 9 day shift < 14

    def test_results_posted(self):
        current = {
            "NCT001": {
                "overall_status": "Completed",
                "primary_completion_date": "2026-01-01",
                "enrollment": 100,
                "results_first_posted_date": "2026-03-15",
                "mapped_ticker": "TEST",
            }
        }
        prior = {
            "NCT001": {
                "overall_status": "Completed",
                "primary_completion_date": "2026-01-01",
                "enrollment": 100,
                "results_first_posted_date": None,
                "mapped_ticker": "TEST",
            }
        }
        deltas = compute_deltas(current, prior)
        results_deltas = [d for d in deltas if d["delta_type"] == "results_posted"]
        assert len(results_deltas) == 1
        assert results_deltas[0]["materiality_flag"] is True

    def test_enrollment_change_material(self):
        current = {
            "NCT001": {
                "overall_status": "Recruiting",
                "primary_completion_date": "2026-01-01",
                "enrollment": 150,
                "results_first_posted_date": None,
                "mapped_ticker": "TEST",
            }
        }
        prior = {
            "NCT001": {
                "overall_status": "Recruiting",
                "primary_completion_date": "2026-01-01",
                "enrollment": 100,
                "results_first_posted_date": None,
                "mapped_ticker": "TEST",
            }
        }
        deltas = compute_deltas(current, prior)
        enr_deltas = [d for d in deltas if d["delta_type"] == "enrollment_change"]
        assert len(enr_deltas) == 1
        assert enr_deltas[0]["materiality_flag"] is True  # 50% change

    def test_no_changes(self):
        trial = {
            "overall_status": "Recruiting",
            "primary_completion_date": "2026-01-01",
            "enrollment": 100,
            "results_first_posted_date": None,
            "mapped_ticker": "TEST",
        }
        deltas = compute_deltas({"NCT001": trial.copy()}, {"NCT001": trial.copy()})
        assert len(deltas) == 0


class TestHealthReport:
    def test_basic_report(self):
        trials = {
            "NCT001": {
                "overall_status": "Recruiting",
                "phase": "Phase 3",
                "mapped_ticker": "TEST",
                "mapping_confidence": "high",
            },
            "NCT002": {
                "overall_status": "Completed",
                "phase": "Phase 2",
                "mapped_ticker": None,
                "mapping_confidence": "none",
            },
        }
        deltas = [{"delta_type": "status_change", "materiality_flag": True}]
        health = build_health_report(trials, deltas, "2026-04-01", ["studies", "sponsors"], [], [])
        assert health["schema"] == "aact_health.v1"
        assert health["n_trials"] == 2
        assert health["n_linked_to_ticker"] == 1
        assert health["linkage_pct"] == 50.0
        assert health["delta_summary"]["n_total"] == 1
        assert health["delta_summary"]["n_material"] == 1

    def test_empty_trials(self):
        health = build_health_report({}, [], "2026-04-01", [], ["studies"], ["FATAL"])
        assert health["n_trials"] == 0
        assert health["linkage_pct"] == 0.0
