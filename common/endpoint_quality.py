"""Endpoint quality v2 — structured, phase-aware endpoint assessment.

Classifies primary endpoints into interpretable buckets and scores their
clinical decision-usefulness by phase. Replaces the simple keyword-density
proxy with a more structured signal.

PIT safety: all inputs are from ClinicalTrials.gov primary_endpoints field,
posted before trial enrollment.

Endpoint buckets (ordered by clinical strength):
  HARD_CLINICAL: OS, event-free survival, MACE, mortality
  VALIDATED_SURROGATE: PFS, DFS, validated biomarker response
  OBJECTIVE_RESPONSE: ORR, CR, PR, tumor response rates
  SYMPTOM_FUNCTIONAL: QoL, symptom scores, functional scales (EDSS, PANSS, ACR)
  SAFETY_TOLERABILITY: AE, TEAE, DLT, MTD, safety endpoints
  PK_PD_EXPLORATORY: Cmax, AUC, PK parameters, PD markers
  VAGUE_OTHER: unclassifiable or generic wording
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Endpoint classification patterns
# ---------------------------------------------------------------------------

# Order matters: first match wins. More specific patterns first.
_ENDPOINT_BUCKETS: List[Tuple[str, List[str], float]] = [
    # (bucket_name, patterns, base_strength)
    (
        "hard_clinical",
        [
            r"\boverall\s*survival\b",
            r"\b(?:^|\s)os\b(?!\s*\()",
            r"\boverall survival\s*\(os\)",
            r"\bevent[- ]?free\s*survival\b",
            r"\bmajor adverse c(?:ardiac|ardiovascular)\b",
            r"\b(?:all[- ]?cause\s*)?mortality\b",
            r"\bdeath\b",
            r"\bmace\b",
            r"\brelapse[- ]?free\s*survival\b",
        ],
        1.0,
    ),
    (
        "validated_surrogate",
        [
            r"\bprogression[- ]?free\s*survival\b",
            r"\bpfs\b",
            r"\bdisease[- ]?free\s*survival\b",
            r"\bdfs\b",
            r"\bsustained\s*virologic\s*response\b",
            r"\bsvr\b",
            r"\bhba1c\b",
            r"\bglycated\s*hemoglobin\b",
            r"\bestimated\s*glomerular\s*filtration\b",
            r"\begfr\b(?=.*rate)",
            r"\bldl[- ]?c(?:holesterol)?\b",
            r"\bmajor\s*molecular\s*response\b",
            r"\bcomplete\s*cytogenetic\s*response\b",
        ],
        0.85,
    ),
    (
        "objective_response",
        [
            r"\bobjective\s*response\s*rate\b",
            r"\borr\b",
            r"\boverall\s*response\s*rate\b",
            r"\bcomplete\s*response\b",
            r"\bcomplete\s*remission\b",
            r"\bpartial\s*response\b",
            r"\btumor\s*(?:response|reduction|shrinkage)\b",
            r"\bpathological?\s*complete\s*response\b",
            r"\bpcr\b",
            r"\bconfirmed\s*response\b",
        ],
        0.75,
    ),
    (
        "symptom_functional",
        [
            r"\bquality\s*of\s*life\b",
            r"\bqol\b",
            r"\bedss\b",
            r"\bpanss\b",
            r"\bham[- ]?d\b",
            r"\bmadrs\b",
            r"\bacr\s*\d+\b",
            r"\bpasi\b",
            r"\beasi\b",
            r"\bnyha\b",
            r"\b6[- ]?minute\s*walk\b",
            r"\b6mwt\b",
            r"\b6mwd\b",
            r"\bfev1\b",
            r"\bfvc\b",
            r"\bpeak\s*(?:expiratory|flow)\b",
            r"\bvo2\b",
            r"\bpain\s*(?:score|reduction|relief|response)\b",
            r"\bvisual\s*an(?:a)?log(?:ue)?\s*scale\b",
            r"\bvas\b",
            r"\bsymptom\s*(?:improvement|reduction|score|response)\b",
            r"\bfunctional\s*(?:improvement|capacity|outcome)\b",
            r"\bclinical\s*(?:improvement|response|remission|benefit)\b",
        ],
        0.60,
    ),
    (
        "safety_tolerability",
        [
            r"\badverse\s*event\b",
            r"\bteaes?\b",
            r"\baes?\b",
            r"\bdose[- ]?limiting\s*toxic\b",
            r"\bdlt\b",
            r"\bmaximum\s*tolerated\s*dose\b",
            r"\bmtd\b",
            r"\bsafety\b",
            r"\btolerability\b",
            r"\bserious\s*adverse\b",
            r"\bsae\b",
            r"\bincidence\s*of\s*(?:treatment|adverse)\b",
        ],
        0.35,
    ),
    (
        "pk_pd_exploratory",
        [
            r"\bcmax\b",
            r"\bauc\b(?=.*\b(?:0|inf|\d+))",
            r"\bpharmacokinetic\b",
            r"\bpk\b",
            r"\bpharmacodynamic\b",
            r"\bpd\b(?=.*marker)",
            r"\bbioavailability\b",
            r"\bhalf[- ]?life\b",
            r"\btrough\s*(?:level|concentration)\b",
            r"\bimmunogenicity\b",
            r"\bantibod(?:y|ies)\s*(?:formation|response)\b",
        ],
        0.25,
    ),
]

# Compiled pattern cache
_COMPILED_BUCKETS: List[Tuple[str, list, float]] = []


def _get_compiled_buckets():
    global _COMPILED_BUCKETS
    if not _COMPILED_BUCKETS:
        _COMPILED_BUCKETS = [
            (name, [re.compile(p, re.IGNORECASE) for p in patterns], strength)
            for name, patterns, strength in _ENDPOINT_BUCKETS
        ]
    return _COMPILED_BUCKETS


# Phase-aware endpoint strength multipliers
# Controls how much each bucket matters by phase
_PHASE_BUCKET_MULT: Dict[str, Dict[str, float]] = {
    "1": {
        "hard_clinical": 1.0,  # neutral in Ph1 — rare and may be dose-expansion cohort noise
        "validated_surrogate": 0.9,
        "objective_response": 0.85,
        "symptom_functional": 0.8,
        "safety_tolerability": 1.0,  # expected in Ph1 — neutral, not penalized
        "pk_pd_exploratory": 0.9,  # expected in Ph1 — neutral
        "vague_other": 0.5,
    },
    "2": {
        "hard_clinical": 1.3,
        "validated_surrogate": 1.2,
        "objective_response": 1.1,
        "symptom_functional": 1.0,
        "safety_tolerability": 0.6,  # disappointing if STILL safety-only in Ph2
        "pk_pd_exploratory": 0.5,  # very weak for Ph2
        "vague_other": 0.3,
    },
    "3": {
        "hard_clinical": 1.4,  # gold standard for registration
        "validated_surrogate": 1.2,
        "objective_response": 1.0,
        "symptom_functional": 0.9,
        "safety_tolerability": 0.4,  # red flag if primary endpoint is safety in Ph3
        "pk_pd_exploratory": 0.3,  # red flag in Ph3
        "vague_other": 0.2,
    },
}
_DEFAULT_PHASE_MULT = _PHASE_BUCKET_MULT["3"]

# Multi-endpoint penalty: >3 primary endpoints = design complexity concern
_MULTI_EP_THRESHOLD = 3
_MULTI_EP_PENALTY = 0.05  # per extra endpoint above threshold


def classify_endpoint(text: str) -> Tuple[str, float]:
    """Classify a single endpoint string into a bucket.

    Returns (bucket_name, base_strength).
    """
    lower = text.lower().strip()
    if not lower:
        return ("vague_other", 0.15)

    for name, patterns, strength in _get_compiled_buckets():
        if any(p.search(lower) for p in patterns):
            return (name, strength)

    return ("vague_other", 0.15)


def compute_endpoint_quality(
    trial_records: list,
    as_of_date: str,
) -> Dict[str, Dict[str, Any]]:
    """Compute endpoint quality v2 per ticker.

    Selects the best-scoring trial per ticker (phase-priority, then score),
    classifies primary endpoints into interpretable buckets, and applies
    phase-aware strength multipliers.

    Args:
        trial_records: List of trial dicts from trial_records.json.
        as_of_date: ISO date string for PIT filtering.

    Returns:
        {ticker: {
            "endpoint_quality_score": float [0, 1],
            "endpoint_buckets": list of (bucket, strength) for each EP,
            "best_bucket": str,
            "endpoint_signals": str,
            "endpoint_breakdown": dict,
        }}
    """
    from common.protocol_quality import _TRIAL_PHASE_MAP

    try:
        from datetime import date as _date

        as_of = _date.fromisoformat(as_of_date)
    except (ValueError, TypeError):
        return {}

    _PHASE_RANK = {"1": 1, "1_2": 2, "2": 3, "2_3": 4, "3": 5}

    by_ticker: Dict[str, list] = {}
    for t in trial_records:
        tk = (t.get("ticker") or "").upper()
        if tk:
            by_ticker.setdefault(tk, []).append(t)

    result = {}
    for ticker, trials in by_ticker.items():
        best_score = -1.0
        best_phase_rank = 0
        best_out: Dict[str, Any] = {}

        for t in trials:
            collected = t.get("collected_at", "")
            if collected and collected > str(as_of):
                continue
            if (t.get("study_type") or "").upper() != "INTERVENTIONAL":
                continue

            raw_phase = (t.get("phase") or "").upper().replace(" ", "")
            trial_phase = _TRIAL_PHASE_MAP.get(raw_phase, "unknown")
            phase_rank = _PHASE_RANK.get(trial_phase, 0)

            endpoints = t.get("primary_endpoints") or []
            score, out = _score_trial_endpoints(endpoints, trial_phase)

            if (phase_rank, score) > (best_phase_rank, best_score):
                best_score = score
                best_phase_rank = phase_rank
                best_out = out

        if best_out:
            result[ticker] = best_out
        else:
            result[ticker] = {
                "endpoint_quality_score": 0.0,
                "endpoint_buckets": [],
                "best_bucket": "vague_other",
                "endpoint_signals": "",
                "endpoint_breakdown": {},
            }

    return result


def _score_trial_endpoints(
    endpoints: List[str],
    phase: str,
) -> Tuple[float, Dict[str, Any]]:
    """Score a trial's primary endpoints.

    Strategy: classify each endpoint, take the strongest bucket as the
    primary contributor, add a small bonus for secondary strong endpoints,
    apply phase multiplier, and penalize excessive endpoint proliferation.

    Returns (score, output_dict).
    """
    if not endpoints:
        return 0.0, {
            "endpoint_quality_score": 0.0,
            "endpoint_buckets": [],
            "best_bucket": "vague_other",
            "endpoint_signals": "no_endpoints",
            "endpoint_breakdown": {},
        }

    # Classify all endpoints
    classified = []
    for ep in endpoints:
        bucket, strength = classify_endpoint(ep)
        classified.append((bucket, strength, ep[:80]))

    # Sort by strength descending
    classified.sort(key=lambda x: -x[1])

    # Primary: strongest endpoint
    best_bucket, best_strength, best_ep_text = classified[0]

    # Phase multiplier
    phase_mults = _PHASE_BUCKET_MULT.get(phase, _DEFAULT_PHASE_MULT)
    phase_mult = phase_mults.get(best_bucket, 0.5)

    # Secondary bonus: if a second endpoint is also strong
    secondary_bonus = 0.0
    if len(classified) > 1:
        second_bucket, second_strength, _ = classified[1]
        if second_strength >= 0.60:  # at least symptom_functional or better
            secondary_bonus = 0.05
        elif second_strength >= 0.35:  # at least safety
            secondary_bonus = 0.02

    # Multi-endpoint penalty
    multi_penalty = 0.0
    n_endpoints = len(endpoints)
    if n_endpoints > _MULTI_EP_THRESHOLD:
        multi_penalty = min(
            _MULTI_EP_PENALTY * (n_endpoints - _MULTI_EP_THRESHOLD),
            0.15,  # cap penalty
        )

    # Composite
    raw = best_strength * phase_mult + secondary_bonus - multi_penalty
    score = max(0.0, min(1.0, raw))

    # Build signals
    signals = [f"ep_{best_bucket}", f"phase_{phase}"]
    breakdown: Dict[str, Any] = {
        "best_strength": round(best_strength, 4),
        "phase_mult": round(phase_mult, 2),
        "secondary_bonus": round(secondary_bonus, 4),
        "multi_penalty": round(multi_penalty, 4),
        "n_endpoints": n_endpoints,
    }

    if best_bucket == "hard_clinical":
        signals.append("endpoint_hard_clinical_bonus")
    elif best_bucket == "validated_surrogate":
        signals.append("endpoint_validated_surrogate_bonus")
    elif best_bucket in ("pk_pd_exploratory", "vague_other"):
        if phase in ("2", "2_3", "3"):
            signals.append("endpoint_weak_for_phase")
    if best_bucket == "safety_tolerability" and phase in ("2", "2_3", "3"):
        signals.append("endpoint_safety_only_late_phase")
    if multi_penalty > 0:
        signals.append("endpoint_multi_primary_penalty")

    return score, {
        "endpoint_quality_score": round(score, 4),
        "endpoint_buckets": [(b, round(s, 2)) for b, s, _ in classified],
        "best_bucket": best_bucket,
        "endpoint_signals": ",".join(signals),
        "endpoint_breakdown": breakdown,
    }
