"""Tests for the rank-change monitor soak-window audit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.audit_rank_change_monitor import (
    EXPECTED_V2_COHORT_SIZE,
    REPEAT_OFFENDER_THRESHOLD,
    aggregate,
    collect,
    derive_observations,
)


def write_alerts(snapshots_dir: Path, date: str, payload: dict) -> None:
    target = snapshots_dir / date
    target.mkdir(parents=True, exist_ok=True)
    (target / "rank_change_alerts.json").write_text(json.dumps(payload), encoding="utf-8")


def make_alerts_payload(
    *,
    as_of: str,
    prior: str,
    n_critical: int = 0,
    n_warn: int = 0,
    n_watch: int = 0,
    cohort_churn_pct: float = 5.0,
    cohort_size: int = EXPECTED_V2_COHORT_SIZE,
    integrity_ok: bool = True,
    system_alerts=None,
    alerts=None,
) -> dict:
    return {
        "schema_version": "rank_change_monitor.v1",
        "as_of_date": as_of,
        "prior_date": prior,
        "summary": {
            "n_ticker_alerts": n_critical + n_warn + n_watch,
            "n_critical": n_critical,
            "n_warn": n_warn,
            "n_watch": n_watch,
            "cohort_churn_pct": cohort_churn_pct,
            "curr_cohort_size": cohort_size,
        },
        "system_alerts": system_alerts or [],
        "alerts": alerts or [],
        "integrity": {"current": {"ok": integrity_ok}},
    }


def test_collect_reports_missing_weekday_files(tmp_path):
    snap = tmp_path / "snapshots"
    # 2026-04-27 (Mon) and 2026-04-29 (Wed) present, 2026-04-28 (Tue) missing
    write_alerts(snap, "2026-04-27", make_alerts_payload(as_of="2026-04-27", prior="2026-04-24"))
    write_alerts(snap, "2026-04-29", make_alerts_payload(as_of="2026-04-29", prior="2026-04-28"))
    cov = collect(snap, "2026-04-27", "2026-04-29")
    assert cov["expected"] == ["2026-04-27", "2026-04-28", "2026-04-29"]
    assert "2026-04-28" in cov["missing"]
    assert sorted(cov["present"]) == ["2026-04-27", "2026-04-29"]


def test_collect_excludes_weekends_from_expected(tmp_path):
    snap = tmp_path / "snapshots"
    cov = collect(snap, "2026-04-25", "2026-04-26")  # Sat + Sun
    assert cov["expected"] == []
    assert cov["missing"] == []


def test_aggregate_severity_rollup(tmp_path):
    snap = tmp_path / "snapshots"
    # Mon: clean. Tue: 1 CRITICAL, 5 WARN, 30 WATCH. Wed: 8 WARN.
    write_alerts(
        snap,
        "2026-04-27",
        make_alerts_payload(as_of="2026-04-27", prior="2026-04-24", cohort_churn_pct=3.0),
    )
    write_alerts(
        snap,
        "2026-04-28",
        make_alerts_payload(
            as_of="2026-04-28",
            prior="2026-04-27",
            n_critical=1,
            n_warn=5,
            n_watch=30,
            cohort_churn_pct=12.5,
            alerts=[
                {
                    "ticker": "ERAS",
                    "severity": "WARN",
                    "likely_reason": "ranker_v2_cohort_dropout",
                    "flags": ["cohort_exit", "rank_delta_+47"],
                },
                {
                    "ticker": "ABSI",
                    "severity": "WARN",
                    "likely_reason": "ranker_v2_cohort_dropout",
                    "flags": ["cohort_exit"],
                },
                {
                    "ticker": "BIIB",
                    "severity": "WARN",
                    "likely_reason": "ranker_v2_cohort_dropout",
                    "flags": ["cohort_exit"],
                },
                {
                    "ticker": "TARS",
                    "severity": "WARN",
                    "likely_reason": "ranker_v2_cohort_dropout",
                    "flags": ["cohort_exit"],
                },
                {
                    "ticker": "SLN",
                    "severity": "WARN",
                    "likely_reason": "ranker_v2_cohort_dropout",
                    "flags": ["cohort_exit", "top30_exit"],
                },
                {
                    "ticker": "XYZ",
                    "severity": "CRITICAL",
                    "likely_reason": "eligibility_change",
                    "flags": ["eligible:1→0"],
                },
            ],
        ),
    )
    write_alerts(
        snap,
        "2026-04-29",
        make_alerts_payload(
            as_of="2026-04-29",
            prior="2026-04-28",
            n_warn=8,
            cohort_churn_pct=11.0,
            alerts=[
                {
                    "ticker": "ERAS",
                    "severity": "WARN",
                    "likely_reason": "ranker_v2_cohort_dropout",
                    "flags": ["cohort_exit"],
                },
                {
                    "ticker": "ERAS_DUP",
                    "severity": "WARN",
                    "likely_reason": "selector_score_move",
                    "flags": ["rank_delta_+15"],
                },
            ]
            + [
                {
                    "ticker": f"X{i}",
                    "severity": "WARN",
                    "likely_reason": "selector_score_move",
                    "flags": ["rank_delta_+12"],
                }
                for i in range(6)
            ],
        ),
    )

    cov = collect(snap, "2026-04-27", "2026-04-29")
    agg = aggregate(cov["days"])
    assert agg["n_days"] == 3
    assert agg["total_critical"] == 1
    assert agg["total_warn"] == 13
    assert agg["total_watch"] == 30
    assert agg["integrity_ok_days"] == 3
    assert agg["cohort_churn"]["max_pct"] == 12.5
    assert agg["cohort_churn"]["days_above_threshold"] == 2  # 12.5 and 11.0

    top = dict(agg["top_warn_reasons"])
    assert top.get(("WARN", "ranker_v2_cohort_dropout")) == 6  # 5 on Tue + 1 on Wed
    assert top.get(("CRITICAL", "eligibility_change")) == 1


def test_repeat_offender_detection(tmp_path):
    snap = tmp_path / "snapshots"
    # ERAS flagged WARN on 4 weekday alert files; threshold = 3
    for d in ["2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30"]:
        write_alerts(
            snap,
            d,
            make_alerts_payload(
                as_of=d,
                prior="prev",
                n_warn=1,
                alerts=[
                    {
                        "ticker": "ERAS",
                        "severity": "WARN",
                        "likely_reason": "ranker_v2_cohort_dropout",
                        "flags": ["cohort_exit"],
                    }
                ],
            ),
        )
    cov = collect(snap, "2026-04-27", "2026-04-30")
    agg = aggregate(cov["days"])
    offenders = {r["ticker"]: r for r in agg["repeat_offenders"]}
    assert "ERAS" in offenders
    assert offenders["ERAS"]["warn_days"] == 4
    assert offenders["ERAS"]["warn_days"] >= REPEAT_OFFENDER_THRESHOLD


def test_observations_flag_dominant_cohort_reason(tmp_path):
    snap = tmp_path / "snapshots"
    # 80% of WARN+CRITICAL are ranker_v2_cohort_dropout → expect REASON-MIX warning
    write_alerts(
        snap,
        "2026-04-27",
        make_alerts_payload(
            as_of="2026-04-27",
            prior="2026-04-24",
            n_warn=10,
            alerts=[
                {
                    "ticker": f"T{i}",
                    "severity": "WARN",
                    "likely_reason": "ranker_v2_cohort_dropout",
                    "flags": ["cohort_exit"],
                }
                for i in range(8)
            ]
            + [
                {
                    "ticker": f"T{i}",
                    "severity": "WARN",
                    "likely_reason": "selector_score_move",
                    "flags": ["rank_delta_+12"],
                }
                for i in range(8, 10)
            ],
        ),
    )
    cov = collect(snap, "2026-04-27", "2026-04-27")
    agg = aggregate(cov["days"])
    obs_blob = " ".join(derive_observations(agg, cov))
    assert "REASON-MIX" in obs_blob
    assert "ranker_v2_cohort_dropout" in obs_blob


def test_observations_flag_missing_coverage(tmp_path):
    snap = tmp_path / "snapshots"
    # Only Mon present, Tue/Wed missing — expect explicit COVERAGE warning
    write_alerts(snap, "2026-04-27", make_alerts_payload(as_of="2026-04-27", prior="2026-04-24"))
    cov = collect(snap, "2026-04-27", "2026-04-29")
    agg = aggregate(cov["days"])
    obs_blob = " ".join(derive_observations(agg, cov))
    assert "COVERAGE" in obs_blob
    assert "missing days bias" in obs_blob


def test_integrity_failure_propagates_to_observations(tmp_path):
    snap = tmp_path / "snapshots"
    write_alerts(
        snap,
        "2026-04-27",
        make_alerts_payload(as_of="2026-04-27", prior="2026-04-24", integrity_ok=False),
    )
    cov = collect(snap, "2026-04-27", "2026-04-27")
    agg = aggregate(cov["days"])
    assert "2026-04-27" in agg["integrity_fail_days"]
    obs_blob = " ".join(derive_observations(agg, cov))
    assert "INTEGRITY" in obs_blob
