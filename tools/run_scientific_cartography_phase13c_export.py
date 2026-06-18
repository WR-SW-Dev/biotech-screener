#!/usr/bin/env python3
"""Phase 13C Disease Map Artifact Export.

Disabled-by-default hook for automated generation of per-disease artifacts
(JSON/CSV/MD) from Phase 7A diagnostic artifacts.

This phase requires Phase 7A (diagnostics wrapper) to have been run first,
as it consumes the Phase 7A JSONL outputs.

Usage:
    python3 tools/run_scientific_cartography_phase13c_export.py \
      --as-of-date 2026-06-18 \
      --snapshot-dir data/snapshots_pit/2026-06-18 \
      --ctgov-cache cache/ctgov \
      --output-dir artifacts/scientific_cartography/2026-06-18/diseases

Exit codes:
  0 — export succeeded
  1 — export failed (wrapper error)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
_logger = logging.getLogger(__name__)

# Repo root — all paths relative
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


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
        0 on success, 1 on failure
    """
    try:
        from scientific_cartography.export.disease_map_artifact_exporter import DiseaseMapArtifactExporter

        _logger.info(f"Phase 13C Export: Starting for {as_of_date}")
        _logger.info(f"  Snapshot: {snapshot_dir}")
        _logger.info(f"  CTGov cache: {ctgov_cache_dir}")
        _logger.info(f"  Output: {output_dir}")

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

        # Load program records
        programs = []
        with open(program_records_file) as f:
            for line in f:
                if line.strip():
                    programs.append(json.loads(line))
        _logger.info(f"  → {len(programs)} program records")

        # Load clusters
        clusters = []
        with open(clusters_file) as f:
            for line in f:
                if line.strip():
                    clusters.append(json.loads(line))
        _logger.info(f"  → {len(clusters)} cluster records")

        # Load features
        features = []
        with open(features_file) as f:
            for line in f:
                if line.strip():
                    features.append(json.loads(line))
        _logger.info(f"  → {len(features)} landscape feature records")

        # Load disease ontology (map index)
        map_index = json.load(open(map_index_file))
        disease_ontology = map_index.get("disease_index", {})
        _logger.info(f"  → {len(disease_ontology)} disease ontology records")

        # Export per-disease artifacts
        _logger.info("Exporting per-disease artifacts...")
        exporter = DiseaseMapArtifactExporter()

        # Reconstruct disease records from map_index for exporter
        disease_ontology_records = []
        for disease_key, disease_data in disease_ontology.items():
            disease_ontology_records.append(disease_data)

        exporter.export_all(
            asset_indication_map=programs,
            enhanced_clusters=clusters,
            landscape_features=features,
            disease_ontology=disease_ontology_records,
            output_dir=output_dir,
            as_of_date=as_of_date,
        )

        _logger.info("Phase 13C Export: SUCCESS")
        _logger.info(f"  Artifacts: {output_dir}")
        return 0

    except Exception as e:
        _logger.error("Phase 13C Export: FAILED")
        _logger.error(f"  Error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 13C Disease Map Artifact Export")
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
