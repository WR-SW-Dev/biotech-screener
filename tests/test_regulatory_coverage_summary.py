"""Tests for secondary regulatory coverage in weekly summary."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import _compute_regulatory_coverage, write_weekly_summary


def _make_pos(ticker, bucket="binary_91_180", reg_days="", reg_event="", has_reg="0"):
    return {
        "ticker": ticker,
        "bucket": bucket,
        "catalyst_family": "CLINICAL",
        "actionable_rank": 1,
        "tier": "A",
        "size_band": "M",
        "catalyst_days": "100",
        "catalyst_mode": "specific_days",
        "mom_state": "neutral",
        "weight_pct": 2.0,
        "target_dollars": 10000,
        "gap_risk": "",
        "price_coverage": "OK",
        "regulatory_days": reg_days,
        "regulatory_event_type": reg_event,
        "has_regulatory_upcoming_180d": has_reg,
    }


class TestComputeRegulatoryCoverage:
    def test_nonzero_coverage(self):
        positions = [
            _make_pos("ACME", reg_days="30", reg_event="PDUFA", has_reg="1"),
            _make_pos("BETA"),
            _make_pos("GAMA", reg_days="90", reg_event="FDA_ADCOM", has_reg="1"),
        ]
        result = _compute_regulatory_coverage(positions)
        assert result["n_eligible"] == 3
        assert result["n_regulatory"] == 2
        assert result["coverage_pct"] == pytest.approx(66.7, abs=0.1)

    def test_zero_coverage(self):
        positions = [_make_pos("ACME"), _make_pos("BETA")]
        result = _compute_regulatory_coverage(positions)
        assert result["n_regulatory"] == 0
        assert result["coverage_pct"] == 0.0
        assert result["top_imminent"] == []

    def test_empty_positions(self):
        result = _compute_regulatory_coverage([])
        assert result["n_eligible"] == 0
        assert result["n_regulatory"] == 0
        assert result["coverage_pct"] == 0.0

    def test_top_imminent_sorted_by_days(self):
        positions = [
            _make_pos("FAR", reg_days="120", reg_event="PDUFA", has_reg="1"),
            _make_pos("NEAR", reg_days="10", reg_event="FDA_ADCOM", has_reg="1"),
            _make_pos("MID", reg_days="60", reg_event="PDUFA", has_reg="1"),
        ]
        result = _compute_regulatory_coverage(positions)
        tickers = [p["ticker"] for p in result["top_imminent"]]
        assert tickers == ["NEAR", "MID", "FAR"]

    def test_top_imminent_tiebreak_by_ticker(self):
        positions = [
            _make_pos("ZETA", reg_days="30", reg_event="PDUFA", has_reg="1"),
            _make_pos("ALFA", reg_days="30", reg_event="PDUFA", has_reg="1"),
        ]
        result = _compute_regulatory_coverage(positions)
        tickers = [p["ticker"] for p in result["top_imminent"]]
        assert tickers == ["ALFA", "ZETA"]

    def test_top_imminent_capped_at_10(self):
        positions = [_make_pos(f"T{i:02d}", reg_days=str(i * 10), reg_event="PDUFA", has_reg="1") for i in range(15)]
        result = _compute_regulatory_coverage(positions)
        assert len(result["top_imminent"]) == 10


class TestWeeklySummaryRegulatorySection:
    def _render(self, positions, tmp_path):
        positions_data = {"positions": positions, "summary": {"per_bucket": {}, "per_bucket_family": {}}}
        policy = {"account_usd": 100_000, "bucket_targets": {}}
        out = tmp_path / "weekly.md"
        write_weekly_summary("2026-03-08", positions_data, None, policy, {}, out)
        return out.read_text()

    def test_section_present_with_coverage(self, tmp_path):
        positions = [
            _make_pos("ACME", reg_days="30", reg_event="PDUFA", has_reg="1"),
            _make_pos("BETA"),
        ]
        md = self._render(positions, tmp_path)
        assert "## Secondary Regulatory Coverage" in md
        assert "1 / 2 eligible" in md
        assert "ACME" in md
        assert "PDUFA" in md

    def test_section_present_zero_coverage(self, tmp_path):
        positions = [_make_pos("ACME"), _make_pos("BETA")]
        md = self._render(positions, tmp_path)
        assert "## Secondary Regulatory Coverage" in md
        assert "0 / 2 eligible (0.0%)" in md
        assert "No positions with upcoming regulatory catalysts" in md

    def test_section_present_empty_portfolio(self, tmp_path):
        md = self._render([], tmp_path)
        assert "## Secondary Regulatory Coverage" in md
        assert "0 / 0 eligible" in md
