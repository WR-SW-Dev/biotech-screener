"""Tests for the calendar-change A/B gate.

Covers:
  1. compute_verdict — PASS, FAIL, WARN scenarios
  2. classify_calendar_edits — HYGIENE_ONLY / SIGNAL_BEARING / MIXED
  3. apply_hygiene_override — override policy
  4. build_diagnostic_block — diagnostic content
  5. write_ab_receipt — output files + content checks
  6. _safe_delta / formatting helpers
  7. Exit code mapping (PASS/HYGIENE_OVERRIDE=0, FAIL=1, WARN=2)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.gate_calendar_change_ab import (
    _fmt_pct,
    _fmt_pp,
    _safe_delta,
    apply_hygiene_override,
    build_diagnostic_block,
    classify_calendar_edits,
    compute_verdict,
    write_ab_receipt,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cal_entry(
    ticker="ACME",
    pdufa_date="2026-06-01",
    event_type="PDUFA",
    source="COMPANY_GUIDANCE",
    confidence="HIGH",
    disclosed="2026-01-01",
    notes="",
):
    return {
        "ticker": ticker,
        "pdufa_date": pdufa_date,
        "event_type": event_type,
        "source": source,
        "confidence": confidence,
        "as_of_disclosed_at": disclosed,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# 1. compute_verdict
# ---------------------------------------------------------------------------


class TestComputeVerdict:
    def test_all_pass(self):
        base = {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15}
        cand = {"cum_hedged": 0.1030, "mean_hedged": 0.0055, "mean_turnover": 0.15}
        v = compute_verdict(base, cand)
        assert v["verdict"] == "PASS"
        assert v["cum_hedged_pass"] is True
        assert v["mean_hedged_pass"] is True
        assert v["turnover_pass"] is True

    def test_fail_cumulative(self):
        """Cum delta below threshold but guardrail + turnover pass → WARN."""
        base = {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15}
        cand = {"cum_hedged": 0.1010, "mean_hedged": 0.005, "mean_turnover": 0.15}
        v = compute_verdict(base, cand)
        assert v["verdict"] == "WARN"

    def test_fail_guardrail(self):
        base = {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15}
        cand = {"cum_hedged": 0.11, "mean_hedged": 0.0040, "mean_turnover": 0.15}
        v = compute_verdict(base, cand)
        assert v["verdict"] == "FAIL"
        assert v["mean_hedged_pass"] is False

    def test_fail_turnover(self):
        base = {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15}
        cand = {"cum_hedged": 0.11, "mean_hedged": 0.005, "mean_turnover": 0.1550}
        v = compute_verdict(base, cand)
        assert v["verdict"] == "FAIL"
        assert v["turnover_pass"] is False

    def test_none_values_fail(self):
        base = {"cum_hedged": None, "mean_hedged": None, "mean_turnover": None}
        cand = {"cum_hedged": None, "mean_hedged": None, "mean_turnover": None}
        v = compute_verdict(base, cand)
        assert v["verdict"] == "FAIL"

    def test_custom_thresholds(self):
        base = {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15}
        cand = {"cum_hedged": 0.1005, "mean_hedged": 0.005, "mean_turnover": 0.15}
        v = compute_verdict(base, cand, cum_threshold=0.0001)
        assert v["verdict"] == "PASS"

    def test_exact_boundary_pass(self):
        base = {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15}
        cand = {"cum_hedged": 0.1021, "mean_hedged": 0.00460, "mean_turnover": 0.15240}
        v = compute_verdict(base, cand)
        assert v["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# 2. classify_calendar_edits
# ---------------------------------------------------------------------------


class TestClassifyCalendarEdits:
    def test_past_dated_removal_is_hygiene(self):
        baseline = [_cal_entry(ticker="OLD", pdufa_date="2025-01-01")]
        candidate = []
        result = classify_calendar_edits(baseline, candidate, as_of_date="2026-03-10")
        assert result["edit_class"] == "HYGIENE_ONLY"
        assert result["n_removed"] == 1
        assert result["changed_tickers"][0]["is_past_dated"] is True

    def test_exact_dedup_is_hygiene(self):
        entry = _cal_entry(ticker="DUP")
        baseline = [entry, entry]
        candidate = [entry]
        result = classify_calendar_edits(baseline, candidate)
        assert result["edit_class"] == "HYGIENE_ONLY"
        assert result["n_deduped"] >= 1

    def test_metadata_disclosed_at_fix_is_hygiene(self):
        base_entry = _cal_entry(ticker="FIX", disclosed="")
        cand_entry = _cal_entry(ticker="FIX", disclosed="2026-01-15")
        result = classify_calendar_edits([base_entry], [cand_entry])
        assert result["edit_class"] == "HYGIENE_ONLY"
        assert result["n_modified"] == 1
        assert result["changed_tickers"][0]["is_metadata_only"] is True

    def test_future_event_add_is_signal_bearing(self):
        baseline = [_cal_entry(ticker="A")]
        candidate = [_cal_entry(ticker="A"), _cal_entry(ticker="NEW", pdufa_date="2026-12-01")]
        result = classify_calendar_edits(baseline, candidate, as_of_date="2026-03-10")
        assert result["edit_class"] == "SIGNAL_BEARING"
        assert result["n_added"] == 1

    def test_future_event_removal_is_signal_bearing(self):
        baseline = [_cal_entry(ticker="A"), _cal_entry(ticker="GONE", pdufa_date="2026-12-01")]
        candidate = [_cal_entry(ticker="A")]
        result = classify_calendar_edits(baseline, candidate, as_of_date="2026-03-10")
        assert result["edit_class"] == "SIGNAL_BEARING"
        assert result["n_removed"] == 1

    def test_mixed_batch(self):
        """Past-dated removal + future event add = MIXED."""
        baseline = [_cal_entry(ticker="OLD", pdufa_date="2025-01-01")]
        candidate = [_cal_entry(ticker="NEW", pdufa_date="2026-12-01")]
        result = classify_calendar_edits(baseline, candidate, as_of_date="2026-03-10")
        assert result["edit_class"] == "MIXED"

    def test_confidence_change_is_signal_bearing(self):
        base = _cal_entry(ticker="A", confidence="HIGH")
        cand = _cal_entry(ticker="A", confidence="LOW")
        result = classify_calendar_edits([base], [cand])
        assert result["edit_class"] == "SIGNAL_BEARING"

    def test_pdufa_date_change_is_signal_bearing(self):
        base = _cal_entry(ticker="A", pdufa_date="2026-06-01")
        cand = _cal_entry(ticker="A", pdufa_date="2026-09-01")
        # Different key → shows as remove + add
        result = classify_calendar_edits([base], [cand], as_of_date="2026-03-10")
        assert result["edit_class"] == "SIGNAL_BEARING"

    def test_no_changes_is_hygiene(self):
        entries = [_cal_entry()]
        result = classify_calendar_edits(entries, entries)
        assert result["edit_class"] == "HYGIENE_ONLY"
        assert result["n_added"] == 0
        assert result["n_removed"] == 0

    def test_notes_change_is_hygiene(self):
        base = _cal_entry(notes="old note")
        cand = _cal_entry(notes="updated note")
        result = classify_calendar_edits([base], [cand])
        assert result["edit_class"] == "HYGIENE_ONLY"
        assert result["changed_tickers"][0]["is_metadata_only"] is True


# ---------------------------------------------------------------------------
# 3. apply_hygiene_override
# ---------------------------------------------------------------------------


class TestApplyHygieneOverride:
    def test_warn_hygiene_only_overrides(self):
        verdict = {
            "verdict": "WARN",
            "cum_hedged_pass": False,
            "mean_hedged_pass": True,
            "turnover_pass": True,
        }
        result = apply_hygiene_override(verdict, "HYGIENE_ONLY")
        assert result["final_verdict"] == "HYGIENE_OVERRIDE"
        assert result["override_applied"] is True

    def test_signal_bearing_warn_stays_warn(self):
        verdict = {
            "verdict": "WARN",
            "cum_hedged_pass": False,
            "mean_hedged_pass": True,
            "turnover_pass": True,
        }
        result = apply_hygiene_override(verdict, "SIGNAL_BEARING")
        assert result["final_verdict"] == "WARN"
        assert result["override_applied"] is False

    def test_mixed_warn_stays_warn(self):
        verdict = {
            "verdict": "WARN",
            "cum_hedged_pass": False,
            "mean_hedged_pass": True,
            "turnover_pass": True,
        }
        result = apply_hygiene_override(verdict, "MIXED")
        assert result["final_verdict"] == "WARN"
        assert result["override_applied"] is False

    def test_fail_hygiene_only_cum_only_overrides(self):
        """FAIL where only cumulative fails + HYGIENE_ONLY → override."""
        verdict = {
            "verdict": "FAIL",
            "cum_hedged_pass": False,
            "mean_hedged_pass": True,
            "turnover_pass": True,
        }
        result = apply_hygiene_override(verdict, "HYGIENE_ONLY")
        assert result["final_verdict"] == "HYGIENE_OVERRIDE"
        assert result["override_applied"] is True

    def test_fail_guardrail_hygiene_stays_fail(self):
        """FAIL where guardrail fails → no override even for HYGIENE_ONLY."""
        verdict = {
            "verdict": "FAIL",
            "cum_hedged_pass": False,
            "mean_hedged_pass": False,
            "turnover_pass": True,
        }
        result = apply_hygiene_override(verdict, "HYGIENE_ONLY")
        assert result["final_verdict"] == "FAIL"
        assert result["override_applied"] is False

    def test_fail_turnover_hygiene_stays_fail(self):
        """FAIL where turnover fails → no override even for HYGIENE_ONLY."""
        verdict = {
            "verdict": "FAIL",
            "cum_hedged_pass": True,
            "mean_hedged_pass": True,
            "turnover_pass": False,
        }
        result = apply_hygiene_override(verdict, "HYGIENE_ONLY")
        assert result["final_verdict"] == "FAIL"
        assert result["override_applied"] is False

    def test_pass_stays_pass(self):
        verdict = {
            "verdict": "PASS",
            "cum_hedged_pass": True,
            "mean_hedged_pass": True,
            "turnover_pass": True,
        }
        result = apply_hygiene_override(verdict, "HYGIENE_ONLY")
        assert result["final_verdict"] == "PASS"
        assert result["override_applied"] is False


# ---------------------------------------------------------------------------
# 4. build_diagnostic_block
# ---------------------------------------------------------------------------


class TestBuildDiagnosticBlock:
    def test_contains_required_keys(self):
        edit_info = {
            "edit_class": "HYGIENE_ONLY",
            "n_added": 0,
            "n_removed": 1,
            "n_modified": 0,
            "n_deduped": 0,
            "changed_tickers": [
                {
                    "ticker": "OLD",
                    "pdufa_date": "2025-01-01",
                    "edit_type": "REMOVED",
                    "is_past_dated": True,
                    "is_metadata_only": False,
                    "reason": "past-dated removal",
                }
            ],
        }
        base_agg = {"cum_hedged": 0.10, "mean_hedged": 0.005}
        cand_agg = {"cum_hedged": 0.0990, "mean_hedged": 0.005}
        diag = build_diagnostic_block(edit_info, [], [], base_agg, cand_agg)
        assert diag["edit_classification"] == "HYGIENE_ONLY"
        assert "diff_summary" in diag
        assert "changed_tickers" in diag
        assert "bucket_attribution" in diag
        assert "top_contributing_periods" in diag
        assert "interpretation" in diag

    def test_interpretation_for_stale_removal(self):
        edit_info = {
            "edit_class": "HYGIENE_ONLY",
            "n_added": 0,
            "n_removed": 1,
            "n_modified": 0,
            "n_deduped": 0,
            "changed_tickers": [
                {
                    "ticker": "OLD",
                    "edit_type": "REMOVED",
                    "is_past_dated": True,
                    "is_metadata_only": False,
                    "reason": "past-dated removal",
                }
            ],
        }
        base_agg = {"cum_hedged": 0.10, "mean_hedged": 0.005}
        cand_agg = {"cum_hedged": 0.0999, "mean_hedged": 0.005}
        diag = build_diagnostic_block(edit_info, [], [], base_agg, cand_agg)
        assert "stale inventory" in diag["interpretation"]

    def test_top_periods_sorted_by_abs_delta(self):
        edit_info = {
            "edit_class": "SIGNAL_BEARING",
            "n_added": 1,
            "n_removed": 0,
            "n_modified": 0,
            "n_deduped": 0,
            "changed_tickers": [],
        }
        base_results = [
            {"entry_date": "2025-06-01", "exit_date": "2025-06-08", "hedged_return": 0.01},
            {"entry_date": "2025-06-08", "exit_date": "2025-06-15", "hedged_return": 0.02},
        ]
        cand_results = [
            {"entry_date": "2025-06-01", "exit_date": "2025-06-08", "hedged_return": 0.015},
            {"entry_date": "2025-06-08", "exit_date": "2025-06-15", "hedged_return": 0.01},
        ]
        base_agg = {"cum_hedged": 0.03, "mean_hedged": 0.015}
        cand_agg = {"cum_hedged": 0.025, "mean_hedged": 0.0125}
        diag = build_diagnostic_block(edit_info, base_results, cand_results, base_agg, cand_agg)
        periods = diag["top_contributing_periods"]
        assert len(periods) == 2
        # Largest abs delta first
        assert abs(periods[0]["delta"]) >= abs(periods[1]["delta"])


# ---------------------------------------------------------------------------
# 5. write_ab_receipt
# ---------------------------------------------------------------------------


class TestWriteAbReceipt:
    def _base_agg(self):
        return {
            "n_periods": 50,
            "cum_hedged": 0.10,
            "mean_hedged": 0.005,
            "mean_turnover": 0.15,
            "mean_net": 0.008,
            "cum_net": 0.40,
        }

    def _cand_agg(self):
        return {
            "n_periods": 50,
            "cum_hedged": 0.1030,
            "mean_hedged": 0.0055,
            "mean_turnover": 0.15,
            "mean_net": 0.009,
            "cum_net": 0.42,
        }

    def test_files_created(self, tmp_path):
        verdict_data = compute_verdict(self._base_agg(), self._cand_agg())
        md_path = write_ab_receipt(
            verdict_data,
            self._base_agg(),
            self._cand_agg(),
            baseline_n=16,
            candidate_n=18,
            n_periods=50,
            out_dir=tmp_path,
        )
        assert md_path.exists()
        assert (tmp_path / "AB_RECEIPT.json").exists()

    def test_md_contains_verdict(self, tmp_path):
        verdict_data = compute_verdict(self._base_agg(), self._cand_agg())
        md_path = write_ab_receipt(
            verdict_data,
            self._base_agg(),
            self._cand_agg(),
            baseline_n=16,
            candidate_n=18,
            n_periods=50,
            out_dir=tmp_path,
        )
        md = md_path.read_text()
        assert "**Verdict**: PASS" in md
        assert "Safe to promote" in md

    def test_override_receipt(self, tmp_path):
        verdict = compute_verdict(self._base_agg(), self._cand_agg())
        # Force WARN
        verdict["verdict"] = "WARN"
        verdict["cum_hedged_pass"] = False
        verdict = apply_hygiene_override(verdict, "HYGIENE_ONLY")
        assert verdict["final_verdict"] == "HYGIENE_OVERRIDE"

        md_path = write_ab_receipt(
            verdict,
            self._base_agg(),
            self._cand_agg(),
            baseline_n=16,
            candidate_n=15,
            n_periods=50,
            out_dir=tmp_path,
        )
        md = md_path.read_text()
        assert "HYGIENE_OVERRIDE" in md
        assert "Hygiene Override" in md

    def test_diagnostic_in_receipt(self, tmp_path):
        verdict_data = compute_verdict(self._base_agg(), self._cand_agg())
        diagnostic = {
            "edit_classification": "HYGIENE_ONLY",
            "diff_summary": {"n_added": 0, "n_removed": 1, "n_modified": 0, "n_deduped": 0},
            "changed_tickers": [
                {
                    "ticker": "OLD",
                    "pdufa_date": "2025-01-01",
                    "edit_type": "REMOVED",
                    "is_past_dated": True,
                    "is_metadata_only": False,
                    "reason": "past-dated removal",
                }
            ],
            "bucket_attribution": [],
            "top_contributing_periods": [],
            "interpretation": "Removing stale inventory.",
        }
        md_path = write_ab_receipt(
            verdict_data,
            self._base_agg(),
            self._cand_agg(),
            baseline_n=16,
            candidate_n=15,
            n_periods=50,
            out_dir=tmp_path,
            diagnostic=diagnostic,
        )
        md = md_path.read_text()
        assert "## Diagnostic" in md
        assert "HYGIENE_ONLY" in md
        assert "OLD" in md

    def test_json_schema_v2(self, tmp_path):
        verdict_data = compute_verdict(self._base_agg(), self._cand_agg())
        verdict_data = apply_hygiene_override(verdict_data, "HYGIENE_ONLY")
        write_ab_receipt(
            verdict_data,
            self._base_agg(),
            self._cand_agg(),
            baseline_n=16,
            candidate_n=18,
            n_periods=50,
            out_dir=tmp_path,
        )
        data = json.loads((tmp_path / "AB_RECEIPT.json").read_text())
        assert data["schema"] == "calendar_change_ab_gate.v2"
        assert "edit_class" in data
        assert "override_applied" in data
        assert "ab_verdict" in data

    def test_json_diagnostic_block(self, tmp_path):
        verdict_data = compute_verdict(self._base_agg(), self._cand_agg())
        diagnostic = {
            "edit_classification": "SIGNAL_BEARING",
            "diff_summary": {"n_added": 1, "n_removed": 0, "n_modified": 0, "n_deduped": 0},
            "changed_tickers": [],
            "bucket_attribution": [],
            "top_contributing_periods": [],
            "interpretation": "Signal change.",
        }
        write_ab_receipt(
            verdict_data,
            self._base_agg(),
            self._cand_agg(),
            baseline_n=16,
            candidate_n=17,
            n_periods=50,
            out_dir=tmp_path,
            diagnostic=diagnostic,
        )
        data = json.loads((tmp_path / "AB_RECEIPT.json").read_text())
        assert "diagnostic" in data
        assert data["diagnostic"]["edit_classification"] == "SIGNAL_BEARING"


# ---------------------------------------------------------------------------
# 6. Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_safe_delta(self):
        assert _safe_delta(0.5, 0.3) == pytest.approx(0.2)
        assert _safe_delta(None, 0.3) is None
        assert _safe_delta(0.5, None) is None

    def test_fmt_pct(self):
        assert _fmt_pct(0.1234) == "12.34%"
        assert _fmt_pct(None) == "—"

    def test_fmt_pp(self):
        assert _fmt_pp(0.0020) == "+0.20pp"
        assert _fmt_pp(-0.0010) == "-0.10pp"
        assert _fmt_pp(None) == "—"


# ---------------------------------------------------------------------------
# 7. Exit codes
# ---------------------------------------------------------------------------


class TestExitCodes:
    def test_pass_exit_code(self):
        v = compute_verdict(
            {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15},
            {"cum_hedged": 0.1030, "mean_hedged": 0.0055, "mean_turnover": 0.15},
        )
        assert v["verdict"] == "PASS"

    def test_fail_exit_code(self):
        v = compute_verdict(
            {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15},
            {"cum_hedged": 0.11, "mean_hedged": 0.0040, "mean_turnover": 0.15},
        )
        assert v["verdict"] == "FAIL"

    def test_warn_exit_code(self):
        v = compute_verdict(
            {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15},
            {"cum_hedged": 0.1010, "mean_hedged": 0.005, "mean_turnover": 0.15},
        )
        assert v["verdict"] == "WARN"

    def test_hygiene_override_exit_code(self):
        """HYGIENE_OVERRIDE should map to exit 0 (same as PASS)."""
        gate_path = PROJECT_ROOT / "scripts" / "research" / "gate_calendar_change_ab.py"
        source = gate_path.read_text()
        assert '"PASS", "HYGIENE_OVERRIDE"' in source or "'PASS', 'HYGIENE_OVERRIDE'" in source
        assert "sys.exit(0)" in source
        assert "sys.exit(1)" in source
        assert "sys.exit(2)" in source
