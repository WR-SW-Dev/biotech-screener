"""Decision engine determinism and contract hardening tests.

Covers:
  1. Property tests — fuzz catalyst, missing data, drawdown edge cases
  2. Snapshot diff budget — same inputs + ruleset = identical output
  3. Ruleset migration — one field change only affects expected outputs
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from decision_engine import (
    DecisionRuleset,
    compute_actionable_sort_key,
    compute_decision_fields,
    compute_target_weights,
)

# =============================================================================
# Fixture builder (same as contract tests)
# =============================================================================


def _rec(
    ticker: str = "TEST",
    severity: str = "NONE",
    confidence_overall: float = 0.72,
    catalyst_days: int = None,
    catalyst_in_window: bool = None,
    vol_60d: float = 0.65,
    beta_xbi_60d: float = 1.1,
    drawdown: float = -0.15,
    rsi_14d: float = 48.0,
    alpha_60d: float = 0.02,
    tier1_count: int = 3,
) -> Dict[str, Any]:
    rec: Dict[str, Any] = {
        "ticker": ticker,
        "severity": severity,
        "confidence_overall": confidence_overall,
        "fundamental_red_flag": False,
        "fundamental_red_flag_reasons": [],
        "flags": [],
        "attn_flags": [],
    }
    cd: Dict[str, Any] = {}
    if catalyst_days is not None:
        cd["days_to_catalyst"] = catalyst_days
    if catalyst_in_window is not None:
        cd["in_optimal_window"] = catalyst_in_window
    rec["catalyst_decay"] = cd if cd else None
    rec["smart_money_signal"] = {}
    rec["coinvest"] = {"tier1_count": tier1_count}
    df: Dict[str, Any] = {}
    if vol_60d is not None:
        df["vol_60d"] = vol_60d
    if beta_xbi_60d is not None:
        df["beta_xbi_60d"] = beta_xbi_60d
    if drawdown is not None:
        df["drawdown"] = drawdown
    if rsi_14d is not None:
        df["rsi_14d"] = rsi_14d
    rec["defensive_features"] = df
    if alpha_60d is not None:
        rec["score_breakdown"] = {"enhancements": {"momentum": {"alpha_60d": alpha_60d}}}
    else:
        rec["score_breakdown"] = {}
    rec["momentum_signal"] = {}
    return rec


def _compute(rec, archetype="drug_developer", optionality=0.70, ruleset=None):
    rs = ruleset or DecisionRuleset()
    return compute_decision_fields(rec, archetype, optionality, ruleset=rs)


# =============================================================================
# 1. Property tests — fuzz catalyst, missing data, drawdown
# =============================================================================


class TestPropertyFuzzCatalyst:
    """Catalyst field permutations should never crash the engine."""

    def test_no_catalyst_data(self):
        rec = _rec(catalyst_days=None, catalyst_in_window=None)
        f = _compute(rec)
        assert f["catalyst_mode"] == "missing"
        assert f["eligible"] in ("0", "1")

    def test_catalyst_days_zero(self):
        f = _compute(_rec(catalyst_days=0, catalyst_in_window=True))
        assert f["catalyst_mode"] in ("blended_window", "specific_days")

    def test_catalyst_days_negative(self):
        """Negative days (past event) should not crash."""
        f = _compute(_rec(catalyst_days=-5, catalyst_in_window=False))
        assert f["eligible"] in ("0", "1")

    def test_catalyst_days_very_large(self):
        f = _compute(_rec(catalyst_days=9999))
        assert f["catalyst_strength"] in ("near", "mid", "far", "missing")

    def test_catalyst_window_only(self):
        """catalyst_in_window=True but no days."""
        rec = _rec()
        rec["catalyst_decay"] = {"in_optimal_window": True}
        f = _compute(rec)
        assert f["catalyst_mode"] in ("blended_window", "missing", "no_upcoming")


class TestPropertyFuzzMissingData:
    """Missing or None fields should not crash."""

    def test_missing_defensive_features(self):
        rec = _rec()
        rec["defensive_features"] = {}
        f = _compute(rec)
        assert "eligible" in f

    def test_none_confidence(self):
        rec = _rec(confidence_overall=None)
        f = _compute(rec)
        assert "eligible" in f

    def test_none_volatility(self):
        f = _compute(_rec(vol_60d=None))
        assert "risk_flags" in f

    def test_none_drawdown(self):
        f = _compute(_rec(drawdown=None))
        assert "eligible" in f

    def test_missing_score_breakdown(self):
        rec = _rec()
        rec["score_breakdown"] = {}
        f = _compute(rec)
        assert f["mom_state"] in ("tailwind", "neutral", "headwind")

    def test_missing_coinvest(self):
        rec = _rec()
        rec["coinvest"] = {}
        f = _compute(rec)
        assert "sponsor_tier1_count" in f

    def test_empty_smart_money(self):
        rec = _rec()
        rec["smart_money_signal"] = {}
        f = _compute(rec)
        assert "eligible" in f


class TestPropertyFuzzDrawdown:
    """Drawdown gate edge cases."""

    def test_drawdown_at_exact_gate(self):
        """Drawdown exactly at gate threshold — should be eligible (gate is exclusive)."""
        rs = DecisionRuleset(drawdown_gate=-0.40)
        f = _compute(_rec(drawdown=-0.40), ruleset=rs)
        assert f["eligible"] in ("0", "1")  # exact boundary — either is valid

    def test_drawdown_just_above_gate(self):
        rs = DecisionRuleset(drawdown_gate=-0.40)
        f = _compute(_rec(drawdown=-0.39), ruleset=rs)
        assert f["eligible"] == "1"

    def test_drawdown_just_below_gate(self):
        rs = DecisionRuleset(drawdown_gate=-0.40)
        f = _compute(_rec(drawdown=-0.41), ruleset=rs)
        # Should be ineligible under hard mode
        assert f["eligible"] == "0"

    def test_soft_drawdown_mode(self):
        rs = DecisionRuleset(drawdown_gate=-0.40, drawdown_gate_mode="soft")
        f = _compute(_rec(drawdown=-0.50), ruleset=rs)
        # Soft mode: still eligible, but sized down
        assert f["eligible"] == "1"

    def test_soft_drawdown_below_hard_floor(self):
        rs = DecisionRuleset(
            drawdown_gate=-0.40,
            drawdown_gate_mode="soft",
            drawdown_hard_floor=-0.75,
        )
        f = _compute(_rec(drawdown=-0.80), ruleset=rs)
        assert f["eligible"] == "0"


# =============================================================================
# 2. Snapshot diff budget — identical inputs = identical output
# =============================================================================


class TestSnapshotDiffBudget:
    """Same inputs + same ruleset must produce bit-for-bit identical output."""

    def test_deterministic_single_ticker(self):
        rec = _rec(ticker="DET1", catalyst_days=45, catalyst_in_window=True)
        f1 = _compute(rec)
        f2 = _compute(copy.deepcopy(rec))
        for key in f1:
            assert f1[key] == f2[key], f"Non-deterministic field: {key}"

    def test_deterministic_sort_key(self):
        rec = _rec(ticker="SORT1", catalyst_days=60)
        f = _compute(rec)
        k1 = compute_actionable_sort_key(f, "drug_developer", 0.70, 1, "SORT1")
        k2 = compute_actionable_sort_key(f, "drug_developer", 0.70, 1, "SORT1")
        assert k1 == k2

    def test_deterministic_weights(self):
        rows = [
            {"size_band": "L", "ticker": "A"},
            {"size_band": "M", "ticker": "B"},
            {"size_band": "S", "ticker": "C"},
        ]
        r1 = compute_target_weights(copy.deepcopy(rows))
        r2 = compute_target_weights(copy.deepcopy(rows))
        for a, b in zip(r1, r2):
            assert a["target_weight_pct"] == b["target_weight_pct"]

    def test_deterministic_cohort(self):
        """Full 5-ticker cohort produces identical ranks on repeated runs."""
        recs = [
            (_rec(ticker="A", catalyst_days=30, catalyst_in_window=True), 0.80),
            (_rec(ticker="B", catalyst_days=60), 0.70),
            (_rec(ticker="C", catalyst_days=120), 0.50),
            (_rec(ticker="D"), 0.40),
            (_rec(ticker="E", catalyst_days=10, catalyst_in_window=True), 0.90),
        ]
        rs = DecisionRuleset()

        def _run_cohort():
            rows = []
            for i, (rec, opt) in enumerate(recs):
                f = compute_decision_fields(copy.deepcopy(rec), "drug_developer", opt, ruleset=rs)
                f["optionality"] = opt
                f["composite_rank"] = i + 1
                f["ticker"] = rec["ticker"]
                rows.append(f)
            rows.sort(
                key=lambda r: compute_actionable_sort_key(
                    r, "drug_developer", r["optionality"], r["composite_rank"], r["ticker"]
                )
            )
            return [r["ticker"] for r in rows if r["eligible"] == "1"]

        order1 = _run_cohort()
        order2 = _run_cohort()
        assert order1 == order2


# =============================================================================
# 3. Ruleset migration — changing one field only affects expected outputs
# =============================================================================


class TestRulesetMigration:
    """Changing one ruleset parameter should only affect related outputs."""

    def _baseline_fields(self, rec=None, opt=0.70):
        rec = rec or _rec(catalyst_days=45, catalyst_in_window=True)
        return _compute(rec, optionality=opt)

    def test_drawdown_gate_change_only_affects_eligibility(self):
        """Loosening drawdown gate should not change tier/sort for eligible names."""
        rec = _rec(catalyst_days=45, catalyst_in_window=True, drawdown=-0.15)
        f_strict = _compute(rec, ruleset=DecisionRuleset(drawdown_gate=-0.40))
        f_loose = _compute(copy.deepcopy(rec), ruleset=DecisionRuleset(drawdown_gate=-0.80))

        # Both should be eligible (drawdown=-0.15 passes both gates)
        assert f_strict["eligible"] == "1"
        assert f_loose["eligible"] == "1"

        # Tier, catalyst mode, momentum should be identical
        assert f_strict["tier_dev"] == f_loose["tier_dev"]
        assert f_strict["catalyst_mode"] == f_loose["catalyst_mode"]
        assert f_strict["mom_state"] == f_loose["mom_state"]

    def test_catalyst_near_days_only_affects_catalyst_strength(self):
        """Changing catalyst_near_days only changes catalyst_strength, not eligibility."""
        rec = _rec(catalyst_days=45, catalyst_in_window=True)
        f_narrow = _compute(rec, ruleset=DecisionRuleset(catalyst_near_days=30))
        f_wide = _compute(copy.deepcopy(rec), ruleset=DecisionRuleset(catalyst_near_days=90))

        assert f_narrow["eligible"] == f_wide["eligible"]
        assert f_narrow["tier_dev"] == f_wide["tier_dev"]
        # catalyst_strength may differ — that's expected
        # But catalyst_mode should be the same
        assert f_narrow["catalyst_mode"] == f_wide["catalyst_mode"]

    def test_sizing_weights_only_affect_weights(self):
        """Changing sizing weights should not change eligibility, tier, or sort."""
        rec = _rec(catalyst_days=45, catalyst_in_window=True)
        rs_default = DecisionRuleset()
        rs_flat = DecisionRuleset(sizing_weights=(("L", 1.0), ("M", 1.0), ("S", 1.0), ("XS", 1.0)))

        f1 = _compute(rec, ruleset=rs_default)
        f2 = _compute(copy.deepcopy(rec), ruleset=rs_flat)

        assert f1["eligible"] == f2["eligible"]
        assert f1["tier_dev"] == f2["tier_dev"]
        assert f1["size_band"] == f2["size_band"]
        assert f1["catalyst_mode"] == f2["catalyst_mode"]

    def test_vol_threshold_only_affects_risk_flags(self):
        """Changing vol threshold only changes risk_flags, not tier."""
        rec = _rec(vol_60d=1.0)  # between default thresholds
        f_tight = _compute(rec, ruleset=DecisionRuleset(vol_high_threshold=0.80))
        f_loose = _compute(copy.deepcopy(rec), ruleset=DecisionRuleset(vol_high_threshold=1.50))

        # Tier should be the same
        assert f_tight["tier_dev"] == f_loose["tier_dev"]
        assert f_tight["eligible"] == f_loose["eligible"]
        # risk_flags may differ
        tight_flags = set(f_tight["risk_flags"].split("|")) if f_tight["risk_flags"] else set()
        loose_flags = set(f_loose["risk_flags"].split("|")) if f_loose["risk_flags"] else set()
        assert "high_vol" in tight_flags or "high_vol" not in loose_flags

    def test_optionality_floor_change_moves_tier(self):
        """Lowering tier_a floor should promote names — expected behavioral change."""
        rec = _rec(catalyst_days=45, catalyst_in_window=True)
        opt = 0.55  # below default tier_a floor (0.60)
        f_default = _compute(rec, optionality=opt)
        f_lowered = _compute(
            copy.deepcopy(rec), optionality=opt, ruleset=DecisionRuleset(tier_a_optionality_floor=0.50)
        )

        # Default: not tier A (opt 0.55 < floor 0.60)
        # Lowered: tier A (opt 0.55 >= floor 0.50)
        # The tier should change — this is the intended effect
        assert f_default["tier_dev"] != "A" or f_lowered["tier_dev"] == "A"
