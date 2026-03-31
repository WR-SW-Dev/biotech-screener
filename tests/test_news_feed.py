"""Tests for Spec 044 — Grok news feed schema + feature builder."""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.news_feed_features import compute_competitor_features, compute_ticker_features
from common.news_feed_schema import (
    EventCategory,
    NewOrStale,
    NewsEvent,
    NewsFeedBatch,
    OutcomeGuess,
    PriceGuess,
    Severity,
    SourceKind,
)


def _make_event(**overrides) -> NewsEvent:
    defaults = dict(
        event_id="test-001",
        dedupe_key="abc123",
        ticker="SION",
        first_seen_utc="2026-03-31T12:00:00Z",
        event_category=EventCategory.CLINICAL,
        severity=Severity.HIGH,
        new_or_stale=NewOrStale.NEW,
        confidence=0.8,
    )
    defaults.update(overrides)
    return NewsEvent(**defaults)


class TestNewsEventSchema:
    def test_valid_event(self):
        e = _make_event()
        assert e.ticker == "SION"
        assert e.event_category == EventCategory.CLINICAL

    def test_clean_for_calibration(self):
        e = _make_event()
        assert e.is_clean_for_calibration()

    def test_informational_not_clean(self):
        e = _make_event(informational_only=True)
        assert not e.is_clean_for_calibration()

    def test_exogenous_not_clean(self):
        e = _make_event(exogenous_to_primary_catalyst=True)
        assert not e.is_clean_for_calibration()

    def test_needs_review_not_clean(self):
        e = _make_event(needs_review=True)
        assert not e.is_clean_for_calibration()

    def test_official_source(self):
        e = _make_event(primary_source_kind=SourceKind.COMPANY_IR)
        assert e.is_official_source()

    def test_non_official_source(self):
        e = _make_event(primary_source_kind=SourceKind.NEWS)
        assert not e.is_official_source()

    def test_severity_num(self):
        assert _make_event(severity=Severity.CRITICAL).severity_num() == 3.0
        assert _make_event(severity=Severity.LOW).severity_num() == 0.5

    def test_outcome_num(self):
        assert _make_event(event_outcome_guess=OutcomeGuess.HIT).outcome_num() == 1.0
        assert _make_event(event_outcome_guess=OutcomeGuess.MISS).outcome_num() == -1.0

    def test_confidence_weighted_outcome(self):
        e = _make_event(severity=Severity.HIGH, event_outcome_guess=OutcomeGuess.HIT, confidence=0.9)
        assert e.confidence_weighted_outcome() == 2.0 * 1.0 * 0.9

    def test_outcome_separate_from_price(self):
        e = _make_event(
            event_outcome_guess=OutcomeGuess.MISS,
            price_direction_guess=PriceGuess.UP,
        )
        assert e.outcome_num() == -1.0
        assert e.price_num() == 1.0


class TestNewsFeedBatch:
    def test_empty_batch(self):
        b = NewsFeedBatch(
            run_id="test",
            generated_at_utc="2026-03-31T12:00:00Z",
            as_of_utc="2026-03-31T12:00:00Z",
            lookback_minutes=30,
        )
        assert len(b.events) == 0
        assert b.schema_version == "dem_grok_news_feed.v1"

    def test_batch_with_events(self):
        e = _make_event()
        b = NewsFeedBatch(
            run_id="test",
            generated_at_utc="2026-03-31T12:00:00Z",
            as_of_utc="2026-03-31T12:00:00Z",
            lookback_minutes=30,
            events=[e],
        )
        assert len(b.events) == 1


class TestTickerFeatures:
    def test_empty_events(self):
        f = compute_ticker_features([], "SION", datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["news_material_event_count_7d"] == 0
        assert f["news_critical_event_flag_7d"] == 0

    def test_material_count(self):
        events = [
            _make_event(ticker="SION", event_time_utc="2026-03-30T12:00:00Z"),
            _make_event(ticker="SION", event_time_utc="2026-03-29T12:00:00Z"),
            _make_event(ticker="OTHER", event_time_utc="2026-03-30T12:00:00Z"),
        ]
        f = compute_ticker_features(events, "SION", datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["news_material_event_count_7d"] == 2

    def test_critical_flag(self):
        events = [_make_event(ticker="SION", severity=Severity.CRITICAL, event_time_utc="2026-03-30T12:00:00Z")]
        f = compute_ticker_features(events, "SION", datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["news_critical_event_flag_7d"] == 1

    def test_no_critical(self):
        events = [_make_event(ticker="SION", severity=Severity.MEDIUM, event_time_utc="2026-03-30T12:00:00Z")]
        f = compute_ticker_features(events, "SION", datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["news_critical_event_flag_7d"] == 0

    def test_exogenous_flag(self):
        events = [_make_event(ticker="BIIB", exogenous_to_primary_catalyst=True, event_time_utc="2026-03-31T12:00:00Z")]
        f = compute_ticker_features(events, "BIIB", datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["news_exogenous_event_flag_30d"] == 1

    def test_safety_signal_flag(self):
        events = [_make_event(ticker="MAZE", safety_signal_flag=True, event_time_utc="2026-03-25T12:00:00Z")]
        f = compute_ticker_features(events, "MAZE", datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["news_safety_signal_flag_90d"] == 1

    def test_informational_excluded_from_material(self):
        events = [_make_event(ticker="SION", informational_only=True, event_time_utc="2026-03-30T12:00:00Z")]
        f = compute_ticker_features(events, "SION", datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["news_material_event_count_7d"] == 0

    def test_old_events_excluded_from_7d(self):
        events = [_make_event(ticker="SION", event_time_utc="2026-03-20T12:00:00Z")]
        f = compute_ticker_features(events, "SION", datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["news_material_event_count_7d"] == 0


class TestCompetitorFeatures:
    def test_peer_positive(self):
        events = [
            _make_event(ticker="PEER1", event_outcome_guess=OutcomeGuess.HIT, event_time_utc="2026-03-30T12:00:00Z"),
        ]
        f = compute_competitor_features(events, "SION", ["PEER1", "PEER2"], datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["competitor_positive_readout_count_30d"] == 1

    def test_peer_negative(self):
        events = [
            _make_event(ticker="PEER1", event_outcome_guess=OutcomeGuess.MISS, event_time_utc="2026-03-30T12:00:00Z"),
        ]
        f = compute_competitor_features(events, "SION", ["PEER1"], datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["competitor_negative_readout_count_30d"] == 1

    def test_self_excluded_from_peers(self):
        events = [
            _make_event(ticker="SION", event_outcome_guess=OutcomeGuess.HIT, event_time_utc="2026-03-30T12:00:00Z"),
        ]
        f = compute_competitor_features(events, "SION", ["SION", "PEER1"], datetime(2026, 3, 31, tzinfo=timezone.utc))
        assert f["competitor_positive_readout_count_30d"] == 0
