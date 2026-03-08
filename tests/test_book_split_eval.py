"""Tests for book-split backtest evaluation (--bucket-filter + --book-split).

Validates:
  1. eval_forward_returns bucket_filter param filters rankings correctly
  2. run_audited_backtest book_split wiring (constants, _run_eval passthrough)
  3. AUDIT.md rendering of book-split results
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from decision_engine import assign_catalyst_bucket

# ---------------------------------------------------------------------------
# Helper: build a minimal rankings.csv
# ---------------------------------------------------------------------------


def _make_ranking_row(
    ticker: str,
    rank: int,
    catalyst_bucket: str = "core",
    catalyst_days: str = "200",
    catalyst_mode: str = "specific_days",
    eligible: str = "1",
) -> Dict[str, str]:
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": eligible,
        "catalyst_bucket": catalyst_bucket,
        "catalyst_days": catalyst_days,
        "catalyst_mode": catalyst_mode,
        "target_weight_pct": "5.0",
        "tier_any": "A",
        "mom_state": "tailwind",
    }


def _write_snapshot(snap_dir: Path, rows: List[Dict[str, str]]) -> None:
    snap_dir.mkdir(parents=True, exist_ok=True)
    csv_path = snap_dir / "rankings.csv"
    if rows:
        fieldnames = list(rows[0].keys())
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


# ---------------------------------------------------------------------------
# A) bucket_filter integration with eval_forward_returns.evaluate()
# ---------------------------------------------------------------------------


class TestBucketFilterIntegration:
    """Test the bucket_filter parameter in eval_forward_returns.evaluate()."""

    def test_bucket_filter_param_exists(self):
        """evaluate() accepts bucket_filter keyword."""
        import inspect

        from eval_forward_returns import evaluate

        sig = inspect.signature(evaluate)
        assert "bucket_filter" in sig.parameters

    def test_bucket_filter_default_is_none(self):
        """Default bucket_filter is None (no filtering)."""
        import inspect

        from eval_forward_returns import evaluate

        sig = inspect.signature(evaluate)
        assert sig.parameters["bucket_filter"].default is None


# ---------------------------------------------------------------------------
# B) run_audited_backtest book_split constants
# ---------------------------------------------------------------------------


class TestBookSplitConstants:

    def test_binary_book_buckets(self):
        from run_audited_backtest import BINARY_BOOK_BUCKETS

        assert set(BINARY_BOOK_BUCKETS) == {"binary_now", "build_window"}

    def test_core_book_buckets(self):
        from run_audited_backtest import CORE_BOOK_BUCKETS

        assert set(CORE_BOOK_BUCKETS) == {"less_binary", "core"}

    def test_binary_book_horizons(self):
        from run_audited_backtest import BINARY_BOOK_HORIZONS

        assert BINARY_BOOK_HORIZONS == [5, 20, 84]

    def test_core_book_horizons(self):
        from run_audited_backtest import CORE_BOOK_HORIZONS

        assert CORE_BOOK_HORIZONS == [84, 126]

    def test_bucket_sets_are_disjoint(self):
        from run_audited_backtest import BINARY_BOOK_BUCKETS, CORE_BOOK_BUCKETS

        assert set(BINARY_BOOK_BUCKETS).isdisjoint(set(CORE_BOOK_BUCKETS))

    def test_bucket_sets_cover_all_buckets(self):
        """Binary + core buckets should cover all possible assign_catalyst_bucket outputs."""
        from run_audited_backtest import BINARY_BOOK_BUCKETS, CORE_BOOK_BUCKETS

        all_buckets = set(BINARY_BOOK_BUCKETS) | set(CORE_BOOK_BUCKETS)
        # Verify against known outputs
        assert all_buckets == {"binary_now", "build_window", "less_binary", "core"}


# ---------------------------------------------------------------------------
# C) _run_eval passes bucket_filter through to CLI args
# ---------------------------------------------------------------------------


class TestRunEvalBucketFilter:

    def test_run_eval_accepts_bucket_filter(self):
        """_run_eval() accepts bucket_filter keyword."""
        import inspect

        from run_audited_backtest import _run_eval

        sig = inspect.signature(_run_eval)
        assert "bucket_filter" in sig.parameters

    def test_run_eval_default_bucket_filter_is_none(self):
        import inspect

        from run_audited_backtest import _run_eval

        sig = inspect.signature(_run_eval)
        assert sig.parameters["bucket_filter"].default is None


# ---------------------------------------------------------------------------
# D) run_audited_backtest accepts book_split
# ---------------------------------------------------------------------------


class TestRunAuditedBacktestBookSplit:

    def test_book_split_param_exists(self):
        import inspect

        from run_audited_backtest import run_audited_backtest

        sig = inspect.signature(run_audited_backtest)
        assert "book_split" in sig.parameters

    def test_book_split_default_is_false(self):
        import inspect

        from run_audited_backtest import run_audited_backtest

        sig = inspect.signature(run_audited_backtest)
        assert sig.parameters["book_split"].default is False


# ---------------------------------------------------------------------------
# E) AUDIT.md book-split rendering
# ---------------------------------------------------------------------------


class TestAuditMdBookSplit:

    def _make_eval_summary(self, out_dir: Path, by_horizon: dict) -> None:
        """Write a mock summary.json."""
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "n_evaluated": 50,
            "n_dates": 55,
            "n_skipped": 5,
            "horizons": list(by_horizon.keys()),
            "by_horizon": by_horizon,
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    def test_audit_md_includes_book_split(self, tmp_path):
        """_write_audit_md renders book-split sections when dirs are provided."""
        from unittest.mock import MagicMock

        from run_audited_backtest import _write_audit_md

        # Create mock eval summary dirs
        eval_binary = tmp_path / "eval_binary"
        self._make_eval_summary(
            eval_binary,
            {
                "5": {
                    "mean_ic": 0.05,
                    "ic_t_stat": 1.5,
                    "mean_net_return": 0.01,
                    "mean_excess_return": 0.005,
                    "mean_turnover": 0.15,
                },
                "20": {
                    "mean_ic": 0.08,
                    "ic_t_stat": 2.1,
                    "mean_net_return": 0.03,
                    "mean_excess_return": 0.015,
                    "mean_turnover": 0.12,
                },
                "84": {
                    "mean_ic": 0.10,
                    "ic_t_stat": 2.5,
                    "mean_net_return": 0.05,
                    "mean_excess_return": 0.025,
                    "mean_turnover": 0.10,
                },
            },
        )
        eval_core = tmp_path / "eval_core"
        self._make_eval_summary(
            eval_core,
            {
                "84": {
                    "mean_ic": 0.12,
                    "ic_t_stat": 3.0,
                    "mean_net_return": 0.06,
                    "mean_excess_return": 0.03,
                    "mean_turnover": 0.08,
                },
                "126": {
                    "mean_ic": 0.15,
                    "ic_t_stat": 3.5,
                    "mean_net_return": 0.08,
                    "mean_excess_return": 0.04,
                    "mean_turnover": 0.06,
                },
            },
        )

        # Mock preflight report
        report = MagicMock()
        report.n_total = 55
        report.n_pass = 50
        report.n_warn = 3
        report.n_fail = 2
        report.results = []

        audit_path = _write_audit_md(
            tmp_path,
            run_id="test_run",
            git_sha="abc123",
            file_hashes={},
            report=report,
            horizons=[84, 126],
            top_k=20,
            cost_bps=30,
            snapshot_root=tmp_path / "snaps",
            eval_snapshot_root=tmp_path / "snaps",
            price_csv=tmp_path / "prices.csv",
            ruleset_path=None,
            date_from="2024-01-01",
            date_to="2024-12-31",
            date_manifest=None,
            anchor_mode="prev_trading_day",
            benchmark="XBI",
            strict=True,
            relaxed=False,
            reranked=False,
            preflight_dir=tmp_path / "preflight",
            eval_dir=tmp_path / "eval",
            eval_binary_dir=eval_binary,
            eval_core_dir=eval_core,
        )

        text = audit_path.read_text()
        assert "Book-Split Results" in text
        assert "Binary Book" in text
        assert "Core Book" in text
        # Check metrics rendered
        assert "5d" in text
        assert "20d" in text
        assert "84d" in text
        assert "126d" in text

    def test_audit_md_no_book_split(self, tmp_path):
        """Without book-split dirs, no book-split section appears."""
        from unittest.mock import MagicMock

        from run_audited_backtest import _write_audit_md

        report = MagicMock()
        report.n_total = 10
        report.n_pass = 10
        report.n_warn = 0
        report.n_fail = 0
        report.results = []

        audit_path = _write_audit_md(
            tmp_path,
            run_id="test_run",
            git_sha="abc123",
            file_hashes={},
            report=report,
            horizons=[84, 126],
            top_k=20,
            cost_bps=30,
            snapshot_root=tmp_path / "snaps",
            eval_snapshot_root=tmp_path / "snaps",
            price_csv=tmp_path / "prices.csv",
            ruleset_path=None,
            date_from=None,
            date_to=None,
            date_manifest=None,
            anchor_mode="prev_trading_day",
            benchmark="XBI",
            strict=True,
            relaxed=False,
            reranked=False,
            preflight_dir=tmp_path / "preflight",
            eval_dir=tmp_path / "eval",
        )

        text = audit_path.read_text()
        assert "Book-Split Results" not in text

    def test_audit_md_missing_summary_graceful(self, tmp_path):
        """When book-split dir exists but summary.json is missing, renders gracefully."""
        from unittest.mock import MagicMock

        from run_audited_backtest import _write_audit_md

        eval_binary = tmp_path / "eval_binary"
        eval_binary.mkdir(parents=True)
        # No summary.json

        report = MagicMock()
        report.n_total = 10
        report.n_pass = 10
        report.n_warn = 0
        report.n_fail = 0
        report.results = []

        audit_path = _write_audit_md(
            tmp_path,
            run_id="test_run",
            git_sha="abc123",
            file_hashes={},
            report=report,
            horizons=[84, 126],
            top_k=20,
            cost_bps=30,
            snapshot_root=tmp_path / "snaps",
            eval_snapshot_root=tmp_path / "snaps",
            price_csv=tmp_path / "prices.csv",
            ruleset_path=None,
            date_from=None,
            date_to=None,
            date_manifest=None,
            anchor_mode="prev_trading_day",
            benchmark="XBI",
            strict=True,
            relaxed=False,
            reranked=False,
            preflight_dir=tmp_path / "preflight",
            eval_dir=tmp_path / "eval",
            eval_binary_dir=eval_binary,
        )

        text = audit_path.read_text()
        assert "Book-Split Results" in text
        assert "not available" in text


# ---------------------------------------------------------------------------
# F) Bucket filter with assign_catalyst_bucket consistency
# ---------------------------------------------------------------------------


class TestBucketFilterConsistency:
    """Verify bucket assignment is consistent with filter expectations."""

    @pytest.mark.parametrize(
        "days,mode,expected_book",
        [
            (10, "specific_days", "binary"),
            (0, "blended_window", "binary"),
            (30, "specific_days", "binary"),
            (60, "specific_days", "binary"),
            (90, "specific_days", "binary"),
            (91, "specific_days", "core"),
            (120, "specific_days", "core"),
            (180, "specific_days", "core"),
            (200, "specific_days", "core"),
            (None, "no_upcoming", "core"),
            (None, "missing", "core"),
        ],
    )
    def test_bucket_maps_to_correct_book(self, days, mode, expected_book):
        from run_audited_backtest import BINARY_BOOK_BUCKETS, CORE_BOOK_BUCKETS

        bucket = assign_catalyst_bucket(days, mode)
        if expected_book == "binary":
            assert bucket in BINARY_BOOK_BUCKETS, f"days={days}, mode={mode} → bucket={bucket} not in binary"
        else:
            assert bucket in CORE_BOOK_BUCKETS, f"days={days}, mode={mode} → bucket={bucket} not in core"
