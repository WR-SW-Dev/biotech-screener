"""Surface Diagnostics & Anomaly Detection (Spec 059 Phase C).

Cross-sectional options surface analysis for the event-EV overlay:
1. Anomaly detector — flags names with unusual event premium ratios
2. Term structure shape classification — finer than EPD's surface_regime
3. Historical comparison — current surface vs own history
4. Belief intensity modifier — tightens/loosens expectation model confidence

Policy: OVERLAY-ONLY. No selector/ranker impact. All gated on liquid options.
"""

from __future__ import annotations

import logging
import math
import statistics
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# Term Structure Shape Classification
# ============================================================================

# Thresholds for shape classification
_BACKWARDATION_EXTREME_RATIO = 2.0  # front/back > 2.0
_HIGH_IV_THRESHOLD = 0.80  # annualized, above which "flat_high" applies
_LOW_IV_THRESHOLD = 0.40  # below which "flat_low" applies
_FLAT_TOLERANCE = 0.10  # |front/back - 1.0| < this → flat


def classify_term_structure(
    front_iv: float,
    back_iv: float,
    catalyst_days: int,
) -> Optional[str]:
    """Classify the term structure shape with finer granularity.

    Returns one of:
        - backwardation_extreme: front >> back, catalyst fully loaded
        - backwardation: front > back (normal near-catalyst)
        - contango_near_event: back > front AND catalyst < 14d (unusual)
        - contango: back > front, catalyst far
        - flat_high: flat at elevated IV (broad uncertainty)
        - flat_low: flat at low IV (no event pricing)
        - None: invalid inputs
    """
    if front_iv <= 0 or back_iv <= 0 or catalyst_days <= 0:
        return None

    ratio = front_iv / back_iv

    # Flat check
    if abs(ratio - 1.0) < _FLAT_TOLERANCE:
        avg_iv = (front_iv + back_iv) / 2
        if avg_iv >= _HIGH_IV_THRESHOLD:
            return "flat_high"
        if avg_iv <= _LOW_IV_THRESHOLD:
            return "flat_low"
        return "flat"

    # Backwardation (front > back)
    if ratio > 1.0:
        if ratio >= _BACKWARDATION_EXTREME_RATIO:
            return "backwardation_extreme"
        return "backwardation"

    # Contango (back > front)
    if catalyst_days <= 14:
        return "contango_near_event"
    return "contango"


# ============================================================================
# Surface Anomaly Detection
# ============================================================================


def detect_surface_anomalies(
    rows: List[Dict[str, Any]],
    z_threshold: float = 2.0,
) -> List[Dict[str, Any]]:
    """Detect names with anomalous options surface state.

    Computes cross-sectional z-scores of event premium ratio (front/back IV)
    and flags names that are >z_threshold standard deviations from the mean.

    Args:
        rows: List of surface row dicts (from rankings or snapshot).
            Each needs: ticker, opt_front_iv, opt_back_iv, opt_atm_iv,
            catalyst_days, opt_liquidity_state.
        z_threshold: Standard deviations for anomaly flag.

    Returns:
        List of anomaly dicts for flagged names.
    """
    if not rows:
        return []

    # Filter to liquid only, compute EPR
    liquid_rows = []
    for row in rows:
        if row.get("opt_liquidity_state") != "liquid":
            continue
        front = _sf(row.get("opt_front_iv"))
        back = _sf(row.get("opt_back_iv"))
        if front <= 0 or back <= 0:
            continue
        epr = front / back
        catalyst_days = int(_sf(row.get("catalyst_days")) or 0)
        liquid_rows.append(
            {
                "ticker": row.get("ticker", ""),
                "front_iv": front,
                "back_iv": back,
                "atm_iv": _sf(row.get("opt_atm_iv")),
                "epr": epr,
                "catalyst_days": catalyst_days,
                "event_family": row.get("event_family", ""),
            }
        )

    if len(liquid_rows) < 3:
        return []

    # Cross-sectional z-score of EPR
    epr_values = [r["epr"] for r in liquid_rows]
    mu = statistics.mean(epr_values)
    sd = statistics.stdev(epr_values)
    if sd < 0.001:
        return []

    anomalies = []
    for r in liquid_rows:
        epr_z = (r["epr"] - mu) / sd
        flags = []

        # Classify term structure
        shape = classify_term_structure(r["front_iv"], r["back_iv"], max(r["catalyst_days"], 1))

        if shape == "backwardation_extreme" or epr_z > z_threshold:
            flags.append("backwardation_extreme")
        if shape == "contango_near_event" or (epr_z < -z_threshold and r["catalyst_days"] <= 14):
            flags.append("contango_near_event")
        if shape == "flat_high" and abs(epr_z) > z_threshold:
            flags.append("flat_high_anomaly")

        if flags:
            anomalies.append(
                {
                    "ticker": r["ticker"],
                    "flags": flags,
                    "epr": round(r["epr"], 4),
                    "epr_z": round(epr_z, 4),
                    "term_shape": shape,
                    "front_iv": round(r["front_iv"], 4),
                    "back_iv": round(r["back_iv"], 4),
                    "catalyst_days": r["catalyst_days"],
                }
            )

    return anomalies


