"""Tests for compute_gate_margins and compute_tier_margins from decision_engine."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from decision_engine import DecisionRuleset, compute_gate_margins, compute_tier_margins


def _rec(**overrides):
    base = {
        "ticker": "TEST",
        "severity": "NONE",
        "fundamental_red_flag": False,
        "fundamental_red_flag_reasons": [],
        "flags": [],
        "attn_flags": [],
        "defensive_features": {"drawdown": -0.15, "drawdown_rel_xbi": -0.05},
        "survivability_signal": {"metrics": {"cash_total": 500_000_000, "burn_ttm": 50_000_000}, "coverage": []},
    }
    base.update(overrides)
    return base


DEFAULT_RS = DecisionRuleset()


class TestComputeGateMargins(unittest.TestCase):

    def test_clean_rec_passes_all_gates(self):
        result = compute_gate_margins(_rec())
        for g in result["gates"]:
            self.assertTrue(g["passed"], f"gate {g['gate']} should pass")
        self.assertEqual(result["first_failed_gate"], "")
        self.assertEqual(result["first_failed_effective_gate"], "")
        self.assertEqual(result["counterfactual"], {})
        self.assertFalse(result["rescued_by_rel"])

    def test_red_flag_fails(self):
        result = compute_gate_margins(_rec(fundamental_red_flag=True))
        rf_gate = [g for g in result["gates"] if g["gate"] == "fundamental_red_flag"][0]
        self.assertFalse(rf_gate["passed"])
        self.assertEqual(result["first_failed_effective_gate"], "fundamental_red_flag")
        self.assertIn("fundamental_red_flag", result["counterfactual"])
        self.assertFalse(result["counterfactual"]["fundamental_red_flag"])

    def test_sev3_fails(self):
        result = compute_gate_margins(_rec(severity="SEV3"))
        sev_gate = [g for g in result["gates"] if g["gate"] == "sev3"][0]
        self.assertFalse(sev_gate["passed"])
        self.assertEqual(result["first_failed_effective_gate"], "sev3")
        self.assertEqual(result["counterfactual"]["severity"], "SEV2")

    def test_deep_drawdown_abs_fails_hard_no_rel(self):
        rec = _rec(defensive_features={"drawdown": -0.80})
        result = compute_gate_margins(rec)
        dd_combined = [g for g in result["gates"] if g["gate"] == "deep_drawdown"][0]
        self.assertFalse(dd_combined["passed"])
        self.assertEqual(dd_combined["mode"], "abs_only_fallback")
        self.assertIn("drawdown", result["counterfactual"])
        self.assertAlmostEqual(result["counterfactual"]["drawdown"], DEFAULT_RS.drawdown_gate)

    def test_deep_drawdown_require_both_both_breach(self):
        rec = _rec(defensive_features={"drawdown": -0.80, "drawdown_rel_xbi": -0.50})
        result = compute_gate_margins(rec)
        dd_combined = [g for g in result["gates"] if g["gate"] == "deep_drawdown"][0]
        self.assertFalse(dd_combined["passed"])
        self.assertEqual(dd_combined["mode"], "require_both")
        # Counterfactual picks smaller delta side
        self.assertTrue("drawdown" in result["counterfactual"] or "drawdown_rel_xbi" in result["counterfactual"])
        # abs margin = -0.80 - (-0.40) = -0.40; rel margin = -0.50 - (-0.20) = -0.30
        # rel_delta (0.30) < abs_delta (0.40), so counterfactual should pick rel
        self.assertIn("drawdown_rel_xbi", result["counterfactual"])

    def test_deep_drawdown_require_both_only_abs_breaches_passes(self):
        # abs breaches but rel does not -> AND logic -> passes
        rec = _rec(defensive_features={"drawdown": -0.80, "drawdown_rel_xbi": -0.10})
        result = compute_gate_margins(rec)
        dd_combined = [g for g in result["gates"] if g["gate"] == "deep_drawdown"][0]
        self.assertTrue(dd_combined["passed"])
        self.assertEqual(dd_combined["mode"], "require_both")

    def test_deep_drawdown_require_either_abs_breach_fails(self):
        rs = replace(DEFAULT_RS, drawdown_gate_require_both=False)
        rec = _rec(defensive_features={"drawdown": -0.80, "drawdown_rel_xbi": -0.10})
        result = compute_gate_margins(rec, ruleset=rs)
        dd_combined = [g for g in result["gates"] if g["gate"] == "deep_drawdown"][0]
        self.assertFalse(dd_combined["passed"])
        self.assertEqual(dd_combined["mode"], "require_either")
        self.assertIn("drawdown", result["counterfactual"])

    def test_soft_drawdown_above_hard_floor_passes(self):
        rs = replace(DEFAULT_RS, drawdown_gate_mode="soft")
        # drawdown below drawdown_gate (-0.40) but above hard_floor (-0.75) -> passes in soft mode
        rec = _rec(defensive_features={"drawdown": -0.60, "drawdown_rel_xbi": -0.10})
        result = compute_gate_margins(rec, ruleset=rs)
        dd_combined = [g for g in result["gates"] if g["gate"] == "deep_drawdown"][0]
        self.assertTrue(dd_combined["passed"])
        self.assertEqual(dd_combined["mode"], "soft")

    def test_soft_drawdown_below_hard_floor_fails(self):
        rs = replace(DEFAULT_RS, drawdown_gate_mode="soft")
        rec = _rec(defensive_features={"drawdown": -0.80, "drawdown_rel_xbi": -0.10})
        result = compute_gate_margins(rec, ruleset=rs)
        dd_combined = [g for g in result["gates"] if g["gate"] == "deep_drawdown"][0]
        self.assertFalse(dd_combined["passed"])
        self.assertEqual(dd_combined["mode"], "soft")
        self.assertAlmostEqual(result["counterfactual"]["drawdown"], rs.drawdown_hard_floor)

    def test_adv_fail_flag(self):
        result = compute_gate_margins(_rec(attn_flags=["adv_fail"]))
        adv_gate = [g for g in result["gates"] if g["gate"] == "adv_fail"][0]
        self.assertFalse(adv_gate["passed"])
        self.assertEqual(result["counterfactual"]["flags"], "remove_adv_fail")

    def test_rescued_by_relative_gate(self):
        # abs breaches, rel does not, require_both -> rescued_by_rel=True
        rec = _rec(defensive_features={"drawdown": -0.80, "drawdown_rel_xbi": -0.10})
        result = compute_gate_margins(rec)
        self.assertTrue(result["rescued_by_rel"])
        self.assertLess(result["dd_abs_margin"], 0)
        self.assertGreaterEqual(result["dd_rel_margin"], 0)

    def test_multiple_gates_fail_first_is_red_flag(self):
        rec = _rec(
            fundamental_red_flag=True,
            defensive_features={"drawdown": -0.80},
        )
        result = compute_gate_margins(rec)
        self.assertEqual(result["first_failed_effective_gate"], "fundamental_red_flag")
        # Both should appear in counterfactual
        self.assertIn("fundamental_red_flag", result["counterfactual"])
        self.assertIn("drawdown", result["counterfactual"])

    def test_dd_rel_margin_rescue(self):
        # Both abs and rel breach, but enable rescue: rel margin > rescue threshold -> passes
        rs = replace(
            DEFAULT_RS,
            enable_dd_rel_margin_rescue=True,
            dd_rel_margin_rescue_threshold=-0.05,
        )
        # rel = -0.22 -> margin = -0.22 - (-0.20) = -0.02 > -0.05 -> rescued
        rec = _rec(defensive_features={"drawdown": -0.80, "drawdown_rel_xbi": -0.22})
        result = compute_gate_margins(rec, ruleset=rs)
        dd_combined = [g for g in result["gates"] if g["gate"] == "deep_drawdown"][0]
        self.assertTrue(dd_combined["passed"])
        self.assertEqual(dd_combined["mode"], "require_both")


class TestComputeTierMargins(unittest.TestCase):

    def test_above_a_floor(self):
        result = compute_tier_margins(0.75, "near")
        self.assertGreater(result["optionality_margin_a"], 0)
        self.assertGreater(result["optionality_margin_b"], 0)

    def test_between_a_and_b(self):
        result = compute_tier_margins(0.45, "near")
        self.assertLess(result["optionality_margin_a"], 0)
        self.assertGreater(result["optionality_margin_b"], 0)

    def test_below_b_floor(self):
        result = compute_tier_margins(0.10, "near")
        self.assertLess(result["optionality_margin_a"], 0)
        self.assertLess(result["optionality_margin_b"], 0)

    def test_none_optionality(self):
        result = compute_tier_margins(None, "near")
        self.assertIsNone(result["optionality_margin_a"])
        self.assertIsNone(result["optionality_margin_b"])

    def test_actionable_catalyst_near(self):
        result = compute_tier_margins(0.50, "near")
        self.assertTrue(result["actionable_catalyst"])

    def test_actionable_catalyst_mid(self):
        result = compute_tier_margins(0.50, "mid")
        self.assertTrue(result["actionable_catalyst"])

    def test_non_actionable_catalyst_far(self):
        result = compute_tier_margins(0.50, "far")
        self.assertFalse(result["actionable_catalyst"])

    def test_non_actionable_catalyst_empty(self):
        result = compute_tier_margins(0.50, "")
        self.assertFalse(result["actionable_catalyst"])


if __name__ == "__main__":
    unittest.main()
