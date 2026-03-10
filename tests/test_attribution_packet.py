"""Tests for tools/build_attribution_packet.py — weekly attribution packet."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_attribution_packet import (
    _classify_proximity_band,
    _parse_top_3_drivers,
    build_attribution_packet,
    build_proximity_rails,
    build_signal_alignment,
    build_top_contributors,
    build_why_held,
    render_attribution_packet_md,
    write_attribution_packet,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_contributor(ticker, bucket="less_binary", pnl=100.0, return_pct=2.0, dollars=10000):
    return {
        "ticker": ticker,
        "bucket": bucket,
        "effective_family": "CLINICAL",
        "pnl": pnl,
        "return_pct": return_pct,
        "dollars": dollars,
    }


def _make_position(
    ticker,
    bucket="less_binary",
    target_dollars=10000,
    actionable_rank=1,
    weight_pct=2.0,
    regulatory_days=None,
    catalyst_days=None,
    effective_family="CLINICAL",
):
    return {
        "ticker": ticker,
        "bucket": bucket,
        "target_dollars": target_dollars,
        "actionable_rank": actionable_rank,
        "weight_pct": weight_pct,
        "regulatory_days": regulatory_days,
        "catalyst_days": catalyst_days,
        "effective_family": effective_family,
    }


# ---------------------------------------------------------------------------
# _parse_top_3_drivers
# ---------------------------------------------------------------------------


class TestParseTop3Drivers:
    def test_normal(self):
        raw = "smart_money_score:+45.4;clinical_score:-34.6;financial_score:-34.6"
        result = _parse_top_3_drivers(raw)
        assert len(result) == 3
        assert result[0] == {"name": "smart_money_score", "value": 45.4}
        assert result[1] == {"name": "clinical_score", "value": -34.6}

    def test_empty(self):
        assert _parse_top_3_drivers("") == []
        assert _parse_top_3_drivers(None) == []

    def test_partial(self):
        result = _parse_top_3_drivers("score_a:+10.0;bad_entry")
        assert len(result) == 1
        assert result[0]["name"] == "score_a"


# ---------------------------------------------------------------------------
# _classify_proximity_band
# ---------------------------------------------------------------------------


class TestClassifyProximityBand:
    def test_within_bands(self):
        assert _classify_proximity_band(0) == "0-7"
        assert _classify_proximity_band(7) == "0-7"
        assert _classify_proximity_band(8) == "8-14"
        assert _classify_proximity_band(50) == "46-90"
        assert _classify_proximity_band(100) == "91-180"
        assert _classify_proximity_band(200) == ">180/NA"

    def test_none_and_nan(self):
        assert _classify_proximity_band(None) == ">180/NA"
        assert _classify_proximity_band(float("nan")) == ">180/NA"

    def test_string_input(self):
        assert _classify_proximity_band("bad") == ">180/NA"


# ---------------------------------------------------------------------------
# Section 1: Top Contributors
# ---------------------------------------------------------------------------


class TestBuildTopContributors:
    def test_ordering_deterministic(self):
        """Ties in P&L are broken by ticker alphabetically."""
        contribs = [
            _make_contributor("ZZAA", pnl=100),
            _make_contributor("AABB", pnl=100),
            _make_contributor("MMNN", pnl=100),
        ]
        result = build_top_contributors(contribs, None, {}, {}, {}, None, 500_000, n=10)
        top = result["top"]
        assert top[0]["ticker"] == "AABB"
        assert top[1]["ticker"] == "MMNN"
        assert top[2]["ticker"] == "ZZAA"

    def test_top_and_bottom_split(self):
        """Top N and bottom N are separated, no overlap."""
        contribs = [_make_contributor(f"T{i:02d}", pnl=100 - i * 20) for i in range(15)]
        result = build_top_contributors(contribs, None, {}, {}, {}, None, 500_000, n=5)
        top_tickers = {e["ticker"] for e in result["top"]}
        bottom_tickers = {e["ticker"] for e in result["bottom"]}
        assert len(top_tickers & bottom_tickers) == 0

    def test_realized_vs_theoretical_with_fills(self):
        """When close and current prices given, theoretical P&L diverges from realized."""
        contribs = [_make_contributor("XYZ", pnl=500, return_pct=5.0, dollars=10000)]
        # Theoretical: close=100, current=103 → 3% → $300
        result = build_top_contributors(
            contribs,
            None,
            close_prices={"XYZ": 100.0},
            fill_prices={},
            current_prices={"XYZ": 103.0},
            xbi_return=None,
            portfolio_notional=500_000,
        )
        top = result["top"][0]
        assert top["pnl_usd_realized"] == 500.0
        assert abs(top["pnl_usd_theoretical"] - 300.0) < 0.1

    def test_no_close_price_falls_back(self):
        """Missing close price → theoretical = realized."""
        contribs = [_make_contributor("ABC", pnl=200, return_pct=2.0)]
        result = build_top_contributors(contribs, None, {}, {}, {}, None, 500_000)
        top = result["top"][0]
        assert top["pnl_usd_theoretical"] == top["pnl_usd_realized"]

    def test_hedged_contribution(self):
        """XBI return provided → hedged contribution calculated."""
        contribs = [_make_contributor("ABC", pnl=500, return_pct=5.0, dollars=10000)]
        result = build_top_contributors(contribs, None, {}, {}, {}, xbi_return=0.02, portfolio_notional=500_000)
        top = result["top"][0]
        # excess = 5%/100 - 2% = 0.03; hedged = 0.03 * 10000 = 300
        assert abs(top["hedged_contrib_usd_realized"] - 300.0) < 1.0

    def test_entry_price_source_annotation(self):
        """Entry annotation surface through to output."""
        contribs = [_make_contributor("ABC")]
        ann = {"ABC": {"entry_price_source": "FILL_VWAP", "entry_price": 45.5}}
        result = build_top_contributors(contribs, ann, {}, {}, {}, None, 500_000)
        assert result["top"][0]["entry_price_source"] == "FILL_VWAP"


# ---------------------------------------------------------------------------
# Section 2: Signal Alignment
# ---------------------------------------------------------------------------


class TestBuildSignalAlignment:
    def test_enough_positions(self):
        """With >= 5 positions, IC is computed (not UNKNOWN)."""
        positions = [_make_position(f"T{i}", actionable_rank=i + 1) for i in range(6)]
        rets = {f"T{i}": float(6 - i) for i in range(6)}  # perfect negative rank corr
        result = build_signal_alignment(positions, rets, rets)
        assert result["n_positions"] == 6
        ic = result["spearman_rank_vs_realized"]
        assert ic != "UNKNOWN"
        # Higher rank number = worse, and we negate, so perfect correlation expected
        assert isinstance(ic, float)

    def test_too_few_positions(self):
        """With < 5 positions, returns UNKNOWN."""
        positions = [_make_position("T1", actionable_rank=1)]
        rets = {"T1": 5.0}
        result = build_signal_alignment(positions, rets, rets)
        assert result["spearman_rank_vs_realized"] == "UNKNOWN"
        assert "reason" in result

    def test_zero_rank_excluded(self):
        """Positions with actionable_rank=0 are skipped."""
        positions = [_make_position(f"T{i}", actionable_rank=0) for i in range(10)]
        rets = {f"T{i}": float(i) for i in range(10)}
        result = build_signal_alignment(positions, rets, rets)
        assert result["n_positions"] == 0
        assert result["spearman_rank_vs_realized"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Section 3: Why We Held These
# ---------------------------------------------------------------------------


class TestBuildWhyHeld:
    def test_extracts_drivers(self):
        """Drivers extracted from rankings_data top_3_drivers column."""
        positions = [_make_position("ABC", bucket="less_binary", target_dollars=10000)]
        rankings = {
            "ABC": {
                "top_3_drivers": "score_a:+10.0;score_b:-5.0;score_c:+3.0",
                "actionable_rank": "1",
            }
        }
        result = build_why_held(positions, rankings)
        assert "less_binary" in result
        entry = result["less_binary"][0]
        assert entry["ticker"] == "ABC"
        assert len(entry["drivers"]) == 3
        assert entry["drivers"][0]["name"] == "score_a"

    def test_missing_drivers_fallback(self):
        """Missing top_3_drivers → UNKNOWN placeholder."""
        positions = [_make_position("XYZ", bucket="binary_0_30")]
        result = build_why_held(positions, {})
        entry = result["binary_0_30"][0]
        assert entry["drivers"][0]["name"] == "UNKNOWN"

    def test_top_n_per_bucket(self):
        """Only top N by weight per bucket are included."""
        positions = [_make_position(f"T{i}", bucket="less_binary", target_dollars=10000 - i * 100) for i in range(10)]
        result = build_why_held(positions, {}, top_n_per_bucket=3)
        assert len(result["less_binary"]) == 3

    def test_empty_bucket_excluded(self):
        """Buckets with no positions don't appear in result."""
        positions = [_make_position("ABC", bucket="less_binary")]
        result = build_why_held(positions, {})
        assert "binary_0_30" not in result


