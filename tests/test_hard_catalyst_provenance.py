"""Tests for hard-catalyst classification and nearest-event provenance.

Covers:
  1. classify_hard_catalyst: all 6 rules + edge cases
  2. _find_nearest_catalyst_event: all 4 tiers + hard-source priority
  3. Tie-break behavior at equal dates and equal distances
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.hard_catalyst import classify_hard_catalyst, is_hard_catalyst
from run_screen import _find_nearest_catalyst_event

# =============================================================================
# 1. classify_hard_catalyst — all 6 rules
# =============================================================================


class TestClassifyHardCatalyst:
    # Rule 1: hard event types
    def test_pdufa_is_hard(self):
        r = classify_hard_catalyst("pdufa")
        assert r["is_hard_catalyst"] is True
        assert "hard_event_type" in r["reason"]

    def test_data_readout_is_hard(self):
        assert classify_hard_catalyst("data_readout")["is_hard_catalyst"] is True

    def test_fda_adcom_is_hard(self):
        assert classify_hard_catalyst("fda_adcom")["is_hard_catalyst"] is True

    def test_interim_analysis_is_hard(self):
        assert classify_hard_catalyst("interim_analysis")["is_hard_catalyst"] is True

    def test_ema_decision_is_hard(self):
        assert classify_hard_catalyst("ema_decision")["is_hard_catalyst"] is True

    def test_case_insensitive(self):
        assert classify_hard_catalyst("PDUFA")["is_hard_catalyst"] is True
        assert classify_hard_catalyst("Data_Readout")["is_hard_catalyst"] is True

    # Rule 2: hard sources override event type
    def test_sec_8k_source_makes_any_event_hard(self):
        r = classify_hard_catalyst("unknown_event", "SEC_8K_FILING")
        assert r["is_hard_catalyst"] is True
        assert "hard_source" in r["reason"]

    def test_fda_pdufa_date_source_is_hard(self):
        assert classify_hard_catalyst("", "FDA_PDUFA_DATE")["is_hard_catalyst"] is True

    def test_company_guidance_source_is_hard(self):
        assert classify_hard_catalyst("", "COMPANY_GUIDANCE")["is_hard_catalyst"] is True

    # Rule 3: soft event types
    def test_ct_primary_completion_is_soft(self):
        r = classify_hard_catalyst("ct_primary_completion")
        assert r["is_hard_catalyst"] is False
        assert "soft_event_type" in r["reason"]

    def test_enrollment_complete_is_soft(self):
        assert classify_hard_catalyst("enrollment_complete")["is_hard_catalyst"] is False

    # Rule 4: soft sources
    def test_ctgov_calendar_source_is_soft(self):
        r = classify_hard_catalyst("some_event", "CTGOV_CALENDAR")
        assert r["is_hard_catalyst"] is False
        assert "soft_source" in r["reason"]

    # Rule 5: abs_gap backstop
    def test_large_gap_makes_unknown_hard(self):
        r = classify_hard_catalyst("mystery_event", "", abs_gap=0.15)
        assert r["is_hard_catalyst"] is True
        assert "abs_gap_backstop" in r["reason"]

    def test_small_gap_does_not_trigger_backstop(self):
        r = classify_hard_catalyst("mystery_event", "", abs_gap=0.05)
        assert r["is_hard_catalyst"] is False

    # Rule 6: keyword scan
    def test_keyword_readout_in_type(self):
        r = classify_hard_catalyst("phase3_readout_topline")
        assert r["is_hard_catalyst"] is True
        assert "keyword_match" in r["reason"]

    def test_keyword_pivotal(self):
        assert classify_hard_catalyst("pivotal_data")["is_hard_catalyst"] is True

    # Default: unknown → not hard
    def test_unknown_defaults_to_soft(self):
        r = classify_hard_catalyst("completely_unknown")
        assert r["is_hard_catalyst"] is False
        assert "unknown_default" in r["reason"]

    # Edge cases
    def test_empty_event_type_and_source(self):
        r = classify_hard_catalyst("", "")
        assert r["is_hard_catalyst"] is False

    def test_none_event_type(self):
        r = classify_hard_catalyst(None, "")
        assert r["is_hard_catalyst"] is False

    def test_hard_event_trumps_soft_source(self):
        """Rule 1 (hard event) fires before Rule 4 (soft source)."""
        r = classify_hard_catalyst("pdufa", "CTGOV_CALENDAR")
        assert r["is_hard_catalyst"] is True

    def test_convenience_wrapper(self):
        assert is_hard_catalyst("pdufa") is True
        assert is_hard_catalyst("ct_primary_completion") is False


# =============================================================================
# 2. _find_nearest_catalyst_event — tier priorities
# =============================================================================


def _make_summaries(ticker, integration, events):
    return {ticker: {"integration": integration, "events": events}}


class TestFindNearestCatalystEvent:
    # Tier 1: exact date match
    def test_tier1_exact_match(self):
        events = [
            {"event_date": "2026-04-01", "event_type": "data_readout", "source": "SEC_8K_FILING"},
            {"event_date": "2026-04-10", "event_type": "ct_primary_completion", "source": "CTGOV_CALENDAR"},
        ]
        m3 = _make_summaries("TEST", {"next_catalyst_date": "2026-04-01"}, events)
        result = _find_nearest_catalyst_event(m3, "TEST")
        assert result["event_type"] == "data_readout"

    # Tier 2: fuzzy match prefers closer date
    def test_tier2_fuzzy_closer_date_wins(self):
        events = [
            {"event_date": "2026-04-05", "event_type": "ct_primary_completion", "source": "CTGOV_CALENDAR"},
            {"event_date": "2026-04-15", "event_type": "data_readout", "source": "SEC_8K_FILING"},
        ]
        m3 = _make_summaries("TEST", {"next_catalyst_date": "2026-04-03"}, events)
        result = _find_nearest_catalyst_event(m3, "TEST")
        assert result["event_date"] == "2026-04-05"

    # Tier 2: hard source wins at equal distance
    def test_tier2_hard_beats_soft_at_equal_distance(self):
        events = [
            {"event_date": "2026-04-05", "event_type": "ct_primary_completion", "source": "CTGOV_CALENDAR"},
            {"event_date": "2026-04-15", "event_type": "pdufa", "source": "SEC_8K_FILING"},
        ]
        # Both are 5 days from target
        m3 = _make_summaries("TEST", {"next_catalyst_date": "2026-04-10"}, events)
        result = _find_nearest_catalyst_event(m3, "TEST")
        assert result["event_type"] == "pdufa"
        assert result["source"] == "SEC_8K_FILING"

    # Tier 2: closer soft still beats farther hard
    def test_tier2_closer_soft_beats_farther_hard(self):
        events = [
            {"event_date": "2026-04-09", "event_type": "ct_primary_completion", "source": "CTGOV_CALENDAR"},
            {"event_date": "2026-04-20", "event_type": "pdufa", "source": "SEC_8K_FILING"},
        ]
        m3 = _make_summaries("TEST", {"next_catalyst_date": "2026-04-10"}, events)
        result = _find_nearest_catalyst_event(m3, "TEST")
        # 1 day vs 10 days — closer wins regardless of source
        assert result["event_date"] == "2026-04-09"

    # Tier 0: earliest future event, hard preferred at same date
    def test_tier0_hard_preferred_at_same_date(self):
        events = [
            {"event_date": "2026-04-01", "event_type": "ct_primary_completion", "source": "CTGOV_CALENDAR"},
            {"event_date": "2026-04-01", "event_type": "pdufa", "source": "FDA_PDUFA_DATE"},
        ]
        m3 = _make_summaries("TEST", {}, events)  # no next_catalyst_date
        result = _find_nearest_catalyst_event(m3, "TEST", as_of_date="2026-03-25")
        assert result["event_type"] == "pdufa"

    # Tier 0: earlier date wins over later hard
    def test_tier0_earlier_soft_beats_later_hard(self):
        events = [
            {"event_date": "2026-04-01", "event_type": "ct_primary_completion", "source": "CTGOV_CALENDAR"},
            {"event_date": "2026-04-15", "event_type": "pdufa", "source": "FDA_PDUFA_DATE"},
        ]
        m3 = _make_summaries("TEST", {}, events)
        result = _find_nearest_catalyst_event(m3, "TEST", as_of_date="2026-03-25")
        assert result["event_date"] == "2026-04-01"

    # Tier 0: skips past events
    def test_tier0_skips_past_events(self):
        events = [
            {"event_date": "2026-03-01", "event_type": "data_readout", "source": "SEC_8K_FILING"},
            {"event_date": "2026-04-10", "event_type": "ct_primary_completion", "source": "CTGOV_CALENDAR"},
        ]
        m3 = _make_summaries("TEST", {}, events)
        result = _find_nearest_catalyst_event(m3, "TEST", as_of_date="2026-03-25")
        assert result["event_date"] == "2026-04-10"

    # Tier 3: NCT source UID synthesizes CLINICAL event
    def test_tier3_nct_inference(self):
        m3 = _make_summaries(
            "TEST",
            {"next_catalyst_date": "2026-05-01", "nearest_catalyst_source_uid": "NCT12345678"},
            [],  # no events
        )
        result = _find_nearest_catalyst_event(m3, "TEST")
        assert result["event_type"] == "CT_PRIMARY_COMPLETION"
        assert result["source"] == "CTGOV_CALENDAR"
        assert result["_inferred"] is True

    # No events, no next_date → None
    def test_no_data_returns_none(self):
        m3 = _make_summaries("TEST", {}, [])
        assert _find_nearest_catalyst_event(m3, "TEST") is None

    # Missing ticker → None
    def test_missing_ticker_returns_none(self):
        m3 = _make_summaries("OTHER", {}, [])
        assert _find_nearest_catalyst_event(m3, "TEST") is None

    # None summaries → None
    def test_none_summaries_returns_none(self):
        assert _find_nearest_catalyst_event(None, "TEST") is None

    # Missing event_date in events → skipped
    def test_missing_event_date_skipped(self):
        events = [
            {"event_type": "pdufa", "source": "SEC_8K_FILING"},  # no event_date
            {"event_date": "2026-04-10", "event_type": "ct_primary_completion", "source": "CTGOV_CALENDAR"},
        ]
        m3 = _make_summaries("TEST", {}, events)
        result = _find_nearest_catalyst_event(m3, "TEST", as_of_date="2026-03-25")
        assert result["event_date"] == "2026-04-10"


# =============================================================================
# 3. Source-family change detection
# =============================================================================


class TestSourceFamilyChangeDetection:
    """Verify that source changes are detectable from snapshot comparisons."""

    def test_hard_to_soft_detectable(self):
        """When a ticker flips from hard to soft source, is_hard_catalyst changes."""
        day1 = is_hard_catalyst("pdufa", "SEC_8K_FILING")
        day2 = is_hard_catalyst("ct_primary_completion", "CTGOV_CALENDAR")
        assert day1 is True
        assert day2 is False
        # The flip is detectable
        assert day1 != day2

    def test_same_source_family_stable(self):
        """Same event type + source → same classification."""
        day1 = classify_hard_catalyst("data_readout", "SEC_8K_FILING")
        day2 = classify_hard_catalyst("data_readout", "SEC_8K_FILING")
        assert day1 == day2

    def test_source_upgrade_detectable(self):
        """Soft → hard source upgrade is detectable."""
        before = classify_hard_catalyst("some_event", "CTGOV_CALENDAR")
        after = classify_hard_catalyst("some_event", "SEC_8K_FILING")
        assert before["is_hard_catalyst"] is False
        assert after["is_hard_catalyst"] is True

    def test_event_type_change_without_source_change(self):
        """Event type change under same source changes classification."""
        v1 = is_hard_catalyst("ct_primary_completion", "CTGOV_CALENDAR")
        v2 = is_hard_catalyst("data_readout", "CTGOV_CALENDAR")
        # ct_primary_completion is soft (rule 3), but data_readout is hard (rule 1)
        # Rule 1 fires before rule 4, so data_readout is hard even with soft source
        assert v1 is False
        assert v2 is True
