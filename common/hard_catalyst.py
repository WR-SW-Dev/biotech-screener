"""Shared hard-catalyst classifier for options research.

Provides a single, deterministic classification of whether a catalyst
event is a true binary/near-binary event (readout, FDA decision, ADCOM)
vs a calendar milestone (PCD completion, study completion).

Used by all options research studies to filter out calendar noise.
"""

from __future__ import annotations

from typing import Any, Dict

# Event types that are always hard catalysts
_HARD_EVENT_TYPES = frozenset(
    {
        "data_readout",
        "topline",
        "interim_analysis",
        "interim_data",
        "top_line",
        "pdufa",
        "fda_pdufa_date",
        "fda_decision",
        "fda_approval",
        "fda_crl",
        "fda_rtf",
        "advisory_committee",
        "fda_adcom",
        "regulatory_decision",
        "approval_decision",
        "crl",
        "ema_decision",
        "ema_agenda",
        "ema_outcome",
        "ema_committee_agenda",
        "ema_committee_outcome",
        "maa_decision",
        "nda_bla",
        "snda",
        "sbla",
    }
)

# Event types that are always soft/calendar
_SOFT_EVENT_TYPES = frozenset(
    {
        "ct_primary_completion",
        "ct_study_completion",
        "ct_results_posted",
        "ct_date_confirmed_actual",
        "ct_status_upgrade",
        "ct_timeline_pullin",
        "ct_timeline_pushout",
        "ct_activity_proxy",
        "enrollment_complete",
        "results_posted",
    }
)

# Sources that indicate hard catalysts regardless of event type
_HARD_SOURCES = frozenset(
    {
        "SEC_8K_FILING",
        "FDA_PDUFA_DATE",
        "COMPANY_GUIDANCE",
    }
)

# Sources that indicate calendar/soft catalysts
_SOFT_SOURCES = frozenset(
    {
        "CTGOV_CALENDAR",
        "CTGOV_PCD_FAR",
    }
)


def classify_hard_catalyst(
    event_type: str,
    source: str = "",
    abs_gap: float = None,
) -> Dict[str, Any]:
    """Classify whether an event is a hard (binary) catalyst.

    Args:
        event_type: Normalized catalyst event type string.
        source: Catalyst source string.
        abs_gap: Absolute gap if outcome is known (for backstop).

    Returns:
        Dict with is_hard_catalyst (bool) and reason (str).
    """
    et = (event_type or "").lower().strip()
    src = (source or "").strip()

    # Rule 1: explicit hard event type
    if et in _HARD_EVENT_TYPES:
        return {"is_hard_catalyst": True, "reason": f"hard_event_type:{et}"}

    # Rule 2: hard source regardless of event type
    if src in _HARD_SOURCES:
        return {"is_hard_catalyst": True, "reason": f"hard_source:{src}"}

    # Rule 3: explicit soft event type
    if et in _SOFT_EVENT_TYPES:
        return {"is_hard_catalyst": False, "reason": f"soft_event_type:{et}"}

    # Rule 4: soft source
    if src in _SOFT_SOURCES:
        return {"is_hard_catalyst": False, "reason": f"soft_source:{src}"}

    # Rule 5: backstop — large abs_gap indicates real event regardless of labeling
    if abs_gap is not None and abs_gap >= 0.10:
        return {"is_hard_catalyst": True, "reason": f"abs_gap_backstop:{abs_gap:.3f}"}

    # Rule 6: keyword scan for borderline types
    hard_keywords = {"readout", "topline", "top-line", "pivotal", "phase 3", "phase3"}
    if any(kw in et for kw in hard_keywords):
        return {"is_hard_catalyst": True, "reason": f"keyword_match:{et}"}

    # Default: unknown → not hard (conservative)
    return {"is_hard_catalyst": False, "reason": "unknown_default"}


def is_hard_catalyst(
    event_type: str,
    source: str = "",
    abs_gap: float = None,
) -> bool:
    """Convenience wrapper returning just the boolean."""
    return classify_hard_catalyst(event_type, source, abs_gap)["is_hard_catalyst"]
