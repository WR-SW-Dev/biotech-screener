"""Event EV Calculator — Orchestrator for all six layers.

Ties the catalyst graph, timing hazard, outcome model, expectation model,
payoff engine, and portfolio translator into a single pipeline.

Usage:
    from event_ev.ev_calculator import EventEVCalculator

    calc = EventEVCalculator(as_of_date=date(2026, 4, 4))
    results = calc.run(
        catalyst_nodes=nodes,
        market_features=features_by_ticker,
        context_features=context_by_ticker,
        current_weights=weights,
    )

    for ev in results:
        print(f"{ev.node.ticker}: EV={ev.scenario_ev:.2f}%, "
              f"mispricing={ev.mispricing_score:.3f}")
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .branch_sensitivity import compute_branch_sensitivity, compute_breakeven_straddle
from .catalyst_graph import CatalystGraph
from .data_contracts import CatalystNode, EventEV, PositionRecommendation
from .expectation_model import ExpectationModel
from .outcome_model import OutcomeModel
from .payoff_engine import PayoffEngine
from .portfolio_translator import PortfolioTranslator
from .surface_diagnostics import classify_term_structure, compute_belief_intensity_modifier
from .timing_hazard import TimingHazardModel

logger = logging.getLogger(__name__)


class EventEVCalculator:
    """Orchestrates all six layers of the Event EV Engine.

    Runs the full pipeline:
        1. Catalyst graph → actionable event cohort
        2. Timing hazard → timing estimates
        3. Outcome model → branch probabilities
        4. Expectation model → crowd beliefs
        5. Payoff engine → scenario EVs
        6. Portfolio translator → position recommendations
    """

    def __init__(
        self,
        as_of_date: date,
        timing_model: Optional[TimingHazardModel] = None,
        outcome_model: Optional[OutcomeModel] = None,
        expectation_model: Optional[ExpectationModel] = None,
        payoff_engine: Optional[PayoffEngine] = None,
        portfolio_translator: Optional[PortfolioTranslator] = None,
        max_days: int = 180,
        min_days: int = 0,
    ) -> None:
        self.as_of_date = as_of_date
        self.timing = timing_model or TimingHazardModel()
        self.outcome = outcome_model or OutcomeModel()
        self.expectation = expectation_model or ExpectationModel()
        self.payoff = payoff_engine or PayoffEngine()
        self.portfolio = portfolio_translator or PortfolioTranslator()
        self.max_days = max_days
        self.min_days = min_days

    def run(
        self,
        catalyst_nodes: List[CatalystNode],
        market_features: Optional[Dict[str, Dict[str, Any]]] = None,
        context_features: Optional[Dict[str, Dict[str, Any]]] = None,
        current_weights: Optional[Dict[str, float]] = None,
        sizing_mode: str = "hybrid",
    ) -> List[EventEV]:
        """Run the full Event EV pipeline.

        Args:
            catalyst_nodes: list of CatalystNode objects
            market_features: {ticker: {feature: value}} for expectation model
            context_features: {ticker: {feature: value}} for outcome model
            current_weights: {ticker: weight_pct} for portfolio translation
            sizing_mode: portfolio sizing mode

        Returns:
            List of EventEV objects, sorted by downside-adjusted EV
        """
        market_features = market_features or {}
        context_features = context_features or {}

        # Filter to actionable cohort
        cohort = self._filter_cohort(catalyst_nodes)
        if not cohort:
            logger.info("No actionable catalysts in [%d, %d] day window", self.min_days, self.max_days)
            return []

        logger.info(
            "Processing %d actionable catalysts (as_of=%s)",
            len(cohort),
            self.as_of_date,
        )

        # First pass: timing, outcome, payoff (per-name)
        partials = []
        failed_nodes = []
        model_p_hits = {}
        for node in cohort:
            try:
                timing_est = self.timing.estimate(node, self.as_of_date)
                outcome_est = self.outcome.estimate(
                    node,
                    self.as_of_date,
                    context_features.get(node.ticker, {}),
                )
                payoff_est = self.payoff.estimate(
                    node,
                    outcome_est,
                    self.as_of_date,
                    context_features.get(node.ticker, {}),
                )
                partials.append((node, timing_est, outcome_est, payoff_est))
                model_p_hits[node.node_id] = outcome_est.p_hit
            except Exception:
                logger.exception("Failed to process node %s (%s)", node.node_id, node.ticker)
                failed_nodes.append(node.node_id)

        if failed_nodes:
            logger.warning(
                "EV calculation: %d/%d nodes failed: %s",
                len(failed_nodes),
                len(cohort),
                failed_nodes[:10],
            )

        # Second pass: expectation (cross-sectional batch)
        beliefs = self.expectation.estimate_batch(
            [p[0] for p in partials],
            self.as_of_date,
            market_features,
            model_p_hits=model_p_hits,
        )
        belief_by_node = {b.node_id: b for b in beliefs}

        # Assemble EventEV objects
        event_evs = []
        for node, timing_est, outcome_est, payoff_est in partials:
            belief = belief_by_node.get(node.node_id)
            if belief is None:
                continue
            try:
                ev = self._assemble_ev(
                    node,
                    timing_est,
                    outcome_est,
                    belief,
                    payoff_est,
                    market_features.get(node.ticker, {}),
                    context_features.get(node.ticker, {}),
                )
                event_evs.append(ev)
            except Exception:
                logger.exception("Failed to assemble EV for %s (%s)", node.node_id, node.ticker)
                failed_nodes.append(node.node_id)

        # Sort by downside-adjusted EV
        event_evs.sort(key=lambda ev: ev.payoff.downside_adjusted_ev, reverse=True)

        # Run portfolio translator
        if current_weights is not None:
            recommendations = self.portfolio.translate(event_evs, current_weights, mode=sizing_mode)
            # Attach recommendations to EventEV objects
            rec_by_node = {r.node_id: r for r in recommendations}
            for ev in event_evs:
                ev.position = rec_by_node.get(ev.node.node_id)

        # Assign EV ranks
        for rank, ev in enumerate(event_evs, 1):
            if ev.position and ev.position.ev_rank != rank:
                # Reconstruct with correct rank (frozen dataclass workaround)
                ev.position = PositionRecommendation(
                    ticker=ev.position.ticker,
                    node_id=ev.position.node_id,
                    action=ev.position.action,
                    target_weight_pct=ev.position.target_weight_pct,
                    max_weight_pct=ev.position.max_weight_pct,
                    ev_rank=rank,
                    risk_flags=ev.position.risk_flags,
                    reasoning=ev.position.reasoning,
                    model_version=ev.position.model_version,
                )

        return event_evs

    def _filter_cohort(self, nodes: List[CatalystNode]) -> List[CatalystNode]:
        """Filter to actionable cohort within time window."""
        result = []
        for node in nodes:
            if not node.is_visible(self.as_of_date):
                continue
            if node.is_resolved():
                continue
            days = node.days_to_event(self.as_of_date)
            if days is None:
                continue
            if self.min_days <= days <= self.max_days:
                result.append(node)
        return result

    def _process_single(
        self,
        node: CatalystNode,
        market_feats: Dict[str, Any],
        context_feats: Dict[str, Any],
    ) -> EventEV:
        """Process a single catalyst through all layers (legacy per-name path).

        Retained for backward compatibility. The main run() method now uses
        the batch path (timing/outcome/payoff per-name, expectation cross-sectional).
        """
        timing_est = self.timing.estimate(node, self.as_of_date)
        outcome_est = self.outcome.estimate(node, self.as_of_date, context_feats)
        expectation_est = self.expectation.estimate(node, self.as_of_date, market_feats, model_p_hit=outcome_est.p_hit)
        payoff_est = self.payoff.estimate(node, outcome_est, self.as_of_date, context_feats)
        return self._assemble_ev(
            node, timing_est, outcome_est, expectation_est, payoff_est, market_feats, context_feats
        )

    def _assemble_ev(
        self,
        node: CatalystNode,
        timing_est,
        outcome_est,
        expectation_est,
        payoff_est,
        market_feats: Dict[str, Any],
        context_feats: Dict[str, Any],
    ) -> EventEV:
        """Assemble EventEV from pre-computed layer estimates + branch sensitivity."""
        # Spec 059: Branch sensitivity overlay (diagnostic, liquid-only)
        branch_sens = None
        try:
            front_iv = context_feats.get("opt_front_iv") or market_feats.get("opt_front_iv")
            back_iv = context_feats.get("opt_back_iv") or market_feats.get("opt_back_iv")
            atm_iv = context_feats.get("opt_atm_iv") or market_feats.get("opt_atm_iv")
            liquidity = context_feats.get("opt_liquidity_state") or market_feats.get("opt_liquidity_state", "absent")
            underlying = context_feats.get("underlying_price") or market_feats.get("underlying_price")
            catalyst_days_val = node.days_to_event(self.as_of_date)

            if atm_iv and underlying and catalyst_days_val and catalyst_days_val > 0:
                surface = {
                    "opt_atm_iv": atm_iv,
                    "opt_front_iv": front_iv,
                    "opt_back_iv": back_iv,
                    "underlying_price": underlying,
                    "catalyst_days": catalyst_days_val,
                    "opt_liquidity_state": liquidity,
                    "event_family": node.event_family,
                }
                scenario_moves = {
                    "upside_hit": payoff_est.upside_hit,
                    "downside_miss": payoff_est.downside_miss,
                    "move_mixed": payoff_est.move_mixed,
                }
                branch_sens = compute_branch_sensitivity(surface, scenario_moves)

                # Add breakeven straddle info
                if branch_sens is not None:
                    breakeven = compute_breakeven_straddle(
                        float(underlying),
                        float(atm_iv),
                        catalyst_days_val,
                        event_family=node.event_family,
                    )
                    if breakeven:
                        branch_sens["breakeven"] = breakeven

                    # Add term structure shape + belief modifier
                    if front_iv and back_iv:
                        shape = classify_term_structure(float(front_iv), float(back_iv), catalyst_days_val)
                        if shape:
                            branch_sens["term_shape"] = shape
                            branch_sens["belief_modifier"] = compute_belief_intensity_modifier(
                                shape,
                                0.0,  # epr_z=0 for single-name (no cross-section here)
                            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            logger.debug("Branch sensitivity failed for %s — skipping", node.ticker)

        return EventEV(
            node=node,
            timing=timing_est,
            outcome=outcome_est,
            expectation=expectation_est,
            payoff=payoff_est,
            branch_sensitivity=branch_sens,
        )

    # =========================================================================
    # Convenience: run from graph
    # =========================================================================

    def run_from_graph(
        self,
        graph: CatalystGraph,
        market_features: Optional[Dict[str, Dict[str, Any]]] = None,
        context_features: Optional[Dict[str, Dict[str, Any]]] = None,
        current_weights: Optional[Dict[str, float]] = None,
        sizing_mode: str = "hybrid",
        families: Optional[List[str]] = None,
    ) -> List[EventEV]:
        """Run the pipeline from a CatalystGraph.

        Convenience method that extracts the event cohort from the graph.
        """
        nodes = graph.get_event_cohort(
            self.as_of_date,
            max_days=self.max_days,
            min_days=self.min_days,
            families=families,
        )
        return self.run(
            catalyst_nodes=nodes,
            market_features=market_features,
            context_features=context_features,
            current_weights=current_weights,
            sizing_mode=sizing_mode,
        )

    # =========================================================================
    # Serialization
    # =========================================================================

    def results_to_json(
        self,
        results: List[EventEV],
        path: Optional[Path] = None,
    ) -> str:
        """Serialize results to JSON. Optionally write to file."""
        output = {
            "as_of_date": str(self.as_of_date),
            "n_events": len(results),
            "n_actionable": sum(1 for ev in results if ev.actionable),
            "events": [ev.to_dict() for ev in results],
        }
        json_str = json.dumps(output, indent=2, default=str)

        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json_str)
            logger.info("Results written to %s", path)

        return json_str

    def summary_table(self, results: List[EventEV]) -> List[Dict[str, Any]]:
        """Produce a compact summary table for display/analysis."""
        rows = []
        for rank, ev in enumerate(results, 1):
            days = ev.node.days_to_event(self.as_of_date)
            row = {
                "rank": rank,
                "ticker": ev.node.ticker,
                "event_type": ev.node.event_type,
                "days_to_event": days,
                "p_hit": round(ev.outcome.p_hit, 3),
                "p_miss": round(ev.outcome.p_miss, 3),
                "implied_p_hit": round(ev.expectation.implied_p_hit, 3),
                "mispricing": round(ev.mispricing_score, 3),
                "upside_hit": round(ev.payoff.upside_hit, 1),
                "downside_miss": round(ev.payoff.downside_miss, 1),
                "scenario_ev": round(ev.scenario_ev, 2),
                "ds_adj_ev": round(ev.payoff.downside_adjusted_ev, 2),
                "timing_on_time": round(ev.timing.prob_on_time, 3),
                "analog_conf": ev.payoff.analog_confidence,
                "actionable": ev.actionable,
            }
            if ev.position:
                row["action"] = ev.position.action
                row["target_wt"] = round(ev.position.target_weight_pct, 2)
                row["risk_flags"] = ev.position.risk_flags
            rows.append(row)
        return rows
