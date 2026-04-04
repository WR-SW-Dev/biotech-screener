"""Layer 6 — Portfolio / Risk Translation.

Converts event EV into tradeable position recommendations
subject to risk constraints from the production risk layer.

Sizing modes:
1. EV-proportional: weight proportional to downside-adjusted EV
2. Kelly-capped: half-Kelly with production caps
3. EW with EV filter: equal-weight among positive-EV names
4. Hybrid: production weight * EV multiplier (bounded)
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional

from .data_contracts import EventEV, PositionAction, PositionRecommendation

logger = logging.getLogger(__name__)

# Default constraints
_DEFAULT_MAX_WEIGHT_PCT = 5.0
_DEFAULT_MIN_WEIGHT_PCT = 0.5
_DEFAULT_MAX_POSITIONS = 30
_DEFAULT_MAX_INDICATION_WEIGHT = 25.0
_DEFAULT_MAX_EVENT_CLUSTER = 5  # max names with catalysts in same week
_DEFAULT_EV_MULTIPLIER_BOUNDS = (0.7, 1.3)  # for hybrid mode


class PortfolioTranslator:
    """Converts event EV scores into position recommendations.

    Usage:
        translator = PortfolioTranslator()
        recommendations = translator.translate(
            event_evs, current_weights, mode="hybrid"
        )
    """

    def __init__(
        self,
        max_weight_pct: float = _DEFAULT_MAX_WEIGHT_PCT,
        min_weight_pct: float = _DEFAULT_MIN_WEIGHT_PCT,
        max_positions: int = _DEFAULT_MAX_POSITIONS,
        max_indication_weight: float = _DEFAULT_MAX_INDICATION_WEIGHT,
        max_event_cluster: int = _DEFAULT_MAX_EVENT_CLUSTER,
        ev_multiplier_bounds: tuple[float, float] = _DEFAULT_EV_MULTIPLIER_BOUNDS,
    ) -> None:
        self.max_weight_pct = max_weight_pct
        self.min_weight_pct = min_weight_pct
        self.max_positions = max_positions
        self.max_indication_weight = max_indication_weight
        self.max_event_cluster = max_event_cluster
        self.ev_multiplier_bounds = ev_multiplier_bounds

    def translate(
        self,
        event_evs: List[EventEV],
        current_weights: Optional[Dict[str, float]] = None,
        mode: str = "hybrid",
    ) -> List[PositionRecommendation]:
        """Translate event EVs into position recommendations.

        Args:
            event_evs: list of EventEV objects (all layers computed)
            current_weights: {ticker: current_weight_pct} from production
            mode: sizing mode — "ev_proportional", "kelly", "ew_filter", "hybrid"

        Returns:
            List of PositionRecommendation, sorted by EV rank
        """
        current_weights = current_weights or {}

        # Step 1: Filter to actionable events
        actionable = [ev for ev in event_evs if ev.actionable]
        if not actionable:
            return []

        # Step 2: Rank by downside-adjusted EV
        actionable.sort(key=lambda ev: ev.payoff.downside_adjusted_ev, reverse=True)

        # Step 3: Compute raw weights based on mode
        if mode == "ev_proportional":
            raw_weights = self._ev_proportional(actionable)
        elif mode == "kelly":
            raw_weights = self._kelly_sizing(actionable)
        elif mode == "ew_filter":
            raw_weights = self._ew_filter(actionable)
        elif mode == "hybrid":
            raw_weights = self._hybrid(actionable, current_weights)
        else:
            raise ValueError(f"Unknown sizing mode: {mode}")

        # Step 4: Apply risk constraints
        constrained = self._apply_constraints(actionable, raw_weights)

        # Step 5: Build recommendations
        recommendations = []
        for rank, ev in enumerate(actionable, 1):
            ticker = ev.node.ticker
            target = constrained.get(ev.node.node_id, 0.0)
            current = current_weights.get(ticker, 0.0)
            risk_flags = self._check_risk_flags(ev)

            # Determine action
            if target <= 0:
                action = PositionAction.EXIT.value if current > 0 else PositionAction.NO_ACTION.value
            elif target > current * 1.1:
                action = PositionAction.ADD.value
            elif target < current * 0.9:
                action = PositionAction.TRIM.value
            else:
                action = PositionAction.HOLD.value

            recommendations.append(
                PositionRecommendation(
                    ticker=ticker,
                    node_id=ev.node.node_id,
                    action=action,
                    target_weight_pct=round(target, 4),
                    max_weight_pct=self.max_weight_pct,
                    ev_rank=rank,
                    risk_flags=risk_flags,
                    reasoning={
                        "scenario_ev": round(ev.payoff.scenario_ev, 4),
                        "downside_adj_ev": round(ev.payoff.downside_adjusted_ev, 4),
                        "mispricing": round(ev.expectation.mispricing_score, 4),
                        "p_hit": round(ev.outcome.p_hit, 4),
                        "mode": mode,
                    },
                    model_version="portfolio_v0.1",
                )
            )

        return recommendations

    def _ev_proportional(self, evs: List[EventEV]) -> Dict[str, float]:
        """Weight proportional to max(0, downside_adjusted_ev)."""
        positive = [
            (ev.node.node_id, ev.payoff.downside_adjusted_ev) for ev in evs if ev.payoff.downside_adjusted_ev > 0
        ]
        if not positive:
            return {}

        total_ev = sum(v for _, v in positive)
        budget = 100.0  # total portfolio percentage
        weights = {}
        for node_id, ev_val in positive:
            weights[node_id] = (ev_val / total_ev) * budget if total_ev > 0 else 0
        return weights

    def _kelly_sizing(self, evs: List[EventEV]) -> Dict[str, float]:
        """Half-Kelly sizing from payoff engine's kelly_fraction."""
        weights = {}
        for ev in evs:
            kelly = ev.payoff.kelly_fraction
            if kelly > 0:
                # Convert fraction to percentage, cap at max_weight
                weights[ev.node.node_id] = min(kelly * 100, self.max_weight_pct)
        return weights

    def _ew_filter(self, evs: List[EventEV]) -> Dict[str, float]:
        """Equal-weight among positive-EV names (capped at max_positions)."""
        positive = [ev for ev in evs if ev.payoff.downside_adjusted_ev > 0]
        n = min(len(positive), self.max_positions)
        if n == 0:
            return {}

        weight_each = 100.0 / n
        weights = {}
        for ev in positive[:n]:
            weights[ev.node.node_id] = weight_each
        return weights

    def _hybrid(self, evs: List[EventEV], current_weights: Dict[str, float]) -> Dict[str, float]:
        """Production weight * EV multiplier (bounded ±30%).

        If no current weight, use EV-proportional for new positions.
        """
        lo, hi = self.ev_multiplier_bounds
        weights = {}

        # Normalize EV to multiplier range
        ev_values = [ev.payoff.downside_adjusted_ev for ev in evs]
        if not ev_values:
            return {}
        max_ev = max(abs(v) for v in ev_values) or 1.0

        for ev in evs:
            ticker = ev.node.ticker
            current = current_weights.get(ticker, 0.0)

            # EV multiplier: map downside_adjusted_ev to [lo, hi]
            normalized_ev = ev.payoff.downside_adjusted_ev / max_ev  # [-1, 1]
            multiplier = 1.0 + normalized_ev * (hi - 1.0)
            multiplier = max(lo, min(multiplier, hi))

            if current > 0:
                # Adjust existing position
                weights[ev.node.node_id] = current * multiplier
            else:
                # New position: scale from base weight
                base = 100.0 / self.max_positions
                weights[ev.node.node_id] = base * max(multiplier, 1.0)

        return weights

    def _apply_constraints(
        self,
        evs: List[EventEV],
        raw_weights: Dict[str, float],
    ) -> Dict[str, float]:
        """Apply risk constraints to raw weights."""
        constrained = dict(raw_weights)

        # Cap individual weights
        for node_id in constrained:
            constrained[node_id] = min(constrained[node_id], self.max_weight_pct)
            if constrained[node_id] < self.min_weight_pct:
                constrained[node_id] = 0.0

        # Cap number of positions
        if len([v for v in constrained.values() if v > 0]) > self.max_positions:
            sorted_items = sorted(constrained.items(), key=lambda x: x[1], reverse=True)
            for i, (node_id, _) in enumerate(sorted_items):
                if i >= self.max_positions:
                    constrained[node_id] = 0.0

        # Cap indication concentration
        indication_weights: Dict[str, float] = {}
        node_indications: Dict[str, str] = {}
        for ev in evs:
            ind = ev.node.indication
            node_indications[ev.node.node_id] = ind
            w = constrained.get(ev.node.node_id, 0.0)
            indication_weights[ind] = indication_weights.get(ind, 0.0) + w

        for ind, total_w in indication_weights.items():
            if total_w > self.max_indication_weight:
                scale = self.max_indication_weight / total_w
                for node_id, node_ind in node_indications.items():
                    if node_ind == ind and node_id in constrained:
                        constrained[node_id] *= scale

        # Event clustering: cap names with catalysts in same week
        week_clusters: Dict[str, List[str]] = {}
        for ev in evs:
            if ev.node.expected_date:
                try:
                    d = date.fromisoformat(ev.node.expected_date)
                    week_key = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
                    week_clusters.setdefault(week_key, []).append(ev.node.node_id)
                except (ValueError, TypeError):
                    pass

        for week, node_ids in week_clusters.items():
            if len(node_ids) > self.max_event_cluster:
                # Keep top EV, reduce rest
                sorted_ids = sorted(
                    node_ids,
                    key=lambda nid: constrained.get(nid, 0),
                    reverse=True,
                )
                for nid in sorted_ids[self.max_event_cluster :]:
                    constrained[nid] *= 0.5

        return constrained

    def _check_risk_flags(self, ev: EventEV) -> List[str]:
        """Check for risk conditions that should be flagged."""
        flags = []

        # Low analog confidence
        if ev.payoff.analog_confidence == "insufficient":
            flags.append("LOW_ANALOG_COUNT")

        # High downside
        if ev.payoff.downside_miss < -50:
            flags.append("HIGH_DOWNSIDE_RISK")

        # Low model confidence
        if ev.outcome.confidence < 0.3:
            flags.append("LOW_OUTCOME_CONFIDENCE")

        # Near-term event (high urgency)
        days = ev.node.days_to_event(date.fromisoformat(ev.timing.as_of_date))
        if days is not None and days <= 7:
            flags.append("IMMINENT_CATALYST")

        # High slip probability
        if ev.timing.prob_slip > 0.5:
            flags.append("HIGH_SLIP_RISK")

        # Market already pricing in (small mispricing)
        if abs(ev.expectation.mispricing_score) < 0.05:
            flags.append("FULLY_PRICED")

        return flags
