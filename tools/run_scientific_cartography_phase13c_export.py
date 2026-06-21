#!/usr/bin/env python3
"""Phase 13C-lite Disease Map Artifact Export.

Disabled-by-default hook for repeatable generation of diagnostic artifacts
from Phase 7A diagnostic stack. Not production deployment—scheduled generation
with manifest, size guard, and safety checks.

Usage:
    python3 tools/run_scientific_cartography_phase13c_export.py \
      --as-of-date 2026-06-18 \
      --snapshot-dir data/snapshots_pit/2026-06-18 \
      --ctgov-cache cache/ctgov \
      --output-dir artifacts/scientific_cartography/2026-06-18

Exit codes:
  0 — export succeeded, manifest written
  1 — export failed (wrapper error)
  2 — safety check failed (forbidden fields, size guard, governance)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
_logger = logging.getLogger(__name__)

# Repo root — all paths relative
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scientific_cartography.io import deterministic_timestamp, write_json  # noqa: E402

# Safety thresholds
MAX_OUTPUT_SIZE_MB = 2048  # 2GB hard limit
FORBIDDEN_PATTERNS = [
    r"\bscore\b",  # numeric or comparative scores
    r"\brank(?:ing)?\b",  # ranking fields
    r"\bweight\b",  # portfolio weight
    r"\bfinal_score\b",  # final score
    r"(?:buy|sell|recommend)\s",  # action language (not in disclaimers)
]


def calculate_directory_size(directory: Path) -> float:
    """Calculate total size of directory in MB."""
    total_bytes = sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
    return total_bytes / (1024 * 1024)


def scan_for_forbidden_fields(directory: Path) -> Optional[list[str]]:
    """Scan all files for forbidden fields. Return list of violations or None."""
    violations = []

    for file_path in directory.rglob("*"):
        if not file_path.is_file():
            continue

        # Skip non-text files
        if file_path.suffix not in [".json", ".csv", ".md", ".jsonl"]:
            continue

        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Check for forbidden patterns
            for pattern in FORBIDDEN_PATTERNS:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    context = content[max(0, match.start() - 100) : match.end() + 100]
                    # Allow in governance/disclaimer context: "no/not scoring/ranking/weight"
                    if re.search(r"\b(no|not|governance|disclaimer|diagnostic|only)\b", context, re.IGNORECASE):
                        continue
                    # Allow "investment recommendation" in disclaimer
                    if "investment recommendation" in context:
                        continue
                    violations.append(f"{file_path.name}: {match.group()} at position {match.start()}")
        except (UnicodeDecodeError, IOError):
            # Skip binary files
            continue

    return violations if violations else None


def validate_governance_flags(directory: Path) -> bool:
    """Verify Phase 13C-generated JSON artifacts have read_only_diagnostic=true."""
    json_files = sorted(path for path in directory.rglob("*.json") if path.is_file())

    for file_path in json_files:
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            _logger.error("Failed to validate %s: %s", file_path.relative_to(directory), e)
            return False

        if not isinstance(data, dict):
            _logger.error("%s: JSON artifact is not an object", file_path.relative_to(directory))
            return False

        governance = data.get("governance")
        if not isinstance(governance, dict) or governance.get("read_only_diagnostic") is not True:
            _logger.error(
                "%s: governance.read_only_diagnostic not set",
                file_path.relative_to(directory),
            )
            return False

    return True


def generate_manifest(
    output_dir: Path,
    as_of_date: str,
    snapshot_dir: Path,
    runtime_seconds: float,
    created_at_utc: str = "",
) -> dict:
    """Generate manifest.json for Phase 13C-lite export."""
    size_mb = calculate_directory_size(output_dir)
    file_count = sum(1 for f in output_dir.rglob("*") if f.is_file())

    # Collect artifact details
    artifacts = {}
    for file_path in sorted(output_dir.glob("*.json*")):
        if file_path.name == "scientific_cartography_manifest.json":
            continue
        try:
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            if file_path.suffix == ".jsonl":
                # Count lines in JSONL
                with open(file_path, encoding="utf-8") as f:
                    record_count = sum(1 for line in f if line.strip())
            else:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
                record_count = len(data) if isinstance(data, (list, dict)) else "unknown"

            artifacts[file_path.stem] = {
                "size_mb": round(file_size_mb, 2),
                "records": record_count,
            }
        except (json.JSONDecodeError, IOError):
            pass

    manifest = {
        "artifact_type": "scientific_cartography_diagnostic",
        "as_of_date": as_of_date,
        "snapshot_dir": str(snapshot_dir),
        "generated_at": created_at_utc or deterministic_timestamp(as_of_date),
        "runtime_seconds": round(runtime_seconds, 1),
        "file_count": file_count,
        "total_size_mb": round(size_mb, 2),
        "governance": {
            "read_only_diagnostic": True,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "final_score_change": False,
        },
        "artifacts": artifacts,
        "safety_checks": {
            "size_guard_pass": size_mb <= MAX_OUTPUT_SIZE_MB,
            "forbidden_fields_scan": "PENDING",
            "governance_flags_valid": "PENDING",
        },
    }

    return manifest


def main(
    as_of_date: str,
    snapshot_dir: Path,
    ctgov_cache_dir: Path,
    output_dir: Path,
) -> int:
    """Export per-disease artifacts from Phase 7A diagnostic stack.

    Requires Phase 7A diagnostics to have been run, which generates:
    - program_records.jsonl
    - competitive_clusters.jsonl
    - landscape_features.jsonl
    - map_index.json (disease ontology)

    Args:
        as_of_date: snapshot date (YYYY-MM-DD)
        snapshot_dir: path to promoted snapshot directory
        ctgov_cache_dir: path to CTGov cache directory
        output_dir: path where disease artifacts will be written

    Returns:
        0 on success, 1 on failure, 2 on safety check failure
    """
    start_time = time.time()

    try:
        from scientific_cartography.build.asset_indication_map_builder import AssetIndicationMapBuilder
        from scientific_cartography.build.enhanced_cluster_builder import EnhancedCompetitiveClusterBuilder
        from scientific_cartography.build.landscape_context_builder import LandscapeContextFeatureBuilder
        from scientific_cartography.export.disease_map_artifact_exporter import DiseaseMapArtifactExporter
        from scientific_cartography.schemas.program_schema import ProgramRecord

        _logger.info("Phase 13C-lite Export: Starting for %s", as_of_date)
        _logger.info("  Snapshot: %s", snapshot_dir)
        _logger.info("  Output: %s", output_dir)

        # Phase 13C requires Phase 7A diagnostic artifacts to be present
        diagnostics_dir = REPO_ROOT / "artifacts" / "scientific_cartography" / as_of_date
        program_records_file = diagnostics_dir / "program_records.jsonl"
        clusters_file = diagnostics_dir / "competitive_clusters.jsonl"
        features_file = diagnostics_dir / "landscape_features.jsonl"
        map_index_file = diagnostics_dir / "map_index.json"

        # Check all required files exist
        missing_files = []
        if not program_records_file.exists():
            missing_files.append(str(program_records_file))
        if not clusters_file.exists():
            missing_files.append(str(clusters_file))
        if not features_file.exists():
            missing_files.append(str(features_file))
        if not map_index_file.exists():
            missing_files.append(str(map_index_file))

        if missing_files:
            msg = (
                "Phase 13C requires Phase 7A diagnostics to be run first.\n"
                "Missing files:\n" + "\n".join(f"  - {f}" for f in missing_files) + "\n\n"
                "To enable Phase 13C, run daily pipeline with:\n"
                "  --run-scientific-cartography --run-scientific-cartography-phase13c\n"
                "\n"
                "Or run Phase 7A first:\n"
                "  python3 tools/run_scientific_cartography_diagnostics.py \\\n"
                f"    --as-of-date {as_of_date} \\\n"
                f"    --snapshot-dir {snapshot_dir} \\\n"
                f"    --ctgov-cache {ctgov_cache_dir} \\\n"
                f"    --output-dir {diagnostics_dir}"
            )
            raise FileNotFoundError(msg)

        _logger.info("Loading Phase 7A diagnostic artifacts...")

        # Load Phase 7A program records and rebuild Phase 9-11 objects expected
        # by the per-disease artifact exporter.
        programs = []
        with open(program_records_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    programs.append(ProgramRecord.from_dict(json.loads(line)))
        _logger.info("  → %d program records", len(programs))

        # Validate upstream files are parseable even though Phase 13C rebuilds
        # later-stage schema objects from program records for type safety.
        upstream_clusters = []
        with open(clusters_file, encoding="utf-8") as f:
            upstream_clusters = [json.loads(line) for line in f if line.strip()]
        _logger.info("  → %d upstream cluster records", len(upstream_clusters))

        upstream_features = []
        with open(features_file, encoding="utf-8") as f:
            upstream_features = [json.loads(line) for line in f if line.strip()]
        _logger.info("  → %d upstream landscape feature records", len(upstream_features))

        with open(map_index_file, encoding="utf-8") as f:
            map_index = json.load(f)
        _logger.info("  → %d map-index disease entries", len(map_index.get("diseases", [])))

        asset_map_builder = AssetIndicationMapBuilder(as_of_date=as_of_date)
        asset_indication_records, asset_map_coverage = asset_map_builder.build_from_programs(programs)
        _logger.info("  → %d rebuilt asset-indication records", len(asset_indication_records))

        enhanced_cluster_builder = EnhancedCompetitiveClusterBuilder(as_of_date=as_of_date)
        enhanced_clusters, enhanced_cluster_coverage = enhanced_cluster_builder.build_from_asset_indication_records(
            asset_indication_records
        )
        _logger.info("  → %d rebuilt enhanced clusters", len(enhanced_clusters))

        context_builder = LandscapeContextFeatureBuilder(as_of_date=as_of_date)
        landscape_context_features, context_coverage = context_builder.build_from_records(
            asset_indication_records,
            enhanced_clusters,
        )
        _logger.info("  → %d rebuilt landscape context features", len(landscape_context_features))

        # Export per-disease artifacts
        _logger.info("Exporting per-disease artifacts...")
        exporter = DiseaseMapArtifactExporter(
            as_of_date=as_of_date,
            created_at_utc=deterministic_timestamp(as_of_date),
        )

        exporter.export_all(
            disease_ontology_records=[],
            asset_indication_records=asset_indication_records,
            enhanced_clusters=enhanced_clusters,
            landscape_context_features=landscape_context_features,
            output_dir=output_dir,
        )

        runtime = time.time() - start_time

        # === SAFETY CHECKS ===
        _logger.info("Running safety checks...")

        # 1. Size guard
        size_mb = calculate_directory_size(output_dir)
        if size_mb > MAX_OUTPUT_SIZE_MB:
            _logger.error(
                "SIZE_GUARD_FAIL: Output %d MB exceeds limit %d MB",
                size_mb,
                MAX_OUTPUT_SIZE_MB,
            )
            return 2

        _logger.info("  ✓ Size guard: %.1f MB (limit %.0f MB)", size_mb, MAX_OUTPUT_SIZE_MB)

        # 2. Governance flags
        if not validate_governance_flags(output_dir):
            _logger.error("GOVERNANCE_FAIL: Governance flags invalid")
            return 2

        _logger.info("  ✓ Governance flags: valid")

        # 3. Forbidden fields
        violations = scan_for_forbidden_fields(output_dir)
        if violations:
            _logger.error("FORBIDDEN_FIELDS_FAIL: Found %d violations", len(violations))
            for violation in violations[:5]:
                _logger.error("    %s", violation)
            if len(violations) > 5:
                _logger.error("    ... and %d more", len(violations) - 5)
            return 2

        _logger.info("  ✓ Forbidden field scan: PASS")

        # === MANIFEST GENERATION ===
        manifest = generate_manifest(
            output_dir,
            as_of_date,
            snapshot_dir,
            runtime,
            created_at_utc=deterministic_timestamp(as_of_date),
        )
        manifest["rebuilt_phase_9_11_counts"] = {
            "asset_indication_records": asset_map_coverage.total_records,
            "enhanced_clusters": enhanced_cluster_coverage.total_clusters,
            "landscape_context_features": context_coverage.total_features,
        }
        manifest["safety_checks"]["forbidden_fields_scan"] = "PASS"
        manifest["safety_checks"]["governance_flags_valid"] = True

        manifest_file = output_dir / "scientific_cartography_manifest.json"
        write_json(manifest_file, manifest)

        _logger.info("Phase 13C-lite Export: SUCCESS")
        _logger.info("  Runtime: %.1f seconds", runtime)
        _logger.info("  Size: %.1f MB (%d files)", size_mb, manifest["file_count"])
        _logger.info("  Manifest: %s", manifest_file.name)
        return 0

    except Exception as e:
        _logger.error("Phase 13C-lite Export: FAILED")
        _logger.error("  Error: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 13C-lite Disease Map Artifact Export")
    parser.add_argument(
        "--as-of-date",
        type=str,
        required=True,
        help="Snapshot date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        required=True,
        help="Path to promoted snapshot directory",
    )
    parser.add_argument(
        "--ctgov-cache",
        type=Path,
        required=True,
        help="Path to CTGov cache directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Path where disease artifacts will be written",
    )

    args = parser.parse_args()
    exit_code = main(
        as_of_date=args.as_of_date,
        snapshot_dir=args.snapshot_dir,
        ctgov_cache_dir=args.ctgov_cache,
        output_dir=args.output_dir,
    )
    sys.exit(exit_code)
