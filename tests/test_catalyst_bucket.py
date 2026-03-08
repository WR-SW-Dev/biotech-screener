"""Tests for catalyst_bucket column + far-out relabel + action list exporter."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from decision_engine import DecisionRuleset, _compute_overlays, assign_catalyst_bucket

# ---------------------------------------------------------------------------
# assign_catalyst_bucket
# ---------------------------------------------------------------------------


class TestAssignCatalystBucket:

    def test_binary_now(self):
        assert assign_catalyst_bucket(10, "specific_days") == "binary_now"

    def test_binary_now_zero(self):
        assert assign_catalyst_bucket(0, "blended_window") == "binary_now"

    def test_build_window(self):
        assert assign_catalyst_bucket(60, "specific_days") == "build_window"

    def test_less_binary(self):
        assert assign_catalyst_bucket(120, "specific_days") == "less_binary"

    def test_core_far(self):
        assert assign_catalyst_bucket(200, "specific_days") == "core"

    def test_core_no_upcoming(self):
        assert assign_catalyst_bucket(10, "no_upcoming") == "core"

    def test_core_missing(self):
        assert assign_catalyst_bucket(None, "missing") == "core"

    def test_core_none_days(self):
        assert assign_catalyst_bucket(None, "specific_days") == "core"

    def test_boundary_30(self):
        assert assign_catalyst_bucket(30, "specific_days") == "binary_now"

    def test_boundary_31(self):
        assert assign_catalyst_bucket(31, "specific_days") == "build_window"

    def test_boundary_90(self):
        assert assign_catalyst_bucket(90, "specific_days") == "build_window"

    def test_boundary_91(self):
        assert assign_catalyst_bucket(91, "specific_days") == "less_binary"

    def test_boundary_180(self):
        assert assign_catalyst_bucket(180, "specific_days") == "less_binary"

    def test_boundary_181(self):
        assert assign_catalyst_bucket(181, "specific_days") == "core"


# ---------------------------------------------------------------------------
# Far-out relabel (>540 days → no_upcoming)
# ---------------------------------------------------------------------------


class TestFarOutRelabel:

    def _make_rec(self, days_to_catalyst, in_optimal_window=False):
        """Minimal rec for _compute_overlays."""
        return {
            "catalyst_decay": {
                "days_to_catalyst": days_to_catalyst,
                "in_optimal_window": in_optimal_window,
            },
            "smart_money_signal": {},
            "coinvest": {},
            "defensive_features": {},
            "score_breakdown": {"enhancements": {"momentum": {}}},
            "momentum_signal": {},
        }

    def test_600_days_becomes_no_upcoming(self):
        """catalyst_days > 540 → mode=no_upcoming, bucket=core."""
        rec = self._make_rec(600)
        result = _compute_overlays(rec, DecisionRuleset())
        assert result["catalyst_mode"] == "no_upcoming"
        assert result["catalyst_bucket"] == "core"

    def test_541_days_becomes_no_upcoming(self):
        rec = self._make_rec(541)
        result = _compute_overlays(rec, DecisionRuleset())
        assert result["catalyst_mode"] == "no_upcoming"

    def test_540_days_stays_specific(self):
        rec = self._make_rec(540)
        result = _compute_overlays(rec, DecisionRuleset())
        assert result["catalyst_mode"] == "specific_days"

    def test_near_91_180_stays_unchanged(self):
        rec = self._make_rec(120)
        result = _compute_overlays(rec, DecisionRuleset())
        assert result["catalyst_mode"] == "specific_days"
        assert result["catalyst_bucket"] == "less_binary"

    def test_near_30_is_binary_now(self):
        rec = self._make_rec(15)
        result = _compute_overlays(rec, DecisionRuleset())
        assert result["catalyst_mode"] == "specific_days"
        assert result["catalyst_bucket"] == "binary_now"

    def test_blended_window_is_binary_now(self):
        rec = self._make_rec(0, in_optimal_window=True)
        result = _compute_overlays(rec, DecisionRuleset())
        assert result["catalyst_mode"] == "blended_window"
        assert result["catalyst_bucket"] == "binary_now"


# ---------------------------------------------------------------------------
# Action list exporter
# ---------------------------------------------------------------------------

from export_action_lists import OUTPUT_COLUMNS, export_action_lists, split_by_book, write_csv, write_summary_md


def _make_ranking_row(
    ticker: str,
    eligible: str = "1",
    actionable_rank: str = "1",
    catalyst_days: str = "10",
    catalyst_mode: str = "specific_days",
    catalyst_bucket: str = "binary_now",
    target_weight_pct: str = "5.0",
    tier_any: str = "A",
    mom_state: str = "tailwind",
    alpha_cohort_key: str = "early|near_0_30|pos",
    clinical_optionality_pct_dev: str = "0.75",
    tier_any_reason: str = "high_opt+catalyst_near",
    catalyst_in_window: str = "True",
) -> dict:
    return {
        "ticker": ticker,
        "eligible": eligible,
        "actionable_rank": actionable_rank,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "catalyst_bucket": catalyst_bucket,
        "target_weight_pct": target_weight_pct,
        "tier_any": tier_any,
        "mom_state": mom_state,
        "alpha_cohort_key": alpha_cohort_key,
        "clinical_optionality_pct_dev": clinical_optionality_pct_dev,
        "tier_any_reason": tier_any_reason,
        "catalyst_in_window": catalyst_in_window,
    }


class TestSplitByBook:

    def test_binary_rows_go_to_binary(self):
        rows = [_make_ranking_row("A", catalyst_bucket="binary_now")]
        core, binary = split_by_book(rows, "2026-03-08")
        assert len(binary) == 1
        assert len(core) == 0
        assert binary[0]["ticker"] == "A"

    def test_core_rows_go_to_core(self):
        rows = [_make_ranking_row("B", catalyst_bucket="core", catalyst_days="200", catalyst_mode="no_upcoming")]
        core, binary = split_by_book(rows, "2026-03-08")
        assert len(core) == 1
        assert len(binary) == 0

    def test_less_binary_goes_to_core(self):
        rows = [_make_ranking_row("C", catalyst_bucket="less_binary", catalyst_days="120")]
        core, binary = split_by_book(rows, "2026-03-08")
        assert len(core) == 1

    def test_build_window_goes_to_binary(self):
        rows = [_make_ranking_row("D", catalyst_bucket="build_window", catalyst_days="60")]
        core, binary = split_by_book(rows, "2026-03-08")
        assert len(binary) == 1

    def test_ineligible_excluded(self):
        rows = [_make_ranking_row("E", eligible="0")]
        core, binary = split_by_book(rows, "2026-03-08")
        assert len(core) == 0
        assert len(binary) == 0

    def test_sorted_by_rank(self):
        rows = [
            _make_ranking_row("Z", actionable_rank="3", catalyst_bucket="binary_now"),
            _make_ranking_row("A", actionable_rank="1", catalyst_bucket="binary_now"),
            _make_ranking_row("M", actionable_rank="2", catalyst_bucket="binary_now"),
        ]
        _, binary = split_by_book(rows, "2026-03-08")
        tickers = [r["ticker"] for r in binary]
        assert tickers == ["A", "M", "Z"]

    def test_date_column_present(self):
        rows = [_make_ranking_row("A", catalyst_bucket="binary_now")]
        _, binary = split_by_book(rows, "2026-03-08")
        assert binary[0]["date"] == "2026-03-08"

    def test_fallback_bucket_assignment(self):
        """Older snapshots without catalyst_bucket column still work."""
        row = _make_ranking_row("X", catalyst_days="15", catalyst_mode="specific_days")
        del row["catalyst_bucket"]
        _, binary = split_by_book([row], "2026-03-08")
        assert len(binary) == 1
        assert binary[0]["catalyst_bucket"] == "binary_now"


class TestWriteCsv:

    def test_writes_valid_csv(self, tmp_path):
        rows = [
            {"date": "2026-03-08", "ticker": "A", "actionable_rank": "1"},
        ]
        path = tmp_path / "test.csv"
        write_csv(rows, path)
        with open(path) as f:
            reader = csv.DictReader(f)
            loaded = list(reader)
        assert len(loaded) == 1
        assert loaded[0]["ticker"] == "A"
        assert set(reader.fieldnames) == set(OUTPUT_COLUMNS)


class TestWriteSummaryMd:

    def test_summary_has_both_sections(self, tmp_path):
        core = [_make_ranking_row("C", catalyst_bucket="core")]
        binary = [_make_ranking_row("B", catalyst_bucket="binary_now")]
        path = tmp_path / "summary.md"
        write_summary_md(core, binary, "2026-03-08", path)
        text = path.read_text()
        assert "Binary Book" in text
        assert "Core Book" in text
        assert "B" in text
        assert "C" in text


class TestExportActionListsE2E:

    def test_full_export(self, tmp_path):
        """End-to-end: write a snapshot, export, verify outputs."""
        snap_dir = tmp_path / "snapshot"
        snap_dir.mkdir()
        # Write a minimal rankings.csv
        csv_path = snap_dir / "rankings.csv"
        fieldnames = list(_make_ranking_row("X").keys())
        rows = [
            _make_ranking_row("BIN1", actionable_rank="1", catalyst_bucket="binary_now", catalyst_days="10"),
            _make_ranking_row("BIN2", actionable_rank="2", catalyst_bucket="build_window", catalyst_days="60"),
            _make_ranking_row("CORE1", actionable_rank="3", catalyst_bucket="less_binary", catalyst_days="120"),
            _make_ranking_row(
                "CORE2", actionable_rank="4", catalyst_bucket="core", catalyst_days="", catalyst_mode="no_upcoming"
            ),
            _make_ranking_row("INELIG", actionable_rank="", eligible="0", catalyst_bucket="binary_now"),
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        out_dir = tmp_path / "output"
        core_p, bin_p, md_p = export_action_lists(snap_dir, out_dir, "2026-03-08")

        assert core_p.exists()
        assert bin_p.exists()
        assert md_p.exists()

        # Verify counts
        with open(bin_p) as f:
            binary_rows = list(csv.DictReader(f))
        with open(core_p) as f:
            core_rows = list(csv.DictReader(f))

        assert len(binary_rows) == 2  # BIN1 + BIN2
        assert len(core_rows) == 2  # CORE1 + CORE2
        assert binary_rows[0]["ticker"] == "BIN1"
        assert core_rows[0]["ticker"] == "CORE1"
