"""Tests for tools/build_options_watch.py."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.build_options_watch import (
    SCHEMA_VERSION,
    WATCHLIST_MAX,
    _check_eligibility,
    _compute_flags,
    _compute_priority_score,
    _should_suppress,
    build_options_watch,
    format_watch_md,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ranking_row(
    ticker="TEST",
    tier_dev="A",
    actionable_rank="10",
    catalyst_days="15",
    catalyst_family="CLINICAL",
    is_hard_catalyst="1",
    opt_has_data="1",
    opt_liquidity_ok="1",
    opt_use_for_judgment="YES",
    opt_atm_iv="0.50",
    opt_term_slope="-0.12",
    opt_rr_25d="0.03",
    actual_implied_move_pctile="0.70",
    atm_iv_change_5d="0.08",
    opt_iv_regime="NORMAL",
    opt_event_premium="NO",
):
    return {
        "ticker": ticker,
        "tier_dev": tier_dev,
        "actionable_rank": actionable_rank,
        "catalyst_days": catalyst_days,
        "catalyst_family": catalyst_family,
        "is_hard_catalyst": is_hard_catalyst,
        "opt_has_data": opt_has_data,
        "opt_liquidity_ok": opt_liquidity_ok,
        "opt_use_for_judgment": opt_use_for_judgment,
        "opt_atm_iv": opt_atm_iv,
        "opt_term_slope": opt_term_slope,
        "opt_rr_25d": opt_rr_25d,
        "actual_implied_move_pctile": actual_implied_move_pctile,
        "atm_iv_change_5d": atm_iv_change_5d,
        "opt_iv_regime": opt_iv_regime,
        "opt_event_premium": opt_event_premium,
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


def _write_csv(path: Path, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
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
# Eligibility
# ---------------------------------------------------------------------------
class TestEligibility:
    def test_all_pass(self):
        assert _check_eligibility(_ranking_row()) is True

    def test_no_data(self):
        assert _check_eligibility(_ranking_row(opt_has_data="0")) is False

    def test_no_liquidity(self):
        assert _check_eligibility(_ranking_row(opt_liquidity_ok="0")) is False

    def test_no_judgment(self):
        assert _check_eligibility(_ranking_row(opt_use_for_judgment="NO")) is False

    def test_empty_fields(self):
        assert _check_eligibility(_ranking_row(opt_has_data="")) is False


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
class TestFlags:
    def test_event_premium_yes(self):
        flags = _compute_flags(_ranking_row(opt_event_premium="YES", opt_term_slope="0.05"))
        assert "EVENT_PREMIUM" in flags

    def test_event_premium_slope(self):
        flags = _compute_flags(_ranking_row(opt_event_premium="NO", opt_term_slope="-0.15"))
        assert "EVENT_PREMIUM" in flags

    def test_no_event_premium(self):
        flags = _compute_flags(_ranking_row(opt_event_premium="NO", opt_term_slope="0.05"))
        assert "EVENT_PREMIUM" not in flags

    def test_iv_ramp_high(self):
        flags = _compute_flags(_ranking_row(atm_iv_change_5d="0.12"))
        assert "IV_RAMP_HIGH" in flags
        assert "IV_RAMP_MED" not in flags

    def test_iv_ramp_med(self):
        flags = _compute_flags(_ranking_row(atm_iv_change_5d="0.07"))
        assert "IV_RAMP_MED" in flags
        assert "IV_RAMP_HIGH" not in flags

    def test_iv_falling(self):
        flags = _compute_flags(_ranking_row(atm_iv_change_5d="-0.08"))
        assert "IV_FALLING" in flags

    def test_surface_move_high(self):
        flags = _compute_flags(_ranking_row(actual_implied_move_pctile="0.85"))
        assert "SURFACE_MOVE_HIGH" in flags

    def test_surface_move_med(self):
        flags = _compute_flags(_ranking_row(actual_implied_move_pctile="0.65"))
        assert "SURFACE_MOVE_MED" in flags

    def test_drift_risk_high_pctile(self):
        flags = _compute_flags(_ranking_row(actual_implied_move_pctile="0.90"))
        assert "DRIFT_RISK_HIGH" in flags

    def test_drift_risk_high_iv(self):
        flags = _compute_flags(_ranking_row(atm_iv_change_5d="0.15", actual_implied_move_pctile="0.40"))
        assert "DRIFT_RISK_HIGH" in flags

    def test_drift_risk_med(self):
        flags = _compute_flags(_ranking_row(actual_implied_move_pctile="0.70", atm_iv_change_5d="0.03"))
        assert "DRIFT_RISK_MED" in flags

    def test_extreme_skew(self):
        flags = _compute_flags(_ranking_row(opt_rr_25d="0.20"))
        assert "EXTREME_SKEW" in flags

    def test_extreme_skew_negative(self):
        flags = _compute_flags(_ranking_row(opt_rr_25d="-0.18"))
        assert "EXTREME_SKEW" in flags

    def test_no_flags_normal(self):
        flags = _compute_flags(
            _ranking_row(
                opt_event_premium="NO",
                opt_term_slope="0.05",
                atm_iv_change_5d="0.02",
                actual_implied_move_pctile="0.40",
                opt_rr_25d="0.03",
            )
        )
        assert flags == []

    def test_missing_fields_no_crash(self):
        row = _ranking_row()
        row["atm_iv_change_5d"] = ""
        row["actual_implied_move_pctile"] = ""
        row["opt_rr_25d"] = ""
        flags = _compute_flags(row)
        # Should still get EVENT_PREMIUM from slope
        assert "EVENT_PREMIUM" in flags


# ---------------------------------------------------------------------------
# Priority score
# ---------------------------------------------------------------------------
class TestPriorityScore:
    def test_max_cap(self):
        flags = ["SURFACE_MOVE_HIGH", "IV_RAMP_HIGH"]
        assert _compute_priority_score(flags) == 3  # 2+2 capped to 3

    def test_surface_high_only(self):
        assert _compute_priority_score(["SURFACE_MOVE_HIGH"]) == 2

    def test_iv_med_surface_med(self):
        assert _compute_priority_score(["SURFACE_MOVE_MED", "IV_RAMP_MED"]) == 2

    def test_no_scoring_flags(self):
        assert _compute_priority_score(["EVENT_PREMIUM", "EXTREME_SKEW"]) == 0

    def test_empty(self):
        assert _compute_priority_score([]) == 0


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------
class TestSuppression:
    def test_extreme_not_hard(self):
        row = _ranking_row(opt_iv_regime="EXTREME", is_hard_catalyst="0")
        reason = _should_suppress(row, is_hard=False, in_trade_plan=False)
        assert reason is not None
        assert "EXTREME" in reason

    def test_extreme_hard_catalyst(self):
        row = _ranking_row(opt_iv_regime="EXTREME", is_hard_catalyst="1")
        assert _should_suppress(row, is_hard=True, in_trade_plan=False) is None

    def test_extreme_in_trade_plan(self):
        row = _ranking_row(opt_iv_regime="EXTREME", is_hard_catalyst="0")
        assert _should_suppress(row, is_hard=False, in_trade_plan=True) is None

    def test_normal_regime(self):
        row = _ranking_row(opt_iv_regime="NORMAL")
        assert _should_suppress(row, is_hard=False, in_trade_plan=False) is None


# ---------------------------------------------------------------------------
# Integration: build_options_watch
# ---------------------------------------------------------------------------
class TestBuildOptionsWatch:
    def test_basic_post_packet(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        rows = [
            _ranking_row(ticker="AAA", actionable_rank="1", catalyst_days="5"),
            _ranking_row(ticker="BBB", actionable_rank="2", catalyst_days="10"),
            _ranking_row(ticker="CCC", actionable_rank="50", catalyst_days="100", tier_dev="B"),
        ]
        _write_rankings(snap_dir, rows)

        # Review queue with AAA
        _write_csv(snap_dir / "review_queue.csv", [{"ticker": "AAA", "action": "review"}])

        # Positions with BBB
        _write_json(
            artifacts_dir / "live_shadow" / "positions" / "2026-03-27.json",
            {"positions": [{"ticker": "BBB"}]},
        )

        result = build_options_watch(
            "2026-03-27",
            mode="post_packet",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        assert result["schema"] == SCHEMA_VERSION
        assert result["mode"] == "post_packet"
        assert "error" not in result
        tickers = [r["ticker"] for r in result["rows"]]
        assert "AAA" in tickers  # review queue
        assert "BBB" in tickers  # shadow position
        assert "CCC" not in tickers  # B-tier, not in any source

    def test_watchlist_cap(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        rows = [_ranking_row(ticker=f"T{i:03d}", actionable_rank=str(i), catalyst_days="10") for i in range(1, 50)]
        _write_rankings(snap_dir, rows)

        result = build_options_watch(
            "2026-03-27",
            mode="post_packet",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        assert len(result["rows"]) <= WATCHLIST_MAX

    def test_missing_rankings(self, tmp_path):
        result = build_options_watch(
            "2026-03-27",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=tmp_path / "artifacts",
        )
        assert "error" in result

    def test_ineligible_excluded(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        rows = [
            _ranking_row(ticker="GOOD", opt_has_data="1", opt_liquidity_ok="1", opt_use_for_judgment="YES"),
            _ranking_row(ticker="BAD", opt_has_data="0", opt_liquidity_ok="1", opt_use_for_judgment="YES"),
        ]
        _write_rankings(snap_dir, rows)

        result = build_options_watch(
            "2026-03-27",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        tickers = [r["ticker"] for r in result["rows"]]
        assert "GOOD" in tickers
        assert "BAD" not in tickers

    def test_extreme_suppressed(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        rows = [
            _ranking_row(ticker="EXTR", opt_iv_regime="EXTREME", is_hard_catalyst="0"),
        ]
        _write_rankings(snap_dir, rows)

        result = build_options_watch(
            "2026-03-27",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        assert result["n_suppressed"] == 1
        assert result["suppressed"][0]["ticker"] == "EXTR"

    def test_extreme_not_suppressed_if_hard(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        rows = [
            _ranking_row(ticker="HARDX", opt_iv_regime="EXTREME", is_hard_catalyst="1"),
        ]
        _write_rankings(snap_dir, rows)

        result = build_options_watch(
            "2026-03-27",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        tickers = [r["ticker"] for r in result["rows"]]
        assert "HARDX" in tickers
        assert result["n_suppressed"] == 0

    def test_pre_open_requires_strong_signal(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        # Name in review queue with only medium signals — should be excluded in pre_open
        rows = [
            _ranking_row(
                ticker="WEAK",
                atm_iv_change_5d="0.07",  # IV_RAMP_MED only
                actual_implied_move_pctile="0.50",
                opt_event_premium="NO",
                opt_term_slope="0.05",
                opt_rr_25d="0.03",
            ),
        ]
        _write_rankings(snap_dir, rows)
        _write_csv(snap_dir / "review_queue.csv", [{"ticker": "WEAK"}])

        result = build_options_watch(
            "2026-03-27",
            mode="pre_open",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        assert len(result["rows"]) == 0

    def test_pre_open_includes_strong_signal(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        rows = [
            _ranking_row(
                ticker="STRONG",
                atm_iv_change_5d="0.15",  # IV_RAMP_HIGH
                actual_implied_move_pctile="0.85",  # SURFACE_MOVE_HIGH
            ),
        ]
        _write_rankings(snap_dir, rows)
        _write_csv(snap_dir / "review_queue.csv", [{"ticker": "STRONG"}])

        result = build_options_watch(
            "2026-03-27",
            mode="pre_open",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        tickers = [r["ticker"] for r in result["rows"]]
        assert "STRONG" in tickers

    def test_pre_open_excludes_low_priority(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        # Tier A 20d name but not in review/trade/positions — priority 5
        rows = [
            _ranking_row(
                ticker="LOWP",
                tier_dev="A",
                catalyst_days="20",
                is_hard_catalyst="0",
                atm_iv_change_5d="0.15",
                actual_implied_move_pctile="0.85",
            ),
        ]
        _write_rankings(snap_dir, rows)

        result = build_options_watch(
            "2026-03-27",
            mode="pre_open",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        # Priority 5 excluded in pre_open unless hard-catalyst <= 14d
        assert len(result["rows"]) == 0

    def test_pre_open_includes_hard_catalyst_14d(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        rows = [
            _ranking_row(
                ticker="NEAR",
                tier_dev="B",
                catalyst_days="10",
                is_hard_catalyst="1",
                atm_iv_change_5d="0.15",
                opt_event_premium="YES",
            ),
        ]
        _write_rankings(snap_dir, rows)
        # Not in review/trade/positions — but hard-catalyst <= 14d

        result = build_options_watch(
            "2026-03-27",
            mode="pre_open",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        tickers = [r["ticker"] for r in result["rows"]]
        assert "NEAR" in tickers

    def test_writes_artifacts(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        rows = [_ranking_row(ticker="AAA")]
        _write_rankings(snap_dir, rows)

        build_options_watch(
            "2026-03-27",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        json_path = artifacts_dir / "options_watch" / "2026-03-27_watch.json"
        md_path = artifacts_dir / "options_watch" / "2026-03-27_watch.md"
        assert json_path.exists()
        assert md_path.exists()

        # Verify JSON roundtrips
        loaded = json.loads(json_path.read_text())
        assert loaded["schema"] == SCHEMA_VERSION

    def test_premarket_artifact_names(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        rows = [_ranking_row(ticker="AAA")]
        _write_rankings(snap_dir, rows)
        _write_csv(snap_dir / "review_queue.csv", [{"ticker": "AAA"}])

        build_options_watch(
            "2026-03-27",
            mode="pre_open",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        assert (artifacts_dir / "options_watch" / "2026-03-27_premarket_watch.json").exists()
        assert (artifacts_dir / "options_watch" / "2026-03-27_premarket_watch.md").exists()

    def test_sort_order(self, tmp_path):
        snap_dir = tmp_path / "snapshots" / "2026-03-27"
        artifacts_dir = tmp_path / "artifacts"

        rows = [
            _ranking_row(
                ticker="LOW_PRI",
                actionable_rank="5",
                catalyst_days="10",
                atm_iv_change_5d="0.02",
                actual_implied_move_pctile="0.40",
                opt_event_premium="NO",
                opt_term_slope="0.05",
            ),
            _ranking_row(
                ticker="HIGH_PRI",
                actionable_rank="15",
                catalyst_days="10",
                atm_iv_change_5d="0.15",
                actual_implied_move_pctile="0.90",
            ),
        ]
        _write_rankings(snap_dir, rows)

        result = build_options_watch(
            "2026-03-27",
            snapshots_dir=tmp_path / "snapshots",
            artifacts_dir=artifacts_dir,
        )

        tickers = [r["ticker"] for r in result["rows"]]
        assert tickers[0] == "HIGH_PRI"  # higher priority_score


# ---------------------------------------------------------------------------
# Markdown formatting
# ---------------------------------------------------------------------------
class TestFormatMd:
    def test_basic_formatting(self):
        d = {
            "as_of_date": "2026-03-27",
            "mode": "post_packet",
            "watchlist_size": 1,
            "n_eligible": 1,
            "n_flagged": 1,
            "n_suppressed": 0,
            "sources": {"review_queue": 1, "trade_plan": 0, "positions": 5, "catalyst_delta": 0},
            "generated_at": "2026-03-27T00:00:00Z",
            "rows": [
                {
                    "ticker": "TEST",
                    "tier": "A",
                    "actionable_rank": 5,
                    "catalyst_days": 10,
                    "catalyst_family": "CLINICAL",
                    "is_hard_catalyst": 1,
                    "opt_atm_iv": 0.50,
                    "opt_term_slope": -0.12,
                    "opt_rr_25d": 0.03,
                    "actual_implied_move_pctile": 0.85,
                    "atm_iv_change_5d": 0.15,
                    "opt_iv_regime": "NORMAL",
                    "flags": ["SURFACE_MOVE_HIGH", "IV_RAMP_HIGH"],
                    "priority_score": 3,
                    "why": "review queue, hard catalyst 10d, high implied move + rising IV",
                }
            ],
            "suppressed": [],
        }
        md = format_watch_md(d)
        assert "Post-Packet" in md
        assert "TEST" in md
        assert "SURFACE_MOVE_HIGH" in md

    def test_pre_open_label(self):
        d = {
            "as_of_date": "2026-03-27",
            "mode": "pre_open",
            "watchlist_size": 0,
            "n_eligible": 0,
            "n_flagged": 0,
            "n_suppressed": 0,
            "sources": {"review_queue": 0, "trade_plan": 0, "positions": 0, "catalyst_delta": 0},
            "generated_at": "",
            "rows": [],
            "suppressed": [],
        }
        md = format_watch_md(d)
        assert "Pre-Open" in md
