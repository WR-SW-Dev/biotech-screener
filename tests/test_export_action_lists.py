"""Tests for export_action_lists.py — bucket assignment and CSV/MD output.

Validates:
  1. _assign_bucket_from_row correctly classifies catalyst timing
  2. split_by_book separates core vs binary and sorts by rank
  3. _eligible_rows filters on eligible=1 + actionable_rank
  4. write_csv produces valid output with correct columns
  5. export_action_lists end-to-end produces three files
  6. Fallback bucket assignment for older snapshots without catalyst_bucket
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.export_action_lists import (
    OUTPUT_COLUMNS,
    _assign_bucket_from_row,
    _eligible_rows,
    _safe_float,
    export_action_lists,
    split_by_book,
    write_csv,
    write_summary_md,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ranking_row(
    ticker="TEST",
    eligible="1",
    actionable_rank="5",
    catalyst_bucket="",
    catalyst_mode="specific_days",
    catalyst_days="60",
    tier_any="A",
    target_weight_pct="2.0",
    alpha_cohort_key="",
    clinical_optionality_pct_dev="",
    mom_state="",
    tier_any_reason="",
):
    return {
        "ticker": ticker,
        "eligible": eligible,
        "actionable_rank": actionable_rank,
        "catalyst_bucket": catalyst_bucket,
        "catalyst_mode": catalyst_mode,
        "catalyst_days": catalyst_days,
        "tier_any": tier_any,
        "target_weight_pct": target_weight_pct,
        "alpha_cohort_key": alpha_cohort_key,
        "clinical_optionality_pct_dev": clinical_optionality_pct_dev,
        "mom_state": mom_state,
        "tier_any_reason": tier_any_reason,
    }


def _write_rankings_csv(snap_dir, rows):
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / "rankings.csv"
    fieldnames = list(rows[0].keys()) if rows else []
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# A) _safe_float
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_valid(self):
        assert _safe_float("3.14") == 3.14

    def test_empty(self):
        assert _safe_float("") == 0.0

    def test_none(self):
        assert _safe_float(None) == 0.0

    def test_bad_string(self):
        assert _safe_float("abc") == 0.0

    def test_custom_default(self):
        assert _safe_float("", default=999.0) == 999.0


# ---------------------------------------------------------------------------
# B) _assign_bucket_from_row
# ---------------------------------------------------------------------------


class TestAssignBucket:
    def test_uses_existing_bucket(self):
        row = _ranking_row(catalyst_bucket="build_window")
        assert _assign_bucket_from_row(row) == "build_window"

    def test_fallback_no_upcoming(self):
        row = _ranking_row(catalyst_bucket="", catalyst_mode="no_upcoming")
        assert _assign_bucket_from_row(row) == "core"

    def test_fallback_missing_mode(self):
        row = _ranking_row(catalyst_bucket="", catalyst_mode="missing")
        assert _assign_bucket_from_row(row) == "core"

    def test_fallback_0_30_days(self):
        row = _ranking_row(catalyst_bucket="", catalyst_mode="specific_days", catalyst_days="15")
        assert _assign_bucket_from_row(row) == "binary_now"

    def test_fallback_30_boundary(self):
        row = _ranking_row(catalyst_bucket="", catalyst_mode="specific_days", catalyst_days="30")
        assert _assign_bucket_from_row(row) == "binary_now"

    def test_fallback_31_90_days(self):
        row = _ranking_row(catalyst_bucket="", catalyst_mode="specific_days", catalyst_days="60")
        assert _assign_bucket_from_row(row) == "build_window"

    def test_fallback_91_180_days(self):
        row = _ranking_row(catalyst_bucket="", catalyst_mode="specific_days", catalyst_days="120")
        assert _assign_bucket_from_row(row) == "less_binary"

    def test_fallback_over_180_days(self):
        row = _ranking_row(catalyst_bucket="", catalyst_mode="specific_days", catalyst_days="200")
        assert _assign_bucket_from_row(row) == "core"

    def test_fallback_no_days_defaults_core(self):
        row = _ranking_row(catalyst_bucket="", catalyst_mode="specific_days", catalyst_days="")
        # empty days → float("inf") → core
        assert _assign_bucket_from_row(row) == "core"


# ---------------------------------------------------------------------------
# C) _eligible_rows
# ---------------------------------------------------------------------------


class TestEligibleRows:
    def test_filters_ineligible(self):
        rows = [
            _ranking_row(ticker="A", eligible="1", actionable_rank="1"),
            _ranking_row(ticker="B", eligible="0", actionable_rank=""),
            _ranking_row(ticker="C", eligible="1", actionable_rank="3"),
        ]
        result = _eligible_rows(rows)
        tickers = [r["ticker"] for r in result]
        assert tickers == ["A", "C"]

    def test_filters_no_rank(self):
        rows = [
            _ranking_row(ticker="A", eligible="1", actionable_rank=""),
        ]
        result = _eligible_rows(rows)
        assert len(result) == 0

    def test_empty_input(self):
        assert _eligible_rows([]) == []


# ---------------------------------------------------------------------------
# D) split_by_book
# ---------------------------------------------------------------------------


class TestSplitByBook:
    def test_correct_split(self):
        rows = [
            _ranking_row(ticker="BIN", eligible="1", actionable_rank="2", catalyst_bucket="binary_now"),
            _ranking_row(ticker="BUILD", eligible="1", actionable_rank="1", catalyst_bucket="build_window"),
            _ranking_row(ticker="CORE", eligible="1", actionable_rank="3", catalyst_bucket="core"),
            _ranking_row(ticker="LESS", eligible="1", actionable_rank="4", catalyst_bucket="less_binary"),
        ]
        core, binary = split_by_book(rows, "2026-03-08")
        core_tickers = [r["ticker"] for r in core]
        binary_tickers = [r["ticker"] for r in binary]
        assert "CORE" in core_tickers
        assert "LESS" in core_tickers
        assert "BIN" in binary_tickers
        assert "BUILD" in binary_tickers

    def test_sorted_by_rank(self):
        rows = [
            _ranking_row(ticker="Z", eligible="1", actionable_rank="10", catalyst_bucket="core"),
            _ranking_row(ticker="A", eligible="1", actionable_rank="1", catalyst_bucket="core"),
            _ranking_row(ticker="M", eligible="1", actionable_rank="5", catalyst_bucket="core"),
        ]
        core, binary = split_by_book(rows, "2026-03-08")
        ranks = [_safe_float(r["actionable_rank"]) for r in core]
        assert ranks == sorted(ranks)

    def test_date_prepended(self):
        rows = [
            _ranking_row(ticker="A", eligible="1", actionable_rank="1", catalyst_bucket="core"),
        ]
        core, _ = split_by_book(rows, "2026-03-08")
        assert core[0]["date"] == "2026-03-08"

    def test_ineligible_excluded(self):
        rows = [
            _ranking_row(ticker="A", eligible="0", actionable_rank="", catalyst_bucket="core"),
        ]
        core, binary = split_by_book(rows, "2026-03-08")
        assert len(core) == 0
        assert len(binary) == 0


# ---------------------------------------------------------------------------
# E) write_csv
# ---------------------------------------------------------------------------


class TestWriteCSV:
    def test_output_has_correct_columns(self, tmp_path):
        rows = [
            {"date": "2026-03-08", "ticker": "AAPL", "actionable_rank": "1"},
        ]
        path = tmp_path / "out.csv"
        write_csv(rows, path)
        with open(path) as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == OUTPUT_COLUMNS

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "deep" / "out.csv"
        write_csv([], path)
        assert path.exists()


# ---------------------------------------------------------------------------
# F) write_summary_md
# ---------------------------------------------------------------------------


class TestWriteSummaryMD:
    def test_summary_contains_both_books(self, tmp_path):
        core = [{"ticker": "C1", "actionable_rank": "1"}]
        binary = [{"ticker": "B1", "actionable_rank": "1"}]
        path = tmp_path / "summary.md"
        write_summary_md(core, binary, "2026-03-08", path)
        content = path.read_text()
        assert "Binary Book" in content
        assert "Core Book" in content
        assert "B1" in content
        assert "C1" in content

    def test_empty_books(self, tmp_path):
        path = tmp_path / "summary.md"
        write_summary_md([], [], "2026-03-08", path)
        content = path.read_text()
        assert "No names in this book" in content


# ---------------------------------------------------------------------------
# G) export_action_lists (integration)
# ---------------------------------------------------------------------------


class TestExportActionLists:
    def test_end_to_end(self, tmp_path):
        snap_dir = tmp_path / "snap"
        rows = [
            _ranking_row(ticker="BIN1", eligible="1", actionable_rank="1", catalyst_bucket="binary_now"),
            _ranking_row(ticker="CORE1", eligible="1", actionable_rank="2", catalyst_bucket="core"),
            _ranking_row(ticker="INELIG", eligible="0", actionable_rank=""),
        ]
        _write_rankings_csv(snap_dir, rows)

        out_dir = tmp_path / "output"
        core_path, binary_path, summary_path = export_action_lists(
            snap_dir, output_dir=out_dir, as_of_date="2026-03-08"
        )

        assert core_path.exists()
        assert binary_path.exists()
        assert summary_path.exists()

        # Verify core CSV
        with open(core_path) as f:
            core_rows = list(csv.DictReader(f))
        assert len(core_rows) == 1
        assert core_rows[0]["ticker"] == "CORE1"

        # Verify binary CSV
        with open(binary_path) as f:
            binary_rows = list(csv.DictReader(f))
        assert len(binary_rows) == 1
        assert binary_rows[0]["ticker"] == "BIN1"

    def test_uses_snapshot_name_as_date(self, tmp_path):
        snap_dir = tmp_path / "2026-03-08"
        _write_rankings_csv(
            snap_dir,
            [
                _ranking_row(ticker="A", eligible="1", actionable_rank="1", catalyst_bucket="core"),
            ],
        )
        out_dir = tmp_path / "output"
        core_path, _, _ = export_action_lists(snap_dir, output_dir=out_dir)
        assert "2026-03-08" in core_path.name

    def test_missing_rankings_raises(self, tmp_path):
        snap_dir = tmp_path / "empty_snap"
        snap_dir.mkdir()
        try:
            export_action_lists(snap_dir, output_dir=tmp_path / "out")
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass
