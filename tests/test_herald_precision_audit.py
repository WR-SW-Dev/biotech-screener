"""Tests for herald_precision_audit.py — Spec 053."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "research"))

from herald_precision_audit import (
    classify_date_type,
    detect_forward_dates,
    detect_high_severity_low_confidence,
    detect_mixed_confidence,
    detect_negation_misclass,
    detect_noise_leakage,
    detect_placeholder_dates,
    detect_pre_ipo_events,
    detect_staleness,
    normalize_confidence,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _ev(
    ticker="AAAA",
    event_date="2026-03-15",
    pit_available_at="2026-03-10",
    event_name="Phase 3 topline readout",
    confidence="HIGH",
    event_type="DATA_READOUT",
    source_family="SEC",
    event_id="abc123",
):
    return {
        "ticker": ticker,
        "event_date": event_date,
        "pit_available_at": pit_available_at,
        "event_name": event_name,
        "confidence": confidence,
        "event_type": event_type,
        "source_family": source_family,
        "event_id": event_id,
    }


def _classified(
    ticker="AAAA",
    headline="Phase 3 topline data announced",
    event_category="clinical",
    severity="high",
    confidence=0.7,
    safety_signal_flag=False,
    event_outcome_guess="hit",
):
    return {
        "ticker": ticker,
        "headline": headline,
        "event_category": event_category,
        "severity": severity,
        "confidence": confidence,
        "safety_signal_flag": safety_signal_flag,
        "event_outcome_guess": event_outcome_guess,
        "needs_review": False,
    }


# ── Placeholder Date Detection ──────────────────────────────────────


class TestPlaceholderDateDetection:
    def test_quarter_start_with_guidance_flagged(self):
        events = [_ev(event_date="2022-07-01", event_name="expects readout Q3 2022")]
        result = detect_placeholder_dates(events)
        assert len(result) == 1
        assert result[0]["ticker"] == "AAAA"

    def test_mid_month_not_flagged(self):
        events = [_ev(event_date="2022-07-15", event_name="expects readout Q3 2022")]
        result = detect_placeholder_dates(events)
        assert len(result) == 0

    def test_quarter_start_without_guidance_not_flagged(self):
        events = [_ev(event_date="2023-01-01", event_name="FDA approval on January 1")]
        result = detect_placeholder_dates(events)
        assert len(result) == 0

    def test_guidance_language_variants(self):
        for word in ["anticipated", "planned", "projected", "estimated", "target"]:
            events = [_ev(event_date="2023-04-01", event_name=f"{word} Phase 2 start")]
            result = detect_placeholder_dates(events)
            assert len(result) == 1, f"Failed for guidance word: {word}"


# ── Forward Date Detection ──────────────────────────────────────────


class TestForwardDateDetection:
    def test_forward_date_flagged(self):
        events = [_ev(event_date="2026-06-01", pit_available_at="2026-03-15")]
        result = detect_forward_dates(events)
        assert len(result) == 1
        assert result[0]["delta_days"] == 78

    def test_same_date_not_flagged(self):
        events = [_ev(event_date="2026-03-15", pit_available_at="2026-03-15")]
        result = detect_forward_dates(events)
        assert len(result) == 0

    def test_pit_after_event_not_flagged(self):
        events = [_ev(event_date="2026-03-01", pit_available_at="2026-03-05")]
        result = detect_forward_dates(events)
        assert len(result) == 0


# ── Ticker Contamination ────────────────────────────────────────────


class TestTickerContamination:
    def test_pre_ipo_flagged(self):
        events = [_ev(ticker="ORKA", event_date="2023-01-01")]
        ipo = {"ORKA": {"first_price_date": "2024-06-15"}}
        result = detect_pre_ipo_events(events, ipo)
        assert len(result) == 1
        assert result[0]["ticker"] == "ORKA"

    def test_post_ipo_not_flagged(self):
        events = [_ev(ticker="ORKA", event_date="2025-01-01")]
        ipo = {"ORKA": {"first_price_date": "2024-06-15"}}
        result = detect_pre_ipo_events(events, ipo)
        assert len(result) == 0

    def test_missing_ipo_not_flagged(self):
        events = [_ev(ticker="NEWCO", event_date="2020-01-01")]
        ipo = {}  # no IPO data
        result = detect_pre_ipo_events(events, ipo)
        assert len(result) == 0  # fail-open


# ── Confidence ───────────────────────────────────────────────────────


class TestConfidenceNormalization:
    def test_categorical_high(self):
        assert normalize_confidence("HIGH") == 0.9

    def test_categorical_med(self):
        assert normalize_confidence("MED") == 0.6

    def test_categorical_low(self):
        assert normalize_confidence("LOW") == 0.3

    def test_numeric_passthrough(self):
        assert normalize_confidence("0.7") == 0.7
        assert normalize_confidence("0.85") == 0.85

    def test_numeric_float(self):
        assert normalize_confidence(0.75) == 0.75

    def test_unparseable_default(self):
        assert normalize_confidence("UNKNOWN") == 0.5


class TestMixedConfidence:
    def test_mixed_batch_detected(self):
        events = [
            _ev(confidence="HIGH"),
            _ev(confidence="0.3", event_id="def456"),
        ]
        result = detect_mixed_confidence(events)
        assert result["has_mixed"] is True
        assert result["n_categorical"] == 1
        assert result["n_numeric"] == 1


# ── Staleness ────────────────────────────────────────────────────────


class TestStalenessDetection:
    def test_past_unresolved_flagged(self):
        events = [_ev(event_date="2025-12-01", event_type="DATA_READOUT")]
        resolved = set()
        result = detect_staleness(events, resolved, "2026-04-04")
        assert len(result) == 1

    def test_future_event_not_flagged(self):
        events = [_ev(event_date="2026-06-01")]
        result = detect_staleness(events, set(), "2026-04-04")
        assert len(result) == 0

    def test_resolved_event_not_flagged(self):
        events = [_ev(ticker="AAAA", event_date="2025-12-01")]
        resolved = {("AAAA", "2025-12-01")}
        result = detect_staleness(events, resolved, "2026-04-04")
        assert len(result) == 0


# ── Herald Classification Audit ──────────────────────────────────────


class TestNoiseLeakage:
    def test_market_research_detected(self):
        records = [
            _classified(
                headline="Black Masterbatches Market Valuation to Surpass US$ 4.8 Billion",
                event_category="regulatory",
            ),
        ]
        result = detect_noise_leakage(records)
        assert len(result) == 1
        assert "market valuation" in result[0]["pattern_matched"].lower()

    def test_cagr_detected(self):
        records = [
            _classified(
                headline="Oncology Market to grow at a CAGR of 8.5% during 2025-2030",
                event_category="clinical",
            ),
        ]
        result = detect_noise_leakage(records)
        assert len(result) == 1

    def test_legitimate_not_flagged(self):
        records = [
            _classified(headline="Phase 3 topline data positive for Drug X"),
        ]
        result = detect_noise_leakage(records)
        assert len(result) == 0


class TestNegationMisclass:
    def test_lifts_clinical_hold(self):
        records = [
            _classified(
                headline="FDA Lifts Clinical Hold on Phase 2 Trial of Drug X",
                event_category="safety",
                safety_signal_flag=True,
                event_outcome_guess="miss",
            ),
        ]
        result = detect_negation_misclass(records)
        assert len(result) == 1
        assert result[0]["should_be_outcome"] == "hit"

    def test_actual_hold_not_flagged(self):
        records = [
            _classified(
                headline="FDA Places Clinical Hold on Phase 2 Trial",
                event_category="safety",
                safety_signal_flag=True,
                event_outcome_guess="miss",
            ),
        ]
        result = detect_negation_misclass(records)
        assert len(result) == 0


class TestHighSeverityLowConfidence:
    def test_high_severity_low_conf_flagged(self):
        records = [_classified(severity="critical", confidence=0.3)]
        result = detect_high_severity_low_confidence(records)
        assert len(result) == 1

    def test_high_severity_high_conf_not_flagged(self):
        records = [_classified(severity="critical", confidence=0.8)]
        result = detect_high_severity_low_confidence(records)
        assert len(result) == 0

    def test_low_severity_low_conf_not_flagged(self):
        records = [_classified(severity="low", confidence=0.3)]
        result = detect_high_severity_low_confidence(records)
        assert len(result) == 0


# ── classify_date_type ───────────────────────────────────────────────


class TestClassifyDateType:
    def test_actual(self):
        # Event happened before filing — actual event
        assert classify_date_type("2026-03-10", "2026-03-15", "Phase 3 readout") == "actual"

    def test_guidance(self):
        assert classify_date_type("2026-06-01", "2026-03-10", "Phase 3 readout") == "guidance"

    def test_placeholder(self):
        assert classify_date_type("2022-07-01", "2022-03-01", "expects readout Q3 2022") == "placeholder"

    def test_placeholder_takes_precedence_over_guidance(self):
        # Quarter-start + guidance language → placeholder even if also forward
        assert classify_date_type("2026-07-01", "2026-03-01", "anticipated Phase 3 start") == "placeholder"
