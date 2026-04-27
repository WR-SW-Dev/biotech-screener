"""Tests for the sentinel ticker report (read-only diagnostic)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_sentinel_ticker_report import (
    DEFAULT_SENTINELS,
    REPORTED_FIELDS,
    build_sentinel_report,
    extract_for_sentinel,
    get_cohort_membership,
    parse_sentinel_arg,
)


def make_row(**kw) -> dict[str, str]:
    base = {f: "" for f in REPORTED_FIELDS}
    base.update({k: ("" if v is None else str(v)) for k, v in kw.items()})
    return base


def write_snap(root: Path, date: str, rows: list[dict[str, str]]) -> Path:
    target = root / date
    target.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys())
    with open(target / "rankings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return target


# ---------------------------------------------------------------------------


def test_default_sentinel_list_includes_canonical_tickers():
    tickers = {t for t, _ in DEFAULT_SENTINELS}
    assert {"ERAS", "ARVN", "AXSM", "ARGX"}.issubset(tickers)


def test_get_cohort_membership_handles_present_absent_blank():
    assert get_cohort_membership({"ranker_v2_score": "0.6"}) == "in_cohort"
    assert get_cohort_membership({"ranker_v2_score": ""}) == "out_of_cohort"
    assert get_cohort_membership(None) == "absent"


def test_extract_missing_ticker_marks_status():
    rec = extract_for_sentinel("XXXX", "test", curr_row=None, prev_row=None)
    assert rec["status"] == "missing_from_universe"
    assert rec["cohort_membership"] == "absent"


def test_extract_eras_pattern_detects_cohort_re_entry():
    """ERAS dropped out 04-25, came back in 04-27 — verify transition is captured."""
    prev = make_row(
        ticker="ERAS",
        actionable_rank=63,
        ranker_v2_score="",  # out of cohort on prior day
        tier_any="A",
    )
    curr = make_row(
        ticker="ERAS",
        actionable_rank=18,
        ranker_v2_score="0.631",  # back in cohort today
        tier_any="A",
    )
    rec = extract_for_sentinel("ERAS", "boundary noise", curr, prev)
    assert rec["status"] == "present"
    assert rec["cohort_transition"] == "out_of_cohort→in_cohort"
    assert rec["rank_delta"] == -45  # 18 - 63
    assert rec["cohort_membership"] == "in_cohort"


def test_extract_dropout_pattern():
    """Reverse case: was in cohort, now out."""
    prev = make_row(ticker="X", actionable_rank=15, ranker_v2_score="0.6")
    curr = make_row(ticker="X", actionable_rank=63, ranker_v2_score="")
    rec = extract_for_sentinel("X", "test", curr, prev)
    assert rec["cohort_transition"] == "in_cohort→out_of_cohort"
    assert rec["rank_delta"] == 48


def test_extract_no_prior_yields_null_delta():
    curr = make_row(ticker="X", actionable_rank=10, ranker_v2_score="0.6")
    rec = extract_for_sentinel("X", "test", curr, None)
    assert rec["rank_delta"] is None
    assert rec["prev_actionable_rank"] is None


def test_extract_no_change_no_transition():
    prev = make_row(ticker="X", actionable_rank=10, ranker_v2_score="0.6")
    curr = make_row(ticker="X", actionable_rank=10, ranker_v2_score="0.6")
    rec = extract_for_sentinel("X", "test", curr, prev)
    assert rec["rank_delta"] == 0
    assert rec["cohort_transition"] is None


def test_build_report_summary_counts():
    curr = {"A": make_row(ticker="A", actionable_rank=1, ranker_v2_score="0.6")}
    prev: dict = {}  # no prior
    sentinels = [("A", "first"), ("MISSING", "absent")]
    report = build_sentinel_report(curr, prev, sentinels)
    assert report["n_sentinels"] == 2
    assert report["n_present"] == 1
    assert report["n_absent"] == 1


def test_parse_sentinel_arg_returns_uppercase_pairs():
    assert parse_sentinel_arg("eras,arvn") == [("ERAS", ""), ("ARVN", "")]
    assert parse_sentinel_arg("") is None
    assert parse_sentinel_arg(None) is None


def test_end_to_end_writes_artifacts(tmp_path):
    write_snap(
        tmp_path / "snap",
        "2026-04-25",
        [make_row(ticker="ERAS", actionable_rank=63, ranker_v2_score="", tier_any="A")],
    )
    write_snap(
        tmp_path / "snap",
        "2026-04-27",
        [make_row(ticker="ERAS", actionable_rank=18, ranker_v2_score="0.631", tier_any="A")],
    )
    from tools.build_sentinel_ticker_report import main

    rc = main(
        [
            "--as-of-date",
            "2026-04-27",
            "--snapshots-dir",
            str(tmp_path / "snap"),
            "--tickers",
            "ERAS",
            "--quiet",
        ]
    )
    assert rc == 0
    snap = tmp_path / "snap" / "2026-04-27"
    assert (snap / "sentinel_ticker_report.json").exists()
    assert (snap / "sentinel_ticker_report.md").exists()
    payload = json.loads((snap / "sentinel_ticker_report.json").read_text())
    eras = next(r for r in payload["records"] if r["ticker"] == "ERAS")
    assert eras["cohort_transition"] == "out_of_cohort→in_cohort"
    assert eras["rank_delta"] == -45


def test_no_prior_snapshot_graceful(tmp_path):
    write_snap(
        tmp_path / "snap",
        "2026-04-27",
        [make_row(ticker="ERAS", actionable_rank=18, ranker_v2_score="0.631", tier_any="A")],
    )
    from tools.build_sentinel_ticker_report import main

    rc = main(
        [
            "--as-of-date",
            "2026-04-27",
            "--snapshots-dir",
            str(tmp_path / "snap"),
            "--tickers",
            "ERAS",
            "--quiet",
        ]
    )
    assert rc == 0
    payload = json.loads((tmp_path / "snap" / "2026-04-27" / "sentinel_ticker_report.json").read_text())
    assert payload["prior_date"] is None
    eras = payload["records"][0]
    assert eras["status"] == "present"
    assert eras["rank_delta"] is None
