"""FDA historical outcome priors for the Event EV outcome model.

Provides structured PDUFA approval base rates keyed by:
  - review_type: PRIORITY vs STANDARD
  - therapeutic_area: oncology, neurology, rare_disease, etc.
  - designation: BTD, FT, ODD, RMAT
  - prior_crl: whether this is a resubmission after a Complete Response Letter

Sources:
  - FDA CDER Annual Reports (2015-2024)
  - BIO/QLS Clinical Development Success Rates (2011-2020)
  - Thomas et al., Clinical Drug Investigation, 2016
  - Hay et al., Nature Biotechnology, 2014

Usage:
    from event_ev.fda_outcome_priors import get_pdufa_prior

    prior = get_pdufa_prior(
        review_type="PRIORITY",
        therapeutic_area="oncology",
        designations=["BTD", "ODD"],
        has_prior_crl=False,
    )
    # Returns: {"p_approve": 0.91, "source": "fda_historical", "n_basis": 342}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# PDUFA approval rates by review type (FDA CDER 2015-2024, 10-year average)
# ---------------------------------------------------------------------------

# Standard review: ~75-80% approval rate
# Priority review: ~85-90% approval rate
# These are first-cycle approvals (excluding resubmissions)
_REVIEW_TYPE_RATES = {
    "PRIORITY": {"p_approve": 0.88, "n_basis": 342},
    "STANDARD": {"p_approve": 0.76, "n_basis": 298},
    "UNKNOWN": {"p_approve": 0.82, "n_basis": 640},
}

# ---------------------------------------------------------------------------
# Therapeutic area adjustment (multiplicative, centered at 1.0)
# Source: BIO/QLS 2011-2020, Thomas et al. 2016
# ---------------------------------------------------------------------------

_THERAPEUTIC_AREA_MULTIPLIERS = {
    "oncology": 0.95,  # slightly below average (complex endpoints)
    "hematology": 1.05,  # above average (clear biomarkers)
    "rare_disease": 1.08,  # regulatory tailwinds, smaller trials
    "rare": 1.08,
    "neurology": 0.82,  # hardest area (CNS penetration, endpoint noise)
    "psychiatry": 0.80,
    "cardiovascular": 0.88,
    "infectious_disease": 0.92,
    "immunology": 0.98,
    "ophthalmology": 1.04,
    "dermatology": 1.06,
    "gastroenterology": 0.95,
    "endocrinology": 0.98,
    "respiratory": 0.90,
    "musculoskeletal": 0.92,
}

# ---------------------------------------------------------------------------
# Designation impact on PDUFA approval rate
# Source: FDA CDER reports, academic literature
# ---------------------------------------------------------------------------

# Each designation is an independent positive signal.
# Applied as additive adjustments to log-odds, then converted back.
_DESIGNATION_LOG_ODDS_BOOSTS = {
    "BTD": 0.30,  # Breakthrough: strong signal, ~93% approval
    "FT": 0.10,  # Fast Track: mild positive, ~86% approval
    "ODD": 0.15,  # Orphan Drug: regulatory tailwind, ~88% approval
    "RMAT": 0.25,  # Regenerative Medicine: ~91% approval
    "AA": 0.20,  # Accelerated Approval pathway: ~90% approval
    "PR": 0.20,  # Priority Review (as designation, not review type)
}

# Cap: max total designation boost
_MAX_DESIGNATION_BOOST = 0.45

# ---------------------------------------------------------------------------
# Prior CRL (Complete Response Letter) adjustment
# Source: FDA data, Tufts CSDD
# ---------------------------------------------------------------------------

# Resubmission after CRL has ~55-65% approval (vs ~82% first submission)
_CRL_RESUBMISSION_RATE = 0.60
_CRL_LOG_ODDS_PENALTY = -0.80  # large negative shift

# ---------------------------------------------------------------------------
# AdCom vote adjustment
# Source: FDA advisory committee historical voting patterns
# ---------------------------------------------------------------------------

_ADCOM_VOTE_RATES = {
    # (favorable_votes / total_votes) → P(approve | adcom)
    "unanimous_yes": 0.97,  # 100% favorable
    "strong_yes": 0.93,  # >75% favorable
    "moderate_yes": 0.78,  # 50-75% favorable
    "split": 0.55,  # ~50/50
    "moderate_no": 0.30,  # 25-50% favorable
    "strong_no": 0.12,  # <25% favorable
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

import math


def _sigmoid(x: float) -> float:
    if x > 500:
        return 1.0
    if x < -500:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def get_pdufa_prior(
    review_type: str = "UNKNOWN",
    therapeutic_area: str = "",
    designations: Optional[List[str]] = None,
    has_prior_crl: bool = False,
    adcom_outcome: Optional[str] = None,
) -> Dict[str, Any]:
    """Get enriched PDUFA approval prior.

    Returns dict with:
      - p_approve: float [0, 1]
      - source: str description of prior components
      - n_basis: int (approximate sample size basis)
      - adjustments: dict of applied adjustments
    """
    designations = designations or []
    adjustments = {}

    # Step 1: Base rate by review type
    base = _REVIEW_TYPE_RATES.get(review_type.upper(), _REVIEW_TYPE_RATES["UNKNOWN"])
    p_base = base["p_approve"]
    n_basis = base["n_basis"]
    adjustments["review_type"] = {"type": review_type, "p_base": p_base}

    # Convert to log-odds for additive updates
    log_odds = math.log(p_base / max(1.0 - p_base, 0.001))

    # Step 2: Therapeutic area multiplier
    ta = therapeutic_area.lower().strip() if therapeutic_area else ""
    ta_mult = _THERAPEUTIC_AREA_MULTIPLIERS.get(ta, 1.0)
    if ta_mult != 1.0:
        ta_update = math.log(ta_mult) * 0.7  # damped
        log_odds += ta_update
        adjustments["therapeutic_area"] = {"area": ta, "multiplier": ta_mult, "log_odds_delta": round(ta_update, 4)}

    # Step 3: Designation boosts (capped)
    total_boost = 0.0
    desig_details = []
    for d in designations:
        boost = _DESIGNATION_LOG_ODDS_BOOSTS.get(d.upper(), 0.0)
        if boost > 0:
            total_boost += boost
            desig_details.append({"designation": d, "boost": boost})
    total_boost = min(total_boost, _MAX_DESIGNATION_BOOST)
    if total_boost > 0:
        log_odds += total_boost
        adjustments["designations"] = {"details": desig_details, "total_boost": round(total_boost, 4)}

    # Step 4: Prior CRL penalty
    if has_prior_crl:
        log_odds += _CRL_LOG_ODDS_PENALTY
        adjustments["prior_crl"] = {"penalty": _CRL_LOG_ODDS_PENALTY}

    # Step 5: AdCom override (strongest signal, replaces rather than adjusts)
    if adcom_outcome and adcom_outcome in _ADCOM_VOTE_RATES:
        adcom_p = _ADCOM_VOTE_RATES[adcom_outcome]
        # Blend: 70% AdCom signal + 30% prior (AdCom is very informative)
        p_prior = _sigmoid(log_odds)
        p_blended = 0.70 * adcom_p + 0.30 * p_prior
        log_odds = math.log(p_blended / max(1.0 - p_blended, 0.001))
        adjustments["adcom"] = {"outcome": adcom_outcome, "p_adcom": adcom_p, "blend_weight": 0.70}

    p_approve = _sigmoid(log_odds)

    # Build source description
    source_parts = [f"review={review_type}"]
    if ta:
        source_parts.append(f"area={ta}")
    if designations:
        source_parts.append(f"desig={'+'.join(designations)}")
    if has_prior_crl:
        source_parts.append("CRL_resub")
    if adcom_outcome:
        source_parts.append(f"adcom={adcom_outcome}")

    return {
        "p_approve": round(p_approve, 4),
        "source": "fda_historical(" + ", ".join(source_parts) + ")",
        "n_basis": n_basis,
        "adjustments": adjustments,
    }


def classify_adcom_outcome(favorable_votes: int, total_votes: int) -> str:
    """Classify an advisory committee vote into outcome buckets."""
    if total_votes == 0:
        return "split"
    ratio = favorable_votes / total_votes
    if ratio >= 0.95:
        return "unanimous_yes"
    if ratio >= 0.75:
        return "strong_yes"
    if ratio >= 0.50:
        return "moderate_yes"
    if ratio >= 0.40:
        return "split"
    if ratio >= 0.25:
        return "moderate_no"
    return "strong_no"


def enrich_regulatory_prior(node_event_type: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Convenience wrapper: only enriches PDUFA/FDA_ADCOM events.

    Returns None for non-regulatory events (caller should use default prior).
    """
    if node_event_type in ("PDUFA", "PDUFA_ACTION"):
        return get_pdufa_prior(**kwargs)
    if node_event_type in ("FDA_ADCOM", "ADVISORY_COMMITTEE"):
        # AdCom prior is just the base rate — no review type adjustment
        return get_pdufa_prior(review_type="UNKNOWN", **{k: v for k, v in kwargs.items() if k != "review_type"})
    return None
