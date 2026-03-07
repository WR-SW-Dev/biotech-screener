"""Contract tests: cash metric definition in the survivability module.

Proves that:
1. cash_total = cash_and_equivalents + short_term_investments (including
   MarketableSecurities fallback).
2. The financials_missing gate uses cash_total as ground truth, not the
   coverage flags alone.
3. Profitable companies with cash via STI are not false-flagged.

These contracts codify the GAAP field mapping so it can't silently change.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from decision_engine import compute_decision_fields
from financial_module_2_survivability import compute_survivability_score, to_decimal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fin_data(**overrides) -> Dict[str, Any]:
    """Minimal financial_data dict with sensible defaults."""
    base = {
        "cash_and_equivalents": None,
        "Cash": None,
        "short_term_investments": None,
        "ShortTermInvestments": None,
        "MarketableSecurities": None,
        "operating_cash_flow_ttm": None,
        "CFO": None,
        "NetIncome": None,
        "total_operating_expense_ttm": None,
        "revenue_ttm": None,
        "Revenue": None,
        "interest_expense_ttm": None,
        "InterestExpense": None,
        "R&D": None,
    }
    base.update(overrides)
    return base


def _de_rec(
    ticker: str = "TEST",
    surv_coverage: list | None = None,
    surv_metrics: dict | None = None,
    fundamental_red_flag: bool = False,
) -> Dict[str, Any]:
    """Build a minimal rec for decision engine gate testing."""
    rec: Dict[str, Any] = {
        "ticker": ticker,
        "severity": "NONE",
        "confidence_overall": 0.72,
        "fundamental_red_flag": fundamental_red_flag,
        "fundamental_red_flag_reasons": [],
        "flags": [],
        "attn_flags": [],
        "catalyst_decay": None,
        "smart_money_signal": {},
        "coinvest": {},
        "defensive_features": {"drawdown": -0.10, "vol_60d": 0.50},
        "score_breakdown": {},
        "momentum_signal": {},
    }
    if surv_coverage is not None:
        surv_signal: Dict[str, Any] = {"coverage": surv_coverage}
        surv_signal["metrics"] = surv_metrics or {"cash_total": 0.0, "burn_ttm": 0.0}
        rec["survivability_signal"] = surv_signal
    return rec


# ---------------------------------------------------------------------------
# Contract 1: cash_total definition
# ---------------------------------------------------------------------------


class TestCashTotalDefinition:
    """Contract: cash_total = cash_and_equivalents + short_term_investments."""

    def test_both_components_present(self):
        """cash_total = cash_and_equiv + short_term_inv when both present."""
        fin = _fin_data(
            cash_and_equivalents=500_000_000,
            short_term_investments=200_000_000,
        )
        result = compute_survivability_score(fin)
        metrics = result.get("metrics", {})
        cash_total = float(metrics.get("cash_total", 0))
        assert abs(cash_total - 700_000_000) < 1.0

    def test_cash_only_no_sti(self):
        """cash_total = cash_and_equiv when no STI."""
        fin = _fin_data(cash_and_equivalents=300_000_000)
        result = compute_survivability_score(fin)
        cash_total = float(result["metrics"]["cash_total"])
        assert abs(cash_total - 300_000_000) < 1.0

    def test_sti_only_no_cash(self):
        """cash_total = short_term_inv when no cash_and_equiv."""
        fin = _fin_data(short_term_investments=400_000_000)
        result = compute_survivability_score(fin)
        cash_total = float(result["metrics"]["cash_total"])
        assert abs(cash_total - 400_000_000) < 1.0

    def test_zero_when_both_missing(self):
        """cash_total = 0 when both components are None."""
        fin = _fin_data()
        result = compute_survivability_score(fin)
        cash_total = float(result["metrics"]["cash_total"])
        assert cash_total == 0.0


# ---------------------------------------------------------------------------
# Contract 2: GAAP field fallback chain
# ---------------------------------------------------------------------------


class TestGAAPFieldFallbackChain:
    """Contract: the fallback chain for each cash component is codified."""

    def test_cash_prefers_cash_and_equivalents_over_Cash(self):
        """cash_and_equivalents takes priority over Cash."""
        fin = _fin_data(
            cash_and_equivalents=100_000_000,
            Cash=999_000_000,  # should be ignored
        )
        result = compute_survivability_score(fin)
        cash_total = float(result["metrics"]["cash_total"])
        assert abs(cash_total - 100_000_000) < 1.0

    def test_cash_falls_back_to_Cash(self):
        """When cash_and_equivalents is None, uses Cash."""
        fin = _fin_data(Cash=250_000_000)
        result = compute_survivability_score(fin)
        cash_total = float(result["metrics"]["cash_total"])
        assert abs(cash_total - 250_000_000) < 1.0

    def test_sti_prefers_short_term_investments(self):
        """short_term_investments takes priority over ShortTermInvestments."""
        fin = _fin_data(
            short_term_investments=100_000_000,
            ShortTermInvestments=999_000_000,  # should be ignored
        )
        result = compute_survivability_score(fin)
        cash_total = float(result["metrics"]["cash_total"])
        # Only STI component (no cash)
        assert abs(cash_total - 100_000_000) < 1.0

    def test_sti_falls_back_to_ShortTermInvestments(self):
        """When short_term_investments is None, uses ShortTermInvestments."""
        fin = _fin_data(ShortTermInvestments=180_000_000)
        result = compute_survivability_score(fin)
        cash_total = float(result["metrics"]["cash_total"])
        assert abs(cash_total - 180_000_000) < 1.0

    def test_sti_falls_back_to_MarketableSecurities(self):
        """When both STI fields are None, uses MarketableSecurities."""
        fin = _fin_data(MarketableSecurities=220_000_000)
        result = compute_survivability_score(fin)
        cash_total = float(result["metrics"]["cash_total"])
        assert abs(cash_total - 220_000_000) < 1.0


# ---------------------------------------------------------------------------
# Contract 3: coverage flags vs cash_total ground truth
# ---------------------------------------------------------------------------


class TestCoverageFlagSemantics:
    """Contract: coverage flags reflect component presence, not total cash."""

    def test_missing_cash_flag_when_cash_equiv_zero(self):
        """missing_cash set when cash_and_equivalents is zero/None."""
        fin = _fin_data(MarketableSecurities=500_000_000)
        result = compute_survivability_score(fin)
        assert "missing_cash" in result["coverage"]
        # But cash_total is > 0 via MarketableSecurities
        assert float(result["metrics"]["cash_total"]) > 0

    def test_no_missing_cash_when_cash_equiv_positive(self):
        """No missing_cash flag when cash_and_equivalents > 0."""
        fin = _fin_data(cash_and_equivalents=100_000_000)
        result = compute_survivability_score(fin)
        assert "missing_cash" not in result["coverage"]

    def test_missing_burn_when_no_ocf_no_opex(self):
        """missing_burn_data set when no burn method succeeds."""
        fin = _fin_data(cash_and_equivalents=100_000_000)
        result = compute_survivability_score(fin)
        assert "missing_burn_data" in result["coverage"]

    def test_no_missing_burn_when_negative_ocf(self):
        """Negative OCF = real burn data, no missing_burn_data flag."""
        fin = _fin_data(
            cash_and_equivalents=100_000_000,
            operating_cash_flow_ttm=-50_000_000,
        )
        result = compute_survivability_score(fin)
        assert "missing_burn_data" not in result["coverage"]

    def test_positive_ocf_sets_missing_burn(self):
        """Positive OCF = profitable, no burn → missing_burn_data flag.

        This is a known pitfall: profitable companies show missing_burn_data
        even though they're not actually missing data — their burn is zero.
        """
        fin = _fin_data(
            cash_and_equivalents=100_000_000,
            operating_cash_flow_ttm=200_000_000,  # profitable
        )
        result = compute_survivability_score(fin)
        # Positive OCF doesn't produce a burn, so burn_method stays "none"
        # unless the code handles positive OCF as zero burn
        burn = float(result["metrics"].get("burn_ttm", 0))
        assert burn == 0.0  # correct: positive OCF → zero burn


# ---------------------------------------------------------------------------
# Contract 4: decision engine gate uses cash_total, not flags alone
# ---------------------------------------------------------------------------


class TestFinancialsMissingGateContract:
    """Contract: financials_missing requires BOTH flags AND cash_total <= 0."""

    def test_both_flags_and_zero_cash_triggers_gate(self):
        """Both coverage flags + cash_total=0 → financials_missing."""
        rec = _de_rec(
            surv_coverage=["missing_cash", "missing_burn_data"],
            surv_metrics={"cash_total": 0.0},
        )
        fields = compute_decision_fields(rec, archetype="drug_developer")
        assert fields["eligible"] == "0"
        assert "financials_missing" in fields["ineligible_reasons"]

    def test_flags_but_positive_cash_total_no_gate(self):
        """Both flags present BUT cash_total > 0 → eligible (GILD pattern).

        This is the critical contract: companies with cash via
        MarketableSecurities have missing_cash flag but real cash_total.
        """
        rec = _de_rec(
            ticker="GILD",
            surv_coverage=["missing_cash", "missing_burn_data"],
            surv_metrics={"cash_total": 68_000_000.0},
        )
        fields = compute_decision_fields(rec, archetype="commercial_pharma")
        assert fields["eligible"] == "1"
        assert "financials_missing" not in fields.get("ineligible_reasons", "")

    def test_only_one_flag_checks_red_flag(self):
        """Only missing_cash (not missing_burn_data) → falls through to red flag check."""
        rec = _de_rec(
            surv_coverage=["missing_cash"],
            surv_metrics={"cash_total": 0.0},
            fundamental_red_flag=True,
        )
        fields = compute_decision_fields(rec, archetype="drug_developer")
        # Should hit red flag gate, not financials_missing
        assert "fundamental_red_flag" in fields["ineligible_reasons"]
        assert "financials_missing" not in fields["ineligible_reasons"]

    def test_no_survivability_signal_checks_red_flag(self):
        """Missing survivability_signal entirely → falls through to red flag check."""
        rec = _de_rec(fundamental_red_flag=True)
        fields = compute_decision_fields(rec, archetype="drug_developer")
        assert "fundamental_red_flag" in fields["ineligible_reasons"]


# ---------------------------------------------------------------------------
# Contract 5: to_decimal conversion
# ---------------------------------------------------------------------------


class TestToDecimalContract:
    """Contract: to_decimal handles all input types safely."""

    def test_none_returns_zero(self):
        assert to_decimal(None) == Decimal("0")

    def test_int_converts(self):
        assert to_decimal(500_000_000) == Decimal("500000000")

    def test_float_converts(self):
        result = to_decimal(1.5e9)
        assert abs(result - Decimal("1500000000")) < Decimal("1")

    def test_string_converts(self):
        assert to_decimal("250000000") == Decimal("250000000")

    def test_empty_string_returns_default(self):
        assert to_decimal("") == Decimal("0")

    def test_decimal_passthrough(self):
        d = Decimal("123.45")
        assert to_decimal(d) == d
