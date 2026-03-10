"""Tests for post-promotion smoke gate in the promotion battery."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts.research.run_promotion_battery import (
    SMOKE_REQUIRED_FILES,
    build_packet,
    check_smoke_snapshot,
    run_post_promotion_smoke,
)

# ---------------------------------------------------------------------------
# check_smoke_snapshot unit tests
# ---------------------------------------------------------------------------


class TestCheckSmokeSnapshotPass:
    def test_all_files_present_and_provenance_ok(self, tmp_path):
        snap = tmp_path / "2026-03-10"
        snap.mkdir()
        (snap / "rankings.csv").write_text("ticker,rank\nACME,1\n")
        (snap / "run_manifest.json").write_text("{}")
        meta = {
            "ruleset_id": "7177a4ea",
            "engine_version": "v1.3.0",
            "git_sha": "abc123",
        }
        (snap / "metadata.json").write_text(json.dumps(meta))
        result = check_smoke_snapshot(snap, expected_ruleset_id="7177a4ea")
        assert result["status"] == "PASS"
        assert result["snapshot_ok"] is True
        assert result["provenance_ok"] is True


class TestCheckSmokeSnapshotMissingFiles:
    def test_no_rankings(self, tmp_path):
        snap = tmp_path / "2026-03-10"
        snap.mkdir()
        (snap / "run_manifest.json").write_text("{}")
        meta = {"ruleset_id": "x", "engine_version": "v1", "git_sha": "abc"}
        (snap / "metadata.json").write_text(json.dumps(meta))
        result = check_smoke_snapshot(snap)
        assert result["status"] == "FAIL"
        assert result["snapshot_ok"] is False
        assert "rankings.csv" in result["detail"]

    def test_no_metadata(self, tmp_path):
        snap = tmp_path / "2026-03-10"
        snap.mkdir()
        (snap / "rankings.csv").write_text("ticker,rank\n")
        (snap / "run_manifest.json").write_text("{}")
        result = check_smoke_snapshot(snap)
        assert result["status"] == "FAIL"
        assert result["snapshot_ok"] is False
        assert "metadata.json" in result["detail"]


class TestCheckSmokeSnapshotProvenanceMismatch:
    def test_wrong_ruleset_id(self, tmp_path):
        snap = tmp_path / "2026-03-10"
        snap.mkdir()
        for f in SMOKE_REQUIRED_FILES:
            if f == "metadata.json":
                meta = {
                    "ruleset_id": "deadbeef",
                    "engine_version": "v1.3.0",
                    "git_sha": "abc123",
                }
                (snap / f).write_text(json.dumps(meta))
            else:
                (snap / f).write_text("{}")
        result = check_smoke_snapshot(snap, expected_ruleset_id="7177a4ea")
        assert result["status"] == "FAIL"
        assert result["provenance_ok"] is False
        assert "mismatch" in result["detail"]

    def test_missing_provenance_key(self, tmp_path):
        snap = tmp_path / "2026-03-10"
        snap.mkdir()
        for f in SMOKE_REQUIRED_FILES:
            if f == "metadata.json":
                meta = {"ruleset_id": "7177a4ea"}  # missing engine_version, git_sha
                (snap / f).write_text(json.dumps(meta))
            else:
                (snap / f).write_text("{}")
        result = check_smoke_snapshot(snap, expected_ruleset_id="7177a4ea")
        assert result["status"] == "FAIL"
        assert result["provenance_ok"] is False
        assert "engine_version" in result["detail"]


# ---------------------------------------------------------------------------
# run_post_promotion_smoke tests (mocked subprocess)
# ---------------------------------------------------------------------------


def _make_smoke_snapshot(snap_dir: Path, as_of: str, ruleset_id: str = "7177a4ea"):
    """Create a minimal valid snapshot in snap_dir/as_of."""
    d = snap_dir / as_of
    d.mkdir(parents=True, exist_ok=True)
    (d / "rankings.csv").write_text("ticker,rank\nACME,1\n")
    (d / "run_manifest.json").write_text("{}")
    meta = {
        "ruleset_id": ruleset_id,
        "engine_version": "v1.3.0",
        "git_sha": "abc123def456",  # pragma: allowlist secret
    }
    (d / "metadata.json").write_text(json.dumps(meta))


class TestSmokePassPath:
    def test_exit_0_with_valid_snapshot(self, tmp_path):
        """Exit 0 + valid snapshot → PASS."""
        as_of = "2026-03-10"

        def fake_run(cmd, **kwargs):
            # Write snapshot files into the --snapshot-dir
            snap_dir_idx = cmd.index("--snapshot-dir") + 1
            snap_dir = Path(cmd[snap_dir_idx])
            _make_smoke_snapshot(snap_dir, as_of, "test_id")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK\n", stderr="")

        with patch("scripts.research.run_promotion_battery.subprocess.run", side_effect=fake_run):
            result = run_post_promotion_smoke(as_of, expected_ruleset_id="test_id")

        assert result["status"] == "PASS"
        assert result["exit_code"] == 0
        assert result["snapshot_ok"] is True
        assert result["provenance_ok"] is True


class TestSmokeWarnPath:
    def test_exit_2_with_valid_snapshot(self, tmp_path):
        """Exit 2 (WARN) + valid snapshot → WARN (not FAIL)."""
        as_of = "2026-03-10"

        def fake_run(cmd, **kwargs):
            snap_dir = Path(cmd[cmd.index("--snapshot-dir") + 1])
            _make_smoke_snapshot(snap_dir, as_of, "test_id")
            return subprocess.CompletedProcess(args=cmd, returncode=2, stdout="WARN\n", stderr="")

        with patch("scripts.research.run_promotion_battery.subprocess.run", side_effect=fake_run):
            result = run_post_promotion_smoke(as_of, expected_ruleset_id="test_id")

        assert result["status"] == "WARN"
        assert result["exit_code"] == 2
        assert result["snapshot_ok"] is True


class TestSmokeFailPath:
    def test_exit_1_is_fail(self):
        """Exit 1 → FAIL regardless of snapshot."""
        as_of = "2026-03-10"

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="FAIL gate\n", stderr="")

        with patch("scripts.research.run_promotion_battery.subprocess.run", side_effect=fake_run):
            result = run_post_promotion_smoke(as_of, expected_ruleset_id="test_id")

        assert result["status"] == "FAIL"
        assert result["exit_code"] == 1


class TestSmokeMissingOutputs:
    def test_exit_0_but_no_snapshot_files(self):
        """Exit 0 but no snapshot files → FAIL."""
        as_of = "2026-03-10"

        def fake_run(cmd, **kwargs):
            # Don't create any snapshot files
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK\n", stderr="")

        with patch("scripts.research.run_promotion_battery.subprocess.run", side_effect=fake_run):
            result = run_post_promotion_smoke(as_of, expected_ruleset_id="test_id")

        assert result["status"] == "FAIL"
        assert result["snapshot_ok"] is False


class TestSmokeProvenanceMismatch:
    def test_wrong_ruleset_id_in_metadata(self):
        """Snapshot exists but ruleset_id doesn't match → FAIL."""
        as_of = "2026-03-10"

        def fake_run(cmd, **kwargs):
            snap_dir = Path(cmd[cmd.index("--snapshot-dir") + 1])
            _make_smoke_snapshot(snap_dir, as_of, "wrong_id")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK\n", stderr="")

        with patch("scripts.research.run_promotion_battery.subprocess.run", side_effect=fake_run):
            result = run_post_promotion_smoke(as_of, expected_ruleset_id="expected_id")

        assert result["status"] == "FAIL"
        assert result["provenance_ok"] is False
        assert "mismatch" in result["detail"]


