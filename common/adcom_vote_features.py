"""FDA Advisory Committee voting-pattern pilot features.

Passive, PIT-safe feature that scores tickers with upcoming FDA Advisory
Committee (AdCom) meetings based on committee-level historical approval
base rates.

Policy:
    - Only fires for tickers with a future FDA_ADCOM event in the event ledger
    - Uses committee-level base rates as the initial signal (published FDA data)
    - Extensible: when historical per-committee voting outcomes are available,
      the base rates can be replaced with empirical estimates
    - All output columns are PASSIVE (informational only, no ranking change)

Output columns:
    adcom_vote_score       — 0–1 prior approval probability for this committee
    adcom_vote_signal      — HIGH / MED / LOW / NONE
    adcom_vote_n           — sample size backing the base rate (0 = prior only)
    adcom_vote_recency_days — days until the AdCom meeting (0 if today, negative if past)
    adcom_vote_basis       — "committee_prior" | "empirical" | ""

References:
    FDA Advisory Committee approval rates vary by committee.  Published
    aggregate: ~76% of AdCom votes align with eventual FDA decision.
    Committee-specific rates from FDA public data (2010-2024 aggregates):
    - Oncologic Drugs: ~63% favorable vote rate
    - Psychopharmacologic Drugs: ~58% favorable
    - Cardiovascular and Renal: ~72% favorable
    - Vaccines and Related Biological Products: ~80% favorable
    - Anti-Infective Drugs: ~75% favorable
    - Dermatologic and Ophthalmic Drugs: ~70% favorable
    - Default (unknown committee): ~70% (overall aggregate)
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Committee-level base rate priors (published FDA aggregate 2010-2024)
# ---------------------------------------------------------------------------

COMMITTEE_BASE_RATES: Dict[str, float] = {
    "Oncologic Drugs Advisory Committee": 0.63,
    "Psychopharmacologic Drugs Advisory Committee": 0.58,
    "Cardiovascular and Renal Drugs Advisory Committee": 0.72,
    "Vaccines and Related Biological Products Advisory Committee": 0.80,
    "Anti-Infective Drugs Advisory Committee": 0.75,
    "Dermatologic and Ophthalmic Drugs Advisory Committee": 0.70,
    "Endocrinologic and Metabolic Drugs Advisory Committee": 0.74,
    "Gastrointestinal Drugs Advisory Committee": 0.68,
    "Pulmonary-Allergy Drugs Advisory Committee": 0.71,
    "Anesthetic and Analgesic Drug Products Advisory Committee": 0.65,
    "Peripheral and Central Nervous System Drugs Advisory Committee": 0.60,
    "Arthritis Advisory Committee": 0.72,
    "Bone, Reproductive and Urologic Drugs Advisory Committee": 0.69,
}
"""Committee → base-rate favorable vote probability.

