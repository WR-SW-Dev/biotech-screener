"""Catalyst Risk Overlay (Spec 059 Phase D).

Risk-focused options overlay for names already in the book:
1. Catalyst proximity risk matrix — near-catalyst names with key risk metrics
2. Hedge cost indicator — ATM put cost as % of position
3. Escalated risk alerts — EXTREME IV + near catalyst + large implied move

Policy: OVERLAY-ONLY. Informational for operator review. No automated hedging.
All outputs gated on opt_liquidity_state == "liquid".
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from common.options_greeks import CRUSH_RATIO_BASE, black_scholes_greeks

logger = logging.getLogger(__name__)


# ============================================================================
# Catalyst Proximity Risk Matrix
# ============================================================================


def build_catalyst_risk_matrix(
    book: List[Dict[str, Any]],
    max_days: int = 30,
) -> List[Dict[str, Any]]:
    """Build a risk matrix for book names within max_days of a catalyst.

    Only includes names with liquid options data.

    Args:
        book: List of book name dicts, each with ticker, catalyst_days,
            implied_event_move, opt_atm_iv, opt_liquidity_state,
            underlying_price, weight_pct.
        max_days: Maximum catalyst days for inclusion.

    Returns:
        List of risk matrix rows, sorted by catalyst_days ascending.
    """
    matrix = []

    for row in book:
        liquidity = row.get("opt_liquidity_state", "absent")
        if liquidity != "liquid":
            continue

        catalyst_days = _safe_int(row.get("catalyst_days"))
        if catalyst_days is None or catalyst_days <= 0 or catalyst_days > max_days:
            continue

        underlying = _safe_float(row.get("underlying_price"))
        atm_iv = _safe_float(row.get("opt_atm_iv"))
        implied_move = _safe_float(row.get("implied_event_move"))

        if underlying is None or underlying <= 0:
            continue
        if atm_iv is None or atm_iv <= 0:
            continue

        # Breakeven straddle (simplified: straddle cost / underlying)
        T = catalyst_days / 365.0
        call = black_scholes_greeks(underlying, underlying, T, 0.05, atm_iv, "call")
        put = black_scholes_greeks(underlying, underlying, T, 0.05, atm_iv, "put")
        straddle = call["price"] + put["price"]
        breakeven_pct = straddle / underlying if not math.isnan(straddle) else None

        # IV crush estimate
        fam = (row.get("event_family") or "").upper()
        crush_ratio = CRUSH_RATIO_BASE.get(fam, CRUSH_RATIO_BASE["default"])
        iv_crush_est = round(atm_iv * (1 - crush_ratio), 4)

        # 1-day VaR estimate (from implied move, simplified)
        # For a binary catalyst, 1d VaR ≈ implied_move at ~1σ
        var_1d = implied_move if implied_move is not None else None

        matrix.append(
            {
                "ticker": row.get("ticker", ""),
                "catalyst_days": catalyst_days,
                "implied_move_pct": round(implied_move, 4) if implied_move is not None else None,
                "breakeven_straddle_pct": round(breakeven_pct, 4) if breakeven_pct is not None else None,
                "iv_crush_est": iv_crush_est,
                "var_1d_pct": round(var_1d, 4) if var_1d is not None else None,
                "atm_iv": round(atm_iv, 4),
                "underlying_price": round(underlying, 2),
                "weight_pct": round(_safe_float(row.get("weight_pct")) or 0.0, 2),
                "iv_regime": row.get("opt_iv_regime", ""),
            }
        )

    matrix.sort(key=lambda r: r["catalyst_days"])
    return matrix


# ============================================================================
# Hedge Cost Indicator
# ============================================================================


def compute_hedge_cost(
    underlying_price: float,
    atm_iv: float,
    catalyst_days: int,
    risk_free_rate: float = 0.05,
) -> Optional[Dict[str, Any]]:
    """Compute ATM put cost as % of position.

    This is the cost of 1-month protection via an ATM put, reported
    as informational for the operator. No automated hedging.

    Args:
        underlying_price: Current stock price.
        atm_iv: ATM implied vol (annualized).
        catalyst_days: Days to catalyst (used as put expiry proxy).
        risk_free_rate: Risk-free rate.

    Returns:
        Dict with put_cost, put_cost_pct, or None on invalid inputs.
    """
    if underlying_price <= 0 or atm_iv <= 0 or catalyst_days <= 0:
        return None

    T = catalyst_days / 365.0
    put = black_scholes_greeks(underlying_price, underlying_price, T, risk_free_rate, atm_iv, "put")
    put_price = put["price"]

    if math.isnan(put_price) or put_price <= 0:
        return None

    put_cost_pct = put_price / underlying_price

    return {
        "put_cost": round(put_price, 4),
        "put_cost_pct": round(put_cost_pct, 4),
        "put_delta": round(put["delta"], 4),
        "catalyst_days": catalyst_days,
        "atm_iv": round(atm_iv, 4),
    }


# ============================================================================
# Escalated Risk Alerts
# ============================================================================

# Thresholds for escalation
_ESCALATION_MAX_DAYS = 7
_ESCALATION_IMPLIED_MOVE_CRITICAL = 0.20  # 20%


def check_escalated_risk(
    row: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Check if a book name triggers an escalated risk alert.

    Escalation criteria:
    - Critical: EXTREME IV + catalyst < 7d + implied move > 20%
    - Warning: EXTREME IV + catalyst < 7d (any implied move)

    Returns:
        Alert dict with ticker, severity, reason, or None.
    """
    liquidity = row.get("opt_liquidity_state", "absent")
    if liquidity == "absent":
        return None

    iv_regime = (row.get("opt_iv_regime") or "").strip().upper()
    catalyst_days = _safe_int(row.get("catalyst_days"))
    implied_move = _safe_float(row.get("implied_event_move"))

    if catalyst_days is None or catalyst_days > _ESCALATION_MAX_DAYS:
        return None

    if iv_regime != "EXTREME":
        return None

    ticker = row.get("ticker", "")

    # Critical: EXTREME + near + large implied
    if implied_move is not None and implied_move > _ESCALATION_IMPLIED_MOVE_CRITICAL:
        return {
            "ticker": ticker,
            "severity": "critical",
            "reason": (f"EXTREME IV + {catalyst_days}d to catalyst + " f"{implied_move:.0%} implied move"),
            "catalyst_days": catalyst_days,
            "implied_move": round(implied_move, 4),
            "iv_regime": iv_regime,
        }

    # Warning: EXTREME + near (lower implied)
    return {
        "ticker": ticker,
        "severity": "warning",
        "reason": f"EXTREME IV + {catalyst_days}d to catalyst",
        "catalyst_days": catalyst_days,
        "implied_move": round(implied_move, 4) if implied_move is not None else None,
        "iv_regime": iv_regime,
    }


def collect_escalated_alerts(
    book: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collect all escalated risk alerts from the book.

    Returns:
        List of alert dicts, sorted by severity (critical first)
        then catalyst_days ascending.
    """
    alerts = []
    for row in book:
        alert = check_escalated_risk(row)
        if alert is not None:
            alerts.append(alert)

    severity_order = {"critical": 0, "warning": 1}
    alerts.sort(key=lambda a: (severity_order.get(a["severity"], 2), a.get("catalyst_days", 999)))
    return alerts


# ============================================================================
# Helpers
# ============================================================================


def _safe_float(v) -> Optional[float]:
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
        return f if not math.isnan(f) else None
    except (ValueError, TypeError):
        return None


def _safe_int(v) -> Optional[int]:
    if v is None or v == "" or v == "None":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None