# ============================================================================
# Historical Comparison
# ============================================================================


def compare_to_history(
    current_atm_iv: float,
    current_epr: float,
    history: List[Dict[str, Any]],
    min_history: int = 3,
) -> Optional[Dict[str, Any]]:
    """Compare current surface to historical observations for the same name.

    Args:
        current_atm_iv: Current ATM IV.
        current_epr: Current event premium ratio (front/back).
        history: List of historical observations, each with
            'atm_iv' and 'event_premium_ratio' keys.
        min_history: Minimum observations required.

    Returns:
        Dict with percentile ranks, or None if insufficient history.
    """
    if len(history) < min_history:
        return None

    hist_ivs = [_sf(h.get("atm_iv")) for h in history]
    hist_eprs = [_sf(h.get("event_premium_ratio")) for h in history]
    hist_ivs = [v for v in hist_ivs if v > 0]
    hist_eprs = [v for v in hist_eprs if v > 0]

    if len(hist_ivs) < min_history or len(hist_eprs) < min_history:
        return None

    atm_iv_pctile = _percentile_rank(current_atm_iv, hist_ivs)
    epr_pctile = _percentile_rank(current_epr, hist_eprs)

    return {
        "atm_iv_pctile": round(atm_iv_pctile, 4),
        "epr_pctile": round(epr_pctile, 4),
        "atm_iv_hist_mean": round(statistics.mean(hist_ivs), 4),
        "atm_iv_hist_sd": round(statistics.stdev(hist_ivs), 4) if len(hist_ivs) > 1 else 0.0,
        "epr_hist_mean": round(statistics.mean(hist_eprs), 4),
        "epr_hist_sd": round(statistics.stdev(hist_eprs), 4) if len(hist_eprs) > 1 else 0.0,
        "n_history": len(hist_ivs),
    }


# ============================================================================
# Belief Intensity Modifier
# ============================================================================


def compute_belief_intensity_modifier(
    term_shape: str,
    epr_z: float,
) -> float:
    """Compute a belief intensity modifier based on surface state.

    This modifies the ExpectationModel's belief_intensity (not the feature
    weights — that would be alpha, which is policy-forbidden).

    The idea: if the surface is in extreme backwardation, the market has
    high conviction → tighter confidence band. If contango near event,
    the market doesn't believe the date → looser band.

    Returns:
        Modifier in [0.5, 1.5]. 1.0 = no change.
    """
    modifier = 1.0

    # Shape-based adjustment
    shape_adj = {
        "backwardation_extreme": 0.20,  # higher conviction
        "backwardation": 0.05,
        "contango_near_event": -0.20,  # market skeptical of date
        "contango": -0.05,
        "flat_high": 0.10,  # broad uncertainty but elevated
        "flat_low": -0.10,
        "flat": 0.0,
    }
    modifier += shape_adj.get(term_shape, 0.0)

    # EPR z-score adjustment (continuous, capped)
    # Large positive z → event heavily loaded → more conviction
    epr_adj = max(-0.15, min(0.15, epr_z * 0.05))
    modifier += epr_adj

    # Bound to [0.5, 1.5]
    return max(0.5, min(1.5, round(modifier, 4)))


# ============================================================================
# Helpers
# ============================================================================


def _sf(v) -> float:
    if v is None or v == "" or v == "None":
        return float("nan")
    try:
        f = float(v)
        return f if not math.isnan(f) else 0.0
    except (ValueError, TypeError):
        return 0.0


def _percentile_rank(value: float, distribution: List[float]) -> float:
    """Compute percentile rank of value within distribution."""
    n = len(distribution)
    if n == 0:
        return 0.5
    count_below = sum(1 for v in distribution if v < value)
    count_equal = sum(1 for v in distribution if v == value)
    return (count_below + 0.5 * count_equal) / n
