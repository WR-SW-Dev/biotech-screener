"""Tests for tools/ic_packet.py — weekly IC-ready packet."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.ic_packet import (
    build_contributors,
    build_file_index,
    build_gates,
    build_ic_packet,
    build_risk_flags,
    render_ic_packet_md,
    write_ic_packet,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

POLICY = {"account_usd": 500_000, "bucket_targets": {"less_binary": 0.55}}


def _make_positions(n=5):
    return [
        {
            "ticker": f"T{i}",
            "bucket": "less_binary",
            "target_dollars": 10000,
            "weight_pct": 2.0,
            "effective_family": "CLINICAL",
            "gap_risk": "",
            "price_coverage": "OK",
            "regulatory_days": None,
            "catalyst_days": None,
            "actionable_rank": i + 1,
        }
        for i in range(n)
    ]


def _make_perf(total_pnl=500, pnl_pct=1.0, n_contribs=6):
    contribs = [
        {
            "ticker": f"T{i}",
            "bucket": "less_binary",
            "effective_family": "CLINICAL",
            "pnl": 200 - i * 80,
            "return_pct": 5.0 - i * 2.0,
            "dollars": 10000,
        }
        for i in range(n_contribs)
    ]
    return {
        "total_pnl": total_pnl,
        "pnl_pct": pnl_pct,
        "excess_vs_xbi_pct": 0.5,
        "name_turnover_pct": 10.0,
        "contributors": contribs,
        "sleeve_attribution": {
            "less_binary": {"pnl": 300, "return_pct": 0.6, "excess_pct": 0.2},
            "binary_0_30": {"pnl": 100, "return_pct": 0.2, "excess_pct": 0.1},
            "binary_31_90": {"pnl": 50, "return_pct": 0.1, "excess_pct": 0.0},
            "binary_91_180": {"pnl": 50, "return_pct": 0.1, "excess_pct": 0.0},
        },
        "execution_quality": None,
        "model_vs_realized": None,
    }


def _make_exec_packet(status="READY"):
    return {
        "status": status,
        "pre_trade": {
            "overall": "PASS" if status != "BLOCKED" else "FAIL",
            "can_trade": status != "BLOCKED",
            "checks": [
                {"name": "provenance", "status": "PASS", "detail": "ok"},
                {"name": "ruleset_active", "status": "PASS", "detail": "matches"},
            ],
        },
    }


def _make_metadata():
    return {"ruleset_id": "7177a4ea", "engine_version": "v1.3.0", "as_of_date": "2026-03-10"}


# ---------------------------------------------------------------------------
# Test: READY path
# ---------------------------------------------------------------------------


class TestReadyPath:
    def test_produces_both_files(self, tmp_path):
        out_dir = tmp_path / "execution" / "2026-03-10"
        out_dir.mkdir(parents=True)
        # Write a dummy file so file_index picks it up
        (out_dir / "trade_plan.csv").write_text("dummy")

        packet = build_ic_packet(
            "2026-03-10",
            _make_exec_packet("READY"),
            _make_positions(),
            POLICY,
            _make_metadata(),
            _make_perf(),
            out_dir,
        )
        json_p, md_p = write_ic_packet(out_dir, packet)

        assert json_p.exists()
        assert md_p.exists()
        assert json_p.name == "IC_PACKET.json"
        assert md_p.name == "IC_PACKET.md"

        data = json.loads(json_p.read_text())
        assert data["schema"] == "ic_packet.v1"
        assert data["status"] == "READY"

    def test_md_includes_all_headings(self, tmp_path):
        out_dir = tmp_path / "execution" / "2026-03-10"
        out_dir.mkdir(parents=True)

        packet = build_ic_packet(
            "2026-03-10",
            _make_exec_packet("READY"),
            _make_positions(),
            POLICY,
            _make_metadata(),
            _make_perf(),
            out_dir,
        )
        md = render_ic_packet_md(packet)

        required_headings = [
            "## Provenance",
            "## Gate Outcomes",
            "## Portfolio Summary",
            "## Performance: Model vs Realized",
            "## Alpha Attribution",
            "## What Drove the Week",
            "## Execution Quality",
            "## Risk Flags",
            "## Files",
        ]
        for h in required_headings:
            assert h in md, f"Missing heading: {h}"

    def test_json_has_all_keys(self, tmp_path):
        out_dir = tmp_path / "execution" / "2026-03-10"
        out_dir.mkdir(parents=True)

        packet = build_ic_packet(
            "2026-03-10",
            _make_exec_packet("READY"),
            _make_positions(),
            POLICY,
            _make_metadata(),
            _make_perf(),
            out_dir,
        )
        required_keys = {
            "schema",
            "provenance",
            "status",
            "gates",
            "positions_summary",
            "model_vs_realized",
            "alpha_attribution",
            "contributors",
            "execution_quality",
            "risk_flags",
            "files_written",
        }
        assert required_keys.issubset(set(packet.keys()))


# ---------------------------------------------------------------------------
# Test: BLOCKED path
# ---------------------------------------------------------------------------


class TestBlockedPath:
    def test_blocked_still_writes_packet(self, tmp_path):
        out_dir = tmp_path / "execution" / "2026-03-10"
        out_dir.mkdir(parents=True)

        exec_pkt = {
            "status": "BLOCKED",
            "pre_trade": {
                "overall": "FAIL",
                "can_trade": False,
                "checks": [
                    {"name": "ruleset_active", "status": "FAIL", "detail": "mismatch"},
                ],
            },
        }
        packet = build_ic_packet(
            "2026-03-10",
            exec_pkt,
            _make_positions(),
            POLICY,
            _make_metadata(),
            None,
            out_dir,
        )
        json_p, md_p = write_ic_packet(out_dir, packet)
        assert json_p.exists()
        assert packet["status"] == "BLOCKED"

    def test_blocked_includes_blocking_reasons(self, tmp_path):
        out_dir = tmp_path / "execution" / "2026-03-10"
        out_dir.mkdir(parents=True)

        exec_pkt = {
            "status": "BLOCKED",
            "pre_trade": {
                "overall": "FAIL",
                "can_trade": False,
                "checks": [
                    {"name": "ruleset_active", "status": "FAIL", "detail": "snapshot mismatch"},
                    {"name": "turnover", "status": "FAIL", "detail": "turnover 50% > 40%"},
                ],
            },
        }
        packet = build_ic_packet(
            "2026-03-10",
            exec_pkt,
            _make_positions(),
            POLICY,
            _make_metadata(),
            None,
            out_dir,
        )
        md = render_ic_packet_md(packet)
        assert "Blocking reasons" in md
        assert "snapshot mismatch" in md
        assert "turnover 50%" in md

    def test_blocked_no_trade_plan_reference(self, tmp_path):
        out_dir = tmp_path / "execution" / "2026-03-10"
        out_dir.mkdir(parents=True)

        packet = build_ic_packet(
            "2026-03-10",
            _make_exec_packet("BLOCKED"),
            _make_positions(),
            POLICY,
            _make_metadata(),
            None,
            out_dir,
        )
        md = render_ic_packet_md(packet)
        # Should not crash and should still have all sections
        assert "## Alpha Attribution" in md
        assert "*N/A" in md  # performance sections show N/A


# ---------------------------------------------------------------------------
# Test: No fills (model_vs_realized absent)
# ---------------------------------------------------------------------------


class TestNoFills:
    def test_no_fills_does_not_crash(self, tmp_path):
        out_dir = tmp_path / "execution" / "2026-03-10"
        out_dir.mkdir(parents=True)

        perf = _make_perf()
        perf["model_vs_realized"] = None
        perf["execution_quality"] = None

        packet = build_ic_packet(
            "2026-03-10",
            _make_exec_packet("READY"),
            _make_positions(),
            POLICY,
            _make_metadata(),
            perf,
            out_dir,
        )
        md = render_ic_packet_md(packet)
        assert "N/A" in md
        assert "## Performance: Model vs Realized" in md


# ---------------------------------------------------------------------------
# Test: With fills (model_vs_realized present)
# ---------------------------------------------------------------------------


class TestWithFills:
    def test_model_vs_realized_rendered(self, tmp_path):
        out_dir = tmp_path / "execution" / "2026-03-10"
        out_dir.mkdir(parents=True)

        perf = _make_perf()
        perf["model_vs_realized"] = {
            "theoretical_total_pnl": 400,
            "realized_total_pnl": 500,
            "theoretical_pnl_pct": 0.08,
            "realized_pnl_pct": 0.10,
            "execution_gap_pnl": 100,
            "execution_gap_pct": 0.02,
            "n_fill_overrides": 3,
            "by_bucket": {},
            "by_family": {},
        }

        packet = build_ic_packet(
            "2026-03-10",
            _make_exec_packet("READY"),
            _make_positions(),
            POLICY,
            _make_metadata(),
            perf,
            out_dir,
        )
        assert packet["model_vs_realized"] is not None
        assert packet["model_vs_realized"]["execution_gap_pnl"] == 100


# ---------------------------------------------------------------------------
# Test: Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_identical_output(self, tmp_path):
        """Same inputs produce byte-identical IC_PACKET.md and IC_PACKET.json."""
        out1 = tmp_path / "run1"
        out2 = tmp_path / "run2"

        for out_dir in (out1, out2):
            out_dir.mkdir(parents=True)
            packet = build_ic_packet(
                "2026-03-10",
                _make_exec_packet("READY"),
                _make_positions(),
                POLICY,
                _make_metadata(),
                _make_perf(),
                out_dir,
            )
            write_ic_packet(out_dir, packet)

        md1 = (out1 / "IC_PACKET.md").read_text()
        md2 = (out2 / "IC_PACKET.md").read_text()
        assert md1 == md2

        json1 = (out1 / "IC_PACKET.json").read_text()
        json2 = (out2 / "IC_PACKET.json").read_text()
        assert json1 == json2


# ---------------------------------------------------------------------------
# Unit tests for subsections
# ---------------------------------------------------------------------------


class TestBuildGates:
    def test_extracts_blocking_reasons(self):
        pre_trade = {
            "overall": "FAIL",
            "can_trade": False,
            "checks": [
                {"name": "a", "status": "PASS", "detail": "ok"},
                {"name": "b", "status": "FAIL", "detail": "bad thing"},
            ],
        }
        gates = build_gates(pre_trade)
        assert gates["blocking_reasons"] == ["bad thing"]
        assert not gates["can_trade"]


class TestBuildContributors:
    def test_top_and_bottom(self):
        perf = _make_perf(n_contribs=10)
        result = build_contributors(perf, n=5)
        assert result["available"]
        assert len(result["top"]) == 5
        assert len(result["bottom"]) > 0
        # Top should have highest pnl
        assert result["top"][0]["pnl_usd"] >= result["top"][-1]["pnl_usd"]

    def test_no_perf(self):
        result = build_contributors(None)
        assert not result["available"]


class TestBuildRiskFlags:
    def test_gap_risk_high_detected(self):
        positions = _make_positions(2)
        positions[0]["gap_risk"] = "HIGH"
        positions[0]["catalyst_days"] = 5
        rf = build_risk_flags(positions)
        assert len(rf["gap_risk_high"]) == 1
        assert rf["gap_risk_high"][0]["ticker"] == "T0"

    def test_missing_price_detected(self):
        positions = _make_positions(2)
        positions[1]["price_coverage"] = "MISSING"
        rf = build_risk_flags(positions)
        assert "T1" in rf["missing_price_coverage"]

    def test_resolved_regulatory_detected(self):
        positions = _make_positions(1)
        positions[0]["regulatory_days"] = -1
        rf = build_risk_flags(positions)
        assert "T0" in rf["resolved_regulatory"]


class TestBuildFileIndex:
    def test_lists_files(self, tmp_path):
        (tmp_path / "a.csv").write_text("x")
        (tmp_path / "b.json").write_text("x")
        result = build_file_index(tmp_path)
        assert result == ["a.csv", "b.json"]

    def test_empty_dir(self, tmp_path):
        assert build_file_index(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path):
        assert build_file_index(tmp_path / "nope") == []
