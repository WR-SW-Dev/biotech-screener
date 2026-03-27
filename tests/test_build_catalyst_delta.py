"""Tests for tools/build_catalyst_delta.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.build_catalyst_delta import (
    SCHEMA_VERSION,
    build_catalyst_delta,
    classify_change,
    format_delta_md,
    passes_noise_filter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row(
    ticker="TEST",
    tier_dev="A",
    actionable_rank="10",
    catalyst_days="30",
    catalyst_family="CLINICAL",
    catalyst_source="CTGOV_CALENDAR",
    catalyst_event_type="CT_PRIMARY_COMPLETION",
    catalyst_mode="specific_days",
    catalyst_bucket="build_window",
    is_hard_catalyst="1",
):
    return {
        "ticker": ticker,
        "tier_dev": tier_dev,
        "actionable_rank": actionable_rank,
        "catalyst_days": catalyst_days,
        "catalyst_family": catalyst_family,
        "catalyst_source": catalyst_source,
        "catalyst_event_type": catalyst_event_type,
        "catalyst_mode": catalyst_mode,
        "catalyst_bucket": catalyst_bucket,
        "is_hard_catalyst": is_hard_catalyst,
    }


def _write_rankings(snap_dir: Path, rows: list):
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / "rankings.csv"
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# classify_change
# ---------------------------------------------------------------------------
class TestClassifyChange:
    def test_new_entrant(self):
        result = classify_change("AAA", None, _row(ticker="AAA"))
        assert result is not None
        assert "NEW_ENTRANT" in result["codes"]

    def test_exited(self):
        result = classify_change("AAA", _row(ticker="AAA"), None)
        assert result is not None
        assert "EXITED" in result["codes"]

    def test_no_change(self):
        r = _row()
        # Same day: catalyst_days goes from 30 to 29 (natural decay)
        prior = {**r, "catalyst_days": "30"}
        current = {**r, "catalyst_days": "29"}
        result = classify_change("TEST", prior, current)
        assert result is None  # natural -1 decay, no material change

    def test_date_pushed_back(self):
        prior = _row(catalyst_days="30")
        current = _row(catalyst_days="35")  # pushed back 6 days
        result = classify_change("TEST", prior, current)
        assert result is not None
        assert "DATE_PUSHED_BACK" in result["codes"]

    def test_date_pulled_forward(self):
        prior = _row(catalyst_days="60")
        current = _row(catalyst_days="45")  # pulled forward 14 days beyond natural
        result = classify_change("TEST", prior, current)
        assert result is not None
        assert "DATE_PULLED_FORWARD" in result["codes"]

    def test_small_shift_ignored(self):
        # 2-day shift beyond natural (below threshold of 3)
        prior = _row(catalyst_days="30")
        current = _row(catalyst_days="31")  # shift = 31 - 29 = +2
        result = classify_change("TEST", prior, current)
        assert result is None

    def test_family_changed(self):
        prior = _row(catalyst_family="CLINICAL")
        current = _row(catalyst_family="REGULATORY")
        result = classify_change("TEST", prior, current)
        assert result is not None
        assert "FAMILY_CHANGED" in result["codes"]

    def test_source_changed(self):
        prior = _row(catalyst_source="CTGOV_CALENDAR")
        current = _row(catalyst_source="SEC_8K_FILING")
        result = classify_change("TEST", prior, current)
        assert result is not None
        assert "SOURCE_CHANGED" in result["codes"]

    def test_event_type_changed(self):
        prior = _row(catalyst_event_type="CT_PRIMARY_COMPLETION")
        current = _row(catalyst_event_type="DATA_READOUT")
        result = classify_change("TEST", prior, current)
        assert result is not None
        assert "EVENT_TYPE_CHANGED" in result["codes"]

    def test_became_hard(self):
        prior = _row(is_hard_catalyst="0")
        current = _row(is_hard_catalyst="1")
        result = classify_change("TEST", prior, current)
        assert result is not None
        assert "BECAME_HARD" in result["codes"]

    def test_became_soft(self):
        prior = _row(is_hard_catalyst="1")
        current = _row(is_hard_catalyst="0")
        result = classify_change("TEST", prior, current)
        assert result is not None
        assert "BECAME_SOFT" in result["codes"]

    def test_event_resolved(self):
        prior = _row(catalyst_mode="specific_days")
        current = _row(catalyst_mode="no_upcoming")
        result = classify_change("TEST", prior, current)
        assert result is not None
        assert "EVENT_RESOLVED" in result["codes"]

    def test_new_event_appeared(self):
        prior = _row(catalyst_mode="no_upcoming")
        current = _row(catalyst_mode="specific_days")
        result = classify_change("TEST", prior, current)
        assert result is not None
        assert "NEW_EVENT_APPEARED" in result["codes"]

    def test_multiple_codes(self):
        prior = _row(catalyst_family="CLINICAL", catalyst_source="CTGOV_CALENDAR", catalyst_days="60")
        current = _row(catalyst_family="REGULATORY", catalyst_source="SEC_8K_FILING", catalyst_days="20")
        result = classify_change("TEST", prior, current)
        assert result is not None
        assert "FAMILY_CHANGED" in result["codes"]
        assert "SOURCE_CHANGED" in result["codes"]
        assert "DATE_PULLED_FORWARD" in result["codes"]

    def test_both_none(self):
        result = classify_change("TEST", None, None)
        assert result is None


# ---------------------------------------------------------------------------
# passes_noise_filter
# ---------------------------------------------------------------------------
class TestNoiseFilter:
    def test_a_tier_passes(self):
        change = {"ticker": "AAA", "tier": "A", "codes": ["DATE_SHIFTED"]}
        assert passes_noise_filter(change, set(), set()) is True

    def test_b_tier_passes(self):
        change = {"ticker": "BBB", "tier": "B", "codes": ["DATE_SHIFTED"]}
        assert passes_noise_filter(change, set(), set()) is True

    def test_c_tier_blocked(self):
        change = {"ticker": "CCC", "tier": "C", "codes": ["DATE_SHIFTED"], "catalyst_days": "100"}
        assert passes_noise_filter(change, set(), set()) is False

    def test_near_catalyst_passes(self):
        change = {"ticker": "CCC", "tier": "C", "codes": ["DATE_SHIFTED"], "catalyst_days": "15"}
        assert passes_noise_filter(change, set(), set()) is True

    def test_family_changed_passes(self):
        change = {"ticker": "CCC", "tier": "C", "codes": ["FAMILY_CHANGED"], "catalyst_days": "100"}
        assert passes_noise_filter(change, set(), set()) is True

    def test_in_positions_passes(self):
        change = {"ticker": "CCC", "tier": "C", "codes": ["DATE_SHIFTED"], "catalyst_days": "100"}
        assert passes_noise_filter(change, {"CCC"}, set()) is True

    def test_in_trade_plan_passes(self):
        change = {"ticker": "CCC", "tier": "C", "codes": ["DATE_SHIFTED"], "catalyst_days": "100"}
        assert passes_noise_filter(change, set(), {"CCC"}) is True


# ---------------------------------------------------------------------------
# build_catalyst_delta integration
# ---------------------------------------------------------------------------
class TestBuildCatalystDelta:
    def test_basic(self, tmp_path):
        snaps = tmp_path / "snapshots"
        artifacts = tmp_path / "artifacts"

        prior_rows = [
            _row(ticker="AAA", catalyst_days="30"),
            _row(ticker="BBB", catalyst_days="60"),
            _row(ticker="CCC", catalyst_days="100", tier_dev="C"),
        ]
        current_rows = [
            _row(ticker="AAA", catalyst_days="29"),  # natural decay, no change
            _row(ticker="BBB", catalyst_days="40"),  # pulled forward 19d
            _row(ticker="CCC", catalyst_days="99", tier_dev="C"),  # natural, C-tier
            _row(ticker="DDD", catalyst_days="10"),  # new entrant
        ]
        _write_rankings(snaps / "2026-03-26", prior_rows)
        _write_rankings(snaps / "2026-03-27", current_rows)

        result = build_catalyst_delta(
            "2026-03-27",
            prior_date="2026-03-26",
            snapshots_dir=snaps,
            artifacts_dir=artifacts,
        )

        assert result["schema"] == SCHEMA_VERSION
        assert "error" not in result
        tickers = [d["ticker"] for d in result["deltas"]]
        assert "BBB" in tickers  # date pulled forward, A-tier
        assert "DDD" in tickers  # new entrant, A-tier
        assert "AAA" not in tickers  # no material change
        # CCC should be filtered out (C-tier, 99d, no family change)
        assert "CCC" not in tickers

    def test_auto_finds_prior(self, tmp_path):
        snaps = tmp_path / "snapshots"
        artifacts = tmp_path / "artifacts"

        _write_rankings(snaps / "2026-03-25", [_row(ticker="AAA", catalyst_days="32")])
        _write_rankings(snaps / "2026-03-26", [_row(ticker="AAA", catalyst_days="31")])
        _write_rankings(snaps / "2026-03-27", [_row(ticker="AAA", catalyst_days="30")])

        result = build_catalyst_delta("2026-03-27", snapshots_dir=snaps, artifacts_dir=artifacts)
        assert result["prior_date"] == "2026-03-26"

    def test_skips_pre_staging_dirs(self, tmp_path):
        snaps = tmp_path / "snapshots"
        artifacts = tmp_path / "artifacts"

        _write_rankings(snaps / "2026-03-26", [_row(ticker="AAA", catalyst_days="31")])
        _write_rankings(snaps / "2026-03-26__pre_20260326T203350Z", [_row(ticker="AAA", catalyst_days="99")])
        _write_rankings(snaps / "2026-03-27", [_row(ticker="AAA", catalyst_days="30")])

        result = build_catalyst_delta("2026-03-27", snapshots_dir=snaps, artifacts_dir=artifacts)
        assert result["prior_date"] == "2026-03-26"

    def test_missing_rankings(self, tmp_path):
        result = build_catalyst_delta(
            "2026-03-27",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=tmp_path / "artifacts",
        )
        assert "error" in result

    def test_writes_artifacts(self, tmp_path):
        snaps = tmp_path / "snapshots"
        artifacts = tmp_path / "artifacts"

        _write_rankings(snaps / "2026-03-26", [_row(ticker="AAA", catalyst_days="31")])
        _write_rankings(snaps / "2026-03-27", [_row(ticker="AAA", catalyst_days="30")])

        build_catalyst_delta("2026-03-27", prior_date="2026-03-26", snapshots_dir=snaps, artifacts_dir=artifacts)

        assert (artifacts / "catalyst_delta" / "2026-03-27_delta.json").exists()
        assert (artifacts / "catalyst_delta" / "2026-03-27_delta.md").exists()

        loaded = json.loads((artifacts / "catalyst_delta" / "2026-03-27_delta.json").read_text())
        assert loaded["schema"] == SCHEMA_VERSION

    def test_position_context(self, tmp_path):
        snaps = tmp_path / "snapshots"
        artifacts = tmp_path / "artifacts"

        # C-tier name with date shift — would be filtered without position context
        prior_rows = [_row(ticker="CCC", catalyst_days="50", tier_dev="C")]
        current_rows = [_row(ticker="CCC", catalyst_days="30", tier_dev="C")]
        _write_rankings(snaps / "2026-03-26", prior_rows)
        _write_rankings(snaps / "2026-03-27", current_rows)

        # Put CCC in positions
        _write_json(
            artifacts / "live_shadow" / "positions" / "2026-03-27.json",
            {"positions": [{"ticker": "CCC"}]},
        )

        result = build_catalyst_delta(
            "2026-03-27",
            prior_date="2026-03-26",
            snapshots_dir=snaps,
            artifacts_dir=artifacts,
        )

        tickers = [d["ticker"] for d in result["deltas"]]
        assert "CCC" in tickers


# ---------------------------------------------------------------------------
# Markdown formatting
# ---------------------------------------------------------------------------
class TestFormatMd:
    def test_basic(self):
        d = {
            "as_of_date": "2026-03-27",
            "prior_date": "2026-03-26",
            "generated_at": "2026-03-27T00:00:00Z",
            "n_filtered": 1,
            "n_noise_suppressed": 5,
            "code_counts": {"DATE_PULLED_FORWARD": 1},
            "deltas": [
                {
                    "ticker": "BBB",
                    "tier": "A",
                    "rank": "5",
                    "catalyst_days": "40",
                    "catalyst_family": "CLINICAL",
                    "codes": ["DATE_PULLED_FORWARD"],
                    "prior_days": 60,
                    "current_days": 40,
                    "shift": -19,
                }
            ],
        }
        md = format_delta_md(d)
        assert "BBB" in md
        assert "DATE_PULLED_FORWARD" in md
        assert "shift" in md

    def test_empty_deltas(self):
        d = {
            "as_of_date": "2026-03-27",
            "prior_date": "2026-03-26",
            "generated_at": "",
            "n_filtered": 0,
            "n_noise_suppressed": 0,
            "code_counts": {},
            "deltas": [],
        }
        md = format_delta_md(d)
        assert "No material catalyst changes" in md
