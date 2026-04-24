"""Tests for tools/agent_heartbeat_checks.py.

Covers the production_qa heartbeat, which previously looked for the wrong
filename pattern and the wrong JSON fields — silently reporting STALE even
when production_qa_check wrote a healthy RED/YELLOW/GREEN report.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@pytest.fixture
def hb_mod(tmp_path, monkeypatch):
    import tools.agent_heartbeat_checks as mod

    mod = importlib.reload(mod)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SNAPSHOT_DIR", tmp_path / "data" / "snapshots")
    monkeypatch.setattr(mod, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path / "logs")
    (tmp_path / "data" / "snapshots").mkdir(parents=True)
    (tmp_path / "artifacts" / "production_qa").mkdir(parents=True)
    (tmp_path / "logs").mkdir()
    return mod


def _write_qa_report(tmp_path: Path, ds: str, verdict: str, fails: list[str]) -> None:
    """Write a report in the exact format production_qa_check.py emits."""
    report = {
        "schema": "production_qa.v1",
        "as_of_date": ds,
        "generated_at": "2026-04-15T00:00:00+00:00",
        "verdict": verdict,
        "n_checks": 9,
        "n_pass": 9 - len(fails),
        "n_fail": len(fails),
        "checks": [{"check": name, "status": "FAIL", "detail": ""} for name in fails]
        + [{"check": "other", "status": "PASS", "detail": ""}],
    }
    out = tmp_path / "artifacts" / "production_qa" / f"{ds}_report.json"
    out.write_text(json.dumps(report), encoding="utf-8")


def test_production_qa_finds_report_with_correct_filename(hb_mod, tmp_path):
    """Heartbeat must look for `{ds}_report.json` (the actual production_qa output)."""
    ds = "2026-04-15"
    _write_qa_report(tmp_path, ds, verdict="GREEN", fails=[])

    result = hb_mod.check_production_qa(date.fromisoformat(ds))
    assert result.status == "OK", f"Expected OK for GREEN verdict; got {result.status} ({result.detail})"


def test_production_qa_red_verdict_reports_fail(hb_mod, tmp_path):
    ds = "2026-04-15"
    _write_qa_report(tmp_path, ds, verdict="RED", fails=["sidecars", "schema", "tracebacks"])

    result = hb_mod.check_production_qa(date.fromisoformat(ds))
    assert result.status == "WARN"  # current code WARNs on any anomaly
    assert result.anomalies
    joined = " ".join(result.anomalies)
    assert "VERDICT_RED" in joined
    # Must name at least one failing check so ops knows what to look at
    assert "sidecars" in joined or "schema" in joined


def test_production_qa_yellow_verdict_reports_warn(hb_mod, tmp_path):
    ds = "2026-04-15"
    _write_qa_report(tmp_path, ds, verdict="YELLOW", fails=["tracebacks"])

    result = hb_mod.check_production_qa(date.fromisoformat(ds))
    assert result.status == "WARN"
    joined = " ".join(result.anomalies)
    assert "YELLOW" in joined


def test_production_qa_missing_report_is_stale(hb_mod):
    result = hb_mod.check_production_qa(date.fromisoformat("2026-04-15"))
    assert result.status == "STALE"


def test_production_qa_corrupt_report_is_flagged(hb_mod, tmp_path):
    ds = "2026-04-15"
    (tmp_path / "artifacts" / "production_qa" / f"{ds}_report.json").write_text("{ malformed", encoding="utf-8")
    result = hb_mod.check_production_qa(date.fromisoformat(ds))
    assert result.status == "WARN"
    joined = " ".join(result.anomalies)
    assert "CORRUPT" in joined


# ── Fleet receipt (Fix #3) ────────────────────────────────────


def _mk_result(hb_mod, agent, status, detail="", anomalies=None):
    return hb_mod.CheckResult(agent, status, detail, anomalies or [])


def test_derive_verdict_red_on_missing_snapshot(hb_mod):
    results = [_mk_result(hb_mod, "qa", "OK")]
    assert hb_mod._derive_verdict(results, {"missing_count": 0}, snapshot_ok=False) == "RED"


def test_derive_verdict_red_on_fail(hb_mod):
    results = [_mk_result(hb_mod, "qa", "FAIL", "pipeline crash")]
    assert hb_mod._derive_verdict(results, {"missing_count": 0}, snapshot_ok=True) == "RED"


def test_derive_verdict_red_on_coverage_gap(hb_mod):
    results = [_mk_result(hb_mod, "qa", "OK")]
    assert hb_mod._derive_verdict(results, {"missing_count": 3}, snapshot_ok=True) == "RED"


def test_derive_verdict_yellow_on_warn_or_stale(hb_mod):
    r = [_mk_result(hb_mod, "a", "WARN"), _mk_result(hb_mod, "b", "OK")]
    assert hb_mod._derive_verdict(r, {"missing_count": 0}, snapshot_ok=True) == "YELLOW"
    r = [_mk_result(hb_mod, "a", "STALE"), _mk_result(hb_mod, "b", "OK")]
    assert hb_mod._derive_verdict(r, {"missing_count": 0}, snapshot_ok=True) == "YELLOW"


def test_derive_verdict_green_when_all_ok(hb_mod):
    r = [_mk_result(hb_mod, "a", "OK"), _mk_result(hb_mod, "b", "SKIP")]
    assert hb_mod._derive_verdict(r, {"missing_count": 0}, snapshot_ok=True) == "GREEN"


def test_write_fleet_receipt_creates_file_with_core_sections(hb_mod, tmp_path):
    ds = "2026-04-24"
    (tmp_path / "data" / "snapshots" / ds).mkdir(parents=True)
    (tmp_path / "data" / "snapshots" / ds / "rankings.csv").write_text("x\n")

    results = [
        _mk_result(hb_mod, "qa", "OK", "snapshot valid"),
        _mk_result(hb_mod, "ic_health_monitor", "FAIL", "attention=HIGH", ["SIGNAL_ALERT: foo"]),
        _mk_result(hb_mod, "sentinel", "STALE", "10d > 2d"),
        _mk_result(hb_mod, "bioshort_watch", "SKIP", "unsupervised: cosmetic"),
    ]
    counts = {
        "active_count": 27,
        "monitored_count": 26,
        "stale_count": 1,
        "missing_count": 1,
        "deprecated_count": 2,
    }
    out_path = hb_mod.write_fleet_receipt(results, counts, date.fromisoformat(ds))

    assert out_path.exists()
    assert out_path.name == f"{ds}_receipt.md"
    text = out_path.read_text()
    assert "# Fleet Receipt" in text
    assert "Verdict: RED" in text
    assert "## Pipeline" in text
    assert "## Fleet (AGENT_REGISTRY.json)" in text
    assert "Active: 27" in text
    assert "Coverage gap" in text
    assert "## Agent Status" in text
    assert "### FAIL" in text
    assert "ic_health_monitor" in text
    assert "SIGNAL_ALERT: foo" in text
    assert "## Escalated to ops" in text


def test_write_fleet_receipt_green_verdict_minimal(hb_mod, tmp_path):
    ds = "2026-04-24"
    (tmp_path / "data" / "snapshots" / ds).mkdir(parents=True)
    (tmp_path / "data" / "snapshots" / ds / "rankings.csv").write_text("x\n")

    results = [_mk_result(hb_mod, "qa", "OK"), _mk_result(hb_mod, "ops", "OK")]
    counts = {
        "active_count": 2,
        "monitored_count": 2,
        "stale_count": 0,
        "missing_count": 0,
        "deprecated_count": 0,
    }
    out_path = hb_mod.write_fleet_receipt(results, counts, date.fromisoformat(ds))
    text = out_path.read_text()
    assert "Verdict: GREEN" in text
    assert "## Escalated to ops" not in text
