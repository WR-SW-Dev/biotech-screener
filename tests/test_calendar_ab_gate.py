"""Tests for the calendar-change A/B gate.

Covers:
  1. compute_verdict — PASS, FAIL, WARN scenarios
  2. write_ab_receipt — output files + content checks
  3. _safe_delta / formatting helpers
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research.gate_calendar_change_ab import _fmt_pct, _fmt_pp, _safe_delta, compute_verdict, write_ab_receipt

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
        assert v["cum_hedged_pass"] is False
        assert v["mean_hedged_pass"] is True
        assert v["turnover_pass"] is True

    def test_fail_guardrail(self):
        """Mean hedged delta below -0.05pp → FAIL."""
        base = {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15}
        cand = {"cum_hedged": 0.11, "mean_hedged": 0.0040, "mean_turnover": 0.15}
        v = compute_verdict(base, cand)
        assert v["verdict"] == "FAIL"
        assert v["mean_hedged_pass"] is False

    def test_fail_turnover(self):
        """Turnover increase above +0.25pp → FAIL."""
        base = {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15}
        cand = {"cum_hedged": 0.11, "mean_hedged": 0.005, "mean_turnover": 0.1550}
        v = compute_verdict(base, cand)
        assert v["verdict"] == "FAIL"
        assert v["turnover_pass"] is False

    def test_none_values_fail(self):
        """None aggregates → all bars fail."""
        base = {"cum_hedged": None, "mean_hedged": None, "mean_turnover": None}
        cand = {"cum_hedged": None, "mean_hedged": None, "mean_turnover": None}
        v = compute_verdict(base, cand)
        assert v["verdict"] == "FAIL"

    def test_custom_thresholds(self):
        """Custom thresholds allow looser bars."""
        base = {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15}
        cand = {"cum_hedged": 0.1005, "mean_hedged": 0.005, "mean_turnover": 0.15}
        v = compute_verdict(
            base,
            cand,
            cum_threshold=0.0001,  # +0.01pp
        )
        assert v["verdict"] == "PASS"

    def test_exact_boundary_pass(self):
        """Just above threshold → PASS."""
        base = {"cum_hedged": 0.10, "mean_hedged": 0.005, "mean_turnover": 0.15}
        # cum_delta = +0.21pp, mean_delta = -0.04pp, turnover_delta = +0.24pp
        cand = {"cum_hedged": 0.1021, "mean_hedged": 0.00460, "mean_turnover": 0.15240}
        v = compute_verdict(base, cand)
        assert v["cum_hedged_pass"] is True
        assert v["mean_hedged_pass"] is True
        assert v["turnover_pass"] is True
        assert v["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# 2. write_ab_receipt
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
        assert "## Pass Bars" in md
        assert "## Returns" in md
        assert "Safe to promote" in md

    def test_fail_receipt_message(self, tmp_path):
        base = self._base_agg()
        cand = self._cand_agg()
        cand["mean_hedged"] = 0.0040  # below guardrail
        verdict_data = compute_verdict(base, cand)
        md_path = write_ab_receipt(
            verdict_data,
            base,
            cand,
            baseline_n=16,
            candidate_n=18,
            n_periods=50,
            out_dir=tmp_path,
        )
        md = md_path.read_text()
        assert "FAIL" in md
        assert "Do not promote" in md

    def test_json_schema(self, tmp_path):
        verdict_data = compute_verdict(self._base_agg(), self._cand_agg())
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
        assert data["schema"] == "calendar_change_ab_gate.v1"
        assert data["verdict"] == "PASS"
        assert "bars" in data
        assert data["bars"]["cum_hedged_pass"] is True


# ---------------------------------------------------------------------------
# 3. Helpers
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
