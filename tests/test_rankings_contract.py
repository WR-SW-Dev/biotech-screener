"""Tests for the rankings.csv value-level data contract.

Synthetic fixtures only — no dependency on real snapshots, so CI is hermetic.
Data-contract/tooling only; no ranker/model/selector/sizing/final_score
behavior is exercised.
"""

import sys
from pathlib import Path

import pandas as pd

# Import the contract module by path (tools/ is not a package).
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "contracts"))

import rankings_contract as rc  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _good_base(n: int = 60) -> pd.DataFrame:
    """n-ticker cohort (ranks 1..n) with valid gate fields and positive prices."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "ticker": f"TK{i:03d}",
                "actionable_rank": str(i + 1),
                "final_score": str(0.10 + 0.001 * i),
                "composite_score": str(0.20 + 0.001 * i),
                "close_price": str(100.0 + i),
                "catalyst_decay_w": str(0.3),
                "catalyst_score": str(0.4),
                "coinvest_score_z": str(0.5),
                "financial_score": str(0.6),
            }
        )
    return pd.DataFrame(rows)


def _good_forward(base: pd.DataFrame, bump: float = 1.0, spread: float = 0.5) -> pd.DataFrame:
    """Forward snapshot with distinct, varied prices (non-degenerate returns)."""
    fwd = base.copy()
    fwd["close_price"] = [str(100.0 + bump + spread * i) for i in range(len(base))]
    return fwd


# ---------------------------------------------------------------------------
# Schema / required fields
# ---------------------------------------------------------------------------


class TestSchema:
    def test_missing_required_column_fails(self):
        df = _good_base().drop(columns=["financial_score"])
        v = rc.validate_rankings_schema(df)
        assert any("financial_score" in x for x in v)

    def test_missing_actionable_rank_fails(self):
        df = _good_base().drop(columns=["actionable_rank"])
        v = rc.validate_rankings_schema(df)
        assert any("actionable_rank" in x for x in v)

    def test_duplicate_ticker_fails(self):
        df = _good_base()
        df.loc[1, "ticker"] = "TK000"  # dup of row 0
        v = rc.validate_rankings_schema(df)
        assert any("duplicate" in x.lower() for x in v)

    def test_non_numeric_rank_fails(self):
        df = _good_base()
        df.loc[0, "actionable_rank"] = "not_a_number"
        v = rc.validate_rankings_schema(df)
        assert any("non-numeric actionable_rank" in x for x in v)

    def test_clean_schema_passes(self):
        assert rc.validate_rankings_schema(_good_base()) == []


# ---------------------------------------------------------------------------
# Cohort
# ---------------------------------------------------------------------------


class TestCohort:
    def test_cohort_size_60_passes(self):
        assert rc.validate_cohort(_good_base(60), expect_cohort=60) == []

    def test_cohort_size_59_fails(self):
        v = rc.validate_cohort(_good_base(59), expect_cohort=60)
        assert any("cohort size 59" in x for x in v)

    def test_null_final_score_in_cohort_fails(self):
        df = _good_base(60)
        df.loc[5, "final_score"] = ""
        v = rc.validate_cohort(df)
        assert any("final_score" in x for x in v)

    def test_close_price_non_positive_fails(self):
        df = _good_base(60)
        df.loc[7, "close_price"] = "0"
        v = rc.validate_cohort(df)
        assert any("close_price <= 0" in x for x in v)

    def test_null_close_price_in_cohort_fails(self):
        df = _good_base(60)
        df.loc[3, "close_price"] = ""
        v = rc.validate_cohort(df)
        assert any("close_price" in x for x in v)


# ---------------------------------------------------------------------------
# Forward pair
# ---------------------------------------------------------------------------


class TestForwardPair:
    def test_valid_forward_pair_ok(self):
        base = _good_base(60)
        fwd = _good_forward(base)
        status, n, reason = rc.validate_forward_pair(base, fwd, "2026-07-08")
        assert status == "OK"
        assert n == 60
        assert reason is None

    def test_observed_date_none_unobservable(self):
        base = _good_base(60)
        status, n, reason = rc.validate_forward_pair(base, None, None)
        assert status == "UNOBSERVABLE"
        assert n == 0
        assert reason

    def test_too_few_pairs_unobservable(self):
        base = _good_base(60)
        # forward has only 3 tickers in common → < MIN_IC_PAIRS
        fwd = _good_forward(base).iloc[:3].copy()
        status, n, reason = rc.validate_forward_pair(base, fwd, "2026-07-08")
        assert status == "UNOBSERVABLE"
        assert n < rc.MIN_IC_PAIRS
        assert "cannot compute IC" in reason


# ---------------------------------------------------------------------------
# Freshness / variance warnings
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_identical_prices_warn_not_fail(self):
        base = _good_base(60)
        fwd = base.copy()  # identical close_price → all returns 0
        warns = rc.check_freshness(base, fwd, "2026-07-08")
        assert any("identical" in w or "zero variance" in w for w in warns)
        # And it must NOT be a hard violation:
        result = rc.run_contract(base, fwd_df=fwd, observed_forward_date="2026-07-08")
        assert result.status == "PASS"
        assert result.warnings

    def test_good_variance_no_warning(self):
        base = _good_base(60)
        fwd = _good_forward(base)
        assert rc.check_freshness(base, fwd, "2026-07-08") == []

    def test_fallback_gap_beyond_tolerance_warns(self):
        base = _good_base(60)
        fwd = _good_forward(base)
        warns = rc.check_freshness(
            base,
            fwd,
            observed_forward_date="2026-07-20",
            requested_forward_date="2026-07-08",
            fallback_tolerance_days=7,
        )
        assert any("fallback" in w for w in warns)


# ---------------------------------------------------------------------------
# Orchestrator precedence
# ---------------------------------------------------------------------------


class TestRunContract:
    def test_clean_full_contract_passes(self):
        base = _good_base(60)
        fwd = _good_forward(base)
        result = rc.run_contract(base, fwd_df=fwd, observed_forward_date="2026-07-08")
        assert result.status == "PASS"
        assert result.violations == []

    def test_missing_forward_is_unobservable_not_fail(self):
        base = _good_base(60)
        result = rc.run_contract(base, fwd_df=None, observed_forward_date=None)
        assert result.status == "UNOBSERVABLE"
        assert result.unobservable_reason

    def test_base_violation_dominates_unobservable(self):
        # Bad cohort (size 59) + no forward → FAIL takes precedence over UNOBSERVABLE.
        base = _good_base(59)
        result = rc.run_contract(base, fwd_df=None, observed_forward_date=None, expect_cohort=60)
        assert result.status == "FAIL"
        assert any("cohort size 59" in v for v in result.violations)
