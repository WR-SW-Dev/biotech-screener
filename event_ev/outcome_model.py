"""Layer 3 — Outcome Probability Model.

Bayesian prior-posterior framework for estimating catalyst outcome
branch probabilities (HIT / MISS / MIXED).

Prior: Phase-specific clinical PoS from Wong et al. + literature priors
       + CRT empirical calibration, keyed by (phase, indication, endpoint_class).

Phase-specific base rates (literature fallback):
  - Phase 1 readout: ~63% (transition to Phase 2)
  - Phase 2 readout: ~31% (transition to Phase 3)
  - Phase 3 readout: ~58% (primary endpoint success, Wong et al.)
  - PDUFA approval: ~85-90% (FDA CDER historical)

CRT calibration overrides literature when sufficient unbiased data exists.
Phase 1/2 CRT data excluded due to Herald positive-press-release selection bias.

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

# Literature-based phase transition success rates.
# These represent the probability that a readout at a given phase is positive
# (i.e., the drug advances), NOT the overall LoA from Phase X to approval.
# Sources: Wong et al. 2019, BIO/QLS 2011-2020, Thomas et al. 2016
#
# Phase 2 recalibration (2026-04-16):
#   Old value: 0.310 (Wong et al. 2019 Phase 2→3 transition)
#   HINT benchmark (n=6,610): empirical 49.2%, Brier 0.250 vs our 0.336
#   New value: 0.420 — conservative move toward benchmark (halfway between
#   0.310 and 0.492). Full move to 0.49 tested but deferred pending
#   downstream stability validation.
#   See: research/HINT_INTEGRATION.md, artifacts/hint_benchmark_phase2.json
LITERATURE_PHASE_READOUT_PRIORS: Dict[str, float] = {
    "1": 0.630,  # Phase 1→2 transition rate
    "1_2": 0.470,  # Midpoint of Phase 1→2 and Phase 2→3
    "2": 0.420,  # Phase 2→3 transition rate (recalibrated from 0.310, HINT benchmark)
    "2_3": 0.400,  # Phase 2/3→3 transition
    "3": 0.580,  # Phase 3 primary endpoint success (Wong et al.)
    "4": 0.650,  # Post-marketing (mostly confirmatory)
    "unknown": 0.350,  # Conservative unknown
}

# Pre-recalibration values preserved for A/B comparison
_PHASE_2_PRIOR_OLD = 0.310  # Wong et al. 2019
_PHASE_2_PRIOR_NEW = 0.420  # HINT-informed conservative recalibration
_PHASE_2_PRIOR_AGGRESSIVE = 0.492  # Full HINT empirical rate

# Mapping from CRT catalyst_type to clinical phase.
# Used by build_crt_calibration to aggregate resolution data.
# Extend this dict to capture new catalyst_type values from CRT.
DEFAULT_CATALYST_TYPE_TO_PHASE: Dict[str, str] = {
    "PHASE_1_DATA": "1",
    "PHASE_1_2_DATA": "1_2",
    "PHASE_2_READOUT": "2",
    "PHASE_2_3_READOUT": "2_3",
    "PHASE_3_READOUT": "3",
    "PHASE_4_DATA": "4",
}

# Phases where CRT data is EXCLUDED due to Herald positive-press-release
# selection bias (only positive readouts captured → inflated hit rate).
# Only Phase 3 has enough balanced (HIT + MISS) CRT data for calibration.
HERALD_BIASED_PHASES: frozenset = frozenset({"1", "1_2", "2"})

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
    "PDUFA_ACTION": 0.85,  # CRT alias for PDUFA
    "FDA_ADCOM": 0.65,  # advisory committee more uncertain
    "ADVISORY_COMMITTEE": 0.65,  # CRT alias for FDA_ADCOM
    "FDA_SUBMISSION": 0.90,  # most submissions get accepted
    "NDA_BLA_FILING": 0.90,  # CRT alias for FDA_SUBMISSION
    "FDA_DESIGNATION": 0.75,
    "REGULATORY_DESIGNATION": 0.75,  # CRT alias for FDA_DESIGNATION
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
        crt_calibration: Optional[Dict[str, Any]] = None,
        phase_readout_priors: Optional[Dict[str, float]] = None,
    ) -> None:
        self.pos_priors = pos_priors or dict(WONG_PHASE_PRIORS)
        self.mixed_fraction = mixed_fraction
        self.v2_priors = v2_priors  # loaded from clinical_pos_priors_v2.json
        self.crt_calibration = crt_calibration  # CRT empirical rates by phase
        # Phase-specific readout priors (literature-based, overridable)
        self.phase_readout_priors = phase_readout_priors or dict(LITERATURE_PHASE_READOUT_PRIORS)

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
                - literature_support_score: float [0, 1] (from PubMed, optional)

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
        eps = _safe_context_float(context, "endpoint_strength_score")
        if eps is not None:
            # Center at 0.5, scale to ±0.3 log-odds
            update = (eps - 0.5) * 0.6
            log_odds += update
            updates["endpoint_strength"] = round(update, 4)

        # Design quality
        dqs = _safe_context_float(context, "design_quality_score")
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
        # Execution momentum — only apply if non-zero (currently all 0.0 in rankings.csv)
        em = _safe_context_float(context, "execution_momentum")
        if em is not None and em != 0.0:
            update = em * 0.15  # small effect
            log_odds += update
            updates["execution_momentum"] = round(update, 4)

        # Competitive intensity (crowded → lower marginal value but same PoS)
        # Uses z-scored competitive_intensity_z (mean=0, std=1).
        # Only penalize extreme crowding (>2.0 std devs), not moderate.
        # Prior threshold of 0.7 was too low — fired on 56% of names.
        ci = _safe_context_float(context, "competitive_intensity_z")
        if ci is not None and ci > 2.0:
            update = -0.1 * min((ci - 2.0) / 2.0, 1.0)  # graduated, max -0.1
            log_odds += update
            updates["competitive_intensity"] = round(update, 4)

        # Literature support (PubMed enrichment, optional)
        # Higher literature score → more published evidence supporting the
        # mechanism/target, which modestly increases PoS. Capped at ±0.15
        # log-odds to prevent domination by publication volume.
        lit = _safe_context_float(context, "literature_support_score")
        if lit is not None and lit > 0:
            update = (lit - 0.3) * 0.3  # center at 0.3, scale ±0.15
            log_odds += update
            updates["literature_support"] = round(update, 4)

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
        """Get the base prior P(HIT) for this catalyst type.

        Priority order:
          1. Regulatory events → enriched FDA priors → flat regulatory priors
          2. Clinical events:
             a. CRT-calibrated (Bayesian blend, Phase 3+ only due to Herald bias)
             b. v2 empirical (if sufficient N)
             c. Phase-specific readout priors (literature-based)
             d. Wong et al. LoA priors (last resort)
        """
        # Regulatory events: try enriched FDA priors first
        if node.event_family == EventFamily.REGULATORY.value:
            enriched = self._get_enriched_regulatory_prior(node)
            if enriched is not None:
                return enriched

            # Fall back to flat regulatory priors
            reg_prior = _REGULATORY_PRIORS.get(node.event_type)
            if reg_prior is not None:
                return reg_prior, f"regulatory_{node.event_type}"

        # Clinical events: use phase-based PoS
        phase = node.phase

        # Try CRT-calibrated prior (Bayesian blend, unbiased phases only)
        if self.crt_calibration:
            crt_rate = self._lookup_crt_prior(phase)
            if crt_rate is not None:
                return crt_rate, "crt_calibrated"

        # Try v2 empirical (if available and sufficient N)
        if self.v2_priors:
            v2_rate = self._lookup_v2_prior(phase, node.indication)
            if v2_rate is not None:
                return v2_rate, "v2_empirical"

        # Phase-specific readout priors (literature-based)
        readout_prior = self.phase_readout_priors.get(phase)
        if readout_prior is not None:
            return readout_prior, "literature_phase_readout"

        # Fall back to Wong et al. LoA
        prior = self.pos_priors.get(phase, self.pos_priors.get("unknown", 0.25))
        return prior, "wong_et_al"

    def _get_enriched_regulatory_prior(self, node: CatalystNode) -> Optional[tuple[float, str]]:
        """Try to get enriched PDUFA/AdCom prior from FDA historical data."""
        try:
            from .fda_outcome_priors import enrich_regulatory_prior
        except ImportError:
            return None

        # Extract features from node metadata
        review_type = getattr(node, "review_type", None) or "UNKNOWN"
        therapeutic_area = node.indication or ""
        designations = getattr(node, "designations", None) or []
        has_prior_crl = getattr(node, "has_prior_crl", False)
        adcom_outcome = getattr(node, "adcom_outcome", None)

        result = enrich_regulatory_prior(
            node.event_type,
            review_type=review_type,
            therapeutic_area=therapeutic_area,
            designations=designations,
            has_prior_crl=has_prior_crl,
            adcom_outcome=adcom_outcome,
        )
        if result is None:
            return None

        return result["p_approve"], result["source"]

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

    def _lookup_crt_prior(self, phase: str) -> Optional[float]:
        """Look up CRT-calibrated prior for a phase.

        Uses beta-binomial posterior: blends literature prior with CRT evidence.
        Only returns a value if:
          - CRT has sufficient data (n >= 15) for the phase
          - The phase is NOT marked as Herald-biased
        """
        if not self.crt_calibration:
            return None

        entry = self.crt_calibration.get(phase)
        if entry is None:
            return None

        # Exclude Herald-biased phases (Phase 1/2 have inflated hit rates)
        if entry.get("herald_biased", False):
            return None

        n = entry.get("n", 0)
        if n < 15:
            return None  # insufficient CRT evidence

        return entry.get("posterior_mean")

    @staticmethod
    def build_crt_calibration(
        resolutions_dir,
        prior_equiv_n: int = 20,
        catalyst_type_to_phase: Optional[Dict[str, str]] = None,
        herald_biased_phases: Optional[frozenset] = None,
        as_of_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build CRT-calibrated priors from resolution records.

        Uses beta-binomial conjugate update:
          prior ~ Beta(alpha_0, beta_0) where alpha_0 = base_rate * prior_equiv_n
          posterior ~ Beta(alpha_0 + hits, beta_0 + misses)

        Herald-biased phases (1, 1_2, 2 by default) are collected but marked
        as biased so that _lookup_crt_prior can exclude them. Only unbiased
        phases (3, 2_3, 4) are used for calibration.

        The base rate for Bayesian blending uses LITERATURE_PHASE_READOUT_PRIORS
        (phase transition rates) rather than WONG_PHASE_PRIORS (lifetime LoA),
        since readout priors better match what CRT measures.

        Args:
            resolutions_dir: Path to data/snapshots/resolutions/
            prior_equiv_n: Effective sample size of the prior (higher = more
                conservative, lower = more data-driven). 20 = moderate trust.
            catalyst_type_to_phase: Mapping from catalyst_type to phase string.
                Defaults to DEFAULT_CATALYST_TYPE_TO_PHASE.
            herald_biased_phases: Phases to exclude from calibration.
                Defaults to HERALD_BIASED_PHASES.

        Returns:
            Dict keyed by phase with posterior_mean, hits, misses, n, prior, source.
        """
        import json
        from pathlib import Path

        resolutions_dir = Path(resolutions_dir)
        if not resolutions_dir.exists():
            return {}

        type_to_phase = catalyst_type_to_phase or DEFAULT_CATALYST_TYPE_TO_PHASE
        biased = herald_biased_phases if herald_biased_phases is not None else HERALD_BIASED_PHASES

        # Count hits/misses by phase
        from collections import defaultdict

        counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"hit": 0, "miss": 0})
        for month_dir in resolutions_dir.iterdir():
            if not month_dir.is_dir():
                continue
            for f in month_dir.glob("*.json"):
                try:
                    rec = json.loads(f.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                outcome = rec.get("outcome")
                ct = rec.get("catalyst_type", "")
                phase = type_to_phase.get(ct)
                if phase is None or outcome not in ("HIT", "MISS"):
                    continue
                # PIT gate: only use resolutions known at as_of_date
                if as_of_date:
                    resolved = rec.get("resolved_date") or rec.get("resolution_date", "")
                    if resolved > as_of_date:
                        continue
                if outcome == "HIT":
                    counts[phase]["hit"] += 1
                else:
                    counts[phase]["miss"] += 1

        calibration = {}
        for phase, c in counts.items():
            hits, misses = c["hit"], c["miss"]
            n = hits + misses

            # Use literature readout prior (not Wong LoA) for Bayesian blend
            base_rate = LITERATURE_PHASE_READOUT_PRIORS.get(phase, WONG_PHASE_PRIORS.get(phase, 0.25))

            # Beta-binomial posterior
            alpha_0 = base_rate * prior_equiv_n
            beta_0 = (1 - base_rate) * prior_equiv_n
            posterior_mean = (alpha_0 + hits) / (alpha_0 + beta_0 + n)

            is_biased = phase in biased
            calibration[phase] = {
                "hits": hits,
                "misses": misses,
                "n": n,
                "empirical_rate": round(hits / n, 4) if n > 0 else None,
                "base_rate_prior": round(base_rate, 4),
                "prior_equiv_n": prior_equiv_n,
                "posterior_mean": round(posterior_mean, 4),
                "herald_biased": is_biased,
            }
            bias_tag = " [HERALD-BIASED, excluded]" if is_biased else ""
            logger.info(
                "CRT calibration phase=%s: n=%d, empirical=%.3f, base=%.3f, posterior=%.3f%s",
                phase,
                n,
                hits / n if n > 0 else 0,
                base_rate,
                posterior_mean,
                bias_tag,
            )

        return calibration

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
        """Model confidence in probability estimates.

        Confidence reflects how much the p_hit estimate should be trusted.
        Low confidence → shrink EV influence harder in downstream consumers.
        """
        confidence = 0.5  # base

        # Prior quality hierarchy
        if prior_source == "crt_calibrated":
            confidence += 0.20  # best: real outcome data
        elif prior_source == "v2_empirical":
            confidence += 0.15
        elif prior_source.startswith("regulatory"):
            confidence += 0.15  # FDA historical is well-sourced
        elif prior_source == "literature_phase_readout":
            confidence += 0.05  # decent but generic
        # wong_et_al: no bonus (lowest quality)

        # Clinical discriminator features → higher confidence
        _discriminator_keys = (
            "endpoint_strength_score",
            "design_quality_score",
            "execution_momentum",
            "binary_quality_score",
        )
        feature_count = sum(1 for k in _discriminator_keys if _safe_context_float(context, k) is not None)
        confidence += feature_count * 0.04  # up to +0.16

        # Regulatory events have more certain priors
        if node.event_family == EventFamily.REGULATORY.value:
            confidence += 0.1

        # Phase 3 has more data than phase 1
        if node.phase == "3":
            confidence += 0.1
        elif node.phase in ("1", "1_2"):
            confidence -= 0.1

        # Unknown phase → big penalty (coarse pooled prior)
        if node.phase in ("unknown", ""):
            confidence -= 0.15

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


def _safe_context_float(context: Dict[str, Any], key: str) -> Optional[float]:
    """Safely extract a float from context (may be str from CSV)."""
    val = context.get(key)
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None
