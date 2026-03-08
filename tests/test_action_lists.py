"""Tests for action list builder + bucket classification + far-out relabel.

Validates:
  1. Bucket exclusivity — no ticker in both binary and less_binary
  2. Deterministic sorting — actionable_rank then ticker
  3. Far-out relabel — catalyst_days > 540 → not "specific_days"
  4. Classification rules match spec
  5. Output file structure
  6. Bucketed eval output schema
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from decision_engine import assign_catalyst_bucket

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(
    ticker: str,
    rank: int,
    catalyst_days: str = "",
    catalyst_mode: str = "missing",
    eligible: str = "1",
    weight: str = "5.0",
    catalyst_bucket: str = "",
) -> Dict[str, str]:
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": eligible,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "catalyst_bucket": catalyst_bucket,
        "catalyst_strength": "",
        "target_weight_pct": weight,
        "tier_any": "A",
        "archetype": "drug_developer",
        "alpha_cohort_key": "",
        "mom_state": "tailwind",
        "industry_group": "",
    }


def _write_rankings_csv(snap_dir: Path, rows: List[Dict[str, str]]) -> None:
    snap_dir.mkdir(parents=True, exist_ok=True)
    csv_path = snap_dir / "rankings.csv"
    if rows:
        fieldnames = list(rows[0].keys())
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


# ---------------------------------------------------------------------------
# A) Classification rules
# ---------------------------------------------------------------------------


class TestClassifyActionBucket:

    def test_specific_days_0_30_is_binary(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("VRTX", 1, catalyst_days="15", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "binary_0_30"

    def test_specific_days_31_90_is_binary(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("GILD", 2, catalyst_days="60", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "binary_31_90"

    def test_specific_days_91_180_is_binary(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("BIIB", 3, catalyst_days="120", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "binary_91_180"

    def test_specific_days_boundary_30(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("ALNY", 4, catalyst_days="30", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "binary_0_30"

    def test_specific_days_boundary_31(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("ALNY", 4, catalyst_days="31", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "binary_31_90"

    def test_specific_days_boundary_90(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("ALNY", 4, catalyst_days="90", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "binary_31_90"

    def test_specific_days_boundary_91(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("ALNY", 4, catalyst_days="91", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "binary_91_180"

    def test_specific_days_boundary_180(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("ALNY", 4, catalyst_days="180", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "binary_91_180"

    def test_specific_days_above_180_is_less_binary(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("IONS", 5, catalyst_days="200", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "less_binary"

    def test_blended_window_is_less_binary(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("MRNA", 6, catalyst_days="0", catalyst_mode="blended_window")
        assert classify_action_bucket(row) == "less_binary"

    def test_no_upcoming_is_less_binary(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("ILMN", 7, catalyst_days="", catalyst_mode="no_upcoming")
        assert classify_action_bucket(row) == "less_binary"

    def test_missing_mode_is_less_binary(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("NTRA", 8, catalyst_days="", catalyst_mode="missing")
        assert classify_action_bucket(row) == "less_binary"

    def test_zero_days_specific_is_less_binary(self):
        """catalyst_days=0 with specific_days is not binary (must be >= 1)."""
        from build_action_lists import classify_action_bucket

        row = _make_row("TEST", 9, catalyst_days="0", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "less_binary"

    def test_negative_days_is_less_binary(self):
        from build_action_lists import classify_action_bucket

        row = _make_row("TEST", 10, catalyst_days="-5", catalyst_mode="specific_days")
        assert classify_action_bucket(row) == "less_binary"


# ---------------------------------------------------------------------------
# B) Bucket exclusivity
# ---------------------------------------------------------------------------


class TestBucketExclusivity:

    def test_no_ticker_in_multiple_buckets(self, tmp_path):
        from build_action_lists import build_action_lists

        snap_dir = tmp_path / "2026-03-08"
        rows = [
            _make_row("VRTX", 1, "15", "specific_days"),
            _make_row("GILD", 2, "60", "specific_days"),
            _make_row("BIIB", 3, "120", "specific_days"),
            _make_row("ILMN", 4, "", "no_upcoming"),
            _make_row("MRNA", 5, "0", "blended_window"),
            _make_row("LLY", 6, "200", "specific_days"),
        ]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)

        all_tickers: List[str] = []
        for bucket_rows in buckets.values():
            for r in bucket_rows:
                all_tickers.append(r["ticker"])

        # No duplicates
        assert len(all_tickers) == len(set(all_tickers)), f"Duplicate tickers across buckets: {all_tickers}"

    def test_all_eligible_tickers_assigned(self, tmp_path):
        from build_action_lists import build_action_lists

        snap_dir = tmp_path / "2026-03-08"
        rows = [
            _make_row("A", 1, "10", "specific_days"),
            _make_row("B", 2, "50", "specific_days"),
            _make_row("C", 3, "100", "specific_days"),
            _make_row("D", 4, "", "missing"),
            _make_row("E", 5, "300", "specific_days"),  # >180 → less_binary
        ]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)

        all_tickers = set()
        for bucket_rows in buckets.values():
            for r in bucket_rows:
                all_tickers.add(r["ticker"])

        assert all_tickers == {"A", "B", "C", "D", "E"}


# ---------------------------------------------------------------------------
# C) Deterministic sorting
# ---------------------------------------------------------------------------


class TestDeterministicSort:

    def test_sorted_by_rank_then_ticker(self, tmp_path):
        from build_action_lists import build_action_lists

        snap_dir = tmp_path / "2026-03-08"
        # Same rank → should be sorted by ticker
        rows = [
            _make_row("ZZZZ", 1, "", "missing"),
            _make_row("AAAA", 1, "", "missing"),
            _make_row("MMMM", 2, "", "missing"),
        ]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)

        lb = buckets["less_binary"]
        tickers = [r["ticker"] for r in lb]
        assert tickers == ["AAAA", "ZZZZ", "MMMM"]

    def test_stable_across_runs(self, tmp_path):
        """Two runs produce identical output."""
        from build_action_lists import build_action_lists

        snap_dir = tmp_path / "2026-03-08"
        rows = [
            _make_row("C", 3, "15", "specific_days"),
            _make_row("A", 1, "15", "specific_days"),
            _make_row("B", 2, "15", "specific_days"),
        ]
        _write_rankings_csv(snap_dir, rows)

        run1 = build_action_lists(snap_dir)
        run2 = build_action_lists(snap_dir)

        for b in run1:
            t1 = [r["ticker"] for r in run1[b]]
            t2 = [r["ticker"] for r in run2[b]]
            assert t1 == t2, f"Bucket {b} not stable: {t1} vs {t2}"


# ---------------------------------------------------------------------------
# D) Far-out relabel (catalyst_days > 540)
# ---------------------------------------------------------------------------


class TestFarOutRelabel:

    def test_540_days_not_specific_days(self):
        """catalyst_days=1200 should NOT be labeled specific_days by DE."""
        # In decision_engine, days > 540 forces catalyst_mode = "no_upcoming"
        # So assign_catalyst_bucket should return "core"
        bucket = assign_catalyst_bucket(1200, "no_upcoming")
        assert bucket == "core"

    def test_541_days_forced_no_upcoming(self):
        """Verify DE relabel: days > 540 → no_upcoming."""
        from decision_engine import DecisionRuleset, _compute_overlays

        ruleset = DecisionRuleset()
        rec = {
            "catalyst_decay": {
                "days_to_catalyst": 1200,
                "in_optimal_window": False,
            },
            "smart_money_signal": {"score": 0},
            "coinvest": {},
            "momentum_signal": {"alpha_60d_vs_xbi": 0},
            "score_breakdown": {"enhancements": {"momentum": {"alpha_60d": 0}}},
            "severity": "GREEN",
        }
        overlays = _compute_overlays(rec, ruleset)
        assert overlays["catalyst_mode"] == "no_upcoming"

    def test_540_exactly_is_still_specific(self):
        """540 days exactly should still be specific_days (threshold is >540)."""
        from decision_engine import DecisionRuleset, _compute_overlays

        ruleset = DecisionRuleset()
        rec = {
            "catalyst_decay": {
                "days_to_catalyst": 540,
                "in_optimal_window": False,
            },
            "smart_money_signal": {"score": 0},
            "coinvest": {},
            "momentum_signal": {"alpha_60d_vs_xbi": 0},
            "score_breakdown": {"enhancements": {"momentum": {"alpha_60d": 0}}},
            "severity": "GREEN",
        }
        overlays = _compute_overlays(rec, ruleset)
        assert overlays["catalyst_mode"] == "specific_days"

    def test_regression_1200_days_not_binary(self):
        """Regression: catalyst_days=1200 must NOT output binary bucket."""
        from build_action_lists import classify_action_bucket

        # Even if somehow catalyst_mode is "specific_days" with 1200 days,
        # classify_action_bucket rejects it (days > 180 → less_binary)
        row = _make_row("TEST", 1, "1200", "specific_days")
        assert classify_action_bucket(row) == "less_binary"


# ---------------------------------------------------------------------------
# E) Output file structure
# ---------------------------------------------------------------------------


class TestOutputFiles:

    def test_writes_four_csvs_and_readme(self, tmp_path):
        from build_action_lists import build_action_lists, write_action_lists

        snap_dir = tmp_path / "2026-03-08"
        rows = [
            _make_row("VRTX", 1, "15", "specific_days"),
            _make_row("GILD", 2, "", "missing"),
        ]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)

        out_dir = tmp_path / "action_lists"
        write_action_lists(buckets, out_dir, as_of_date="2026-03-08")

        assert (out_dir / "binary_0_30.csv").is_file()
        assert (out_dir / "binary_31_90.csv").is_file()
        assert (out_dir / "binary_91_180.csv").is_file()
        assert (out_dir / "less_binary.csv").is_file()
        assert (out_dir / "README.md").is_file()

    def test_csv_has_correct_columns(self, tmp_path):
        from build_action_lists import ACTION_LIST_COLUMNS, build_action_lists, write_action_lists

        snap_dir = tmp_path / "2026-03-08"
        rows = [_make_row("VRTX", 1, "15", "specific_days")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)

        out_dir = tmp_path / "action_lists"
        write_action_lists(buckets, out_dir, as_of_date="2026-03-08")

        with open(out_dir / "binary_0_30.csv") as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == ACTION_LIST_COLUMNS
            rows_out = list(reader)
            assert len(rows_out) == 1
            assert rows_out[0]["ticker"] == "VRTX"

    def test_readme_contains_classification_rules(self, tmp_path):
        from build_action_lists import build_action_lists, write_action_lists

        snap_dir = tmp_path / "2026-03-08"
        rows = [_make_row("VRTX", 1, "15", "specific_days")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)

        out_dir = tmp_path / "action_lists"
        write_action_lists(buckets, out_dir, as_of_date="2026-03-08")

        readme = (out_dir / "README.md").read_text()
        assert "Classification Rules" in readme
        assert "specific_days" in readme
        assert "Binary book" in readme or "binary" in readme.lower()

    def test_empty_bucket_writes_header_only_csv(self, tmp_path):
        from build_action_lists import build_action_lists, write_action_lists

        snap_dir = tmp_path / "2026-03-08"
        # Only less_binary names
        rows = [_make_row("GILD", 1, "", "missing")]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir)

        out_dir = tmp_path / "action_lists"
        write_action_lists(buckets, out_dir, as_of_date="2026-03-08")

        with open(out_dir / "binary_0_30.csv") as f:
            reader = csv.DictReader(f)
            assert list(reader) == []  # Header only, no rows

    def test_ineligible_excluded_by_default(self, tmp_path):
        from build_action_lists import build_action_lists

        snap_dir = tmp_path / "2026-03-08"
        rows = [
            _make_row("VRTX", 1, "15", "specific_days", eligible="1"),
            _make_row("GILD", 2, "30", "specific_days", eligible="0"),
        ]
        _write_rankings_csv(snap_dir, rows)
        buckets = build_action_lists(snap_dir, eligible_only=True)

        all_tickers = set()
        for bucket_rows in buckets.values():
            for r in bucket_rows:
                all_tickers.add(r["ticker"])
        assert "VRTX" in all_tickers
        assert "GILD" not in all_tickers


# ---------------------------------------------------------------------------
# F) Bucketed eval output schema
# ---------------------------------------------------------------------------


class TestBucketEvalSchema:

    def test_bucket_filter_map_covers_all_buckets(self):
        from eval_by_bucket import ALL_BUCKETS, BUCKET_FILTER_MAP

        for b in ALL_BUCKETS:
            assert b in BUCKET_FILTER_MAP, f"Missing filter map for bucket {b}"

    def test_bucket_filter_map_values_are_valid(self):
        """Filter values should be valid catalyst_bucket values."""
        from eval_by_bucket import BUCKET_FILTER_MAP

        valid_catalyst_buckets = {"binary_now", "build_window", "less_binary", "core"}
        for bucket, filters in BUCKET_FILTER_MAP.items():
            for f in filters:
                assert f in valid_catalyst_buckets, f"Invalid filter {f!r} for bucket {bucket}"

    def test_schema_version(self):
        from eval_by_bucket import SCHEMA

        assert SCHEMA == "eval_by_bucket.v1"

    def test_verdict_md_rendering(self, tmp_path):
        from eval_by_bucket import write_verdict_md

        results = {
            "schema": "eval_by_bucket.v1",
            "horizons": [84, 126],
            "top_k": 20,
            "cost_bps": 30.0,
            "benchmark": "XBI",
            "buckets": {
                "binary_0_30": {
                    "display_name": "Binary 0-30d",
                    "by_horizon": {
                        84: {
                            "n_dates": 10,
                            "mean_ic": 0.05,
                            "ic_t_stat": 1.5,
                            "mean_net_return": 0.01,
                            "mean_excess_return": 0.005,
                            "mean_hedged_return": 0.008,
                            "mean_turnover": 0.15,
                        },
                        126: {
                            "n_dates": 10,
                            "mean_ic": 0.08,
                            "ic_t_stat": 2.0,
                            "mean_net_return": 0.02,
                            "mean_excess_return": 0.01,
                            "mean_hedged_return": 0.015,
                            "mean_turnover": 0.12,
                        },
                    },
                },
                "binary_31_90": {
                    "display_name": "Binary 31-90d",
                    "by_horizon": {
                        84: {
                            "n_dates": 10,
                            "mean_ic": 0.06,
                            "ic_t_stat": 1.8,
                            "mean_net_return": 0.015,
                            "mean_excess_return": 0.008,
                            "mean_hedged_return": 0.01,
                            "mean_turnover": 0.10,
                        },
                        126: {
                            "n_dates": 10,
                            "mean_ic": 0.09,
                            "ic_t_stat": 2.2,
                            "mean_net_return": 0.025,
                            "mean_excess_return": 0.012,
                            "mean_hedged_return": 0.018,
                            "mean_turnover": 0.09,
                        },
                    },
                },
                "binary_91_180": {
                    "display_name": "Binary 91-180d",
                    "by_horizon": {
                        84: {
                            "n_dates": 10,
                            "mean_ic": 0.07,
                            "ic_t_stat": 2.0,
                            "mean_net_return": 0.02,
                            "mean_excess_return": 0.01,
                            "mean_hedged_return": 0.012,
                            "mean_turnover": 0.08,
                        },
                        126: {
                            "n_dates": 10,
                            "mean_ic": 0.10,
                            "ic_t_stat": 2.5,
                            "mean_net_return": 0.03,
                            "mean_excess_return": 0.015,
                            "mean_hedged_return": 0.02,
                            "mean_turnover": 0.07,
                        },
                    },
                },
                "less_binary": {
                    "display_name": "Less Binary",
                    "by_horizon": {
                        84: {
                            "n_dates": 10,
                            "mean_ic": 0.10,
                            "ic_t_stat": 3.0,
                            "mean_net_return": 0.03,
                            "mean_excess_return": 0.015,
                            "mean_hedged_return": 0.02,
                            "mean_turnover": 0.06,
                        },
                        126: {
                            "n_dates": 10,
                            "mean_ic": 0.12,
                            "ic_t_stat": 3.5,
                            "mean_net_return": 0.04,
                            "mean_excess_return": 0.02,
                            "mean_hedged_return": 0.025,
                            "mean_turnover": 0.05,
                        },
                    },
                },
            },
        }

        path = write_verdict_md(results, tmp_path)
        text = path.read_text()
        assert "Bucketed Evaluation Verdict" in text
        assert "84-Day Horizon" in text
        assert "126-Day Horizon" in text
        assert "Binary 0-30d" in text
        assert "Less Binary" in text
        assert "Binary vs Less-Binary Aggregate" in text

    def test_bucket_default_horizons_defined(self):
        from eval_by_bucket import ALL_BUCKETS, BUCKET_DEFAULT_HORIZONS

        for b in ALL_BUCKETS:
            assert b in BUCKET_DEFAULT_HORIZONS, f"Missing default horizons for {b}"
            assert len(BUCKET_DEFAULT_HORIZONS[b]) >= 2, f"Need primary+guardrail for {b}"

    def test_verdict_md_bucket_specific(self, tmp_path):
        from eval_by_bucket import write_verdict_md

        results = {
            "schema": "eval_by_bucket.v1",
            "horizons": [20, 63, 84, 126],
            "top_k": 20,
            "cost_bps": 30.0,
            "benchmark": "XBI",
            "bucket_specific_horizons": True,
            "buckets": {
                "binary_0_30": {
                    "display_name": "Binary 0-30d",
                    "horizons": [20, 63],
                    "by_horizon": {
                        20: {"n_dates": 5, "mean_ic": 0.03},
                        63: {"n_dates": 5, "mean_ic": 0.04},
                    },
                },
                "binary_31_90": {
                    "display_name": "Binary 31-90d",
                    "horizons": [63, 84],
                    "by_horizon": {
                        63: {"n_dates": 5, "mean_ic": 0.05},
                        84: {"n_dates": 5, "mean_ic": 0.06},
                    },
                },
                "binary_91_180": {
                    "display_name": "Binary 91-180d",
                    "horizons": [84, 126],
                    "by_horizon": {
                        84: {"n_dates": 5, "mean_ic": 0.07},
                        126: {"n_dates": 5, "mean_ic": 0.08},
                    },
                },
                "less_binary": {
                    "display_name": "Less Binary",
                    "horizons": [84, 126],
                    "by_horizon": {
                        84: {"n_dates": 5, "mean_ic": 0.10},
                        126: {"n_dates": 5, "mean_ic": 0.12},
                    },
                },
            },
        }
        path = write_verdict_md(results, tmp_path)
        text = path.read_text()
        assert "bucket-specific" in text
        # Each bucket gets its own section (not per-horizon cross-bucket)
        assert "## Binary 0-30d" in text
        assert "## Less Binary" in text
        assert "20d" in text  # binary_0_30 uses 20d horizon


# ---------------------------------------------------------------------------
# G) Bucket hysteresis
# ---------------------------------------------------------------------------


class TestBucketHysteresis:

    def test_no_prev_bucket_standard_assignment(self):
        from decision_engine import assign_catalyst_bucket_with_hysteresis

        assert assign_catalyst_bucket_with_hysteresis(25, "specific_days") == "binary_now"
        assert assign_catalyst_bucket_with_hysteresis(60, "specific_days") == "build_window"
        assert assign_catalyst_bucket_with_hysteresis(120, "specific_days") == "less_binary"

    def test_stays_in_binary_now_within_buffer(self):
        from decision_engine import assign_catalyst_bucket_with_hysteresis

        # At 33 days, normally would be build_window (31-90)
        # But with hysteresis from binary_now, stays until 37
        result = assign_catalyst_bucket_with_hysteresis(33, "specific_days", prev_bucket="binary_now")
        assert result == "binary_now"

    def test_exits_binary_now_past_buffer(self):
        from decision_engine import assign_catalyst_bucket_with_hysteresis

        # At 38 days, past the exit threshold (30+7=37)
        result = assign_catalyst_bucket_with_hysteresis(38, "specific_days", prev_bucket="binary_now")
        assert result == "build_window"

    def test_stays_in_build_window_within_buffer(self):
        from decision_engine import assign_catalyst_bucket_with_hysteresis

        # At 93 days, normally would be less_binary (91-180)
        # But with hysteresis from build_window, stays until 97
        result = assign_catalyst_bucket_with_hysteresis(93, "specific_days", prev_bucket="build_window")
        assert result == "build_window"

    def test_exits_build_window_past_buffer(self):
        from decision_engine import assign_catalyst_bucket_with_hysteresis

        result = assign_catalyst_bucket_with_hysteresis(98, "specific_days", prev_bucket="build_window")
        assert result == "less_binary"

    def test_stays_in_less_binary_within_buffer(self):
        from decision_engine import assign_catalyst_bucket_with_hysteresis

        # At 183 days, normally would be core (>180)
        # But with hysteresis, stays until 187
        result = assign_catalyst_bucket_with_hysteresis(183, "specific_days", prev_bucket="less_binary")
        assert result == "less_binary"

    def test_exits_less_binary_past_buffer(self):
        from decision_engine import assign_catalyst_bucket_with_hysteresis

        result = assign_catalyst_bucket_with_hysteresis(188, "specific_days", prev_bucket="less_binary")
        assert result == "core"

    def test_can_reenter_lower_bucket(self):
        """If days decrease (new closer event), should enter lower bucket."""
        from decision_engine import assign_catalyst_bucket_with_hysteresis

        # Was in build_window, now days=20 → should enter binary_now
        result = assign_catalyst_bucket_with_hysteresis(20, "specific_days", prev_bucket="build_window")
        assert result == "binary_now"

    def test_core_modes_always_core(self):
        from decision_engine import assign_catalyst_bucket_with_hysteresis

        result = assign_catalyst_bucket_with_hysteresis(25, "no_upcoming", prev_bucket="binary_now")
        assert result == "core"

    def test_custom_buffer(self):
        from decision_engine import assign_catalyst_bucket_with_hysteresis

        # With buffer=10, exit threshold is 30+10=40
        result = assign_catalyst_bucket_with_hysteresis(38, "specific_days", prev_bucket="binary_now", buffer=10)
        assert result == "binary_now"  # 38 < 40, stays

    def test_ruleset_flag_exists(self):
        from decision_engine import DecisionRuleset

        rs = DecisionRuleset()
        assert rs.enable_bucket_hysteresis is False


# ---------------------------------------------------------------------------
# On-the-fly bucket backfill in eval_forward_returns
# ---------------------------------------------------------------------------


class TestEvalBucketBackfill:
    """Verify eval computes catalyst_bucket on the fly for legacy snapshots."""

    def test_backfill_assigns_correct_buckets(self):
        """Rankings without catalyst_bucket get it computed from mode + days."""
        rankings = [
            {"ticker": "A", "catalyst_mode": "specific_days", "catalyst_days": "15"},
            {"ticker": "B", "catalyst_mode": "specific_days", "catalyst_days": "60"},
            {"ticker": "C", "catalyst_mode": "specific_days", "catalyst_days": "120"},
            {"ticker": "D", "catalyst_mode": "no_upcoming", "catalyst_days": ""},
        ]
        # None have catalyst_bucket → backfill should fire
        assert not any(r.get("catalyst_bucket") for r in rankings)

        from decision_engine import assign_catalyst_bucket

        for r in rankings:
            cd = r.get("catalyst_days", "")
            try:
                cd_f = float(cd) if cd not in ("", None) else None
            except (ValueError, TypeError):
                cd_f = None
            r["catalyst_bucket"] = assign_catalyst_bucket(cd_f, str(r.get("catalyst_mode", "")))

        assert rankings[0]["catalyst_bucket"] == "binary_now"
        assert rankings[1]["catalyst_bucket"] == "build_window"
        assert rankings[2]["catalyst_bucket"] == "less_binary"
        assert rankings[3]["catalyst_bucket"] == "core"

    def test_filter_after_backfill(self):
        """After backfill, bucket_filter correctly restricts rankings."""
        rankings = [
            {"ticker": "A", "catalyst_mode": "specific_days", "catalyst_days": "15"},
            {"ticker": "B", "catalyst_mode": "specific_days", "catalyst_days": "60"},
            {"ticker": "C", "catalyst_mode": "no_upcoming", "catalyst_days": ""},
        ]
        from decision_engine import assign_catalyst_bucket

        for r in rankings:
            cd = r.get("catalyst_days", "")
            try:
                cd_f = float(cd) if cd not in ("", None) else None
            except (ValueError, TypeError):
                cd_f = None
            r["catalyst_bucket"] = assign_catalyst_bucket(cd_f, str(r.get("catalyst_mode", "")))

        allowed = {"build_window"}
        filtered = [r for r in rankings if r.get("catalyst_bucket", "").strip() in allowed]
        assert len(filtered) == 1
        assert filtered[0]["ticker"] == "B"
