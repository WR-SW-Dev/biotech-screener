"""Integration tests for book-split (sleeve) in live portfolio.

Validates:
  1. SLEEVE_MAP covers all buckets
  2. SLEEVE_NAMES consistent with SLEEVE_MAP
  3. Sleeve allocation sums to 100%
  4. compare_sleeve_performance report structure
  5. Empty history cold start
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import BUCKET_NAMES, SLEEVE_MAP, SLEEVE_NAMES, compare_sleeve_performance

# ---------------------------------------------------------------------------
# Sleeve map invariants
# ---------------------------------------------------------------------------


class TestSleeveMap:

    def test_all_buckets_mapped(self):
        for b in BUCKET_NAMES:
            assert b in SLEEVE_MAP, f"Bucket {b} not in SLEEVE_MAP"

    def test_sleeve_names_correct(self):
        assert set(SLEEVE_MAP.values()) <= set(
            SLEEVE_NAMES
        ), f"SLEEVE_MAP values {set(SLEEVE_MAP.values())} not subset of SLEEVE_NAMES {set(SLEEVE_NAMES)}"
        assert set(SLEEVE_MAP.values()) == set(SLEEVE_NAMES), "SLEEVE_MAP values should cover all SLEEVE_NAMES"

    def test_sleeve_allocation_sums(self):
        """Binary + core bucket_targets should sum to 100%."""
        policy_path = PROJECT_ROOT / "production_data" / "portfolio_policy.json"
        if not policy_path.is_file():
            return  # skip if no policy file
        with open(policy_path) as f:
            policy = json.load(f)
        targets = policy.get("bucket_targets", {})
        binary_total = sum(targets.get(b, 0) for b in BUCKET_NAMES if SLEEVE_MAP[b] == "binary")
        core_total = sum(targets.get(b, 0) for b in BUCKET_NAMES if SLEEVE_MAP[b] == "core")
        assert abs(binary_total + core_total - 1.0) < 0.01, f"binary({binary_total}) + core({core_total}) != 1.0"


# ---------------------------------------------------------------------------
# Sleeve comparison
# ---------------------------------------------------------------------------


class TestSleeveComparison:

    def test_comparison_report_structure(self, tmp_path):
        """compare_sleeve_performance with real data returns valid schema."""
        perf_csv = tmp_path / "performance.csv"
        fieldnames = [
            "schema_version",
            "date",
            "prior_date",
            "total_pnl",
            "pnl_pct",
            "xbi_return_pct",
            "excess_vs_xbi_pct",
            "n_held",
            "turnover",
            "gap_risk_high_count",
            "n_missing_price",
            "sleeve_binary_0_30_pnl",
            "sleeve_binary_31_90_pnl",
            "sleeve_binary_91_180_pnl",
            "sleeve_less_binary_pnl",
            "sleeve_binary_book_pnl",
            "sleeve_binary_book_return_pct",
            "sleeve_core_book_pnl",
            "sleeve_core_book_return_pct",
            "sleeve_binary_book_turnover",
            "sleeve_core_book_turnover",
            "ruleset_id",
        ]
        with open(perf_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for i in range(5):
                writer.writerow(
                    {
                        "schema_version": "live_shadow_perf.v2",
                        "date": f"2026-02-{10+i*7:02d}",
                        "prior_date": f"2026-02-{3+i*7:02d}",
                        "total_pnl": str(100 + i * 50),
                        "pnl_pct": str(0.2 + i * 0.1),
                        "xbi_return_pct": str(0.1 + i * 0.05),
                        "excess_vs_xbi_pct": str(0.1 + i * 0.05),
                        "n_held": "30",
                        "turnover": "0.1",
                        "gap_risk_high_count": "0",
                        "n_missing_price": "0",
                        "sleeve_binary_0_30_pnl": str(10 + i),
                        "sleeve_binary_31_90_pnl": str(20 + i),
                        "sleeve_binary_91_180_pnl": str(50 + i * 3),
                        "sleeve_less_binary_pnl": str(20 + i),
                        "sleeve_binary_book_pnl": str(30 + i * 2),
                        "sleeve_binary_book_return_pct": str(0.3 + i * 0.1),
                        "sleeve_core_book_pnl": str(70 + i * 4),
                        "sleeve_core_book_return_pct": str(0.5 + i * 0.1),
                        "sleeve_binary_book_turnover": "0.1",
                        "sleeve_core_book_turnover": "0.05",
                        "ruleset_id": "test",
                    }
                )

        result = compare_sleeve_performance(perf_csv, trailing_weeks=4)
        assert result["schema"] == "sleeve_comparison.v1"
        assert "binary_book" in result
        assert "core_book" in result
        assert "combined_book_pnl" in result
        assert "portfolio_total_pnl" in result
        assert result["verdict"] == "tracking"
        assert result["weeks_used"] == 4

    def test_empty_history_returns_cold_start(self, tmp_path):
        perf_csv = tmp_path / "nonexistent.csv"
        result = compare_sleeve_performance(perf_csv)
        assert result["verdict"] == "cold_start"
