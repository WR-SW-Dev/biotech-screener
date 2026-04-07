"""Tests for common.snapshot_integrity module."""

from __future__ import annotations

from pathlib import Path

import pytest

from common.snapshot_integrity import require_checksum, verify_checksum, write_checksum


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    f = tmp_path / "rankings.csv"
    f.write_text("ticker,score\nACME,100\n")
    return f


class TestWriteChecksum:
    def test_creates_sidecar(self, sample_file: Path):
        sidecar = write_checksum(sample_file)
        assert sidecar.exists()
        assert sidecar.name == "rankings.csv.sha256"

    def test_sidecar_contains_digest(self, sample_file: Path):
        write_checksum(sample_file)
        sidecar = sample_file.with_suffix(".csv.sha256")
        content = sidecar.read_text()
        assert len(content.split()[0]) == 64  # SHA-256 hex = 64 chars
        assert "rankings.csv" in content


class TestVerifyChecksum:
    def test_passes_when_matching(self, sample_file: Path):
        write_checksum(sample_file)
        assert verify_checksum(sample_file) is True

    def test_fails_when_modified(self, sample_file: Path):
        write_checksum(sample_file)
        sample_file.write_text("ticker,score\nACME,999\n")  # modify
        assert verify_checksum(sample_file) is False

    def test_passes_when_no_sidecar(self, sample_file: Path):
        assert verify_checksum(sample_file) is True

    def test_fails_on_empty_sidecar(self, sample_file: Path):
        sidecar = sample_file.with_suffix(".csv.sha256")
        sidecar.write_text("")
        assert verify_checksum(sample_file) is False


class TestRequireChecksum:
    def test_raises_when_no_sidecar(self, sample_file: Path):
        with pytest.raises(FileNotFoundError):
            require_checksum(sample_file)

    def test_raises_on_mismatch(self, sample_file: Path):
        write_checksum(sample_file)
        sample_file.write_text("TAMPERED")
        with pytest.raises(ValueError, match="Integrity check failed"):
            require_checksum(sample_file)

    def test_passes_when_valid(self, sample_file: Path):
        write_checksum(sample_file)
        require_checksum(sample_file)  # should not raise
