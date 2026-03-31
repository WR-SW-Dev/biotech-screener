#!/usr/bin/env python3
"""Catalyst Resolution Tracker (CRT) — Spec 042.

Closes the prediction -> resolution -> calibration loop by detecting
when binary catalysts resolve and recording structured outcomes.

Phase 1: schemas, watchlist construction, deterministic outcome classification.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

SCHEMA_VERSION = "1.0.0"

OUTCOMES = frozenset({"HIT", "MISS", "MIXED", "DELAYED", "WITHDRAWN", "NEEDS_REVIEW"})

CATALYST_TYPES = frozenset(
    {
        "PDUFA_ACTION",
        "PHASE_3_READOUT",
        "PHASE_2_READOUT",
        "PHASE_1_DATA",
        "ADVISORY_COMMITTEE",
        "NDA_BLA_FILING",
        "REGULATORY_DESIGNATION",
        "CORPORATE_UPDATE",
        "EARNINGS",
        "CONFERENCE_PRESENTATION",
    }
)

SOURCE_TYPES = frozenset({"SEC_8K", "PRESS_RELEASE", "CTGOV_STATUS", "FDA_ACTION", "MANUAL"})

# Detection window: T-30 to T+7 (look back 30 days for past-due catalysts,
# look ahead 7 days for early announcements)
WINDOW_LOOKBACK_DAYS = 30
WINDOW_LOOKAHEAD_DAYS = 7

# Keyword lists for deterministic outcome classification
_HIT_KEYWORDS = [
    "met primary endpoint",
    "positive topline",
    "statistically significant",
    "achieved primary",
    "met the primary",
    "demonstrated superiority",
    "approved",
]

_MISS_KEYWORDS = [
    "did not meet",
    "failed to achieve",
    "not statistically significant",
    "discontinued",
    "discontinuation",
    "terminated",
    "complete response letter",
    "did not achieve",
    "negative topline",
]


@dataclass
class ResolutionRecord:
    """A single catalyst resolution record."""

    ticker: str
    catalyst_date: str
    catalyst_type: str
    resolution_date: Optional[str] = None
    outcome: str = "NEEDS_REVIEW"
    outcome_detail: str = ""
    source_type: str = "MANUAL"
    source_id: str = ""
    catalyst_description: str = ""
    prediction_snapshot_date: Optional[str] = None
    prediction_dem_rank: Optional[int] = None
    prediction_composite_score: Optional[float] = None
    price_t_minus_1: Optional[float] = None
    price_t_0: Optional[float] = None
    price_t_plus_5: Optional[float] = None
    days_from_expected: Optional[int] = None
    as_of_date: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"Invalid outcome: {self.outcome!r}. Must be one of {OUTCOMES}")
        if self.catalyst_type not in CATALYST_TYPES:
            raise ValueError(f"Invalid catalyst_type: {self.catalyst_type!r}. Must be one of {CATALYST_TYPES}")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"Invalid source_type: {self.source_type!r}. Must be one of {SOURCE_TYPES}")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        d["schema_version"] = self.schema_version
        d["ticker"] = self.ticker
        d["catalyst_date"] = self.catalyst_date
        d["catalyst_type"] = self.catalyst_type
        d["catalyst_description"] = self.catalyst_description
        d["resolution_date"] = self.resolution_date
        d["outcome"] = self.outcome
        d["outcome_detail"] = self.outcome_detail
        d["source_type"] = self.source_type
        d["source_id"] = self.source_id
        d["prediction_snapshot_date"] = self.prediction_snapshot_date
        d["prediction_dem_rank"] = self.prediction_dem_rank
        d["prediction_composite_score"] = self.prediction_composite_score
        d["price_t_minus_1"] = self.price_t_minus_1
        d["price_t_0"] = self.price_t_0
        d["price_t_plus_5"] = self.price_t_plus_5
        d["days_from_expected"] = self.days_from_expected
        d["as_of_date"] = self.as_of_date
        return d


def compute_record_hash(record: ResolutionRecord) -> str:
    """Compute deterministic SHA256 hash of a resolution record."""
    d = record.to_dict()
    # Remove any existing hash field to avoid circularity
    d.pop("record_hash", None)
    canonical = json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_watchlist(
    catalyst_events: List[Dict[str, Any]],
    as_of_date: date,
    existing_resolutions: Set[Tuple[str, str]],
) -> List[Dict[str, Any]]:
    """Select catalysts in the resolution detection window.

    Window: as_of_date - LOOKBACK to as_of_date + LOOKAHEAD.
    Excludes catalysts already resolved.

    Args:
        catalyst_events: List of dicts with ticker, catalyst_date (str), catalyst_type.
        as_of_date: Current snapshot date.
        existing_resolutions: Set of (ticker, catalyst_date) already resolved.

    Returns:
        Filtered list of events in the detection window.
    """
    window_start = as_of_date - timedelta(days=WINDOW_LOOKBACK_DAYS)
    window_end = as_of_date + timedelta(days=WINDOW_LOOKAHEAD_DAYS)

    result = []
    for event in catalyst_events:
        ticker = event.get("ticker", "")
        cat_date_str = event.get("catalyst_date", "")
        if not ticker or not cat_date_str:
            continue

        try:
            cat_date = date.fromisoformat(cat_date_str[:10])
        except ValueError:
            continue

        if cat_date < window_start or cat_date > window_end:
            continue

        if (ticker, cat_date_str[:10]) in existing_resolutions:
            continue

        result.append(event)

    return result


def classify_outcome(
    catalyst_type: str,
    *,
    headline: str = "",
    fda_action: Optional[str] = None,
    ctgov_status_from: Optional[str] = None,
    ctgov_status_to: Optional[str] = None,
) -> str:
    """Deterministic rules-based outcome classification.

    CRITICAL: This is keyword matching, not LLM inference. If keywords
    are ambiguous, returns NEEDS_REVIEW for human classification.
    """
    # FDA action (PDUFA)
    if catalyst_type == "PDUFA_ACTION" and fda_action:
        fda_upper = fda_action.upper()
        if fda_upper == "APPROVED":
            return "HIT"
        if fda_upper in ("CRL", "COMPLETE_RESPONSE_LETTER"):
            return "MISS"

    # CT.gov status transitions
    if ctgov_status_to:
        status_to = ctgov_status_to.upper()
        if status_to in ("TERMINATED", "SUSPENDED"):
            return "MISS"
        if status_to == "WITHDRAWN":
            return "MISS"
        # COMPLETED alone is ambiguous — need headline to determine HIT/MISS
        if status_to == "COMPLETED" and not headline:
            return "NEEDS_REVIEW"

    # Headline keyword matching
    if headline:
        headline_lower = headline.lower()

        for kw in _HIT_KEYWORDS:
            if kw in headline_lower:
                return "HIT"

        for kw in _MISS_KEYWORDS:
            if kw in headline_lower:
                return "MISS"

    # FDA action without known result
    if catalyst_type == "PDUFA_ACTION" and fda_action is None:
        return "NEEDS_REVIEW"

    return "NEEDS_REVIEW"