# ---------------------------------------------------------------------------
# Section 4: Proximity Rails
# ---------------------------------------------------------------------------


class TestBuildProximityRails:
    def test_correct_bucketing(self):
        """Regulatory days mapped to correct bands."""
        positions = [
            _make_position("A", regulatory_days=5, target_dollars=10000),
            _make_position("B", regulatory_days=10, target_dollars=10000),
            _make_position("C", regulatory_days=50, target_dollars=10000),
        ]
        result = build_proximity_rails(positions)
        reg = result["regulatory"]
        assert reg["0-7"]["count"] == 1
        assert reg["8-14"]["count"] == 1
        assert reg["46-90"]["count"] == 1

    def test_missing_days_not_counted(self):
        """Positions without regulatory_days don't appear in reg bands."""
        positions = [_make_position("A", regulatory_days=None, target_dollars=10000)]
        result = build_proximity_rails(positions)
        total_reg = sum(b["count"] for b in result["regulatory"].values())
        assert total_reg == 0

    def test_clinical_only_for_clinical_family(self):
        """Clinical bands only count positions with CLINICAL family."""
        positions = [
            _make_position(
                "A",
                catalyst_days=10,
                effective_family="CLINICAL",
                target_dollars=10000,
            ),
            _make_position(
                "B",
                catalyst_days=10,
                effective_family="REGULATORY",
                target_dollars=10000,
            ),
        ]
        result = build_proximity_rails(positions)
        total_clin = sum(b["count"] for b in result["clinical"].values())
        assert total_clin == 1  # only the CLINICAL family position

    def test_weight_sums(self):
        """Weight percentages sum to ~100% across bands when all positions have regulatory_days."""
        positions = [
            _make_position("A", regulatory_days=5, target_dollars=5000),
            _make_position("B", regulatory_days=100, target_dollars=5000),
        ]
        result = build_proximity_rails(positions)
        total_weight = sum(b["total_weight_pct"] for b in result["regulatory"].values())
        assert abs(total_weight - 100.0) < 0.2


