"""Contract tests for decision engine eligibility, sizing, cost, commercial tier, and catalyst priority."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest

from decision_engine import (
    DecisionRuleset,
    _compute_cost_mult,
    _compute_eligibility,
    _compute_size_band,
    _compute_tier_commercial,
    _resolve_catalyst_strength,
    resolve_catalyst_priority,
)

DEFAULT_RS = DecisionRuleset()


def _rec(**overrides):
    base = {
        "ticker": "TEST",
        "severity": "NONE",
        "fundamental_red_flag": False,
        "fundamental_red_flag_reasons": [],
        "flags": [],
        "attn_flags": [],
        "defensive_features": {"drawdown": -0.15, "drawdown_rel_xbi": -0.05},
        "survivability_signal": {
            "metrics": {"cash_total": 500_000_000, "burn_ttm": 50_000_000},
            "coverage": [],
        },
    }
    base.update(overrides)
    return base


# =============================================================================
# TestEligibility
# =============================================================================


class TestEligibility(unittest.TestCase):

    def test_clean_rec_is_eligible(self):
        eligible, reasons, rescued, bypassed = _compute_eligibility(_rec(), DEFAULT_RS)
        self.assertTrue(eligible)
        self.assertEqual(reasons, [])

    def test_financials_missing_triggers_ineligible(self):
        rec = _rec(
            survivability_signal={
                "metrics": {"cash_total": 0},
                "coverage": ["missing_cash", "missing_burn_data"],
            }
        )
        eligible, reasons, _, _ = _compute_eligibility(rec, DEFAULT_RS)
        self.assertFalse(eligible)
        self.assertIn("financials_missing", reasons)

    def test_financials_missing_with_positive_cash_total_passes(self):
        rec = _rec(
            survivability_signal={
                "metrics": {"cash_total": 500_000_000},
                "coverage": ["missing_cash", "missing_burn_data"],
            }
        )
        eligible, reasons, _, _ = _compute_eligibility(rec, DEFAULT_RS)
        self.assertTrue(eligible)
        self.assertEqual(reasons, [])

    def test_financials_missing_mega_cap_bypass(self):
        rs = DecisionRuleset(financials_missing_bypass_market_cap=50e9)
        rec = _rec(
            survivability_signal={
                "metrics": {"cash_total": 0},
                "coverage": ["missing_cash", "missing_burn_data"],
            }
        )
        eligible, reasons, _, bypassed = _compute_eligibility(rec, rs, market_cap=100e9)
        self.assertTrue(eligible)
        self.assertTrue(bypassed)

    def test_red_flag_triggers_ineligible(self):
        rec = _rec(fundamental_red_flag=True)
        eligible, reasons, _, _ = _compute_eligibility(rec, DEFAULT_RS)
        self.assertFalse(eligible)
        self.assertIn("fundamental_red_flag", reasons)

    def test_sev3_triggers_ineligible(self):
        rec = _rec(severity="SEV3")
        eligible, reasons, _, _ = _compute_eligibility(rec, DEFAULT_RS)
        self.assertFalse(eligible)
        self.assertIn("sev3", reasons)

    def test_drawdown_hard_abs_only_no_rel_data(self):
        rec = _rec(defensive_features={"drawdown": -0.80})
        eligible, reasons, _, _ = _compute_eligibility(rec, DEFAULT_RS)
        self.assertFalse(eligible)
        self.assertIn("deep_drawdown", reasons)

    def test_drawdown_hard_require_both_only_abs_breaches(self):
        rs = DecisionRuleset(drawdown_gate=-0.40, drawdown_rel_xbi_gate=-0.20, drawdown_gate_require_both=True)
        rec = _rec(defensive_features={"drawdown": -0.50, "drawdown_rel_xbi": -0.10})
        eligible, reasons, _, _ = _compute_eligibility(rec, rs)
        self.assertTrue(eligible)
        self.assertNotIn("deep_drawdown", reasons)

    def test_drawdown_hard_require_both_both_breach(self):
        rs = DecisionRuleset(drawdown_gate=-0.40, drawdown_rel_xbi_gate=-0.20, drawdown_gate_require_both=True)
        rec = _rec(defensive_features={"drawdown": -0.50, "drawdown_rel_xbi": -0.30})
        eligible, reasons, _, _ = _compute_eligibility(rec, rs)
        self.assertFalse(eligible)
        self.assertIn("deep_drawdown", reasons)

    def test_drawdown_hard_require_either(self):
        rs = DecisionRuleset(drawdown_gate=-0.40, drawdown_gate_require_both=False)
        rec = _rec(defensive_features={"drawdown": -0.50, "drawdown_rel_xbi": -0.10})
        eligible, reasons, _, _ = _compute_eligibility(rec, rs)
        self.assertFalse(eligible)
        self.assertIn("deep_drawdown", reasons)

    def test_drawdown_soft_above_hard_floor(self):
        rs = DecisionRuleset(drawdown_gate_mode="soft", drawdown_hard_floor=-0.75)
        rec = _rec(defensive_features={"drawdown": -0.50})
        eligible, reasons, _, _ = _compute_eligibility(rec, rs)
        self.assertTrue(eligible)
        self.assertNotIn("deep_drawdown", reasons)

    def test_drawdown_soft_below_hard_floor(self):
        rs = DecisionRuleset(drawdown_gate_mode="soft", drawdown_hard_floor=-0.75)
        rec = _rec(defensive_features={"drawdown": -0.80})
        eligible, reasons, _, _ = _compute_eligibility(rec, rs)
        self.assertFalse(eligible)
        self.assertIn("deep_drawdown", reasons)

    def test_drawdown_rescue(self):
        rs = DecisionRuleset(
            drawdown_gate=-0.40,
            drawdown_rel_xbi_gate=-0.20,
            drawdown_gate_require_both=True,
            enable_dd_rel_margin_rescue=True,
            dd_rel_margin_rescue_threshold=-0.05,
        )
        # Both breach, but rel margin is close to gate → rescued
        rec = _rec(defensive_features={"drawdown": -0.50, "drawdown_rel_xbi": -0.22})
        eligible, reasons, rescued, _ = _compute_eligibility(rec, rs)
        self.assertTrue(eligible)
        self.assertTrue(rescued)
        self.assertNotIn("deep_drawdown", reasons)

    def test_adv_fail_flag(self):
        rec = _rec(attn_flags=["adv_fail"])
        eligible, reasons, _, _ = _compute_eligibility(rec, DEFAULT_RS)
        self.assertFalse(eligible)
        self.assertIn("adv_fail", reasons)

    def test_liquidity_fail_in_flags(self):
        rec = _rec(flags=["liquidity_fail_msg"])
        eligible, reasons, _, _ = _compute_eligibility(rec, DEFAULT_RS)
        self.assertFalse(eligible)
        self.assertIn("adv_fail", reasons)


# =============================================================================
# TestSizeBand
# =============================================================================


class TestSizeBand(unittest.TestCase):

    def test_ineligible_returns_xs(self):
        band, reasons = _compute_size_band(False, "C", 0.5, {}, DEFAULT_RS)
        self.assertEqual(band, "XS")
        self.assertIn("ineligible", reasons)

    def test_tier_a_high_optionality_l(self):
        band, reasons = _compute_size_band(True, "A", 0.65, {}, DEFAULT_RS)
        self.assertIn("tier_a_dev", reasons)
        # With tier_a_dev boost, idx starts 2 + 1 = 3 → L
        self.assertEqual(band, "L")

    def test_tier_a_commercial_quality_l(self):
        rs = DecisionRuleset(tier_a_commercial_floor=0.70)
        band, reasons = _compute_size_band(True, "A", None, {}, rs, commercial_quality_pct=0.80)
        self.assertIn("tier_a_commercial", reasons)

    def test_momentum_tailwind_upgrades(self):
        band_neutral, _ = _compute_size_band(True, "C", 0.2, {"mom_state": "neutral"}, DEFAULT_RS)
        band_tailwind, reasons = _compute_size_band(True, "C", 0.2, {"mom_state": "tailwind"}, DEFAULT_RS)
        self.assertIn("momentum_tailwind", reasons)
        # tailwind should be >= neutral band
        band_order = ["XS", "S", "M", "L"]
        self.assertGreaterEqual(band_order.index(band_tailwind), band_order.index(band_neutral))

    def test_momentum_headwind_downgrades(self):
        band, reasons = _compute_size_band(True, "C", 0.2, {"mom_state": "headwind"}, DEFAULT_RS)
        self.assertIn("momentum_headwind", reasons)
        # Base M (idx=2) - 1 = S
        self.assertEqual(band, "S")

    def test_runway_short_downgrades(self):
        band, reasons = _compute_size_band(True, "C", 0.2, {"runway_bucket": "short"}, DEFAULT_RS)
        self.assertIn("runway_short", reasons)
        self.assertEqual(band, "S")

    def test_high_risk_downgrades(self):
        band, reasons = _compute_size_band(True, "C", 0.2, {"risk_flags": "high_vol"}, DEFAULT_RS)
        self.assertIn("high_risk", reasons)
        self.assertEqual(band, "S")

    def test_missingness_penalties(self):
        rs = DecisionRuleset(enable_missingness_size_penalty=True)
        overlays = {
            "sponsor_tier1_count": None,
            "catalyst_mode": "missing",
        }
        band, reasons = _compute_size_band(True, "A", 0.65, overlays, rs)
        self.assertIn("missing_sponsor", reasons)
        self.assertIn("missing_catalyst", reasons)

    def test_soft_drawdown_penalty(self):
        rs = DecisionRuleset(drawdown_gate_mode="soft", drawdown_gate=-0.40, drawdown_size_penalty=-1)
        rec = _rec(defensive_features={"drawdown": -0.50})
        band, reasons = _compute_size_band(True, "C", 0.2, {}, rs, rec=rec)
        self.assertIn("drawdown_penalty", reasons)
        # Base M (idx=2) - 1 = S
        self.assertEqual(band, "S")

    def test_cost_haircut_band_step_down(self):
        band, reasons = _compute_size_band(True, "C", 0.2, {}, DEFAULT_RS, cost_mult=0.60, cost_bucket="<=2000bps")
        self.assertIn("cost_haircut_<=2000bps", reasons)
        self.assertEqual(band, "S")


# =============================================================================
# TestCostMult
# =============================================================================


class TestCostMult(unittest.TestCase):

    def test_cost_haircut_disabled(self):
        rs = DecisionRuleset(enable_cost_haircut=False)
        mult, label = _compute_cost_mult(100, rs)
        self.assertEqual(mult, 1.0)
        self.assertEqual(label, "")

    def test_below_first_bucket(self):
        rs = DecisionRuleset(
            enable_cost_haircut=True,
            cost_haircut_buckets=((30, 0.9), (100, 0.7)),
        )
        mult, label = _compute_cost_mult(5, rs)
        self.assertEqual(mult, 0.9)
        self.assertEqual(label, "<=30bps")

    def test_above_all_buckets(self):
        rs = DecisionRuleset(
            enable_cost_haircut=True,
            cost_haircut_buckets=((30, 0.9), (100, 0.7)),
            cost_haircut_floor_mult=0.50,
        )
        mult, label = _compute_cost_mult(500, rs)
        self.assertEqual(mult, 0.50)
        self.assertEqual(label, ">100bps")

    def test_none_cost(self):
        rs = DecisionRuleset(enable_cost_haircut=True)
        mult, label = _compute_cost_mult(None, rs)
        self.assertEqual(mult, 1.0)
        self.assertEqual(label, "")


# =============================================================================
# TestTierCommercial
# =============================================================================


class TestTierCommercial(unittest.TestCase):

    def test_non_commercial_archetype_returns_empty(self):
        tier, reason = _compute_tier_commercial("drug_developer", True, 0.90, "0", 0, DEFAULT_RS)
        self.assertEqual(tier, "")
        self.assertEqual(reason, "")

    def test_high_quality_actionable_catalyst_a(self):
        tier, reason = _compute_tier_commercial("commercial_biotech", True, 0.90, "0", 60, DEFAULT_RS)
        self.assertEqual(tier, "A")
        self.assertIn("high_quality", reason)

    def test_high_quality_far_catalyst_b(self):
        tier, reason = _compute_tier_commercial("commercial_biotech", True, 0.90, "0", 300, DEFAULT_RS)
        self.assertEqual(tier, "B")
        self.assertIn("high_quality", reason)

    def test_mod_quality_actionable_b(self):
        tier, reason = _compute_tier_commercial("commercial_pharma", True, 0.70, "0", 60, DEFAULT_RS)
        self.assertEqual(tier, "B")
        self.assertIn("mod_quality", reason)

    def test_low_quality_c(self):
        tier, reason = _compute_tier_commercial("commercial_biotech", True, 0.10, "0", 60, DEFAULT_RS)
        self.assertEqual(tier, "C")
        self.assertIn("low_quality", reason)

    def test_no_catalyst_data_high_quality_b(self):
        tier, reason = _compute_tier_commercial("commercial_biotech", True, 0.90, "0", 0, DEFAULT_RS)
        self.assertEqual(tier, "B")
        self.assertIn("no_catalyst_data", reason)

    def test_ineligible_d(self):
        tier, reason = _compute_tier_commercial("commercial_biotech", False, 0.90, "0", 60, DEFAULT_RS)
        self.assertEqual(tier, "D")
        self.assertEqual(reason, "ineligible")


# =============================================================================
# TestResolveCatalystStrength
# =============================================================================


class TestResolveCatalystStrength(unittest.TestCase):

    def test_no_data_missing(self):
        strength, actionable, has_data, tag = _resolve_catalyst_strength("0", 0, DEFAULT_RS)
        self.assertEqual(strength, "missing")
        self.assertFalse(actionable)
        self.assertFalse(has_data)

    def test_blended_window_near(self):
        strength, actionable, has_data, tag = _resolve_catalyst_strength("1", 0, DEFAULT_RS)
        self.assertEqual(strength, "near")
        self.assertTrue(actionable)
        self.assertTrue(has_data)
        self.assertEqual(tag, "catalyst_window")

    def test_specific_days_near(self):
        strength, actionable, has_data, tag = _resolve_catalyst_strength("0", 60, DEFAULT_RS)
        self.assertEqual(strength, "near")
        self.assertTrue(actionable)
        self.assertEqual(tag, "catalyst_near")

    def test_specific_days_mid(self):
        strength, actionable, has_data, tag = _resolve_catalyst_strength("0", 120, DEFAULT_RS)
        self.assertEqual(strength, "mid")
        self.assertTrue(actionable)
        self.assertEqual(tag, "catalyst_mid")

    def test_specific_days_far(self):
        strength, actionable, has_data, tag = _resolve_catalyst_strength("0", 300, DEFAULT_RS)
        self.assertEqual(strength, "far")
        self.assertFalse(actionable)
        self.assertEqual(tag, "catalyst_far")


# =============================================================================
# TestCatalystPriority
# =============================================================================


class TestCatalystPriority(unittest.TestCase):

    def test_no_data_default(self):
        pri = resolve_catalyst_priority("", "", DEFAULT_RS)
        self.assertEqual(pri, DEFAULT_RS.catalyst_priority_default)

    def test_unknown_returns_unknown_priority(self):
        pri = resolve_catalyst_priority("UNKNOWN", "CTGOV", DEFAULT_RS)
        self.assertEqual(pri, DEFAULT_RS.catalyst_priority_unknown)

    def test_matched_rule(self):
        pri = resolve_catalyst_priority("FDA_PDUFA_DATE", "SEC_8K_FILING", DEFAULT_RS)
        self.assertEqual(pri, 1)

    def test_no_rule_match_default(self):
        pri = resolve_catalyst_priority("SOME_RANDOM_TYPE", "SOME_RANDOM_SOURCE", DEFAULT_RS)
        self.assertEqual(pri, DEFAULT_RS.catalyst_priority_default)


if __name__ == "__main__":
    unittest.main()
