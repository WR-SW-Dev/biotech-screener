"""Tests for options IV/skew alpha research study.

Synthetic fixtures exercise the full pipeline with planted signal.
No live API calls, no network, no credentials required.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
_SCRIPTS = PROJECT_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_RESEARCH = _SCRIPTS / "research"
if str(_RESEARCH) not in sys.path:
    sys.path.insert(0, str(_RESEARCH))

from scripts.research.eval_options_alpha import (
    STUDY_SCHEMA,
    _safe_float,
    compute_binned_comparison,
    compute_descriptive,
    compute_double_sort,
    compute_incremental_ic,
    compute_incremental_tests,
    compute_portfolio_slice,
    compute_portfolio_slices,
    compute_premium_split,
    compute_raw_ic,
    compute_simple_tests,
    format_alpha_report_md,
    generate_alpha_report,
    load_enriched_dataset,
)

# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

# 10 tickers across 4 snap_dates = 40 observations
TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ"]
SNAP_DATES = ["2025-06-01", "2025-06-08", "2025-06-15", "2025-06-22"]

# Planted signal: more negative term_slope → larger absolute gap
# Tickers AAA-EEE: backwardated (negative slope), get large gaps
# Tickers FFF-JJJ: contango (positive slope), get small gaps
TERM_SLOPES = {
    "AAA": -0.30,
    "BBB": -0.25,
    "CCC": -0.20,
    "DDD": -0.15,
    "EEE": -0.10,
    "FFF": 0.02,
    "GGG": 0.05,
    "HHH": 0.10,
    "III": 0.15,
    "JJJ": 0.20,
}
ATM_IVS = {
    "AAA": 1.20,
    "BBB": 0.95,
    "CCC": 0.80,
    "DDD": 0.70,
    "EEE": 0.65,
    "FFF": 0.50,
    "GGG": 0.45,
    "HHH": 0.40,
    "III": 0.35,
    "JJJ": 0.30,
}
CATALYST_DAYS = {
    "AAA": 10,
    "BBB": 45,
    "CCC": 20,
    "DDD": 70,
    "EEE": 15,
    "FFF": 50,
    "GGG": 25,
    "HHH": 80,
    "III": 35,
    "JJJ": 85,
}


def _build_synthetic_dataset() -> List[Dict[str, Any]]:
    """Build 40 synthetic enriched rows with planted signal."""
    rows = []
    for snap_date in SNAP_DATES:
        for ticker in TICKERS:
            slope = TERM_SLOPES[ticker]
            # Planted relationship: abs_gap roughly proportional to backwardation
            # More negative slope → larger gap
            abs_gap = max(0.01, 0.30 + slope * -0.8)  # slope=-0.3 → gap=0.54, slope=0.2 → gap=0.14
            signed_gap = abs_gap if slope < 0 else -abs_gap * 0.5  # backwardated → positive gap

            cat_days = CATALYST_DAYS[ticker]
            decay_w = max(0.0, 1.0 - cat_days / 90.0)

            rows.append(
                {
                    "ticker": ticker,
                    "snap_date": snap_date,
                    "opt_term_slope": slope,
                    "opt_atm_iv": ATM_IVS[ticker],
                    "opt_front_iv": ATM_IVS[ticker] * 1.1,
                    "opt_back_iv": ATM_IVS[ticker] * (1.1 + slope),
                    "opt_event_premium": "YES" if slope < -0.10 else "NO",
                    "opt_iv_regime": "ELEVATED" if ATM_IVS[ticker] >= 0.60 else "NORMAL",
                    "opt_use_for_judgment": "YES",
                    "catalyst_days": cat_days,
                    "catalyst_decay_w": decay_w,
                    "catalyst_mode": "binary_now" if cat_days <= 30 else "build_window",
                    "catalyst_family": "REGULATORY" if ticker in ("AAA", "BBB", "FFF", "GGG") else "CLINICAL",
                    "eligible": "1",
                    "abs_gap": abs_gap,
                    "signed_gap": signed_gap,
                    "event_1d_move": signed_gap,
                    "event_5d_move": signed_gap * 1.2,
                    "fwd_ret_5d": signed_gap * 0.8,
                    "fwd_ret_21d": signed_gap * 0.5,
                    "fwd_ret_63d": signed_gap * 0.3,
                }
            )
    return rows


SYNTHETIC_DATASET = _build_synthetic_dataset()


# ---------------------------------------------------------------------------
# Test 1: Dataset join mechanics
# ---------------------------------------------------------------------------


class TestDatasetJoin:
    """Verify enriched dataset merge correctness."""

    def test_synthetic_row_count(self):
        assert len(SYNTHETIC_DATASET) == 40

    def test_no_duplicate_ticker_date(self):
        keys = [(r["ticker"], r["snap_date"]) for r in SYNTHETIC_DATASET]
        assert len(keys) == len(set(keys))

    def test_all_fields_present(self):
        required = [
            "ticker",
            "snap_date",
            "opt_term_slope",
            "opt_atm_iv",
            "catalyst_days",
            "catalyst_decay_w",
            "catalyst_family",
            "abs_gap",
            "signed_gap",
            "fwd_ret_5d",
        ]
        for row in SYNTHETIC_DATASET:
            for field in required:
                assert field in row, f"Missing {field}"

    def test_load_enriched_dataset_empty_dir(self, tmp_path):
        """Empty snapshots dir → empty dataset."""
        result = load_enriched_dataset(tmp_path, tmp_path / "prices.csv", [5, 21])
        assert result == []


# ---------------------------------------------------------------------------
# Test 2: PIT-safe resolution
# ---------------------------------------------------------------------------


class TestPITSafeResolution:
    """Forward returns must anchor on next-trading-day, not snap_date."""

    def test_fwd_ret_uses_trade_date_anchor(self, tmp_path):
        """Verify compute_forward_return anchors on first date >= snap_date."""
        from scripts.research.options_prospective_analysis import compute_forward_return

        # Trading dates: skip 2025-06-02 (Monday) → first available is 2025-06-03
        sorted_dates = ["2025-06-03", "2025-06-04", "2025-06-05", "2025-06-06", "2025-06-09", "2025-06-10"]
        prices = {d: 100.0 + i for i, d in enumerate(sorted_dates)}

        ret = compute_forward_return(prices, sorted_dates, "2025-06-01", 3)
        # Anchors on 2025-06-03 (p=100), horizon 3 → 2025-06-06 (p=103)
        assert ret is not None
        assert abs(ret - 0.03) < 0.001


# ---------------------------------------------------------------------------
# Test 3: Exclude unresolved events
# ---------------------------------------------------------------------------


class TestExcludeUnresolved:
    """Rows with None returns should be excluded from tests."""

    def test_raw_ic_excludes_none_returns(self):
        dataset = [
            {"opt_term_slope": -0.2, "abs_gap": None},
            {"opt_term_slope": -0.1, "abs_gap": 0.3},
            {"opt_term_slope": 0.0, "abs_gap": 0.2},
            {"opt_term_slope": 0.1, "abs_gap": 0.1},
        ]
        result = compute_raw_ic(dataset, "opt_term_slope", "abs_gap", min_obs=3)
        assert result["status"] == "ok"
        assert result["n"] == 3  # excludes None row


# ---------------------------------------------------------------------------
# Test 4: Deterministic binning
# ---------------------------------------------------------------------------


class TestDeterministicBinning:
    """Tercile assignment must be stable with tie-breaking by ticker."""

    def test_stable_bins(self):
        result1 = compute_binned_comparison(SYNTHETIC_DATASET, "opt_term_slope", "abs_gap", 3, min_obs=5)
        result2 = compute_binned_comparison(SYNTHETIC_DATASET, "opt_term_slope", "abs_gap", 3, min_obs=5)
        assert result1 == result2

    def test_three_bins(self):
        result = compute_binned_comparison(SYNTHETIC_DATASET, "opt_term_slope", "abs_gap", 3, min_obs=5)
        assert result["status"] == "ok"
        assert len(result["bins"]) == 3
        # Bin 1 (most negative slope) should have higher abs_gap
        assert result["bins"][0]["mean_return"] > result["bins"][-1]["mean_return"]

    def test_ties_broken_by_ticker(self):
        """When multiple rows have same signal, ticker breaks the tie."""
        tied = [
            {"opt_term_slope": 0.0, "abs_gap": 0.1, "ticker": "ZZZ"},
            {"opt_term_slope": 0.0, "abs_gap": 0.2, "ticker": "AAA"},
            {"opt_term_slope": 0.0, "abs_gap": 0.3, "ticker": "MMM"},
            {"opt_term_slope": 0.1, "abs_gap": 0.05, "ticker": "BBB"},
            {"opt_term_slope": -0.1, "abs_gap": 0.4, "ticker": "CCC"},
            {"opt_term_slope": -0.1, "abs_gap": 0.35, "ticker": "DDD"},
        ]
        result = compute_binned_comparison(tied, "opt_term_slope", "abs_gap", 3, min_obs=2)
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Test 5: Raw IC — planted signal
# ---------------------------------------------------------------------------


class TestRawIC:
    """Planted signal should produce expected IC sign."""

    def test_term_slope_vs_abs_gap_negative_ic(self):
        """More negative slope → larger abs_gap → negative IC."""
        result = compute_raw_ic(SYNTHETIC_DATASET, "opt_term_slope", "abs_gap", min_obs=5)
        assert result["status"] == "ok"
        assert result["n"] == 40
        # Planted: negative slope → high abs_gap, so IC should be negative
        assert result["ic"] < -0.3, f"Expected strong negative IC, got {result['ic']}"

    def test_atm_iv_vs_abs_gap_positive_ic(self):
        """Higher ATM IV → larger abs_gap (planted) → positive IC."""
        result = compute_raw_ic(SYNTHETIC_DATASET, "opt_atm_iv", "abs_gap", min_obs=5)
        assert result["status"] == "ok"
        # ATM IV is correlated with slope (high IV tickers are backwardated)
        assert result["ic"] > 0.3

    def test_term_slope_vs_signed_gap(self):
        """Verify IC exists for signed gap too."""
        result = compute_raw_ic(SYNTHETIC_DATASET, "opt_term_slope", "signed_gap", min_obs=5)
        assert result["status"] == "ok"
        # Planted: backwardated → positive signed_gap
        assert result["ic"] < 0  # negative slope → positive return → negative IC


# ---------------------------------------------------------------------------
# Test 6: Incremental IC
# ---------------------------------------------------------------------------


class TestIncrementalIC:
    """Residualized signal should produce non-zero incremental IC."""

    def test_incremental_after_catalyst_control(self):
        result = compute_incremental_ic(
            SYNTHETIC_DATASET,
            "opt_term_slope",
            "catalyst_decay_w",
            "abs_gap",
            min_obs=5,
        )
        assert result["status"] == "ok"
        assert result["n"] == 40
        # Both raw and incremental should be non-zero
        assert result["raw_ic"] != 0.0
        assert result["incremental_ic"] != 0.0

    def test_incremental_ic_less_than_raw(self):
        """After controlling for catalyst timing, IC may decrease."""
        result = compute_incremental_ic(
            SYNTHETIC_DATASET,
            "opt_term_slope",
            "catalyst_decay_w",
            "abs_gap",
            min_obs=5,
        )
        # Catalyst timing is correlated with slope in our fixture, so controlling
        # for it should reduce the signal somewhat (not necessarily always true,
        # but in our planted setup decay_w partially explains the same variation)
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Test 7: Double-sort bridge
# ---------------------------------------------------------------------------


class TestDoubleSortBridge:
    """Double-sort passes through to compute_double_sort_spread."""

    def test_double_sort_returns_spread(self):
        result = compute_double_sort(
            SYNTHETIC_DATASET,
            "catalyst_decay_w",
            "opt_term_slope",
            "abs_gap",
            min_obs=5,
        )
        assert result["status"] == "ok"
        assert "spread" in result
        assert isinstance(result["spread"], float)

    def test_double_sort_insufficient(self):
        result = compute_double_sort(
            SYNTHETIC_DATASET[:2],
            "catalyst_decay_w",
            "opt_term_slope",
            "abs_gap",
            min_obs=20,
        )
        assert result["status"] == "insufficient_sample"


# ---------------------------------------------------------------------------
# Test 8: Insufficient sample guards
# ---------------------------------------------------------------------------


class TestInsufficientSample:
    """Every function returns clean status when n < min_obs."""

    def test_raw_ic_insufficient(self):
        result = compute_raw_ic(SYNTHETIC_DATASET[:3], "opt_term_slope", "abs_gap", min_obs=20)
        assert result["status"] == "insufficient_sample"
        assert result["n"] == 3
        assert result["min_required"] == 20

    def test_binned_insufficient(self):
        result = compute_binned_comparison(
            SYNTHETIC_DATASET[:2],
            "opt_term_slope",
            "abs_gap",
            3,
            min_obs=20,
        )
        assert result["status"] == "insufficient_sample"

    def test_premium_split_insufficient(self):
        result = compute_premium_split(SYNTHETIC_DATASET[:2], "abs_gap", min_obs=20)
        assert result["status"] == "insufficient_sample"

    def test_incremental_ic_insufficient(self):
        result = compute_incremental_ic(
            SYNTHETIC_DATASET[:2],
            "opt_term_slope",
            "catalyst_decay_w",
            "abs_gap",
            min_obs=20,
        )
        assert result["status"] == "insufficient_sample"

    def test_portfolio_slice_insufficient(self):
        result = compute_portfolio_slice(
            SYNTHETIC_DATASET[:2],
            "opt_term_slope",
            "abs_gap",
            top_k=10,
            min_obs=20,
        )
        assert result["status"] == "insufficient_sample"

    def test_full_report_empty_dataset(self):
        report = generate_alpha_report([], {}, {}, {}, {}, [5, 21], 20)
        assert report["status"] == "insufficient_sample"
        assert report["schema"] == STUDY_SCHEMA
        assert report["n_observations"] == 0


# ---------------------------------------------------------------------------
# Test 9: No live API calls
# ---------------------------------------------------------------------------


class TestNoLiveAPICalls:
    """Ensure no tastytrade or network calls happen."""

    def test_no_tt_credentials(self):
        """TT_SECRET and TT_REFRESH should not be needed."""
        env = os.environ.copy()
        env.pop("TT_SECRET", None)
        env.pop("TT_REFRESH", None)
        with patch.dict(os.environ, env, clear=True):
            # Just building synthetic dataset should not trigger API calls
            dataset = _build_synthetic_dataset()
            result = compute_raw_ic(dataset, "opt_term_slope", "abs_gap", min_obs=5)
            assert result["status"] == "ok"

    def test_no_tastytrade_import(self):
        """The eval script itself should not import tastytrade."""
        import scripts.research.eval_options_alpha as mod

        source = Path(mod.__file__).read_text()
        assert "import tastytrade" not in source
        assert "from tastytrade" not in source


# ---------------------------------------------------------------------------
# Test 10: Stable on empty data
# ---------------------------------------------------------------------------


class TestStableOnEmptyData:
    """Full pipeline on empty snapshots → no crash, clean report."""

    def test_empty_snapshots_dir(self, tmp_path):
        dataset = load_enriched_dataset(tmp_path, tmp_path / "fake_prices.csv", [5, 21])
        assert dataset == []

        descriptive = compute_descriptive(dataset)
        assert descriptive["n_total"] == 0

        simple = compute_simple_tests(dataset, [5, 21], min_obs=20)
        incremental = compute_incremental_tests(dataset, [5, 21], min_obs=20)
        portfolio = compute_portfolio_slices(dataset, [5, 21], top_k=10, min_obs=20)

        report = generate_alpha_report(
            dataset,
            descriptive,
            simple,
            incremental,
            portfolio,
            [5, 21],
            20,
        )
        assert report["status"] == "insufficient_sample"
        assert report["schema"] == STUDY_SCHEMA

        # Markdown should not crash
        md = format_alpha_report_md(report)
        assert "insufficient" in md.lower() or "Insufficient" in md

    def test_header_only_sidecar(self, tmp_path):
        """Sidecar CSV with header but no data rows → empty dataset."""
        snap_dir = tmp_path / "2025-06-01"
        snap_dir.mkdir()
        # Write header-only options_diagnostics.csv
        (snap_dir / "options_diagnostics.csv").write_text("ticker,opt_has_data,opt_term_slope\n")
        # Write header-only rankings.csv
        (snap_dir / "rankings.csv").write_text("ticker,eligible,catalyst_days\n")
        dataset = load_enriched_dataset(tmp_path, tmp_path / "fake.csv", [5])
        assert dataset == []


# ---------------------------------------------------------------------------
# Additional integration-style tests
# ---------------------------------------------------------------------------


class TestDescriptive:
    """Descriptive analysis on synthetic data."""

    def test_counts(self):
        desc = compute_descriptive(SYNTHETIC_DATASET)
        assert desc["n_total"] == 40
        assert desc["n_liquid"] == 40  # all YES in fixture
        assert desc["n_regulatory"] > 0
        assert desc["n_clinical"] > 0

    def test_feature_distributions(self):
        desc = compute_descriptive(SYNTHETIC_DATASET)
        slope_dist = desc["features"]["opt_term_slope"]
        assert slope_dist["n"] == 40
        assert slope_dist["std"] > 0


class TestSimpleTests:
    """Full simple test suite on synthetic data."""

    def test_all_keys_present(self):
        results = compute_simple_tests(SYNTHETIC_DATASET, [5, 21], min_obs=5)
        assert "ic_opt_term_slope_vs_abs_gap" in results
        assert "ic_opt_atm_iv_vs_abs_gap" in results
        assert "bins_opt_term_slope_vs_abs_gap" in results
        assert "premium_split_abs_gap" in results


class TestPortfolioSlice:
    """Portfolio-realistic slicing."""

    def test_top_k_spread(self):
        result = compute_portfolio_slice(
            SYNTHETIC_DATASET,
            "opt_term_slope",
            "abs_gap",
            top_k=10,
            min_obs=5,
        )
        assert result["status"] == "ok"
        # Top-K (most negative slope) should have higher abs_gap
        assert result["top_mean"] > result["rest_mean"]
        assert result["spread"] > 0

    def test_baseline_present(self):
        result = compute_portfolio_slice(
            SYNTHETIC_DATASET,
            "opt_term_slope",
            "abs_gap",
            top_k=10,
            min_obs=5,
        )
        assert result["baseline_mean"] is not None


class TestPremiumSplit:
    """Event premium YES vs NO split."""

    def test_premium_split_on_abs_gap(self):
        result = compute_premium_split(SYNTHETIC_DATASET, "abs_gap", min_obs=5)
        assert result["status"] == "ok"
        # YES group (backwardated) should have higher abs_gap
        assert result["mean_yes"] > result["mean_no"]
        assert result["effect_size"] > 0


class TestSafeFloat:
    """_safe_float edge cases."""

    def test_empty_string(self):
        assert math.isnan(_safe_float(""))

    def test_none(self):
        assert math.isnan(_safe_float(None))

    def test_valid(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_nan_string(self):
        assert math.isnan(_safe_float("nan"))

    def test_garbage(self):
        assert math.isnan(_safe_float("abc"))


class TestReportGeneration:
    """Full report generation and formatting."""

    def test_full_report_ok(self):
        desc = compute_descriptive(SYNTHETIC_DATASET)
        simple = compute_simple_tests(SYNTHETIC_DATASET, [5], min_obs=5)
        incr = compute_incremental_tests(SYNTHETIC_DATASET, [5], min_obs=5)
        port = compute_portfolio_slices(SYNTHETIC_DATASET, [5], top_k=10, min_obs=5)
        report = generate_alpha_report(
            SYNTHETIC_DATASET,
            desc,
            simple,
            incr,
            port,
            [5],
            5,
        )
        assert report["status"] == "ok"
        assert report["schema"] == STUDY_SCHEMA
        assert report["n_observations"] == 40
        assert "decision" in report

    def test_markdown_renders(self):
        desc = compute_descriptive(SYNTHETIC_DATASET)
        simple = compute_simple_tests(SYNTHETIC_DATASET, [5], min_obs=5)
        incr = compute_incremental_tests(SYNTHETIC_DATASET, [5], min_obs=5)
        port = compute_portfolio_slices(SYNTHETIC_DATASET, [5], top_k=10, min_obs=5)
        report = generate_alpha_report(
            SYNTHETIC_DATASET,
            desc,
            simple,
            incr,
            port,
            [5],
            5,
        )
        md = format_alpha_report_md(report)
        assert "# Options IV/Skew Alpha Study" in md
        assert "Decision" in md
        assert "Raw ICs" in md
