"""Event premium decomposition for within-top-30 ranking.

Decomposes the options surface into components that differentiate
names inside the good bucket:

1. event_premium_ratio   — front/back IV ratio (how much extra the market prices for the catalyst)
2. term_slope_z          — normalized term slope vs own history
3. skew_richness_z       — current RR vs own history (z-scored)
4. implied_vs_historical — current implied move vs realized moves on similar past catalysts
5. iv_momentum           — 5d IV change direction and magnitude
6. surface_regime        — composite: {event_loaded, iv_ramping, skew_extreme, flat}

These features are designed for within-top-30 ranking, not full-universe selection.
They vary meaningfully inside the good bucket because they capture how the
*market is pricing* the upcoming catalyst, not just whether a catalyst exists.

Usage:
    from common.event_premium_decomp import compute_event_premium_decomp
"""

from __future__ import annotations

import math
import statistics
from typing import Any

# ---------------------------------------------------------------------------
# Core decomposition
# ---------------------------------------------------------------------------


def compute_event_premium_decomp(
    row: dict[str, Any],
    iv_history: list[dict] | None = None,
    rr_history: list[float] | None = None,
    event_move_table: dict | None = None,
) -> dict[str, Any]:
    """Compute event premium decomposition for a single name.

    Parameters
    ----------
    row : rankings row dict with opt_* fields
    iv_history : list of {date, atm_iv, actual_implied_move, rr_25d} sorted by date
    rr_history : list of historical RR 25d values
    event_move_table : {catalyst_type: {phase: {p50: float, p75: float, n: int}}}

    Returns
    -------
    dict with decomposed features (all prefixed with epd_)
    """
    result: dict[str, Any] = {}

    front_iv = _sf(row.get("opt_front_iv"))
    back_iv = _sf(row.get("opt_back_iv"))
    atm_iv = _sf(row.get("opt_atm_iv"))
    rr_25d = _sf(row.get("opt_rr_25d"))
    term_slope = _sf(row.get("opt_term_slope"))
    implied_move = _sf(row.get("implied_event_move"))
    iv_change_5d = _sf(row.get("atm_iv_change_5d"))
    catalyst_days = _sf(row.get("catalyst_days"))
    catalyst_type = row.get("catalyst_event_type", "") or ""
    phase = row.get("lead_program_phase", "") or ""

    has_surface = not math.isnan(front_iv) and front_iv > 0

    # 1. Event premium ratio: front / back
    if has_surface and not math.isnan(back_iv) and back_iv > 0:
        result["epd_event_premium_ratio"] = round(front_iv / back_iv, 4)
    else:
        result["epd_event_premium_ratio"] = None

    # 2. Term slope z-scored vs own history
    if iv_history and not math.isnan(term_slope):
        hist_slopes = _extract_term_slopes(iv_history)
        if len(hist_slopes) >= 5:
            mu = statistics.mean(hist_slopes)
            sd = statistics.stdev(hist_slopes)
            if sd > 0.001:
                z = (term_slope - mu) / sd
                result["epd_term_slope_z"] = round(max(-3.0, min(3.0, z)), 4)
            else:
                result["epd_term_slope_z"] = 0.0
        else:
            result["epd_term_slope_z"] = None
    else:
        result["epd_term_slope_z"] = None

    # 3. Skew richness: current RR vs history (z-scored)
    if not math.isnan(rr_25d) and rr_history and len(rr_history) >= 5:
        mu = statistics.mean(rr_history)
        sd = statistics.stdev(rr_history)
        if sd > 0.001:
            z = (rr_25d - mu) / sd
            result["epd_skew_richness_z"] = round(max(-3.0, min(3.0, z)), 4)
        else:
            result["epd_skew_richness_z"] = 0.0
    else:
        result["epd_skew_richness_z"] = None

    # 4. Implied vs historical realized move
    if not math.isnan(implied_move) and event_move_table and catalyst_type:
        hist_move = _lookup_historical_move(event_move_table, catalyst_type, phase)
        if hist_move is not None and hist_move > 0:
            ratio = implied_move / hist_move
            result["epd_implied_vs_realized_ratio"] = round(ratio, 4)
            # > 1.0 = market pricing more than historical, < 1.0 = underpricing
            result["epd_mispricing_direction"] = (
                "overpriced" if ratio > 1.3 else "underpriced" if ratio < 0.7 else "fair"
            )
        else:
            result["epd_implied_vs_realized_ratio"] = None
            result["epd_mispricing_direction"] = None
    else:
        result["epd_implied_vs_realized_ratio"] = None
        result["epd_mispricing_direction"] = None

    # 5. IV momentum (5d change magnitude and direction)
    if not math.isnan(iv_change_5d):
        result["epd_iv_momentum"] = round(iv_change_5d, 6)
        result["epd_iv_ramping"] = iv_change_5d > 0.05  # >5pp IV increase in 5 days
        result["epd_iv_crushing"] = iv_change_5d < -0.05
    else:
        result["epd_iv_momentum"] = None
        result["epd_iv_ramping"] = None
        result["epd_iv_crushing"] = None

    # 6. Catalyst proximity × IV interaction
    if has_surface and not math.isnan(catalyst_days) and catalyst_days > 0:
        # IV per day to catalyst — higher means market is pricing more urgency
        result["epd_iv_per_catalyst_day"] = round(atm_iv / catalyst_days, 6) if not math.isnan(atm_iv) else None
        # Event premium concentrated in near-term?
        result["epd_catalyst_proximity_bucket"] = (
            "imminent"
            if catalyst_days <= 14
            else "near" if catalyst_days <= 45 else "mid" if catalyst_days <= 90 else "far"
        )
    else:
        result["epd_iv_per_catalyst_day"] = None
        result["epd_catalyst_proximity_bucket"] = None

    # 7. Surface regime composite
    result["epd_surface_regime"] = _classify_surface_regime(result)

    # 8. Decomposition quality flag
    n_filled = sum(1 for v in result.values() if v is not None and v != "")
    result["epd_quality"] = "full" if n_filled >= 8 else "partial" if n_filled >= 4 else "sparse"

    return result


