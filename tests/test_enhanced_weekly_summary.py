"""Tests for enhanced weekly summary sections.

Validates:
  1. Hit rate by bucket — correct counts and percentages
  2. Alpha leaders — top/bottom 5 sorted correctly
  3. Alpha leaders — bucket filter works
  4. Signal diagnostics — catalyst_days average, gap-risk weight
  5. Bucket movers — enter/exit detection
  6. Integration — output .md has all new headers
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import _compute_alpha_leaders, _compute_hit_rate_by_bucket, _compute_signal_diagnostics


def _make_contributors():
    return [
        {
            "ticker": "AAPL",
            "bucket": "binary_91_180",
            "return_pct": 5.0,
            "pnl": 500,
            "excess_pnl": 200,
            "dollars": 10000,
        },
        {
            "ticker": "GOOG",
            "bucket": "binary_91_180",
            "return_pct": -2.0,
            "pnl": -200,
            "excess_pnl": -400,
            "dollars": 10000,
        },
        {
            "ticker": "AMGN",
            "bucket": "binary_91_180",
            "return_pct": 3.0,
            "pnl": 300,
            "excess_pnl": 100,
            "dollars": 10000,
        },
        {"ticker": "BIIB", "bucket": "less_binary", "return_pct": 1.0, "pnl": 50, "excess_pnl": -50, "dollars": 5000},
        {
            "ticker": "REGN",
            "bucket": "less_binary",
            "return_pct": -4.0,
            "pnl": -200,
            "excess_pnl": -300,
            "dollars": 5000,
        },
        {"ticker": "VRTX", "bucket": "binary_31_90", "return_pct": 8.0, "pnl": 400, "excess_pnl": 300, "dollars": 5000},
        {
            "ticker": "ALNY",
            "bucket": "binary_0_30",
            "return_pct": -10.0,
            "pnl": -500,
            "excess_pnl": -600,
            "dollars": 5000,
        },
    ]


class TestHitRateByBucket:
    def test_correct_counts(self):
        contribs = _make_contributors()
        result = _compute_hit_rate_by_bucket(contribs)
        by_bucket = {r["bucket"]: r for r in result}
        # binary_91_180: AAPL(+), GOOG(-), AMGN(+) → 2/3
        b91 = by_bucket["binary_91_180"]
        assert b91["names"] == 3
        assert b91["positive"] == 2
        assert abs(b91["hit_rate"] - 66.67) < 0.1

    def test_empty_bucket_excluded(self):
        contribs = [{"ticker": "AAPL", "bucket": "binary_91_180", "return_pct": 5.0, "pnl": 500}]
        result = _compute_hit_rate_by_bucket(contribs)
        buckets = [r["bucket"] for r in result]
        assert "less_binary" not in buckets


class TestAlphaLeaders:
    def test_overall(self):
        contribs = _make_contributors()
        top, bottom = _compute_alpha_leaders(contribs, n=3)
        # Top by excess_pnl: VRTX(300), AAPL(200), AMGN(100)
        assert [c["ticker"] for c in top] == ["VRTX", "AAPL", "AMGN"]
        # Bottom: ALNY(-600), GOOG(-400), REGN(-300)
        assert [c["ticker"] for c in bottom] == ["ALNY", "GOOG", "REGN"]

    def test_filtered(self):
        contribs = _make_contributors()
        top, bottom = _compute_alpha_leaders(contribs, n=2, bucket_filter="binary_91_180")
        # Only binary_91_180: AAPL(200), AMGN(100), GOOG(-400)
        assert len(top) == 2
        assert top[0]["ticker"] == "AAPL"
        assert bottom[0]["ticker"] == "GOOG"


class TestSignalDiagnostics:
    def test_catalyst_days_and_gap_risk(self):
        positions = [
            {
                "ticker": "AAPL",
                "catalyst_days": "90",
                "gap_risk": "HIGH",
                "target_dollars": 10000,
                "bucket": "binary_91_180",
            },
            {
                "ticker": "GOOG",
                "catalyst_days": "120",
                "gap_risk": "",
                "target_dollars": 10000,
                "bucket": "binary_91_180",
            },
            {
                "ticker": "BIIB",
                "catalyst_days": "",
                "gap_risk": "HIGH",
                "target_dollars": 5000,
                "bucket": "less_binary",
            },
        ]
        prior = [
            {"ticker": "AAPL", "bucket": "binary_91_180"},
            {"ticker": "REGN", "bucket": "less_binary"},
        ]
        result = _compute_signal_diagnostics(positions, prior)
        assert abs(result["avg_catalyst_days"] - 105.0) < 0.1  # (90+120)/2
        assert result["gap_high_weight"] > 0
        assert result["gap_high_usd"] == 15000  # 10000+5000

    def test_bucket_movers(self):
        positions = [
            {"ticker": "AAPL", "bucket": "binary_91_180"},
            {"ticker": "NEW1", "bucket": "binary_31_90"},
        ]
        prior = [
            {"ticker": "AAPL", "bucket": "binary_91_180"},
            {"ticker": "OLD1", "bucket": "less_binary"},
        ]
        result = _compute_signal_diagnostics(positions, prior)
        assert result["bucket_movers_in"] == 1  # NEW1 entered
        assert result["bucket_movers_out"] == 1  # OLD1 exited


class TestWeeklySummaryIntegration:
    def test_new_sections_present(self, tmp_path):
        from tools.live_shadow_portfolio import write_weekly_summary

        positions_data = {
            "positions": [
                {
                    "ticker": "AAPL",
                    "bucket": "binary_91_180",
                    "actionable_rank": 1,
                    "weight_pct": 3.0,
                    "target_dollars": 15000,
                    "gap_risk": "",
                    "catalyst_days": "90",
                    "catalyst_mode": "specific_days",
                },
                {
                    "ticker": "GOOG",
                    "bucket": "less_binary",
                    "actionable_rank": 5,
                    "weight_pct": 2.0,
                    "target_dollars": 10000,
                    "gap_risk": "HIGH",
                    "catalyst_days": "",
                    "catalyst_mode": "",
                },
            ],
            "summary": {
                "total_positions": 2,
                "total_allocated": 25000,
                "residual_cash": 475000,
                "per_bucket": {
                    "binary_0_30": {"count": 0, "total_dollars": 0, "weight_pct": 0},
                    "binary_31_90": {"count": 0, "total_dollars": 0, "weight_pct": 0},
                    "binary_91_180": {"count": 1, "total_dollars": 15000, "weight_pct": 3.0},
                    "less_binary": {"count": 1, "total_dollars": 10000, "weight_pct": 2.0},
                },
                "gap_risk_high": ["GOOG"],
                "missing_price": [],
            },
        }
        perf = {
            "prior_date": "2026-03-01",
            "total_pnl": 500,
            "pnl_pct": 2.0,
            "xbi_return_pct": 1.0,
            "excess_vs_xbi_pct": 1.0,
            "turnover": 0.1,
            "sleeve_attribution": {
                "binary_0_30": {"pnl": 0, "return_pct": 0, "weight": 0},
                "binary_31_90": {"pnl": 0, "return_pct": 0, "weight": 0},
                "binary_91_180": {
                    "pnl": 400,
                    "return_pct": 2.67,
                    "weight": 15000,
                    "excess_vs_xbi_pct": 1.67,
                    "excess_pnl": 250,
                },
                "less_binary": {
                    "pnl": 100,
                    "return_pct": 1.0,
                    "weight": 10000,
                    "excess_vs_xbi_pct": 0.0,
                    "excess_pnl": 0,
                },
            },
            "contributors": [
                {
                    "ticker": "AAPL",
                    "bucket": "binary_91_180",
                    "dollars": 15000,
                    "return_pct": 2.67,
                    "pnl": 400,
                    "excess_vs_xbi_pct": 1.67,
                    "excess_pnl": 250,
                },
                {
                    "ticker": "GOOG",
                    "bucket": "less_binary",
                    "dollars": 10000,
                    "return_pct": 1.0,
                    "pnl": 100,
                    "excess_vs_xbi_pct": 0.0,
                    "excess_pnl": 0,
                },
            ],
        }
        policy = {
            "account_usd": 500000,
            "bucket_targets": {"binary_0_30": 0.10, "binary_31_90": 0.25, "binary_91_180": 0.55, "less_binary": 0.10},
        }
        metadata = {"ruleset_id": "test123"}

        out_path = tmp_path / "weekly_summary.md"
        write_weekly_summary("2026-03-08", positions_data, perf, policy, metadata, out_path)

        text = out_path.read_text()
        assert "## Hit Rate by Bucket" in text
        assert "## Alpha Leaders" in text
        assert "## Signal Diagnostics" in text
