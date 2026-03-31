"""Ticker-level rolling features from normalized Grok news feed (Spec 044).

Phase 1: operator/dashboard features only. No DEM integration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from common.news_feed_schema import NewsEvent


def _parse_utc(s: str) -> datetime:
    """Parse ISO-8601 UTC string to datetime."""
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def compute_ticker_features(
    events: List[NewsEvent],
    ticker: str,
    as_of_utc: datetime,
) -> Dict[str, Any]:
    """Compute Phase 1 rolling features for one ticker.

    Returns dict of feature name -> value.
    """
    # Filter to this ticker's events
    tk_events = [e for e in events if e.ticker.upper() == ticker.upper()]

    def in_window(e: NewsEvent, days: int) -> bool:
        et = _parse_utc(e.event_time_utc or e.first_seen_utc)
        return (as_of_utc - et).total_seconds() <= days * 86400

    # Events by window
    e7 = [e for e in tk_events if in_window(e, 7)]
    e30 = [e for e in tk_events if in_window(e, 30)]
    e90 = [e for e in tk_events if in_window(e, 90)]

    # Phase 1 features
    material_7d = [e for e in e7 if not e.informational_only]
    clean_30d = [e for e in e30 if e.is_clean_for_calibration()]

    return {
        "news_material_event_count_7d": len(material_7d),
        "news_critical_event_flag_7d": int(any(e.severity.value == "critical" for e in material_7d)),
        "news_exogenous_event_flag_30d": int(any(e.exogenous_to_primary_catalyst for e in e30)),
        "news_safety_signal_flag_90d": int(any(e.safety_signal_flag for e in e90)),
        "news_conf_weighted_outcome_30d": round(sum(e.confidence_weighted_outcome() for e in clean_30d), 4),
        # Operator context (not for DEM training yet)
        "news_mna_interest_flag_90d": int(any(e.mna_signal_flag for e in e90)),
        "news_financing_stress_flag_30d": int(any(e.financing_signal_flag for e in e30)),
        "news_leadership_disruption_flag_90d": int(
            any(e.event_category.value == "leadership" and e.severity.value in ("critical", "high") for e in e90)
        ),
    }


def compute_competitor_features(
    events: List[NewsEvent],
    ticker: str,
    peer_tickers: List[str],
    as_of_utc: datetime,
) -> Dict[str, Any]:
    """Compute competitor/industry context features.

    Args:
        events: All events (not filtered to ticker).
        ticker: The target ticker.
        peer_tickers: Direct peers in the same indication/mechanism.
        as_of_utc: Snapshot time.
    """
    peer_set = {t.upper() for t in peer_tickers} - {ticker.upper()}

    def in_window(e: NewsEvent, days: int) -> bool:
        et = _parse_utc(e.event_time_utc or e.first_seen_utc)
        return (as_of_utc - et).total_seconds() <= days * 86400

    peer_events_30d = [
        e for e in events if e.ticker.upper() in peer_set and in_window(e, 30) and not e.informational_only
    ]
    peer_events_90d = [
        e for e in events if e.ticker.upper() in peer_set and in_window(e, 90) and not e.informational_only
    ]

    sector_events_30d = [e for e in events if e.event_category.value == "sector" and in_window(e, 30)]

    return {
        "competitor_positive_readout_count_30d": sum(
            1 for e in peer_events_30d if e.event_outcome_guess.value == "hit"
        ),
        "competitor_negative_readout_count_30d": sum(
            1 for e in peer_events_30d if e.event_outcome_guess.value == "miss"
        ),
        "competitor_safety_signal_count_90d": sum(1 for e in peer_events_90d if e.safety_signal_flag),
        "sector_regulatory_risk_flag_30d": int(
            any(
                e.severity.value in ("critical", "high") and e.event_category.value in ("regulatory", "safety")
                for e in sector_events_30d
            )
        ),
        "sector_financing_window_score_30d": sum(1 for e in sector_events_30d if e.financing_signal_flag),
    }


def compute_all_ticker_features(
    events: List[NewsEvent],
    tickers: List[str],
    as_of_utc: datetime,
) -> Dict[str, Dict[str, Any]]:
    """Compute features for all tickers. Returns {ticker: {feature: value}}."""
    result = {}
    for ticker in tickers:
        result[ticker] = compute_ticker_features(events, ticker, as_of_utc)
    return result