# ---------------------------------------------------------------------------
# Write & Render
# ---------------------------------------------------------------------------


class TestWriteAttributionPacket:
    def test_files_written(self, tmp_path):
        """JSON and MD files written to expected directory."""
        packet = {
            "schema": "attribution_packet.v1",
            "as_of_date": "2026-03-10",
            "prior_date": "2026-03-07",
            "generated_at": "2026-03-10T00:00:00Z",
            "top_contributors": {"top": [], "bottom": [], "n_total": 0},
            "signal_alignment": {"n_positions": 0, "spearman_rank_vs_realized": "UNKNOWN"},
            "why_held": {},
            "proximity_rails": {"regulatory": {}, "clinical": {}},
        }
        out_dir = tmp_path / "attribution" / "2026-03-10"
        json_path, md_path = write_attribution_packet(packet, out_dir)

        assert json_path.exists()
        assert md_path.exists()
        assert json_path.name == "ATTRIBUTION_PACKET.json"
        assert md_path.name == "ATTRIBUTION_PACKET.md"

        data = json.loads(json_path.read_text())
        assert data["schema"] == "attribution_packet.v1"

    def test_md_contains_all_sections(self, tmp_path):
        """Rendered markdown contains all 4 section headers."""
        positions = [
            _make_position("A", regulatory_days=5, target_dollars=10000),
        ]
        contribs = [_make_contributor("A")]
        packet = {
            "schema": "attribution_packet.v1",
            "as_of_date": "2026-03-10",
            "prior_date": "2026-03-07",
            "generated_at": "2026-03-10T00:00:00Z",
            "top_contributors": build_top_contributors(contribs, None, {}, {}, {}, None, 500_000),
            "signal_alignment": {"n_positions": 0, "spearman_rank_vs_realized": "UNKNOWN"},
            "why_held": build_why_held(positions, {}),
            "proximity_rails": build_proximity_rails(positions),
        }
        md = render_attribution_packet_md(packet)
        assert "## Top Contributors" in md
        assert "## Signal Alignment" in md
        assert "## Why We Held These" in md
        assert "## Event Proximity Rails" in md


