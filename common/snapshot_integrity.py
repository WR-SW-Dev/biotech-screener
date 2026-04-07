"""
Snapshot integrity — SHA-256 sidecar files for immutable data artifacts.

Write a .sha256 sidecar alongside any snapshot file so downstream
consumers can verify the file hasn't been modified since creation.

Usage:
    from common.snapshot_integrity import write_checksum, verify_checksum

    # After writing a file:
    write_checksum(Path("data/snapshots/2026-04-07/rankings.csv"))

    # Before reading a file:
    ok = verify_checksum(Path("data/snapshots/2026-04-07/rankings.csv"))
    if not ok:
        raise IntegrityError("rankings.csv checksum mismatch")
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sidecar_path(filepath: Path) -> Path:
    """Return the .sha256 sidecar path for a given file."""
    return filepath.with_suffix(filepath.suffix + ".sha256")


def write_checksum(filepath: Path) -> Path:
    """Write a SHA-256 checksum sidecar file.

    Creates ``{filepath}.sha256`` containing the hex digest.

    Args:
        filepath: Path to the data file.

    Returns:
        Path to the sidecar file.
    """
    digest = _compute_sha256(filepath)
    sidecar = _sidecar_path(filepath)
    sidecar.write_text(f"{digest}  {filepath.name}\n", encoding="utf-8")
    logger.debug("Wrote checksum sidecar: %s", sidecar)
    return sidecar


def verify_checksum(filepath: Path) -> bool:
    """Verify a file against its SHA-256 sidecar.

    Returns True if the checksum matches, False if it doesn't.
    Returns True (vacuously) if no sidecar exists — callers that
    require verification should check for the sidecar first.

    Args:
        filepath: Path to the data file.

    Returns:
        True if verified or no sidecar present. False on mismatch.
    """
    sidecar = _sidecar_path(filepath)
    if not sidecar.exists():
        return True  # No sidecar → nothing to verify

    stored_line = sidecar.read_text(encoding="utf-8").strip()
    stored_digest = stored_line.split()[0] if stored_line else ""

    if not stored_digest:
        logger.warning("Empty checksum sidecar: %s", sidecar)
        return False

    computed = _compute_sha256(filepath)
    if computed != stored_digest:
        logger.error(
            "Checksum MISMATCH for %s: expected %s, got %s",
            filepath.name,
            stored_digest[:16],
            computed[:16],
        )
        return False

    logger.debug("Checksum verified: %s", filepath.name)
    return True


def require_checksum(filepath: Path) -> None:
    """Verify checksum and raise if mismatch or sidecar missing.

    Raises:
        FileNotFoundError: If the sidecar doesn't exist.
        ValueError: If the checksum doesn't match.
    """
    sidecar = _sidecar_path(filepath)
    if not sidecar.exists():
        raise FileNotFoundError(f"Checksum sidecar not found: {sidecar}")

    if not verify_checksum(filepath):
        raise ValueError(f"Integrity check failed for {filepath.name} — " f"file may have been modified after creation")
