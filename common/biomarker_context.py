"""Conditional biomarker scoring — context-dependent trial-quality modifier.

Replaces the old global-positive biomarker treatment with a conditional
signal that depends on phase, indication, protocol quality, and endpoint
specificity. Based on HINT benchmark finding that biomarker selection is
NOT globally positive (Δ=-2.7%) but may matter in specific contexts.

Design principles:
  - Biomarker selection is NOT a blanket positive
  - Biomarker + strong protocol + specific endpoints + oncology → positive
  - Biomarker + weak design + vague endpoints → neutral or slight negative
  - Biomarker in Phase 1 exploratory → near neutral
  - Biomarker in Phase 2/3 confirmatory + targeted indication → positive

PIT safety: all inputs are pre-catalyst PIT-safe fields.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Biomarker detection patterns (from conditional_model.py)
# ---------------------------------------------------------------------------

_BIOMARKER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bher2\b",
        r"\bher-2\b",
        r"\begfr\b",
        r"\bbraf\b",
        r"\bkras\b",
        r"\bbrca\b",
        r"\bpd-l1\b",
        r"\bpdl1\b",
        r"\bmsi[- ]?h",
        r"\btmb[- ]?h",
        r"\balk\b",
        r"\bfgfr\b",
        r"\bntrk\b",
        r"\bret\b",
        r"\bcd19\b",
        r"\bcd20\b",
        r"\bcd38\b",
        r"\bbcma\b",
        r"\bctdna\b",
        r"\bbiomarker[- ]?select",
        r"\bbiomarker[- ]?positive\b",
        r"\bmolecular[- ]?select",
        r"\bgenotype[- ]?positive\b",
        r"\bmutation[- ]?positive\b",
        r"\bexpression[- ]?positive\b",
        r"\bcompanion\s+diagnostic",
    ]
]

# Indication buckets where biomarker selection is mechanistically relevant
_TARGETED_INDICATIONS = frozenset(
    {
        "oncology",
        "hematology",
        "immuno-oncology",
    }
)

# Indications where biomarker is moderately relevant
_MODERATE_INDICATIONS = frozenset(
    {
        "rare_disease",
        "rare",
        "immunology",
        "autoimmune",
    }
)

# ---------------------------------------------------------------------------
# Conditional biomarker scoring rules
# ---------------------------------------------------------------------------

# Phase-dependent base relevance of biomarker selection.
# Higher = biomarker more meaningful in that phase context.
_PHASE_BIOMARKER_RELEVANCE = {
    "1": 0.15,  # exploratory: biomarker is early signal, not rigor
    "1_2": 0.25,
    "2": 0.40,  # proof-of-concept: biomarker selection adds real value
    "2_3": 0.50,
    "3": 0.35,  # confirmatory: biomarker matters but design dominates
}

# Indication multiplier for biomarker relevance
_INDICATION_BIOMARKER_MULT = {
    "targeted": 1.5,  # oncology/hematology: biomarker is core
    "moderate": 1.0,  # rare/autoimmune: biomarker is useful
    "broad": 0.5,  # general: biomarker is noise
}


def _detect_biomarker(trial: Dict[str, Any]) -> bool:
    """Check if trial involves biomarker-selected population."""
    title = trial.get("title", "")
    conditions = trial.get("conditions", [])
    endpoints = trial.get("primary_endpoints", [])
    interventions = trial.get("interventions", [])
    text = " ".join([title] + conditions + endpoints + interventions)
    return any(p.search(text) for p in _BIOMARKER_PATTERNS)


def _classify_indication_bucket(indication: str) -> str:
    """Classify indication into targeted/moderate/broad."""
    if not indication:
        return "broad"
    lower = indication.lower().strip()
    if (
        lower in _TARGETED_INDICATIONS
        or "oncolog" in lower
        or "cancer" in lower
        or "tumor" in lower
        or "leukemi" in lower
        or "lymphom" in lower
        or "melanom" in lower
        or "myelom" in lower
        or "nsclc" in lower
        or "sclc" in lower
        or "carcinoma" in lower
        or "sarcoma" in lower
        or "glioblastom" in lower
        or "egfr" in lower
        or "her2" in lower
        or "braf" in lower
    ):
        return "targeted"
    if lower in _MODERATE_INDICATIONS or "rare" in lower:
        return "moderate"
    return "broad"


def compute_biomarker_context_score(
    trial_records: list,
    as_of_date: str,
    protocol_quality: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Compute conditional biomarker score per ticker.

    Args:
        trial_records: List of trial dicts from trial_records.json.
        as_of_date: ISO date string for PIT filtering.
        protocol_quality: Optional pre-computed {ticker: {protocol_quality_score, ...}}.
            If not provided, biomarker scoring uses conservative defaults.

    Returns:
        {ticker: {
            "biomarker_context_score": float [-0.05, 0.30],
            "biomarker_detected": bool,
            "biomarker_signals": str,
            "biomarker_breakdown": dict,
        }}
    """
    from datetime import date as _date

    try:
        as_of = _date.fromisoformat(as_of_date)
    except (ValueError, TypeError):
        return {}

    protocol_quality = protocol_quality or {}

    by_ticker: Dict[str, list] = {}
    for t in trial_records:
        tk = (t.get("ticker") or "").upper()
        if tk:
            by_ticker.setdefault(tk, []).append(t)

    result = {}
    for ticker, trials in by_ticker.items():
        has_biomarker = False
        best_phase = "unknown"
        best_indication = ""

        _PHASE_RANK = {"1": 1, "1_2": 2, "2": 3, "2_3": 4, "3": 5}

        for t in trials:
            collected = t.get("collected_at", "")
            if collected and collected > str(as_of):
                continue
            if (t.get("study_type") or "").upper() != "INTERVENTIONAL":
                continue

            if _detect_biomarker(t):
                has_biomarker = True
                # Track the most advanced phase for this biomarker trial
                raw_phase = (t.get("phase") or "").upper().replace(" ", "")
                from common.protocol_quality import _TRIAL_PHASE_MAP

                trial_phase = _TRIAL_PHASE_MAP.get(raw_phase, "unknown")
                if _PHASE_RANK.get(trial_phase, 0) > _PHASE_RANK.get(best_phase, 0):
                    best_phase = trial_phase
                    # Get indication from the most advanced biomarker trial
                    conditions = t.get("conditions") or []
                    if conditions:
                        best_indication = conditions[0]

        if not has_biomarker:
            result[ticker] = {
                "biomarker_context_score": 0.0,
                "biomarker_detected": False,
                "biomarker_signals": "",
                "biomarker_breakdown": {},
            }
            continue

        # Compute conditional score
        score, breakdown, signals = _score_biomarker_context(
            phase=best_phase,
            indication=best_indication,
            protocol_quality_score=protocol_quality.get(ticker, {}).get("protocol_quality_score", 0.3),
            protocol_signals=protocol_quality.get(ticker, {}).get("protocol_signals", ""),
        )

        result[ticker] = {
            "biomarker_context_score": round(score, 4),
            "biomarker_detected": True,
            "biomarker_signals": ",".join(signals),
            "biomarker_breakdown": breakdown,
        }

    return result


