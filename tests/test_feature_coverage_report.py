"""Tests for the feature coverage report (read-only diagnostic)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_feature_coverage_report import (
    FAIL_BELOW_PCT,
    TRACKED_FEATURES,
    UNIVERSE_WIDE_FEATURES,
    WARN_BELOW_PCT,
    build_coverage_report,
    coverage_for_feature,
    segment_by,
)


def write_snapshot(snap_root: Path, date: str, rows: list[dict[str, str]]) -> Path:
    target = snap_root / date
    target.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys()) if rows else ["ticker"]
    with open(target / "rankings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return target


def make_row(**kw) -> dict[str, str]:
    base = {f: "" for f in TRACKED_FEATURES}
    base["ticker"] = ""
    base["company_name"] = ""
    base.update({k: ("" if v is None else str(v)) for k, v in kw.items()})
    return base


# ---------------------------------------------------------------------------


def test_coverage_for_feature_full_passes_for_universe_wide():
    rows = [make_row(ticker=f"T{i}", tier_any="A") for i in range(10)]
    rec = coverage_for_feature("tier_any", rows, cols_present=True)
    assert rec["pct_present"] == 100.0
    assert rec["severity"] == "PASS"


def test_coverage_warns_when_universe_field_below_threshold():
    n = 100
    rows = [make_row(ticker=f"T{i}", market_cap_mm=str(i + 1)) for i in range(70)]
    rows += [make_row(ticker=f"X{i}") for i in range(n - 70)]
    rec = coverage_for_feature("market_cap_mm", rows, cols_present=True)
    assert rec["pct_present"] == 70.0
    assert rec["severity"] == "WARN"
    assert WARN_BELOW_PCT > rec["pct_present"] >= FAIL_BELOW_PCT


def test_coverage_fails_when_universe_field_far_below():
    n = 100
    rows = [make_row(ticker=f"T{i}", market_cap_mm=str(i + 1)) for i in range(40)]
    rows += [make_row(ticker=f"X{i}") for i in range(n - 40)]
    rec = coverage_for_feature("market_cap_mm", rows, cols_present=True)
    assert rec["pct_present"] == 40.0
    assert rec["severity"] == "FAIL"


def test_optional_cohort_field_stays_info_at_low_coverage():
    rows = [make_row(ticker=f"T{i}", ranker_v2_score=0.6 if i < 60 else "") for i in range(297)]
    rec = coverage_for_feature("ranker_v2_score", rows, cols_present=True)
    assert rec["severity"] == "INFO"
    assert 19.0 < rec["pct_present"] < 21.0


def test_missing_column_is_fail():
    rows = [make_row(ticker="T1")]
    rec = coverage_for_feature("nonexistent_col", rows, cols_present=False)
    assert rec["severity"] == "FAIL"
    assert rec["column_present"] is False


def test_universe_wide_features_set_is_subset_of_tracked():
    assert UNIVERSE_WIDE_FEATURES.issubset(set(TRACKED_FEATURES))


def test_segment_by_buckets_correctly():
    rows = [
        make_row(ticker="A", tier_any="A", market_cap_mm="100"),
        make_row(ticker="B", tier_any="A", market_cap_mm=""),
        make_row(ticker="C", tier_any="B", market_cap_mm="200"),
    ]
    seg = segment_by(rows, "market_cap_mm", "tier_any")
    assert seg["A"]["n_total"] == 2
    assert seg["A"]["n_present"] == 1
    assert seg["A"]["pct_present"] == 50.0
    assert seg["B"]["n_present"] == 1


def test_blank_segment_value_grouped_as_blank():
    rows = [
        make_row(ticker="A", tier_any="", market_cap_mm="1"),
        make_row(ticker="B", tier_any="", market_cap_mm=""),
    ]
    seg = segment_by(rows, "market_cap_mm", "tier_any")
    assert "(blank)" in seg
    assert seg["(blank)"]["n_total"] == 2


def test_end_to_end_writes_artifacts(tmp_path):
    snap = write_snapshot(
        tmp_path / "snap",
        "2026-04-27",
        [make_row(ticker=f"T{i}", tier_any="A", market_cap_mm=str(i + 1)) for i in range(10)],
    )
    from tools.build_feature_coverage_report import main

    rc = main(["--as-of-date", "2026-04-27", "--snapshots-dir", str(tmp_path / "snap"), "--quiet"])
    assert rc == 0
    j = json.loads((snap / "feature_coverage_report.json").read_text())
    assert j["schema_version"].startswith("feature_coverage_report")
    assert (snap / "feature_coverage_report.md").exists()


def test_overall_severity_picks_worst(tmp_path):
    # market_cap_mm at 30% (< FAIL_BELOW_PCT) should drive overall to FAIL
    rows = [make_row(ticker=f"T{i}", tier_any="A", market_cap_mm="100") for i in range(3)]
    rows += [make_row(ticker=f"X{i}", tier_any="A") for i in range(7)]
    snap_dir = write_snapshot(tmp_path / "snap", "2026-04-27", rows)
    report = build_coverage_report(snap_dir)
    assert report["overall_severity"] == "FAIL"
    by_feat = {f["feature"]: f for f in report["features"]}
    assert by_feat["market_cap_mm"]["severity"] == "FAIL"


def test_zero_coverage_field_is_info_for_optional(tmp_path):
    """The PCR=0% case (today's reality before backfill is consumed)."""
    rows = [make_row(ticker=f"T{i}", tier_any="A", market_cap_mm="100") for i in range(50)]
    snap_dir = write_snapshot(tmp_path / "snap", "2026-04-27", rows)
    report = build_coverage_report(snap_dir)
    by_feat = {f["feature"]: f for f in report["features"]}
    pcr = by_feat["pre_event_put_call_ratio"]
    assert pcr["pct_present"] == 0.0
    assert pcr["severity"] == "INFO"  # optional field — not a hard fail
