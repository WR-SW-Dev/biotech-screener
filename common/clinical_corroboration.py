"""Clinical exact-date corroboration evaluator.

Determines whether a clinical catalyst date from a noisy source is
corroborated by an independent cleaner source.  Used to prevent false
precision from SEC 8-K style sources that historically show high slip rates.

Policy:
    - TRUSTED sources (CTGov, COMPANY_GUIDANCE) can stand alone as exact-date
    - NOISY sources (SEC_8K, SEC_MULTI) require corroboration within a window
    - If uncorroborated, precision should be downgraded (DAY → MONTH)
    - REGULATORY family is unaffected (handled by separate PDUFA pipeline)
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Source classification (centralized, easy to tune)
# ---------------------------------------------------------------------------

TRUSTED_CLINICAL_SOURCES = frozenset(
    {
        "CTGOV",
        "CTGOV_CALENDAR",
        "COMPANY_GUIDANCE",
        "CORPORATE_CALENDAR",
    }
)
"""Sources that can produce exact-date clinical catalysts without corroboration."""

NOISY_CLINICAL_SOURCES = frozenset(
    {
        "SEC_8K",
        "SEC_8K_FILING",
        "SEC_MULTI",
        "SEC_MULTI_FORM",
    }
)
"""Sources that require corroboration for exact-date clinical trust."""

CORROBORATION_WINDOW_DAYS = 30
"""Maximum date difference for two sources to count as corroborating."""

DOWNGRADED_PRECISION = "MONTH"
"""Precision assigned to uncorroborated noisy clinical sources."""


# ---------------------------------------------------------------------------
# Corroboration evaluator
# ---------------------------------------------------------------------------


def evaluate_corroboration(
    selected_source: str,
    selected_date: str,
    events: List[Dict[str, Any]],
    family: str,
) -> Dict[str, Any]:
    """Evaluate whether a selected clinical catalyst date is corroborated.

    Parameters
    ----------
    selected_source : source of the nearest catalyst event (e.g., "SEC_8K")
    selected_date : event_date of the selected catalyst (YYYY-MM-DD)
    events : all events for the ticker from Module 3 summary
    family : catalyst family (CLINICAL, REGULATORY, etc.)

    Returns
    -------
    Dict with:
        needs_corroboration: bool
        corroborated: bool
        corroborating_sources: list of source strings
        trust_status: "exact" | "downgraded" | "not_applicable"
        trust_reason: human-readable explanation
    """
    result: Dict[str, Any] = {
        "needs_corroboration": False,
        "corroborated": True,
        "corroborating_sources": [],
        "trust_status": "exact",
        "trust_reason": "",
    }

    # Only applies to CLINICAL family
    if family != "CLINICAL":
        result["trust_status"] = "not_applicable"
        result["trust_reason"] = "non-clinical family"
        return result

    # Trusted sources stand alone
    if selected_source in TRUSTED_CLINICAL_SOURCES:
        result["trust_reason"] = f"{selected_source} is trusted"
        return result

    # Not a noisy source → allow (unknown sources get benefit of the doubt)
    if selected_source not in NOISY_CLINICAL_SOURCES:
        result["trust_reason"] = f"{selected_source} is not classified as noisy"
        return result

    # Noisy source — needs corroboration
    result["needs_corroboration"] = True
    result["corroborated"] = False

    if not selected_date or not events:
        result["trust_status"] = "downgraded"
        result["trust_reason"] = f"{selected_source} is noisy; no events to corroborate"
        return result

    # Check events for corroboration
    corroborating = _find_corroborating_sources(selected_source, selected_date, events)

    if corroborating:
        result["corroborated"] = True
        result["corroborating_sources"] = corroborating
        result["trust_status"] = "exact"
        result["trust_reason"] = f"{selected_source} corroborated by {', '.join(corroborating)}"
    else:
        result["trust_status"] = "downgraded"
        result["trust_reason"] = (
            f"{selected_source} uncorroborated; " f"no trusted source within {CORROBORATION_WINDOW_DAYS}d"
        )

    return result


def _find_corroborating_sources(
    selected_source: str,
    selected_date: str,
    events: List[Dict[str, Any]],
) -> List[str]:
    """Find trusted sources that corroborate the selected date.

    Returns sorted list of corroborating source names.
    """
    try:
        sel_dt = _date.fromisoformat(selected_date)
    except (ValueError, TypeError):
        return []

    seen: set = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        src = event.get("source", "")
        if not src or src == selected_source:
            continue
        if src not in TRUSTED_CLINICAL_SOURCES:
            continue

        evt_date = event.get("event_date", "")
        if not evt_date:
            continue
        try:
            evt_dt = _date.fromisoformat(evt_date)
        except (ValueError, TypeError):
            continue

        if abs((evt_dt - sel_dt).days) <= CORROBORATION_WINDOW_DAYS:
            seen.add(src)

    return sorted(seen)


def should_downgrade_precision(
    source: str,
    family: str,
    corroborated: bool,
) -> bool:
    """Return True if the source/family/corroboration combo warrants downgrade."""
    if family != "CLINICAL":
        return False
    if source not in NOISY_CLINICAL_SOURCES:
        return False
    return not corroborated
