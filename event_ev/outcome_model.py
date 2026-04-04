"""Layer 3 — Outcome Probability Model.

Bayesian prior-posterior framework for estimating catalyst outcome
branch probabilities (HIT / MISS / MIXED).

Prior: Clinical PoS from Wong et al. + v2 empirical priors,
       keyed by (phase, indication, endpoint_class).

Likelihood updates: endpoint strength, design quality, sponsor quality,
       execution behavior, modality, competitive context.

PIT safety:
- PoS priors are versioned and dated
- Feature scores use only data available at as_of_date
- No future resolution leakage
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Dict, List, Optional

from .data_contracts import CatalystNode, EventFamily, OutcomeProbabilities

logger = logging.getLogger(__name__)

# Wong et al. reference priors (matches common/clinical_pos_prior.py)
WONG_PHASE_PRIORS: Dict[str, float] = {
    "1": 0.066,
    "1_2": 0.150,
    "2": 0.305,
    "2_3": 0.400,
    "3": 0.580,
    "4": 0.650,
    "unknown": 0.250,
}

# Indication difficulty adjustments (multiplicative)
_INDICATION_DIFFICULTY: Dict[str, float] = {
    "oncology": 0.85,  # harder
    "rare_disease": 1.10,  # slightly easier (regulatory tailwinds)
    "rare": 1.10,
    "neurology": 0.80,  # hardest
    "psychiatry": 0.80,
    "cardiovascular": 0.90,
    "infectious_disease": 0.95,
    "immunology": 0.95,
    "ophthalmology": 1.05,
    "dermatology": 1.10,
    "unknown": 1.00,
}

# Modality priors (relative to baseline)
_MODALITY_ADJUSTMENTS: Dict[str, float] = {
    "small_molecule": 1.00,
    "antibody": 1.05,
    "adc": 0.95,
    "gene_therapy": 0.85,
    "cell_therapy": 0.80,
    "mrna": 0.90,
    "antisense": 0.90,
    "protein": 1.00,
    "vaccine": 0.95,
}

# Regulatory event priors (separate from clinical PoS)
_REGULATORY_PRIORS: Dict[str, float] = {
    "PDUFA": 0.85,  # most PDUFAs approve after NDA/BLA
    "FDA_ADCOM": 0.65,  # advisory committee more uncertain
    "FDA_SUBMISSION": 0.90,  # most submissions get accepted
    "FDA_DESIGNATION": 0.75,
    "EMA_OUTCOME": 0.80,
}

# Default MIXED allocation (fraction of total probability)
_DEFAULT_MIXED_FRACTION = 0.12


class OutcomeModel:
    """Bayesian outcome probability model for catalyst events.

    Usage:
        model = OutcomeModel()
        probs = model.estimate(node, as_of, context_features)
    """

    def __init__(
        self,
        pos_priors: Optional[Dict[str, float]] = None,
        mixed_fraction: float = _DEFAULT_MIXED_FRACTION,
        v2_priors: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.pos_priors = pos_priors or dict(WONG_PHASE_PRIORS)
        self.mixed_fraction = mixed_fraction
        self.v2_priors = v2_priors  # loaded from clinical_pos_priors_v2.json

    def estimate(
        self,
        node: CatalystNode,
        as_of: date,
        context: Optional[Dict[str, Any]] = None,
    ) -> OutcomeProbabilities:
        """Estimate outcome branch probabilities for a catalyst.

        Args:
            node: CatalystNode to evaluate
            as_of: evaluation date (PIT anchor)
            context: optional dict with additional features:
                - endpoint_strength_score: float [0, 1]
                - design_quality_score: float [0, 1]
                - execution_momentum: float [-1, 1]
                - competitive_intensity: float [0, 1]
                - sponsor_track_record_n: int (number of prior outcomes)
                - sponsor_track_record_hit_rate: float [0, 1]

        Returns:
            OutcomeProbabilities with calibrated branch probabilities
        """
        context = context or {}
        features_used: Dict[str, Any] = {}

        # Step 1: Get base prior
        p_hit_prior, prior_source = self._get_prior(node)
        features_used["prior_p_hit"] = round(p_hit_prior, 4)
        features_used["prior_source"] = prior_source

        # Step 2: Apply likelihood updates (log-odds space)
        log_odds = math.log(p_hit_prior / max(1.0 - p_hit_prior, 0.001))
        updates: Dict[str, float] = {}

        # Indication difficulty
        ind = node.indication.lower().strip() if node.indication else "unknown"
        ind_mult = _INDICATION_DIFFICULTY.get(ind, 1.0)
        if ind_mult != 1.0:
            update = math.log(ind_mult) * 0.5  # damped
            log_odds += update
            updates["indication"] = round(update, 4)

        # Modality
        if node.modality:
            mod_mult = _MODALITY_ADJUSTMENTS.get(node.modality.lower(), 1.0)
            if mod_mult != 1.0:
                update = math.log(mod_mult) * 0.5
                log_odds += update
                updates["modality"] = round(update, 4)

        # Endpoint strength (strong endpoints → higher PoS)
        eps = context.get("endpoint_strength_score")
        if eps is not None:
            # Center at 0.5, scale to ±0.3 log-odds
            update = (eps - 0.5) * 0.6
            log_odds += update
            updates["endpoint_strength"] = round(update, 4)

        # Design quality
        dqs = context.get("design_quality_score")
        if dqs is not None:
            update = (dqs - 0.5) * 0.4
            log_odds += update
            updates["design_quality"] = round(update, 4)

        # Sponsor quality (from node or context)
        sq = node.sponsor_quality
        if sq is not None:
            update = (sq - 0.5) * 0.3
            log_odds += update
            updates["sponsor_quality"] = round(update, 4)

        # Sponsor track record (empirical Bayes)
        sr_n = context.get("sponsor_track_record_n", 0)
        sr_rate = context.get("sponsor_track_record_hit_rate")
        if sr_n >= 3 and sr_rate is not None:
            # Shrink toward prior based on sample size
            shrinkage = min(sr_n / (sr_n + 10), 0.5)  # max 50% weight
            prior_rate = _sigmoid(log_odds)
            blended = prior_rate * (1 - shrinkage) + sr_rate * shrinkage
            log_odds = math.log(blended / max(1 - blended, 0.001))
            updates["sponsor_track_record"] = round(shrinkage, 4)

        # Execution momentum
        em = context.get("execution_momentum")
        if em is not None:
            update = em * 0.15  # small effect
            log_odds += update
            updates["execution_momentum"] = round(update, 4)

        # Competitive intensity (crowded → lower marginal value but same PoS)
        # This affects value more than probability — small adjustment here
        ci = context.get("competitive_intensity")
        if ci is not None and ci > 0.7:
            update = -0.1  # slightly lower in very crowded indications
            log_odds += update
            updates["competitive_intensity"] = round(update, 4)

        features_used["log_odds_updates"] = updates

        # Step 3: Convert back to probability
        p_hit_posterior = _sigmoid(log_odds)

        # Step 4: Allocate MIXED
        p_mixed = self._allocate_mixed(node, context)

        # Step 5: Normalize to sum to 1.0
        p_hit = p_hit_posterior * (1.0 - p_mixed)
        p_miss = (1.0 - p_hit_posterior) * (1.0 - p_mixed)

        # Confidence based on prior quality and feature coverage
        confidence = self._compute_confidence(node, context, prior_source)

        return OutcomeProbabilities(
            node_id=node.node_id,
            as_of_date=str(as_of),
            p_hit=round(p_hit, 4),
            p_miss=round(p_miss, 4),
            p_mixed=round(p_mixed, 4),
            confidence=round(confidence, 4),
            prior_source=prior_source,
            features_used=features_used,
            model_version="outcome_bayesian_v0.1",
        )

    def _get_prior(self, node: CatalystNode) -> tuple[float, str]:
        """Get the base prior P(HIT) for this catalyst type."""
        # Regulatory events use separate priors
        if node.event_family == EventFamily.REGULATORY.value:
            reg_prior = _REGULATORY_PRIORS.get(node.event_type)
            if reg_prior is not None:
                return reg_prior, f"regulatory_{node.event_type}"

        # Clinical events: use phase-based PoS
        phase = node.phase

        # Try v2 empirical first (if available and sufficient N)
        if self.v2_priors:
            v2_rate = self._lookup_v2_prior(phase, node.indication)
            if v2_rate is not None:
                return v2_rate, "v2_empirical"

        # Fall back to Wong et al.
        prior = self.pos_priors.get(phase, self.pos_priors.get("unknown", 0.25))
        return prior, "wong_et_al"

    def _lookup_v2_prior(self, phase: str, indication: str) -> Optional[float]:
        """Look up v2 empirical prior. Returns None if insufficient data."""
        if not self.v2_priors:
            return None

        priors = self.v2_priors.get("priors", {})

        # Try (phase, indication) key first
        key = f"{phase}|{indication.lower()}"
        entry = priors.get(key)
        if entry and entry.get("n", 0) >= 10:
            return entry.get("hit_rate")

        # Fall back to phase-only key
        key = f"{phase}|all"
        entry = priors.get(key)
        if entry and entry.get("n", 0) >= 10:
            return entry.get("hit_rate")

        return None

    def _allocate_mixed(self, node: CatalystNode, context: Dict[str, Any]) -> float:
        """Determine P(MIXED) allocation.

        MIXED outcomes are more likely with:
        - Complex endpoints (multiple co-primaries)
        - Early-stage studies (exploratory)
        - Regulatory submissions with conditions
        """
        base = self.mixed_fraction

        # Phase adjustment: early phases have more mixed results
        if node.phase in ("1", "1_2"):
            base *= 1.5
        elif node.phase == "3":
            base *= 0.8

        # Regulatory events: lower mixed (binary decisions)
        if node.event_family == EventFamily.REGULATORY.value:
            if node.event_type == "PDUFA":
                base *= 0.5  # PDUFA is mostly binary
            elif node.event_type == "FDA_ADCOM":
                base *= 0.7  # AdCom can be split vote

        # Endpoint complexity (if available)
        eps = context.get("endpoint_strength_score")
        if eps is not None and eps < 0.3:
            base *= 1.3  # weak endpoints → more ambiguity

        return min(max(base, 0.02), 0.30)  # bound [2%, 30%]

    def _compute_confidence(
        self,
        node: CatalystNode,
        context: Dict[str, Any],
        prior_source: str,
    ) -> float:
        """Model confidence in probability estimates."""
        confidence = 0.5  # base

        # v2 empirical priors are more reliable
        if prior_source == "v2_empirical":
            confidence += 0.15

        # More context features → higher confidence
        feature_count = sum(
            1
            for k in (
                "endpoint_strength_score",
                "design_quality_score",
                "execution_momentum",
                "sponsor_track_record_n",
            )
            if context.get(k) is not None
        )
        confidence += feature_count * 0.05

        # Regulatory events have more certain priors
        if node.event_family == EventFamily.REGULATORY.value:
            confidence += 0.1

        # Phase 3 has more data than phase 1
        if node.phase == "3":
            confidence += 0.1
        elif node.phase in ("1", "1_2"):
            confidence -= 0.1

        return min(max(confidence, 0.1), 0.95)

    # =========================================================================
    # Calibration evaluation
    # =========================================================================

    def evaluate_calibration(
        self,
        predictions: List[OutcomeProbabilities],
        actuals: List[str],
        n_bins: int = 5,
    ) -> Dict[str, Any]:
        """Evaluate calibration of outcome predictions against CRT resolutions.

        Args:
            predictions: list of OutcomeProbabilities
            actuals: list of actual outcomes ("HIT", "MISS", "MIXED")

        Returns:
            Calibration diagnostics: Brier score, ECE, bin table
        """
        if len(predictions) != len(actuals):
            return {"error": "length_mismatch"}

        n = len(predictions)
        if n < 5:
            return {"error": "insufficient_data", "n": n}

        # Brier score (for HIT prediction)
        brier_sum = 0.0
        p_hats = []
        y_trues = []
        for pred, actual in zip(predictions, actuals):
            p_hat = pred.p_hit
            y = 1.0 if actual == "HIT" else 0.0
            brier_sum += (p_hat - y) ** 2
            p_hats.append(p_hat)
            y_trues.append(y)

        brier_score = brier_sum / n

        # ECE (Expected Calibration Error)
        bins = self._compute_calibration_bins(p_hats, y_trues, n_bins)
        ece = sum(b["count"] / n * b["gap"] for b in bins)

        # Overall hit rate
        actual_hit_rate = sum(y_trues) / n

        return {
            "n": n,
            "brier_score": round(brier_score, 4),
            "ece": round(ece, 4),
            "actual_hit_rate": round(actual_hit_rate, 4),
            "mean_predicted_p_hit": round(sum(p_hats) / n, 4),
            "bins": bins,
        }

    def _compute_calibration_bins(
        self,
        p_hats: List[float],
        y_trues: List[float],
        n_bins: int,
    ) -> List[Dict[str, Any]]:
        """Compute calibration bins."""
        pairs = sorted(zip(p_hats, y_trues))
        bin_size = max(len(pairs) // n_bins, 1)
        bins = []
        for i in range(0, len(pairs), bin_size):
            chunk = pairs[i : i + bin_size]
            if not chunk:
                continue
            mean_p = sum(p for p, _ in chunk) / len(chunk)
            mean_y = sum(y for _, y in chunk) / len(chunk)
            bins.append(
                {
                    "mean_predicted": round(mean_p, 4),
                    "mean_actual": round(mean_y, 4),
                    "count": len(chunk),
                    "gap": round(abs(mean_p - mean_y), 4),
                }
            )
        return bins


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ez = math.exp(x)
    return ez / (1.0 + ez)
