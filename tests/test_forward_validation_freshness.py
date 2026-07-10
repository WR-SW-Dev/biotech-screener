"""Tests for the forward-validation freshness/provenance gate.

Guards against a stale-output false positive: a capture that looks live but was
built from an earlier run's artifacts, a hard-failed run, or a different
invocation. See docs/governance/2026-07-10-dem-candidate-hash-equivalence.md
and the SM-20260629-001 hardening (IC re-review ICD-20260710-001).
"""

from __future__ import annotations

import json

from tools.run_forward_validation import validate_run_freshness

DATE = "2026-07-10"
COMMIT = "97e76149dce0dfaf9fa4ed4110f0c1c7eceabce8"  # pragma: allowlist secret  (git sha, not a credential)


def _write_manifest(snap_dir, **overrides):
    snap_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "as_of_date": DATE,
        "requested_as_of_date": DATE,
        "overall_status": "WARN",
        "git": {"commit_sha": COMMIT},
    }
    manifest.update(overrides)
    (snap_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return snap_dir


def test_fresh_run_passes(tmp_path):
    snap = _write_manifest(tmp_path / DATE)
    assert validate_run_freshness(DATE, snap) == []


def test_warn_status_still_passes(tmp_path):
    # exit-2 / WARN runs are legitimate captures; only FAIL is blocked.
    snap = _write_manifest(tmp_path / DATE, overall_status="WARN")
    assert validate_run_freshness(DATE, snap) == []


def test_missing_manifest_blocks(tmp_path):
    snap = tmp_path / DATE
    snap.mkdir()
    reasons = validate_run_freshness(DATE, snap)
    assert any("missing" in r for r in reasons)


def test_stale_leftover_date_blocks(tmp_path):
    # A directory for DATE whose manifest actually describes a different date.
    snap = _write_manifest(tmp_path / DATE, as_of_date="2026-07-03", requested_as_of_date="2026-07-03")
    reasons = validate_run_freshness(DATE, snap)
    assert any("stale/leftover" in r for r in reasons)


def test_hard_failed_run_blocks(tmp_path):
    snap = _write_manifest(tmp_path / DATE, overall_status="FAIL")
    reasons = validate_run_freshness(DATE, snap)
    assert any("hard-failed" in r for r in reasons)


def test_commit_mismatch_blocks(tmp_path):
    snap = _write_manifest(tmp_path / DATE)
    reasons = validate_run_freshness(DATE, snap, expect_commit="deadbeefdeadbeef")
    assert any("invocation commit" in r for r in reasons)


def test_commit_prefix_match_passes(tmp_path):
    # The wrapper may pass a short or full sha; prefix match in either direction is OK.
    snap = _write_manifest(tmp_path / DATE)
    assert validate_run_freshness(DATE, snap, expect_commit=COMMIT[:12]) == []


def test_no_expect_commit_skips_commit_check(tmp_path):
    # Manual backfills don't pass a commit; the check is simply skipped.
    snap = _write_manifest(tmp_path / DATE)
    assert validate_run_freshness(DATE, snap, expect_commit=None) == []
