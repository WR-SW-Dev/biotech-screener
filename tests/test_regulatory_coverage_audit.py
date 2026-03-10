"""Tests for scripts/research/audit_regulatory_calendar_coverage.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.audit_regulatory_calendar_coverage import (
    compute_coverage,
    compute_overlap,
    find_prior_snapshot,
    find_snapshot,
    run_audit,
)


def _make_snapshot(tmp_path, date, rows):
    """Create a fake snapshot directory with rankings.csv."""
    snap_dir = tmp_path / date
    snap_dir.mkdir(parents=True, exist_ok=True)
    if rows:
        fieldnames = rows[0].keys()
        with open(snap_dir / "rankings.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
    return snap_dir


def _make_calendar(tmp_path, records):
    p = tmp_path / "pdufa_dates.json"
    p.write_text(json.dumps(records), encoding="utf-8")
    return p


def _eligible_row(ticker, flagged=False, days="", event_type=""):
    return {
        "ticker": ticker,
        "eligible": "1",
        "has_regulatory_upcoming_180d": "1" if flagged else "0",
        "regulatory_days": days,
        "regulatory_event_type": event_type,
    }


class TestFindSnapshot:
    def test_finds_existing(self, tmp_path):
        _make_snapshot(tmp_path, "2026-03-08", [_eligible_row("A")])
        assert find_snapshot(tmp_path, "2026-03-08") is not None

    def test_returns_none_missing(self, tmp_path):
        assert find_snapshot(tmp_path, "2026-03-08") is None


class TestComputeCoverage:
    def test_basic(self):
        rows = [
            _eligible_row("A", flagged=True, days="30", event_type="PDUFA"),
            _eligible_row("B", flagged=False),
            _eligible_row("C", flagged=True, days="60", event_type="FDA_ADCOM"),
        ]
        eligible, flagged, details = compute_coverage(rows)
        assert eligible == 3
        assert flagged == 2
        assert details[0]["ticker"] == "A"  # 30d < 60d

    def test_no_flagged(self):
        rows = [_eligible_row("A"), _eligible_row("B")]
        eligible, flagged, details = compute_coverage(rows)
        assert flagged == 0
        assert details == []


class TestComputeOverlap:
    def test_overlap(self):
        kept, added, dropped = compute_overlap({"A", "B", "C"}, {"B", "C", "D"})
        assert kept == {"B", "C"}
        assert added == {"A"}
        assert dropped == {"D"}


class TestFindPriorSnapshot:
    def test_finds_prior(self, tmp_path):
        _make_snapshot(tmp_path, "2026-03-07", [_eligible_row("A")])
        _make_snapshot(tmp_path, "2026-03-08", [_eligible_row("A")])
        prior = find_prior_snapshot(tmp_path, "2026-03-08")
        assert prior is not None
        assert prior.name == "2026-03-07"

    def test_no_prior(self, tmp_path):
        _make_snapshot(tmp_path, "2026-03-08", [_eligible_row("A")])
        assert find_prior_snapshot(tmp_path, "2026-03-08") is None


class TestRunAudit:
    def test_full_audit(self, tmp_path):
        rows = [
            _eligible_row("A", flagged=True, days="30", event_type="PDUFA"),
            _eligible_row("B"),
        ]
        _make_snapshot(tmp_path, "2026-03-08", rows)
        cal = _make_calendar(
            tmp_path,
            [
                {
                    "ticker": "A",
                    "pdufa_date": "2026-04-07",
                    "event_type": "PDUFA",
                    "confidence": "HIGH",
                    "source": "COMPANY_GUIDANCE",
                    "as_of_disclosed_at": "2025-10-07",
                }
            ],
        )

        result = run_audit("2026-03-08", tmp_path, calendar_path=cal)
        assert result["exit_code"] == 0
        assert result["manual_calendar"]["pit_eligible"] == 1
        assert result["snapshot"]["flagged_count"] == 1
        assert result["snapshot"]["coverage_pct"] == 50.0

    def test_pit_zero_warns(self, tmp_path):
        """Manual has records but all disclosed after as_of → exit 1."""
        rows = [_eligible_row("A")]
        _make_snapshot(tmp_path, "2026-03-08", rows)
        cal = _make_calendar(
            tmp_path,
            [
                {
                    "ticker": "A",
                    "pdufa_date": "2026-05-01",
                    "event_type": "PDUFA",
                    "confidence": "HIGH",
                    "source": "MANUAL",
                    "as_of_disclosed_at": "2026-12-01",  # future
                }
            ],
        )
        result = run_audit("2026-03-08", tmp_path, calendar_path=cal)
        assert result["exit_code"] == 1
        assert "schema error" in result["manual_calendar"].get("warning", "")

    def test_missing_snapshot(self, tmp_path):
        cal = _make_calendar(tmp_path, [])
        result = run_audit("2026-03-08", tmp_path, calendar_path=cal)
        assert "error" in result.get("snapshot", {})

    def test_overlap_computed(self, tmp_path):
        _make_snapshot(
            tmp_path,
            "2026-03-07",
            [_eligible_row("A", flagged=True, days="30", event_type="PDUFA")],
        )
        _make_snapshot(
            tmp_path,
            "2026-03-08",
            [
                _eligible_row("A", flagged=True, days="29", event_type="PDUFA"),
                _eligible_row("B", flagged=True, days="60", event_type="FDA_ADCOM"),
            ],
        )
        cal = _make_calendar(tmp_path, [])
        result = run_audit("2026-03-08", tmp_path, calendar_path=cal)
        assert "overlap" in result
        assert "A" in result["overlap"]["kept"]
        assert "B" in result["overlap"]["added"]
