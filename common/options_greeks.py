"""Black-Scholes Greeks and IV crush stress testing.

Provides:
1. black_scholes_greeks() — analytical Greeks from BS model
2. iv_crush_stress_test() — biotech-specific: breakeven move after IV crush

Uses scipy.stats.norm for CDF/PDF. Does not reimplement.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from scipy.stats import norm


def black_scholes_greeks(
    S: float,
    K: float,
    T: float,
    r: float = 0.05,
    sigma: float = 0.50,
    option_type: str = "call",
) -> Dict[str, Any]:
    """Compute Black-Scholes price and Greeks.

    Args:
        S: Underlying price.
        K: Strike price.
        T: Time to expiry in years (catalyst_days / 365).
        r: Risk-free rate (default 5%).
        sigma: Implied volatility (annualized).
        option_type: "call" or "put".

    Returns:
        Dict with price, delta, gamma, vega (per 1% IV), theta (per day),
        rho, d1, d2. Returns nans on invalid inputs.
    """
    nan_result: Dict[str, Any] = {
        "price": float("nan"),
        "delta": float("nan"),
        "gamma": float("nan"),
        "vega": float("nan"),
        "theta": float("nan"),
        "rho": float("nan"),
        "d1": float("nan"),
        "d2": float("nan"),
    }

    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return nan_result

    try:
        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        exp_rT = math.exp(-r * T)
        nd1 = norm.cdf(d1)
        nd2 = norm.cdf(d2)
        pdf_d1 = norm.pdf(d1)

        if option_type == "call":
            price = S * nd1 - K * exp_rT * nd2
            delta = nd1
            rho = K * T * exp_rT * nd2 / 100
        else:
            price = K * exp_rT * norm.cdf(-d2) - S * norm.cdf(-d1)
            delta = nd1 - 1.0
            rho = -K * T * exp_rT * norm.cdf(-d2) / 100

        gamma = pdf_d1 / (S * sigma * sqrt_T)
        vega = S * pdf_d1 * sqrt_T / 100  # per 1% IV change
        theta = (
            -(S * pdf_d1 * sigma) / (2 * sqrt_T) - r * K * exp_rT * (nd2 if option_type == "call" else norm.cdf(-d2))
        ) / 365  # per calendar day

        return {
            "price": round(price, 6),
            "delta": round(delta, 6),
            "gamma": round(gamma, 6),
            "vega": round(vega, 6),
            "theta": round(theta, 6),
            "rho": round(rho, 6),
            "d1": round(d1, 6),
            "d2": round(d2, 6),
        }
    except (ValueError, ZeroDivisionError, OverflowError):
        return nan_result


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """BS price only (no Greeks), for use in the IV solver inner loop."""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return float("nan")
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    if option_type == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.05,
    option_type: str = "call",
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float:
    """Solve for implied volatility using Brent's method.

    Given observed option market price and BS inputs, find the sigma
    that makes BS_price(sigma) = market_price.

    Args:
        market_price: Observed option close price.
        S: Underlying price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate.
        option_type: "call" or "put".
        tol: Convergence tolerance.
        max_iter: Maximum iterations.

    Returns:
        Implied volatility (annualized), or NaN if solver fails.
    """
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return float("nan")

    # Intrinsic value check — price must exceed intrinsic
    if option_type == "call":
        intrinsic = max(S - K * math.exp(-r * T), 0)
    else:
        intrinsic = max(K * math.exp(-r * T) - S, 0)
    if market_price < intrinsic - tol:
        return float("nan")

    try:
        from scipy.optimize import brentq

        def objective(sigma: float) -> float:
            return _bs_price(S, K, T, r, sigma, option_type) - market_price

        # Search in [0.01, 10.0] — covers 1% to 1000% annualized IV
        return brentq(objective, 0.01, 10.0, xtol=tol, maxiter=max_iter)
    except (ValueError, RuntimeError):
        return float("nan")


def compute_historical_greeks(
    option_close: float,
    underlying_close: float,
    strike: float,
    days_to_expiry: int,
    option_type: str,
    r: float = 0.05,
) -> Dict[str, Any]:
    """Compute full Greeks from a historical option close price.

    Solves for implied vol from the market price, then computes all
    BS Greeks at that IV. This is the core function for building
    historical IV surfaces and Greek time series from Massive day aggs.

    Args:
        option_close: Historical option close price (from day aggs).
        underlying_close: Historical underlying close (from price_history.csv).
        strike: Strike price (parsed from option ticker).
        days_to_expiry: Calendar days to expiry on that date.
        option_type: "call" or "put".
        r: Risk-free rate.

    Returns:
        Dict with implied_vol plus all BS Greeks, or nans on failure.
    """
    T = days_to_expiry / 365.0 if days_to_expiry > 0 else 0.0

    iv = implied_volatility(option_close, underlying_close, strike, T, r, option_type)
    if math.isnan(iv):
        return {
            "implied_vol": float("nan"),
            "price": option_close,
            "delta": float("nan"),
            "gamma": float("nan"),
            "vega": float("nan"),
            "theta": float("nan"),
        }

    greeks = black_scholes_greeks(underlying_close, strike, T, r, iv, option_type)
    greeks["implied_vol"] = round(iv, 6)
    return greeks


def parse_option_ticker(ticker: str) -> Dict[str, Any]:
    """Parse an OCC/OPRA option ticker into components.

    Format: O:BIIB260403C00200000
    → underlying=BIIB, expiry=2026-04-03, type=call, strike=200.00

    Returns dict with underlying, expiry_str, option_type, strike.
    """
    t = ticker
    if t.startswith("O:"):
        t = t[2:]
    if len(t) < 15:
        return {"underlying": "", "expiry_str": "", "option_type": "", "strike": 0.0}

    # Underlying: letters at start
    i = 0
    while i < len(t) and t[i].isalpha():
        i += 1
    underlying = t[:i].upper()
    rest = t[i:]

    if len(rest) < 15:
        return {"underlying": underlying, "expiry_str": "", "option_type": "", "strike": 0.0}

    # Date: 6 digits YYMMDD
    date_part = rest[:6]
    try:
        yy = int(date_part[:2])
        mm = int(date_part[2:4])
        dd = int(date_part[4:6])
        expiry_str = f"20{yy:02d}-{mm:02d}-{dd:02d}"
    except (ValueError, IndexError):
        expiry_str = ""

    # Type: C or P
    type_char = rest[6] if len(rest) > 6 else ""
    option_type = "call" if type_char == "C" else "put" if type_char == "P" else ""

    # Strike: 8 digits, divide by 1000
    strike_str = rest[7:15] if len(rest) >= 15 else ""
    try:
        strike = int(strike_str) / 1000.0
    except (ValueError, IndexError):
        strike = 0.0

    return {
        "underlying": underlying,
        "expiry_str": expiry_str,
        "option_type": option_type,
        "strike": strike,
    }


def iv_crush_stress_test(
    chain_contracts: List[Dict[str, Any]],
    underlying_price: float,
    catalyst_days: int,
    post_crush_iv_ratio: float = 0.45,
    risk_free_rate: float = 0.05,
) -> Dict[str, Any]:
    """IV crush stress test for biotech binary catalysts.

    Computes breakeven stock move required to overcome IV crush on an
    ATM straddle position. The post_crush_iv_ratio is the fraction of
    pre-event IV assumed to remain after the event resolves (default 0.45
    = IV drops to 45% of pre-event level, calibrated to PDUFA/readout
    events — should be tuned per catalyst type when outcome data permits).

    Args:
        chain_contracts: Massive chain snapshot (list of contract dicts).
        underlying_price: Current underlying close price.
        catalyst_days: Days to catalyst event.
        post_crush_iv_ratio: Post-event IV as fraction of pre-event.
        risk_free_rate: Risk-free rate.

    Returns:
        Dict with crush metrics and confidence flag.
    """
    empty: Dict[str, Any] = {
        "pre_crush_straddle": None,
        "post_crush_straddle": None,
        "crush_loss_per_contract": None,
        "breakeven_move_pct": None,
        "crush_adjusted_implied_move": None,
        "post_crush_iv": None,
        "expiry_used": None,
        "atm_strike": None,
        "confidence": "insufficient_data",
    }

    if not chain_contracts or underlying_price <= 0 or catalyst_days <= 0:
        return empty

    # Find ATM call and put for the nearest relevant expiry
    from common.massive_chain_analytics import find_atm_contracts

    # Get available expiries
    expiries = sorted(set(c.get("expiration_date", "") for c in chain_contracts if c.get("expiration_date")))
    if not expiries:
        return empty

    # Pick expiry that best brackets the catalyst date
    from datetime import date, timedelta

    try:
        event_date = date.today() + timedelta(days=catalyst_days)
    except (ValueError, OverflowError):
        return empty

    event_str = event_date.isoformat()
    # Find first expiry on or after the event
    target_expiry = None
    for exp in expiries:
        if exp >= event_str:
            target_expiry = exp
            break
    if target_expiry is None:
        target_expiry = expiries[-1]  # use last if all before event

    atm_call, atm_put = find_atm_contracts(chain_contracts, underlying_price, target_expiry)
    if atm_call is None or atm_put is None:
        empty["confidence"] = "no_atm_data"
        return empty

    # Pre-crush: use actual chain prices if available, else BS model
    call_price = atm_call.get("day_close")
    put_price = atm_put.get("day_close")
    call_iv = atm_call.get("implied_volatility")
    put_iv = atm_put.get("implied_volatility")

    if call_iv is None or put_iv is None:
        empty["confidence"] = "no_iv_data"
        return empty

    atm_iv = (call_iv + put_iv) / 2
    atm_strike = atm_call.get("strike_price", underlying_price)
    T = catalyst_days / 365.0

    # Pre-crush straddle: prefer actual prices, fall back to BS
    if call_price and put_price and call_price > 0 and put_price > 0:
        pre_straddle = call_price + put_price
    else:
        bs_call = black_scholes_greeks(underlying_price, atm_strike, T, risk_free_rate, atm_iv, "call")
        bs_put = black_scholes_greeks(underlying_price, atm_strike, T, risk_free_rate, atm_iv, "put")
        pre_straddle = bs_call["price"] + bs_put["price"]
        if math.isnan(pre_straddle):
            return empty

    # Post-crush: BS model at reduced IV, T≈1 day (event just happened)
    post_iv = atm_iv * post_crush_iv_ratio
    T_post = 1 / 365.0  # day-of pricing
    bs_call_post = black_scholes_greeks(underlying_price, atm_strike, T_post, risk_free_rate, post_iv, "call")
    bs_put_post = black_scholes_greeks(underlying_price, atm_strike, T_post, risk_free_rate, post_iv, "put")
    post_straddle = bs_call_post["price"] + bs_put_post["price"]
    if math.isnan(post_straddle):
        post_straddle = 0.0

    crush_loss = pre_straddle - post_straddle
    breakeven_move = crush_loss / underlying_price if underlying_price > 0 else None
    implied_move = pre_straddle / underlying_price if underlying_price > 0 else None
    crush_adj_move = (implied_move - breakeven_move) if implied_move and breakeven_move else None

    return {
        "pre_crush_straddle": round(pre_straddle, 4),
        "post_crush_straddle": round(post_straddle, 4),
        "crush_loss_per_contract": round(crush_loss * 100, 2),  # per 100 shares
        "breakeven_move_pct": round(breakeven_move, 4) if breakeven_move else None,
        "crush_adjusted_implied_move": round(crush_adj_move, 4) if crush_adj_move else None,
        "post_crush_iv": round(post_iv, 4),
        "expiry_used": target_expiry,
        "atm_strike": atm_strike,
        "confidence": "ok",
    }
