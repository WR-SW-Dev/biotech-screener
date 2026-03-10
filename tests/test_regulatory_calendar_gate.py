"""Tests for regulatory calendar production gate + maintenance audit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.audit_regulatory_calendar_maintenance import (
    compute_freshness,
    compute_proximity,
    find_missing_disclosed,
    find_past_dated,
    run_maintenance_audit,
    write_report,
)
from tools.run_daily_production import GateConfig, check_regulatory_calendar

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_metadata(tmp_path, reg_cov=None):
    """Write a metadata.json with regulatory_coverage dict."""
    meta = {
        "regulatory_coverage": reg_cov
        or {
            "manual_calendar_n_records": 10,
            "n_eligible_flagged": 5,
            "regulatory_secondary_coverage_pct": 4.1,
        }
    }
    meta_path = tmp_path / "metadata.json"
    meta_path.write_text(json.dumps(meta))
    return meta_path


def _write_calendar(tmp_path, records):
    p = tmp_path / "pdufa_dates.json"
    p.write_text(json.dumps(records))
    return p


def _make_record(ticker="ACME", pdufa_date="2026-06-01", disclosed="2025-12-01"):
    return {
        "ticker": ticker,
        "pdufa_date": pdufa_date,
        "event_type": "PDUFA",
        "confidence": "HIGH",
        "source": "COMPANY_GUIDANCE",
        "as_of_disclosed_at": disclosed,
    }


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------


class TestCheckRegulatoryCalendar:
    def test_pass_normal(self, tmp_path):
        _write_metadata(tmp_path)
        config = GateConfig()
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        assert result.status == "PASS"
        assert result.name == "regulatory_calendar"
        assert "n_manual=10" in result.detail

    def test_warn_empty_calendar(self, tmp_path):
        _write_metadata(
            tmp_path,
            {
                "manual_calendar_n_records": 0,
                "n_eligible_flagged": 0,
                "regulatory_secondary_coverage_pct": 0.0,
            },
        )
        config = GateConfig()
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        assert result.status == "WARN"
        assert "empty or failed" in result.detail

    def test_warn_low_coverage(self, tmp_path):
        _write_metadata(
            tmp_path,
            {
                "manual_calendar_n_records": 5,
                "n_eligible_flagged": 1,
                "regulatory_secondary_coverage_pct": 0.8,
            },
        )
        config = GateConfig(regulatory_calendar_min_coverage_pct=2.0)
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        assert result.status == "WARN"
        assert "coverage" in result.detail
        assert "floor" in result.detail

    def test_warn_missing_metadata(self, tmp_path):
        # No metadata.json at all
        config = GateConfig()
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        assert result.status == "WARN"

    def test_pass_with_zero_floor(self, tmp_path):
        """Coverage floor of 0 means no coverage check."""
        _write_metadata(
            tmp_path,
            {
                "manual_calendar_n_records": 5,
                "n_eligible_flagged": 0,
                "regulatory_secondary_coverage_pct": 0.0,
            },
        )
        config = GateConfig(regulatory_calendar_min_coverage_pct=0.0)
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        # Should not fail on coverage, only on empty calendar check
        assert result.name == "regulatory_calendar"


# ---------------------------------------------------------------------------
# Maintenance audit tests
# ---------------------------------------------------------------------------


class TestComputeProximity:
    def test_bands(self):
        records = [
            _make_record("A", "2026-03-15"),  # 5d from 2026-03-10
            _make_record("B", "2026-04-01"),  # 22d
            _make_record("C", "2026-05-15"),  # 66d
            _make_record("D", "2026-08-01"),  # 144d
        ]
        bands = compute_proximity(records, "2026-03-10")
        assert len(bands["imminent"]) == 1
        assert bands["imminent"][0]["ticker"] == "A"
        assert len(bands["near"]) == 1
        assert bands["near"][0]["ticker"] == "B"
        assert len(bands["mid"]) == 1
        assert bands["mid"][0]["ticker"] == "C"
        assert len(bands["far"]) == 1
        assert bands["far"][0]["ticker"] == "D"

    def test_past_excluded(self):
        records = [_make_record("A", "2026-03-01")]
        bands = compute_proximity(records, "2026-03-10")
        assert all(len(v) == 0 for v in bands.values())


class TestFindMissingDisclosed:
    def test_finds_missing(self):
        records = [
            {
                "ticker": "A",
                "pdufa_date": "2026-04-01",
                "as_of_disclosed_at": "",
            },
            {
                "ticker": "B",
                "pdufa_date": "2026-04-01",
                "as_of_disclosed_at": "2025-11-01",
            },
        ]
        missing = find_missing_disclosed(records, max_days=90, as_of_date="2026-03-10")
        assert len(missing) == 1
        assert missing[0]["ticker"] == "A"

    def test_ignores_far(self):
        records = [
            {
                "ticker": "A",
                "pdufa_date": "2027-01-01",
                "as_of_disclosed_at": "",
            }
        ]
        missing = find_missing_disclosed(records, max_days=90, as_of_date="2026-03-10")
        assert len(missing) == 0


class TestFindPastDated:
    def test_finds_past(self):
        records = [
            _make_record("A", "2026-02-01"),
            _make_record("B", "2026-04-01"),
        ]
        past = find_past_dated(records, "2026-03-10")
        assert len(past) == 1
        assert past[0]["ticker"] == "A"


class TestComputeFreshness:
    def test_freshness(self):
        records = [
            _make_record("A", disclosed="2025-11-01"),
            _make_record("B", disclosed="2026-01-15"),
        ]
        fresh = compute_freshness(records, "2026-03-10")
        assert fresh["newest_disclosed_at"] == "2026-01-15"
        assert fresh["age_days"] == 54
        assert fresh["n_with_disclosed"] == 2

    def test_no_disclosed(self):
        records = [{"ticker": "A", "pdufa_date": "2026-06-01"}]
        fresh = compute_freshness(records, "2026-03-10")
        assert fresh["newest_disclosed_at"] is None


class TestRunMaintenanceAudit:
    def test_full_audit(self, tmp_path):
        cal = _write_calendar(
            tmp_path,
            [
                _make_record("A", "2026-03-15", "2025-11-01"),
                _make_record("B", "2026-05-01", "2026-01-01"),
                _make_record("C", "2026-02-01", "2025-10-01"),  # past
            ],
        )
        result = run_maintenance_audit("2026-03-10", calendar_path=cal)
        assert result["raw_count"] == 3
        assert result["all_normalized"] == 3
        assert len(result["past_dated"]) == 1
        assert result["past_dated"][0]["ticker"] == "C"

    def test_write_report(self, tmp_path):
        cal = _write_calendar(
            tmp_path,
            [_make_record("A", "2026-04-01", "2025-12-01")],
        )
        result = run_maintenance_audit("2026-03-10", calendar_path=cal)
        out_dir = tmp_path / "out"
        md_path = write_report(result, out_dir)
        assert md_path.exists()
        text = md_path.read_text()
        assert "Regulatory Calendar Maintenance Report" in text
        assert (out_dir / "REPORT.json").exists()
