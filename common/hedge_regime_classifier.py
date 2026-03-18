"""Hedge regime preference classifier — rule-based shadow signal.

Classifies whether the current market environment favors collars or
OTM puts as the primary hedge structure, using bioshort's existing
state variables.

Research-only — does not change production ranking or execution.

Inputs (all from bioshort's existing report surface):
    vrp                  — volatility risk premium (ATM IV - realized vol)
    vrp_percentile       — VRP vs trailing 1yr history
    cost_regime          — cheap / fair / expensive
    implied_move_pct     — nearest-expiry implied move
    r_squared            — hedge vehicle R² to portfolio
    skew_25d             — 25-delta put skew

Output:
    regime_preference    — collar_preferred / otm_put_preferred / ambiguous
    regime_confidence    — high / medium / low
    regime_reasons       — list of reasons supporting the classification
    regime_inputs        — dict of input values used

Decision logic (based on rolling-window study findings):
    - Collars dominate on average DD reduction but OTM puts win more
      individual windows on lowest absolute hedged DD
    - Collars outperform when protection is expensive (high VRP),
      because the upside cap costs less relative to the downside
      protection gained
    - OTM puts outperform when protection is cheap (low VRP), because
      the premium is small and there is no upside cap
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Thresholds (calibrated from rolling-window study)
# ---------------------------------------------------------------------------

# VRP regime splits
VRP_HIGH = 0.05  # VRP > 5% → protection expensive, collar territory
VRP_LOW = 0.02  # VRP < 2% → protection cheap, OTM put territory

# VRP percentile splits
VRP_PCTILE_HIGH = 0.75  # 75th percentile → elevated
VRP_PCTILE_LOW = 0.30  # 30th percentile → low

# Cost regime mapping
EXPENSIVE_REGIMES = ("expensive",)
CHEAP_REGIMES = ("cheap",)

# Hedge vehicle quality floor
R_SQUARED_MIN = 0.50  # below this, hedge vehicle is unreliable

# Skew threshold (put skew suggests fear premium)
SKEW_ELEVATED = -0.05  # skew more negative than -5% → put demand elevated


def classify_hedge_regime(
    vrp: Optional[float] = None,
    vrp_percentile: Optional[float] = None,
    cost_regime: str = "",
    implied_move_pct: Optional[float] = None,
    r_squared: Optional[float] = None,
    skew_25d: Optional[float] = None,
) -> Dict[str, Any]:
    """Classify whether the current environment favors collars or OTM puts.

    Returns dict with regime_preference, regime_confidence, regime_reasons,
    and regime_inputs.
    """
    reasons: List[str] = []
    collar_score = 0
    put_score = 0

    inputs = {
        "vrp": vrp,
        "vrp_percentile": vrp_percentile,
        "cost_regime": cost_regime,
        "implied_move_pct": implied_move_pct,
        "r_squared": r_squared,
        "skew_25d": skew_25d,
    }

    # --- VRP level ---
    if vrp is not None:
        if vrp > VRP_HIGH:
            collar_score += 2
            reasons.append(f"VRP={vrp:.1%} > {VRP_HIGH:.0%} (protection expensive → collar)")
        elif vrp < VRP_LOW:
            put_score += 2
            reasons.append(f"VRP={vrp:.1%} < {VRP_LOW:.0%} (protection cheap → OTM put)")
        else:
            reasons.append(f"VRP={vrp:.1%} (neutral)")

    # --- VRP percentile ---
    if vrp_percentile is not None:
        if vrp_percentile > VRP_PCTILE_HIGH:
            collar_score += 1
            reasons.append(f"VRP percentile={vrp_percentile:.0%} (elevated → collar)")
        elif vrp_percentile < VRP_PCTILE_LOW:
            put_score += 1
            reasons.append(f"VRP percentile={vrp_percentile:.0%} (low → OTM put)")

    # --- Cost regime ---
    if cost_regime in EXPENSIVE_REGIMES:
        collar_score += 2
        reasons.append(f"cost_regime={cost_regime} (expensive → collar)")
    elif cost_regime in CHEAP_REGIMES:
        put_score += 2
        reasons.append(f"cost_regime={cost_regime} (cheap → OTM put)")

    # --- Put skew ---
    if skew_25d is not None:
        if skew_25d < SKEW_ELEVATED:
            collar_score += 1
            reasons.append(f"put skew={skew_25d:.1%} (elevated fear premium → collar)")

    # --- Hedge vehicle quality ---
    if r_squared is not None and r_squared < R_SQUARED_MIN:
        reasons.append(f"R²={r_squared:.2f} below floor (hedge unreliable)")
        # Reduce confidence but don't change preference

    # --- Decision ---
    gap = collar_score - put_score

    if gap >= 3:
        preference = "collar_preferred"
        confidence = "high"
    elif gap >= 1:
        preference = "collar_preferred"
        confidence = "medium"
    elif gap <= -3:
        preference = "otm_put_preferred"
        confidence = "high"
    elif gap <= -1:
        preference = "otm_put_preferred"
        confidence = "medium"
    else:
        preference = "ambiguous"
        confidence = "low"

    # Downgrade confidence if hedge vehicle is weak
    if r_squared is not None and r_squared < R_SQUARED_MIN:
        if confidence == "high":
            confidence = "medium"
        elif confidence == "medium":
            confidence = "low"

    return {
        "regime_preference": preference,
        "regime_confidence": confidence,
        "collar_score": collar_score,
        "put_score": put_score,
        "regime_reasons": reasons,
        "regime_inputs": inputs,
    }
