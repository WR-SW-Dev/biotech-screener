"""Protocol quality score — trial design rigor derived from eligibility criteria.

Transparent, PIT-safe features extracted from ClinicalTrials.gov protocol text.
Feeds into clinical_score_v2 via CalendarAlpha composition.

Source: research/hint_feature_extract.py (HINT benchmark-derived patterns).
All features are pre-catalyst PIT-safe (eligibility posted before enrollment).

Design principles:
  - Comparator + randomization + blinding = stronger design → positive
  - Endpoint specificity = clearer primary endpoint → positive
  - Multi-arm = can be rigor or complexity; neutral-to-slightly-positive
  - Biomarker selection = globally neutral (HINT data: Δ=-2.7%, not positive)
  - Excess complexity (very high criteria counts) = enrollment burden → slight negative
  - Protocol quality ≠ "more text = better"
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern libraries (from research/hint_feature_extract.py)
# ---------------------------------------------------------------------------

_COMPARATOR_PATTERNS = [
    r"\bplacebo\b",
    r"\bcomparator\b",
    r"\bstandard.?of.?care\b",
    r"\bactive.?control\b",
    r"\bsoc\b",
    r"\bcontrol.?arm\b",
    r"\bbest.?supportive\b",
]

_RANDOMIZATION_PATTERNS = [
    r"\brandom\w*\b",
    r"\brandomiz\w*\b",
]

_BLINDING_PATTERNS = [
    r"\bdouble.?blind\b",
    r"\bsingle.?blind\b",
    r"\btriple.?blind\b",
    r"\bblinded\b",
    r"\bmasked\b",
    r"\bdouble.?mask\b",
]

_MULTI_ARM_PATTERNS = [
    r"\bmulti.?arm\b",
    r"\b\d+.?arm\b",
    r"\bthree.?arm\b",
    r"\bfour.?arm\b",
    r"\bcohort\s+[a-d]\b",
]

_ENDPOINT_KEYWORDS = [
    r"\boverall.?survival\b",
    r"\bprogression.?free\b",
    r"\bpfs\b",
    r"\bcomplete.?response\b",
    r"\bobjective.?response\b",
    r"\borr\b",
    r"\bprimary.?endpoint\b",
    r"\bco-primary\b",
    r"\bhazard.?ratio\b",
    r"\bsuperior\b",
    r"\bnon.?inferior\b",
]


def _has_pattern(text: str, patterns: list) -> bool:
    lower = text.lower()
    return any(re.search(p, lower) for p in patterns)


def _count_criteria(text: str, section: str) -> int:
    """Count bullet-point criteria in inclusion/exclusion section."""
    lines = text.split("\n")
    in_section = False
    count = 0
    for line in lines:
        stripped = line.strip().lower()
        if section in stripped:
            in_section = True
            continue
        if in_section:
            other = "exclusion" if section == "inclusion" else "inclusion"
            if other in stripped:
                break
            if re.match(r"^[-\u2013\u2022*]\s|^\d+[.\)]\s|^[a-z][.\)]\s", stripped):
                count += 1
    return count


def _endpoint_specificity(text: str) -> float:
    """Score how specific the protocol is about endpoints. [0, 1]."""
    lower = text.lower()
    hits = sum(1 for p in _ENDPOINT_KEYWORDS if re.search(p, lower))
    return min(hits / 5.0, 1.0)


# ---------------------------------------------------------------------------
# Protocol quality score
# ---------------------------------------------------------------------------

# Feature weights for protocol quality subscore.
# Positive = feature indicates stronger trial design.
# These are hand-set, transparent, and capped.
_FEATURE_WEIGHTS = {
    "comparator": 0.25,  # comparator arm = strongest rigor indicator
    "randomization": 0.20,  # randomization = reduced bias
    "blinding": 0.20,  # blinding = reduced observer bias
    "endpoint_spec": 0.20,  # specific endpoint = clearer signal
    "multi_arm": 0.05,  # slight positive for structured comparison
    "complexity_penalty": -0.10,  # excess criteria count = enrollment burden
}

# Max influence on clinical_score_v2 (bounded)
MAX_PROTOCOL_ADJUSTMENT = 0.35  # same cap as other CalendarAlpha components


def compute_protocol_quality(
    trial_records: list,
    as_of_date: str,
) -> Dict[str, Dict[str, Any]]:
    """Compute protocol quality features per ticker from trial structured fields.

    Primary source: structured ClinicalTrials.gov fields (allocation, masking,
    intervention_model, primary_endpoints). Falls back to eligibility text
    patterns when structured fields are absent.

    PIT-safe: uses only data posted before trial enrollment.

    Args:
        trial_records: List of trial dicts from trial_records.json.
        as_of_date: ISO date string for PIT filtering.

    Returns:
        {ticker: {
            "protocol_quality_score": float [0, 1],
            "protocol_signals": str (comma-separated signal tags),
            "protocol_breakdown": dict (per-feature contributions),
        }}
    """
    from datetime import date as _date

    try:
        as_of = _date.fromisoformat(as_of_date)
    except (ValueError, TypeError):
        return {}

    by_ticker: Dict[str, list] = {}
    for t in trial_records:
        tk = (t.get("ticker") or "").upper()
        if tk:
            by_ticker.setdefault(tk, []).append(t)

    result = {}
    for ticker, trials in by_ticker.items():
        best_score = 0.0
        best_breakdown: Dict[str, float] = {}
        best_signals: List[str] = []

        for t in trials:
            # PIT check: collected_at <= as_of
            collected = t.get("collected_at", "")
            if collected and collected > str(as_of):
                continue

            # Only score interventional trials
            if (t.get("study_type") or "").upper() != "INTERVENTIONAL":
                continue

            score, breakdown, sigs = _score_single_trial(t)
            if score > best_score:
                best_score = score
                best_breakdown = breakdown
                best_signals = sigs

        result[ticker] = {
            "protocol_quality_score": round(best_score, 4),
            "protocol_signals": ",".join(best_signals),
            "protocol_breakdown": best_breakdown,
        }

    return result


def _score_single_trial(trial: Dict[str, Any]) -> tuple:
    """Score a single trial's protocol quality from structured fields.

    Uses ClinicalTrials.gov structured data (allocation, masking,
    intervention_model, primary_endpoints) as the primary source.
    Falls back to eligibility text patterns when structured fields are absent.

    Returns (score [0,1], breakdown dict, signal tags list).
    """
    breakdown: Dict[str, float] = {}
    signals: List[str] = []

    alloc = (trial.get("allocation") or "").upper()
    masking = (trial.get("masking") or "").upper()
    model = (trial.get("intervention_model") or "").upper()
    endpoints = trial.get("primary_endpoints") or []
    criteria = trial.get("criteria") or trial.get("eligibility_criteria") or ""

    # 1. Comparator present (from intervention_model or text fallback)
    #    PARALLEL or CROSSOVER implies a comparator arm; SINGLE_GROUP does not
    has_comparator = model in ("PARALLEL", "CROSSOVER", "FACTORIAL")
    if not has_comparator and criteria:
        has_comparator = _has_pattern(criteria, _COMPARATOR_PATTERNS)
    breakdown["comparator"] = _FEATURE_WEIGHTS["comparator"] if has_comparator else 0.0
    if has_comparator:
        signals.append("comparator")

    # 2. Randomization (structured field preferred)
    has_random = alloc == "RANDOMIZED"
    if not has_random and criteria:
        has_random = _has_pattern(criteria, _RANDOMIZATION_PATTERNS)
    breakdown["randomization"] = _FEATURE_WEIGHTS["randomization"] if has_random else 0.0
    if has_random:
        signals.append("randomized")

    # 3. Blinding (structured field preferred)
    has_blind = masking in ("DOUBLE", "SINGLE", "TRIPLE", "QUADRUPLE")
    if not has_blind and criteria:
        has_blind = _has_pattern(criteria, _BLINDING_PATTERNS)
    breakdown["blinding"] = _FEATURE_WEIGHTS["blinding"] if has_blind else 0.0
    if has_blind:
        signals.append("blinded")

    # 4. Endpoint specificity (from primary_endpoints list or text)
    ep_text = " ".join(endpoints) if endpoints else criteria
    ep_spec = _endpoint_specificity(ep_text)
    breakdown["endpoint_spec"] = round(_FEATURE_WEIGHTS["endpoint_spec"] * ep_spec, 4)
    if ep_spec > 0.4:
        signals.append("specific_endpoint")

    # 5. Multi-arm (from intervention_model or text)
    has_multi_arm = model == "FACTORIAL"
    if not has_multi_arm and criteria:
        has_multi_arm = _has_pattern(criteria, _MULTI_ARM_PATTERNS)
    breakdown["multi_arm"] = _FEATURE_WEIGHTS["multi_arm"] if has_multi_arm else 0.0
    if has_multi_arm:
        signals.append("multi_arm")

    # 6. Complexity penalty (from criteria text if available)
    if criteria:
        incl_n = _count_criteria(criteria, "inclusion")
        excl_n = _count_criteria(criteria, "exclusion")
        total_criteria = incl_n + excl_n
        if total_criteria > 25:
            penalty_frac = min((total_criteria - 25) / 25.0, 1.0)
            breakdown["complexity_penalty"] = round(_FEATURE_WEIGHTS["complexity_penalty"] * penalty_frac, 4)
            signals.append("high_complexity")
        else:
            breakdown["complexity_penalty"] = 0.0
    else:
        breakdown["complexity_penalty"] = 0.0

    # Sum and clamp to [0, 1]
    raw = sum(breakdown.values())
    score = max(0.0, min(1.0, raw))

    return score, breakdown, signals
