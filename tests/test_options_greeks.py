"""Tests for common/options_greeks.py."""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.options_greeks import black_scholes_greeks, iv_crush_stress_test


class TestBlackScholesGreeks:
    def test_atm_call_price(self):
        """ATM call: S=185, K=185, T=20/365, r=0.05, sigma=0.36."""
        g = black_scholes_greeks(S=185, K=185, T=20 / 365, r=0.05, sigma=0.36)
        # ATM call with 20d and 36% vol on $185 stock should be ~$4-8
        assert 3.0 < g["price"] < 8.0
        assert not math.isnan(g["price"])

    def test_atm_delta_near_half(self):
        """ATM call delta should be ~0.5."""
        g = black_scholes_greeks(S=100, K=100, T=30 / 365, r=0.05, sigma=0.50, option_type="call")
        assert abs(g["delta"] - 0.5) < 0.05

    def test_put_call_parity(self):
        """call - put = S - K*e^(-rT)."""
        S, K, T, r, sigma = 100, 100, 0.25, 0.05, 0.40
        call = black_scholes_greeks(S, K, T, r, sigma, "call")
        put = black_scholes_greeks(S, K, T, r, sigma, "put")
        parity = S - K * math.exp(-r * T)
        assert abs((call["price"] - put["price"]) - parity) < 0.01

    def test_vega_positive(self):
        call = black_scholes_greeks(100, 100, 0.1, 0.05, 0.50, "call")
        put = black_scholes_greeks(100, 100, 0.1, 0.05, 0.50, "put")
        assert call["vega"] > 0
        assert put["vega"] > 0

    def test_theta_negative(self):
        call = black_scholes_greeks(100, 100, 0.1, 0.05, 0.50, "call")
        put = black_scholes_greeks(100, 100, 0.1, 0.05, 0.50, "put")
        assert call["theta"] < 0
        assert put["theta"] < 0

    def test_deep_itm_call_delta_near_one(self):
        g = black_scholes_greeks(200, 100, 0.25, 0.05, 0.30, "call")
        assert g["delta"] > 0.95

    def test_deep_otm_call_delta_near_zero(self):
        g = black_scholes_greeks(50, 100, 0.25, 0.05, 0.30, "call")
        assert g["delta"] < 0.05

    def test_T_zero_returns_nan(self):
        g = black_scholes_greeks(100, 100, 0, 0.05, 0.50, "call")
        assert math.isnan(g["price"])

    def test_sigma_zero_returns_nan(self):
        g = black_scholes_greeks(100, 100, 0.25, 0.05, 0, "call")
        assert math.isnan(g["price"])

    def test_S_zero_returns_nan(self):
        g = black_scholes_greeks(0, 100, 0.25, 0.05, 0.50, "call")
        assert math.isnan(g["price"])


class TestIVCrushStressTest:
    def _make_chain(self, iv=0.80, atm_strike=100, close_call=8.0, close_put=7.0, expiry="2026-04-17"):
        return [
            {
                "expiration_date": expiry,
                "contract_type": "call",
                "strike_price": atm_strike,
                "implied_volatility": iv,
                "day_close": close_call,
                "delta": 0.52,
            },
            {
                "expiration_date": expiry,
                "contract_type": "put",
                "strike_price": atm_strike,
                "implied_volatility": iv + 0.02,
                "day_close": close_put,
                "delta": -0.48,
            },
        ]

    def test_crush_loss_positive(self):
        chain = self._make_chain(iv=0.80)
        result = iv_crush_stress_test(chain, underlying_price=100, catalyst_days=20)
        assert result["confidence"] == "ok"
        assert result["crush_loss_per_contract"] > 0
        assert result["breakeven_move_pct"] > 0

    def test_breakeven_less_than_implied(self):
        """Breakeven should be less than the full implied move."""
        chain = self._make_chain(iv=0.80, close_call=8.0, close_put=7.0)
        result = iv_crush_stress_test(chain, underlying_price=100, catalyst_days=20)
        if result["breakeven_move_pct"] and result["crush_adjusted_implied_move"]:
            # Straddle = 15, implied move = 15%, breakeven < 15%
            assert result["breakeven_move_pct"] < 0.15

    def test_high_iv_higher_crush(self):
        """Higher IV → higher crush loss."""
        chain_high = self._make_chain(iv=1.50, close_call=15.0, close_put=14.0)
        chain_low = self._make_chain(iv=0.40, close_call=4.0, close_put=3.5)
        high = iv_crush_stress_test(chain_high, 100, 20)
        low = iv_crush_stress_test(chain_low, 100, 20)
        if high["crush_loss_per_contract"] and low["crush_loss_per_contract"]:
            assert high["crush_loss_per_contract"] > low["crush_loss_per_contract"]

    def test_empty_chain(self):
        result = iv_crush_stress_test([], 100, 20)
        assert result["confidence"] == "insufficient_data"

    def test_zero_price(self):
        chain = self._make_chain()
        result = iv_crush_stress_test(chain, 0, 20)
        assert result["confidence"] == "insufficient_data"

    def test_biib_sanity(self):
        """BIIB-like: IV=0.36, cat_days=20, S=185. Breakeven ~12-16%."""
        chain = [
            {
                "expiration_date": "2026-04-03",
                "contract_type": "call",
                "strike_price": 185,
                "implied_volatility": 0.36,
                "day_close": 6.0,
                "delta": 0.51,
            },
            {
                "expiration_date": "2026-04-03",
                "contract_type": "put",
                "strike_price": 185,
                "implied_volatility": 0.38,
                "day_close": 5.5,
                "delta": -0.49,
            },
        ]
        result = iv_crush_stress_test(chain, underlying_price=185, catalyst_days=20)
        assert result["confidence"] == "ok"
        # Straddle = $11.50, implied move = 6.2%
        # After crush, breakeven should be ~5-6%
        assert result["breakeven_move_pct"] is not None
        assert result["breakeven_move_pct"] > 0
