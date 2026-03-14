"""Term structure validator — Agent 0 staleness flag and blind-spot surfacer.

Uses IV term structure to flag two cases CT.gov alone cannot detect:

1. **Catalyst date mismatch**: surfaced catalyst date disagrees with where
   the term structure is elevated — suggests stale date or miscategorized window.
2. **Blind spot candidate**: no catalyst surfaced, but front/back term structure
   shows event premium — surfaces a name for manual review.

Purely diagnostic. No scoring changes. No ranking impact.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Thresholds (calibrated against 2026-03-14 manual review)
# ---------------------------------------------------------------------------

# Case 1: market sees event sooner than model
MISMATCH_SLOPE_THRESHOLD = -0.10  # front IV elevated > 10% above back
MISMATCH_MIN_CATALYST_DAYS = 91  # model says > 90d out

# Case 1b: market NOT pricing expected near-term event
FLAT_SLOPE_THRESHOLD = 0.0  # no backwardation
FLAT_MAX_CATALYST_DAYS = 45  # model says < 45d
FLAT_IV_MULTIPLIER = 1.2  # IV not elevated above baseline

# Case 2: blind spot — no catalyst but term structure screams event
BLIND_SPOT_SLOPE_THRESHOLD = -0.15
BLIND_SPOT_IV_MULTIPLIER = 1.4


def detect_catalyst_date_mismatch(
    catalyst_days: Optional[int],
    opt_term_slope: Optional[float],
    opt_atm_iv: Optional[float],
    baseline_iv: Optional[float],
) -> Dict[str, Any]:
    """Flag when term structure elevation disagrees with catalyst_days.

    Returns:
        Dict with keys: flag (bool), flag_type (str), reason (str),
        requires_review (bool).
    """
    empty = {"flag": False, "flag_type": "", "reason": "", "requires_review": False}

    if catalyst_days is None or catalyst_days <= 0:
        return empty
    if opt_term_slope is None or math.isnan(opt_term_slope):
        return empty

    # Pattern A: front IV elevated but model says catalyst is far out
    if opt_term_slope < MISMATCH_SLOPE_THRESHOLD and catalyst_days > MISMATCH_MIN_CATALYST_DAYS:
        return {
            "flag": True,
            "flag_type": "MARKET_SEES_SOONER",
            "reason": (
                f"term_slope={opt_term_slope:.3f} (front elevated) but "
                f"catalyst_days={catalyst_days} (model says >90d). "
                f"Market may see a nearer event."
            ),
            "requires_review": True,
        }

    # Pattern B: market NOT pricing expected near-term event
    if (
        opt_term_slope >= FLAT_SLOPE_THRESHOLD
        and catalyst_days <= FLAT_MAX_CATALYST_DAYS
        and opt_atm_iv is not None
        and baseline_iv is not None
        and not math.isnan(opt_atm_iv)
        and not math.isnan(baseline_iv)
        and baseline_iv > 0
        and opt_atm_iv < baseline_iv * FLAT_IV_MULTIPLIER
    ):
        return {
            "flag": True,
            "flag_type": "MARKET_NOT_PRICING_EVENT",
            "reason": (
                f"term_slope={opt_term_slope:.3f} (flat/contango) and "
                f"catalyst_days={catalyst_days} (model says near-term) but "
                f"IV={opt_atm_iv:.2f} not elevated vs baseline={baseline_iv:.2f}. "
                f"Possible stale catalyst date."
            ),
            "requires_review": True,
        }

    return empty


def detect_blind_spot_candidate(
    catalyst_days: Optional[int],
    catalyst_mode: Optional[str],
    opt_term_slope: Optional[float],
    opt_atm_iv: Optional[float],
    baseline_iv: Optional[float],
) -> Dict[str, Any]:
    """Flag names with no surfaced catalyst but elevated front-end IV.

    These are candidates for manual catalyst search, not auto-trades.

    Returns:
        Dict with keys: flag (bool), flag_type (str), reason (str),
        requires_review (bool).
    """
    empty = {"flag": False, "flag_type": "", "reason": "", "requires_review": False}

    # Only fire for names with no catalyst or missing/no_upcoming
    has_catalyst = (
        catalyst_days is not None and catalyst_days > 0 and catalyst_mode not in (None, "", "missing", "no_upcoming")
    )
    if has_catalyst:
        return empty

    if opt_term_slope is None or math.isnan(opt_term_slope):
        return empty
    if opt_atm_iv is None or math.isnan(opt_atm_iv):
        return empty
    if baseline_iv is None or math.isnan(baseline_iv) or baseline_iv <= 0:
        return empty

    if opt_term_slope < BLIND_SPOT_SLOPE_THRESHOLD and opt_atm_iv > baseline_iv * BLIND_SPOT_IV_MULTIPLIER:
        return {
            "flag": True,
            "flag_type": "BLIND_SPOT",
            "reason": (
                f"No catalyst surfaced but term_slope={opt_term_slope:.3f} "
                f"(strong backwardation) and IV={opt_atm_iv:.2f} >> "
                f"baseline={baseline_iv:.2f}. Market sees an event."
            ),
            "requires_review": True,
        }

    return empty


def validate_term_structure(
    catalyst_days: Optional[int],
    catalyst_mode: Optional[str],
    opt_term_slope: Optional[float],
    opt_atm_iv: Optional[float],
    baseline_iv: Optional[float],
) -> Dict[str, Any]:
    """Run both validators and return the first flag found (or no flag).

    Args:
        catalyst_days: Days to nearest catalyst (int or None).
        catalyst_mode: Catalyst mode string from rankings.
        opt_term_slope: (back_iv - front_iv) / front_iv from diagnostics.
        opt_atm_iv: ATM implied vol from diagnostics.
        baseline_iv: Trailing realized vol or median IV (cross-sectional).

    Returns:
        Dict with flag, flag_type, reason, requires_review.
    """
    # Check mismatch first (higher priority)
    result = detect_catalyst_date_mismatch(catalyst_days, opt_term_slope, opt_atm_iv, baseline_iv)
    if result["flag"]:
        return result

    # Then check blind spot
    result = detect_blind_spot_candidate(catalyst_days, catalyst_mode, opt_term_slope, opt_atm_iv, baseline_iv)
    if result["flag"]:
        return result

    return {"flag": False, "flag_type": "", "reason": "", "requires_review": False}
