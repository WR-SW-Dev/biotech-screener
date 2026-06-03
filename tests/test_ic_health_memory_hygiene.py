"""Tests for IC Health Memory Hygiene — Stale-memory/artifact mismatch detection.

Phase 1 Priority 5: Observability logging for IC health state consistency.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.ic_health_memory_hygiene import MemoryHygieneChecker


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories for testing."""
    memory_dir = tmp_path / "memory"
    artifact_dir = tmp_path / "artifacts"
    hygiene_log = tmp_path / "hygiene.jsonl"
    memory_dir.mkdir()
    artifact_dir.mkdir()
    return {
        "memory_dir": memory_dir,
        "artifact_dir": artifact_dir,
        "log_path": hygiene_log,
    }


@pytest.fixture
def checker(temp_dirs):
    """Create checker with temp directories."""
    with patch("tools.ic_health_memory_hygiene.IC_MEMORY_DIR", temp_dirs["memory_dir"]):
        with patch("tools.ic_health_memory_hygiene.IC_ARTIFACTS_DIR", temp_dirs["artifact_dir"]):
            with patch("tools.ic_health_memory_hygiene.HYGIENE_LOG_PATH", temp_dirs["log_path"]):
                checker = MemoryHygieneChecker()
                yield checker


# ---------------------------------------------------------------------------
# Basic Date Parsing
# ---------------------------------------------------------------------------


def test_parse_date_valid():
    """Parse valid date string."""
    checker = MemoryHygieneChecker()
    parsed = checker._parse_date("2026-06-01")
    assert parsed == date(2026, 6, 1)


def test_parse_date_invalid_falls_back_to_today():
    """Invalid date string falls back to today."""
    checker = MemoryHygieneChecker()
    parsed = checker._parse_date("invalid")
    assert parsed == date.today()


# ---------------------------------------------------------------------------
# Memory File Detection
# ---------------------------------------------------------------------------


def test_get_latest_memory_file_when_none_exist(checker, temp_dirs):
    """Returns None when no memory files exist."""
    latest = checker._get_latest_memory_file()
    assert latest is None


def test_get_latest_memory_file_single_file(checker, temp_dirs):
    """Returns the only memory file."""
    memory_file = temp_dirs["memory_dir"] / "2026-05-20.md"
    memory_file.write_text("# Memory")

    latest = checker._get_latest_memory_file()
    assert latest == memory_file


def test_get_latest_memory_file_multiple_files(checker, temp_dirs):
    """Returns the most recent memory file."""
    (temp_dirs["memory_dir"] / "2026-05-15.md").write_text("# Old")
    (temp_dirs["memory_dir"] / "2026-05-25.md").write_text("# Recent")
    (temp_dirs["memory_dir"] / "2026-05-20.md").write_text("# Middle")

    latest = checker._get_latest_memory_file()
    assert latest.name == "2026-05-25.md"


# ---------------------------------------------------------------------------
# Artifact Checks
# ---------------------------------------------------------------------------


def test_check_detects_missing_artifact(checker, temp_dirs):
    """Detects when dashboard artifact is missing."""
    check_date = date(2026, 6, 1)

    report = checker.check_as_of_date(check_date)

    assert not report["has_artifact"]
    assert len(report["issues"]) == 1
    assert report["issues"][0]["type"] == "MISSING_ARTIFACT"
    assert report["summary"]["status"] == "ISSUES_DETECTED"


def test_check_detects_corrupt_artifact(checker, temp_dirs):
    """Detects when artifact JSON is corrupted."""
    artifact_file = temp_dirs["artifact_dir"] / "2026-06-01_dashboard.json"
    artifact_file.write_text("{invalid json}")

    report = checker.check_as_of_date(date(2026, 6, 1))

    assert report["has_artifact"]
    assert len(report["issues"]) == 1
    assert report["issues"][0]["type"] == "CORRUPT_ARTIFACT"


def test_check_passes_valid_artifact(checker, temp_dirs):
    """Passes when valid artifact exists."""
    artifact_file = temp_dirs["artifact_dir"] / "2026-06-01_dashboard.json"
    artifact_file.write_text(
        json.dumps(
            {
                "attention": "OK",
                "signals": {},
                "generated_at": datetime.now().isoformat(),
            }
        )
    )

    report = checker.check_as_of_date(date(2026, 6, 1))

    assert report["has_artifact"]
    assert len(report["issues"]) == 0


