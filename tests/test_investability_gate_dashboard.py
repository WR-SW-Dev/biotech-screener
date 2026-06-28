"""Tests for the DEM investability gate dashboard (verdict ladder + card).

VALIDATION_INFRASTRUCTURE / INVESTABILITY_GATE_MONITOR / NO_MODEL_CHANGE.
"""

from __future__ import annotations

from tools.investability_gate_dashboard import COST_BPS, GATES, build_card, evaluate_gate, nonoverlapping_weekly

# --- verdict ladder (pure function) ---


def test_research_only_when_harness_not_live():
    v, _ = evaluate_gate(0, None, None, None, harness_live=False)
    assert v == "RESEARCH_ONLY"


def test_pilot_validation_below_20_windows():
    v, _ = evaluate_gate(5, 0.03, 0.99, 0.01, harness_live=True)
    assert v == "PILOT_VALIDATION"


def test_provisional_at_20_windows_passing():
    v, _ = evaluate_gate(20, 0.02, 0.80, 0.20, harness_live=True)
    assert v == "PROVISIONAL_INVESTABLE"


def test_investable_at_52_windows_all_criteria():
    v, _ = evaluate_gate(52, 0.05, 0.92, 0.04, harness_live=True)
    assert v == "INVESTABLE"


def test_reject_when_net_excess_negative_after_20():
    v, reasons = evaluate_gate(25, -0.01, 0.80, 0.20, harness_live=True)
    assert v == "REJECT_OR_EXTEND"
    assert any("net excess" in r for r in reasons)


def test_reject_when_percentile_too_low_after_20():
    v, reasons = evaluate_gate(30, 0.02, 0.60, 0.40, harness_live=True)
    assert v == "REJECT_OR_EXTEND"


def test_52_windows_but_weak_falls_to_provisional_not_investable():
    # meets provisional (pctile>0.75, net>0) but not investable (pctile<0.90)
    v, _ = evaluate_gate(60, 0.03, 0.80, 0.20, harness_live=True)
    assert v == "PROVISIONAL_INVESTABLE"


# --- cost model ---


def test_cost_cases_ordered_and_positive():
    assert COST_BPS["low"] <= COST_BPS["base"] <= COST_BPS["stress"]
    assert all(v > 0 for v in COST_BPS.values())


def test_net_excess_below_gross_under_costs():
    captures = [{"date": "2026-06-15", "data_quality": "PASS"}]
    fills = {
        "2026-06-15": {
            "capture_date": "2026-06-15",
            "xs_5d": 0.02,
            "basket_5d": 0.03,
            "xbi_5d": 0.01,
            "control_bootstrap_pct_5d": 0.9,
        }
    }
    card = build_card(captures, fills, {"status": "active", "model_hash": "x", "ruleset_hash": "y"}, "base", None)
    assert card["windows_completed"] == 1
    # net < gross by exactly the cost
    assert card["net_excess"]["mean"] < card["gross_excess"]["mean"]
    assert abs((card["gross_excess"]["mean"] - card["net_excess"]["mean"]) - COST_BPS["base"] / 1e4) < 1e-9


def test_pending_guards_present_and_verdict_pilot_with_few_windows():
    captures = [{"date": "2026-06-15", "data_quality": "PASS"}]
    fills = {
        "2026-06-15": {
            "capture_date": "2026-06-15",
            "xs_5d": 0.02,
            "basket_5d": 0.03,
            "xbi_5d": 0.01,
            "control_bootstrap_pct_5d": 0.9,
        }
    }
    card = build_card(captures, fills, {"status": "active", "model_hash": "x", "ruleset_hash": "y"}, "base", None)
    assert card["verdict"] == "PILOT_VALIDATION"
    assert "ees_guarded_shadow_delta" in card["pending_metrics"]
    assert "repeat_offender_count" in card["pending_metrics"]


def test_nonoverlapping_one_per_iso_week():
    # two captures same ISO week -> one window (earliest)
    captures = [{"date": "2026-06-15", "data_quality": "PASS"}, {"date": "2026-06-16", "data_quality": "PASS"}]
    fills = {
        "2026-06-15": {"capture_date": "2026-06-15", "xs_5d": 0.01},
        "2026-06-16": {"capture_date": "2026-06-16", "xs_5d": 0.02},
    }
    rows = nonoverlapping_weekly(captures, fills, None)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-15"


def test_unfilled_windows_excluded():
    captures = [{"date": "2026-06-15", "data_quality": "PASS"}]
    fills = {"2026-06-15": {"capture_date": "2026-06-15", "xs_5d": None}}
    rows = nonoverlapping_weekly(captures, fills, None)
    assert rows == []
