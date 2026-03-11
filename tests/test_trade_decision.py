"""Tests for tools/trade_decision.py — deterministic trade decision engine."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.trade_decision import (
    VERDICT_NO_TRADE,
    VERDICT_TRADE,
    VERDICT_TRADE_WITH_CAPS,
    build_trade_decision,
    check_alpha_health,
    check_execution_quality,
    check_gap_risk_count,
    check_gap_risk_weight,
    check_missing_price_coverage,
    check_model_vs_realized,
    check_pre_trade_gate,
    check_resolved_regulatory,
    check_turnover,
    render_trade_decision_md,
    write_trade_decision,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_POLICY = {
    "schema": "trade_decision_policy.v1",
    "gates": {"pre_trade_must_pass": True},
    "risk_limits": {
        "max_gap_risk_high_count": 4,
        "max_gap_risk_high_weight_pct": 8.0,
        "max_missing_price_coverage": 2,
        "max_resolved_regulatory": 3,
    },
    "execution_quality": {
        "min_fill_coverage_pct": 50.0,
        "max_avg_slippage_bps": 50.0,
    },
    "model_vs_realized": {"max_negative_gap_pct": -0.50},
    "alpha_health": {"min_trailing_excess_pct": -1.0},
    "turnover": {"max_turnover_pct": 40.0},
    "caps": {
        "gap_risk_high_count_trigger": 3,
        "gap_risk_high_name_cap_pct": 0.25,
        "gap_risk_high_budget_reduction_pct": 15.0,
        "realized_worse_slippage_trigger_bps": 30.0,
        "realized_worse_min_trade_usd_bump": 500,
    },
}


def _make_ic_packet(**overrides) -> dict:
    """Build a clean-passing IC packet. Override sections as needed."""
    packet = {
        "schema": "ic_packet.v1",
        "provenance": {
            "as_of_date": "2026-03-10",
            "ruleset_id": "7177a4ea",
            "engine_version": "v1.3.0",
            "execution_status": "READY",
        },
        "status": "READY",
        "gates": {
            "overall": "PASS",
            "can_trade": True,
            "checks": [{"name": "provenance", "status": "PASS", "detail": "ok"}],
            "blocking_reasons": [],
        },
        "positions_summary": {
            "n_positions": 45,
            "gross_exposure_usd": 450000.0,
            "cash_usd": 50000.0,
            "turnover_estimate_pct": 8.5,
            "by_bucket": {},
            "by_family": {},
        },
        "model_vs_realized": None,
        "alpha_attribution": {"available": False},
        "contributors": {"available": False},
        "execution_quality": {"available": False},
        "risk_flags": {
            "gap_risk_high": [],
            "missing_price_coverage": [],
            "resolved_regulatory": [],
        },
        "files_written": [],
    }
    packet.update(overrides)
    return packet


# ---------------------------------------------------------------------------
# Pre-trade gate
# ---------------------------------------------------------------------------


class TestPreTradeGate:
    def test_pass_when_can_trade(self):
        ic = _make_ic_packet()
        result = check_pre_trade_gate(ic, DEFAULT_POLICY)
        assert result.status == "PASS"

    def test_fail_when_blocked(self):
        ic = _make_ic_packet(
            gates={
                "overall": "FAIL",
                "can_trade": False,
                "checks": [],
                "blocking_reasons": ["bucket_deviation too large"],
            }
        )
        result = check_pre_trade_gate(ic, DEFAULT_POLICY)
        assert result.status == "FAIL"
        assert "bucket_deviation" in result.detail

    def test_pass_when_policy_advisory(self):
        ic = _make_ic_packet(gates={"overall": "FAIL", "can_trade": False, "checks": [], "blocking_reasons": []})
        policy = {**DEFAULT_POLICY, "gates": {"pre_trade_must_pass": False}}
        result = check_pre_trade_gate(ic, policy)
        assert result.status == "PASS"


# ---------------------------------------------------------------------------
# Gap risk count
# ---------------------------------------------------------------------------


class TestGapRiskCount:
    def test_pass_zero(self):
        ic = _make_ic_packet()
        result = check_gap_risk_count(ic, DEFAULT_POLICY)
        assert result.status == "PASS"
        assert result.value == 0

    def test_warn_at_trigger(self):
        gap = [{"ticker": f"T{i}", "weight_pct": 1.0} for i in range(3)]
        ic = _make_ic_packet(risk_flags={"gap_risk_high": gap, "missing_price_coverage": [], "resolved_regulatory": []})
        result = check_gap_risk_count(ic, DEFAULT_POLICY)
        assert result.status == "WARN"
        assert result.cap is not None
        assert result.cap["type"] == "gap_risk_cap"
        assert "T0" in result.cap["affected_tickers"]

    def test_fail_above_max(self):
        gap = [{"ticker": f"T{i}", "weight_pct": 1.0} for i in range(5)]
        ic = _make_ic_packet(risk_flags={"gap_risk_high": gap, "missing_price_coverage": [], "resolved_regulatory": []})
        result = check_gap_risk_count(ic, DEFAULT_POLICY)
        assert result.status == "FAIL"
        assert result.value == 5


# ---------------------------------------------------------------------------
# Gap risk weight
# ---------------------------------------------------------------------------


class TestGapRiskWeight:
    def test_pass_low_weight(self):
        gap = [{"ticker": "T0", "weight_pct": 2.0}]
        ic = _make_ic_packet(risk_flags={"gap_risk_high": gap, "missing_price_coverage": [], "resolved_regulatory": []})
        result = check_gap_risk_weight(ic, DEFAULT_POLICY)
        assert result.status == "PASS"

    def test_fail_high_weight(self):
        gap = [{"ticker": f"T{i}", "weight_pct": 3.0} for i in range(3)]
        ic = _make_ic_packet(risk_flags={"gap_risk_high": gap, "missing_price_coverage": [], "resolved_regulatory": []})
        result = check_gap_risk_weight(ic, DEFAULT_POLICY)
        assert result.status == "FAIL"
        assert result.value == 9.0


# ---------------------------------------------------------------------------
# Missing price coverage
# ---------------------------------------------------------------------------


class TestMissingPriceCoverage:
    def test_pass_none_missing(self):
        ic = _make_ic_packet()
        result = check_missing_price_coverage(ic, DEFAULT_POLICY)
        assert result.status == "PASS"

    def test_warn_one_missing(self):
        ic = _make_ic_packet(
            risk_flags={"gap_risk_high": [], "missing_price_coverage": ["RNA"], "resolved_regulatory": []}
        )
        result = check_missing_price_coverage(ic, DEFAULT_POLICY)
        assert result.status == "WARN"

    def test_fail_too_many(self):
        ic = _make_ic_packet(
            risk_flags={"gap_risk_high": [], "missing_price_coverage": ["A", "B", "C"], "resolved_regulatory": []}
        )
        result = check_missing_price_coverage(ic, DEFAULT_POLICY)
        assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# Resolved regulatory
# ---------------------------------------------------------------------------


class TestResolvedRegulatory:
    def test_pass_none(self):
        ic = _make_ic_packet()
        result = check_resolved_regulatory(ic, DEFAULT_POLICY)
        assert result.status == "PASS"

    def test_warn_above_max(self):
        ic = _make_ic_packet(
            risk_flags={"gap_risk_high": [], "missing_price_coverage": [], "resolved_regulatory": ["A", "B", "C", "D"]}
        )
        result = check_resolved_regulatory(ic, DEFAULT_POLICY)
        assert result.status == "WARN"


# ---------------------------------------------------------------------------
# Execution quality
# ---------------------------------------------------------------------------


class TestExecutionQuality:
    def test_pass_no_data(self):
        ic = _make_ic_packet()
        result = check_execution_quality(ic, DEFAULT_POLICY)
        assert result.status == "PASS"
        assert "skipped" in result.detail

    def test_pass_good_fills(self):
        ic = _make_ic_packet(execution_quality={"available": True, "fill_coverage_pct": 95.0, "avg_slippage_bps": 5.0})
        result = check_execution_quality(ic, DEFAULT_POLICY)
        assert result.status == "PASS"

    def test_warn_bad_slippage(self):
        ic = _make_ic_packet(execution_quality={"available": True, "fill_coverage_pct": 90.0, "avg_slippage_bps": 60.0})
        result = check_execution_quality(ic, DEFAULT_POLICY)
        assert result.status == "WARN"
        assert result.cap is not None
        assert result.cap["type"] == "min_trade_bump"

    def test_warn_low_coverage_no_cap_if_slippage_ok(self):
        ic = _make_ic_packet(execution_quality={"available": True, "fill_coverage_pct": 30.0, "avg_slippage_bps": 5.0})
        result = check_execution_quality(ic, DEFAULT_POLICY)
        assert result.status == "WARN"
        assert result.cap is None  # Slippage is below trigger, no cap


# ---------------------------------------------------------------------------
# Model vs realized
# ---------------------------------------------------------------------------


class TestModelVsRealized:
    def test_pass_no_data(self):
        ic = _make_ic_packet()
        result = check_model_vs_realized(ic, DEFAULT_POLICY)
        assert result.status == "PASS"

    def test_pass_small_gap(self):
        ic = _make_ic_packet(model_vs_realized={"gap_pct": -0.20})
        result = check_model_vs_realized(ic, DEFAULT_POLICY)
        assert result.status == "PASS"

    def test_warn_large_gap(self):
        ic = _make_ic_packet(model_vs_realized={"gap_pct": -0.80})
        result = check_model_vs_realized(ic, DEFAULT_POLICY)
        assert result.status == "WARN"
        assert "-0.80" in result.detail


# ---------------------------------------------------------------------------
# Alpha health
# ---------------------------------------------------------------------------


class TestAlphaHealth:
    def test_pass_no_data(self):
        ic = _make_ic_packet()
        result = check_alpha_health(ic, DEFAULT_POLICY)
        assert result.status == "PASS"

    def test_pass_positive_excess(self):
        ic = _make_ic_packet(alpha_attribution={"available": True, "excess_vs_xbi_pct": 0.5})
        result = check_alpha_health(ic, DEFAULT_POLICY)
        assert result.status == "PASS"

    def test_fail_deep_negative(self):
        ic = _make_ic_packet(alpha_attribution={"available": True, "excess_vs_xbi_pct": -2.0})
        result = check_alpha_health(ic, DEFAULT_POLICY)
        assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# Turnover
# ---------------------------------------------------------------------------


class TestTurnover:
    def test_pass_normal(self):
        ic = _make_ic_packet()
        result = check_turnover(ic, DEFAULT_POLICY)
        assert result.status == "PASS"
        assert result.value == 8.5

    def test_fail_high_turnover(self):
        ic = _make_ic_packet(positions_summary={"turnover_estimate_pct": 50.0})
        result = check_turnover(ic, DEFAULT_POLICY)
        assert result.status == "FAIL"

    def test_pass_no_estimate(self):
        ic = _make_ic_packet(positions_summary={"turnover_estimate_pct": None})
        result = check_turnover(ic, DEFAULT_POLICY)
        assert result.status == "PASS"


# ---------------------------------------------------------------------------
# Full decision
# ---------------------------------------------------------------------------


class TestBuildTradeDecision:
    def test_all_pass_trade(self):
        ic = _make_ic_packet()
        decision = build_trade_decision(ic, DEFAULT_POLICY)
        assert decision["verdict"] == VERDICT_TRADE
        assert decision["n_fail"] == 0
        assert decision["caps"] == []

    def test_fail_produces_no_trade(self):
        ic = _make_ic_packet(gates={"overall": "FAIL", "can_trade": False, "checks": [], "blocking_reasons": ["bad"]})
        decision = build_trade_decision(ic, DEFAULT_POLICY)
        assert decision["verdict"] == VERDICT_NO_TRADE
        assert decision["n_fail"] >= 1
        assert len(decision["blocking_reasons"]) >= 1

    def test_caps_produce_trade_with_caps(self):
        gap = [{"ticker": f"T{i}", "weight_pct": 1.0} for i in range(3)]
        ic = _make_ic_packet(risk_flags={"gap_risk_high": gap, "missing_price_coverage": [], "resolved_regulatory": []})
        decision = build_trade_decision(ic, DEFAULT_POLICY)
        assert decision["verdict"] == VERDICT_TRADE_WITH_CAPS
        assert len(decision["caps"]) >= 1
        assert decision["caps"][0]["triggered_by"] == "gap_risk_high_count"

    def test_fail_trumps_caps(self):
        """If there's a FAIL + caps, verdict should be NO_TRADE."""
        gap = [{"ticker": f"T{i}", "weight_pct": 1.0} for i in range(3)]
        ic = _make_ic_packet(
            gates={"overall": "FAIL", "can_trade": False, "checks": [], "blocking_reasons": ["bad"]},
            risk_flags={"gap_risk_high": gap, "missing_price_coverage": [], "resolved_regulatory": []},
        )
        decision = build_trade_decision(ic, DEFAULT_POLICY)
        assert decision["verdict"] == VERDICT_NO_TRADE

    def test_schema_and_provenance(self):
        ic = _make_ic_packet()
        decision = build_trade_decision(ic, DEFAULT_POLICY)
        assert decision["schema"] == "trade_decision.v1"
        assert decision["provenance"]["ruleset_id"] == "7177a4ea"
        assert decision["as_of_date"] == "2026-03-10"

    def test_multiple_caps(self):
        """Gap risk cap + execution quality cap both fire."""
        gap = [{"ticker": f"T{i}", "weight_pct": 1.0} for i in range(3)]
        ic = _make_ic_packet(
            risk_flags={"gap_risk_high": gap, "missing_price_coverage": [], "resolved_regulatory": []},
            execution_quality={"available": True, "fill_coverage_pct": 90.0, "avg_slippage_bps": 60.0},
        )
        decision = build_trade_decision(ic, DEFAULT_POLICY)
        assert decision["verdict"] == VERDICT_TRADE_WITH_CAPS
        assert len(decision["caps"]) == 2
        cap_types = {c["type"] for c in decision["caps"]}
        assert "gap_risk_cap" in cap_types
        assert "min_trade_bump" in cap_types


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    def test_trade_verdict_renders(self):
        ic = _make_ic_packet()
        decision = build_trade_decision(ic, DEFAULT_POLICY)
        md = render_trade_decision_md(decision)
        assert "Trade Decision" in md
        assert "TRADE" in md
        assert "Checks" in md

    def test_no_trade_shows_blocking(self):
        ic = _make_ic_packet(
            gates={"overall": "FAIL", "can_trade": False, "checks": [], "blocking_reasons": ["bucket way off"]}
        )
        decision = build_trade_decision(ic, DEFAULT_POLICY)
        md = render_trade_decision_md(decision)
        assert "NO TRADE" in md
        assert "Blocking Reasons" in md

    def test_caps_section_renders(self):
        gap = [{"ticker": f"T{i}", "weight_pct": 1.0} for i in range(3)]
        ic = _make_ic_packet(risk_flags={"gap_risk_high": gap, "missing_price_coverage": [], "resolved_regulatory": []})
        decision = build_trade_decision(ic, DEFAULT_POLICY)
        md = render_trade_decision_md(decision)
        assert "Active Caps" in md
        assert "gap_risk_cap" in md


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class TestWriter:
    def test_write_creates_files(self, tmp_path):
        ic = _make_ic_packet()
        decision = build_trade_decision(ic, DEFAULT_POLICY)
        json_path, md_path = write_trade_decision(tmp_path, decision)
        assert json_path.is_file()
        assert md_path.is_file()

        loaded = json.loads(json_path.read_text())
        assert loaded["verdict"] == VERDICT_TRADE
        assert loaded["schema"] == "trade_decision.v1"

        md = md_path.read_text()
        assert "Trade Decision" in md
