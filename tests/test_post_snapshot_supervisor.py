"""Tests for tools/run_post_snapshot_supervisor.py."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@pytest.fixture
def supervisor_mod(tmp_path, monkeypatch):
    import tools.run_post_snapshot_supervisor as mod

    mod = importlib.reload(mod)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "LEDGER_DIR", tmp_path / "artifacts" / "post_snapshot_done")
    (tmp_path / "data" / "snapshots" / "2026-05-08").mkdir(parents=True)
    (tmp_path / "data" / "snapshots" / "2026-05-08" / "rankings.csv").write_text("ticker\n")
    return mod


def test_herald_done_requires_classified_artifact(supervisor_mod, tmp_path):
    """A deduped file alone should not make Herald done; classify must retry."""
    as_of = "2026-05-08"
    deduped = tmp_path / "data" / "press_releases" / "deduped"
    deduped.mkdir(parents=True)
    (deduped / f"deduped_{as_of}.jsonl").write_text("{}\n")

    assert supervisor_mod._herald_done(as_of) is False

    classified = tmp_path / "data" / "press_releases" / "classified"
    classified.mkdir(parents=True)
    (classified / f"classified_{as_of}.jsonl").write_text("{}\n")

    assert supervisor_mod._herald_done(as_of) is True
