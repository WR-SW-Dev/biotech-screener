"""Tests for common.snapshot_manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.snapshot_manifest import SNAPSHOT_REQUIRED_FILES, validate_snapshot, write_snapshot_manifest


@pytest.fixture
def full_snapshot(tmp_path: Path) -> Path:
    """Create a minimal valid snapshot directory with all required files."""
    (tmp_path / "rankings.csv").write_text("ticker,score\nACME,1.0\n")
    (tmp_path / "metadata.json").write_text('{"version": "1.0"}')
    return tmp_path


def test_write_creates_valid_json(full_snapshot: Path):
    manifest_path = write_snapshot_manifest(full_snapshot)
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())
    assert "files" in data
    assert "snapshot_dir" in data
    names = [f["name"] for f in data["files"]]
    assert "rankings.csv" in names
    assert "metadata.json" in names
    # Every entry must have size_bytes and sha256
    for entry in data["files"]:
        assert isinstance(entry["size_bytes"], int)
        assert len(entry["sha256"]) == 64  # hex sha256


def test_write_excludes_self(full_snapshot: Path):
    """Manifest should not list itself to avoid self-referential hashing."""
    write_snapshot_manifest(full_snapshot)
    data = json.loads((full_snapshot / "snapshot_manifest.json").read_text())
    names = [f["name"] for f in data["files"]]
    assert "snapshot_manifest.json" not in names


def test_validate_passes_with_required_files(full_snapshot: Path):
    passed, missing = validate_snapshot(full_snapshot)
    assert passed is True
    assert missing == []


def test_validate_fails_when_rankings_missing(tmp_path: Path):
    """Missing rankings.csv should cause validation failure."""
    (tmp_path / "metadata.json").write_text('{"version": "1.0"}')
    passed, missing = validate_snapshot(tmp_path)
    assert passed is False
    assert "rankings.csv" in missing


def test_validate_fails_when_metadata_missing(tmp_path: Path):
    """Missing metadata.json should cause validation failure."""
    (tmp_path / "rankings.csv").write_text("ticker,score\n")
    passed, missing = validate_snapshot(tmp_path)
    assert passed is False
    assert "metadata.json" in missing


def test_validate_fails_empty_dir(tmp_path: Path):
    passed, missing = validate_snapshot(tmp_path)
    assert passed is False
    assert set(missing) == set(SNAPSHOT_REQUIRED_FILES)


def test_write_raises_on_missing_dir(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        write_snapshot_manifest(tmp_path / "nonexistent")
