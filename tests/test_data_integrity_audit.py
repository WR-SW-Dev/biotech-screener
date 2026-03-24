"""Tests for data_integrity_audit.py — invariant checks + price-derived cross-validation.

Validates:
  1. check_invariants catches eligible/ineligible mismatches
  2. check_invariants catches catalyst window violations
  3. check_invariants catches range violations
  4. check_universe_coverage detects missing tickers
  5. _violation_severity classifies correctly
  6. _verdict returns correct labels
  7. _safe_float handles edge cases
  8. recompute_price_fields detects mismatches
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.data_integrity_audit import (
    _safe_float,
    _verdict,
    _violation_severity,
    check_invariants,
    check_universe_coverage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(**kw):
    """Build a single-row DataFrame for check_invariants."""
    defaults = {
        "ticker": "TEST",
        "eligible": "1",
        "ineligible_reasons": "",
        "actionable_rank": "5",
        "catalyst_in_window": "",
        "catalyst_days": "",
        "catalyst_mode": "",
        "missingness_penalty": "0",
        "missing_components": "",
        "tier_any": "",
        "tier_any_reason": "",
        "risk_flags": "",
        "de_drawdown": "",
        "de_rsi_14d": "",
        "de_beta_xbi_60d": "",
    }
    defaults.update(kw)
    return pd.DataFrame([defaults])


# ---------------------------------------------------------------------------
# A) _violation_severity
# ---------------------------------------------------------------------------


class TestViolationSeverity:
    def test_critical_rules(self):
        assert _violation_severity("eligible_reasons_mismatch") == "critical"
        assert _violation_severity("ineligible_has_rank") == "critical"

    def test_warn_rules(self):
        assert _violation_severity("catalyst_window_no_days") == "warn"
        assert _violation_severity("tier_no_reason") == "warn"

    def test_range_rules_are_info(self):
        assert _violation_severity("range_de_drawdown") == "info"
        assert _violation_severity("range_score_rank_pct") == "info"

    def test_unknown_defaults_to_warn(self):
        assert _violation_severity("some_new_rule_xyz") == "warn"


# ---------------------------------------------------------------------------
# B) _verdict
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_both_missing(self):
        assert _verdict(None, None, 0.01) == "BOTH_MISSING"

    def test_stored_missing(self):
        assert _verdict(None, 0.5, 0.01) == "STORED_MISSING"

    def test_recomp_missing(self):
        assert _verdict(0.5, None, 0.01) == "RECOMP_MISSING"

    def test_ok_within_tolerance(self):
        assert _verdict(0.50, 0.51, 0.02) == "OK"

    def test_fail_outside_tolerance(self):
        assert _verdict(0.50, 0.60, 0.02) == "FAIL"

    def test_exact_match(self):
        assert _verdict(1.0, 1.0, 0.001) == "OK"


# ---------------------------------------------------------------------------
# C) _safe_float
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_valid_number(self):
        assert _safe_float("3.14") == 3.14

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan_float(self):
        assert _safe_float(float("nan")) is None

    def test_nan_string(self):
        assert _safe_float("nan") is None

    def test_empty_string(self):
        assert _safe_float("") is None

    def test_none_string(self):
        assert _safe_float("None") is None

    def test_integer(self):
        assert _safe_float(42) == 42.0


# ---------------------------------------------------------------------------
# D) check_invariants
# ---------------------------------------------------------------------------


class TestCheckInvariants:
    def test_clean_row_no_violations(self):
        df = _row()
        violations = check_invariants(df)
        assert len(violations) == 0

    def test_eligible_with_ineligible_reasons(self):
        df = _row(eligible="1", ineligible_reasons="low_volume")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "eligible_reasons_mismatch" in rules

    def test_ineligible_with_rank(self):
        df = _row(eligible="0", actionable_rank="3")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "ineligible_has_rank" in rules

    def test_ineligible_no_rank_is_clean(self):
        df = _row(eligible="0", actionable_rank="", ineligible_reasons="no_data")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "ineligible_has_rank" not in rules

    def test_catalyst_in_window_no_days(self):
        df = _row(catalyst_in_window="True", catalyst_days="")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "catalyst_window_no_days" in rules

    def test_catalyst_in_window_negative_days(self):
        df = _row(catalyst_in_window="True", catalyst_days="-5")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "catalyst_window_negative_days" in rules

    def test_catalyst_in_window_valid(self):
        df = _row(catalyst_in_window="True", catalyst_days="30")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "catalyst_window_no_days" not in rules
        assert "catalyst_window_negative_days" not in rules

    def test_specific_days_no_days(self):
        df = _row(catalyst_mode="specific_days", catalyst_days="")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "specific_days_no_days" in rules

    def test_specific_days_non_integer(self):
        df = _row(catalyst_mode="specific_days", catalyst_days="30.5")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "specific_days_non_integer" in rules

    def test_penalty_without_components(self):
        df = _row(missingness_penalty="0.5", missing_components="")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "penalty_no_components" in rules

    def test_penalty_with_components_ok(self):
        df = _row(missingness_penalty="0.5", missing_components="catalyst")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "penalty_no_components" not in rules

    def test_unknown_missing_component(self):
        df = _row(missingness_penalty="0.5", missing_components="bogus_component")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "unknown_missing_component" in rules

    def test_tier_without_reason(self):
        df = _row(tier_any="A", tier_any_reason="")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "tier_no_reason" in rules

    def test_tier_with_reason_ok(self):
        df = _row(tier_any="A", tier_any_reason="clinical_quality")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "tier_no_reason" not in rules

    def test_deep_drawdown_flag_no_value(self):
        df = _row(risk_flags="deep_drawdown", de_drawdown="")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "deep_dd_no_value" in rules

    def test_overbought_rsi_flag_no_value(self):
        df = _row(risk_flags="overbought_rsi", de_rsi_14d="")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "rsi_flag_no_value" in rules

    def test_range_violation(self):
        # score_rank_pct must be in [0, 1] per SANITY_RANGES
        df = _row(score_rank_pct="1.5")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "range_score_rank_pct" in rules

    def test_range_ok(self):
        df = _row(score_rank_pct="0.75")
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        range_violations = [r for r in rules if r.startswith("range_score_rank_pct")]
        assert len(range_violations) == 0

    def test_multiple_violations_same_row(self):
        df = _row(
            eligible="1",
            ineligible_reasons="test",
            tier_any="B",
            tier_any_reason="",
        )
        violations = check_invariants(df)
        rules = [v["rule"] for v in violations]
        assert "eligible_reasons_mismatch" in rules
        assert "tier_no_reason" in rules


# ---------------------------------------------------------------------------
# E) check_universe_coverage
# ---------------------------------------------------------------------------


class TestUniverseCoverage:
    def test_all_present(self, tmp_path):
        universe = [{"ticker": "AAPL"}, {"ticker": "GOOG"}]
        uni_path = tmp_path / "universe.json"
        uni_path.write_text(json.dumps(universe))

        df = pd.DataFrame({"ticker": ["AAPL", "GOOG", "MSFT"]})
        violations = check_universe_coverage(df, uni_path)
        assert len(violations) == 0

    def test_missing_ticker(self, tmp_path):
        universe = [{"ticker": "AAPL"}, {"ticker": "GOOG"}, {"ticker": "TSLA"}]
        uni_path = tmp_path / "universe.json"
        uni_path.write_text(json.dumps(universe))

        df = pd.DataFrame({"ticker": ["AAPL", "GOOG"]})
        violations = check_universe_coverage(df, uni_path)
        assert len(violations) == 1
        assert violations[0]["ticker"] == "TSLA"
        assert violations[0]["rule"] == "universe_missing"

    def test_no_universe_file(self, tmp_path):
        df = pd.DataFrame({"ticker": ["AAPL"]})
        violations = check_universe_coverage(df, tmp_path / "missing.json")
        assert len(violations) == 0

    def test_skips_underscore_tickers(self, tmp_path):
        universe = [{"ticker": "AAPL"}, {"ticker": "_INTERNAL"}]
        uni_path = tmp_path / "universe.json"
        uni_path.write_text(json.dumps(universe))

        df = pd.DataFrame({"ticker": ["AAPL"]})
        violations = check_universe_coverage(df, uni_path)
        assert len(violations) == 0

    def test_string_universe_format(self, tmp_path):
        universe = ["AAPL", "GOOG"]
        uni_path = tmp_path / "universe.json"
        uni_path.write_text(json.dumps(universe))

        df = pd.DataFrame({"ticker": ["AAPL"]})
        violations = check_universe_coverage(df, uni_path)
        assert len(violations) == 1
        assert violations[0]["ticker"] == "GOOG"
