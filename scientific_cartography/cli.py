"""CLI for scientific cartography module."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from scientific_cartography.build.competitive_cluster_builder import CompetitiveClusterBuilder
from scientific_cartography.export import ArtifactManifestExporter, DiseaseMapExporter, MapIndexExporter
from scientific_cartography.normalize.disease_normalizer import DiseaseNormalizer
from scientific_cartography.normalize.stage_normalizer import StageNormalizer
from scientific_cartography.schemas.cluster_schema import CompetitiveClusterRecord
from scientific_cartography.schemas.landscape_feature_schema import LandscapeFeatureRecord
from scientific_cartography.schemas.program_schema import ProgramRecord


def build_command(args: argparse.Namespace) -> int:
    """Build scientific cartography artifacts from cache.

    Arguments:
        args.as_of_date: Date for artifacts (YYYY-MM-DD).
        args.snapshot_dir: Path to snapshot directory.
        args.output_dir: Output directory for artifacts.
        args.cache_only: Must be True for this version.
        args.build_clusters: If True, build competitive clusters (Phase 4).
    """
    if not args.cache_only:
        print("ERROR: Phase 0/1 implementation requires --cache-only mode", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize normalizers
    _disease_normalizer = DiseaseNormalizer(as_of_date=args.as_of_date)
    _stage_normalizer = StageNormalizer()

    # Write a basic coverage report (Phase 1)
    report = {
        "as_of_date": args.as_of_date,
        "as_of_timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "Phase 0/1: Skeleton and normalizers initialized",
        "modules": {
            "disease_normalizer": {"status": "ready", "cached_records": 0},
            "stage_normalizer": {"status": "ready", "stages_normalized": 0},
        },
        "governance": {
            "classification": "SCIENTIFIC_CARTOGRAPHY_CONTEXT_LAYER",
            "read_only": True,
            "no_ranker_change": True,
            "no_selector_change": True,
            "no_sizing_change": True,
            "cache_only": True,
            "alpha_promotion": False,
            "point_in_time_safe": True,
        },
    }

    report_path = output_dir / "build_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"✓ Build report written to {report_path}")
    print(f"✓ Phase 0/1 skeleton initialized for {args.as_of_date}")

    # Phase 4: Build clusters if requested and programs exist
    if args.build_clusters:
        cluster_builder = CompetitiveClusterBuilder(as_of_date=args.as_of_date)
        # Empty program list for now (would be populated from Phase 2/3 data in production)
        clusters, coverage_report = cluster_builder.build_from_programs([])

        # Write clusters JSONL
        clusters_path = output_dir / "competitive_clusters.jsonl"
        cluster_builder.write_clusters_jsonl(clusters, clusters_path)
        print(f"✓ Competitive clusters written to {clusters_path}")

        # Write cluster coverage report
        cluster_coverage_path = output_dir / "cluster_coverage_report.json"
        cluster_builder.write_coverage_report(coverage_report, cluster_coverage_path)
        print(f"✓ Cluster coverage report written to {cluster_coverage_path}")

    return 0


def export_artifacts_command(args: argparse.Namespace) -> int:
    """Export Phase 6 diagnostic artifacts from existing records.

    Arguments:
        args.as_of_date: Date for artifacts (YYYY-MM-DD).
        args.artifact_dir: Directory containing program_records.jsonl, etc.
        args.output_dir: Output directory for exported artifacts.
        args.created_at_utc: Optional deterministic timestamp for manifest.
    """
    artifact_dir = Path(args.artifact_dir)
    output_dir = Path(args.output_dir)

    # Validate artifact directory exists
    if not artifact_dir.exists():
        print(f"ERROR: Artifact directory not found: {artifact_dir}", file=sys.stderr)
        return 1

    # Load program records (required)
    programs_path = artifact_dir / "program_records.jsonl"
    if not programs_path.exists():
        print(f"ERROR: program_records.jsonl not found in {artifact_dir}", file=sys.stderr)
        return 1

    try:
        programs = []
        with open(programs_path) as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    programs.append(ProgramRecord(**data))
        print(f"✓ Loaded {len(programs)} program records", file=sys.stderr)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"ERROR: Failed to parse program_records.jsonl: {e}", file=sys.stderr)
        return 1

    # Load competitive clusters (optional)
    clusters = []
    clusters_path = artifact_dir / "competitive_clusters.jsonl"
    if clusters_path.exists():
        try:
            with open(clusters_path) as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        clusters.append(CompetitiveClusterRecord(**data))
            print(f"✓ Loaded {len(clusters)} competitive cluster records", file=sys.stderr)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"⚠ Warning: Failed to parse competitive_clusters.jsonl: {e}", file=sys.stderr)
    else:
        print("⚠ Warning: competitive_clusters.jsonl not found; continuing with empty clusters", file=sys.stderr)

    # Load landscape features (optional)
    features = []
    features_path = artifact_dir / "landscape_features.jsonl"
    if features_path.exists():
        try:
            with open(features_path) as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        features.append(LandscapeFeatureRecord(**data))
            print(f"✓ Loaded {len(features)} landscape feature records", file=sys.stderr)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"⚠ Warning: Failed to parse landscape_features.jsonl: {e}", file=sys.stderr)
    else:
        print("⚠ Warning: landscape_features.jsonl not found; continuing with empty features", file=sys.stderr)

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build and write map index
    map_exporter = MapIndexExporter(as_of_date=args.as_of_date)
    map_index = map_exporter.build_index(programs, clusters, features)
    map_index_path = output_dir / "map_index.json"
    map_exporter.write_index(map_index, map_index_path)
    print(f"✓ Wrote map_index.json ({map_index_path.stat().st_size} bytes)", file=sys.stderr)

    # Build and write disease summary (JSON)
    disease_exporter = DiseaseMapExporter(as_of_date=args.as_of_date)
    disease_summary = disease_exporter.build_disease_summary(programs, clusters, features)
    disease_summary_json_path = output_dir / "disease_map_summary.json"
    disease_exporter.write_disease_summary(disease_summary, disease_summary_json_path)
    print(
        f"✓ Wrote disease_map_summary.json ({disease_summary_json_path.stat().st_size} bytes)",
        file=sys.stderr,
    )

    # Build and write disease summary (Markdown)
    disease_summary_md_path = output_dir / "disease_map_summary.md"
    disease_exporter.write_disease_summary_markdown(disease_summary, disease_summary_md_path)
    print(
        f"✓ Wrote disease_map_summary.md ({disease_summary_md_path.stat().st_size} bytes)",
        file=sys.stderr,
    )

    # Build and write artifact manifest
    manifest_exporter = ArtifactManifestExporter(
        as_of_date=args.as_of_date,
        created_at_utc=args.created_at_utc,
    )
    manifest = manifest_exporter.build_manifest(
        inputs={
            "program_records": str(programs_path.relative_to(artifact_dir)),
            "competitive_clusters": str(clusters_path.relative_to(artifact_dir)) if clusters_path.exists() else None,
            "landscape_features": str(features_path.relative_to(artifact_dir)) if features_path.exists() else None,
        },
        outputs=[
            "map_index.json",
            "disease_map_summary.json",
            "disease_map_summary.md",
            "artifact_manifest.json",
        ],
    )
    # Remove None values from inputs
    manifest["inputs"] = {k: v for k, v in manifest["inputs"].items() if v is not None}
    manifest_path = output_dir / "artifact_manifest.json"
    manifest_exporter.write_manifest(manifest, manifest_path)
    print(f"✓ Wrote artifact_manifest.json ({manifest_path.stat().st_size} bytes)", file=sys.stderr)

    # Print summary
    print("", file=sys.stderr)
    print(
        f"✓ Export complete: {len(disease_summary['diseases'])} diseases, "
        f"{len(programs)} programs, {len(clusters)} clusters, {len(features)} features",
        file=sys.stderr,
    )
    print(f"✓ Output directory: {output_dir}", file=sys.stderr)

    return 0


def qa_command(args: argparse.Namespace) -> int:
    """Run QA on artifacts.

    Arguments:
        args.as_of_date: Date of artifacts.
        args.artifact_dir: Directory containing artifacts.
    """
    artifact_dir = Path(args.artifact_dir)

    if not artifact_dir.exists():
        print(f"ERROR: Artifact directory not found: {artifact_dir}", file=sys.stderr)
        return 1

    # Generate stub QA reports
    coverage_report = {
        "as_of_date": args.as_of_date,
        "status": "Phase 0/1: Skeleton - no data ingested yet",
        "eligible_tickers": 0,
        "tickers_with_disease": 0,
        "tickers_with_asset": 0,
        "disease_coverage_pct": 0.0,
    }

    point_in_time_audit = {
        "as_of_date": args.as_of_date,
        "cache_only_mode": True,
        "network_calls_detected": False,
        "future_dated_sources": [],
        "violations": [],
    }

    coverage_path = artifact_dir / "coverage_report.json"
    pit_path = artifact_dir / "point_in_time_audit.json"

    with open(coverage_path, "w") as f:
        json.dump(coverage_report, f, indent=2)
    with open(pit_path, "w") as f:
        json.dump(point_in_time_audit, f, indent=2)

    print(f"✓ Coverage report: {coverage_path}")
    print(f"✓ PIT audit report: {pit_path}")
    return 0


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scientific Cartography Layer - Read-only diagnostic module",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # build command
    build_parser = subparsers.add_parser("build", help="Build artifacts from cache")
    build_parser.add_argument(
        "--as-of-date",
        type=str,
        default="2026-06-16",
        help="Date for artifacts (YYYY-MM-DD)",
    )
    build_parser.add_argument(
        "--snapshot-dir",
        type=str,
        default="artifacts/snapshots/2026-06-16",
        help="Path to snapshot directory",
    )
    build_parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/scientific_cartography/2026-06-16",
        help="Output directory for artifacts",
    )
    build_parser.add_argument(
        "--cache-only",
        action="store_true",
        default=True,
        help="Production mode: cache-only (no network calls)",
    )
    build_parser.add_argument(
        "--build-clusters",
        action="store_true",
        default=False,
        help="Phase 4: Build competitive clusters (count-only, no scoring)",
    )
    build_parser.set_defaults(func=build_command)

    # export-artifacts command (Phase 6.1)
    export_parser = subparsers.add_parser(
        "export-artifacts",
        help="Export Phase 6 diagnostic artifacts (CLI ergonomics)",
    )
    export_parser.add_argument(
        "--as-of-date",
        type=str,
        required=True,
        help="Date for artifacts (YYYY-MM-DD)",
    )
    export_parser.add_argument(
        "--artifact-dir",
        type=str,
        required=True,
        help="Directory containing program_records.jsonl, etc.",
    )
    export_parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Output directory for exported artifacts",
    )
    export_parser.add_argument(
        "--created-at-utc",
        type=str,
        default=None,
        help="Optional deterministic timestamp for manifest (YYYY-MM-DDTHH:MM:SSZ)",
    )
    export_parser.set_defaults(func=export_artifacts_command)

    # qa command
    qa_parser = subparsers.add_parser("qa", help="Run QA on artifacts")
    qa_parser.add_argument(
        "--as-of-date",
        type=str,
        default="2026-06-16",
        help="Date of artifacts (YYYY-MM-DD)",
    )
    qa_parser.add_argument(
        "--artifact-dir",
        type=str,
        default="artifacts/scientific_cartography/2026-06-16",
        help="Directory containing artifacts",
    )
    qa_parser.set_defaults(func=qa_command)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
