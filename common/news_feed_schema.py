"""Grok news feed schema (Spec 044) — dem_grok_news_feed.v1.

Pydantic models for structured event records from the xAI news pipeline.
These records are designed to join cleanly into CRT and DEM snapshots.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class EventCategory(str, Enum):
    MNA = "mna"
    CLINICAL = "clinical"
    REGULATORY = "regulatory"
    FINANCING = "financing"
    LEADERSHIP = "leadership"
    SAFETY = "safety"
    LEGAL = "legal"
    COMPETITOR = "competitor"
    SECTOR = "sector"
    OTHER = "other"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Materiality(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class NewOrStale(str, Enum):
    NEW = "new"
    FOLLOW_ON = "follow_on"
    STALE = "stale"


class OutcomeGuess(str, Enum):
    HIT = "hit"
    MISS = "miss"
    MIXED = "mixed"
    UNCLEAR = "unclear"
    NOT_APPLICABLE = "not_applicable"


class PriceGuess(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"
    UNCLEAR = "unclear"
    NOT_APPLICABLE = "not_applicable"


class SourceKind(str, Enum):
    COMPANY_IR = "company_ir"
    SEC = "sec"
    FDA = "fda"
    EXCHANGE = "exchange"
    X_OFFICIAL = "x_official"
    NEWS = "news"
    SELL_SIDE = "sell_side"
    OTHER = "other"


class ReviewReason(str, Enum):
    LOW_CONFIDENCE = "low_confidence"
    SOURCE_CONFLICT = "source_conflict"
    DUPLICATE_RISK = "duplicate_risk"
    INFORMATIONAL_AMBIGUOUS = "informational_ambiguous"
    OUTCOME_PRICE_DISAGREE = "outcome_price_disagree"
    POSSIBLE_EXOGENOUS = "possible_exogenous"
    TICKER_ALIAS_CONFLICT = "ticker_alias_conflict"


class NewsEvent(BaseModel):
    """A single normalized news event record."""

    event_id: str = Field(description="UUID v4")
    dedupe_key: str = Field(description="SHA256(ticker|category|subtype|date|primary_url)")

    ticker: str = Field(description="Public ticker, uppercase")
    company: str = Field(default="", description="Company name")
    aliases_matched: List[str] = Field(default_factory=list)

    event_time_utc: Optional[str] = Field(default=None, description="ISO-8601 UTC")
    first_seen_utc: str = Field(description="When this feed first captured the event")

    source_type: str = Field(default="web", description="x or web")
    primary_source_kind: SourceKind = Field(default=SourceKind.OTHER)
    primary_source_publisher: str = Field(default="")
    primary_source_url: str = Field(default="")
    source_urls: List[str] = Field(default_factory=list)
    source_count: int = Field(default=1)

    event_category: EventCategory
    event_subtype: str = Field(default="", description="e.g. phase3_topline, crl, definitive_acquisition")
    severity: Severity
    materiality: Materiality = Field(default=Materiality.MEDIUM)
    new_or_stale: NewOrStale

    informational_only: bool = Field(default=False)
    informational_reason: str = Field(default="")

    event_outcome_guess: OutcomeGuess = Field(default=OutcomeGuess.UNCLEAR)
    event_outcome_reason: str = Field(default="")
    price_direction_guess: PriceGuess = Field(default=PriceGuess.UNCLEAR)
    price_direction_reason: str = Field(default="")

    exogenous_to_primary_catalyst: bool = Field(default=False)
    exogenous_reason: str = Field(default="")

    catalyst_family_candidate: str = Field(default="")
    catalyst_type_candidate: str = Field(default="")
    hard_catalyst_guess: bool = Field(default=False)
    catalyst_window_guess_days: Optional[int] = Field(default=None)

    competitor_impact_flag: bool = Field(default=False)
    sector_regime_flag: bool = Field(default=False)
    safety_signal_flag: bool = Field(default=False)
    financing_signal_flag: bool = Field(default=False)
    mna_signal_flag: bool = Field(default=False)

    thesis_change_flag: bool = Field(default=False)
    thesis_change_direction: str = Field(default="")
    why_it_matters: str = Field(default="")
    operator_summary: str = Field(default="")

    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    needs_review: bool = Field(default=False)
    review_reason_codes: List[ReviewReason] = Field(default_factory=list)

    # Ticker-collision provenance (added 2026-04-18 alongside CH-4 + P2 in
    # tools/classify_press_releases.py). `ticker_collision_flag=True` marks
    # items whose headline appears to be about a company other than the
    # tagged ticker. `collision_severity`:
    #   - "none": not a collision
    #   - "soft": CH-4 caught it via tightened biotech-rescue rule; keep
    #             visible in escalation pool for review, do not calibrate
    #   - "hard": no biotech signal at all; silent drop
    # Both fields default backward-compatibly — records produced before these
    # fields were added decode to `False` / `"none"` and preserve prior behavior.
    ticker_collision_flag: bool = Field(default=False)
    collision_severity: str = Field(default="none")

    def is_clean_for_calibration(self) -> bool:
        """Can this event be used for CRT/DEM calibration?"""
        return (
            not self.informational_only
            and not self.exogenous_to_primary_catalyst
            and not self.needs_review
            and not self.ticker_collision_flag
        )

    def is_official_source(self) -> bool:
        return self.primary_source_kind in (
            SourceKind.COMPANY_IR,
            SourceKind.SEC,
            SourceKind.FDA,
            SourceKind.EXCHANGE,
            SourceKind.X_OFFICIAL,
        )

    def severity_num(self) -> float:
        return {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}[self.severity.value]

    def outcome_num(self) -> float:
        return {"hit": 1.0, "miss": -1.0, "mixed": 0.0, "unclear": 0.0, "not_applicable": 0.0}[
            self.event_outcome_guess.value
        ]

    def price_num(self) -> float:
        return {"up": 1.0, "down": -1.0, "flat": 0.0, "unclear": 0.0, "not_applicable": 0.0}[
            self.price_direction_guess.value
        ]

    def confidence_weighted_outcome(self) -> float:
        return self.severity_num() * self.outcome_num() * self.confidence

    def confidence_weighted_price(self) -> float:
        return self.severity_num() * self.price_num() * self.confidence


class NewsFeedBatch(BaseModel):
    """A batch of events from one Grok query run."""

    schema_version: str = Field(default="dem_grok_news_feed.v1")
    run_id: str = Field(description="UUID v4")
    generated_at_utc: str
    as_of_utc: str
    lookback_minutes: int
    watchlist_name: str = Field(default="dem_top60_and_watchlist")
    query_version: str = Field(default="grok_news_prompt_v1")
    events: List[NewsEvent] = Field(default_factory=list)
