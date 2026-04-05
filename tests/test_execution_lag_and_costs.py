"""Tests for execution lag and liquidity-aware cost model.

Verifies:
  1. Forward returns with execution_lag=1 start one trading day later
  2. Liquidity-aware cost model produces per-name costs from ADV
  3. Cost estimates are monotonically decreasing in ADV
  4. Portfolio average cost function works for EW portfolios
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.cost_model import CostSchedule, estimate_portfolio_cost_bps, estimate_trade_cost


class TestLiquidityAwareCosts:
    """Verify the ADV-based cost model."""

    def test_higher_adv_lower_cost(self):
        """More liquid names should have lower costs."""
        low_adv = estimate_trade_cost(3.33, 500_000)  # $500K ADV
        high_adv = estimate_trade_cost(3.33, 50_000_000)  # $50M ADV
        assert high_adv.one_way_bps < low_adv.one_way_bps

    def test_zero_adv_returns_zero(self):
        """Zero ADV should return zero cost (not crash)."""
        est = estimate_trade_cost(3.33, 0)
        assert est.one_way_bps == 0.0

    def test_spread_schedule_tiers(self):
        """Spread should step down at ADV breakpoints."""
        est_500k = estimate_trade_cost(3.33, 500_000)
        est_1m = estimate_trade_cost(3.33, 1_000_000)
        est_10m = estimate_trade_cost(3.33, 10_000_000)
        assert est_500k.spread_bps > est_1m.spread_bps
        assert est_1m.spread_bps > est_10m.spread_bps

    def test_impact_cap_binds(self):
        """Impact should be capped at impact_cap_bps."""
        # Tiny ADV with huge position → impact should cap
        est = estimate_trade_cost(10.0, 100, CostSchedule(aum_dollars=50_000_000))
        assert est.impact_bps <= 200.0

    def test_portfolio_cost_function(self):
        """estimate_portfolio_cost_bps returns a reasonable average."""
        advs = [1_000_000, 5_000_000, 50_000_000]
        avg = estimate_portfolio_cost_bps(advs, 3, CostSchedule(aum_dollars=500_000))
        assert 5 < avg < 200  # reasonable range

    def test_portfolio_cost_fills_missing(self):
        """Missing ADV names get worst-tier cost."""
        # 2 names with ADV, but n_positions=5 → 3 get worst cost
        advs = [50_000_000, 50_000_000]
        avg = estimate_portfolio_cost_bps(advs, 5, CostSchedule(aum_dollars=500_000))
        # Should be higher than if all 5 had good ADV
        avg_all = estimate_portfolio_cost_bps([50_000_000] * 5, 5, CostSchedule(aum_dollars=500_000))
        assert avg > avg_all


class TestExecutionLag:
    """Verify the research panel builder's execution lag parameter."""

    def test_lag_shifts_start_by_one(self):
        """execution_lag=1 should use idx+1 as start price."""
        from scripts.research.build_signal_research_panel import forward_return

        prices = {
            "2024-01-01": 100.0,
            "2024-01-02": 102.0,
            "2024-01-03": 105.0,
            "2024-01-04": 103.0,
        }
        sorted_dates = sorted(prices.keys())

        # lag=0: start at 2024-01-01 (100), end at 2024-01-03 (105) → 5%
        ret_no_lag = forward_return(prices, sorted_dates, "2024-01-01", 2, execution_lag=0)
        assert ret_no_lag == pytest.approx(0.05, abs=0.001)

        # lag=1: start at 2024-01-02 (102), end at 2024-01-04 (103) → ~0.98%
        ret_lag = forward_return(prices, sorted_dates, "2024-01-01", 2, execution_lag=1)
        assert ret_lag == pytest.approx((103 - 102) / 102, abs=0.001)

    def test_lag_default_is_one(self):
        """Default execution_lag should be 1 (next-trading-day)."""
        from scripts.research.build_signal_research_panel import forward_return

        prices = {
            "2024-01-01": 100.0,
            "2024-01-02": 102.0,
            "2024-01-03": 105.0,
        }
        sorted_dates = sorted(prices.keys())

        # Default (lag=1): start at 01-02, 1-day horizon → 01-03
        ret = forward_return(prices, sorted_dates, "2024-01-01", 1)
        assert ret == pytest.approx((105 - 102) / 102, abs=0.001)

    def test_lag_returns_none_if_insufficient_data(self):
        """If lag pushes past available data, return None."""
        from scripts.research.build_signal_research_panel import forward_return

        prices = {"2024-01-01": 100.0, "2024-01-02": 102.0}
        sorted_dates = sorted(prices.keys())

        # lag=1 + horizon=1 needs 3 dates, only have 2
        ret = forward_return(prices, sorted_dates, "2024-01-01", 1, execution_lag=1)
        assert ret is None