# ---------------------------------------------------------------------------
# Memory Freshness Checks
# ---------------------------------------------------------------------------


def test_check_detects_stale_memory(checker, temp_dirs):
    """Detects when memory hasn't been updated recently."""
    old_memory = temp_dirs["memory_dir"] / "2026-05-20.md"
    old_memory.write_text("# Old memory")

    # Check for a date 5 days later
    report = checker.check_as_of_date(date(2026, 5, 25))

    assert report["has_memory"]
    assert len(report["warnings"]) == 1
    assert report["warnings"][0]["type"] == "STALE_MEMORY"
    assert report["warnings"][0]["memory_age_days"] == 5


def test_check_passes_fresh_memory(checker, temp_dirs):
    """Passes when memory is recent."""
    recent_memory = temp_dirs["memory_dir"] / "2026-06-01.md"
    recent_memory.write_text("# Recent memory")

    report = checker.check_as_of_date(date(2026, 6, 1))

    # Might have other issues, but not stale memory
    stale_warnings = [w for w in report["warnings"] if w["type"] == "STALE_MEMORY"]
    assert len(stale_warnings) == 0


# ---------------------------------------------------------------------------
# Memory vs Artifact Consistency
# ---------------------------------------------------------------------------


def test_detects_memory_overstates_issues(checker, temp_dirs):
    """Detects when memory claims issues but artifact is healthy."""
    memory = temp_dirs["memory_dir"] / "2026-06-01.md"
    memory.write_text("# ALERT: inst_delta_z is problematic")

    artifact = temp_dirs["artifact_dir"] / "2026-06-01_dashboard.json"
    artifact.write_text(
        json.dumps(
            {
                "attention": "OK",
                "signals": {},
                "generated_at": datetime.now().isoformat(),
            }
        )
    )

    report = checker.check_as_of_date(date(2026, 6, 1))

    overstated = [w for w in report["warnings"] if w["type"] == "MEMORY_OVERSTATES_ISSUES"]
    assert len(overstated) == 1


def test_detects_undocumented_artifact_issues(checker, temp_dirs):
    """Detects when artifact shows issues but memory doesn't document them."""
    memory = temp_dirs["memory_dir"] / "2026-06-01.md"
    memory.write_text("# Everything looks fine")

    artifact = temp_dirs["artifact_dir"] / "2026-06-01_dashboard.json"
    artifact.write_text(
        json.dumps(
            {
                "attention": "ALERT",
                "signals": {},
                "generated_at": datetime.now().isoformat(),
            }
        )
    )

    report = checker.check_as_of_date(date(2026, 6, 1))

    undocumented = [w for w in report["warnings"] if w["type"] == "ARTIFACT_ISSUES_UNDOCUMENTED"]
    assert len(undocumented) == 1


# ---------------------------------------------------------------------------
# Artifact Age Checks
# ---------------------------------------------------------------------------


def test_detects_stale_artifact(checker, temp_dirs):
    """Detects when artifact hasn't been regenerated recently."""
    old_time = (datetime.now() - timedelta(hours=72)).isoformat()

    artifact = temp_dirs["artifact_dir"] / "2026-06-01_dashboard.json"
    artifact.write_text(
        json.dumps(
            {
                "attention": "OK",
                "signals": {},
                "generated_at": old_time,
            }
        )
    )

    report = checker.check_as_of_date(date(2026, 6, 1))

    stale = [w for w in report["warnings"] if w["type"] == "STALE_ARTIFACT"]
    assert len(stale) == 1
    assert stale[0]["age_hours"] > 48


def test_passes_fresh_artifact(checker, temp_dirs):
    """Passes when artifact is recent."""
    fresh_time = datetime.now().isoformat()

    artifact = temp_dirs["artifact_dir"] / "2026-06-01_dashboard.json"
    artifact.write_text(
        json.dumps(
            {
                "attention": "OK",
                "signals": {},
                "generated_at": fresh_time,
            }
        )
    )

    report = checker.check_as_of_date(date(2026, 6, 1))

    stale = [w for w in report["warnings"] if w["type"] == "STALE_ARTIFACT"]
    assert len(stale) == 0


