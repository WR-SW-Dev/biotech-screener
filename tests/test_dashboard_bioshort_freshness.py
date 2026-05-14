"""Spec 087 B2 — bioshort dashboard freshness envelope tests."""

import json
from datetime import date, timedelta
from unittest.mock import patch

import pytest

try:
    from dashboard.app import _FRESHNESS_ERROR_DAYS, _FRESHNESS_WARN_DAYS, _bioshort_freshness_meta

    HAS_DASHBOARD = True
except ImportError:
    HAS_DASHBOARD = False

pytestmark = pytest.mark.skipif(not HAS_DASHBOARD, reason="dashboard not installed")


def test_freshness_fresh(tmp_path):
    """Age <= WARN_DAYS (7) → FRESH."""
    verdict_dir = tmp_path / "output" / "hedge_report"
    verdict_dir.mkdir(parents=True)

    # 1 day old
    report_date = date.today() - timedelta(days=1)
    (verdict_dir / "BIOSHORT_VERDICT.json").write_text(json.dumps({"as_of_date": report_date.isoformat()}))

    with patch("dashboard.app.REPO_ROOT", tmp_path):
        meta = _bioshort_freshness_meta()

    assert meta["freshness_status"] == "FRESH"
    assert meta["report_age_days"] == 1


def test_freshness_stale_warning(tmp_path):
    """WARN_DAYS < age <= ERROR_DAYS (7-14) → STALE_WARNING."""
    verdict_dir = tmp_path / "output" / "hedge_report"
    verdict_dir.mkdir(parents=True)

    # 10 days old
    report_date = date.today() - timedelta(days=10)
    (verdict_dir / "BIOSHORT_VERDICT.json").write_text(json.dumps({"as_of_date": report_date.isoformat()}))

    with patch("dashboard.app.REPO_ROOT", tmp_path):
        meta = _bioshort_freshness_meta()

    assert meta["freshness_status"] == "STALE_WARNING"
    assert meta["report_age_days"] == 10


def test_freshness_stale_error(tmp_path):
    """Age > ERROR_DAYS (14) → STALE_ERROR."""
    verdict_dir = tmp_path / "output" / "hedge_report"
    verdict_dir.mkdir(parents=True)

    # 20 days old
    report_date = date.today() - timedelta(days=20)
    (verdict_dir / "BIOSHORT_VERDICT.json").write_text(json.dumps({"as_of_date": report_date.isoformat()}))

    with patch("dashboard.app.REPO_ROOT", tmp_path):
        meta = _bioshort_freshness_meta()

    assert meta["freshness_status"] == "STALE_ERROR"
    assert meta["report_age_days"] == 20


def test_freshness_missing_verdict_file(tmp_path):
    """Missing BIOSHORT_VERDICT.json → FRESHNESS_UNKNOWN."""
    verdict_dir = tmp_path / "output" / "hedge_report"
    verdict_dir.mkdir(parents=True)

    with patch("dashboard.app.REPO_ROOT", tmp_path):
        meta = _bioshort_freshness_meta()

    assert meta["freshness_status"] == "FRESHNESS_UNKNOWN"
    assert meta["report_as_of_date"] is None
    assert meta["report_age_days"] is None


def test_freshness_unparseable_date(tmp_path):
    """Unparseable date string → FRESHNESS_UNKNOWN."""
    verdict_dir = tmp_path / "output" / "hedge_report"
    verdict_dir.mkdir(parents=True)

    (verdict_dir / "BIOSHORT_VERDICT.json").write_text(json.dumps({"as_of_date": "not-a-date"}))

    with patch("dashboard.app.REPO_ROOT", tmp_path):
        meta = _bioshort_freshness_meta()

    assert meta["freshness_status"] == "FRESHNESS_UNKNOWN"
    assert meta["report_as_of_date"] == "not-a-date"
    assert meta["report_age_days"] is None


def test_freshness_thresholds_constants():
    """Verify freshness thresholds match spec (7/14 days)."""
    assert _FRESHNESS_WARN_DAYS == 7
    assert _FRESHNESS_ERROR_DAYS == 14
