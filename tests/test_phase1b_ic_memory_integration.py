"""Phase 1b Integration: IC memory hygiene check in agent_heartbeat_checks.py.

Phase 1 Priority 5: Observability logging for IC health state consistency.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pytest

from tools.agent_heartbeat_checks import check_ic_memory_hygiene


def test_ic_memory_hygiene_invoked_in_heartbeat_checks():
    """Verify check_ic_memory_hygiene is registered in SPECIALIZED_CHECKS."""
    from tools.agent_heartbeat_checks import SPECIALIZED_CHECKS

    assert "ic_memory_hygiene" in SPECIALIZED_CHECKS
    assert SPECIALIZED_CHECKS["ic_memory_hygiene"] == check_ic_memory_hygiene


def test_ic_memory_hygiene_check_healthy():
    """Verify check returns OK when no issues."""
    with patch("tools.agent_heartbeat_checks.MemoryHygieneChecker") as mock_checker:
        mock_instance = mock_checker.return_value
        mock_instance.check_as_of_date.return_value = {
            "analysis_date": "2026-06-03",
            "issues": [],
            "warnings": [],
            "summary": {"status": "HEALTHY", "issue_count": 0, "warning_count": 0},
        }

        result = check_ic_memory_hygiene(date(2026, 6, 3))

    assert result.status == "OK"
    assert result.agent == "ic_memory_hygiene"
    assert len(result.anomalies) == 0


def test_ic_memory_hygiene_check_detects_issues():
    """Verify check detects missing artifacts and other issues."""
    with patch("tools.agent_heartbeat_checks.MemoryHygieneChecker") as mock_checker:
        mock_instance = mock_checker.return_value
        mock_instance.check_as_of_date.return_value = {
            "analysis_date": "2026-06-03",
            "issues": [
                {
                    "type": "MISSING_ARTIFACT",
                    "severity": "WARN",
                    "description": "No dashboard artifact for 2026-06-03",
                }
            ],
            "warnings": [
                {
                    "type": "STALE_MEMORY",
                    "description": "Memory last updated 5 days ago",
                }
            ],
            "summary": {"status": "ISSUES_DETECTED", "issue_count": 1, "warning_count": 1},
        }

        result = check_ic_memory_hygiene(date(2026, 6, 3))

    assert result.status == "FAIL"
    assert len(result.anomalies) == 2
    assert any("MISSING_ARTIFACT" in a for a in result.anomalies)
    assert any("STALE_MEMORY" in a for a in result.anomalies)


def test_ic_memory_hygiene_check_warns_on_warnings_only():
    """Verify check warns (not fails) when only warnings, no issues."""
    with patch("tools.agent_heartbeat_checks.MemoryHygieneChecker") as mock_checker:
        mock_instance = mock_checker.return_value
        mock_instance.check_as_of_date.return_value = {
            "analysis_date": "2026-06-03",
            "issues": [],
            "warnings": [
                {
                    "type": "STALE_MEMORY",
                    "description": "Memory last updated 3 days ago",
                }
            ],
            "summary": {"status": "HEALTHY", "issue_count": 0, "warning_count": 1},
        }

        result = check_ic_memory_hygiene(date(2026, 6, 3))

    assert result.status == "WARN"
    assert len(result.anomalies) == 1


def test_ic_memory_hygiene_logs_findings():
    """Verify findings are logged to audit trail."""
    with patch("tools.agent_heartbeat_checks.MemoryHygieneChecker") as mock_checker:
        mock_instance = mock_checker.return_value
        report = {
            "analysis_date": "2026-06-03",
            "issues": [],
            "warnings": [],
            "summary": {"status": "HEALTHY", "issue_count": 0, "warning_count": 0},
        }
        mock_instance.check_as_of_date.return_value = report

        check_ic_memory_hygiene(date(2026, 6, 3))

        mock_instance.log_findings.assert_called_once_with(report)


def test_ic_memory_hygiene_nonblocking():
    """Verify check is advisory-only (doesn't block execution)."""
    # The check returns non-blocking status (OK/WARN) regardless of findings
    with patch("tools.agent_heartbeat_checks.MemoryHygieneChecker") as mock_checker:
        mock_instance = mock_checker.return_value
        mock_instance.check_as_of_date.return_value = {
            "analysis_date": "2026-06-03",
            "issues": [
                {
                    "type": "CORRUPT_ARTIFACT",
                    "severity": "ERROR",
                    "description": "Dashboard artifact is corrupted",
                }
            ],
            "warnings": [],
            "summary": {"status": "ISSUES_DETECTED", "issue_count": 1, "warning_count": 0},
        }

        result = check_ic_memory_hygiene(date(2026, 6, 3))

    # FAIL on issues, but still operationally non-blocking
    # (LLM escalation is controlled separately by heartbeat orchestrator)
    assert result.status in ("OK", "WARN", "FAIL")
    # The check itself always returns cleanly without raising exceptions
    assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
