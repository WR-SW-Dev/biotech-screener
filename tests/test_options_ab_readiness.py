"""Tests for tools/options_ab_readiness_monitor.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from options_ab_readiness_monitor import compute_readiness, scan_all_snapshots, scan_snapshot


def _make_snapshot(
    tmp_path: Path,
    date: str,
    rows: list[dict],
    *,
    meta_ab_ready: bool | None = None,
) -> Path:
    snap_dir = tmp_path / date
    snap_dir.mkdir(parents=True, exist_ok=True)
    if rows:
        cols = list(rows[0].keys())
        with open(snap_dir / "rankings.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    if meta_ab_ready is not None:
        meta = {"options_diagnostics": {"ab_ready": meta_ab_ready}}
        (snap_dir / "metadata.json").write_text(json.dumps(meta))
    return snap_dir


def _row(
    ticker: str,
    has_data: str = "1",
    oqc: str = "0.5",
    has_reg_180d: str = "0",
    reg_days: str = "",
) -> dict:
    return {
        "ticker": ticker,
        "opt_has_data": has_data,
        "options_quality_composite": oqc,
        "has_regulatory_upcoming_180d": has_reg_180d,
        "regulatory_days": reg_days,
    }


class TestScanSnapshot:
    def test_populated_snapshot(self, tmp_path):
        rows = [
            _row("A", oqc="0.6", has_reg_180d="1", reg_days="120"),
            _row("B", oqc="0.4"),
            _row("C", has_data="0", oqc=""),
        ]
        snap = _make_snapshot(tmp_path, "2026-03-13", rows, meta_ab_ready=True)
        result = scan_snapshot(snap)
        assert result is not None
        assert result["date"] == "2026-03-13"
        assert result["n_total"] == 3
        assert result["n_has_data"] == 2
        assert result["n_oqc_nonzero"] == 2
        assert result["n_step10_eligible_oqc"] == 1
        assert result["ab_ready"] is True
        assert result["meta_ab_ready"] is True

    def test_reg_outside_91_180_window(self, tmp_path):
        """regulatory_days <= 90 should NOT count as step10 eligible."""
        rows = [
            _row("A", oqc="0.6", has_reg_180d="1", reg_days="60"),
        ]
        snap = _make_snapshot(tmp_path, "2026-03-13", rows)
        result = scan_snapshot(snap)
        assert result["n_step10_eligible_oqc"] == 0

    def test_reg_no_oqc(self, tmp_path):
        """has reg 91-180d but no OQC should NOT count."""
        rows = [
            _row("A", oqc="", has_reg_180d="1", reg_days="120"),
        ]
        snap = _make_snapshot(tmp_path, "2026-03-13", rows)
        result = scan_snapshot(snap)
        assert result["n_step10_eligible_oqc"] == 0

    def test_empty_snapshot(self, tmp_path):
        snap = _make_snapshot(tmp_path, "2026-03-10", [_row("A", has_data="0", oqc="")])
        result = scan_snapshot(snap)
        assert result["ab_ready"] is False
        assert result["n_oqc_nonzero"] == 0

    def test_no_rankings(self, tmp_path):
        snap_dir = tmp_path / "2026-03-09"
        snap_dir.mkdir()
        assert scan_snapshot(snap_dir) is None


class TestScanAllSnapshots:
    def test_skips_non_date_dirs(self, tmp_path):
        _make_snapshot(tmp_path, "2026-03-13", [_row("A")])
        _make_snapshot(tmp_path, "_archive_weekends", [_row("B")])
        (tmp_path / "2026-03-12__pre_backup").mkdir()
        results = scan_all_snapshots(tmp_path)
        assert len(results) == 1
        assert results[0]["date"] == "2026-03-13"

    def test_sorted_output(self, tmp_path):
        _make_snapshot(tmp_path, "2026-03-15", [_row("A")])
        _make_snapshot(tmp_path, "2026-03-13", [_row("B")])
        _make_snapshot(tmp_path, "2026-03-14", [_row("C")])
        results = scan_all_snapshots(tmp_path)
        assert [r["date"] for r in results] == ["2026-03-13", "2026-03-14", "2026-03-15"]


class TestComputeReadiness:
    def test_accumulating(self):
        snapshots = [
            {
                "date": f"2026-03-{10+i:02d}",
                "ab_ready": True,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 10,
                "n_oqc_nonzero": 5,
                "n_total": 20,
            }
            for i in range(3)
        ]
        result = compute_readiness(snapshots, min_weeks=10)
        assert result["trigger"] == "ACCUMULATING"
        assert "7 more" in result["trigger_detail"]

    def test_blocked_no_step10(self):
        snapshots = [
            {
                "date": f"2026-03-{i:02d}",
                "ab_ready": True,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 10,
                "n_oqc_nonzero": 5,
                "n_total": 20,
            }
            for i in range(1, 12)
        ]
        result = compute_readiness(snapshots, min_weeks=10)
        assert result["trigger"] == "BLOCKED"
        assert "Step-10" in result["trigger_detail"]

    def test_ready(self):
        snapshots = [
            {
                "date": f"2026-03-{i:02d}",
                "ab_ready": True,
                "n_step10_eligible_oqc": 2,
                "n_has_data": 10,
                "n_oqc_nonzero": 5,
                "n_total": 20,
            }
            for i in range(1, 12)
        ]
        result = compute_readiness(snapshots, min_weeks=10)
        assert result["trigger"] == "READY"
        assert "eval_b91_options_quality_weekly_ab.py" in result["trigger_detail"]

    def test_gap_detection(self):
        snapshots = [
            {
                "date": "2026-03-01",
                "ab_ready": True,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 10,
                "n_oqc_nonzero": 5,
                "n_total": 20,
            },
            {
                "date": "2026-03-02",
                "ab_ready": False,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 0,
                "n_oqc_nonzero": 0,
                "n_total": 20,
            },
            {
                "date": "2026-03-03",
                "ab_ready": False,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 0,
                "n_oqc_nonzero": 0,
                "n_total": 20,
            },
            {
                "date": "2026-03-04",
                "ab_ready": True,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 10,
                "n_oqc_nonzero": 5,
                "n_total": 20,
            },
        ]
        result = compute_readiness(snapshots, min_weeks=10)
        assert len(result["gaps"]) == 1
        assert result["gaps"][0]["start"] == "2026-03-02"
        assert result["gaps"][0]["end"] == "2026-03-04"

    def test_ongoing_gap(self):
        snapshots = [
            {
                "date": "2026-03-01",
                "ab_ready": True,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 10,
                "n_oqc_nonzero": 5,
                "n_total": 20,
            },
            {
                "date": "2026-03-02",
                "ab_ready": False,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 0,
                "n_oqc_nonzero": 0,
                "n_total": 20,
            },
        ]
        result = compute_readiness(snapshots, min_weeks=10)
        assert len(result["gaps"]) == 1
        assert result["gaps"][0]["end"] == "ongoing"

    def test_no_gaps_before_first_ready(self):
        snapshots = [
            {
                "date": "2026-03-01",
                "ab_ready": False,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 0,
                "n_oqc_nonzero": 0,
                "n_total": 20,
            },
            {
                "date": "2026-03-02",
                "ab_ready": False,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 0,
                "n_oqc_nonzero": 0,
                "n_total": 20,
            },
            {
                "date": "2026-03-03",
                "ab_ready": True,
                "n_step10_eligible_oqc": 0,
                "n_has_data": 10,
                "n_oqc_nonzero": 5,
                "n_total": 20,
            },
        ]
        result = compute_readiness(snapshots, min_weeks=10)
        assert len(result["gaps"]) == 0

    def test_empty_snapshots(self):
        result = compute_readiness([], min_weeks=10)
        assert result["trigger"] == "ACCUMULATING"
        assert result["totals"]["total_snapshots"] == 0

    def test_schema_version(self):
        result = compute_readiness([], min_weeks=10)
        assert result["schema"] == "options_ab_readiness.v2"
