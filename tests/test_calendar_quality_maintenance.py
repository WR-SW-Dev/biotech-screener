"""Tests for regulatory calendar quality maintenance system.

Covers:
  - select_quality_entries pruning rules
  - CalendarPolicy configuration
  - Priority scoring determinism
  - Coverage target enforcement
  - Gate logic updates (WARN-only, coverage band)
  - Enhanced telemetry fields
  - Confidence A/B filter helper
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.regulatory_calendar import (
    CalendarPolicy,
    _compute_entry_priority,
    get_calendar_telemetry,
    select_quality_entries,
)
from tools.run_daily_production import GateConfig, check_regulatory_calendar

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    ticker="ACME",
    pdufa_date="2026-06-01",
    confidence="HIGH",
    source="COMPANY_GUIDANCE",
    disclosed="2025-12-01",
    event_type="PDUFA",
):
    return {
        "ticker": ticker,
        "pdufa_date": pdufa_date,
        "event_type": event_type,
        "confidence": confidence,
        "source": source,
        "as_of_disclosed_at": disclosed,
    }


def _write_metadata(tmp_path, reg_cov=None):
    meta = {
        "regulatory_coverage": reg_cov
        or {
            "manual_calendar_n_records": 10,
            "n_eligible_flagged": 5,
            "regulatory_secondary_coverage_pct": 4.1,
            "reg_calendar_entries_used": 10,
        }
    }
    meta_path = tmp_path / "metadata.json"
    meta_path.write_text(json.dumps(meta))
    return meta_path


# ---------------------------------------------------------------------------
# Tests: select_quality_entries
# ---------------------------------------------------------------------------


class TestSelectQualityEntries:

    def test_prunes_past_dated(self):
        records = [
            _make_entry("A", "2026-02-01"),  # past
            _make_entry("B", "2026-06-01"),  # future
        ]
        selected, diag = select_quality_entries(records, "2026-03-10")
        assert len(selected) == 1
        assert selected[0]["ticker"] == "B"
        assert diag["pruned_past_dated"] == 1

    def test_prunes_missing_disclosed_near_date(self):
        """Entries within 90d missing disclosed_at should be pruned."""
        records = [
            _make_entry("A", "2026-04-01", disclosed=""),  # 22d, no disclosed
            _make_entry("B", "2026-04-01", disclosed="2025-11-01"),  # 22d, has disclosed
            _make_entry("C", "2026-09-01", disclosed=""),  # 175d, no disclosed — kept (far)
        ]
        selected, diag = select_quality_entries(records, "2026-03-10")
        tickers = {r["ticker"] for r in selected}
        assert "A" not in tickers  # pruned
        assert "B" in tickers  # has disclosed_at
        assert "C" in tickers  # >90d, no disclosed OK
        assert diag["pruned_missing_disclosed"] == 1

    def test_max_entries_cap(self):
        records = [_make_entry(f"T{i}", f"2026-{4 + i % 6:02d}-01") for i in range(30)]
        policy = CalendarPolicy(max_entries=10)
        selected, diag = select_quality_entries(records, "2026-03-10", policy=policy)
        assert len(selected) == 10
        assert diag["pruned_max_entries"] == 20

    def test_coverage_cap_pruning(self):
        """If coverage > max_coverage_pct, prune lowest priority entries."""
        records = [_make_entry(f"T{i}", f"2026-{4 + i % 6:02d}-01") for i in range(15)]
        policy = CalendarPolicy(max_entries=50, max_coverage_pct=10.0)
        # With 100 eligible, 10% = 10 max tickers
        selected, diag = select_quality_entries(
            records,
            "2026-03-10",
            n_eligible=100,
            policy=policy,
        )
        unique_tickers = {r["ticker"] for r in selected}
        assert len(unique_tickers) <= 10
        assert diag["pruned_coverage_cap"] > 0

    def test_coverage_cap_skipped_when_no_eligible(self):
        """If n_eligible=0, coverage pruning is skipped."""
        records = [_make_entry("T{}".format(i), "2026-06-01") for i in range(15)]
        policy = CalendarPolicy(max_entries=50, max_coverage_pct=10.0)
        selected, diag = select_quality_entries(
            records,
            "2026-03-10",
            n_eligible=0,
            policy=policy,
        )
        assert len(selected) == 15
        assert diag["pruned_coverage_cap"] == 0

    def test_priority_determinism(self):
        """Same inputs always produce same output order."""
        records = [
            _make_entry("A", "2026-06-01", confidence="MED", source="CTGOV_ESTIMATE"),
            _make_entry("B", "2026-06-01", confidence="HIGH", source="COMPANY_GUIDANCE"),
            _make_entry("C", "2026-06-01", confidence="HIGH", source="ANALYST_ESTIMATE"),
        ]
        s1, _ = select_quality_entries(records, "2026-03-10")
        s2, _ = select_quality_entries(records, "2026-03-10")
        assert [r["ticker"] for r in s1] == [r["ticker"] for r in s2]
        # B (HIGH + COMPANY_GUIDANCE=3) should be before C (HIGH + ANALYST=1) before A (MED + CTGOV=1)
        assert s1[0]["ticker"] == "B"
        assert s1[1]["ticker"] == "C"
        assert s1[2]["ticker"] == "A"

    def test_proximity_preferred_band(self):
        """Entries in 15-180d get higher priority than >180d."""
        records = [
            _make_entry("FAR", "2027-01-01", confidence="HIGH", source="COMPANY_GUIDANCE"),  # 297d
            _make_entry("SWEET", "2026-06-01", confidence="HIGH", source="COMPANY_GUIDANCE"),  # 83d
        ]
        selected, _ = select_quality_entries(records, "2026-03-10")
        assert selected[0]["ticker"] == "SWEET"

    def test_empty_input(self):
        selected, diag = select_quality_entries([], "2026-03-10")
        assert selected == []
        assert diag["output_count"] == 0

    def test_diagnostics_fields(self):
        records = [_make_entry("A", "2026-06-01")]
        _, diag = select_quality_entries(records, "2026-03-10", n_eligible=100)
        assert "input_count" in diag
        assert "output_count" in diag
        assert "unique_tickers" in diag
        assert "coverage_pct" in diag
        assert "pruned_past_dated" in diag
        assert "pruned_missing_disclosed" in diag
        assert "pruned_max_entries" in diag
        assert "pruned_coverage_cap" in diag


# ---------------------------------------------------------------------------
# Tests: _compute_entry_priority
# ---------------------------------------------------------------------------


class TestComputeEntryPriority:

    def test_high_beats_med(self):
        high = _make_entry(confidence="HIGH", source="MANUAL")
        med = _make_entry(confidence="MED", source="MANUAL")
        assert _compute_entry_priority(high, "2026-03-10") > _compute_entry_priority(med, "2026-03-10")

    def test_company_guidance_beats_ctgov(self):
        cg = _make_entry(confidence="MED", source="COMPANY_GUIDANCE")
        ct = _make_entry(confidence="MED", source="CTGOV_ESTIMATE")
        assert _compute_entry_priority(cg, "2026-03-10") > _compute_entry_priority(ct, "2026-03-10")


# ---------------------------------------------------------------------------
# Tests: CalendarPolicy
# ---------------------------------------------------------------------------


class TestCalendarPolicy:

    def test_defaults(self):
        p = CalendarPolicy()
        assert p.max_entries == 25
        assert p.max_coverage_pct == 10.0
        assert p.min_coverage_pct == 3.0
        assert p.require_disclosed_within_days == 90

    def test_custom_values(self):
        p = CalendarPolicy(max_entries=15, max_coverage_pct=8.0)
        assert p.max_entries == 15
        assert p.max_coverage_pct == 8.0

    def test_frozen(self):
        p = CalendarPolicy()
        try:
            p.max_entries = 99  # type: ignore
            assert False, "Should raise"
        except AttributeError:
            pass  # Expected for frozen dataclass


# ---------------------------------------------------------------------------
# Tests: Enhanced telemetry
# ---------------------------------------------------------------------------


class TestEnhancedTelemetry:

    def test_telemetry_includes_selection_diag(self):
        records = [_make_entry("A", "2026-06-01")]
        diag = {"input_count": 5, "output_count": 3, "pruned_past_dated": 2}
        tel = get_calendar_telemetry(records, selection_diag=diag)
        assert "quality_selection" in tel
        assert tel["quality_selection"]["pruned_past_dated"] == 2

    def test_telemetry_without_diag(self):
        records = [_make_entry("A", "2026-06-01")]
        tel = get_calendar_telemetry(records)
        assert "quality_selection" not in tel
        assert tel["manual_calendar_n_records"] == 1


# ---------------------------------------------------------------------------
# Tests: Gate logic (WARN-only, coverage band)
# ---------------------------------------------------------------------------


class TestGateCoverageBand:

    def test_pass_in_band(self, tmp_path):
        """Coverage in [3%, 12%] should PASS."""
        _write_metadata(
            tmp_path,
            {
                "manual_calendar_n_records": 10,
                "n_eligible_flagged": 8,
                "regulatory_secondary_coverage_pct": 5.0,
                "reg_calendar_entries_used": 10,
            },
        )
        config = GateConfig(
            regulatory_calendar_min_coverage_pct=3.0,
            regulatory_calendar_max_coverage_pct=12.0,
        )
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        assert result.status == "PASS"

    def test_warn_below_floor(self, tmp_path):
        """Coverage below min should WARN."""
        _write_metadata(
            tmp_path,
            {
                "manual_calendar_n_records": 2,
                "n_eligible_flagged": 1,
                "regulatory_secondary_coverage_pct": 0.5,
                "reg_calendar_entries_used": 2,
            },
        )
        config = GateConfig(
            regulatory_calendar_min_coverage_pct=3.0,
            regulatory_calendar_max_coverage_pct=12.0,
        )
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        assert result.status == "WARN"
        assert "floor" in result.detail

    def test_warn_above_ceiling(self, tmp_path):
        """Coverage above max should WARN (over-flagging)."""
        _write_metadata(
            tmp_path,
            {
                "manual_calendar_n_records": 50,
                "n_eligible_flagged": 40,
                "regulatory_secondary_coverage_pct": 20.0,
                "reg_calendar_entries_used": 50,
            },
        )
        config = GateConfig(
            regulatory_calendar_min_coverage_pct=3.0,
            regulatory_calendar_max_coverage_pct=12.0,
        )
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        assert result.status == "WARN"
        assert "ceiling" in result.detail or "over-flagging" in result.detail

    def test_gate_always_warn_never_fail(self, tmp_path):
        """Gate should never FAIL, only WARN or PASS."""
        _write_metadata(
            tmp_path,
            {
                "manual_calendar_n_records": 0,
                "n_eligible_flagged": 0,
                "regulatory_secondary_coverage_pct": 0.0,
                "reg_calendar_entries_used": 0,
            },
        )
        config = GateConfig()
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        assert result.status in ("PASS", "WARN")
        assert result.status != "FAIL"

    def test_warn_missing_metadata(self, tmp_path):
        config = GateConfig()
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        assert result.status == "WARN"

    def test_entries_used_in_detail(self, tmp_path):
        _write_metadata(
            tmp_path,
            {
                "manual_calendar_n_records": 20,
                "n_eligible_flagged": 10,
                "regulatory_secondary_coverage_pct": 5.0,
                "reg_calendar_entries_used": 18,
            },
        )
        config = GateConfig()
        result = check_regulatory_calendar(tmp_path, "2026-03-10", config)
        assert "used=18" in result.detail


# ---------------------------------------------------------------------------
# Tests: Confidence filter (for A/B script)
# ---------------------------------------------------------------------------


class TestConfidenceFilter:

    def test_high_only(self):
        from scripts.research.eval_calendar_confidence_ab import filter_calendar

        calendar = [
            _make_entry("A", confidence="HIGH"),
            _make_entry("B", confidence="MED"),
            _make_entry("C", confidence="LOW"),
        ]
        result = filter_calendar(calendar, frozenset({"HIGH"}))
        assert len(result) == 1
        assert result[0]["ticker"] == "A"

    def test_high_plus_med(self):
        from scripts.research.eval_calendar_confidence_ab import filter_calendar

        calendar = [
            _make_entry("A", confidence="HIGH"),
            _make_entry("B", confidence="MED"),
            _make_entry("C", confidence="LOW"),
        ]
        result = filter_calendar(calendar, frozenset({"HIGH", "MED"}))
        assert len(result) == 2

    def test_quality_source_filter(self):
        from scripts.research.eval_calendar_confidence_ab import _QUALITY_SOURCES, filter_calendar

        calendar = [
            _make_entry("A", confidence="HIGH", source="CTGOV_ESTIMATE"),  # HIGH always passes
            _make_entry("B", confidence="MED", source="COMPANY_GUIDANCE"),  # quality source
            _make_entry("C", confidence="MED", source="CTGOV_ESTIMATE"),  # not quality source
        ]
        result = filter_calendar(
            calendar,
            frozenset({"HIGH", "MED"}),
            source_allow=_QUALITY_SOURCES,
        )
        tickers = {r["ticker"] for r in result}
        assert "A" in tickers  # HIGH always passes
        assert "B" in tickers  # MED + quality source
        assert "C" not in tickers  # MED + non-quality source

    def test_empty_calendar(self):
        from scripts.research.eval_calendar_confidence_ab import filter_calendar

        result = filter_calendar([], frozenset({"HIGH"}))
        assert result == []
