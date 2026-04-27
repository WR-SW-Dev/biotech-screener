"""Tests for the distribution drift report (read-only diagnostic)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_distribution_drift_report import (
    CATEGORICAL_FIELDS,
    build_drift_report,
    catalyst_days_buckets,
    cohort_set,
    distribution,
    filter_eligible,
    filter_top,
    top_n_set,
    turnover,
)


def make_row(**kw) -> dict[str, str]:
    base = {f: "" for f in CATEGORICAL_FIELDS}
    base.update(
        {
            "ticker": "",
            "company_name": "",
            "actionable_rank": "",
            "ranker_v2_score": "",
            "catalyst_days": "",
            "eligible": "",
        }
    )
    base.update({k: ("" if v is None else str(v)) for k, v in kw.items()})
    return base


def write_snap(root: Path, date: str, rows: list[dict[str, str]]) -> Path:
    target = root / date
    target.mkdir(parents=True, exist_ok=True)
    with open(target / "rankings.csv", "w", newline="", encoding="utf-8") as f:
        cols = list(rows[0].keys())
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return target


# ---------------------------------------------------------------------------


def test_distribution_counts_and_pcts():
    d = distribution(["A", "A", "B", "", "A"])
    assert d["A"]["count"] == 3
    assert d["A"]["pct"] == 60.0
    assert d["B"]["count"] == 1
    assert d["(blank)"]["count"] == 1


def test_catalyst_buckets_partition_correctly():
    rows = [make_row(ticker=f"T{i}", catalyst_days=str(d)) for i, d in enumerate([3, 14, 60, 120, 250, 400])] + [
        make_row(ticker="X", catalyst_days="")
    ]
    b = catalyst_days_buckets(rows)
    assert b["≤7"]["count"] == 1
    assert b["8-30"]["count"] == 1
    assert b["31-90"]["count"] == 1
    assert b["91-180"]["count"] == 1
    assert b["181-365"]["count"] == 1
    assert b[">365"]["count"] == 1
    assert b["(blank)"]["count"] == 1


def test_top_n_set_takes_lowest_ranks():
    rows = [
        make_row(ticker="A", actionable_rank=1),
        make_row(ticker="B", actionable_rank=5),
        make_row(ticker="C", actionable_rank=3),
        make_row(ticker="D", actionable_rank=""),
    ]
    assert top_n_set(rows, 2) == {"A", "C"}


def test_cohort_set_uses_v2_score_presence():
    rows = [
        make_row(ticker="A", ranker_v2_score=0.6),
        make_row(ticker="B", ranker_v2_score=""),
    ]
    assert cohort_set(rows) == {"A"}


def test_turnover_zero_for_identical_sets():
    s = {"A", "B", "C"}
    t = turnover(s, s)
    assert t["n_entered"] == 0
    assert t["n_exited"] == 0
    assert t["turnover_pct"] == 0.0


def test_turnover_handles_full_replacement():
    t = turnover({"A", "B"}, {"C", "D"})
    assert t["n_entered"] == 2
    assert t["n_exited"] == 2
    assert t["turnover_pct"] == 100.0


def test_filter_top_respects_actionable_rank():
    rows = [
        make_row(ticker="A", actionable_rank=1),
        make_row(ticker="B", actionable_rank=2),
        make_row(ticker="C", actionable_rank=3),
    ]
    assert {r["ticker"] for r in filter_top(rows, 2)} == {"A", "B"}


def test_filter_eligible_truthy_check():
    rows = [
        make_row(ticker="A", eligible="1"),
        make_row(ticker="B", eligible="True"),
        make_row(ticker="C", eligible="0"),
        make_row(ticker="D", eligible=""),
    ]
    assert {r["ticker"] for r in filter_eligible(rows)} == {"A", "B"}


def test_build_drift_no_prior_omits_turnover():
    rows = [make_row(ticker=f"T{i}", actionable_rank=i, eligible="1") for i in range(1, 5)]
    report = build_drift_report(rows, prev_rows=None)
    assert "turnover" not in report
    assert report["n_universe"] == 4


def test_build_drift_with_prior_includes_turnover():
    prev = [make_row(ticker=f"T{i}", actionable_rank=i, eligible="1") for i in range(1, 5)]
    curr = [
        make_row(ticker="T1", actionable_rank=1, eligible="1"),
        make_row(ticker="T9", actionable_rank=2, eligible="1"),
        make_row(ticker="T3", actionable_rank=3, eligible="1"),
        make_row(ticker="T4", actionable_rank=4, eligible="1"),
    ]
    report = build_drift_report(curr, prev_rows=prev)
    t30 = report["turnover"]["top30"]
    assert t30["n_entered"] == 1
    assert t30["n_exited"] == 1
    assert "T9" in t30["entered"]
    assert "T2" in t30["exited"]


def test_end_to_end_writes_artifacts(tmp_path):
    write_snap(
        tmp_path / "snap",
        "2026-04-25",
        [make_row(ticker=f"T{i}", actionable_rank=i, eligible="1", tier_any="A") for i in range(1, 5)],
    )
    write_snap(
        tmp_path / "snap",
        "2026-04-27",
        [make_row(ticker=f"T{i}", actionable_rank=i, eligible="1", tier_any="A") for i in range(1, 5)],
    )
    from tools.build_distribution_drift_report import main

    rc = main(
        [
            "--as-of-date",
            "2026-04-27",
            "--snapshots-dir",
            str(tmp_path / "snap"),
            "--quiet",
        ]
    )
    assert rc == 0
    snap = tmp_path / "snap" / "2026-04-27"
    assert (snap / "distribution_drift_report.json").exists()
    assert (snap / "distribution_drift_report.md").exists()
    payload = json.loads((snap / "distribution_drift_report.json").read_text())
    assert payload["prior_date"] == "2026-04-25"
    assert "top30_distributions" in payload


def test_no_prior_snapshot_graceful(tmp_path):
    write_snap(
        tmp_path / "snap",
        "2026-04-27",
        [make_row(ticker=f"T{i}", actionable_rank=i, eligible="1", tier_any="A") for i in range(1, 5)],
    )
    from tools.build_distribution_drift_report import main

    rc = main(
        [
            "--as-of-date",
            "2026-04-27",
            "--snapshots-dir",
            str(tmp_path / "snap"),
            "--quiet",
        ]
    )
    assert rc == 0
    payload = json.loads((tmp_path / "snap" / "2026-04-27" / "distribution_drift_report.json").read_text())
    assert payload["prior_date"] is None
    assert "turnover" not in payload