class TestNoProductionLeakage:
    def test_snapshot_dir_is_temp(self):
        """Verify smoke uses temp dir, not repo data/snapshots/."""
        as_of = "2026-03-10"
        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            snap_dir = Path(cmd[cmd.index("--snapshot-dir") + 1])
            _make_smoke_snapshot(snap_dir, as_of, "test_id")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("scripts.research.run_promotion_battery.subprocess.run", side_effect=fake_run):
            run_post_promotion_smoke(as_of, expected_ruleset_id="test_id")

        snap_dir_idx = captured_cmd.index("--snapshot-dir") + 1
        snap_dir = captured_cmd[snap_dir_idx]
        # Must NOT be under data/snapshots/
        assert "data/snapshots" not in snap_dir
        # Must be a temp directory
        assert "smoke_snap_" in snap_dir


# ---------------------------------------------------------------------------
# build_packet includes smoke result
# ---------------------------------------------------------------------------


class TestBuildPacketSmoke:
    def test_smoke_included_when_provided(self):
        smoke = {
            "status": "PASS",
            "exit_code": 0,
            "snapshot_ok": True,
            "provenance_ok": True,
            "detail": "OK",
        }
        packet = build_packet({}, {}, "PASS", smoke_result=smoke)
        assert "post_promotion_smoke" in packet
        assert packet["post_promotion_smoke"]["status"] == "PASS"
        assert packet["post_promotion_smoke"]["smoke_ok"] is True
        assert packet["post_promotion_smoke"]["snapshot_ok"] is True

    def test_smoke_ok_false_on_fail(self):
        smoke = {"status": "FAIL", "exit_code": 1, "snapshot_ok": False, "provenance_ok": False, "detail": "bad"}
        packet = build_packet({}, {}, "FAIL", smoke_result=smoke)
        assert packet["post_promotion_smoke"]["smoke_ok"] is False

    def test_smoke_ok_true_on_warn(self):
        smoke = {"status": "WARN", "exit_code": 2, "snapshot_ok": True, "provenance_ok": True, "detail": "ok"}
        packet = build_packet({}, {}, "PASS", smoke_result=smoke)
        assert packet["post_promotion_smoke"]["smoke_ok"] is True

    def test_smoke_omitted_when_none(self):
        packet = build_packet({}, {}, "PASS")
        assert "post_promotion_smoke" not in packet
