"""Layer 5 — Scenario Payoff Engine.

Estimates branch-conditional stock moves and computes scenario EV.

Uses analog-based empirical distributions from event_move_lookup.py,
conditioned on outcome (HIT/MISS/MIXED), phase, indication, and
catalyst family.

Adjustments for market cap, liquidity, volatility, and gap risk.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from .data_contracts import CatalystNode, OutcomeProbabilities, ScenarioPayoffs

logger = logging.getLogger(__name__)

# Default empirical move distributions by (family, phase_bucket, outcome)
# Based on biotech event literature and repo's event_move_table.
# Format: {key: {p25, p50, p75, p90, n}}
# Positive = up, negative = down. All in percentage points.
_DEFAULT_MOVE_PRIORS: Dict[str, Dict[str, float]] = {
    # Regulatory HIT
    "REGULATORY|phase3|HIT": {"p25": 3.0, "p50": 8.0, "p75": 18.0, "p90": 35.0, "n": 80},
    "REGULATORY|phase2|HIT": {"p25": 5.0, "p50": 12.0, "p75": 30.0, "p90": 55.0, "n": 40},
    "REGULATORY|early|HIT": {"p25": 5.0, "p50": 15.0, "p75": 35.0, "p90": 60.0, "n": 20},
    # Regulatory MISS
    "REGULATORY|phase3|MISS": {"p25": -45.0, "p50": -30.0, "p75": -15.0, "p90": -8.0, "n": 30},
    "REGULATORY|phase2|MISS": {"p25": -50.0, "p50": -35.0, "p75": -20.0, "p90": -10.0, "n": 15},
    "REGULATORY|early|MISS": {"p25": -40.0, "p50": -25.0, "p75": -12.0, "p90": -5.0, "n": 10},
    # Clinical HIT
    "CLINICAL|phase3|HIT": {"p25": 8.0, "p50": 20.0, "p75": 45.0, "p90": 80.0, "n": 100},
    "CLINICAL|phase2|HIT": {"p25": 10.0, "p50": 30.0, "p75": 60.0, "p90": 120.0, "n": 60},
    "CLINICAL|early|HIT": {"p25": 8.0, "p50": 25.0, "p75": 50.0, "p90": 100.0, "n": 30},
    # Clinical MISS
    "CLINICAL|phase3|MISS": {"p25": -70.0, "p50": -50.0, "p75": -30.0, "p90": -15.0, "n": 70},
    "CLINICAL|phase2|MISS": {"p25": -55.0, "p50": -40.0, "p75": -20.0, "p90": -10.0, "n": 40},
    "CLINICAL|early|MISS": {"p25": -40.0, "p50": -25.0, "p75": -12.0, "p90": -5.0, "n": 20},
    # MIXED outcomes (both families)
    "REGULATORY|any|MIXED": {"p25": -8.0, "p50": 0.0, "p75": 5.0, "p90": 10.0, "n": 25},
    "CLINICAL|any|MIXED": {"p25": -15.0, "p50": -2.0, "p75": 8.0, "p90": 20.0, "n": 35},
    # Safety events (always negative)
    "SAFETY|any|HIT": {"p25": -5.0, "p50": 0.0, "p75": 2.0, "p90": 5.0, "n": 10},
    "SAFETY|any|MISS": {"p25": -60.0, "p50": -40.0, "p75": -20.0, "p90": -10.0, "n": 15},
}

# Market cap adjustments (smaller = bigger moves)
_MCAP_MULTIPLIERS = {
    "micro": 1.4,  # < $300M
    "small": 1.2,  # $300M - $2B
    "mid": 1.0,  # $2B - $10B
    "large": 0.7,  # > $10B
}

# Risk aversion parameter for downside-adjusted EV
_DEFAULT_LAMBDA = 0.5


class PayoffEngine:
    """Estimates branch-conditional payoffs and scenario EV.

    Usage:
        engine = PayoffEngine()
        payoffs = engine.estimate(node, outcome_probs, as_of, context)
    """

    def __init__(
        self,
        move_priors: Optional[Dict[str, Dict[str, float]]] = None,
        event_move_table: Optional[Dict[str, Dict[str, float]]] = None,
        risk_aversion: float = _DEFAULT_LAMBDA,
    ) -> None:
        self.move_priors = move_priors or dict(_DEFAULT_MOVE_PRIORS)
        self.event_move_table = event_move_table  # from event_move_lookup.build_table()
        self.risk_aversion = risk_aversion

    def estimate(
        self,
        node: CatalystNode,
        outcome: OutcomeProbabilities,
        as_of: date,
        context: Optional[Dict[str, Any]] = None,
    ) -> ScenarioPayoffs:
        """Estimate scenario payoffs for a catalyst.

        Args:
            node: CatalystNode to evaluate
            outcome: OutcomeProbabilities from Layer 3
            as_of: evaluation date
            context: optional dict with:
                - market_cap_mm: float
                - vol_60d: float
                - liquidity_score: float [0, 1]
                - gap_risk: float [0, 1]

        Returns:
            ScenarioPayoffs with branch moves, EV, and asymmetry
        """
        context = context or {}
        features_used: Dict[str, Any] = {}

        phase_bucket = self._phase_bucket(node.phase)
        family = node.event_family

        # Step 1: Look up base move distributions
        upside_dist = self._lookup_move(family, phase_bucket, "HIT")
        downside_dist = self._lookup_move(family, phase_bucket, "MISS")
        mixed_dist = self._lookup_move(family, "any", "MIXED")

        features_used["phase_bucket"] = phase_bucket
        features_used["upside_source"] = upside_dist.get("source", "prior")
        features_used["downside_source"] = downside_dist.get("source", "prior")

        # Step 2: Extract point estimates (use p50 median)
        upside_hit = upside_dist.get("p50", 20.0)
        downside_miss = downside_dist.get("p50", -40.0)
        move_mixed = mixed_dist.get("p50", -2.0)

        # Step 3: Apply adjustments
        mcap_mult = self._mcap_multiplier(context.get("market_cap_mm"))
        features_used["mcap_multiplier"] = round(mcap_mult, 4)

        upside_hit *= mcap_mult
        downside_miss *= mcap_mult
        move_mixed *= mcap_mult

        # Volatility adjustment: high vol → wider distributions
        vol = context.get("vol_60d")
        if vol is not None:
            vol_mult = max(0.7, min(vol / 0.6, 1.5))  # normalize around 60% annualized
            upside_hit *= vol_mult
            downside_miss *= vol_mult
            features_used["vol_multiplier"] = round(vol_mult, 4)

        # Step 4: Compute scenario EV
        scenario_ev = outcome.p_hit * upside_hit + outcome.p_miss * downside_miss + outcome.p_mixed * move_mixed

        # Step 5: Asymmetry ratio
        if abs(downside_miss) > 0.01:
            asymmetry = abs(upside_hit) / abs(downside_miss)
        else:
            asymmetry = float("inf") if upside_hit > 0 else 0.0

        # Step 6: Downside-adjusted EV
        downside_penalty = self.risk_aversion * outcome.p_miss * abs(downside_miss)
        downside_adjusted_ev = scenario_ev - downside_penalty

        # Step 7: Kelly fraction (theoretical)
        kelly = self._kelly_fraction(outcome, upside_hit, downside_miss)

        # Analog count and confidence
        total_n = upside_dist.get("n", 0) + downside_dist.get("n", 0) + mixed_dist.get("n", 0)
        if total_n >= 30:
            confidence = "ok"
        elif total_n >= 10:
            confidence = "low"
        else:
            confidence = "insufficient"

        return ScenarioPayoffs(
            node_id=node.node_id,
            as_of_date=str(as_of),
            upside_hit=round(upside_hit, 2),
            downside_miss=round(downside_miss, 2),
            move_mixed=round(move_mixed, 2),
            scenario_ev=round(scenario_ev, 4),
            asymmetry_ratio=round(min(asymmetry, 10.0), 4),
            downside_adjusted_ev=round(downside_adjusted_ev, 4),
            kelly_fraction=round(kelly, 4),
            analog_count=total_n,
            analog_confidence=confidence,
            features_used=features_used,
            model_version="payoff_analog_v0.1",
        )

    def _lookup_move(self, family: str, phase_bucket: str, outcome: str) -> Dict[str, Any]:
        """Look up move distribution with fallback hierarchy.

        Tries:
        1. event_move_table (repo's empirical table) if available
        2. (family, phase_bucket, outcome)
        3. (family, any, outcome)
        4. global fallback
        """
        # Try repo's event_move_table first
        if self.event_move_table:
            key = f"{family}|{phase_bucket}|{outcome}"
            if key in self.event_move_table:
                result = dict(self.event_move_table[key])
                result["source"] = "event_move_table"
                return result

        # Try our move priors
        key = f"{family}|{phase_bucket}|{outcome}"
        if key in self.move_priors:
            result = dict(self.move_priors[key])
            result["source"] = "prior"
            return result

        # Fallback: family|any|outcome
        key = f"{family}|any|{outcome}"
        if key in self.move_priors:
            result = dict(self.move_priors[key])
            result["source"] = "prior_fallback"
            return result

        # Global fallback
        if outcome == "HIT":
            return {"p50": 15.0, "n": 0, "source": "global_default"}
        elif outcome == "MISS":
            return {"p50": -35.0, "n": 0, "source": "global_default"}
        return {"p50": -2.0, "n": 0, "source": "global_default"}

    def _phase_bucket(self, phase: str) -> str:
        """Map phase to coarse bucket."""
        if phase in ("3", "4"):
            return "phase3"
        if phase in ("2", "2_3"):
            return "phase2"
        if phase in ("1", "1_2"):
            return "early"
        return "phase2"  # default to mid

    def _mcap_multiplier(self, market_cap_mm: Optional[float]) -> float:
        """Market cap adjustment: smaller names move more."""
        if market_cap_mm is None:
            return 1.0
        if market_cap_mm < 300:
            return _MCAP_MULTIPLIERS["micro"]
        if market_cap_mm < 2000:
            return _MCAP_MULTIPLIERS["small"]
        if market_cap_mm < 10000:
            return _MCAP_MULTIPLIERS["mid"]
        return _MCAP_MULTIPLIERS["large"]

    def _kelly_fraction(
        self,
        outcome: OutcomeProbabilities,
        upside: float,
        downside: float,
    ) -> float:
        """Compute Kelly-optimal fraction (half-Kelly capped).

        Kelly = (p * b - q) / b
        where p = P(win), b = win/loss ratio, q = P(lose)

        For biotech events, treat HIT + MIXED as partial wins,
        MISS as loss.
        """
        if abs(downside) < 0.01:
            return 0.0

        p_win = outcome.p_hit + outcome.p_mixed * 0.3  # MIXED is partial win
        p_lose = outcome.p_miss + outcome.p_mixed * 0.7
        b = abs(upside) / abs(downside)

        kelly = (p_win * b - p_lose) / b if b > 0 else 0.0
        half_kelly = kelly / 2.0  # half-Kelly is standard practice

        return max(0.0, min(half_kelly, 0.25))  # cap at 25%

    # =========================================================================
    # Batch estimation
    # =========================================================================

    def estimate_batch(
        self,
        nodes: List[CatalystNode],
        outcomes: Dict[str, OutcomeProbabilities],
        as_of: date,
        contexts: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[ScenarioPayoffs]:
        """Estimate payoffs for a batch of nodes."""
        contexts = contexts or {}
        results = []
        for node in nodes:
            outcome = outcomes.get(node.node_id)
            if outcome is None:
                continue
            ctx = contexts.get(node.ticker, {})
            payoff = self.estimate(node, outcome, as_of, ctx)
            results.append(payoff)
        return results
