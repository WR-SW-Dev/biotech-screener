"""Layer 4 — Market Expectation / Crowd Belief Model.

Estimates what the market already believes about a catalyst outcome
using cross-sectional positioning and behavior proxies.

This layer does NOT predict outcomes. It estimates what is already priced,
so we can identify mispricing when compared to the outcome model.

Inputs (all PIT-safe):
- coinvest_score_z: institutional co-investment (dominant signal)
- inst_delta_z: institutional accumulation delta
- insider_net_buy_value_90d: Form 4 context
- alpha_60d: pre-event price drift
- de_rsi_14d: momentum/sentiment
- short_interest_pct: bearish positioning
- opt_event_premium: options-implied premium (diagnostic)
- priced_move_pct: options-implied move (diagnostic)
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Dict, List, Optional

from .data_contracts import BeliefDirection, CatalystNode, CrowdBelief

logger = logging.getLogger(__name__)

# Feature weights for belief score computation
# These define how much each signal contributes to inferred market belief.
# Positive weight = feature being high implies market is bullish.
_DEFAULT_FEATURE_WEIGHTS: Dict[str, float] = {
    "coinvest_score_z": 0.30,  # dominant institutional signal
    "inst_delta_z": 0.20,  # institutional accumulation
    "insider_net_buy_z": 0.10,  # Form 4 insider context
    "alpha_60d": 0.15,  # pre-event drift
    "rsi_14d": 0.10,  # momentum
    "short_interest_inv": 0.05,  # inverted: low short = bullish
    "opt_event_premium": 0.05,  # options implied premium
    "priced_move_pct": 0.05,  # options implied move
}

# Sigmoid calibration parameters
# Maps raw belief score to implied P(HIT)
_BELIEF_SIGMOID_CENTER = 0.5
_BELIEF_SIGMOID_SCALE = 2.5


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ez = math.exp(x)
    return ez / (1.0 + ez)


class ExpectationModel:
    """Estimates market crowd belief about catalyst outcomes.

    Usage:
        model = ExpectationModel()
        belief = model.estimate(node, as_of, market_features)
    """

    def __init__(
        self,
        feature_weights: Optional[Dict[str, float]] = None,
        sigmoid_center: float = _BELIEF_SIGMOID_CENTER,
        sigmoid_scale: float = _BELIEF_SIGMOID_SCALE,
    ) -> None:
        self.feature_weights = feature_weights or dict(_DEFAULT_FEATURE_WEIGHTS)
        self.sigmoid_center = sigmoid_center
        self.sigmoid_scale = sigmoid_scale

    def estimate(
        self,
        node: CatalystNode,
        as_of: date,
        market_features: Dict[str, Any],
        model_p_hit: Optional[float] = None,
    ) -> CrowdBelief:
        """Estimate market belief for a catalyst.

        Args:
            node: CatalystNode to evaluate
            as_of: evaluation date
            market_features: dict with feature values (raw, not z-scored).
                Expected keys match _DEFAULT_FEATURE_WEIGHTS.
            model_p_hit: outcome model's P(HIT) for mispricing computation

        Returns:
            CrowdBelief with implied market probability and mispricing score
        """
        features_used: Dict[str, Any] = {}

        # Step 1: Normalize features to [0, 1] percentile ranks
        normalized = self._normalize_features(market_features)
        features_used["normalized"] = {k: round(v, 4) for k, v in normalized.items()}

        # Step 2: Compute weighted belief score
        belief_score = 0.0
        total_weight = 0.0
        for feat, weight in self.feature_weights.items():
            if feat in normalized:
                belief_score += weight * normalized[feat]
                total_weight += weight

        if total_weight > 0:
            belief_score /= total_weight
        else:
            belief_score = 0.5  # uninformed

        features_used["raw_belief_score"] = round(belief_score, 4)
        features_used["feature_coverage"] = round(total_weight, 4)

        # Step 3: Convert to implied P(HIT) via sigmoid
        logit = (belief_score - self.sigmoid_center) * self.sigmoid_scale
        implied_p_hit = _sigmoid(logit)

        # Step 4: Determine belief direction and intensity
        direction = self._classify_direction(belief_score)
        intensity = abs(belief_score - 0.5) * 2.0  # [0, 1]

        # Step 5: Options-implied move (pass-through diagnostic)
        priced_move = market_features.get("priced_move_pct")

        # Step 6: Mispricing score
        if model_p_hit is not None:
            mispricing = model_p_hit - implied_p_hit
        else:
            mispricing = 0.0

        return CrowdBelief(
            node_id=node.node_id,
            as_of_date=str(as_of),
            implied_p_hit=round(implied_p_hit, 4),
            belief_direction=direction,
            belief_intensity=round(min(intensity, 1.0), 4),
            priced_move_pct=round(priced_move, 4) if priced_move is not None else None,
            mispricing_score=round(mispricing, 4),
            features_used=features_used,
            model_version="expectation_proxy_v0.1",
        )

    def _normalize_features(self, raw: Dict[str, Any]) -> Dict[str, float]:
        """Normalize raw features to [0, 1] using heuristic ranges.

        In production, this would use cross-sectional percentile ranks.
        For the research scaffold, we use reasonable heuristic bounds.
        """
        normalized = {}

        # coinvest_score_z: typically [-2, 3], center at 0
        if "coinvest_score_z" in raw and raw["coinvest_score_z"] is not None:
            v = float(raw["coinvest_score_z"])
            normalized["coinvest_score_z"] = _clamp((v + 2) / 5, 0, 1)

        # inst_delta_z: typically [-2, 3]
        if "inst_delta_z" in raw and raw["inst_delta_z"] is not None:
            v = float(raw["inst_delta_z"])
            normalized["inst_delta_z"] = _clamp((v + 2) / 5, 0, 1)

        # insider_net_buy_value_90d: convert to z-like via log transform
        if "insider_net_buy_value_90d" in raw and raw["insider_net_buy_value_90d"] is not None:
            v = float(raw["insider_net_buy_value_90d"])
            if v > 0:
                normalized["insider_net_buy_z"] = _clamp(0.5 + math.log1p(v / 100000) * 0.2, 0, 1)
            elif v < 0:
                normalized["insider_net_buy_z"] = _clamp(0.5 - math.log1p(abs(v) / 100000) * 0.2, 0, 1)
            else:
                normalized["insider_net_buy_z"] = 0.5

        # alpha_60d: typically [-0.5, 0.5]
        if "alpha_60d" in raw and raw["alpha_60d"] is not None:
            v = float(raw["alpha_60d"])
            normalized["alpha_60d"] = _clamp((v + 0.5) / 1.0, 0, 1)

        # rsi_14d: [0, 100], normalize to [0, 1]
        if "de_rsi_14d" in raw and raw["de_rsi_14d"] is not None:
            v = float(raw["de_rsi_14d"])
            normalized["rsi_14d"] = _clamp(v / 100, 0, 1)

        # short_interest_pct: [0, ~50], invert (low short = bullish)
        if "short_interest_pct" in raw and raw["short_interest_pct"] is not None:
            v = float(raw["short_interest_pct"])
            normalized["short_interest_inv"] = _clamp(1.0 - v / 30, 0, 1)

        # opt_event_premium: typically [0, 2+]
        if "opt_event_premium" in raw and raw["opt_event_premium"] is not None:
            v = float(raw["opt_event_premium"])
            normalized["opt_event_premium"] = _clamp(v / 2.0, 0, 1)

        # priced_move_pct: pass-through (not part of belief score, used as diagnostic)
        if "priced_move_pct" in raw and raw["priced_move_pct"] is not None:
            normalized["priced_move_pct"] = float(raw["priced_move_pct"])

        return normalized

    def _classify_direction(self, belief_score: float) -> str:
        """Classify belief direction from raw score."""
        if belief_score >= 0.65:
            return BeliefDirection.BULLISH.value
        if belief_score <= 0.35:
            return BeliefDirection.BEARISH.value
        if 0.45 <= belief_score <= 0.55:
            return BeliefDirection.NEUTRAL.value
        return BeliefDirection.UNCERTAIN.value

    # =========================================================================
    # Cross-sectional normalization (production path)
    # =========================================================================

    def estimate_batch(
        self,
        nodes: List[CatalystNode],
        as_of: date,
        market_features_by_ticker: Dict[str, Dict[str, Any]],
        model_p_hits: Optional[Dict[str, float]] = None,
    ) -> List[CrowdBelief]:
        """Estimate beliefs for a batch, using cross-sectional percentile ranks.

        This is more accurate than single-name estimation because it
        normalizes features within the current cross-section.
        """
        model_p_hits = model_p_hits or {}

        # Collect raw feature values for cross-sectional ranking
        feature_values: Dict[str, List[tuple[str, float]]] = {}
        for node in nodes:
            feats = market_features_by_ticker.get(node.ticker, {})
            for key in self.feature_weights:
                raw_key = self._raw_key_for(key)
                if raw_key in feats and feats[raw_key] is not None:
                    feature_values.setdefault(key, []).append((node.ticker, float(feats[raw_key])))

        # Compute cross-sectional percentile ranks
        pct_ranks: Dict[str, Dict[str, float]] = {}
        for feat, pairs in feature_values.items():
            sorted_pairs = sorted(pairs, key=lambda x: x[1])
            n = len(sorted_pairs)
            for rank, (ticker, _) in enumerate(sorted_pairs):
                pct_ranks.setdefault(ticker, {})[feat] = rank / max(n - 1, 1)

        # Estimate for each node using percentile-ranked features
        results = []
        for node in nodes:
            ranks = pct_ranks.get(node.ticker, {})
            raw_feats = market_features_by_ticker.get(node.ticker, {})

            # Override normalized features with cross-sectional ranks
            belief = self._estimate_from_ranks(
                node,
                as_of,
                ranks,
                raw_feats,
                model_p_hits.get(node.node_id),
            )
            results.append(belief)

        return results

    def _estimate_from_ranks(
        self,
        node: CatalystNode,
        as_of: date,
        pct_ranks: Dict[str, float],
        raw_feats: Dict[str, Any],
        model_p_hit: Optional[float],
    ) -> CrowdBelief:
        """Estimate using pre-computed percentile ranks."""
        features_used: Dict[str, Any] = {"percentile_ranks": {k: round(v, 4) for k, v in pct_ranks.items()}}

        belief_score = 0.0
        total_weight = 0.0
        for feat, weight in self.feature_weights.items():
            if feat in pct_ranks:
                belief_score += weight * pct_ranks[feat]
                total_weight += weight

        if total_weight > 0:
            belief_score /= total_weight
        else:
            belief_score = 0.5

        logit = (belief_score - self.sigmoid_center) * self.sigmoid_scale
        implied_p_hit = _sigmoid(logit)
        direction = self._classify_direction(belief_score)
        intensity = abs(belief_score - 0.5) * 2.0
        priced_move = raw_feats.get("priced_move_pct")
        mispricing = (model_p_hit - implied_p_hit) if model_p_hit is not None else 0.0

        return CrowdBelief(
            node_id=node.node_id,
            as_of_date=str(as_of),
            implied_p_hit=round(implied_p_hit, 4),
            belief_direction=direction,
            belief_intensity=round(min(intensity, 1.0), 4),
            priced_move_pct=round(priced_move, 4) if priced_move is not None else None,
            mispricing_score=round(mispricing, 4),
            features_used=features_used,
            model_version="expectation_xsectional_v0.1",
        )

    def _raw_key_for(self, normalized_key: str) -> str:
        """Map normalized feature key back to raw input key."""
        mapping = {
            "coinvest_score_z": "coinvest_score_z",
            "inst_delta_z": "inst_delta_z",
            "insider_net_buy_z": "insider_net_buy_value_90d",
            "alpha_60d": "alpha_60d",
            "rsi_14d": "de_rsi_14d",
            "short_interest_inv": "short_interest_pct",
            "opt_event_premium": "opt_event_premium",
            "priced_move_pct": "priced_move_pct",
        }
        return mapping.get(normalized_key, normalized_key)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))
