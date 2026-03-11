"""Tests for calendar slip tracker — tools/track_calendar_slips.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.track_calendar_slips import (
    SLIPS_COLUMNS,
    check_calendar_slips,
    compute_slip_summary,
    compute_slips,
    find_prior_snapshot,
    load_snapshot_calendar,
    render_slip_summary_md,
    run_slip_tracker,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RANKINGS_HEADER = [
    "ticker",
    "actionable_rank",
    "eligible",
    "catalyst_days",
    "catalyst_mode",
    "catalyst_source",
    "catalyst_event_type",
    "catalyst_reason_detail",
    "de_catalyst_days",
    "de_catalyst_mode",
    "confidence_overall",
]


def _write_rankings(snap_dir, rows):
    snap_dir.mkdir(parents=True, exist_ok=True)
    with open(snap_dir / "rankings.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RANKINGS_HEADER)
        w.writeheader()
        for r in rows:
            full = {h: "" for h in RANKINGS_HEADER}
            full.update(r)
            w.writerow(full)


def _write_metadata(snap_dir, as_of_date):
    snap_dir.mkdir(parents=True, exist_ok=True)
    with open(snap_dir / "metadata.json", "w") as f:
        json.dump({"as_of_date": as_of_date, "ruleset_id": "test"}, f)


def _make_row(ticker, days, rank=1, source="", event_type="", mode="specific_days", confidence="", eligible="1"):
    return {
        "ticker": ticker,
        "actionable_rank": str(rank),
        "eligible": eligible,
        "catalyst_days": str(days) if days is not None else "",
        "catalyst_mode": mode,
        "catalyst_source": source,
        "catalyst_event_type": event_type,
        "de_catalyst_days": str(days) if days is not None else "",
        "de_catalyst_mode": mode,
        "confidence_overall": confidence,
        "catalyst_reason_detail": "",
    }


# ---------------------------------------------------------------------------
# Tests: find_prior_snapshot
# ---------------------------------------------------------------------------


class TestFindPriorSnapshot:
    def test_finds_nearest_prior(self, tmp_path):
        """Selects the closest prior snapshot by date."""
        _write_rankings(tmp_path / "2026-03-03", [_make_row("A", 100)])
        _write_rankings(tmp_path / "2026-03-07", [_make_row("A", 96)])
        _write_rankings(tmp_path / "2026-03-10", [_make_row("A", 93)])

        result = find_prior_snapshot("2026-03-10", tmp_path)
        assert result is not None
        assert result[0] == "2026-03-07"

    def test_skips_current_date(self, tmp_path):
        """Prior snapshot must be strictly before as_of_date."""
        _write_rankings(tmp_path / "2026-03-10", [_make_row("A", 93)])

        result = find_prior_snapshot("2026-03-10", tmp_path)
        assert result is None

    def test_no_prior_returns_none(self, tmp_path):
        """Returns None when no prior snapshot exists."""
        result = find_prior_snapshot("2026-03-10", tmp_path)
        assert result is None

    def test_respects_lookback(self, tmp_path):
        """Snapshots beyond lookback + margin are not found."""
        _write_rankings(tmp_path / "2026-01-01", [_make_row("A", 100)])

        result = find_prior_snapshot("2026-03-10", tmp_path, lookback_days=7)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: compute_slips
# ---------------------------------------------------------------------------


def _cal_entry(days, family="CLINICAL", event_type="", source="", confidence="", mode="specific_days"):
    """Build a calendar entry dict for compute_slips tests."""
    return {
        "_days_int": days,
        "_family": family,
        "catalyst_mode": mode,
        "catalyst_event_type": event_type,
        "catalyst_source": source,
        "confidence_overall": confidence,
    }


class TestComputeSlips:
    def test_delta_days_correct_sign(self):
        """Positive slip = pushed out, negative = pulled in."""
        prior = {"A": _cal_entry(60)}
        current = {"A": _cal_entry(70)}
        slips = compute_slips(prior, current, "2026-03-03", "2026-03-10", elapsed_days=7)
        assert len(slips) == 1
        s = slips[0]
        # expected_days = max(60 - 7, 0) = 53
        # slip_days = 70 - 53 = +17 (pushed out)
        assert s["slip_days"] == 17
        assert s["delta_days"] == 10  # 70 - 60

    def test_negative_slip_pulled_in(self):
        """Catalyst date moved closer → negative slip."""
        prior = {"A": _cal_entry(90)}
        current = {"A": _cal_entry(70)}
        slips = compute_slips(prior, current, "2026-03-03", "2026-03-10", elapsed_days=7)
        s = slips[0]
        # expected = max(90 - 7, 0) = 83, slip = 70 - 83 = -13
        assert s["slip_days"] == -13

    def test_no_slip_on_normal_countdown(self):
        """Normal countdown (days decrease by elapsed) produces slip=0."""
        prior = {"A": _cal_entry(60)}
        current = {"A": _cal_entry(53)}
        slips = compute_slips(prior, current, "2026-03-03", "2026-03-10", elapsed_days=7)
        assert slips[0]["slip_days"] == 0

    def test_new_flag(self):
        """Ticker appearing for first time gets new_flag=1."""
        prior = {}
        current = {"A": _cal_entry(30)}
        slips = compute_slips(prior, current, "2026-03-03", "2026-03-10", elapsed_days=7)
        assert len(slips) == 1
        assert slips[0]["new_flag"] == "1"
        assert slips[0]["dropped_flag"] == "0"
        assert slips[0]["slip_days"] == ""  # Can't compute slip for new entry

    def test_dropped_flag(self):
        """Ticker disappearing gets dropped_flag=1."""
        prior = {"A": _cal_entry(30)}
        current = {}
        slips = compute_slips(prior, current, "2026-03-03", "2026-03-10", elapsed_days=7)
        assert len(slips) == 1
        assert slips[0]["dropped_flag"] == "1"
        assert slips[0]["new_flag"] == "0"

    def test_large_slip_flag(self):
        """slip >= 14d triggers large_slip flag."""
        prior = {"A": _cal_entry(30)}
        # Push out by 20 days: expected=23, actual=43 → slip=20
        current = {"A": _cal_entry(43)}
        slips = compute_slips(prior, current, "2026-03-03", "2026-03-10", elapsed_days=7)
        assert slips[0]["large_slip"] == "1"
        assert slips[0]["slip_days"] == 20

    def test_imminent_flag(self):
        """current_days <= 14 triggers imminent flag."""
        prior = {"A": _cal_entry(21, family="REGULATORY", event_type="PDUFA")}
        current = {"A": _cal_entry(14, family="REGULATORY", event_type="PDUFA")}
        slips = compute_slips(prior, current, "2026-03-03", "2026-03-10", elapsed_days=7)
        assert slips[0]["imminent"] == "1"

    def test_deterministic_ordering(self):
        """Output is sorted by ticker ascending."""
        prior = {"ZZZ": _cal_entry(10), "AAA": _cal_entry(20)}
        current = dict(prior)
        slips = compute_slips(prior, current, "2026-03-03", "2026-03-10", elapsed_days=7)
        tickers = [s["ticker"] for s in slips]
        assert tickers == sorted(tickers)


# ---------------------------------------------------------------------------
# Tests: compute_slip_summary
# ---------------------------------------------------------------------------


def _slip_row(
    ticker="A",
    family="CLINICAL",
    slip_days="",
    new_flag="0",
    dropped_flag="0",
    large_slip="0",
    imminent="0",
    current_days="30",
    current_source="",
    prior_source="",
    current_confidence="",
    prior_confidence="",
    prior_days="",
    delta_days="",
    expected_days="",
):
    """Helper to build a complete slip row for summary tests."""
    return {
        "ticker": ticker,
        "family": family,
        "prior_days": prior_days,
        "current_days": current_days,
        "delta_days": delta_days,
        "expected_days": expected_days,
        "slip_days": slip_days,
        "prior_event_type": "",
        "current_event_type": "",
        "prior_source": prior_source,
        "current_source": current_source,
        "prior_confidence": prior_confidence,
        "current_confidence": current_confidence,
        "prior_mode": "",
        "current_mode": "",
        "prior_snapshot_date": "",
        "current_snapshot_date": "",
        "new_flag": new_flag,
        "dropped_flag": dropped_flag,
        "large_slip": large_slip,
        "imminent": imminent,
    }


class TestComputeSlipSummary:
    def test_counts_correct(self):
        slips = [
            _slip_row(ticker="A", new_flag="1", slip_days=""),
            _slip_row(ticker="B", family="REGULATORY", dropped_flag="1", current_days=""),
            _slip_row(
                ticker="C",
                family="REGULATORY",
                large_slip="1",
                imminent="1",
                slip_days="20",
                current_days="10",
                current_source="CTGOV",
            ),
        ]
        summary = compute_slip_summary(slips)
        assert summary["new_count"] == 1
        assert summary["dropped_count"] == 1
        assert summary["large_slip_count"] == 1
        assert summary["imminent_large_slip_count"] == 1
        assert summary["total_tracked"] == 3

    def test_breakdown_by_source(self):
        slips = [
            _slip_row(ticker="A", slip_days="5", current_source="CTGOV_CALENDAR", current_confidence="HIGH"),
            _slip_row(
                ticker="B",
                slip_days="10",
                current_days="20",
                current_source="CTGOV_CALENDAR",
                current_confidence="HIGH",
            ),
        ]
        summary = compute_slip_summary(slips)
        bd = summary["breakdown_by_source_confidence"]
        assert len(bd) == 1
        assert bd[0]["source"] == "CTGOV_CALENDAR"
        assert bd[0]["confidence"] == "HIGH"
        assert bd[0]["count"] == 2
        assert bd[0]["mean_abs_slip"] == 7.5


# ---------------------------------------------------------------------------
# Tests: check_calendar_slips (WARN gate)
# ---------------------------------------------------------------------------


class TestCheckCalendarSlips:
    def test_pass_when_below_thresholds(self):
        summary = {"imminent_large_slip_count": 1, "large_slip_rate_regulatory": 0.05}
        result = check_calendar_slips(summary)
        assert result["status"] == "PASS"

    def test_warn_on_imminent_large_slip(self):
        summary = {"imminent_large_slip_count": 4, "large_slip_rate_regulatory": 0.05}
        result = check_calendar_slips(summary, max_imminent_large_slip=3)
        assert result["status"] == "WARN"
        assert "imminent_large_slip_count" in result["detail"]

    def test_warn_on_high_regulatory_slip_rate(self):
        summary = {"imminent_large_slip_count": 0, "large_slip_rate_regulatory": 0.25}
        result = check_calendar_slips(summary, max_large_slip_rate_reg=0.20)
        assert result["status"] == "WARN"
        assert "large_slip_rate_regulatory" in result["detail"]

    def test_warn_on_both(self):
        summary = {"imminent_large_slip_count": 5, "large_slip_rate_regulatory": 0.30}
        result = check_calendar_slips(summary, max_imminent_large_slip=3, max_large_slip_rate_reg=0.20)
        assert result["status"] == "WARN"
        # Both issues in detail
        assert "imminent" in result["detail"]
        assert "large_slip_rate" in result["detail"]


# ---------------------------------------------------------------------------
# Tests: render_slip_summary_md
# ---------------------------------------------------------------------------


class TestRenderSlipSummaryMd:
    def test_renders_stable(self):
        summary = {
            "total_tracked": 50,
            "new_count": 3,
            "dropped_count": 2,
            "large_slip_count": 5,
            "imminent_count": 10,
            "imminent_large_slip_count": 1,
            "mean_abs_slip_days": 4.2,
            "median_abs_slip_days": 3,
            "flagged_regulatory_count": 8,
            "flagged_regulatory_large_slip_count": 2,
            "large_slip_rate_regulatory": 0.25,
            "top_slips": [
                {
                    "ticker": "ABCD",
                    "family": "REGULATORY",
                    "slip_days": 30,
                    "prior_days": 45,
                    "current_days": 68,
                    "source": "CTGOV",
                },
            ],
            "breakdown_by_source_confidence": [
                {"source": "CTGOV", "confidence": "HIGH", "count": 20, "mean_abs_slip": 5.0},
            ],
        }
        md = render_slip_summary_md(summary, "2026-03-03", "2026-03-10")
        assert "Calendar Slip Summary" in md
        assert "2026-03-10" in md
        assert "ABCD" in md
        assert "CTGOV" in md
        assert "Large slips" in md


# ---------------------------------------------------------------------------
# Tests: load_snapshot_calendar
# ---------------------------------------------------------------------------


class TestLoadSnapshotCalendar:
    def test_loads_calendar_fields(self, tmp_path):
        snap_dir = tmp_path / "snap"
        _write_rankings(
            snap_dir,
            [
                _make_row("A", 30, source="CTGOV_CALENDAR", event_type="CT_STUDY_COMPLETION"),
                _make_row("B", 90, rank=2, source="", event_type=""),
            ],
        )
        cal = load_snapshot_calendar(snap_dir)
        assert "A" in cal
        assert "B" in cal
        assert cal["A"]["_days_int"] == 30
        assert cal["A"]["catalyst_source"] == "CTGOV_CALENDAR"
        assert cal["B"]["_days_int"] == 90

    def test_skips_ineligible(self, tmp_path):
        snap_dir = tmp_path / "snap"
        _write_rankings(
            snap_dir,
            [
                _make_row("A", 30, eligible="0"),
                _make_row("B", 90, rank=2),
            ],
        )
        cal = load_snapshot_calendar(snap_dir)
        assert "A" not in cal
        assert "B" in cal

    def test_missing_rankings_returns_empty(self, tmp_path):
        cal = load_snapshot_calendar(tmp_path / "nonexistent")
        assert cal == {}


# ---------------------------------------------------------------------------
# Tests: run_slip_tracker (integration)
# ---------------------------------------------------------------------------


class TestRunSlipTracker:
    def test_full_run(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        out_root = tmp_path / "slips_out"

        # Prior: ticker A at 60 days
        prior_dir = snap_root / "2026-03-03"
        _write_rankings(prior_dir, [_make_row("A", 60, source="CTGOV_CALENDAR")])
        _write_metadata(prior_dir, "2026-03-03")

        # Current: ticker A pushed out to 70 (expected 53, slip=+17)
        current_dir = snap_root / "2026-03-10"
        _write_rankings(current_dir, [_make_row("A", 70, source="CTGOV_CALENDAR")])
        _write_metadata(current_dir, "2026-03-10")

        result = run_slip_tracker("2026-03-10", snap_root=snap_root, out_root=out_root)

        assert result["status"] == "OK"
        assert result["elapsed_days"] == 7
        assert result["summary"]["large_slip_count"] == 1  # 17 >= 14

        # Check artifacts written
        assert Path(result["paths"]["csv_path"]).is_file()
        assert Path(result["paths"]["json_path"]).is_file()
        assert Path(result["paths"]["md_path"]).is_file()

        # Check CSV content
        with open(result["paths"]["csv_path"]) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["ticker"] == "A"
        assert rows[0]["slip_days"] == "17"
        assert rows[0]["large_slip"] == "1"

    def test_no_prior_returns_skip(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        out_root = tmp_path / "slips_out"
        current_dir = snap_root / "2026-03-10"
        _write_rankings(current_dir, [_make_row("A", 70)])

        result = run_slip_tracker("2026-03-10", snap_root=snap_root, out_root=out_root)
        assert result["status"] == "SKIP"

    def test_csv_columns_match_schema(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        out_root = tmp_path / "slips_out"
        _write_rankings(snap_root / "2026-03-03", [_make_row("A", 60)])
        _write_rankings(snap_root / "2026-03-10", [_make_row("A", 53)])

        result = run_slip_tracker("2026-03-10", snap_root=snap_root, out_root=out_root)
        with open(result["paths"]["csv_path"]) as f:
            reader = csv.DictReader(f)
            assert list(reader.fieldnames) == SLIPS_COLUMNS
