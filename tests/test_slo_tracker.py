#!/usr/bin/env python3
"""Tests for tools/slo_tracker.py — SLO / error-budget tracker."""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from tools.slo_tracker import (
    compute_slo_report,
    format_report,
    load_ledger,
)


def _make_row(as_of_date: str, overall_status: str, gates: dict = None):
    return {
        "as_of_date": as_of_date,
        "generated_at": f"{as_of_date}T12:00:00Z",
        "overall_status": overall_status,
        "gates": gates or {},
        "n_pass": 1 if overall_status == "PASS" else 0,
        "n_warn": 1 if overall_status == "WARN" else 0,
        "n_fail": 1 if overall_status == "FAIL" else 0,
        "ruleset_hash": "abc123",
        "git_sha": "def456",
    }


class TestLoadLedger:
    def test_empty_file(self, tmp_path):
        p = tmp_path / "ledger.jsonl"
        p.write_text("")
        assert load_ledger(p) == []

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        assert load_ledger(p) == []

    def test_loads_rows(self, tmp_path):
        p = tmp_path / "ledger.jsonl"
        rows = [_make_row("2026-03-01", "PASS"), _make_row("2026-03-02", "FAIL")]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        result = load_ledger(p)
        assert len(result) == 2
        assert result[0]["overall_status"] == "PASS"


class TestComputeSloReport:
    def test_empty_rows(self):
        report = compute_slo_report([], as_of=date(2026, 3, 5))
        assert report["total_runs"] == 0
        assert report["pass_rate_pct"] is None
        assert report["slo_met"] is None

    def test_all_pass(self):
        rows = [_make_row(f"2026-03-{d:02d}", "PASS") for d in range(1, 6)]
        report = compute_slo_report(rows, window_days=30, as_of=date(2026, 3, 5))
        assert report["total_runs"] == 5
        assert report["pass_rate_pct"] == 100.0
        assert report["slo_met"] is True
        assert report["fail_runs"] == 0
        assert report["budget_consumed"] == 0

    def test_all_fail(self):
        rows = [_make_row(f"2026-03-{d:02d}", "FAIL") for d in range(1, 6)]
        report = compute_slo_report(rows, window_days=30, as_of=date(2026, 3, 5))
        assert report["pass_rate_pct"] == 0.0
        assert report["slo_met"] is False
        assert report["fail_runs"] == 5

    def test_warn_counts_as_pass(self):
        rows = [_make_row("2026-03-01", "WARN")]
        report = compute_slo_report(rows, window_days=30, as_of=date(2026, 3, 5))
        assert report["pass_rate_pct"] == 100.0
        assert report["warn_runs"] == 1
        assert report["slo_met"] is True

    def test_budget_computation(self):
        # 20 runs, 95% target → floor(20 * 0.05) = 1 allowed fail
        rows = [_make_row(f"2026-02-{d + 10:02d}", "PASS") for d in range(19)]
        rows.append(_make_row("2026-03-01", "FAIL"))
        report = compute_slo_report(
            rows, window_days=30, slo_target_pct=95.0, as_of=date(2026, 3, 5),
        )
        assert report["total_runs"] == 20
        assert report["budget_total"] == 1  # floor(20 * 0.05)
        assert report["budget_consumed"] == 1
        assert report["budget_remaining"] == 0
        assert report["slo_met"] is True  # 95% exactly

    def test_slo_breached(self):
        # 20 runs, 2 fails → 90% < 95% target
        rows = [_make_row(f"2026-02-{d + 10:02d}", "PASS") for d in range(18)]
        rows.append(_make_row("2026-03-01", "FAIL"))
        rows.append(_make_row("2026-03-02", "FAIL"))
        report = compute_slo_report(
            rows, window_days=30, slo_target_pct=95.0, as_of=date(2026, 3, 5),
        )
        assert report["slo_met"] is False
        assert report["pass_rate_pct"] == 90.0

    def test_window_filter(self):
        # Row outside window should be excluded
        rows = [
            _make_row("2026-01-01", "FAIL"),  # outside 30-day window
            _make_row("2026-03-05", "PASS"),
        ]
        report = compute_slo_report(rows, window_days=30, as_of=date(2026, 3, 5))
        assert report["total_runs"] == 1
        assert report["fail_runs"] == 0

    def test_dedup_by_date(self):
        # Two entries for same date → keep latest
        rows = [
            _make_row("2026-03-01", "FAIL"),
            _make_row("2026-03-01", "PASS"),  # retry succeeded
        ]
        report = compute_slo_report(rows, window_days=30, as_of=date(2026, 3, 5))
        assert report["total_runs"] == 1
        assert report["fail_runs"] == 0  # latest was PASS

    def test_gate_failure_counts(self):
        rows = [
            _make_row("2026-03-01", "FAIL", {"xbi_staleness": "FAIL", "audit": "PASS"}),
            _make_row("2026-03-02", "FAIL", {"xbi_staleness": "FAIL", "ctgov": "FAIL"}),
        ]
        report = compute_slo_report(rows, window_days=30, as_of=date(2026, 3, 5))
        assert report["gate_failure_counts"]["xbi_staleness"] == 2
        assert report["gate_failure_counts"]["ctgov"] == 1

    def test_recent_failures_capped(self):
        rows = [_make_row(f"2026-03-{d:02d}", "FAIL") for d in range(1, 8)]
        report = compute_slo_report(rows, window_days=30, as_of=date(2026, 3, 7))
        assert len(report["recent_failures"]) == 5  # capped at 5


class TestFormatReport:
    def test_empty_report(self):
        report = compute_slo_report([], as_of=date(2026, 3, 5))
        text = format_report(report)
        assert "No runs in window" in text

    def test_met_report(self):
        rows = [_make_row("2026-03-01", "PASS")]
        report = compute_slo_report(rows, window_days=30, as_of=date(2026, 3, 5))
        text = format_report(report)
        assert "MET" in text
        assert "100.0%" in text

    def test_breached_report(self):
        rows = [_make_row("2026-03-01", "FAIL")]
        report = compute_slo_report(rows, window_days=30, as_of=date(2026, 3, 5))
        text = format_report(report)
        assert "BREACHED" in text
