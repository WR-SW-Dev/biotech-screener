"""Options-based construction overlay for 31-90d binary bucket.

Adjusts weights for already-ranked names within the binary_31_90 bucket.
Does not reorder ranks — only affects weight distribution after names
are selected.

Multipliers compound, hard-bounded to [0.60, 1.40].
Suppressed entirely when options data is stale.
"""

from __future__ import annotations

from typing import Any, Dict, List

MULT_FLOOR = 0.60
MULT_CEILING = 1.40


def compute_31_90_weight_multiplier(
    row: dict,
    options_fresh: bool,
) -> Dict[str, Any]:
    """Compute weight multiplier for a binary_31_90 name.

    Returns:
        Dict with weight_multiplier, overlay_reasons, overlay_applied.
    """
    if not options_fresh:
        return {
            "weight_multiplier": 1.0,
            "overlay_reasons": ["stale_options_data"],
            "overlay_applied": False,
        }

    multiplier = 1.0
    reasons: List[str] = []

    oqc = (row.get("options_quality_composite") or "").strip()
    oqc_nonzero = oqc not in ("", "0", "0.0")
    vol_class = (row.get("vol_classification") or "").strip()
    disagreement = (row.get("market_model_disagreement") or "").strip()
    iv_regime = (row.get("opt_iv_regime") or "").strip()

    try:
        cat_days = int(float(row.get("catalyst_days", "") or "9999"))
    except (ValueError, TypeError):
        cat_days = 9999

    # Boost: OQC present + normal IV + cheap vol
    if oqc_nonzero and iv_regime == "NORMAL" and vol_class in ("CHEAP", "SLIGHTLY_CHEAP"):
        multiplier *= 1.20
        reasons.append("oqc_confirmed+cheap_vol(+20%)")

    # Boost: OQC present + low disagreement
    if oqc_nonzero and disagreement == "low":
        multiplier *= 1.10
        reasons.append("oqc_confirmed+model_market_agree(+10%)")

    # Cap: rich vol + near-term
    if vol_class == "RICH" and cat_days <= 75:
        multiplier *= 0.80
        reasons.append("rich_vol_near_term(-20%)")

    # Cap: high disagreement + near-term
    if disagreement == "high" and cat_days <= 75:
        multiplier *= 0.75
        reasons.append("high_disagreement_near_term(-25%)")

    # Enforce hard bounds
    multiplier = max(MULT_FLOOR, min(multiplier, MULT_CEILING))

    return {
        "weight_multiplier": round(multiplier, 4),
        "overlay_reasons": reasons,
        "overlay_applied": len(reasons) > 0,
    }
