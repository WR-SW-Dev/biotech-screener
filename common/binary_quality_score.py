"""Binary Quality Score — rank "good binaries" above coin-flips within buckets.

A simple, deterministic overlay that scores binary names by the *quality*
of their upcoming catalyst, not just the timing.  Applied only within
binary buckets (0–30, 31–90, 91–180) as a tiebreak.

Components (all additive, 0–1 scale each):
  1. Family weight:   REGULATORY > CLINICAL > OTHER
  2. Phase weight:    Phase 3 > Phase 2 > Phase 1
  3. Source weight:    SEC 8-K confirmed > CTgov calendar > unknown
  4. Design quality:   Reuses clinical_calendar_alpha design_quality_score

Final score = weighted sum, capped [0, 1].

Usage:
    from common.binary_quality_score import compute_binary_quality_score
    score = compute_binary_quality_score(row)
"""

from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# Component weights (sum to 1.0)
# ---------------------------------------------------------------------------

W_FAMILY = 0.35
W_PHASE = 0.30
W_SOURCE = 0.20
W_DESIGN = 0.15

# ---------------------------------------------------------------------------
# Family score: how "binary" is the event type?
# ---------------------------------------------------------------------------

_FAMILY_SCORE = {
    "REGULATORY": 1.0,  # Hard-dated FDA/EMA decisions
    "CLINICAL": 0.6,  # Trial readouts — dates can slip
    "SAFETY": 0.0,  # Negative shocks, not positioning events
}

# Granular event_type overrides (within CLINICAL, some are higher quality)
_EVENT_TYPE_BONUS: Dict[str, float] = {
    # Regulatory — already at 1.0 via family, but if event_type arrives
    # without family classification, these provide a fallback.
    "PDUFA": 1.0,
    "FDA_PDUFA_DATE": 1.0,
    "FDA_ADCOM": 0.95,
    "EMA_AGENDA": 0.85,
    "EMA_OUTCOME": 0.85,
    # Clinical — company-confirmed readouts are better than CTgov estimates
    "DATA_READOUT": 0.75,
    "CT_DATE_CONFIRMED_ACTUAL": 0.70,
    "CT_PRIMARY_COMPLETION": 0.55,
    "CT_STUDY_COMPLETION": 0.45,
}


def _family_score(family: str, event_type: str) -> float:
    """Score the catalyst family/event type on a 0–1 scale."""
    # Try granular event_type override first
    if event_type in _EVENT_TYPE_BONUS:
        return _EVENT_TYPE_BONUS[event_type]
    return _FAMILY_SCORE.get(family, 0.3)


# ---------------------------------------------------------------------------
# Phase score: later stage = bigger potential move, more data
# ---------------------------------------------------------------------------

_PHASE_SCORE = {
    3.0: 1.0,
    2.5: 0.75,  # Phase 2/3
    2.0: 0.50,
    1.5: 0.30,  # Phase 1/2
    1.0: 0.15,
    0.5: 0.05,  # Early Phase 1
}


def _phase_score(phase_str: str) -> float:
    """Score the lead program phase on a 0–1 scale."""
    if not phase_str:
        return 0.3  # unknown → neutral
    try:
        phase = float(phase_str)
    except (ValueError, TypeError):
        return 0.3
    return _PHASE_SCORE.get(phase, 0.3)


# ---------------------------------------------------------------------------
# Source score: how reliable is the date?
# ---------------------------------------------------------------------------

_SOURCE_SCORE = {
    "SEC_8K_FILING": 1.0,  # Company-confirmed in SEC filing
    "PDUFA_MANUAL": 0.95,  # Manually curated PDUFA dates
    "FDA_ADCOM": 0.90,  # Federal Register / official calendar
    "FDA_FEDREG": 0.90,
    "EMA_AGENDA": 0.85,
    "CTGOV_CALENDAR": 0.60,  # CTgov trial dates (can slip)
    "CTGOV_PCD_FAR": 0.40,  # Far-future CTgov PCD (very uncertain)
}


def _source_score(source: str) -> float:
    """Score the catalyst source on a 0–1 scale."""
    if not source:
        return 0.3
    return _SOURCE_SCORE.get(source, 0.5)


# ---------------------------------------------------------------------------
# Design quality: reuse clinical_calendar_alpha score
# ---------------------------------------------------------------------------


def _design_score(design_quality: str) -> float:
    """Normalize design_quality_score (0–1 already) with fallback."""
    if not design_quality:
        return 0.3  # unknown → neutral
    try:
        v = float(design_quality)
        return max(0.0, min(1.0, v))
    except (ValueError, TypeError):
        return 0.3


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------


def compute_binary_quality_score(
    row: Dict[str, Any],
    *,
    w_family: float = W_FAMILY,
    w_phase: float = W_PHASE,
    w_source: float = W_SOURCE,
    w_design: float = W_DESIGN,
) -> float:
    """Compute binary quality score for a single position row.

    Parameters
    ----------
    row : dict
        Rankings row with keys: catalyst_family, catalyst_event_type,
        catalyst_source, lead_program_phase, design_quality_score.
    w_family, w_phase, w_source, w_design : float
        Component weights (should sum to 1.0).

    Returns
    -------
    float
        Score in [0, 1] range.  Higher = better quality binary.
    """
    family = str(row.get("catalyst_family", "") or "")
    event_type = str(row.get("catalyst_event_type", "") or "")
    source = str(row.get("catalyst_source", "") or "")
    phase = str(row.get("lead_program_phase", "") or "")
    design = str(row.get("design_quality_score", "") or "")

    score = (
        w_family * _family_score(family, event_type)
        + w_phase * _phase_score(phase)
        + w_source * _source_score(source)
        + w_design * _design_score(design)
    )
    return round(max(0.0, min(1.0, score)), 4)


def score_binary_positions(
    rows: list[Dict[str, Any]],
    *,
    only_binary: bool = True,
) -> list[Dict[str, Any]]:
    """Score a list of position rows, adding binary_quality_score field.

    Parameters
    ----------
    rows : list of dict
        Rankings rows.
    only_binary : bool
        If True, only score rows with catalyst_mode == "specific_days".
        Non-binary rows get score 0.0.

    Returns
    -------
    list of dict
        Same rows with ``binary_quality_score`` added.
    """
    for row in rows:
        if only_binary and row.get("catalyst_mode") != "specific_days":
            row["binary_quality_score"] = 0.0
        else:
            row["binary_quality_score"] = compute_binary_quality_score(row)
    return rows