def _score_biomarker_context(
    phase: str,
    indication: str,
    protocol_quality_score: float,
    protocol_signals: str,
) -> tuple:
    """Score biomarker relevance in context.

    Returns (score, breakdown dict, signal tags list).
    Score range: [-0.05, 0.30]. Negative = biomarker hurts (weak design context).
    """
    breakdown: Dict[str, float] = {}
    signals: List[str] = ["biomarker_detected"]

    # 1. Phase base relevance
    phase_rel = _PHASE_BIOMARKER_RELEVANCE.get(phase, 0.20)
    breakdown["phase_relevance"] = round(phase_rel, 4)
    signals.append(f"phase_{phase}")

    # 2. Indication context
    ind_bucket = _classify_indication_bucket(indication)
    ind_mult = _INDICATION_BIOMARKER_MULT.get(ind_bucket, 0.5)
    breakdown["indication_mult"] = round(ind_mult, 2)
    if ind_bucket == "targeted":
        signals.append("biomarker_oncology_targeted")
    elif ind_bucket == "moderate":
        signals.append("biomarker_moderate_indication")
    else:
        signals.append("biomarker_broad_indication")

    # 3. Protocol quality interaction
    # Strong protocol + biomarker = amplified; weak protocol + biomarker = dampened
    pq = protocol_quality_score
    if pq >= 0.5:
        pq_mult = 1.2  # strong design amplifies biomarker value
        signals.append("biomarker_strong_design_bonus")
    elif pq >= 0.25:
        pq_mult = 1.0  # moderate design: neutral
    else:
        pq_mult = 0.6  # weak design: dampened
        signals.append("biomarker_weak_design_dampened")
    breakdown["protocol_quality_mult"] = round(pq_mult, 2)

    # 4. Endpoint interaction
    # If protocol signals include specific_endpoint, biomarker is more credible
    has_specific_ep = "specific_endpoint" in protocol_signals
    ep_bonus = 0.05 if has_specific_ep else 0.0
    breakdown["endpoint_bonus"] = round(ep_bonus, 4)
    if has_specific_ep:
        signals.append("biomarker_specific_endpoint_bonus")

    # 5. Comparator interaction
    # Biomarker + comparator = strong evidence structure
    has_comparator = "comparator" in protocol_signals
    comp_bonus = 0.03 if has_comparator else 0.0
    breakdown["comparator_bonus"] = round(comp_bonus, 4)
    if has_comparator:
        signals.append("biomarker_comparator_bonus")

    # Composite: phase_relevance * indication_mult * protocol_mult + bonuses
    raw = phase_rel * ind_mult * pq_mult + ep_bonus + comp_bonus
    # Clamp to [-0.05, 0.30] — allow slight negative for weak-design biomarker traps
    score = max(-0.05, min(0.30, raw))

    return score, breakdown, signals
