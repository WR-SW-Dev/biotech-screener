"""Snapshot manifest contract.

Documents and enforces which files a valid snapshot directory must contain.
Provides write_snapshot_manifest() to record what was actually produced, and
validate_snapshot() to check required files are present.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# ── Required files — snapshot is INVALID without these ──────────────────────
SNAPSHOT_REQUIRED_FILES: List[str] = [
    "rankings.csv",
    "metadata.json",
]

# ── Optional files — may or may not be present depending on config ──────────
SNAPSHOT_OPTIONAL_FILES: List[str] = [
    "rankings.csv.sha256",
    "screen_output.json",
    "decision_portfolio.csv",
    "decision_portfolio.json",
    "decision_ruleset.json",
    "catalyst_shadow_metrics.json",
    "catalyst_source_mix.json",
    "coverage_quality.json",
    "coverage_quality.md",
    "cache_health.json",
    "eligibility_debug.json",
    "eligibility_summary.json",
    "eligibility_summary.md",
    "event_premium_decomp.json",
    "health_exposure_metrics.json",
    "inputs_manifest.json",
    "institutional_summary.json",
    "institutional_summary_delta.json",
    "long_call_candidates.csv",
    "long_call_candidates.json",
    "long_call_candidates.md",
    "options_diagnostics.csv",
    "options_diagnostics_summary.json",
    "options_diagnostics_summary.md",
    "options_forward_log.json",
    "options_quality_manifest.json",
    "options_review_queue.csv",
    "options_review_queue.json",
    "options_review_queue.md",
    "phase2_health.json",
    "phase2_run_delta.csv",
    "phase2_run_delta_details.json",
    "phase2_run_delta_report.txt",
    "pnl_attribution.json",
    "pnl_attribution.md",
    "portfolio_positions.csv",
    "portfolio_positions.json",
    "ranker_shadow_comparison.json",
    "regulatory_coverage.json",
    "review_queue.csv",
    "review_queue.md",
    "ruleset_health.json",
    "run_manifest.json",
    "surface_delta.csv",
    "surface_delta.json",
    "surface_delta.md",
    "data_collection_health.json",
    "data_collection_health.md",
    "drift_report.json",
    "drift_report.md",
    "ACTION.json",
    "ACTION.md",
    "_step_progress.json",
    "snapshot_manifest.json",
]


def _sha256_file(path: Path) -> str:
    """Return hex SHA-256 digest for a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_snapshot_manifest(snap_dir: str | Path) -> Path:
    """Scan *snap_dir*, write ``snapshot_manifest.json`` with file inventory.

    Returns the path to the written manifest file.

    Manifest schema::

        {
            "snapshot_dir": "<absolute path>",
            "files": [
                {"name": "rankings.csv", "size_bytes": 12345, "sha256": "abc..."},
                ...
            ]
        }
    """
    snap_dir = Path(snap_dir)
    if not snap_dir.is_dir():
        raise FileNotFoundError(f"Snapshot directory does not exist: {snap_dir}")

    files_info: List[Dict[str, Any]] = []
    for child in sorted(snap_dir.iterdir()):
        if not child.is_file():
            continue
        # Skip the manifest itself to avoid self-referential hashing
        if child.name == "snapshot_manifest.json":
            continue
        files_info.append(
            {
                "name": child.name,
                "size_bytes": child.stat().st_size,
                "sha256": _sha256_file(child),
            }
        )

    manifest = {
        "snapshot_dir": str(snap_dir.resolve()),
        "files": files_info,
    }

    out_path = snap_dir / "snapshot_manifest.json"
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Wrote snapshot manifest (%d files) → %s", len(files_info), out_path)
    return out_path


def validate_snapshot(snap_dir: str | Path) -> Tuple[bool, List[str]]:
    """Check that all required files exist in *snap_dir*.

    Returns ``(passed, missing)`` where *missing* is the list of required
    file names that are absent.
    """
    snap_dir = Path(snap_dir)
    missing: List[str] = []
    for name in SNAPSHOT_REQUIRED_FILES:
        if not (snap_dir / name).exists():
            missing.append(name)
    passed = len(missing) == 0
    return passed, missing
