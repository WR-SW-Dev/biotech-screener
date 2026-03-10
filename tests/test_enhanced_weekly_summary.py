"""Tests for enhanced weekly summary sections.

Validates:
  1. Hit rate by bucket — correct counts and percentages
  2. Alpha leaders — top/bottom sorted correctly by excess_pnl
  3. Alpha leaders — bucket filter restricts results
  4. Signal diagnostics — catalyst_days average, gap-risk weight/usd
  5. Bucket movers — enter/exit detection via current vs prior tickers
  6. Integration — output .md has all new section headers
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import (  # noqa: E402
    _compute_alpha_leaders,
    _compute_hit_rate_by_bucket,
    _compute_signal_diagnostics,
    write_weekly_summary,
)


def _contrib(ticker, bucket, return_pct, pnl, dollars, excess_pnl=0.0):
    return {
        "ticker": ticker,
        "bucket": bucket,
        "return_pct": return_pct,
        "pnl": pnl,
        "dollars": dollars,
        "excess_pnl": excess_pnl,
    }


def _position(ticker, bucket, target_dollars, catalyst_days, gap_risk, weight_pct=5.0):
    return {
        "ticker": ticker,
        "bucket": bucket,
        "target_dollars": target_dollars,
        "catalyst_days": catalyst_days,
        "gap_risk": gap_risk,
        "weight_pct": weight_pct,
    }


# -------------------------------------------------------------------
# 1. Hit rate by bucket
# -------------------------------------------------------------------


class TestHitRateByBucket:
    def test_hit_rate_by_bucket(self):
        contribs = [
            _contrib("AAA", "binary_91_180", 5.0, 500, 10000),
            _contrib("BBB", "binary_91_180", -2.0, -200, 10000),
            _contrib("CCC", "binary_91_180", 3.0, 300, 10000),
            _contrib("DDD", "less_binary", -1.0, -50, 5000),
            _contrib("EEE", "less_binary", 1.5, 75, 5000),
        ]
        result = _compute_hit_rate_by_bucket(contribs)
        by_bucket = {r["bucket"]: r for r in result}

        b91 = by_bucket["binary_91_180"]
        assert b91["names"] == 3
        assert b91["positive"] == 2
        assert abs(b91["hit_rate"] - 66.67) < 0.1

        lb = by_bucket["less_binary"]
        assert lb["names"] == 2
        assert lb["positive"] == 1
        assert abs(lb["hit_rate"] - 50.0) < 0.1

        # Buckets with no contributors should be absent
        buckets_present = {r["bucket"] for r in result}
        assert "binary_0_30" not in buckets_present


# -------------------------------------------------------------------
# 2. Alpha leaders — overall
# -------------------------------------------------------------------


class TestAlphaLeadersOverall:
    def test_alpha_leaders_overall(self):
        contribs = [
            _contrib("A", "binary_91_180", 1, 10, 100, excess_pnl=50),
            _contrib("B", "binary_91_180", 2, 20, 100, excess_pnl=30),
            _contrib("C", "less_binary", -1, -10, 100, excess_pnl=-20),
            _contrib("D", "binary_0_30", 3, 30, 100, excess_pnl=80),
            _contrib("E", "binary_31_90", -2, -5, 100, excess_pnl=-50),
            _contrib("F", "less_binary", 0.5, 5, 100, excess_pnl=10),
            _contrib("G", "binary_91_180", -3, -30, 100, excess_pnl=-70),
        ]
        top, bottom = _compute_alpha_leaders(contribs, n=3)

        # Top 3 by excess_pnl descending: D(80), A(50), B(30)
        assert len(top) == 3
        assert [c["ticker"] for c in top] == ["D", "A", "B"]

        # Bottom 3 by excess_pnl ascending: G(-70), E(-50), C(-20)
        assert len(bottom) == 3
        assert [c["ticker"] for c in bottom] == ["G", "E", "C"]


# -------------------------------------------------------------------
# 3. Alpha leaders — bucket filter
# -------------------------------------------------------------------


class TestAlphaLeadersFiltered:
    def test_alpha_leaders_filtered(self):
        contribs = [
            _contrib("A", "binary_91_180", 1, 10, 100, excess_pnl=200),
            _contrib("B", "less_binary", 2, 20, 100, excess_pnl=900),
            _contrib("C", "binary_91_180", -1, -10, 100, excess_pnl=-30),
            _contrib("D", "binary_0_30", 3, 30, 100, excess_pnl=800),
            _contrib("E", "binary_91_180", 0.5, 5, 100, excess_pnl=50),
        ]
        top, bottom = _compute_alpha_leaders(
            contribs,
            n=5,
            bucket_filter="binary_91_180",
        )
        all_tickers = {c["ticker"] for c in top + bottom}
        # Only binary_91_180 tickers should appear
        assert all_tickers <= {"A", "C", "E"}
        assert "B" not in all_tickers
        assert "D" not in all_tickers

        # Top should be sorted by excess_pnl descending
        assert top[0]["ticker"] == "A"


# -------------------------------------------------------------------
# 4. Signal diagnostics
# -------------------------------------------------------------------


class TestSignalDiagnostics:
    def test_signal_diagnostics(self):
        positions = [
            _position("AAA", "binary_91_180", 10000, "45", "HIGH"),
            _position("BBB", "binary_91_180", 10000, "90", "LOW"),
            _position("CCC", "less_binary", 5000, "30", "HIGH"),
        ]
        prior = [
            _position("AAA", "binary_91_180", 10000, "50", "HIGH"),
            _position("DDD", "binary_0_30", 8000, "10", "LOW"),
        ]
        diag = _compute_signal_diagnostics(positions, prior)

        # avg_catalyst_days = (45+90+30)/3 = 55.0
        assert abs(diag["avg_catalyst_days"] - 55.0) < 0.1

        # gap HIGH: AAA(10000) + CCC(5000) = 15000 out of 25000 total = 60%
        assert abs(diag["gap_high_weight"] - 60.0) < 0.1
        assert abs(diag["gap_high_usd"] - 15000.0) < 0.01


# -------------------------------------------------------------------
# 5. Bucket movers
# -------------------------------------------------------------------


class TestBucketMovers:
    def test_bucket_movers(self):
        current = [
            _position("AAA", "binary_91_180", 10000, "45", "LOW"),
            _position("BBB", "binary_91_180", 10000, "90", "LOW"),
            _position("CCC", "less_binary", 5000, "30", "LOW"),
        ]
        prior = [
            _position("AAA", "binary_91_180", 10000, "50", "LOW"),
            _position("DDD", "binary_0_30", 8000, "10", "LOW"),
            _position("EEE", "binary_31_90", 6000, "20", "LOW"),
        ]
        diag = _compute_signal_diagnostics(current, prior)

        # Entered: BBB, CCC (in current but not prior)
        assert diag["bucket_movers_in"] == 2
        # Exited: DDD, EEE (in prior but not current)
        assert diag["bucket_movers_out"] == 2


# -------------------------------------------------------------------
# 6. Integration — weekly summary .md contains new section headers
# -------------------------------------------------------------------


class TestWeeklySummaryContainsNewSections:
    def test_weekly_summary_contains_new_sections(self, tmp_path):
        positions = [
            {
                "ticker": "AAA",
                "bucket": "binary_91_180",
                "actionable_rank": 1,
                "target_dollars": 15000,
                "catalyst_days": "90",
                "gap_risk": "",
                "weight_pct": 3.0,
            },
            {
                "ticker": "BBB",
                "bucket": "less_binary",
                "actionable_rank": 5,
                "target_dollars": 10000,
                "catalyst_days": "",
                "gap_risk": "HIGH",
                "weight_pct": 2.0,
            },
        ]
        positions_data = {
            "positions": positions,
            "summary": {
                "total_allocated": 25000,
                "residual_cash": 475000,
                "per_bucket": {
                    "binary_91_180": {
                        "count": 1,
                        "total_dollars": 15000,
                        "weight_pct": 3.0,
                    },
                    "less_binary": {
                        "count": 1,
                        "total_dollars": 10000,
                        "weight_pct": 2.0,
                    },
                },
                "gap_risk_high": ["BBB"],
                "missing_price": [],
            },
        }
        contributors = [
            _contrib("AAA", "binary_91_180", 2.67, 400, 15000, excess_pnl=250),
            _contrib("BBB", "less_binary", 1.0, 100, 10000, excess_pnl=0),
        ]
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
            "contributors": contributors,
        }
        policy = {
            "account_usd": 500000,
            "bucket_targets": {
                "binary_0_30": 0.10,
                "binary_31_90": 0.25,
                "binary_91_180": 0.55,
                "less_binary": 0.10,
            },
        }
        metadata = {"ruleset_id": "test_rs_001"}

        out_path = tmp_path / "weekly_summary.md"
        write_weekly_summary(
            "2026-03-09",
            positions_data,
            perf,
            policy,
            metadata,
            out_path,
        )

        text = out_path.read_text()
        assert "## Hit Rate by Bucket" in text
        assert "## Alpha Leaders" in text
        assert "## Signal Diagnostics" in text
