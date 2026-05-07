"""Spec 087 B0 — bioshort upstream freshness guard tests."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from common.bioshort_freshness import (
    STALE_THRESHOLD_DAYS,
    FreshnessResult,
    check_upstream_freshness,
    write_status_artifact,
)


def _write_fake_report(report_dir: Path, as_of_date: str) -> Path:
    p = report_dir / f"hedge_report_{as_of_date}.json"
    p.write_text(json.dumps({"as_of_date": as_of_date}), encoding="utf-8")
    return p


def test_orphaned_when_dir_missing(tmp_path: Path) -> None:
    result = check_upstream_freshness(tmp_path / "does_not_exist")
    assert result.status == "ORPHANED"
    assert result.latest_as_of_date is None
    assert result.age_days is None
    assert result.threshold_days == STALE_THRESHOLD_DAYS


def test_orphaned_when_dir_empty(tmp_path: Path) -> None:
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    result = check_upstream_freshness(rd)
    assert result.status == "ORPHANED"


def test_orphaned_ignores_unrelated_files_and_subdirs(tmp_path: Path) -> None:
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    (rd / "BIOSHORT_VERDICT.json").write_text("{}", encoding="utf-8")
    (rd / "BIOSHORT_VERDICT.md").write_text("#", encoding="utf-8")
    (rd / "archive").mkdir()
    (rd / "archive" / "hedge_report_2026-03-26.json").write_text("{}", encoding="utf-8")
    result = check_upstream_freshness(rd)
    assert result.status == "ORPHANED"
    assert result.latest_as_of_date is None


def test_fresh_when_today(tmp_path: Path) -> None:
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    today = date(2026, 5, 6)
    _write_fake_report(rd, today.isoformat())
    result = check_upstream_freshness(rd, today=today)
    assert result.status == "FRESH"
    assert result.age_days == 0
    assert result.latest_as_of_date == "2026-05-06"


def test_fresh_at_threshold_boundary_inclusive(tmp_path: Path) -> None:
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    today = date(2026, 5, 6)
    _write_fake_report(rd, (today - timedelta(days=STALE_THRESHOLD_DAYS)).isoformat())
    result = check_upstream_freshness(rd, today=today)
    assert result.status == "FRESH"
    assert result.age_days == STALE_THRESHOLD_DAYS


def test_stale_one_day_past_threshold(tmp_path: Path) -> None:
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    today = date(2026, 5, 6)
    _write_fake_report(rd, (today - timedelta(days=STALE_THRESHOLD_DAYS + 1)).isoformat())
    result = check_upstream_freshness(rd, today=today)
    assert result.status == "STALE"
    assert result.age_days == STALE_THRESHOLD_DAYS + 1


def test_stale_reproduces_2026_05_06_production_state(tmp_path: Path) -> None:
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    _write_fake_report(rd, "2026-03-26")
    result = check_upstream_freshness(rd, today=date(2026, 5, 6))
    assert result.status == "STALE"
    assert result.latest_as_of_date == "2026-03-26"
    assert result.age_days == 41


def test_picks_latest_when_multiple_reports(tmp_path: Path) -> None:
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    _write_fake_report(rd, "2026-03-17")
    _write_fake_report(rd, "2026-03-18")
    _write_fake_report(rd, "2026-03-26")
    result = check_upstream_freshness(rd, today=date(2026, 5, 6))
    assert result.latest_as_of_date == "2026-03-26"
    assert result.age_days == 41


def test_calendar_days_not_trading_days(tmp_path: Path) -> None:
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    _write_fake_report(rd, "2026-05-01")  # Friday
    assert check_upstream_freshness(rd, today=date(2026, 5, 10)).status == "FRESH"
    assert check_upstream_freshness(rd, today=date(2026, 5, 11)).status == "STALE"


def test_malformed_filename_ignored(tmp_path: Path) -> None:
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    (rd / "hedge_report_not-a-date.json").write_text("{}", encoding="utf-8")
    (rd / "hedge_report_2026-13-01.json").write_text("{}", encoding="utf-8")
    _write_fake_report(rd, "2026-05-01")
    result = check_upstream_freshness(rd, today=date(2026, 5, 6))
    assert result.latest_as_of_date == "2026-05-01"


def test_write_status_artifact_schema_and_atomic(tmp_path: Path) -> None:
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    _write_fake_report(rd, "2026-03-26")
    result = check_upstream_freshness(rd, today=date(2026, 5, 6))

    artifacts_dir = tmp_path / "artifacts" / "bioshort_watch"
    out = write_status_artifact(artifacts_dir, result)
    assert out == artifacts_dir / "latest_status.json"
    assert out.exists()

    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc == {
        "consumer_status": "suppressed",
        "status": "STALE",
        "threshold_days": STALE_THRESHOLD_DAYS,
        "upstream_age_days": 41,
        "upstream_as_of_date": "2026-03-26",
    }
    leftovers = [p.name for p in artifacts_dir.iterdir() if p.name != "latest_status.json"]
    assert leftovers == [], f"non-atomic write left tempfiles: {leftovers}"


def test_write_status_artifact_overwrites_on_state_change(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "bioshort_watch"
    rd = tmp_path / "hedge_report"
    rd.mkdir()
    today = date(2026, 5, 6)

    r1 = check_upstream_freshness(rd, today=today)
    write_status_artifact(artifacts_dir, r1)
    doc1 = json.loads((artifacts_dir / "latest_status.json").read_text(encoding="utf-8"))
    assert doc1["status"] == "ORPHANED"
    assert doc1["upstream_as_of_date"] is None

    _write_fake_report(rd, today.isoformat())
    r2 = check_upstream_freshness(rd, today=today)
    write_status_artifact(artifacts_dir, r2)
    doc2 = json.loads((artifacts_dir / "latest_status.json").read_text(encoding="utf-8"))
    assert doc2["status"] == "FRESH"
    assert doc2["upstream_as_of_date"] == "2026-05-06"


def test_freshness_result_to_status_doc_consumer_status_constant() -> None:
    r = FreshnessResult(status="FRESH", latest_as_of_date="2026-05-06", age_days=0, threshold_days=9)
    doc = r.to_status_doc()
    assert doc["consumer_status"] == "suppressed"
