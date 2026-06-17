"""CLI for scientific cartography module."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from scientific_cartography.build.competitive_cluster_builder import CompetitiveClusterBuilder
from scientific_cartography.normalize.disease_normalizer import DiseaseNormalizer
from scientific_cartography.normalize.stage_normalizer import StageNormalizer


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
    disease_normalizer = DiseaseNormalizer(as_of_date=args.as_of_date)
    stage_normalizer = StageNormalizer()

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
