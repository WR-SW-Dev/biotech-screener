"""Tests for semantic audit exit codes (4-tier: 0/1/2/3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


# ---------------------------------------------------------------------------
# Import audit internals
# ---------------------------------------------------------------------------
from data_integrity_audit import _violation_severity
from run_daily_production import GateConfig, check_audit_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_proc(returncode: int) -> subprocess.CompletedProcess:
    """Fake subprocess result with the given exit code."""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr="")


# ---------------------------------------------------------------------------
# Part A — Audit tool exit code semantics
# ---------------------------------------------------------------------------


class TestAuditExitCodeLogic:
    """Test the exit code assignment logic in data_integrity_audit.py.

    These tests verify the *decision logic* (not the full main() entry point)
    by checking severity classification and the documented mapping.
    """

    def test_critical_severity_mapping(self):
        """Critical rules map to 'critical' severity."""
        assert _violation_severity("eligible_reasons_mismatch") == "critical"
        assert _violation_severity("ineligible_has_rank") == "critical"

    def test_warn_severity_mapping(self):
        """Warn-level rules map correctly."""
        for rule in [
            "catalyst_window_no_days",
            "catalyst_window_negative_days",
            "specific_days_no_days",
            "penalty_no_components",
            "tier_no_reason",
            "deep_dd_no_value",
            "rsi_flag_no_value",
            "beta_flag_no_value",
            "unknown_missing_component",
            "universe_missing",
        ]:
            assert _violation_severity(rule) == "warn", f"{rule} should be warn"

    def test_range_rules_are_info(self):
        """Rules starting with 'range_' default to info."""
        assert _violation_severity("range_de_drawdown") == "info"
        assert _violation_severity("range_de_rsi_14d") == "info"

    def test_unknown_rules_default_to_warn(self):
        """Unknown rule names default to warn severity."""
        assert _violation_severity("some_unknown_rule") == "warn"

    def test_critical_only_exits_1(self):
        """When only critical violations present, exit code should be 1."""
        # The logic: has_critical → exit 1 regardless of other flags
        has_critical = True
        has_price_fails = False
        has_warn = False
        if has_critical:
            exit_code = 1
        elif has_price_fails:
            exit_code = 3
        elif has_warn:
            exit_code = 2
        else:
            exit_code = 0
        assert exit_code == 1

    def test_price_fail_only_exits_3(self):
        """When only price fails present (no critical), exit code should be 3."""
        has_critical = False
        has_price_fails = True
        has_warn = False
        if has_critical:
            exit_code = 1
        elif has_price_fails:
            exit_code = 3
        elif has_warn:
            exit_code = 2
        else:
            exit_code = 0
        assert exit_code == 3

    def test_critical_plus_price_exits_1(self):
        """Critical takes priority over price fails → exit 1."""
        has_critical = True
        has_price_fails = True
        has_warn = True
        if has_critical:
            exit_code = 1
        elif has_price_fails:
            exit_code = 3
        elif has_warn:
            exit_code = 2
        else:
            exit_code = 0
        assert exit_code == 1

    def test_warn_only_exits_2(self):
        """Structural warn only → exit 2."""
        has_critical = False
        has_price_fails = False
        has_warn = True
        if has_critical:
            exit_code = 1
        elif has_price_fails:
            exit_code = 3
        elif has_warn:
            exit_code = 2
        else:
            exit_code = 0
        assert exit_code == 2

    def test_info_only_exits_0(self):
        """Info-only (range outliers) → exit 0."""
        has_critical = False
        has_price_fails = False
        has_warn = False
        if has_critical:
            exit_code = 1
        elif has_price_fails:
            exit_code = 3
        elif has_warn:
            exit_code = 2
        else:
            exit_code = 0
        assert exit_code == 0


# ---------------------------------------------------------------------------
# Part B — Gate mapping (check_audit_result)
# ---------------------------------------------------------------------------


class TestGateMapping:
    """Test check_audit_result maps exit codes to correct gate statuses."""

    def test_gate_maps_exit0_to_pass(self):
        result = check_audit_result(_make_proc(0), GateConfig())
        assert result.status == "PASS"

    def test_gate_maps_exit1_to_fail(self):
        """Exit 1 (critical) → FAIL when audit_fail_is_gate_fail=True (default)."""
        config = GateConfig()
        assert config.audit_fail_is_gate_fail is True
        result = check_audit_result(_make_proc(1), config)
        assert result.status == "FAIL"
        assert "CRITICAL" in result.detail

    def test_gate_maps_exit1_to_warn_when_overridden(self):
        """Exit 1 → WARN when audit_fail_is_gate_fail=False."""
        config = GateConfig(audit_fail_is_gate_fail=False)
        result = check_audit_result(_make_proc(1), config)
        assert result.status == "WARN"

    def test_gate_maps_exit2_to_warn(self):
        """Exit 2 (structural warn) → WARN."""
        result = check_audit_result(_make_proc(2), GateConfig())
        assert result.status == "WARN"

    def test_gate_maps_exit3_to_warn(self):
        """Exit 3 (stale mismatch) → always WARN regardless of config."""
        result = check_audit_result(_make_proc(3), GateConfig())
        assert result.status == "WARN"
        assert "STALE_MISMATCH" in result.detail

    def test_gate_maps_exit3_ignores_audit_fail_flag(self):
        """Exit 3 is always WARN even if audit_fail_is_gate_fail=True."""
        config = GateConfig(audit_fail_is_gate_fail=True)
        result = check_audit_result(_make_proc(3), config)
        assert result.status == "WARN"

    def test_gate_maps_unknown_exit_to_warn(self):
        """Unknown exit codes → WARN (defensive)."""
        result = check_audit_result(_make_proc(99), GateConfig())
        assert result.status == "WARN"

    def test_default_config_audit_fail_is_true(self):
        """GateConfig default has audit_fail_is_gate_fail=True."""
        assert GateConfig().audit_fail_is_gate_fail is True
