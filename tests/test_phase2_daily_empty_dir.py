"""Tests for the empty-snapshot-dir deadlock fix in run_phase2_daily.py.

Confirmed root cause: the wrapper pre-created data/snapshots/<date>/ before
invoking run_screen.py, whose anti-clobber guard then refused to write because
the managed dir already existed -> empty snapshot dir (e.g. 2026-06-21).

These tests pin the fix: the wrapper no longer pre-creates the dir, and a
truly-empty leftover dir is cleaned (but a non-empty/real snapshot is never
touched). Wrapper/tooling only — no ranker/model/production behavior exercised.
"""

import sys
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_phase2_daily as rp  # noqa: E402

# ---------------------------------------------------------------------------
# _clear_empty_snapshot_dir
# ---------------------------------------------------------------------------


class TestClearEmptySnapshotDir:
    def test_empty_dir_is_removed(self, tmp_path):
        snap = tmp_path / "2026-07-08"
        snap.mkdir()
        assert rp._clear_empty_snapshot_dir(snap) is True
        assert not snap.exists()

    def test_dir_with_rankings_csv_is_left_untouched(self, tmp_path):
        snap = tmp_path / "2026-07-08"
        snap.mkdir()
        (snap / "rankings.csv").write_text("ticker\nTK000\n")
        assert rp._clear_empty_snapshot_dir(snap) is False
        assert snap.exists()
        assert (snap / "rankings.csv").exists()

    def test_dir_with_screen_output_is_left_untouched(self, tmp_path):
        snap = tmp_path / "2026-07-08"
        snap.mkdir()
        (snap / "screen_output.json").write_text("{}")
        assert rp._clear_empty_snapshot_dir(snap) is False
        assert snap.exists()
        assert (snap / "screen_output.json").exists()

    def test_nonexistent_dir_is_noop(self, tmp_path):
        snap = tmp_path / "does_not_exist"
        assert rp._clear_empty_snapshot_dir(snap) is False
        assert not snap.exists()

    def test_dir_with_subdir_only_is_left_untouched(self, tmp_path):
        # A leftover with only a subdirectory is still "non-empty" -> not removed.
        snap = tmp_path / "2026-07-08"
        (snap / "audit").mkdir(parents=True)
        assert rp._clear_empty_snapshot_dir(snap) is False
        assert snap.exists()


# ---------------------------------------------------------------------------
# build_command no longer pre-creates the snapshot dir
# ---------------------------------------------------------------------------


class TestBuildCommandNoPrecreate:
    def _args(self, snap_root: Path) -> Namespace:
        return Namespace(
            snapshot_dir=snap_root,
            as_of_date="2026-07-08",
            data_dir=snap_root.parent / "data",
            health_thresholds=None,
            dry_run=False,
        )

    def test_build_command_does_not_precreate_snapshot_dir(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        cmd = rp.build_command(self._args(snap_root), [])
        # The dated snapshot dir must NOT be created by command assembly —
        # run_screen.py creates it after its overwrite policy passes.
        assert not (snap_root / "2026-07-08").exists()

    def test_build_command_still_points_output_into_snapshot_dir(self, tmp_path):
        snap_root = tmp_path / "snapshots"
        cmd = rp.build_command(self._args(snap_root), [])
        assert "--output" in cmd
        out_idx = cmd.index("--output") + 1
        assert cmd[out_idx].endswith("2026-07-08/screen_output.json")
        assert "--strict" in cmd
        assert "phase2" in cmd
