"""Tests for the deterministic rank-change monitor (read-only diagnostic)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_rank_change_monitor import (
    EXPECTED_V2_COHORT_SIZE,
    build_alerts,
    build_rank_change_monitor,
    check_integrity,
    cohort_set,
    find_prior_date,
    pick_primary_reason,
    top_set,
    write_outputs,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

BASE_FIELDS = {
    "ticker": "",
    "company_name": "",
    "actionable_rank": "",
    "tier_any": "",
    "stage_bucket": "",
    "catalyst_days": "",
    "ranker_v2_score": "",
    "ranker_v2_rank": "",
    "selector_score": "",
    "final_score": "",
    "composite_score": "",
    "eligible": "1",
}


def row(**kwargs) -> dict[str, str]:
    out = dict(BASE_FIELDS)
    out.update({k: ("" if v is None else str(v)) for k, v in kwargs.items()})
    return out


def make_rows(*specs) -> dict[str, dict[str, str]]:
    return {s["ticker"]: row(**s) for s in specs}


def write_snapshot(snap_dir: Path, date: str, rows: list[dict[str, str]]) -> None:
    target = snap_dir / date
    target.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    cols = list(rows[0].keys())
    with open(target / "rankings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_cohort_set_uses_ranker_v2_score_presence():
    rows = make_rows(
        {"ticker": "AAA", "ranker_v2_score": 0.6},
        {"ticker": "BBB", "ranker_v2_score": ""},
    )
    assert cohort_set(rows) == {"AAA"}


def test_top_set_orders_by_actionable_rank():
    rows = make_rows(
        {"ticker": "AAA", "actionable_rank": 5},
        {"ticker": "BBB", "actionable_rank": 1},
        {"ticker": "CCC", "actionable_rank": 3},
        {"ticker": "DDD", "actionable_rank": ""},
    )
    assert top_set(rows, 2) == {"BBB", "CCC"}


def test_pick_primary_reason_priority():
    assert pick_primary_reason(["tier_change", "ranker_v2_cohort_dropout"]) == "ranker_v2_cohort_dropout"
    assert pick_primary_reason(["selector_score_move", "tier_change"]) == "selector_score_move"
    assert pick_primary_reason([]) == "unknown"


def test_check_integrity_dense_ok():
    rows = make_rows(
        {"ticker": "AAA", "actionable_rank": 1},
        {"ticker": "BBB", "actionable_rank": 2},
        {"ticker": "CCC", "actionable_rank": 3},
    )
    r = check_integrity(rows)
    assert r["ok"] is True
    assert r["duplicate_ranks"] == {}
    assert r["missing_ranks"] == []


def test_check_integrity_detects_duplicates_and_gaps():
    rows = make_rows(
        {"ticker": "AAA", "actionable_rank": 1},
        {"ticker": "BBB", "actionable_rank": 1},
        {"ticker": "CCC", "actionable_rank": 4},
    )
    r = check_integrity(rows)
    assert r["ok"] is False
    assert 1 in r["duplicate_ranks"]
    assert sorted(r["duplicate_ranks"][1]) == ["AAA", "BBB"]
    assert 2 in r["missing_ranks"] and 3 in r["missing_ranks"]


# ---------------------------------------------------------------------------
# Flag-rule tests
# ---------------------------------------------------------------------------


def _eras_pair():
    """Reproduce the ERAS pattern: cohort dropout with stable composite."""
    prev = make_rows(
        {
            "ticker": "ERAS",
            "company_name": "Erasca, Inc.",
            "actionable_rank": 16,
            "tier_any": "A",
            "ranker_v2_score": 0.6323,
            "selector_score": 0.7578,
            "final_score": 0.6323,
            "composite_score": 0.0599,
        }
    )
    curr = make_rows(
        {
            "ticker": "ERAS",
            "company_name": "Erasca, Inc.",
            "actionable_rank": 63,
            "tier_any": "A",
            "ranker_v2_score": "",
            "selector_score": 0.7182,
            "final_score": 7.18e-05,
            "composite_score": 0.0599,
        }
    )
    return prev, curr


def test_eras_style_cohort_dropout():
    prev, curr = _eras_pair()
    payload = build_alerts(prev, curr)
    eras_alerts = [a for a in payload["alerts"] if a["ticker"] == "ERAS"]
    assert len(eras_alerts) == 1
    a = eras_alerts[0]
    assert a["likely_reason"] == "ranker_v2_cohort_dropout"
    assert "cohort_exit" in a["flags"]
    assert "final_collapse_composite_stable" in a["flags"]
    assert a["rank_delta"] == 47
    assert a["severity"] == "WARN"
    assert a["cohort_membership_change"] == "exited"


def test_top30_entry_and_exit_flagged():
    prev_specs = [{"ticker": f"T{i:03d}", "actionable_rank": i} for i in range(1, 31)]
    curr_specs = [{"ticker": f"T{i:03d}", "actionable_rank": i} for i in range(2, 32)]
    # T001 drops out (rank 1 → ranked 999); NEW001 enters at rank 1
    prev_specs.append({"ticker": "NEW001", "actionable_rank": 50})
    curr_specs.append({"ticker": "NEW001", "actionable_rank": 1})
    curr_specs[0] = {"ticker": "T001", "actionable_rank": 99}  # demote T001
    prev = {s["ticker"]: row(**s) for s in prev_specs}
    curr = {s["ticker"]: row(**s) for s in curr_specs}

    payload = build_alerts(prev, curr)
    flags_by_ticker = {a["ticker"]: a["flags"] for a in payload["alerts"]}
    assert "top30_exit" in flags_by_ticker.get("T001", [])
    assert "top30_entry" in flags_by_ticker.get("NEW001", [])


def test_duplicate_rank_raises_critical_system_alert():
    prev = make_rows(
        {"ticker": "AAA", "actionable_rank": 1},
        {"ticker": "BBB", "actionable_rank": 2},
    )
    curr = make_rows(
        {"ticker": "AAA", "actionable_rank": 1},
        {"ticker": "BBB", "actionable_rank": 1},
    )
    payload = build_alerts(prev, curr)
    kinds = {sa["kind"]: sa["severity"] for sa in payload["system_alerts"]}
    assert kinds.get("duplicate_actionable_rank") == "CRITICAL"


def test_cohort_churn_threshold_fires_warning():
    # 60-name cohort with 10 names rotated out and 10 new ones in → 33% churn
    prev_specs = [
        {"ticker": f"OLD{i:02d}", "actionable_rank": i, "ranker_v2_score": 0.6, "final_score": 0.6}
        for i in range(1, 61)
    ]
    curr_specs = [
        {"ticker": f"OLD{i:02d}", "actionable_rank": i, "ranker_v2_score": 0.6, "final_score": 0.6}
        for i in range(11, 61)
    ] + [
        {"ticker": f"NEW{i:02d}", "actionable_rank": 60 + i, "ranker_v2_score": 0.6, "final_score": 0.6}
        for i in range(1, 11)
    ]
    prev = {s["ticker"]: row(**s) for s in prev_specs}
    curr = {s["ticker"]: row(**s) for s in curr_specs}
    payload = build_alerts(prev, curr)
    sys_kinds = {sa["kind"] for sa in payload["system_alerts"]}
    assert "cohort_churn" in sys_kinds
    assert payload["summary"]["cohort_churn_pct"] >= 10.0


def test_v2_cohort_size_off_target_is_critical():
    # 59 names with v2 score (expected 60) → CRITICAL system alert
    prev_specs = [{"ticker": f"T{i:02d}", "actionable_rank": i, "ranker_v2_score": 0.6} for i in range(1, 61)]
    curr_specs = [{"ticker": f"T{i:02d}", "actionable_rank": i, "ranker_v2_score": 0.6} for i in range(1, 60)] + [
        {"ticker": "T60", "actionable_rank": 60, "ranker_v2_score": ""}
    ]
    prev = {s["ticker"]: row(**s) for s in prev_specs}
    curr = {s["ticker"]: row(**s) for s in curr_specs}
    payload = build_alerts(prev, curr)
    kinds = {sa["kind"]: sa for sa in payload["system_alerts"]}
    assert "v2_cohort_size" in kinds
    assert kinds["v2_cohort_size"]["severity"] == "CRITICAL"
    assert kinds["v2_cohort_size"]["actual"] == 59
    assert kinds["v2_cohort_size"]["expected"] == EXPECTED_V2_COHORT_SIZE


def test_a_tier_exit_top60_only_fires_on_actual_exit():
    prev = make_rows(
        {"ticker": "INSIDE", "actionable_rank": 50, "tier_any": "A"},
        {"ticker": "OUTSIDE", "actionable_rank": 100, "tier_any": "A"},
    )
    curr = make_rows(
        {"ticker": "INSIDE", "actionable_rank": 70, "tier_any": "A"},
        {"ticker": "OUTSIDE", "actionable_rank": 105, "tier_any": "A"},
    )
    payload = build_alerts(prev, curr)
    flags_by_ticker = {a["ticker"]: a["flags"] for a in payload["alerts"]}
    assert "a_tier_exit_top60" in flags_by_ticker.get("INSIDE", [])
    # OUTSIDE was already past 60 — must not fire
    assert "a_tier_exit_top60" not in flags_by_ticker.get("OUTSIDE", [])


def test_minor_rank_move_is_not_flagged():
    prev = make_rows({"ticker": "AAA", "actionable_rank": 50, "tier_any": "B"})
    curr = make_rows({"ticker": "AAA", "actionable_rank": 53, "tier_any": "B"})
    payload = build_alerts(prev, curr)
    assert payload["alerts"] == []


def test_final_collapse_floor_noise_suppressed():
    """Tickers near the rank-bottom can have tiny final scores swing wildly.

    A 99% drop from 5e-05 to 1e-06 must NOT trigger
    final_collapse_composite_stable — the prev value is below FINAL_COLLAPSE_PREV_MIN.
    """
    prev = make_rows({"ticker": "FLOOR", "actionable_rank": 220, "final_score": 5e-05, "composite_score": 0.001})
    curr = make_rows({"ticker": "FLOOR", "actionable_rank": 221, "final_score": 1e-06, "composite_score": 0.001})
    payload = build_alerts(prev, curr)
    assert payload["alerts"] == []


# ---------------------------------------------------------------------------
# Integration tests (end-to-end via tmp_path)
# ---------------------------------------------------------------------------


def test_no_prior_snapshot_falls_back_gracefully(tmp_path):
    snap_dir = tmp_path / "snapshots"
    today = "2026-04-25"
    write_snapshot(
        snap_dir,
        today,
        list(make_rows({"ticker": "AAA", "actionable_rank": 1, "ranker_v2_score": 0.6}).values()),
    )
    payload = build_rank_change_monitor(today, prior_date=None, snapshots_dir=snap_dir)
    assert payload["prior_date"] is None
    assert payload["alerts"] == []
    assert payload["system_alerts"] == []
    assert "note" in payload
    assert payload["summary"]["curr_cohort_size"] == 1


def test_find_prior_date_picks_most_recent(tmp_path):
    snap_dir = tmp_path / "snapshots"
    for d in ["2026-04-20", "2026-04-22", "2026-04-23"]:
        write_snapshot(snap_dir, d, list(make_rows({"ticker": "X", "actionable_rank": 1}).values()))
    assert find_prior_date(snap_dir, "2026-04-25") == "2026-04-23"
    assert find_prior_date(snap_dir, "2026-04-22") == "2026-04-20"
    assert find_prior_date(snap_dir, "2026-04-20") is None


def test_end_to_end_writes_three_artifacts(tmp_path):
    snap_dir = tmp_path / "snapshots"
    write_snapshot(
        snap_dir,
        "2026-04-24",
        list(_eras_pair()[0].values()),
    )
    write_snapshot(
        snap_dir,
        "2026-04-25",
        list(_eras_pair()[1].values()),
    )
    payload = build_rank_change_monitor("2026-04-25", prior_date=None, snapshots_dir=snap_dir)
    paths = write_outputs(payload, snap_dir / "2026-04-25")
    for k in ("csv", "md", "json"):
        assert paths[k].exists()
    csv_text = paths["csv"].read_text()
    assert "ERAS" in csv_text
    assert "ranker_v2_cohort_dropout" in csv_text
    json_payload = json.loads(paths["json"].read_text())
    assert json_payload["prior_date"] == "2026-04-24"
    assert json_payload["schema_version"].startswith("rank_change_monitor")
