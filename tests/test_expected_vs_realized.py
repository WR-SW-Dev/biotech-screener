"""Tests for expected vs realized diagnostics in live_shadow_portfolio.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import _compute_expected_vs_realized, _write_diagnostics_json


def _make_positions_and_contributors():
    """Build matching positions + contributors for testing."""
    positions = [
        {
            "ticker": "AAA",
            "bucket": "binary_91_180",
            "tier": "A",
            "mom_state": "tailwind",
            "catalyst_days": "60",
            "gap_risk": "HIGH",
            "actionable_rank": 1,
            "target_dollars": 15000.0,
            "weight_pct": 3.0,
        },
        {
            "ticker": "BBB",
            "bucket": "binary_91_180",
            "tier": "A",
            "mom_state": "neutral",
            "catalyst_days": "120",
            "gap_risk": "",
            "actionable_rank": 2,
            "target_dollars": 12000.0,
            "weight_pct": 2.4,
        },
        {
            "ticker": "CCC",
            "bucket": "less_binary",
            "tier": "B",
            "mom_state": "headwind",
            "catalyst_days": "200",
            "gap_risk": "",
            "actionable_rank": 5,
            "target_dollars": 8000.0,
            "weight_pct": 1.6,
        },
        {
            "ticker": "DDD",
            "bucket": "binary_31_90",
            "tier": "B",
            "mom_state": "tailwind",
            "catalyst_days": "45",
            "gap_risk": "HIGH",
            "actionable_rank": 3,
            "target_dollars": 10000.0,
            "weight_pct": 2.0,
        },
    ]
    contributors = [
        {
            "ticker": "AAA",
            "bucket": "binary_91_180",
            "dollars": 15000.0,
            "return_pct": 5.0,
            "pnl": 750.0,
            "excess_pnl": 500.0,
        },
        {
            "ticker": "BBB",
            "bucket": "binary_91_180",
            "dollars": 12000.0,
            "return_pct": -2.0,
            "pnl": -240.0,
            "excess_pnl": -400.0,
        },
        {
            "ticker": "CCC",
            "bucket": "less_binary",
            "dollars": 8000.0,
            "return_pct": 1.0,
            "pnl": 80.0,
            "excess_pnl": 20.0,
        },
        {
            "ticker": "DDD",
            "bucket": "binary_31_90",
            "dollars": 10000.0,
            "return_pct": 3.0,
            "pnl": 300.0,
            "excess_pnl": 150.0,
        },
    ]
    return positions, contributors


class TestByBucketReturns:
    def test_bucket_grouping(self):
        positions, contributors = _make_positions_and_contributors()
        result = _compute_expected_vs_realized(positions, contributors)
        by_bucket = result["by_bucket"]

        # binary_91_180 has AAA (+5%) and BBB (-2%) → mean = 1.5%, hit = 50%
        b91 = by_bucket["binary_91_180"]
        assert b91["n"] == 2
        assert abs(b91["mean_return_pct"] - 1.5) < 0.01
        assert abs(b91["hit_rate"] - 0.5) < 0.01

        # less_binary has CCC (+1%) → hit = 100%
        lb = by_bucket["less_binary"]
        assert lb["n"] == 1
        assert lb["hit_rate"] == 1.0


class TestByTier:
    def test_tier_grouping(self):
        positions, contributors = _make_positions_and_contributors()
        result = _compute_expected_vs_realized(positions, contributors)
        by_tier = result["by_tier"]

        # A-tier: AAA (+5%) and BBB (-2%) → mean = 1.5%
        assert by_tier["A"]["n"] == 2
        assert abs(by_tier["A"]["mean_return_pct"] - 1.5) < 0.01

        # B-tier: CCC (+1%) and DDD (+3%) → mean = 2.0%
        assert by_tier["B"]["n"] == 2
        assert abs(by_tier["B"]["mean_return_pct"] - 2.0) < 0.01


class TestByMomentum:
    def test_momentum_grouping(self):
        positions, contributors = _make_positions_and_contributors()
        result = _compute_expected_vs_realized(positions, contributors)
        by_mom = result["by_momentum"]

        # tailwind: AAA (+5%) and DDD (+3%) → mean = 4.0%
        assert by_mom["tailwind"]["n"] == 2
        assert abs(by_mom["tailwind"]["mean_return_pct"] - 4.0) < 0.01

        # headwind: CCC (+1%)
        assert by_mom["headwind"]["n"] == 1


class TestByCatalystProximity:
    def test_proximity_bands(self):
        positions, contributors = _make_positions_and_contributors()
        result = _compute_expected_vs_realized(positions, contributors)
        by_prox = result["by_catalyst_proximity"]

        # near (<=90): AAA (60d) and DDD (45d)
        assert by_prox["near"]["n"] == 2
        # mid (91-180): BBB (120d)
        assert by_prox["mid"]["n"] == 1
        # far (>180): CCC (200d)
        assert by_prox["far"]["n"] == 1


class TestTop5Gap:
    def test_gap_computation(self):
        positions, contributors = _make_positions_and_contributors()
        result = _compute_expected_vs_realized(positions, contributors)
        top5 = result["top5_gap"]

        assert len(top5) <= 5
        assert all("ticker" in g and "gap" in g for g in top5)
        # Sorted by gap descending
        gaps = [g["gap"] for g in top5]
        assert gaps == sorted(gaps, reverse=True)


class TestDiagnosticsJson:
    def test_write_and_read(self, tmp_path):
        diag = {
            "by_bucket": {"binary_91_180": {"n": 2, "mean_return_pct": 1.5}},
            "by_tier": {},
            "by_momentum": {},
            "by_catalyst_proximity": {},
            "by_gap_risk": {},
            "top5_gap": [],
        }
        out_path = _write_diagnostics_json(diag, "2026-03-07", tmp_path)
        assert out_path.is_file()
        assert out_path.name == "2026-03-07.json"

        doc = json.loads(out_path.read_text())
        assert doc["schema_version"] == "expected_vs_realized.v1"
        assert doc["as_of_date"] == "2026-03-07"
        assert doc["by_bucket"]["binary_91_180"]["n"] == 2
