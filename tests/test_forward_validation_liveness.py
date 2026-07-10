"""Tests for the forward-validation liveness monitor (SM-20260629-001)."""

from __future__ import annotations

import tools.forward_validation_liveness_monitor as m


def _live(date):
    return {
        "date": date,
        "capture_mode": "LIVE",
        "quality_status": "PASS",
        "model_hash_match": True,
        "benchmark_available": True,
        "model_hash": "live-model-hash",
        "top30": [{"ticker": t} for t in ("AAA", "BBB", "CCC")],
    }


# --- stale_live_capture ----------------------------------------------------
def test_stale_when_no_live_capture_in_last_two_days():
    alerts = m.check_stale_live_capture(["2026-07-08", "2026-07-09"], live_clean_dates=set())
    assert alerts and alerts[0]["alert"] == "stale_live_capture"


def test_not_stale_when_recent_live_capture_exists():
    assert m.check_stale_live_capture(["2026-07-08", "2026-07-09"], {"2026-07-09"}) == []


def test_stale_needs_two_completed_days():
    assert m.check_stale_live_capture(["2026-07-09"], set()) == []


# --- candidate_hash_mismatch ----------------------------------------------
def test_hash_mismatch_alerts():
    cap = {"date": "2026-07-09", "model_hash": "aaaaaaaaaaaaaaaa"}
    alerts = m.check_candidate_hash_mismatch(cap, {"model_hash": "bbbbbbbbbbbbbbbb"})
    assert alerts and alerts[0]["alert"] == "candidate_hash_mismatch"


def test_hash_match_ok():
    cap = {"date": "2026-07-09", "model_hash": "abc"}
    assert m.check_candidate_hash_mismatch(cap, {"model_hash": "abc"}) == []


# --- xbi_freshness ---------------------------------------------------------
def test_xbi_missing_alerts():
    assert m.check_xbi_freshness(None, ["2026-07-09"])[0]["alert"] == "xbi_freshness"


def test_xbi_stale_alerts():
    alerts = m.check_xbi_freshness("2026-07-07", ["2026-07-08", "2026-07-09"])
    assert alerts and alerts[0]["alert"] == "xbi_freshness"


def test_xbi_fresh_ok():
    assert m.check_xbi_freshness("2026-07-09", ["2026-07-08", "2026-07-09"]) == []


# --- rankings_mismatch -----------------------------------------------------
def test_rankings_mismatch_alerts():
    cap = {"date": "2026-07-09", "top30": [{"ticker": "AAA"}, {"ticker": "BBB"}]}
    alerts = m.check_rankings_mismatch(cap, ["AAA", "ZZZ"])
    assert alerts and alerts[0]["alert"] == "rankings_mismatch"


def test_rankings_match_ok():
    cap = {"date": "2026-07-09", "top30": [{"ticker": "AAA"}, {"ticker": "BBB"}]}
    assert m.check_rankings_mismatch(cap, ["BBB", "AAA"]) == []


# --- duplicate_capture -----------------------------------------------------
def test_duplicate_capture_alerts():
    caps = [{"date": "2026-07-09"}, {"date": "2026-07-09"}, {"date": "2026-07-08"}]
    alerts = m.check_duplicate_captures(caps)
    assert alerts and "2026-07-09" in alerts[0]["detail"]


def test_no_duplicate_ok():
    assert m.check_duplicate_captures([{"date": "2026-07-09"}, {"date": "2026-07-08"}]) == []


# --- hardfail_skipped_capture ---------------------------------------------
def test_hardfail_without_capture_alerts():
    alerts = m.check_hardfail_skipped_capture(["2026-07-09"], {"2026-07-09": "FAIL"}, captured_dates=set())
    assert alerts and alerts[0]["alert"] == "hardfail_skipped_capture"


def test_hardfail_with_capture_ok():
    assert m.check_hardfail_skipped_capture(["2026-07-09"], {"2026-07-09": "FAIL"}, {"2026-07-09"}) == []


def test_pass_status_ok():
    assert m.check_hardfail_skipped_capture(["2026-07-09"], {"2026-07-09": "WARN"}, set()) == []


# --- evaluate integration --------------------------------------------------
def test_evaluate_healthy_scenario_no_alerts():
    completed = ["2026-07-08", "2026-07-09"]
    captures = [_live("2026-07-08"), _live("2026-07-09")]
    alerts = m.evaluate(
        completed_dates=completed,
        captures=captures,
        candidate={"model_hash": "live-model-hash"},
        xbi_last_date="2026-07-09",
        snapshot_top30=["AAA", "BBB", "CCC"],
        snapshot_status={"2026-07-08": "WARN", "2026-07-09": "WARN"},
    )
    assert alerts == []


def test_evaluate_broken_scenario_flags_multiple():
    completed = ["2026-07-08", "2026-07-09"]
    # only replay captures, stale XBI, hash drift, a hard-failed day
    replay = {**_live("2026-07-08"), "capture_mode": "REPLAY", "model_hash": "aaaaaaaaaaaaaaaa"}
    alerts = m.evaluate(
        completed_dates=completed,
        captures=[replay],
        candidate={"model_hash": "live-model-hash"},
        xbi_last_date="2026-07-01",
        snapshot_top30=["AAA", "BBB", "CCC"],
        snapshot_status={"2026-07-09": "FAIL"},
    )
    kinds = {a["alert"] for a in alerts}
    assert {"stale_live_capture", "candidate_hash_mismatch", "xbi_freshness", "hardfail_skipped_capture"} <= kinds
