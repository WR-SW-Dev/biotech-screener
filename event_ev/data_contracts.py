"""Data contracts for the Event EV Engine.

All dataclasses, enums, and type definitions used across layers.
Every output struct is frozen and serializable to dict/JSON.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional

# =============================================================================
# Enums
# =============================================================================


class EventFamily(str, Enum):
    REGULATORY = "REGULATORY"
    CLINICAL = "CLINICAL"
    SAFETY = "SAFETY"


class DatePrecision(str, Enum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    QUARTER = "QUARTER"
    HALF_YEAR = "HALF_YEAR"
    YEAR = "YEAR"
    UNKNOWN = "UNKNOWN"


class NodeStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"
    DELAYED = "DELAYED"


class OutcomeLabel(str, Enum):
    HIT = "HIT"
    MISS = "MISS"
    MIXED = "MIXED"


class BeliefDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNCERTAIN = "UNCERTAIN"


class PositionAction(str, Enum):
    HOLD = "HOLD"
    ADD = "ADD"
    TRIM = "TRIM"
    EXIT = "EXIT"
    NO_ACTION = "NO_ACTION"


# =============================================================================
# Layer 1 — Catalyst Graph
# =============================================================================


@dataclass
class CatalystRevision:
    """Single revision to a catalyst node field."""

    revision_date: str  # ISO date
    field_name: str
    old_value: str
    new_value: str
    source: str


@dataclass
class CatalystNode:
    """Unified catalyst event object (Layer 1).

    This is the core object that all downstream layers consume.
    Every node has a deterministic ID, PIT anchor, and provenance.
    """

    ticker: str
    event_family: str  # REGULATORY, CLINICAL, SAFETY
    event_type: str  # PDUFA, DATA_READOUT, PHASE_3_READOUT, etc.
    event_subtype: str  # TOPLINE, INTERIM, ADCOM, etc.

    # Timing
    expected_date: Optional[str]  # ISO date
    date_range_start: Optional[str]
    date_range_end: Optional[str]
    date_precision: str  # DAY, WEEK, MONTH, QUARTER, HALF_YEAR, UNKNOWN
    date_confidence: float  # [0, 1]

    # Provenance
    source: str  # CTGOV, SEC_8K, PDUFA_MANUAL, HERALD, FDA_FEDREG
    source_uid: str
    disclosed_at: str  # ISO date — PIT anchor

    # Context
    phase: str  # "1", "1_2", "2", "2_3", "3", "4", "unknown"
    indication: str
    modality: Optional[str] = None
    sponsor_quality: Optional[float] = None  # [0, 1]
    nct_id: Optional[str] = None

    # FDA regulatory context (for enriched PDUFA priors)
    review_type: Optional[str] = None  # PRIORITY, STANDARD
    designations: List[str] = field(default_factory=list)  # BTD, FT, ODD, RMAT
    has_prior_crl: bool = False  # True if resubmission after CRL
    adcom_outcome: Optional[str] = None  # unanimous_yes, strong_yes, etc.

    # Graph
    depends_on: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)

    # Status
    status: str = "PENDING"
    resolution: Optional[str] = None  # HIT, MISS, MIXED
    resolved_date: Optional[str] = None

    # Revision history
    revisions: List[CatalystRevision] = field(default_factory=list)

    # Computed
    node_id: str = ""

    def __post_init__(self) -> None:
        if not self.node_id:
            self.node_id = self._compute_id()

    def _compute_id(self) -> str:
        """Deterministic node ID from (ticker, event_type, source_uid, expected_date)."""
        raw = f"{self.ticker}|{self.event_type}|{self.source_uid}|{self.expected_date or ''}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def days_to_event(self, as_of: date) -> Optional[int]:
        """Calendar days from as_of to the event's effective date.

        For windowed events (date_range_start + date_range_end), uses the
        midpoint of the remaining window. For overdue windows where the
        range end is past, returns a small positive number (event is
        'imminent but undated') instead of negative.

        For exact events, returns simple calendar days.
        """
        if not self.expected_date:
            return None
        try:
            evt = date.fromisoformat(self.expected_date)

            # Windowed event: use range if available
            if self.date_range_end and self.date_precision in (
                "HALF_YEAR",
                "QUARTER",
                "MONTH",
            ):
                try:
                    end = date.fromisoformat(self.date_range_end)
                    start = date.fromisoformat(self.date_range_start) if self.date_range_start else evt

                    if end < as_of:
                        # Overdue window: event should have happened already
                        # Return small positive (imminent) instead of negative
                        return 15  # treat as ~2 weeks out
                    elif start <= as_of <= end:
                        # Inside the window: midpoint of remaining range
                        remaining = (end - as_of).days
                        return max(1, remaining // 2)
                    else:
                        # Future window: days to midpoint
                        mid = start + (end - start) / 2
                        return max(1, (mid - as_of).days)
                except (ValueError, TypeError):
                    pass

            return (evt - as_of).days
        except (ValueError, TypeError):
            return None

    def is_visible(self, as_of: date) -> bool:
        """PIT gate: node only visible if disclosed_at <= as_of."""
        try:
            return date.fromisoformat(self.disclosed_at) <= as_of
        except (ValueError, TypeError):
            return False

    def is_resolved(self) -> bool:
        return self.status == NodeStatus.RESOLVED.value and self.resolution is not None

    def pit_revisions(self, as_of: date) -> List[CatalystRevision]:
        """Only revisions known at as_of."""
        result = []
        for r in self.revisions:
            try:
                if date.fromisoformat(r.revision_date) <= as_of:
                    result.append(r)
            except (ValueError, TypeError):
                continue
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "ticker": self.ticker,
            "event_family": self.event_family,
            "event_type": self.event_type,
            "event_subtype": self.event_subtype,
            "expected_date": self.expected_date,
            "date_range_start": self.date_range_start,
            "date_range_end": self.date_range_end,
            "date_precision": self.date_precision,
            "date_confidence": self.date_confidence,
            "source": self.source,
            "source_uid": self.source_uid,
            "disclosed_at": self.disclosed_at,
            "phase": self.phase,
            "indication": self.indication,
            "modality": self.modality,
            "sponsor_quality": self.sponsor_quality,
            "nct_id": self.nct_id,
            "depends_on": self.depends_on,
            "blocks": self.blocks,
            "status": self.status,
            "resolution": self.resolution,
            "resolved_date": self.resolved_date,
            "revisions": [
                {
                    "revision_date": r.revision_date,
                    "field_name": r.field_name,
                    "old_value": r.old_value,
                    "new_value": r.new_value,
                    "source": r.source,
                }
                for r in self.revisions
            ],
        }


# =============================================================================
# Layer 2 — Timing Hazard
# =============================================================================


@dataclass(frozen=True)
class TimingEstimate:
    """Timing/execution hazard estimate for a catalyst node."""

    node_id: str
    as_of_date: str
    prob_on_time: float  # P(event in expected window)
    prob_slip: float  # P(event slips beyond window)
    prob_early: float  # P(event arrives early)
    expected_delay_days: float
    median_arrival_days: float  # from as_of to expected arrival
    hazard_rate: float  # instantaneous arrival rate
    features_used: Dict[str, Any] = field(default_factory=dict)
    model_version: str = "timing_v0.1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "as_of_date": self.as_of_date,
            "prob_on_time": round(self.prob_on_time, 4),
            "prob_slip": round(self.prob_slip, 4),
            "prob_early": round(self.prob_early, 4),
            "expected_delay_days": round(self.expected_delay_days, 1),
            "median_arrival_days": round(self.median_arrival_days, 1),
            "hazard_rate": round(self.hazard_rate, 6),
            "features_used": self.features_used,
            "model_version": self.model_version,
        }


# =============================================================================
# Layer 3 — Outcome Probabilities
# =============================================================================


@dataclass(frozen=True)
class OutcomeProbabilities:
    """Branch probabilities for catalyst outcome."""

    node_id: str
    as_of_date: str
    p_hit: float
    p_miss: float
    p_mixed: float
    confidence: float  # model confidence [0, 1]
    prior_source: str  # "wong_et_al", "v2_empirical", "indication_phase"
    features_used: Dict[str, Any] = field(default_factory=dict)
    calibration_check: Dict[str, Any] = field(default_factory=dict)
    model_version: str = "outcome_v0.1"

    def __post_init__(self) -> None:
        total = self.p_hit + self.p_miss + self.p_mixed
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Probabilities must sum to 1.0, got {total:.4f}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "as_of_date": self.as_of_date,
            "p_hit": round(self.p_hit, 4),
            "p_miss": round(self.p_miss, 4),
            "p_mixed": round(self.p_mixed, 4),
            "confidence": round(self.confidence, 4),
            "prior_source": self.prior_source,
            "features_used": self.features_used,
            "calibration_check": self.calibration_check,
            "model_version": self.model_version,
        }


# =============================================================================
# Layer 4 — Market Expectation / Crowd Belief
# =============================================================================


@dataclass(frozen=True)
class CrowdBelief:
    """Estimated market belief about a catalyst."""

    node_id: str
    as_of_date: str
    implied_p_hit: float  # market's implied P(positive outcome)
    belief_direction: str  # BULLISH, BEARISH, NEUTRAL, UNCERTAIN
    belief_intensity: float  # [0, 1]
    priced_move_pct: Optional[float]  # options-implied if available
    mispricing_score: float  # model P(HIT) - market implied P(HIT)
    features_used: Dict[str, Any] = field(default_factory=dict)
    model_version: str = "expectation_v0.1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "as_of_date": self.as_of_date,
            "implied_p_hit": round(self.implied_p_hit, 4),
            "belief_direction": self.belief_direction,
            "belief_intensity": round(self.belief_intensity, 4),
            "priced_move_pct": (round(self.priced_move_pct, 4) if self.priced_move_pct is not None else None),
            "mispricing_score": round(self.mispricing_score, 4),
            "features_used": self.features_used,
            "model_version": self.model_version,
        }


# =============================================================================
# Layer 5 — Scenario Payoffs
# =============================================================================


@dataclass(frozen=True)
class ScenarioPayoffs:
    """Branch-conditional payoffs and scenario EV."""

    node_id: str
    as_of_date: str
    # Branch payoffs (percentage moves)
    upside_hit: float  # expected % move if HIT
    downside_miss: float  # expected % move if MISS (negative)
    move_mixed: float  # expected % move if MIXED
    # Derived
    scenario_ev: float  # probability-weighted expected move
    asymmetry_ratio: float  # |upside_hit| / |downside_miss|
    downside_adjusted_ev: float  # EV with downside penalty
    kelly_fraction: float  # theoretical Kelly sizing
    # Diagnostics
    analog_count: int
    analog_confidence: str  # ok / low / insufficient
    features_used: Dict[str, Any] = field(default_factory=dict)
    model_version: str = "payoff_v0.1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "as_of_date": self.as_of_date,
            "upside_hit": round(self.upside_hit, 4),
            "downside_miss": round(self.downside_miss, 4),
            "move_mixed": round(self.move_mixed, 4),
            "scenario_ev": round(self.scenario_ev, 4),
            "asymmetry_ratio": round(self.asymmetry_ratio, 4),
            "downside_adjusted_ev": round(self.downside_adjusted_ev, 4),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "analog_count": self.analog_count,
            "analog_confidence": self.analog_confidence,
            "features_used": self.features_used,
            "model_version": self.model_version,
        }


# =============================================================================
# Layer 6 — Position Recommendation
# =============================================================================


@dataclass(frozen=True)
class PositionRecommendation:
    """Risk-adjusted position recommendation from event EV."""

    ticker: str
    node_id: str
    action: str  # HOLD, ADD, TRIM, EXIT, NO_ACTION
    target_weight_pct: float
    max_weight_pct: float
    ev_rank: int
    risk_flags: List[str] = field(default_factory=list)
    reasoning: Dict[str, Any] = field(default_factory=dict)
    model_version: str = "portfolio_v0.1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "node_id": self.node_id,
            "action": self.action,
            "target_weight_pct": round(self.target_weight_pct, 4),
            "max_weight_pct": round(self.max_weight_pct, 4),
            "ev_rank": self.ev_rank,
            "risk_flags": list(self.risk_flags),
            "reasoning": self.reasoning,
            "model_version": self.model_version,
        }


# =============================================================================
# Composite — EventEV
# =============================================================================


@dataclass
class EventEV:
    """Full event EV assessment tying all six layers together."""

    node: CatalystNode
    timing: TimingEstimate
    outcome: OutcomeProbabilities
    expectation: CrowdBelief
    payoff: ScenarioPayoffs
    position: Optional[PositionRecommendation] = None
    branch_sensitivity: Optional[Dict[str, Any]] = None

    @property
    def scenario_ev(self) -> float:
        return self.payoff.scenario_ev

    @property
    def mispricing_score(self) -> float:
        return self.expectation.mispricing_score

    @property
    def actionable(self) -> bool:
        """Event is actionable if EV > 0 and timing is near enough."""
        days = self.node.days_to_event(date.fromisoformat(self.timing.as_of_date))
        if days is None:
            return False
        return self.payoff.downside_adjusted_ev > 0 and 0 < days <= 180

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "node": self.node.to_dict(),
            "timing": self.timing.to_dict(),
            "outcome": self.outcome.to_dict(),
            "expectation": self.expectation.to_dict(),
            "payoff": self.payoff.to_dict(),
            "scenario_ev": round(self.scenario_ev, 4),
            "mispricing_score": round(self.mispricing_score, 4),
            "actionable": self.actionable,
        }
        if self.position:
            result["position"] = self.position.to_dict()
        if self.branch_sensitivity:
            result["branch_sensitivity"] = self.branch_sensitivity
        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)
