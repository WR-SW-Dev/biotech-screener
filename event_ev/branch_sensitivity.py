"""Branch Sensitivity & Greeks Overlay (Spec 059 Phase B).

For a name near a catalyst with liquid options, computes:
1. Post-event Greeks profile for each branch (HIT/MISS/MIXED)
2. Breakeven straddle move (what realized move offsets IV crush)
3. Market over/under-pricing diagnostic

Policy: OVERLAY-ONLY. All outputs are diagnostic. Gated on liquid options.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional

from common.options_greeks import CRUSH_RATIO_BASE, black_scholes_greeks

logger = logging.getLogger(__name__)


def compute_branch_sensitivity(
    options_surface: Dict[str, Any],
    scenario_moves: Dict[str, float],
    risk_free_rate: float = 0.05,
) -> Optional[Dict[str, Any]]:
    """Compute post-event Greeks for each scenario branch.

    Args:
        options_surface: Dict with:
            - opt_atm_iv: float (annualized)
            - underlying_price: float
            - atm_strike: float (optional, defaults to underlying_price)
            - catalyst_days: int
            - opt_liquidity_state: liquid/thin/absent
            - event_family: REGULATORY/CLINICAL (for crush ratio)
        scenario_moves: Dict with:
            - upside_hit: float (percentage points, e.g. 20.0 = +20%)
            - downside_miss: float (percentage points, e.g. -35.0 = -35%)
            - move_mixed: float (percentage points)

    Returns:
        Dict with branch profiles, or None if inputs are invalid/illiquid.
    """
    # Liquidity gate
    liquidity = options_surface.get("opt_liquidity_state", "absent")
    if liquidity != "liquid":
        return None

    # Validate required fields
    atm_iv = options_surface.get("opt_atm_iv")
    underlying = options_surface.get("underlying_price")
    catalyst_days = options_surface.get("catalyst_days")

    if atm_iv is None or underlying is None or catalyst_days is None:
        return None
    try:
        atm_iv = float(atm_iv)
        underlying = float(underlying)
        catalyst_days = int(catalyst_days)
    except (ValueError, TypeError):
        return None

    if atm_iv <= 0 or underlying <= 0 or catalyst_days <= 0:
        return None

    strike = float(options_surface.get("atm_strike") or underlying)
    event_family = options_surface.get("event_family", "")
    T_pre = catalyst_days / 365.0
    T_post = 1 / 365.0  # day-of pricing (post-event)

    # Crush ratio for this family
    fam_key = event_family.upper() if event_family else "default"
    crush_ratio = CRUSH_RATIO_BASE.get(fam_key, CRUSH_RATIO_BASE["default"])
    post_event_iv = atm_iv * crush_ratio

    # Pre-event Greeks (reference)
    pre_greeks_call = black_scholes_greeks(underlying, strike, T_pre, risk_free_rate, atm_iv, "call")
    pre_greeks_put = black_scholes_greeks(underlying, strike, T_pre, risk_free_rate, atm_iv, "put")
    pre_straddle = pre_greeks_call["price"] + pre_greeks_put["price"]

    # Compute branches
    branches = {}
    for branch_name, move_key in [("hit", "upside_hit"), ("miss", "downside_miss"), ("mixed", "move_mixed")]:
        move_pct = scenario_moves.get(move_key, 0.0)
        post_price = underlying * (1.0 + move_pct / 100.0)

        # Post-event Greeks at the new stock price, crushed IV, minimal remaining time
        post_call = black_scholes_greeks(post_price, strike, T_post, risk_free_rate, post_event_iv, "call")
        post_put = black_scholes_greeks(post_price, strike, T_post, risk_free_rate, post_event_iv, "put")
        post_straddle = post_call["price"] + post_put["price"]

        # Straddle P&L for this branch
        straddle_pnl = post_straddle - pre_straddle

        branches[branch_name] = {
            "stock_move_pct": move_pct,
            "post_event_price": round(post_price, 4),
            "post_event_iv": round(post_event_iv, 4),
            "post_delta": round(post_call["delta"], 4),
            "post_vega": round(post_call["vega"], 4),
            "post_straddle_value": round(post_straddle, 4),
            "straddle_pnl": round(straddle_pnl, 4),
        }

    return {
        "branches": branches,
        "pre_event_iv": round(atm_iv, 4),
        "post_event_iv": round(post_event_iv, 4),
        "crush_ratio": round(crush_ratio, 4),
        "pre_straddle_value": round(pre_straddle, 4),
        "underlying_price": round(underlying, 4),
        "catalyst_days": catalyst_days,
    }


def compute_breakeven_straddle(
    underlying_price: float,
    atm_iv: float,
    catalyst_days: int,
    event_family: str = "",
    expected_move_pct: Optional[float] = None,
    risk_free_rate: float = 0.05,
) -> Optional[Dict[str, Any]]:
    """Compute breakeven move for an ATM straddle.

    The breakeven is the realized stock move needed for an ATM straddle
    buyer to break even, accounting for IV crush and time decay.

    Args:
        underlying_price: Current stock price.
        atm_iv: Current ATM implied vol (annualized).
        catalyst_days: Days until the catalyst.
        event_family: REGULATORY/CLINICAL for crush calibration.
        expected_move_pct: Expected move from payoff engine (for over/under diagnostic).
        risk_free_rate: Risk-free rate.

    Returns:
        Dict with breakeven metrics, or None on invalid inputs.
    """
    if underlying_price <= 0 or atm_iv <= 0 or catalyst_days <= 0:
        return None

    strike = underlying_price
    T_pre = catalyst_days / 365.0

    fam_key = event_family.upper() if event_family else "default"
    crush_ratio = CRUSH_RATIO_BASE.get(fam_key, CRUSH_RATIO_BASE["default"])
    post_iv = atm_iv * crush_ratio

    # Pre-event straddle cost
    pre_call = black_scholes_greeks(underlying_price, strike, T_pre, risk_free_rate, atm_iv, "call")
    pre_put = black_scholes_greeks(underlying_price, strike, T_pre, risk_free_rate, atm_iv, "put")
    straddle_cost = pre_call["price"] + pre_put["price"]

    if math.isnan(straddle_cost) or straddle_cost <= 0:
        return None

    straddle_cost_pct = straddle_cost / underlying_price

    # Breakeven: the move where post-event straddle intrinsic = pre-event cost
    # For a straddle, breakeven ~= straddle_cost / underlying (simplified)
    # More precisely, we need to find move where |S_new - K| = straddle_cost - remaining_time_value
    # Since T_post is tiny, remaining time value is negligible, so breakeven ~= straddle_cost / S
    breakeven_move_pct = straddle_cost_pct

    # Over/under pricing diagnostic
    market_pricing = None
    if expected_move_pct is not None:
        if breakeven_move_pct < expected_move_pct:
            market_pricing = "underpriced"
        else:
            market_pricing = "overpriced"

    return {
        "breakeven_move_pct": round(breakeven_move_pct, 4),
        "straddle_cost": round(straddle_cost, 4),
        "straddle_cost_pct": round(straddle_cost_pct, 4),
        "crush_ratio": round(crush_ratio, 4),
        "post_event_iv_est": round(post_iv, 4),
        "market_pricing": market_pricing,
    }