# ---------------------------------------------------------------------------
# Critical Signal Detection
# ---------------------------------------------------------------------------


def test_detects_undocumented_critical_signals(checker, temp_dirs):
    """Detects CRITICAL signals not mentioned in memory."""
    memory = temp_dirs["memory_dir"] / "2026-06-01.md"
    memory.write_text("# All systems nominal")

    artifact = temp_dirs["artifact_dir"] / "2026-06-01_dashboard.json"
    artifact.write_text(
        json.dumps(
            {
                "attention": "CRITICAL",
                "signals": {
                    "inst_delta_z": {"health": "CRITICAL"},
                    "score_rank_pct": {"health": "OK"},
                },
                "generated_at": datetime.now().isoformat(),
            }
        )
    )

    report = checker.check_as_of_date(date(2026, 6, 1))

    critical_found = [w for w in report["warnings"] if w["type"] == "CRITICAL_SIGNAL_NOT_DOCUMENTED"]
    assert len(critical_found) == 1
    assert critical_found[0]["signal"] == "inst_delta_z"


def test_passes_when_critical_signals_documented(checker, temp_dirs):
    """Passes when CRITICAL signals are documented in memory."""
    memory = temp_dirs["memory_dir"] / "2026-06-01.md"
    memory.write_text("# ALERT: inst_delta_z is critical")

    artifact = temp_dirs["artifact_dir"] / "2026-06-01_dashboard.json"
    artifact.write_text(
        json.dumps(
            {
                "attention": "CRITICAL",
                "signals": {
                    "inst_delta_z": {"health": "CRITICAL"},
                },
                "generated_at": datetime.now().isoformat(),
            }
        )
    )

    report = checker.check_as_of_date(date(2026, 6, 1))

    critical_found = [w for w in report["warnings"] if w["type"] == "CRITICAL_SIGNAL_NOT_DOCUMENTED"]
    assert len(critical_found) == 0


# ---------------------------------------------------------------------------
# Report Logging
# ---------------------------------------------------------------------------


def test_log_findings_creates_jsonl(checker, temp_dirs):
    """Logs findings to JSONL file."""
    report = {
        "analysis_date": "2026-06-01",
        "check_timestamp": datetime.now().isoformat(),
        "issues": [],
        "warnings": [],
    }

    with patch("tools.ic_health_memory_hygiene.HYGIENE_LOG_PATH", temp_dirs["log_path"]):
        checker.log_findings(report)

    assert temp_dirs["log_path"].exists()
    content = temp_dirs["log_path"].read_text()
    logged = json.loads(content.strip())
    assert logged["analysis_date"] == "2026-06-01"


def test_log_findings_appends_to_existing_log(checker, temp_dirs):
    """Appends to existing log without overwriting."""
    log_path = temp_dirs["log_path"]

    # Write initial entry
    log_path.write_text('{"date": "2026-06-01"}\n')

    report = {
        "analysis_date": "2026-06-02",
        "check_timestamp": datetime.now().isoformat(),
        "issues": [],
        "warnings": [],
    }

    with patch("tools.ic_health_memory_hygiene.HYGIENE_LOG_PATH", log_path):
        checker.log_findings(report)

    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["date"] == "2026-06-01"
    assert json.loads(lines[1])["analysis_date"] == "2026-06-02"


# ---------------------------------------------------------------------------
# Summary Reporting
# ---------------------------------------------------------------------------


def test_summary_status_healthy(checker):
    """Summary reports HEALTHY status when no issues."""
    summary = checker._summarize([], [])
    assert summary["status"] == "HEALTHY"
    assert not summary["requires_investigation"]


def test_summary_status_issues_detected(checker):
    """Summary reports ISSUES_DETECTED when issues present."""
    issues = [{"type": "MISSING_ARTIFACT"}]
    summary = checker._summarize(issues, [])
    assert summary["status"] == "ISSUES_DETECTED"
    assert summary["requires_investigation"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