def compute_universe_decomp(
    rows: list[dict],
    iv_histories: dict[str, list[dict]] | None = None,
    rr_histories: dict[str, list[float]] | None = None,
    event_move_table: dict | None = None,
) -> list[dict]:
    """Compute decomposition for a list of ranking rows.

    Returns list of dicts with ticker + all epd_ fields.
    """
    results = []
    for row in rows:
        ticker = (row.get("ticker") or "").upper()
        iv_hist = (iv_histories or {}).get(ticker, [])
        rr_hist = (rr_histories or {}).get(ticker, [])

        decomp = compute_event_premium_decomp(
            row,
            iv_history=iv_hist,
            rr_history=rr_hist,
            event_move_table=event_move_table,
        )
        decomp["ticker"] = ticker
        results.append(decomp)

    # Z-score event_premium_ratio across universe
    _zscore_field(results, "epd_event_premium_ratio", "epd_event_premium_ratio_z")
    # Z-score implied_vs_realized_ratio
    _zscore_field(results, "epd_implied_vs_realized_ratio", "epd_implied_vs_realized_z")
    # Z-score iv_momentum
    _zscore_field(results, "epd_iv_momentum", "epd_iv_momentum_z")

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sf(v) -> float:
    """Safe float conversion, returns NaN on failure."""
    if v is None or v == "" or v == "None":
        return float("nan")
    try:
        return float(v)
    except (ValueError, TypeError):
        return float("nan")


def _extract_term_slopes(iv_history: list[dict]) -> list[float]:
    """Extract historical term slopes from IV history rows."""
    slopes = []
    for row in iv_history:
        # If term_slope is directly available
        ts = row.get("term_slope")
        if ts is not None:
            try:
                slopes.append(float(ts))
            except (ValueError, TypeError):
                pass
            continue
        # Otherwise compute from front/back IV
        front = _sf(row.get("front_iv", row.get("atm_iv")))
        back = _sf(row.get("back_iv"))
        if not math.isnan(front) and not math.isnan(back) and front > 0:
            slopes.append((back - front) / front)
    return slopes


def _lookup_historical_move(
    event_move_table: dict,
    catalyst_type: str,
    phase: str,
) -> float | None:
    """Look up median historical realized move for this catalyst type + phase."""
    # Try exact match
    key = catalyst_type.upper()
    entry = event_move_table.get(key, {})
    if isinstance(entry, dict):
        # Try phase-specific
        phase_key = _phase_bucket(phase)
        phase_entry = entry.get(phase_key, entry.get("all", {}))
        if isinstance(phase_entry, dict):
            return phase_entry.get("p50")  # median realized move
        return None
    return None


def _phase_bucket(phase: str) -> str:
    try:
        p = float(phase)
    except (ValueError, TypeError):
        return "all"
    if p >= 3:
        return "phase3"
    if p >= 2:
        return "phase2"
    return "early"


def _classify_surface_regime(decomp: dict) -> str:
    """Classify the composite surface state."""
    epr = decomp.get("epd_event_premium_ratio")
    ramping = decomp.get("epd_iv_ramping")
    skew_z = decomp.get("epd_skew_richness_z")

    signals = []
    if epr is not None and epr > 1.15:
        signals.append("event_loaded")
    if ramping:
        signals.append("iv_ramping")
    if skew_z is not None and abs(skew_z) > 2.0:
        signals.append("skew_extreme")
    if decomp.get("epd_iv_crushing"):
        signals.append("iv_crushing")

    if not signals:
        return "flat"
    return "+".join(signals)


def _zscore_field(results: list[dict], raw_field: str, z_field: str) -> None:
    """Z-score a field across results, clipped to [-3, 3]."""
    values = [r[raw_field] for r in results if r.get(raw_field) is not None]
    if len(values) < 3:
        for r in results:
            r[z_field] = None
        return

    mu = statistics.mean(values)
    sd = statistics.stdev(values)

    for r in results:
        v = r.get(raw_field)
        if v is not None and sd > 0:
            z = (v - mu) / sd
            r[z_field] = round(max(-3.0, min(3.0, z)), 4)
        else:
            r[z_field] = None