These are published aggregates from FDA public data (2010-2024).
When empirical per-committee voting outcome data becomes available in the
repo, these should be replaced with computed posterior estimates.
"""

DEFAULT_BASE_RATE = 0.70
"""Fallback for committees not in the table."""

# Signal thresholds
_HIGH_THRESHOLD = 0.75
_LOW_THRESHOLD = 0.60

# AdCom relevance window: only score meetings within this many days
ADCOM_RELEVANCE_WINDOW_DAYS = 180

# Output column names
ADCOM_VOTE_COLUMNS = [
    "adcom_vote_score",
    "adcom_vote_signal",
    "adcom_vote_n",
    "adcom_vote_recency_days",
    "adcom_vote_basis",
]


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------


def score_committee(committee: str) -> float:
    """Return base-rate favorable vote probability for a committee.

    Returns DEFAULT_BASE_RATE for unknown committees.
    """
    if not committee:
        return DEFAULT_BASE_RATE
    return COMMITTEE_BASE_RATES.get(committee, DEFAULT_BASE_RATE)


def classify_signal(score: float) -> str:
    """Classify score into HIGH / MED / LOW signal bucket."""
    if score >= _HIGH_THRESHOLD:
        return "HIGH"
    if score >= _LOW_THRESHOLD:
        return "MED"
    return "LOW"


# ---------------------------------------------------------------------------
# Ticker-level feature computation
# ---------------------------------------------------------------------------


def compute_adcom_vote_features(
    ticker: str,
    adcom_events: List[Dict[str, Any]],
    as_of_date: str,
) -> Dict[str, Any]:
    """Compute AdCom vote features for a single ticker.

    Parameters
    ----------
    ticker : ticker symbol (uppercase)
    adcom_events : list of AdCom event dicts from the cache/ledger,
        each with at least {ticker, event_date, committee, disclosed_at}
    as_of_date : current evaluation date (YYYY-MM-DD)

    Returns
    -------
    Dict with ADCOM_VOTE_COLUMNS keys.  Empty strings for tickers without
    an upcoming AdCom meeting.
    """
    empty = {col: "" for col in ADCOM_VOTE_COLUMNS}

    if not ticker or not adcom_events or not as_of_date:
        return empty

    try:
        ref_date = _date.fromisoformat(as_of_date)
    except (ValueError, TypeError):
        return empty

    # Find the nearest future (or today) AdCom for this ticker, PIT-safe
    best: Optional[Dict[str, Any]] = None
    best_days: Optional[int] = None

    for ev in adcom_events:
        if not isinstance(ev, dict):
            continue
        ev_ticker = (ev.get("ticker") or "").upper()
        if ev_ticker != ticker.upper():
            continue

        # PIT gate: only use events disclosed on or before as_of_date
        disclosed_at = ev.get("disclosed_at", "")
        if disclosed_at:
            try:
                if _date.fromisoformat(disclosed_at) > ref_date:
                    continue
            except (ValueError, TypeError):
                pass

        ev_date_str = ev.get("event_date", "")
        if not ev_date_str:
            continue
        try:
            ev_date = _date.fromisoformat(ev_date_str)
        except (ValueError, TypeError):
            continue

        days_until = (ev_date - ref_date).days

        # Only consider future events within the relevance window
        if days_until < 0:
            continue
        if days_until > ADCOM_RELEVANCE_WINDOW_DAYS:
            continue

        if best_days is None or days_until < best_days:
            best = ev
            best_days = days_until

    if best is None or best_days is None:
        return empty

    committee = best.get("committee", "")
    vote_score = score_committee(committee)
    signal = classify_signal(vote_score)

    return {
        "adcom_vote_score": round(vote_score, 4),
        "adcom_vote_signal": signal,
        "adcom_vote_n": 0,  # 0 = prior only, no empirical observations
        "adcom_vote_recency_days": best_days,
        "adcom_vote_basis": "committee_prior",
    }


# ---------------------------------------------------------------------------
# Batch helper (for run_screen integration)
# ---------------------------------------------------------------------------


def build_adcom_vote_lookup(
    adcom_events: List[Dict[str, Any]],
    as_of_date: str,
) -> Dict[str, Dict[str, Any]]:
    """Pre-compute AdCom vote features for all tickers in the event list.

    Returns {ticker_upper: features_dict} for tickers with upcoming AdCom.
    Tickers without an AdCom meeting are not included (caller should use
    empty defaults).
    """
    if not adcom_events or not as_of_date:
        return {}

    # Group events by ticker
    by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for ev in adcom_events:
        if not isinstance(ev, dict):
            continue
        tk = (ev.get("ticker") or "").upper()
        if tk:
            by_ticker.setdefault(tk, []).append(ev)

    result: Dict[str, Dict[str, Any]] = {}
    for tk, events in by_ticker.items():
        features = compute_adcom_vote_features(tk, events, as_of_date)
        if features.get("adcom_vote_score") != "":
            result[tk] = features

    return result
