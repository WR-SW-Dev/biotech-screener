"""Options-based risk controls for 0-30d binary bucket.

Four defensive controls for very near-term binary events:
1. Crowding penalty — heavy front-running, reduce cap
2. Event premium complacency — flat IV near PDUFA, flag for review
3. Gap risk sizing cap — high model-market disagreement within 14d
4. Cheap implied move surfacing — unusually cheap surface for manual review

All controls are suppressed when options data is absent.
Thin chains get a limited subset (EXTREME IV penalty only).
Control 1 (crowding) is dormant until panel data is populated.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional


def compute_rv_30d(
    prices: Dict[str, float],
    as_of_date: str,
) -> Optional[float]:
    """Compute 30-day annualized realized volatility from price dict.

    Args:
        prices: {date_str: close_price} for a single ticker.
        as_of_date: Reference date (YYYY-MM-DD).

    Returns:
        Annualized realized vol, or None if insufficient data.
    """
    sorted_dates = sorted(d for d in prices.keys() if d <= as_of_date)
    if len(sorted_dates) < 22:  # need ~1 month of trading days
        return None

    # Use last 21 trading days (approx 30 calendar days)
    recent = sorted_dates[-22:]
    log_returns = []
    for i in range(1, len(recent)):
        p0 = prices.get(recent[i - 1], 0)
        p1 = prices.get(recent[i], 0)
        if p0 > 0 and p1 > 0:
            log_returns.append(math.log(p1 / p0))

    if len(log_returns) < 15:
        return None

    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    daily_vol = math.sqrt(variance)
    return daily_vol * math.sqrt(252)  # annualize


def compute_0_30_risk_controls(
    row: dict,
    rv_30d: Optional[float],
    options_fresh: bool,
    crowding_panel_populated: bool = False,
) -> Dict[str, Any]:
    """Compute risk control flags and cap adjustments for binary_0_30 names.

    Returns:
        Dict with crowding_flag, complacency_flag, cheap_surface_flag,
        gap_risk_cap_reduction, hard_cap_multiplier, review_required,
        control_reasons.
    """
    result: Dict[str, Any] = {
        "crowding_flag": False,
        "complacency_flag": False,
        "cheap_surface_flag": False,
        "gap_risk_cap_reduction": 0.0,
        "hard_cap_multiplier": 1.0,
        "review_required": False,
        "control_reasons": [],
    }

    liq_state = row.get("opt_liquidity_state", "absent")

    # Gate: absent data → no controls
    if liq_state == "absent":
        result["control_reasons"].append("absent_options_data")
        return result

    # Thin chain + EXTREME IV → penalty even without fresh data
    if not options_fresh:
        iv_regime = (row.get("opt_iv_regime") or "").strip()
        if iv_regime == "EXTREME" and liq_state == "thin":
            result["hard_cap_multiplier"] = 0.75
            result["control_reasons"].append("extreme_iv_thin_chain(-25%)")
            return result
        result["control_reasons"].append("stale_options_data_suppressed")
        return result

    try:
        cat_days = int(float(row.get("catalyst_days", "") or "9999"))
    except (ValueError, TypeError):
        cat_days = 9999

    catalyst_family = (row.get("catalyst_family") or "").upper()

    # Control 1: Crowding penalty (dormant until panel populated)
    if crowding_panel_populated and cat_days <= 20:
        try:
            vol_ratio = float(row.get("options_volume_ratio", "") or "0")
            near_term_share = float(row.get("near_term_volume_share", "") or "0")
        except (ValueError, TypeError):
            vol_ratio = 0.0
            near_term_share = 0.0

        if vol_ratio > 2.0 and near_term_share > 0.60:
            result["crowding_flag"] = True
            result["hard_cap_multiplier"] *= 0.75
            result["control_reasons"].append(
                f"crowding: vol_ratio={vol_ratio:.1f}, near_term_share={near_term_share:.2f}"
            )

    # Control 2: Event premium complacency
    if cat_days <= 20 and catalyst_family == "REGULATORY" and rv_30d is not None and rv_30d > 0:
        try:
            atm_iv = float(row.get("opt_atm_iv", "") or "0")
        except (ValueError, TypeError):
            atm_iv = 0.0

        if atm_iv > 0 and (atm_iv / rv_30d) < 1.15:
            result["complacency_flag"] = True
            result["review_required"] = True
            result["control_reasons"].append(
                f"complacency: IV/RV={atm_iv / rv_30d:.2f} < 1.15 on {cat_days}d regulatory"
            )

    # Control 3: Gap risk sizing cap
    if cat_days <= 14:
        try:
            pos_div = float(row.get("pos_divergence", "") or "0")
        except (ValueError, TypeError):
            pos_div = 0.0

        if abs(pos_div) > 1.0:
            result["gap_risk_cap_reduction"] = 0.25
            result["hard_cap_multiplier"] *= 0.75
            result["control_reasons"].append(f"gap_risk: |pos_divergence|={abs(pos_div):.2f} > 1.0 within {cat_days}d")

    # Control 4: Cheap implied move surfacing (for manual review)
    if liq_state == "liquid" and cat_days <= 30:
        try:
            implied_pctile = float(row.get("actual_implied_move_pctile", "") or "999")
        except (ValueError, TypeError):
            implied_pctile = 999.0

        if 0 < implied_pctile < 0.20:
            result["cheap_surface_flag"] = True
            result["review_required"] = True
            result["control_reasons"].append(
                f"cheap_surface: implied_pctile={implied_pctile:.2f} on liquid {cat_days}d name"
            )

    # Floor the multiplier
    result["hard_cap_multiplier"] = max(0.75, result["hard_cap_multiplier"])

    # Review required if any flag fired
    if result["crowding_flag"] or result["complacency_flag"] or result["cheap_surface_flag"]:
        result["review_required"] = True

    return result
