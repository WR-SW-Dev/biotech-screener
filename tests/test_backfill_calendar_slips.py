"""Tests for calendar slip backfill + reliability bootstrap."""

import csv
import json
from pathlib import Path

from scripts.backfill_calendar_slips import (
    backfill_slips,
    build_validation_report,
    compute_selection_diff,
    discover_snapshot_dates,
    run_backfill,
)
from tools.track_calendar_slips import SLIPS_COLUMNS


def _write_rankings(snap_dir: Path, rows):
    """Write a minimal rankings.csv for testing."""
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / "rankings.csv"
    fieldnames = [
        "ticker",
        "eligible",
        "catalyst_days",
        "catalyst_mode",
        "catalyst_source",
        "catalyst_event_type",
        "catalyst_reason_detail",
        "de_catalyst_days",
        "de_catalyst_mode",
        "confidence_overall",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            full = {k: "" for k in fieldnames}
            full.update(row)
            if "eligible" not in row:
                full["eligible"] = "1"
            w.writerow(full)


# ---------------------------------------------------------------------------
# 1. Snapshot discovery
# ---------------------------------------------------------------------------


class TestDiscoverSnapshotDates:
    def test_finds_dates_in_range(self, tmp_path):
        for d in ["2025-01-01", "2025-01-08", "2025-01-15", "2025-02-01"]:
            _write_rankings(tmp_path / d, [{"ticker": "X", "catalyst_days": "90"}])

        dates = discover_snapshot_dates(tmp_path, "2025-01-05", "2025-01-20")
        assert dates == ["2025-01-08", "2025-01-15"]

    def test_deterministic_ordering(self, tmp_path):
        for d in ["2025-03-01", "2025-01-01", "2025-02-01"]:
            _write_rankings(tmp_path / d, [{"ticker": "X", "catalyst_days": "90"}])

        dates = discover_snapshot_dates(tmp_path)
        assert dates == ["2025-01-01", "2025-02-01", "2025-03-01"]

    def test_skips_dirs_without_rankings(self, tmp_path):
        (tmp_path / "2025-01-01").mkdir()  # no rankings.csv
        _write_rankings(tmp_path / "2025-01-08", [{"ticker": "X", "catalyst_days": "90"}])

        dates = discover_snapshot_dates(tmp_path)
        assert dates == ["2025-01-08"]

    def test_empty_root(self, tmp_path):
        assert discover_snapshot_dates(tmp_path / "nonexistent") == []


# ---------------------------------------------------------------------------
# 2. Backfill
# ---------------------------------------------------------------------------


class TestBackfillSlips:
    def _setup_snapshots(self, tmp_path):
        """Create 3 consecutive snapshots with a slip."""
        snap_root = tmp_path / "snaps"
        rows_base = [
            {
                "ticker": "ACAD",
                "catalyst_days": "90",
                "catalyst_source": "COMPANY_GUIDANCE",
                "catalyst_event_type": "PDUFA",
                "catalyst_mode": "specific_days",
            },
            {
                "ticker": "VRTX",
                "catalyst_days": "60",
                "catalyst_source": "SEC_8K_FILING",
                "catalyst_event_type": "PDUFA",
                "catalyst_mode": "specific_days",
            },
        ]
        _write_rankings(snap_root / "2025-01-01", rows_base)

        rows_week2 = [
            {
                "ticker": "ACAD",
                "catalyst_days": "83",
                "catalyst_source": "COMPANY_GUIDANCE",
                "catalyst_event_type": "PDUFA",
                "catalyst_mode": "specific_days",
            },
            {
                "ticker": "VRTX",
                "catalyst_days": "73",
                "catalyst_source": "SEC_8K_FILING",
                "catalyst_event_type": "PDUFA",
                "catalyst_mode": "specific_days",
            },
        ]
        _write_rankings(snap_root / "2025-01-08", rows_week2)

        rows_week3 = [
            {
                "ticker": "ACAD",
                "catalyst_days": "76",
                "catalyst_source": "COMPANY_GUIDANCE",
                "catalyst_event_type": "PDUFA",
                "catalyst_mode": "specific_days",
            },
            {
                "ticker": "VRTX",
                "catalyst_days": "86",
                "catalyst_source": "SEC_8K_FILING",
                "catalyst_event_type": "PDUFA",
                "catalyst_mode": "specific_days",
            },
        ]
        _write_rankings(snap_root / "2025-01-15", rows_week3)

        return snap_root

    def test_backfill_writes_artifacts(self, tmp_path):
        snap_root = self._setup_snapshots(tmp_path)
        out_root = tmp_path / "artifacts"
        dates = ["2025-01-01", "2025-01-08", "2025-01-15"]

        result = backfill_slips(snap_root, out_root, dates)
        # First date has no prior, so skip. 2 should be written.
        assert result["written"] == 2
        assert (out_root / "2025-01-08" / "slips.csv").is_file()
        assert (out_root / "2025-01-15" / "slips.csv").is_file()

    def test_schema_compatibility(self, tmp_path):
        """Backfilled slips.csv has same columns as live tracker."""
        snap_root = self._setup_snapshots(tmp_path)
        out_root = tmp_path / "artifacts"
        dates = ["2025-01-01", "2025-01-08"]

        backfill_slips(snap_root, out_root, dates)
        csv_path = out_root / "2025-01-08" / "slips.csv"

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == SLIPS_COLUMNS

    def test_resumable_skips_existing(self, tmp_path):
        snap_root = self._setup_snapshots(tmp_path)
        out_root = tmp_path / "artifacts"
        dates = ["2025-01-01", "2025-01-08", "2025-01-15"]

        # First run
        r1 = backfill_slips(snap_root, out_root, dates)
        assert r1["written"] == 2

        # Second run: should skip
        r2 = backfill_slips(snap_root, out_root, dates)
        assert r2["written"] == 0
        assert r2["skipped"] == 2

    def test_force_overwrites(self, tmp_path):
        snap_root = self._setup_snapshots(tmp_path)
        out_root = tmp_path / "artifacts"
        dates = ["2025-01-01", "2025-01-08"]

        backfill_slips(snap_root, out_root, dates)
        r2 = backfill_slips(snap_root, out_root, dates, force=True)
        assert r2["written"] == 1  # 2025-01-08 only (01-01 has no prior)
        assert r2["skipped"] == 0

    def test_summary_json_written(self, tmp_path):
        snap_root = self._setup_snapshots(tmp_path)
        out_root = tmp_path / "artifacts"
        dates = ["2025-01-01", "2025-01-08"]

        backfill_slips(snap_root, out_root, dates)
        json_path = out_root / "2025-01-08" / "slip_summary.json"
        assert json_path.is_file()
        data = json.loads(json_path.read_text())
        assert data["schema"] == "calendar_slips.v1"
        assert "total_tracked" in data


# ---------------------------------------------------------------------------
# 3. Validation report
# ---------------------------------------------------------------------------


class TestBuildValidationReport:
    def test_report_contains_required_sections(self):
        backfill_result = {"total_dates": 10, "written": 8, "skipped": 1, "errors": 1}
        buckets = [
            {
                "source": "A",
                "confidence": "HIGH",
                "family": "REGULATORY",
                "sample_count": 10,
                "median_abs_slip_days": 3.0,
                "large_slip_rate": 0.05,
                "action": "ALLOW",
                "reason": "clean",
            },
            {
                "source": "B",
                "confidence": "LOW",
                "family": "CLINICAL",
                "sample_count": 10,
                "median_abs_slip_days": 25.0,
                "large_slip_rate": 0.50,
                "action": "SUPPRESS",
                "reason": "bad",
            },
        ]

        report = build_validation_report(
            backfill_result,
            buckets,
            [],
            n_weeks=10,
            n_slip_rows=100,
            as_of_date="2026-03-10",
        )

        assert "Backfill Summary" in report
        assert "Action Distribution" in report
        assert "ALLOW: 1" in report
        assert "SUPPRESS: 1" in report
        assert "All Buckets" in report
        assert "Worst Buckets" in report
        assert "Selection Diff" in report

    def test_report_with_selection_changes(self):
        changes = [
            {
                "ticker": "X",
                "source": "BAD",
                "base_rank": 1,
                "aware_rank": 3,
                "rank_delta": 2,
                "reliability_action": "DEMOTE",
                "reliability_reason": "noisy",
            }
        ]
        report = build_validation_report(
            {"total_dates": 1, "written": 1, "skipped": 0, "errors": 0},
            [],
            changes,
        )
        assert "1 entries changed ranking" in report
        assert "DEMOTE" in report


# ---------------------------------------------------------------------------
# 4. Selection diff
# ---------------------------------------------------------------------------


class TestComputeSelectionDiff:
    def test_no_diff_with_empty_reliability(self, tmp_path):
        cal = [
            {
                "ticker": "A",
                "pdufa_date": "2026-06-01",
                "source": "COMPANY_GUIDANCE",
                "confidence": "HIGH",
                "event_type": "PDUFA",
                "as_of_disclosed_at": "2026-01-01",
            }
        ]
        cal_path = tmp_path / "cal.json"
        cal_path.write_text(json.dumps(cal))

        diff = compute_selection_diff([], cal_path, "2026-03-10")
        assert diff == []

    def test_diff_with_reliability_penalty(self, tmp_path):
        cal = [
            {
                "ticker": "A",
                "pdufa_date": "2026-06-01",
                "source": "NOISY",
                "confidence": "HIGH",
                "event_type": "PDUFA",
                "as_of_disclosed_at": "2026-01-01",
            },
            {
                "ticker": "B",
                "pdufa_date": "2026-06-01",
                "source": "CLEAN",
                "confidence": "HIGH",
                "event_type": "PDUFA",
                "as_of_disclosed_at": "2026-01-01",
            },
        ]
        cal_path = tmp_path / "cal.json"
        cal_path.write_text(json.dumps(cal))

        reliability = [
            {"source": "NOISY", "confidence": "HIGH", "family": "REGULATORY", "action": "SUPPRESS", "reason": "bad"},
            {"source": "CLEAN", "confidence": "HIGH", "family": "REGULATORY", "action": "ALLOW", "reason": "ok"},
        ]

        diff = compute_selection_diff(reliability, cal_path, "2026-03-10")
        # Both sources have same static priority, but NOISY gets -5 penalty
        # So the ordering should change
        assert len(diff) > 0


# ---------------------------------------------------------------------------
# 5. Full pipeline integration
# ---------------------------------------------------------------------------


class TestRunBackfillIntegration:
    def test_full_pipeline(self, tmp_path):
        snap_root = tmp_path / "snaps"
        slips_root = tmp_path / "slips"
        rel_root = tmp_path / "rel"
        report_dir = tmp_path / "reports"

        # Create 3 snapshots
        rows_w1 = [
            {
                "ticker": "X",
                "catalyst_days": "90",
                "catalyst_source": "SRC_A",
                "catalyst_event_type": "PDUFA",
                "catalyst_mode": "specific_days",
            },
        ]
        rows_w2 = [
            {
                "ticker": "X",
                "catalyst_days": "83",
                "catalyst_source": "SRC_A",
                "catalyst_event_type": "PDUFA",
                "catalyst_mode": "specific_days",
            },
        ]
        rows_w3 = [
            {
                "ticker": "X",
                "catalyst_days": "76",
                "catalyst_source": "SRC_A",
                "catalyst_event_type": "PDUFA",
                "catalyst_mode": "specific_days",
            },
        ]
        _write_rankings(snap_root / "2025-01-01", rows_w1)
        _write_rankings(snap_root / "2025-01-08", rows_w2)
        _write_rankings(snap_root / "2025-01-15", rows_w3)

        result = run_backfill(
            "2025-01-01",
            "2025-01-15",
            snap_root=snap_root,
            slips_out_root=slips_root,
            reliability_out_root=rel_root,
            report_dir=report_dir,
        )

        assert result["status"] == "OK"
        assert result["n_weeks"] == 2
        assert result["n_buckets"] >= 1
        assert Path(result["paths"]["reliability_json"]).is_file()
        assert Path(result["paths"]["report"]).is_file()
