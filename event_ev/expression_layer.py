"""Options Expression Layer (Spec 062, Phase 1).

Translates Event EV mispricing diagnostics into structured options expression
recommendations. Diagnostic-only — does NOT touch selector, ranker, or
construction. Does NOT reopen options-as-alpha (Spec 053, CLOSED).

Policy: OVERLAY-ONLY. All outputs gated on liquid options. No threshold
fitting. No new data dependencies. Fail closed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from event_ev.data_contracts import (
    CatalystNode,
    CrowdBelief,
    ExpectationErrorScore,
    OutcomeProbabilities,
    ScenarioPayoffs,
    TimingEstimate,
)

logger = logging.getLogger(__name__)

MODEL_VERSION = "expression_v0.1"

# ============================================================================
# Closed enums (spec contract — adding a value requires spec amendment)
# ============================================================================

OVERLAY_CLASSES = frozenset(
    {
        "NO_TRADE",
        "DIRECTIONAL_DEBIT",
        "VARIANCE_DEBIT",
        "DEFINED_RISK_CREDIT",
        "TIMING_CALENDAR",
        "MANUAL_REVIEW",
    }
)

MISPRICING_TYPES = frozenset({"DIRECTIONAL", "VARIANCE", "SKEW", "TIMING", "MIXED", "NONE"})

# Structure → example_structures mapping (Level 2, informational)
_EXAMPLE_STRUCTURES: Dict[str, List[str]] = {
    "DIRECTIONAL_DEBIT": ["bull_call_spread", "put_spread", "risk_reversal"],
    "VARIANCE_DEBIT": ["long_straddle", "long_strangle"],
    "DEFINED_RISK_CREDIT": ["iron_condor", "iron_butterfly"],
    "TIMING_CALENDAR": ["calendar_spread", "diagonal_spread"],
    "MANUAL_REVIEW": [],
    "NO_TRADE": [],
}

# Structure → leg count
_LEG_COUNTS: Dict[str, int] = {
    "DIRECTIONAL_DEBIT": 2,
    "VARIANCE_DEBIT": 1,
    "DEFINED_RISK_CREDIT": 4,
    "TIMING_CALENDAR": 2,
    "MANUAL_REVIEW": 0,
    "NO_TRADE": 0,
}

# Structure → max bid-ask spread per leg
_MAX_SPREAD_PCT: Dict[str, float] = {
    "DIRECTIONAL_DEBIT": 0.06,
    "VARIANCE_DEBIT": 0.08,
    "DEFINED_RISK_CREDIT": 0.04,
    "TIMING_CALENDAR": 0.08,
    "MANUAL_REVIEW": 0.0,
    "NO_TRADE": 0.0,
}


# ============================================================================
# Output dataclass
# ============================================================================


@dataclass(frozen=True)
class ExpressionRecommendation:
    """Structured options expression recommendation (overlay-only).

    Naming discipline: the field is ``overlay_class``, never
    ``trade_signal``. This anchors the object's diagnostic role.
    """

    ticker: str
    node_id: str
    as_of_date: str

    # Classification
    mispricing_type: str  # DIRECTIONAL | VARIANCE | SKEW | TIMING | MIXED | NONE
    mispricing_subtype: str

    # Belief vs permission (two distinct concepts)
    belief_strength: float  # [0, 1]
    permission_to_express: float  # [0, 1]
    mispricing_confidence: float  # min(belief, permission)

    # Recommendation
    overlay_class: str  # closed enum (6 values)
    example_structures: Tuple[str, ...]  # informational
    overlay_rationale: str

    # Snapshot at recommendation time (for attribution)
    priced_move_pct: Optional[float]  # options-implied move %
    scenario_ev: float  # probability-weighted expected move
    opt_atm_iv: Optional[float]  # ATM IV at recommendation time

    # Sizing guidance
    max_premium_pct_nav: float
    sizing_basis: str  # kelly_capped | fixed_notional | no_size

    # Execution constraints
    surface_quality_score: float  # [0, 100]
    execution_risk: str  # low | moderate | high
    leg_count: int
    max_spread_pct: float

    # Tradeability gates
    is_tradeable: bool
    gate_failures: Tuple[str, ...]

    # Governance (always "overlay_only")
    governance_class: str = "overlay_only"
    policy_flags: Tuple[str, ...] = (
        "not_alpha",
        "not_ranking",
        "operator_review_required",
    )

    # Provenance
    inputs_used: Dict[str, Any] = field(default_factory=dict)
    model_version: str = MODEL_VERSION

    def __post_init__(self) -> None:
        if self.overlay_class not in OVERLAY_CLASSES:
            raise ValueError(f"overlay_class must be one of {sorted(OVERLAY_CLASSES)}, " f"got {self.overlay_class!r}")
        if self.mispricing_type not in MISPRICING_TYPES:
            raise ValueError(
                f"mispricing_type must be one of {sorted(MISPRICING_TYPES)}, " f"got {self.mispricing_type!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "node_id": self.node_id,
            "as_of_date": self.as_of_date,
            "mispricing_type": self.mispricing_type,
            "mispricing_subtype": self.mispricing_subtype,
            "belief_strength": round(self.belief_strength, 4),
            "permission_to_express": round(self.permission_to_express, 4),
            "mispricing_confidence": round(self.mispricing_confidence, 4),
            "priced_move_pct": round(self.priced_move_pct, 4) if self.priced_move_pct is not None else None,
            "scenario_ev": round(self.scenario_ev, 4),
            "opt_atm_iv": round(self.opt_atm_iv, 4) if self.opt_atm_iv is not None else None,
            "overlay_class": self.overlay_class,
            "example_structures": list(self.example_structures),
            "overlay_rationale": self.overlay_rationale,
            "max_premium_pct_nav": round(self.max_premium_pct_nav, 4),
            "sizing_basis": self.sizing_basis,
            "surface_quality_score": round(self.surface_quality_score, 2),
            "execution_risk": self.execution_risk,
            "leg_count": self.leg_count,
            "max_spread_pct": round(self.max_spread_pct, 4),
            "is_tradeable": self.is_tradeable,
            "gate_failures": list(self.gate_failures),
            "governance_class": self.governance_class,
            "policy_flags": list(self.policy_flags),
            "inputs_used": self.inputs_used,
            "model_version": self.model_version,
        }


# ============================================================================
# Surface quality
# ============================================================================


def compute_surface_quality(
    opt_liquidity_state: str,
    bid_ask_spread_pct: Optional[float],
    quote_fresh: bool = True,
) -> float:
    """Surface quality score [0, 100].

    Components:
      - liquidity: liquid → 100, else 0
      - freshness: fresh quote → 100, stale → 0
      - spread: 100 - min(100, spread_pct * 10)
      - depth: mirrors liquidity (same source)
    """
    liquidity = 100.0 if opt_liquidity_state == "liquid" else 0.0
    freshness = 100.0 if quote_fresh else 0.0

    if bid_ask_spread_pct is not None and bid_ask_spread_pct >= 0:
        spread_component = max(0.0, 100.0 - bid_ask_spread_pct * 1000.0)
    else:
        spread_component = 50.0  # unknown → neutral

    depth = liquidity  # from same underlying state

    score = (liquidity + freshness + spread_component + depth) / 4.0
    return round(max(0.0, min(100.0, score)), 2)


# ============================================================================
# Confidence computations
# ============================================================================


def compute_belief_strength(
    outcome_confidence: float,
    ees_confidence: float,
    belief_intensity_modifier: float,
    data_completeness: float = 1.0,
) -> float:
    """How strong the mispricing diagnosis is, independent of execution.

    belief_intensity_modifier comes from surface_diagnostics (0.5–1.5).
    data_completeness: 1.0=all present, 0.8=surface missing, 0.6=imputed move.
    """
    bim_scaled = belief_intensity_modifier * 0.8 + 0.2
    raw = min(outcome_confidence, ees_confidence, bim_scaled)
    return round(max(0.0, min(1.0, raw * data_completeness)), 4)


def compute_permission_to_express(
    surface_quality_score: float,
    bid_ask_spread_pct: Optional[float],
    max_spread_for_structure: float,
    opt_liquidity_state: str,
    execution_risk: str,
) -> float:
    """Whether execution context allows any structure.

    Independent of mispricing diagnosis.
    """
    sq = surface_quality_score / 100.0

    if bid_ask_spread_pct is not None and max_spread_for_structure > 0 and bid_ask_spread_pct >= 0:
        spread_quality = max(0.0, 1.0 - bid_ask_spread_pct / max_spread_for_structure)
    else:
        spread_quality = 0.5

    liquidity_factor = 1.0 if opt_liquidity_state == "liquid" else 0.0

    exec_map = {"low": 1.0, "moderate": 0.7, "high": 0.4}
    exec_factor = exec_map.get(execution_risk, 0.4)

    raw = min(sq, spread_quality, liquidity_factor, exec_factor)
    return round(max(0.0, min(1.0, raw)), 4)


def compute_variance_confidence(
    ees_confidence: float,
    surface_quality_score: float,
    analog_confidence: str,
    base_rate_n: int = 30,
) -> float:
    """Extra confidence gate for VARIANCE mispricing classification.

    Stricter than general confidence — wrong variance calls are expensive.
    """
    analog_map = {"ok": 1.0, "low": 0.5, "insufficient": 0.0}
    analog_num = analog_map.get(analog_confidence, 0.0)

    if base_rate_n >= 30:
        sample_factor = 1.0
    elif base_rate_n >= 10:
        sample_factor = 0.7
    else:
        sample_factor = 0.4

    raw = min(ees_confidence, surface_quality_score / 100.0, analog_num)
    return round(max(0.0, min(1.0, raw * sample_factor)), 4)


def compute_timing_confidence(
    prob_on_time: float,
    prob_slip: float,
    surface_quality_score: float,
    date_precision: str,
) -> float:
    """Extra confidence gate for TIMING mispricing classification.

    Highest bar — timing is the weakest validated component.
    """
    # Timing model consistency: probs should sum near 1.0
    timing_sum = prob_on_time + prob_slip
    timing_proxy = min(1.0, timing_sum) if timing_sum > 0 else 0.0

    sq = surface_quality_score / 100.0

    # Coarser precision → more room for delay → more confident delay thesis
    precision_map = {
        "DAY": 0.3,
        "WEEK": 0.4,
        "MONTH": 0.6,
        "QUARTER": 0.8,
        "HALF_YEAR": 1.0,
        "YEAR": 1.0,
        "UNKNOWN": 0.5,
    }
    precision_factor = precision_map.get(date_precision, 0.5)

    raw = min(timing_proxy, sq, precision_factor)
    return round(max(0.0, min(1.0, raw)), 4)


# ============================================================================
# Mispricing classification
# ============================================================================


def classify_mispricing(
    *,
    # CrowdBelief
    mispricing_score: float,
    # ScenarioPayoffs
    scenario_ev: float,
    analog_confidence: str,
    # OutcomeProbabilities
    outcome_confidence: float,
    p_hit: float,
    p_miss: float,
    # ExpectationErrorScore
    base_rate_gap_score: float,
    conditional_misprice_score: float,
    crowding_bias_score: float,
    timing_decay_risk_score: float,
    divergence_score: float,
    ees_confidence: float,
    # TimingEstimate
    prob_slip: float,
    prob_on_time: float,
    # CatalystNode
    date_precision: str,
    # Options surface
    priced_move_pct: Optional[float],
    opt_rr_25d: Optional[float],
    term_structure_shape: Optional[str],
    # Surface quality
    surface_quality_score: float,
    # Base rate sample size (for variance confidence)
    base_rate_n: int = 30,
) -> Tuple[str, str]:
    """Classify the mispricing type and subtype.

    Returns (mispricing_type, mispricing_subtype). Fail-closed: returns
    ("NONE", "") when evidence is insufficient.

    Priority order: DIRECTIONAL > VARIANCE > SKEW > TIMING.
    MIXED triggers when 2+ types qualify at reduced (0.7x) thresholds.
    """
    # Track which types qualify at full and reduced thresholds
    full_hits: List[Tuple[str, str, float]] = []
    reduced_hits: List[Tuple[str, str, float]] = []

    # --- DIRECTIONAL ---
    dir_ok = (
        abs(mispricing_score) >= 0.15
        and abs(scenario_ev) >= 3.0
        and outcome_confidence >= 0.50
        and (
            (mispricing_score > 0 and conditional_misprice_score > 0)
            or (mispricing_score < 0 and conditional_misprice_score < 0)
        )
    )
    if dir_ok:
        if mispricing_score > 0 and scenario_ev > 0:
            sub = "bullish_underpriced"
        else:
            sub = "bearish_underpriced"
        full_hits.append(("DIRECTIONAL", sub, abs(mispricing_score)))

    dir_reduced = (
        abs(mispricing_score) >= 0.15 * 0.7
        and abs(scenario_ev) >= 3.0 * 0.7
        and outcome_confidence >= 0.50 * 0.7
        and (
            (mispricing_score > 0 and conditional_misprice_score > 0)
            or (mispricing_score < 0 and conditional_misprice_score < 0)
        )
    )
    if dir_reduced:
        sub = "bullish_underpriced" if (mispricing_score > 0 and scenario_ev > 0) else "bearish_underpriced"
        reduced_hits.append(("DIRECTIONAL", sub, abs(mispricing_score)))

    # --- VARIANCE ---
    # Only if directional is NOT the primary signal
    var_conf = compute_variance_confidence(ees_confidence, surface_quality_score, analog_confidence, base_rate_n)
    var_ok = (
        abs(base_rate_gap_score) >= 0.30
        and ((base_rate_gap_score > 0 and divergence_score > 0) or (base_rate_gap_score < 0 and divergence_score < 0))
        and priced_move_pct is not None
        and abs(mispricing_score) < 0.15  # directional NOT primary
        and var_conf >= 0.55
    )
    if var_ok:
        sub = "vol_underpriced" if base_rate_gap_score < -0.30 else "vol_overpriced"
        full_hits.append(("VARIANCE", sub, abs(base_rate_gap_score)))

    var_reduced = (
        abs(base_rate_gap_score) >= 0.30 * 0.7
        and ((base_rate_gap_score > 0 and divergence_score > 0) or (base_rate_gap_score < 0 and divergence_score < 0))
        and priced_move_pct is not None
        and abs(mispricing_score) < 0.15 * 0.7 + 0.15  # looser directional filter
        and var_conf >= 0.55 * 0.7
    )
    if var_reduced:
        sub = "vol_underpriced" if base_rate_gap_score < -0.30 * 0.7 else "vol_overpriced"
        reduced_hits.append(("VARIANCE", sub, abs(base_rate_gap_score)))

    # --- SKEW ---
    skew_ok = (
        opt_rr_25d is not None
        and abs(crowding_bias_score) >= 0.30
        and abs(mispricing_score) < 0.15  # directional below threshold
        and abs(base_rate_gap_score) < 0.30  # variance below threshold
    )
    if skew_ok:
        if crowding_bias_score > 0.30 and p_hit > p_miss:
            sub = "put_skew_rich"
        elif crowding_bias_score < -0.30 and p_miss > p_hit:
            sub = "call_skew_rich"
        else:
            sub = ""
        if sub:
            full_hits.append(("SKEW", sub, abs(crowding_bias_score)))

    skew_reduced = opt_rr_25d is not None and abs(crowding_bias_score) >= 0.30 * 0.7
    if skew_reduced:
        if crowding_bias_score > 0.30 * 0.7 and p_hit > p_miss:
            sub = "put_skew_rich"
        elif crowding_bias_score < -0.30 * 0.7 and p_miss > p_hit:
            sub = "call_skew_rich"
        else:
            sub = ""
        if sub:
            reduced_hits.append(("SKEW", sub, abs(crowding_bias_score)))

    # --- TIMING ---
    timing_conf = compute_timing_confidence(prob_on_time, prob_slip, surface_quality_score, date_precision)
    timing_ok = (
        prob_slip >= 0.25
        and timing_decay_risk_score >= 0.40
        and term_structure_shape in ("backwardation", "backwardation_extreme")
        and date_precision in ("MONTH", "QUARTER", "HALF_YEAR", "YEAR", "UNKNOWN")
        and timing_conf >= 0.60
    )
    if timing_ok:
        full_hits.append(("TIMING", "near_term_overpriced", timing_conf))

    timing_reduced = (
        prob_slip >= 0.25 * 0.7
        and timing_decay_risk_score >= 0.40 * 0.7
        and term_structure_shape in ("backwardation", "backwardation_extreme")
        and date_precision in ("MONTH", "QUARTER", "HALF_YEAR", "YEAR", "UNKNOWN")
        and timing_conf >= 0.60 * 0.7
    )
    if timing_reduced:
        reduced_hits.append(("TIMING", "near_term_overpriced", timing_conf))

    # --- Selection ---
    if full_hits:
        # Priority: first full hit wins (DIRECTIONAL > VARIANCE > SKEW > TIMING)
        return full_hits[0][0], full_hits[0][1]

    # MIXED: 2+ types at reduced threshold, no full hit
    if len(reduced_hits) >= 2:
        # Pick highest-confidence component as subtype
        best = max(reduced_hits, key=lambda x: x[2])
        return "MIXED", best[1]

    return "NONE", ""


# ============================================================================
# Expression mapping
# ============================================================================


def select_overlay_class(
    mispricing_type: str,
    mispricing_subtype: str,
    *,
    asymmetry_ratio: float = 1.0,
    p_hit: float = 0.5,
    p_miss: float = 0.5,
    date_precision: str = "MONTH",
    belief_strength: float = 0.0,
    permission_to_express: float = 0.0,
) -> Tuple[str, List[str], str]:
    """Deterministic mapping from mispricing → overlay class.

    Returns (overlay_class, example_structures, rationale).
    Applies context overrides (asymmetry, binary, timing uncertainty,
    belief-permission split).
    """
    if mispricing_type == "NONE":
        return "NO_TRADE", [], "No actionable mispricing detected."

    if mispricing_type == "MIXED":
        return (
            "MANUAL_REVIEW",
            [],
            f"Multiple mispricing signals at moderate strength (dominant: {mispricing_subtype}).",
        )

    # Base mapping
    base_map: Dict[Tuple[str, str], Tuple[str, str]] = {
        ("DIRECTIONAL", "bullish_underpriced"): (
            "DIRECTIONAL_DEBIT",
            "Directional bullish; model P(HIT) > market implied.",
        ),
        ("DIRECTIONAL", "bearish_underpriced"): (
            "DIRECTIONAL_DEBIT",
            "Directional bearish; model P(MISS) > market implied.",
        ),
        ("VARIANCE", "vol_underpriced"): (
            "VARIANCE_DEBIT",
            "Implied move underprices historical base rate.",
        ),
        ("VARIANCE", "vol_overpriced"): (
            "DEFINED_RISK_CREDIT",
            "Implied move overprices historical base rate; sell premium.",
        ),
        ("SKEW", "put_skew_rich"): (
            "DIRECTIONAL_DEBIT",
            "Put skew rich vs upside probability; sell rich puts, buy calls.",
        ),
        ("SKEW", "call_skew_rich"): (
            "DIRECTIONAL_DEBIT",
            "Call skew rich vs downside probability.",
        ),
        ("TIMING", "near_term_overpriced"): (
            "TIMING_CALENDAR",
            "Near-term premium overpriced; timing model expects delay.",
        ),
    }

    key = (mispricing_type, mispricing_subtype)
    if key not in base_map:
        return "NO_TRADE", [], f"Unknown mispricing: {mispricing_type}/{mispricing_subtype}."

    overlay_class, rationale = base_map[key]

    # --- Context override 1: Asymmetry gate ---
    if asymmetry_ratio > 2.5 and mispricing_type == "VARIANCE" and mispricing_subtype == "vol_underpriced":
        overlay_class = "DIRECTIONAL_DEBIT"
        rationale = "Asymmetry ratio > 2.5 overrides variance trade; " "directional asymmetry dominates."

    # --- Context override 2: Binary gate ---
    if p_hit + p_miss > 0.90 and overlay_class == "DEFINED_RISK_CREDIT":
        overlay_class = "MANUAL_REVIEW"
        rationale = "Binary event (p_hit + p_miss > 0.90) forbids short gamma. " "Demoted from DEFINED_RISK_CREDIT."

    # --- Context override 3: Timing uncertainty gate ---
    if date_precision in ("QUARTER", "HALF_YEAR", "YEAR", "UNKNOWN") and overlay_class == "VARIANCE_DEBIT":
        # Theta burn too uncertain; demote to TIMING_CALENDAR or MANUAL_REVIEW
        if mispricing_type == "TIMING" or mispricing_subtype == "near_term_overpriced":
            overlay_class = "TIMING_CALENDAR"
            rationale = "Coarse date precision demotes variance to calendar."
        else:
            overlay_class = "MANUAL_REVIEW"
            rationale = "Coarse date precision with variance mispricing; " "theta burn too uncertain."

    # --- Context override 4: Belief-permission split ---
    if belief_strength >= 0.60 and permission_to_express < 0.40:
        overlay_class = "MANUAL_REVIEW"
        rationale = (
            "Strong thesis (belief={:.2f}) but poor execution context "
            "(permission={:.2f}). Watch, don't act.".format(belief_strength, permission_to_express)
        )

    examples = list(_EXAMPLE_STRUCTURES.get(overlay_class, []))
    return overlay_class, examples, rationale


# ============================================================================
# Tradeability gates
# ============================================================================


def check_tradeability_gates(
    *,
    opt_liquidity_state: str,
    surface_quality_score: float,
    days_to_event: Optional[int],
    analog_confidence: str,
    outcome_confidence: float,
    ees_confidence: float,
    priced_move_pct: Optional[float],
    mispricing_type: str,
    overlay_class: str,
    bid_ask_spread_pct: Optional[float],
    opt_rr_25d: Optional[float],
    p_hit: float,
    p_miss: float,
    prob_slip: float,
    variance_confidence: float,
    timing_confidence: float,
    execution_risk: str,
) -> List[str]:
    """Check all tradeability gates. Returns list of failure reasons (empty = pass)."""
    failures: List[str] = []

    # Universal gates
    if opt_liquidity_state != "liquid":
        failures.append("illiquid_options")

    if surface_quality_score < 50:
        failures.append("invalid_surface")

    if days_to_event is None:
        failures.append("event_too_far")
    elif days_to_event < 3:
        failures.append("event_too_near")
    elif days_to_event > 60:
        failures.append("event_too_far")

    if analog_confidence == "insufficient":
        failures.append("insufficient_analogs")

    if outcome_confidence < 0.40:
        failures.append("low_model_confidence")

    if ees_confidence < 0.50:
        failures.append("low_ees_confidence")

    if priced_move_pct is None or priced_move_pct <= 0:
        failures.append("no_priced_move")

    if mispricing_type == "NONE":
        failures.append("no_mispricing")

    # Spread width gate (per-leg)
    max_spread = _MAX_SPREAD_PCT.get(overlay_class, 0.0)
    if max_spread > 0 and bid_ask_spread_pct is not None and bid_ask_spread_pct > max_spread:
        failures.append("spread_too_wide")

    # Structure-specific gates
    if overlay_class == "DIRECTIONAL_DEBIT" and "risk_reversal" in _EXAMPLE_STRUCTURES.get(overlay_class, []):
        # Risk reversal needs skew data (applies to all DIRECTIONAL_DEBIT but non-fatal)
        pass  # opt_rr_25d is optional for directional

    if overlay_class == "DEFINED_RISK_CREDIT":
        if p_hit + p_miss > 0.90:
            failures.append("binary_event")
        if surface_quality_score < 70:
            failures.append("surface_too_weak_for_short_gamma")

    if overlay_class == "TIMING_CALENDAR":
        if prob_slip < 0.20:
            failures.append("low_delay_probability")
        if timing_confidence < 0.60:
            failures.append("low_timing_confidence")

    if overlay_class == "VARIANCE_DEBIT":
        if variance_confidence < 0.55:
            failures.append("low_variance_confidence")

    # 4-leg execution risk gate
    leg_count = _LEG_COUNTS.get(overlay_class, 0)
    if leg_count >= 4 and execution_risk == "high" and surface_quality_score < 70:
        failures.append("high_execution_risk")

    return failures


# ============================================================================
# Sizing
# ============================================================================


def compute_execution_risk(leg_count: int) -> str:
    """Map leg count to execution risk label."""
    if leg_count <= 1:
        return "low"
    if leg_count <= 2:
        return "moderate"
    return "high"


def compute_sizing(mispricing_confidence: float) -> Tuple[float, str]:
    """Conservative, policy-based sizing.

    Returns (max_premium_pct_nav, sizing_basis).
    """
    if mispricing_confidence >= 0.70:
        return 0.50, "kelly_capped"
    if mispricing_confidence >= 0.50:
        return 0.30, "fixed_notional"
    return 0.0, "no_size"


# ============================================================================
# Orchestrator
# ============================================================================


def build_recommendation(
    *,
    # Required layer outputs
    node: CatalystNode,
    outcome: OutcomeProbabilities,
    crowd: CrowdBelief,
    payoff: ScenarioPayoffs,
    ees: ExpectationErrorScore,
    timing: TimingEstimate,
    as_of_date: str,
    # Options surface context (from CSV row / chain analytics)
    opt_liquidity_state: str = "",
    opt_atm_iv: Optional[float] = None,
    opt_front_iv: Optional[float] = None,
    opt_back_iv: Optional[float] = None,
    opt_rr_25d: Optional[float] = None,
    bid_ask_spread_pct: Optional[float] = None,
    priced_move_pct: Optional[float] = None,
    quote_fresh: bool = True,
    # Surface diagnostics (pre-computed)
    term_structure_shape: Optional[str] = None,
    belief_intensity_modifier: float = 1.0,
    # Base rate sample size
    base_rate_n: int = 30,
) -> ExpressionRecommendation:
    """Build a complete ExpressionRecommendation.

    Orchestrates: surface quality → classification → overlay mapping →
    tradeability gates → sizing → package.

    Fail-closed: missing/bad inputs → NO_TRADE.
    """
    ticker = node.ticker
    node_id = node.node_id

    # Days to event
    try:
        from datetime import date as _date

        days_to_event = node.days_to_event(_date.fromisoformat(as_of_date))
    except (ValueError, TypeError):
        days_to_event = None

    # Catalyst days for term structure (if not pre-computed)
    catalyst_days = days_to_event if days_to_event and days_to_event > 0 else 0

    # Term structure shape (compute if not provided)
    if term_structure_shape is None and opt_front_iv and opt_back_iv and catalyst_days > 0:
        from event_ev.surface_diagnostics import classify_term_structure

        term_structure_shape = classify_term_structure(opt_front_iv, opt_back_iv, catalyst_days)

    # Surface quality
    sq = compute_surface_quality(opt_liquidity_state, bid_ask_spread_pct, quote_fresh)

    # Data completeness factor
    data_completeness = 1.0
    if opt_front_iv is None and opt_back_iv is None:
        data_completeness = 0.8  # surface diagnostics missing
    if priced_move_pct is None:
        data_completeness = min(data_completeness, 0.6)

    # Classify mispricing
    mp_type, mp_subtype = classify_mispricing(
        mispricing_score=crowd.mispricing_score,
        scenario_ev=payoff.scenario_ev,
        analog_confidence=payoff.analog_confidence,
        outcome_confidence=outcome.confidence,
        p_hit=outcome.p_hit,
        p_miss=outcome.p_miss,
        base_rate_gap_score=ees.base_rate_gap_score,
        conditional_misprice_score=ees.conditional_misprice_score,
        crowding_bias_score=ees.crowding_bias_score,
        timing_decay_risk_score=ees.timing_decay_risk_score,
        divergence_score=ees.divergence_score,
        ees_confidence=ees.expectation_confidence,
        prob_slip=timing.prob_slip,
        prob_on_time=timing.prob_on_time,
        date_precision=node.date_precision,
        priced_move_pct=priced_move_pct,
        opt_rr_25d=opt_rr_25d,
        term_structure_shape=term_structure_shape,
        surface_quality_score=sq,
        base_rate_n=base_rate_n,
    )

    # Belief strength
    belief = compute_belief_strength(
        outcome.confidence,
        ees.expectation_confidence,
        belief_intensity_modifier,
        data_completeness,
    )

    # Preliminary overlay class (needed for permission computation)
    prelim_class, _, _ = select_overlay_class(
        mp_type,
        mp_subtype,
        asymmetry_ratio=payoff.asymmetry_ratio,
        p_hit=outcome.p_hit,
        p_miss=outcome.p_miss,
        date_precision=node.date_precision,
        belief_strength=belief,
        permission_to_express=0.5,  # placeholder for first pass
    )

    # Leg count and execution risk
    leg_count = _LEG_COUNTS.get(prelim_class, 0)
    exec_risk = compute_execution_risk(leg_count)

    # Max spread for this structure
    max_spread = _MAX_SPREAD_PCT.get(prelim_class, 0.0)

    # Permission to express
    permission = compute_permission_to_express(sq, bid_ask_spread_pct, max_spread, opt_liquidity_state, exec_risk)

    # Final overlay class (with belief/permission context)
    overlay_class, examples, rationale = select_overlay_class(
        mp_type,
        mp_subtype,
        asymmetry_ratio=payoff.asymmetry_ratio,
        p_hit=outcome.p_hit,
        p_miss=outcome.p_miss,
        date_precision=node.date_precision,
        belief_strength=belief,
        permission_to_express=permission,
    )

    # Update leg count / exec risk / max spread for final class
    leg_count = _LEG_COUNTS.get(overlay_class, 0)
    exec_risk = compute_execution_risk(leg_count)
    max_spread = _MAX_SPREAD_PCT.get(overlay_class, 0.0)

    # Mispricing confidence
    confidence = round(min(belief, permission), 4)

    # Sizing
    max_premium, sizing_basis = compute_sizing(confidence)

    # Variance and timing confidence for gates
    var_conf = compute_variance_confidence(ees.expectation_confidence, sq, payoff.analog_confidence, base_rate_n)
    timing_conf = compute_timing_confidence(timing.prob_on_time, timing.prob_slip, sq, node.date_precision)

    # Tradeability gates
    gate_failures = check_tradeability_gates(
        opt_liquidity_state=opt_liquidity_state,
        surface_quality_score=sq,
        days_to_event=days_to_event,
        analog_confidence=payoff.analog_confidence,
        outcome_confidence=outcome.confidence,
        ees_confidence=ees.expectation_confidence,
        priced_move_pct=priced_move_pct,
        mispricing_type=mp_type,
        overlay_class=overlay_class,
        bid_ask_spread_pct=bid_ask_spread_pct,
        opt_rr_25d=opt_rr_25d,
        p_hit=outcome.p_hit,
        p_miss=outcome.p_miss,
        prob_slip=timing.prob_slip,
        variance_confidence=var_conf,
        timing_confidence=timing_conf,
        execution_risk=exec_risk,
    )

    is_tradeable = len(gate_failures) == 0

    # Inputs provenance
    inputs_used = {
        "mispricing_score": round(crowd.mispricing_score, 4),
        "scenario_ev": round(payoff.scenario_ev, 4),
        "base_rate_gap_score": round(ees.base_rate_gap_score, 4),
        "crowding_bias_score": round(ees.crowding_bias_score, 4),
        "timing_decay_risk_score": round(ees.timing_decay_risk_score, 4),
        "outcome_confidence": round(outcome.confidence, 4),
        "ees_confidence": round(ees.expectation_confidence, 4),
        "variance_confidence": round(var_conf, 4),
        "timing_confidence": round(timing_conf, 4),
        "surface_quality_score": round(sq, 2),
        "term_structure_shape": term_structure_shape,
        "data_completeness": data_completeness,
    }

    return ExpressionRecommendation(
        ticker=ticker,
        node_id=node_id,
        as_of_date=as_of_date,
        mispricing_type=mp_type,
        mispricing_subtype=mp_subtype,
        belief_strength=belief,
        permission_to_express=permission,
        mispricing_confidence=confidence,
        priced_move_pct=priced_move_pct,
        scenario_ev=payoff.scenario_ev,
        opt_atm_iv=opt_atm_iv,
        overlay_class=overlay_class,
        example_structures=tuple(examples),
        overlay_rationale=rationale,
        max_premium_pct_nav=max_premium,
        sizing_basis=sizing_basis,
        surface_quality_score=sq,
        execution_risk=exec_risk,
        leg_count=leg_count,
        max_spread_pct=max_spread,
        is_tradeable=is_tradeable,
        gate_failures=tuple(gate_failures),
        inputs_used=inputs_used,
        model_version=MODEL_VERSION,
    )
