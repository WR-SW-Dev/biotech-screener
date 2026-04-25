"""Conditional Modeling — biomarker / subgroup mispricing detection.

Captures mispriced conditionals: the market prices a generic event, but
true odds or payoff differ materially for a conditioned subgroup:
  - biomarker-selected trials
  - enriched / adaptive designs
  - validated mechanism context
  - prior same-platform success

Outputs a diagnostic alpha candidate (conditional_gap_score) that is
**not** used in production ranking. Sidecar / research only until
PIT-safe standalone validation passes.

Policy: DIAGNOSTIC ONLY. Not in ranking or selection.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EPS = 1e-6

# ═════════════════════════════════════════════════════════════════════════
# Data contract
# ═════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ConditionalModelOverlay:
    """Conditional mispricing assessment for a single ticker.

    Policy: DIAGNOSTIC ONLY. Not in ranking or selection.
    """

    ticker: str
    as_of_date: str
    conditional_bucket: str  # {event_family}|{phase}|{selected_vs_unselected}|{mechanism_class}
    conditional_base_rate: float  # shrinkage-smoothed P(success) for bucket
    conditional_expected_move: float  # weighted expected abs move for bucket
    conditional_gap_score: float  # (expected - priced) / (|priced| + eps), clamped [-1, 1]
    conditional_confidence: float  # [0, 1] data quality * bucket depth
    conditional_notes: str  # human-readable context

    # Audit trail
    bucket_n: int = 0  # sample size for conditional bucket
    shrinkage_applied: float = 0.0  # fraction of prior used
    fallback_level: int = 0  # 0=full, 1=family+phase+sel, 2=family+phase, 3=global
    features_used: Dict[str, Any] = field(default_factory=dict)
    model_version: str = "conditional_v1.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "as_of_date": self.as_of_date,
            "conditional_bucket": self.conditional_bucket,
            "conditional_base_rate": round(self.conditional_base_rate, 4),
            "conditional_expected_move": round(self.conditional_expected_move, 4),
            "conditional_gap_score": round(self.conditional_gap_score, 4),
            "conditional_confidence": round(self.conditional_confidence, 4),
            "conditional_notes": self.conditional_notes,
            "bucket_n": self.bucket_n,
            "shrinkage_applied": round(self.shrinkage_applied, 4),
            "fallback_level": self.fallback_level,
            "features_used": self.features_used,
            "model_version": self.model_version,
        }


# ═════════════════════════════════════════════════════════════════════════
# Biomarker / enrichment detection from trial text
# ═════════════════════════════════════════════════════════════════════════

# Patterns that indicate biomarker-selected populations
_BIOMARKER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bBRCA\b",
        r"\bHER2\b",
        r"\bEGFR\b",
        r"\bALK\b",
        r"\bKRAS\b",
        r"\bBRAF\b",
        r"\bPD-?L1\b",
        r"\bMSI-?H\b",
        r"\bdMMR\b",
        r"\bFGFR\b",
        r"\bROS1\b",
        r"\bNTRK\b",
        r"\bIDH[12]\b",
        r"\bBCR-?ABL\b",
        r"\bFLT3\b",
        r"\bTP53\b",
        r"\bCD\d+[+-]\b",  # e.g. CD19+, CD20+
        r"\bmutation[- ]positive\b",
        r"\bbiomarker[- ]selected\b",
        r"\bbiomarker[- ]positive\b",
        r"\bgenetically[- ]confirmed\b",
        r"\bmolecularly[- ]defined\b",
        r"\bcompanion diagnostic\b",
    ]
]

# Patterns that indicate enriched / adaptive design
_ENRICHMENT_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\benriched\b",
        r"\benrichment\b",
        r"\badaptive design\b",
        r"\bresponder[- ]?enriched\b",
        r"\bbiomarker[- ]?stratified\b",
        r"\bprecision\b.*\btrial\b",
        r"\bbasket trial\b",
        r"\bumbrella trial\b",
        r"\bplatform trial\b",
    ]
]

# Patterns for mechanism class detection
_VALIDATED_MECHANISM_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bcheckpoint inhibitor\b",
        r"\bPD-?[1L]\b.*\binhibitor\b",
        r"\bCAR-?T\b",
        r"\bbispecific\b",
        r"\bADC\b",  # antibody-drug conjugate
        r"\bGLP-?1\b",
        r"\bJAK\b.*\binhibitor\b",
        r"\bBTK\b.*\binhibitor\b",
        r"\bmRNA\b",
        r"\bsiRNA\b",
        r"\bASO\b",  # antisense oligonucleotide
        r"\bgene therap\b",
    ]
]


def _join_text(*parts) -> str:
    """Join a mix of strings and string lists, dropping None / non-str entries."""
    out: List[str] = []
    for p in parts:
        if p is None:
            continue
        if isinstance(p, str):
            out.append(p)
        else:
            out.extend(s for s in p if isinstance(s, str))
    return " ".join(out)


def _detect_biomarker_selected(title: str, conditions: List[str], endpoints: List[str]) -> bool:
    """Check if trial text indicates biomarker-selected population."""
    text = _join_text(title, conditions, endpoints)
    return any(p.search(text) for p in _BIOMARKER_PATTERNS)


def _detect_enrichment(title: str, conditions: List[str], endpoints: List[str]) -> bool:
    """Check if trial text indicates enriched or adaptive design."""
    text = _join_text(title, conditions, endpoints)
    return any(p.search(text) for p in _ENRICHMENT_PATTERNS)


def _detect_adaptive_design(intervention_model: str, title: str) -> bool:
    """Check for adaptive design from structured field or title."""
    if intervention_model and "adaptive" in intervention_model.lower():
        return True
    return bool(re.search(r"\badaptive\b", title, re.IGNORECASE))


def _classify_mechanism(interventions: List[str], conditions: List[str], title: str) -> str:
    """Classify mechanism as validated / semi_validated / novel / unknown."""
    text = _join_text(title, interventions, conditions)
    if any(p.search(text) for p in _VALIDATED_MECHANISM_PATTERNS):
        return "validated"
    # Semi-validated: has identifiable drug class but not in validated list
    if re.search(r"\binhibitor\b|\bantibody\b|\bagonist\b|\bantagonist\b", text, re.IGNORECASE):
        return "semi_validated"
    if interventions:
        return "novel"
    return "unknown"


def _classify_selection_status(
    biomarker_selected: bool,
    enrichment: bool,
    adaptive: bool,
) -> str:
    """Map flags to selected / enriched / unselected / unknown."""
    if biomarker_selected:
        return "selected"
    if enrichment or adaptive:
        return "enriched"
    return "unselected"


# ═════════════════════════════════════════════════════════════════════════
# Conditional base-rate priors (shrinkage-smoothed)
# ═════════════════════════════════════════════════════════════════════════

# Empirical base rates by bucket key.
# Source: Wong et al. + CRT + AACT outcome analysis.
# Keys: event_family|phase|selection_status|mechanism_class
# Values: (n_trials, n_successes)
#
# These are seeded from literature; the system will accumulate
# empirical updates via CRT resolutions over time.

_GLOBAL_BASE_RATES: Dict[str, Tuple[int, int]] = {
    # Phase 3
    "CLINICAL|phase3|selected|validated": (45, 33),  # 73%
    "CLINICAL|phase3|selected|semi_validated": (30, 20),  # 67%
    "CLINICAL|phase3|enriched|validated": (25, 17),  # 68%
    "CLINICAL|phase3|enriched|semi_validated": (20, 12),  # 60%
    "CLINICAL|phase3|unselected|validated": (80, 46),  # 58%
    "CLINICAL|phase3|unselected|semi_validated": (60, 30),  # 50%
    "CLINICAL|phase3|unselected|novel": (40, 16),  # 40%
    # Phase 2
    "CLINICAL|phase2|selected|validated": (35, 18),  # 51%
    "CLINICAL|phase2|selected|semi_validated": (25, 11),  # 44%
    "CLINICAL|phase2|enriched|validated": (20, 9),  # 45%
    "CLINICAL|phase2|enriched|semi_validated": (15, 6),  # 40%
    "CLINICAL|phase2|unselected|validated": (60, 18),  # 30%
    "CLINICAL|phase2|unselected|semi_validated": (50, 13),  # 26%
    "CLINICAL|phase2|unselected|novel": (40, 8),  # 20%
    # Phase 1
    "CLINICAL|early|selected|validated": (20, 5),  # 25%
    "CLINICAL|early|unselected|validated": (40, 6),  # 15%
    "CLINICAL|early|unselected|novel": (30, 3),  # 10%
    # Regulatory
    "REGULATORY|phase3|selected|validated": (30, 26),  # 87%
    "REGULATORY|phase3|unselected|validated": (50, 40),  # 80%
    "REGULATORY|phase3|unselected|semi_validated": (35, 24),  # 69%
    "REGULATORY|phase2|selected|validated": (15, 11),  # 73%
    "REGULATORY|phase2|unselected|validated": (25, 16),  # 64%
}

# Parent-level fallback rates (event_family|phase|selection_status)
_FALLBACK_L1: Dict[str, Tuple[int, int]] = {
    "CLINICAL|phase3|selected": (100, 68),  # 68%
    "CLINICAL|phase3|enriched": (50, 30),  # 60%
    "CLINICAL|phase3|unselected": (180, 92),  # 51%
    "CLINICAL|phase2|selected": (60, 28),  # 47%
    "CLINICAL|phase2|enriched": (35, 15),  # 43%
    "CLINICAL|phase2|unselected": (150, 39),  # 26%
    "CLINICAL|early|selected": (25, 6),  # 24%
    "CLINICAL|early|unselected": (70, 9),  # 13%
    "REGULATORY|phase3|selected": (30, 26),  # 87%
    "REGULATORY|phase3|unselected": (85, 64),  # 75%
    "REGULATORY|phase2|selected": (15, 11),  # 73%
    "REGULATORY|phase2|unselected": (25, 16),  # 64%
}

# Broader fallback (event_family|phase)
_FALLBACK_L2: Dict[str, Tuple[int, int]] = {
    "CLINICAL|phase3": (330, 190),  # 58% (Wong)
    "CLINICAL|phase2": (245, 82),  # 33% (Wong adjusted)
    "CLINICAL|early": (95, 15),  # 16%
    "REGULATORY|phase3": (115, 90),  # 78%
    "REGULATORY|phase2": (40, 27),  # 68%
    "REGULATORY|early": (20, 10),  # 50%
}

# Global fallback
_FALLBACK_GLOBAL: Tuple[int, int] = (800, 320)  # 40%

# Shrinkage strength
_SHRINKAGE_K = 10

# Historical move distributions by event_family|phase|outcome
# Mean abs % move for HIT/MISS, used to compute conditional expected move.
# Source: payoff_engine.py empirical distributions.
_MOVE_PRIORS: Dict[str, Dict[str, float]] = {
    "CLINICAL|phase3": {"up_mean": 20.0, "down_mean": 50.0},
    "CLINICAL|phase2": {"up_mean": 30.0, "down_mean": 40.0},
    "CLINICAL|early": {"up_mean": 25.0, "down_mean": 25.0},
    "REGULATORY|phase3": {"up_mean": 8.0, "down_mean": 30.0},
    "REGULATORY|phase2": {"up_mean": 12.0, "down_mean": 35.0},
    "REGULATORY|early": {"up_mean": 15.0, "down_mean": 25.0},
    "SAFETY|any": {"up_mean": 5.0, "down_mean": 20.0},
}


def _shrinkage_rate(
    bucket_key: str,
) -> Tuple[float, int, float, int]:
    """Compute shrinkage-smoothed base rate with fallback chain.

    Returns (smoothed_rate, bucket_n, shrinkage_fraction, fallback_level).
    """
    # Try full key
    if bucket_key in _GLOBAL_BASE_RATES:
        n, s = _GLOBAL_BASE_RATES[bucket_key]
        raw_rate = s / n if n > 0 else 0.4
        global_rate = _FALLBACK_GLOBAL[1] / _FALLBACK_GLOBAL[0]
        smoothed = (n * raw_rate + _SHRINKAGE_K * global_rate) / (n + _SHRINKAGE_K)
        shrink_frac = _SHRINKAGE_K / (n + _SHRINKAGE_K)
        return smoothed, n, shrink_frac, 0

    # Fallback L1: event_family|phase|selection
    parts = bucket_key.split("|")
    if len(parts) >= 3:
        l1_key = "|".join(parts[:3])
        if l1_key in _FALLBACK_L1:
            n, s = _FALLBACK_L1[l1_key]
            raw_rate = s / n if n > 0 else 0.4
            global_rate = _FALLBACK_GLOBAL[1] / _FALLBACK_GLOBAL[0]
            smoothed = (n * raw_rate + _SHRINKAGE_K * global_rate) / (n + _SHRINKAGE_K)
            shrink_frac = _SHRINKAGE_K / (n + _SHRINKAGE_K)
            return smoothed, n, shrink_frac, 1

    # Fallback L2: event_family|phase
    if len(parts) >= 2:
        l2_key = "|".join(parts[:2])
        if l2_key in _FALLBACK_L2:
            n, s = _FALLBACK_L2[l2_key]
            raw_rate = s / n if n > 0 else 0.4
            global_rate = _FALLBACK_GLOBAL[1] / _FALLBACK_GLOBAL[0]
            smoothed = (n * raw_rate + _SHRINKAGE_K * global_rate) / (n + _SHRINKAGE_K)
            shrink_frac = _SHRINKAGE_K / (n + _SHRINKAGE_K)
            return smoothed, n, shrink_frac, 2

    # Global fallback
    n, s = _FALLBACK_GLOBAL
    rate = s / n
    return rate, n, 1.0, 3


def _conditional_expected_move(
    base_rate: float,
    family_phase: str,
) -> float:
    """Compute conditional expected move = P(hit)*up + (1-P(hit))*down."""
    moves = _MOVE_PRIORS.get(family_phase) or _MOVE_PRIORS.get("CLINICAL|phase2", {"up_mean": 20.0, "down_mean": 35.0})
    return base_rate * moves["up_mean"] + (1.0 - base_rate) * moves["down_mean"]


def _conditional_gap(
    expected_move: float,
    priced_move_pct: Optional[float],
) -> float:
    """Compute gap score: tanh((expected - priced) / (|priced| + eps) / 2).

    Soft-scaled via tanh to avoid saturation at +/-1 when
    cond_ev >> priced_move (common in live options data).
    """
    if priced_move_pct is None:
        return 0.0
    gap = (expected_move - priced_move_pct) / (abs(priced_move_pct) + EPS)
    return math.tanh(gap / 2.0)


def _conditional_confidence(
    bucket_n: int,
    data_quality: float,
    target_n: int = 30,
) -> float:
    """Confidence = min(1, log1p(n) / log1p(target)) * quality."""
    depth = min(1.0, math.log1p(bucket_n) / math.log1p(target_n))
    return round(min(1.0, depth * data_quality), 4)


# ═════════════════════════════════════════════════════════════════════════
# Trial context builder
# ═════════════════════════════════════════════════════════════════════════


def _build_trial_context(
    ticker: str,
    trial_records: List[Dict[str, Any]],
    as_of_date: str,
) -> Dict[str, Any]:
    """Extract conditional features from trial records for a ticker.

    Returns dict with biomarker/enrichment/mechanism flags derived
    from the ticker's active/recent trials.
    """
    from datetime import date as dt_date

    cutoff = dt_date.fromisoformat(as_of_date)
    ticker_trials = [t for t in trial_records if t.get("ticker") == ticker]

    if not ticker_trials:
        return {
            "biomarker_selected_flag": False,
            "enrichment_flag": False,
            "adaptive_design_flag": False,
            "mechanism_class": "unknown",
            "prior_same_platform_success_flag": False,
            "companion_dx_flag": False,
            "n_trials_assessed": 0,
            "data_quality": 0.3,
        }

    # Filter to PIT-visible trials (first_posted <= as_of_date)
    visible = []
    for t in ticker_trials:
        fp = t.get("first_posted")
        if fp:
            try:
                if dt_date.fromisoformat(fp) <= cutoff:
                    visible.append(t)
            except (ValueError, TypeError):
                visible.append(t)
        else:
            visible.append(t)

    if not visible:
        return {
            "biomarker_selected_flag": False,
            "enrichment_flag": False,
            "adaptive_design_flag": False,
            "mechanism_class": "unknown",
            "prior_same_platform_success_flag": False,
            "companion_dx_flag": False,
            "n_trials_assessed": 0,
            "data_quality": 0.3,
        }

    # Aggregate flags across trials (any-positive)
    biomarker = False
    enriched = False
    adaptive = False
    companion_dx = False
    mechanisms: List[str] = []
    has_completed_success = False

    for t in visible:
        title = t.get("title", "")
        conditions = t.get("conditions", [])
        endpoints = t.get("primary_endpoints", [])
        interventions = t.get("interventions", [])
        int_model = t.get("intervention_model", "")
        status = (t.get("status") or "").upper()

        if _detect_biomarker_selected(title, conditions, endpoints):
            biomarker = True
        if _detect_enrichment(title, conditions, endpoints):
            enriched = True
        if _detect_adaptive_design(int_model, title):
            adaptive = True
        if re.search(r"companion diagnostic", _join_text(title, conditions), re.IGNORECASE):
            companion_dx = True

        mech = _classify_mechanism(interventions, conditions, title)
        mechanisms.append(mech)

        # Prior same-platform success: completed trial with results
        if status == "COMPLETED" and t.get("results_first_posted"):
            has_completed_success = True

    # Best mechanism across trials
    mech_priority = {"validated": 3, "semi_validated": 2, "novel": 1, "unknown": 0}
    best_mech = max(mechanisms, key=lambda m: mech_priority.get(m, 0)) if mechanisms else "unknown"

    # Data quality based on field coverage
    quality = 0.5
    if biomarker or enriched:
        quality += 0.2  # explicit signal found
    if len(visible) >= 3:
        quality += 0.15  # multiple trials = more context
    if any(t.get("primary_endpoints") for t in visible):
        quality += 0.15  # endpoints available
    quality = min(1.0, quality)

    return {
        "biomarker_selected_flag": biomarker,
        "enrichment_flag": enriched,
        "adaptive_design_flag": adaptive,
        "mechanism_class": best_mech,
        "prior_same_platform_success_flag": has_completed_success,
        "companion_dx_flag": companion_dx,
        "n_trials_assessed": len(visible),
        "data_quality": round(quality, 2),
    }


# ═════════════════════════════════════════════════════════════════════════
# Phase bucket helper (shared with expectation_error_model)
# ═════════════════════════════════════════════════════════════════════════


def _phase_bucket(phase_str: str) -> str:
    """Map lead_program_phase to coarse bucket."""
    if not phase_str:
        return "early"
    try:
        p = float(phase_str)
    except (ValueError, TypeError):
        s = phase_str.upper()
        if "3" in s:
            return "phase3"
        if "2" in s:
            return "phase2"
        return "early"
    if p >= 3:
        return "phase3"
    if p >= 2:
        return "phase2"
    return "early"


# ═════════════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════════════


class ConditionalModel:
    """Compute conditional mispricing scores for a universe.

    Usage:
        model = ConditionalModel(trial_records=trials)
        results = model.score_batch(csv_rows, as_of_date)
    """

    def __init__(
        self,
        trial_records: Optional[List[Dict[str, Any]]] = None,
        trial_records_path: Optional[Path] = None,
    ) -> None:
        if trial_records is not None:
            self._trials = trial_records
        elif trial_records_path and trial_records_path.exists():
            with open(trial_records_path, "r", encoding="utf-8") as f:
                self._trials = json.load(f)
            logger.info("[ConditionalModel] Loaded %d trial records from %s", len(self._trials), trial_records_path)
        else:
            self._trials = []
            logger.warning("[ConditionalModel] No trial records provided — all tickers get unknown context")

        # Pre-index trials by ticker for O(1) lookup
        self._trials_by_ticker: Dict[str, List[Dict[str, Any]]] = {}
        for t in self._trials:
            tk = t.get("ticker", "")
            if tk:
                self._trials_by_ticker.setdefault(tk, []).append(t)

    def score_row(
        self,
        row: Dict[str, Any],
        as_of_date: str,
    ) -> ConditionalModelOverlay:
        """Score a single ticker row from rankings.csv."""
        ticker = row.get("ticker", "?")
        features: Dict[str, Any] = {}

        # Extract CSV inputs
        family = (row.get("catalyst_family") or "CLINICAL").upper()
        phase = _phase_bucket(row.get("lead_program_phase", ""))
        priced_move = _safe_float(row.get("priced_move_pct"))

        # Get trial context for this ticker
        ticker_trials = self._trials_by_ticker.get(ticker, [])
        ctx = _build_trial_context(ticker, ticker_trials, as_of_date)
        features["trial_context"] = ctx

        # Classify selection status
        sel_status = _classify_selection_status(
            ctx["biomarker_selected_flag"],
            ctx["enrichment_flag"],
            ctx["adaptive_design_flag"],
        )
        # If no trial data, mark as unknown
        if ctx["n_trials_assessed"] == 0:
            sel_status = "unknown"

        mech_class = ctx["mechanism_class"]

        # Build bucket key
        bucket_key = f"{family}|{phase}|{sel_status}|{mech_class}"
        family_phase = f"{family}|{phase}"

        # Compute shrinkage base rate
        base_rate, bucket_n, shrink_frac, fallback_level = _shrinkage_rate(bucket_key)

        # Compute conditional expected move
        expected_move = _conditional_expected_move(base_rate, family_phase)

        # Compute gap score
        gap_score = _conditional_gap(expected_move, priced_move)

        # Compute confidence
        confidence = _conditional_confidence(bucket_n, ctx["data_quality"])

        # Build notes
        notes_parts: List[str] = []
        if sel_status == "selected":
            notes_parts.append("biomarker-selected subgroup")
        elif sel_status == "enriched":
            notes_parts.append("enriched/adaptive design")
        if fallback_level > 0:
            notes_parts.append(f"L{fallback_level} fallback applied")
        if shrink_frac > 0.3:
            notes_parts.append(f"high shrinkage ({shrink_frac:.0%})")
        notes_parts.append(f"bucket n={bucket_n}")
        if sel_status in ("selected", "enriched") and fallback_level == 0:
            # Compute uplift vs unselected
            unsel_key = f"{family}|{phase}|unselected|{mech_class}"
            unsel_rate, _, _, _ = _shrinkage_rate(unsel_key)
            uplift = (base_rate - unsel_rate) * 100
            if abs(uplift) > 1:
                notes_parts.append(f"uplift vs unselected {uplift:+.0f} pts")
        if ctx["prior_same_platform_success_flag"]:
            notes_parts.append("platform prior success")
        if mech_class == "novel":
            notes_parts.append("novel mechanism")

        features["inputs"] = {
            "catalyst_family": family,
            "phase_bucket": phase,
            "priced_move_pct": priced_move,
            "selection_status": sel_status,
            "mechanism_class": mech_class,
        }

        return ConditionalModelOverlay(
            ticker=ticker,
            as_of_date=as_of_date,
            conditional_bucket=bucket_key,
            conditional_base_rate=base_rate,
            conditional_expected_move=expected_move,
            conditional_gap_score=gap_score,
            conditional_confidence=confidence,
            conditional_notes="; ".join(notes_parts),
            bucket_n=bucket_n,
            shrinkage_applied=shrink_frac,
            fallback_level=fallback_level,
            features_used=features,
        )

    def score_batch(
        self,
        csv_rows: List[Dict[str, Any]],
        as_of_date: str,
    ) -> List[ConditionalModelOverlay]:
        """Score all rows. Returns one overlay per row (same order)."""
        results = []
        for row in csv_rows:
            results.append(self.score_row(row, as_of_date))

        n_scored = len(results)
        n_selected = sum(1 for r in results if "selected" in r.conditional_bucket)
        n_enriched = sum(1 for r in results if "enriched" in r.conditional_bucket)
        n_high_conf = sum(1 for r in results if r.conditional_confidence >= 0.5)
        logger.info(
            "[ConditionalModel] Scored %d tickers: %d selected, %d enriched, %d high-confidence",
            n_scored,
            n_selected,
            n_enriched,
            n_high_conf,
        )
        return results


# ═════════════════════════════════════════════════════════════════════════
# CSV enrichment (called from run_screen.py)
# ═════════════════════════════════════════════════════════════════════════

CONDITIONAL_CSV_COLUMNS = [
    "conditional_bucket",
    "conditional_base_rate",
    "conditional_expected_move",
    "conditional_gap_score",
    "conditional_confidence",
    "conditional_notes",
]


def enrich_csv_rows(
    csv_rows: List[Dict[str, Any]],
    as_of_date: str,
    trial_records_path: Optional[Path] = None,
) -> List[ConditionalModelOverlay]:
    """Compute conditional scores and inject columns in-place.

    Returns the list of ConditionalModelOverlay objects (for sidecar writing).
    """
    if trial_records_path is None:
        trial_records_path = Path("production_data") / "trial_records.json"

    model = ConditionalModel(trial_records_path=trial_records_path)
    overlays = model.score_batch(csv_rows, as_of_date)

    for row, overlay in zip(csv_rows, overlays):
        row["conditional_bucket"] = overlay.conditional_bucket
        row["conditional_base_rate"] = overlay.conditional_base_rate
        row["conditional_expected_move"] = overlay.conditional_expected_move
        row["conditional_gap_score"] = overlay.conditional_gap_score
        row["conditional_confidence"] = overlay.conditional_confidence
        row["conditional_notes"] = overlay.conditional_notes

    return overlays


def _safe_float(v: Any) -> Optional[float]:
    """Safe float extraction from CSV row values."""
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None
