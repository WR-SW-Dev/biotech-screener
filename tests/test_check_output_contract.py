"""Tests for the snapshot output-contract checker (read-only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.check_output_contract import (  # noqa: E402
    OPTIONAL_ARTIFACTS,
    REQUIRED_ARTIFACTS,
    check_contract,
    main,
)


def _make_snapshot(root: Path, as_of: str, *, include: tuple[str, ...]) -> Path:
    snap = root / as_of
    snap.mkdir(parents=True)
    for name in include:
        path = snap / name
        # Give every artifact some non-zero content so the EMPTY branch isn't
        # accidentally hit by the happy-path test.
        if name.endswith(".csv"):
            path.write_text("col1,col2\nv1,v2\n", encoding="utf-8")
        elif name.endswith(".sha256"):
            path.write_text("0" * 64 + "  rankings.csv\n", encoding="utf-8")
        else:
            path.write_text(json.dumps({"as_of_date": as_of, "ok": True}), encoding="utf-8")
    return snap


def test_pass_when_all_required_and_optional_present(tmp_path):
    _make_snapshot(tmp_path, "2026-05-01", include=REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS)
    report = check_contract("2026-05-01", snapshot_root=tmp_path)
    assert report.snapshot_exists is True
    assert report.overall == "PASS"
    assert report.missing_required == []
    assert report.missing_optional == []


def test_warn_when_required_present_optional_missing(tmp_path):
    _make_snapshot(tmp_path, "2026-05-01", include=REQUIRED_ARTIFACTS)
    report = check_contract("2026-05-01", snapshot_root=tmp_path)
    assert report.overall == "WARN"
    assert report.missing_required == []
    assert set(report.missing_optional) == set(OPTIONAL_ARTIFACTS)


def test_fail_when_required_missing(tmp_path):
    partial = tuple(a for a in REQUIRED_ARTIFACTS if a != "rank_change_alerts.json")
    _make_snapshot(tmp_path, "2026-05-01", include=partial)
    report = check_contract("2026-05-01", snapshot_root=tmp_path)
    assert report.overall == "FAIL"
    assert "rank_change_alerts.json" in report.missing_required


def test_fail_when_snapshot_dir_missing(tmp_path):
    report = check_contract("2026-05-01", snapshot_root=tmp_path)
    assert report.snapshot_exists is False
    assert report.overall == "FAIL"
    # Every required artifact reported as missing when the dir doesn't exist.
    assert set(report.missing_required) == set(REQUIRED_ARTIFACTS)


def test_empty_required_artifact_treated_as_missing(tmp_path):
    snap = _make_snapshot(tmp_path, "2026-05-01", include=REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS)
    # Wipe one required file to size 0
    (snap / "feature_coverage_report.json").write_text("", encoding="utf-8")
    report = check_contract("2026-05-01", snapshot_root=tmp_path)
    assert report.overall == "FAIL"
    assert "feature_coverage_report.json" in report.missing_required


@pytest.mark.parametrize(
    "overall,strict,expected",
    [
        ("PASS", False, 0),
        ("PASS", True, 0),
        ("WARN", False, 2),
        ("WARN", True, 1),
        ("FAIL", False, 1),
        ("FAIL", True, 1),
    ],
)
def test_main_exit_codes(tmp_path, capsys, overall, strict, expected):
    if overall == "PASS":
        _make_snapshot(tmp_path, "2026-05-01", include=REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS)
    elif overall == "WARN":
        _make_snapshot(tmp_path, "2026-05-01", include=REQUIRED_ARTIFACTS)
    else:
        # FAIL — directory missing entirely
        pass

    argv = ["--as-of", "2026-05-01", "--snapshot-root", str(tmp_path)]
    if strict:
        argv.append("--strict")
    rc = main(argv)
    assert rc == expected
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["overall"] == overall


def test_main_prints_valid_json(tmp_path, capsys):
    _make_snapshot(tmp_path, "2026-05-01", include=REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS)
    main(["--as-of", "2026-05-01", "--snapshot-root", str(tmp_path)])
    parsed = json.loads(capsys.readouterr().out)
    # Sanity: contract report fields the backstop cron will rely on.
    assert parsed["as_of_date"] == "2026-05-01"
    assert parsed["snapshot_exists"] is True
    assert parsed["overall"] in {"PASS", "WARN", "FAIL"}
    assert isinstance(parsed["required"], list)
    assert isinstance(parsed["missing_required"], list)