# ---------------------------------------------------------------------------
# Production-path guard
# ---------------------------------------------------------------------------


class TestProductionLeakageGuard:
    def test_build_attribution_packet_rejects_production_default(self):
        """build_attribution_packet() raises when using production default in pytest."""
        with pytest.raises(AssertionError, match="attribution_root"):
            build_attribution_packet(
                "2026-03-10",
                [],
                {"contributors": []},
                {"account_usd": 500_000},
                snap_dir=Path("/tmp/fake_snap"),
                # attribution_root not overridden → should hit production default
            )


# ---------------------------------------------------------------------------
# Integration: build_attribution_packet
# ---------------------------------------------------------------------------


class TestBuildAttributionPacketIntegration:
    def test_full_packet_structure(self, tmp_path):
        """End-to-end: build + write produces valid packet with all sections."""
        snap_dir = tmp_path / "snapshots" / "2026-03-10"
        snap_dir.mkdir(parents=True)
        # Write a minimal rankings.csv
        import csv

        rankings_path = snap_dir / "rankings.csv"
        with open(rankings_path, "w", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["ticker", "actionable_rank", "top_3_drivers", "eligible"],
            )
            w.writeheader()
            for i in range(6):
                w.writerow(
                    {
                        "ticker": f"T{i}",
                        "actionable_rank": str(i + 1),
                        "top_3_drivers": f"score_a:+{10-i};score_b:-{i};score_c:+1",
                        "eligible": "True",
                    }
                )

        positions = [
            _make_position(
                f"T{i}",
                bucket="less_binary",
                actionable_rank=i + 1,
                target_dollars=10000,
                regulatory_days=i * 20,
                catalyst_days=i * 30,
            )
            for i in range(6)
        ]
        contribs = [_make_contributor(f"T{i}", pnl=100 - i * 30, return_pct=5 - i) for i in range(6)]
        perf = {
            "contributors": contribs,
            "entry_annotations": None,
            "xbi_return_pct": 1.5,
        }
        policy = {"account_usd": 500_000}

        attr_root = tmp_path / "attribution"
        packet = build_attribution_packet(
            "2026-03-10",
            positions,
            perf,
            policy,
            snap_dir=snap_dir,
            attribution_root=attr_root,
        )

        # Verify structure
        assert packet["schema"] == "attribution_packet.v1"
        assert packet["top_contributors"]["n_total"] == 6
        assert packet["signal_alignment"]["n_positions"] >= 5
        assert "less_binary" in packet["why_held"]
        assert "regulatory" in packet["proximity_rails"]

        # Write and verify files
        out_dir = attr_root / "2026-03-10"
        json_path, md_path = write_attribution_packet(packet, out_dir)
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["schema"] == "attribution_packet.v1"

        md = md_path.read_text()
        assert "## Top Contributors" in md
        assert "## Signal Alignment" in md
        assert "## Why We Held These" in md
        assert "## Event Proximity Rails" in md
