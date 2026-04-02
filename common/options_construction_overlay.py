"""Options-based construction overlay for 31-90d binary bucket.

Adjusts weights for already-ranked names within the binary_31_90 bucket.
Does not reorder ranks — only affects weight distribution after names
are selected.

Multipliers compound, hard-bounded to [0.60, 1.40].
Suppressed for names with absent options data (never adjust on missing data).
Thin chains get a limited subset of rules (penalty-only, no boosts).

Uses opt_liquidity_state as the primary gate:
  liquid  — full overlay (boosts + penalties)
  thin    — penalty-only (EXTREME IV, high disagreement)
  absent  — suppressed (1.0x)
"""

from __future__ import annotations

from typing import Any, Dict, List

MULT_FLOOR = 0.60
MULT_CEILING = 1.40

# Implied-move percentile thresholds (fallback when vol_classification absent)
_CHEAP_PCTILE = 0.30
_RICH_PCTILE = 0.80

# Term slope thresholds for disagreement (fallback when market_model_disagreement absent)
_HIGH_DISAGREE_SLOPE = 0.25


def _sf(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def compute_31_90_weight_multiplier(
    row: dict,
    options_fresh: bool = False,
) -> Dict[str, Any]:
    """Compute weight multiplier for a binary_31_90 name.

    Returns:
        Dict with weight_multiplier, overlay_reasons, overlay_applied.
    """
    liq_state = row.get("opt_liquidity_state", "absent")

    # Gate: absent data → no adjustment
    if liq_state == "absent":
        return {
            "weight_multiplier": 1.0,
            "overlay_reasons": ["absent_options_data"],
            "overlay_applied": False,
        }

    # Stale but not absent → penalty-only for extreme cases
    if not options_fresh and liq_state != "absent":
        iv_regime = (row.get("opt_iv_regime") or "").strip()
        if iv_regime == "EXTREME" and liq_state == "thin":
            return {
                "weight_multiplier": 0.70,
                "overlay_reasons": ["extreme_iv_thin_chain(-30%)"],
                "overlay_applied": True,
            }
        return {
            "weight_multiplier": 1.0,
            "overlay_reasons": ["stale_options_data_suppressed"],
            "overlay_applied": False,
        }

    multiplier = 1.0
    reasons: List[str] = []

    oqc = (row.get("options_quality_composite") or "").strip()
    oqc_nonzero = oqc not in ("", "0", "0.0")
    iv_regime = (row.get("opt_iv_regime") or "").strip()

    # Vol classification: prefer explicit field, fallback to implied_move_pctile
    vol_class = (row.get("vol_classification") or "").strip()
    implied_pctile = _sf(row.get("actual_implied_move_pctile", ""))
    if not vol_class and implied_pctile is not None:
        if implied_pctile < _CHEAP_PCTILE:
            vol_class = "CHEAP"
        elif implied_pctile > _RICH_PCTILE:
            vol_class = "RICH"

    # Disagreement: prefer explicit field, fallback to term_slope magnitude
    disagreement = (row.get("market_model_disagreement") or "").strip()
    term_slope = _sf(row.get("opt_term_slope", ""))
    if not disagreement and term_slope is not None:
        if abs(term_slope) > _HIGH_DISAGREE_SLOPE:
            disagreement = "high"
        elif abs(term_slope) < 0.05:
            disagreement = "low"

    try:
        cat_days = int(float(row.get("catalyst_days", "") or "9999"))
    except (ValueError, TypeError):
        cat_days = 9999

    is_liquid = liq_state == "liquid"

    # --- Boosts (liquid chains only) ---
    if is_liquid:
        # Boost: OQC present + normal IV + cheap vol
        if oqc_nonzero and iv_regime == "NORMAL" and vol_class in ("CHEAP", "SLIGHTLY_CHEAP"):
            multiplier *= 1.20
            reasons.append("oqc_confirmed+cheap_vol(+20%)")

        # Boost: OQC present + low disagreement
        if oqc_nonzero and disagreement == "low":
            multiplier *= 1.10
            reasons.append("oqc_confirmed+model_market_agree(+10%)")

    # --- Penalties (liquid + thin) ---

    # Cap: rich vol + near-term
    if vol_class == "RICH" and cat_days <= 75:
        multiplier *= 0.80
        reasons.append("rich_vol_near_term(-20%)")

    # Cap: high disagreement + near-term
    if disagreement == "high" and cat_days <= 75:
        multiplier *= 0.75
        reasons.append("high_disagreement_near_term(-25%)")

    # Penalty: EXTREME IV + thin chain (poor quality extreme surface)
    if iv_regime == "EXTREME" and liq_state == "thin":
        multiplier *= 0.70
        reasons.append("extreme_iv_thin_chain(-30%)")

    # Enforce hard bounds
    multiplier = max(MULT_FLOOR, min(multiplier, MULT_CEILING))

    return {
        "weight_multiplier": round(multiplier, 4),
        "overlay_reasons": reasons if reasons else ["no_adjustment"],
        "overlay_applied": len(reasons) > 0 and reasons[0] != "no_adjustment",
    }
