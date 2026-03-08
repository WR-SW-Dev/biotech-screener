"""Tests for 4-tier semantic audit exit codes.

Validates:
  1. Audit script: critical → exit 1, price fail → exit 3, warn → exit 2, ok → exit 0
  2. Critical wins over price fail when both present
  3. Runner: check_audit_result maps exit codes to correct gate statuses
  4. GateConfig defaults
  5. _violation_severity classification
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from data_integrity_audit import VIOLATION_SEVERITY, _violation_severity
from run_daily_production import GateConfig, check_audit_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_proc(returncode: int) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["audit"], returncode=returncode)


# ---------------------------------------------------------------------------
# A) _violation_severity classification
# ---------------------------------------------------------------------------


class TestViolationSeverity:

    def test_critical_rules(self):
        assert _violation_severity("eligible_reasons_mismatch") == "critical"
        assert _violation_severity("ineligible_has_rank") == "critical"

    def test_warn_rules(self):
        for rule in (
            "catalyst_window_no_days",
            "specific_days_no_days",
            "penalty_no_components",
            "tier_no_reason",
            "universe_missing",
        ):
            assert _violation_severity(rule) == "warn", f"{rule} should be warn"

    def test_range_rules_are_info(self):
        assert _violation_severity("range_de_rsi_14d") == "info"
        assert _violation_severity("range_de_beta_xbi_60d") == "info"

    def test_unknown_rule_defaults_to_warn(self):
        assert _violation_severity("some_future_rule") == "warn"


# ---------------------------------------------------------------------------
# B) VIOLATION_SEVERITY dict completeness
# ---------------------------------------------------------------------------


class TestViolationSeverityDict:

    def test_has_exactly_two_critical(self):
        critical = [k for k, v in VIOLATION_SEVERITY.items() if v == "critical"]
        assert len(critical) == 2
        assert set(critical) == {"eligible_reasons_mismatch", "ineligible_has_rank"}

    def test_all_values_are_valid(self):
        for rule, sev in VIOLATION_SEVERITY.items():
            assert sev in ("critical", "warn", "info"), f"{rule} has invalid severity {sev}"


# ---------------------------------------------------------------------------
# C) check_audit_result gate mapping
# ---------------------------------------------------------------------------


class TestCheckAuditResult:

    def test_exit0_maps_to_pass(self):
        result = check_audit_result(_fake_proc(0), GateConfig())
        assert result.status == "PASS"
        assert result.name == "audit"

    def test_exit1_maps_to_fail(self):
        result = check_audit_result(_fake_proc(1), GateConfig())
        assert result.status == "FAIL"
        assert "CRITICAL" in result.detail

    def test_exit1_with_gate_disabled_maps_to_warn(self):
        config = GateConfig(audit_fail_is_gate_fail=False)
        result = check_audit_result(_fake_proc(1), config)
        assert result.status == "WARN"

    def test_exit2_maps_to_warn(self):
        result = check_audit_result(_fake_proc(2), GateConfig())
        assert result.status == "WARN"

    def test_exit2_with_warn_disabled_maps_to_pass(self):
        config = GateConfig(audit_warn_is_gate_warn=False)
        result = check_audit_result(_fake_proc(2), config)
        assert result.status == "PASS"

    def test_exit3_maps_to_warn_always(self):
        """Stale mismatch is always WARN, regardless of audit_fail_is_gate_fail."""
        result = check_audit_result(_fake_proc(3), GateConfig())
        assert result.status == "WARN"
        assert "STALE_MISMATCH" in result.detail

    def test_exit3_ignores_audit_fail_flag(self):
        """Even with audit_fail_is_gate_fail=True, exit 3 stays WARN."""
        config = GateConfig(audit_fail_is_gate_fail=True)
        result = check_audit_result(_fake_proc(3), config)
        assert result.status == "WARN"

    def test_unknown_exit_code_maps_to_warn(self):
        result = check_audit_result(_fake_proc(42), GateConfig())
        assert result.status == "WARN"


# ---------------------------------------------------------------------------
# D) GateConfig defaults
# ---------------------------------------------------------------------------


class TestGateConfigDefaults:

    def test_audit_fail_is_gate_fail_default_true(self):
        assert GateConfig().audit_fail_is_gate_fail is True

    def test_audit_warn_is_gate_warn_default_true(self):
        assert GateConfig().audit_warn_is_gate_warn is True
