"""Tests for transaction cost and rebalance threshold model."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.rebalance_cost_model import (
    apply_rebalance_threshold,
    compute_turnover_cost_drag,
    estimate_historical_cost_drag,
    estimate_portfolio_trade_cost,
    estimate_trade_cost_bps,
)


class TestTradeCostEstimation:
    def test_mega_cap_low_cost(self):
        c = estimate_trade_cost_bps(market_cap_mm=15000, avg_dollar_volume=50_000_000)
        assert c["total_bps"] <= 15  # mega + high ADV = cheap
        assert c["mcap_bucket"] == "mega"
        assert c["adv_bucket"] == "high"

    def test_micro_cap_high_cost(self):
        c = estimate_trade_cost_bps(market_cap_mm=50, avg_dollar_volume=50_000)
        assert c["total_bps"] >= 100  # micro + micro ADV = expensive
        assert c["mcap_bucket"] == "micro"
        assert c["adv_bucket"] == "micro"

    def test_mid_cap_medium(self):
        c = estimate_trade_cost_bps(market_cap_mm=800, avg_dollar_volume=3_000_000)
        assert 20 < c["total_bps"] < 60
        assert c["mcap_bucket"] == "mid"
        assert c["adv_bucket"] == "medium"

    def test_missing_data_conservative(self):
        c = estimate_trade_cost_bps()
        assert c["total_bps"] >= 100  # defaults to micro/micro

    def test_components_sum(self):
        c = estimate_trade_cost_bps(market_cap_mm=1000, avg_dollar_volume=5_000_000)
        assert c["total_bps"] == c["spread_bps"] + c["impact_bps"]


class TestPortfolioTradeCost:
    def test_basic_portfolio(self):
        trades = [
            {"ticker": "BIIB", "trade_dollars": 25000, "market_cap_mm": 30000, "avg_dollar_volume": 200_000_000},
            {"ticker": "SRPT", "trade_dollars": 15000, "market_cap_mm": 8000, "avg_dollar_volume": 50_000_000},
        ]
        result = estimate_portfolio_trade_cost(trades, 500_000)
        assert result["total_cost_dollars"] > 0
        assert result["n_trades"] == 2
        assert len(result["breakdown"]) == 2

    def test_zero_trades(self):
        result = estimate_portfolio_trade_cost([], 500_000)
        assert result["total_cost_dollars"] == 0
        assert result["n_trades"] == 0

    def test_skip_zero_notional(self):
        trades = [{"ticker": "X", "trade_dollars": 0}]
        result = estimate_portfolio_trade_cost(trades)
        assert result["n_trades"] == 0


class TestTurnoverCostDrag:
    def test_no_change(self):
        positions = [{"ticker": "A", "weight_pct": 50}, {"ticker": "B", "weight_pct": 50}]
        result = compute_turnover_cost_drag(positions, positions)
        assert result["total_cost_dollars"] == 0
        assert result["n_added"] == 0
        assert result["n_removed"] == 0

    def test_full_turnover(self):
        prior = [{"ticker": "A", "weight_pct": 50}, {"ticker": "B", "weight_pct": 50}]
        current = [{"ticker": "C", "weight_pct": 50}, {"ticker": "D", "weight_pct": 50}]
        result = compute_turnover_cost_drag(prior, current)
        assert result["n_added"] == 2
        assert result["n_removed"] == 2
        assert result["total_cost_dollars"] > 0
        assert result["weight_turnover_pct"] > 0

    def test_partial_turnover(self):
        prior = [{"ticker": "A", "weight_pct": 50}, {"ticker": "B", "weight_pct": 50}]
        current = [{"ticker": "A", "weight_pct": 50}, {"ticker": "C", "weight_pct": 50}]
        result = compute_turnover_cost_drag(prior, current)
        assert result["n_added"] == 1
        assert result["n_removed"] == 1
        assert result["n_overlap"] == 1


class TestRebalanceThreshold:
    def test_dont_rebalance_small_alpha(self):
        prior = [{"ticker": "A", "weight_pct": 50}, {"ticker": "B", "weight_pct": 50}]
        proposed = [{"ticker": "C", "weight_pct": 50}, {"ticker": "D", "weight_pct": 50}]
        result = apply_rebalance_threshold(prior, proposed, expected_alpha_bps=5, cost_multiplier=2.0)
        # Full turnover should be expensive — 5 bps alpha shouldn't justify it
        assert result["should_rebalance"] is False
        assert result["positions_to_use"] == prior

    def test_rebalance_with_large_alpha(self):
        prior = [{"ticker": "A", "weight_pct": 50}, {"ticker": "B", "weight_pct": 50}]
        proposed = [{"ticker": "A", "weight_pct": 60}, {"ticker": "B", "weight_pct": 40}]
        result = apply_rebalance_threshold(prior, proposed, expected_alpha_bps=500, cost_multiplier=2.0)
        assert result["should_rebalance"] is True
        assert result["positions_to_use"] == proposed

    def test_required_fields(self):
        result = apply_rebalance_threshold(
            [{"ticker": "A", "weight_pct": 100}],
            [{"ticker": "B", "weight_pct": 100}],
        )
        assert "should_rebalance" in result
        assert "estimated_cost_bps" in result
        assert "threshold_bps" in result
        assert "positions_to_use" in result


class TestHistoricalCostDrag:
    def test_basic_drag(self):
        periods = [
            {"date": "2026-01-02", "turnover": 0.2, "n_held": 20},
            {"date": "2026-01-03", "turnover": 0.1, "n_held": 20},
        ]
        result = estimate_historical_cost_drag(periods, avg_cost_bps=50)
        assert result["total_cost_drag_pct"] > 0
        assert result["n_periods"] == 2
        # 0.2 * 20 = 4 names * 100bps RT / 10000 = 0.04%
        # 0.1 * 20 = 2 names * 100bps RT / 10000 = 0.02%
        # Total = 0.06%
        assert abs(result["total_cost_drag_pct"] - 0.06) < 0.001

    def test_zero_turnover(self):
        periods = [{"date": "2026-01-02", "turnover": 0, "n_held": 20}]
        result = estimate_historical_cost_drag(periods)
        assert result["total_cost_drag_pct"] == 0

    def test_empty_periods(self):
        result = estimate_historical_cost_drag([])
        assert result["n_periods"] == 0
        assert result["total_cost_drag_pct"] == 0
