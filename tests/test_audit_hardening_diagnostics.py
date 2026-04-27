"""Tests for the hardening diagnostics audit (read-only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.audit_hardening_diagnostics import (
    aggregate_drift,
    aggregate_feature_coverage,
    aggregate_integrity,
    aggregate_sentinel,
    collect,
    derive_observations,
)


def write_artifacts(snapshots_dir: Path, date: str, payloads: dict[str, dict]) -> None:
    target = snapshots_dir / date
    target.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (target / name).write_text(json.dumps(payload), encoding="utf-8")


def integrity_payload(severity: str = "PASS", failed: list[str] | None = None) -> dict:
    return {
        "overall_severity": severity,
        "checks": [{"name": n, "severity": "FAIL"} for n in (failed or [])]
        + [{"name": "rank_space_integrity", "severity": severity}],
    }


def feature_payload(features: list[tuple[str, float, str]]) -> dict:
    return {"features": [{"feature": name, "pct_present": pct, "severity": sev} for name, pct, sev in features]}


def drift_payload(top30: float, top60: float, cohort: float) -> dict:
    return {
        "turnover": {
            "top30": {"turnover_pct": top30},
            "top60": {"turnover_pct": top60},
            "v2_cohort": {"turnover_pct": cohort},
        }
    }


def sentinel_payload(records: list[dict]) -> dict:
    return {"records": records}


# ---------------------------------------------------------------------------


def test_collect_reports_fully_missing_days(tmp_path):
    snap = tmp_path / "snap"
    write_artifacts(
        snap,
        "2026-04-28",
        {"snapshot_integrity_report.json": integrity_payload()},
    )
    cov = collect(snap, "2026-04-27", "2026-04-29")
    # 04-27 Mon, 04-28 Tue, 04-29 Wed all weekdays
    assert cov["expected"] == ["2026-04-27", "2026-04-28", "2026-04-29"]
    assert "2026-04-27" in cov["fully_missing"]
    assert "2026-04-29" in cov["fully_missing"]
    assert cov["present_dates"] == ["2026-04-28"]


def test_collect_reports_partial_missing(tmp_path):
    snap = tmp_path / "snap"
    write_artifacts(
        snap,
        "2026-04-28",
        {"snapshot_integrity_report.json": integrity_payload()},  # no other artifacts
    )
    cov = collect(snap, "2026-04-28", "2026-04-28")
    assert "2026-04-28" in cov["partial_missing"]
    assert "feature_coverage_report.json" in cov["partial_missing"]["2026-04-28"]


def test_aggregate_integrity_counts_severities(tmp_path):
    snap = tmp_path / "snap"
    write_artifacts(snap, "2026-04-28", {"snapshot_integrity_report.json": integrity_payload("PASS")})
    write_artifacts(
        snap, "2026-04-29", {"snapshot_integrity_report.json": integrity_payload("FAIL", ["rank_space_integrity"])}
    )
    cov = collect(snap, "2026-04-28", "2026-04-29")
    agg = aggregate_integrity(cov["days"])
    assert agg["severity_counts"] == {"PASS": 1, "FAIL": 1}
    assert agg["fail_days"][0]["date"] == "2026-04-29"
    assert agg["top_failing_checks"][0][0] == "rank_space_integrity"


def test_aggregate_feature_coverage_sorts_by_worst_min(tmp_path):
    snap = tmp_path / "snap"
    write_artifacts(
        snap,
        "2026-04-28",
        {"feature_coverage_report.json": feature_payload([("market_cap_mm", 100.0, "PASS"), ("pcr", 0.0, "INFO")])},
    )
    write_artifacts(
        snap,
        "2026-04-29",
        {"feature_coverage_report.json": feature_payload([("market_cap_mm", 100.0, "PASS"), ("pcr", 30.0, "INFO")])},
    )
    cov = collect(snap, "2026-04-28", "2026-04-29")
    agg = aggregate_feature_coverage(cov["days"])
    assert agg["features"][0]["feature"] == "pcr"  # worst min comes first
    assert agg["features"][0]["min_pct"] == 0.0
    assert agg["features"][0]["max_pct"] == 30.0


def test_aggregate_drift_collects_turnover_stats(tmp_path):
    snap = tmp_path / "snap"
    write_artifacts(snap, "2026-04-28", {"distribution_drift_report.json": drift_payload(10.0, 8.0, 5.0)})
    write_artifacts(
        snap, "2026-04-29", {"distribution_drift_report.json": drift_payload(30.0, 25.0, 22.0)}
    )  # high churn
    cov = collect(snap, "2026-04-28", "2026-04-29")
    agg = aggregate_drift(cov["days"])
    assert agg["top30"]["n"] == 2
    assert agg["top30"]["max"] == 30.0
    assert len(agg["high_churn_days"]) == 1
    assert agg["high_churn_days"][0]["date"] == "2026-04-29"


def test_aggregate_sentinel_counts_transitions(tmp_path):
    snap = tmp_path / "snap"
    write_artifacts(
        snap,
        "2026-04-28",
        {
            "sentinel_ticker_report.json": sentinel_payload(
                [
                    {"ticker": "ERAS", "rank_delta": -45, "cohort_transition": "out_of_cohort→in_cohort"},
                    {"ticker": "ARVN", "rank_delta": 2, "cohort_transition": None},
                ]
            )
        },
    )
    write_artifacts(
        snap,
        "2026-04-29",
        {
            "sentinel_ticker_report.json": sentinel_payload(
                [
                    {"ticker": "ERAS", "rank_delta": 5, "cohort_transition": None},
                    {"ticker": "ARVN", "rank_delta": 1, "cohort_transition": None},
                ]
            )
        },
    )
    cov = collect(snap, "2026-04-28", "2026-04-29")
    agg = aggregate_sentinel(cov["days"])
    by_ticker = {r["ticker"]: r for r in agg["per_ticker"]}
    assert by_ticker["ERAS"]["n_cohort_transitions"] == 1
    assert by_ticker["ERAS"]["abs_max_rank_delta"] == 45
    assert by_ticker["ARVN"]["n_cohort_transitions"] == 0


def test_observations_call_out_missing_coverage(tmp_path):
    snap = tmp_path / "snap"
    write_artifacts(snap, "2026-04-28", {"snapshot_integrity_report.json": integrity_payload()})
    cov = collect(snap, "2026-04-27", "2026-04-29")
    aggs = {
        "integrity": aggregate_integrity(cov["days"]),
        "feature_coverage": aggregate_feature_coverage(cov["days"]),
        "drift": aggregate_drift(cov["days"]),
        "sentinel": aggregate_sentinel(cov["days"]),
    }
    obs = " ".join(derive_observations(cov, aggs))
    assert "COVERAGE" in obs
    assert "missing days bias" in obs


def test_end_to_end_with_json_out(tmp_path):
    snap = tmp_path / "snap"
    for d in ["2026-04-27", "2026-04-28"]:
        write_artifacts(
            snap,
            d,
            {
                "snapshot_integrity_report.json": integrity_payload(),
                "feature_coverage_report.json": feature_payload([("market_cap_mm", 100.0, "PASS")]),
                "distribution_drift_report.json": drift_payload(10.0, 8.0, 5.0),
                "sentinel_ticker_report.json": sentinel_payload(
                    [
                        {"ticker": "ERAS", "rank_delta": -10, "cohort_transition": None},
                    ]
                ),
            },
        )
    out_path = tmp_path / "audit.json"
    from tools.audit_hardening_diagnostics import main

    rc = main(
        [
            "--snapshots-dir",
            str(snap),
            "--start-date",
            "2026-04-27",
            "--end-date",
            "2026-04-28",
            "--json-out",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["window"]["start"] == "2026-04-27"
    assert payload["aggregate"]["integrity"]["severity_counts"]["PASS"] == 2
