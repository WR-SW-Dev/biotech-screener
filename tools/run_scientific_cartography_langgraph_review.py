#!/usr/bin/env python3
"""CLI for LangGraph-based Scientific Cartography review orchestrator.

Usage:
    python3 tools/run_scientific_cartography_langgraph_review.py \\
        --as-of-date 2026-06-18 \\
        --artifact-dir artifacts/scientific_cartography/2026-06-18

Optional:
    --review-dir <path>          (default: artifact_dir/review)
    --max-diseases <n>           (default: 5)
    --auto-approve-for-test      (test mode; does not approve deployment)
    --require-human-review       (enforce human review requirement)
    --strict                     (exit nonzero if governance scan fails)
"""

import argparse
import sys
from pathlib import Path

# Add repo root to sys.path so imports work from any directory
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scientific_cartography.langgraph_review.graph import run_cartography_review_workflow
from scientific_cartography.langgraph_review.nodes import (
    build_review_summary,
    finalize,
    initialize_review,
    load_artifact_index,
    optional_human_review_gate,
    run_governance_scan,
    select_review_diseases,
    validate_artifact_structure,
    write_review_outputs,
)
from scientific_cartography.langgraph_review.state import CartographyReviewState


def run_deterministic_pipeline(
    as_of_date: str,
    artifact_dir: str,
    review_dir: str | None = None,
    max_diseases: int = 5,
    auto_approve_for_test: bool = False,
    strict: bool = False,
) -> CartographyReviewState:
    """Run the review pipeline using deterministic nodes (graph-independent)."""
    if review_dir is None:
        review_dir = str(Path(artifact_dir) / "review")

    state: CartographyReviewState = {
        "as_of_date": as_of_date,
        "artifact_dir": artifact_dir,
        "review_dir": review_dir,
        "max_diseases": max_diseases,
        "auto_approve_for_test": auto_approve_for_test,
        "strict": strict,
    }

    state = initialize_review(state)
    state = load_artifact_index(state)
    state = validate_artifact_structure(state)
    state = run_governance_scan(state)
    state = select_review_diseases(state)
    state = build_review_summary(state)
    state = optional_human_review_gate(state)
    state = write_review_outputs(state)
    state = finalize(state)

    return state


def run_graph_pipeline(
    as_of_date: str,
    artifact_dir: str,
    review_dir: str | None = None,
    max_diseases: int = 5,
    auto_approve_for_test: bool = False,
    strict: bool = False,
) -> CartographyReviewState:
    """Run the review pipeline using LangGraph (if available)."""
    if review_dir is None:
        review_dir = str(Path(artifact_dir) / "review")

    state: CartographyReviewState = {
        "as_of_date": as_of_date,
        "artifact_dir": artifact_dir,
        "review_dir": review_dir,
        "max_diseases": max_diseases,
        "auto_approve_for_test": auto_approve_for_test,
        "strict": strict,
    }

    try:
        return run_cartography_review_workflow(state)
    except ImportError:
        print(
            "WARNING: LangGraph not available; running deterministic pipeline instead.",
            file=sys.stderr,
        )
        return run_deterministic_pipeline(
            as_of_date=as_of_date,
            artifact_dir=artifact_dir,
            review_dir=review_dir,
            max_diseases=max_diseases,
            auto_approve_for_test=auto_approve_for_test,
            strict=strict,
        )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run Scientific Cartography LangGraph review orchestrator.",
    )

    parser.add_argument("--as-of-date", required=True, help="Snapshot date (YYYY-MM-DD)")
    parser.add_argument("--artifact-dir", required=True, help="Path to Scientific Cartography artifacts")
    parser.add_argument("--review-dir", default=None, help="Output review directory (default: artifact-dir/review)")
    parser.add_argument("--max-diseases", type=int, default=5, help="Max diseases to select (default: 5)")
    parser.add_argument(
        "--auto-approve-for-test",
        action="store_true",
        help="Auto-approve for testing (does not approve deployment)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero if governance scan fails or required files missing",
    )
    parser.add_argument(
        "--use-graph",
        action="store_true",
        default=True,
        help="Use LangGraph if available (default)",
    )

    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir)
    if not artifact_dir.exists():
        print(f"ERROR: Artifact directory not found: {artifact_dir}", file=sys.stderr)
        sys.exit(1)

    if args.use_graph:
        result = run_graph_pipeline(
            as_of_date=args.as_of_date,
            artifact_dir=str(artifact_dir),
            review_dir=args.review_dir,
            max_diseases=args.max_diseases,
            auto_approve_for_test=args.auto_approve_for_test,
            strict=args.strict,
        )
    else:
        result = run_deterministic_pipeline(
            as_of_date=args.as_of_date,
            artifact_dir=str(artifact_dir),
            review_dir=args.review_dir,
            max_diseases=args.max_diseases,
            auto_approve_for_test=args.auto_approve_for_test,
            strict=args.strict,
        )

    review_dir = result.get("review_dir", "unknown")
    summary = result.get("summary", {})
    decision = summary.get("decision", "UNKNOWN")
    governance_passed = summary.get("governance_scan_passed", False)

    print("\nLANGGRAPH_CARTOGRAPHY_REVIEW_COMPLETE")
    print(f"governance_scan_passed={governance_passed}")
    print(f"decision={decision}")
    print(f"review_dir={review_dir}")

    selected_count = len(result.get("selected_diseases", []))
    print(f"selected_disease_count={selected_count}")

    if args.strict:
        missing_files = result.get("missing_required_files", [])
        if "disease_map_index.json" in missing_files:
            print("ERROR: Required index file missing (--strict mode)", file=sys.stderr)
            sys.exit(1)
        if not governance_passed:
            print("ERROR: Governance scan failed (--strict mode)", file=sys.stderr)
            sys.exit(1)

    print("\nReview outputs:")
    summary_path = result.get("review_summary_path")
    if summary_path:
        print(f"  JSON: {summary_path}")

    md_path = result.get("review_markdown_path")
    if md_path:
        print(f"  Markdown: {md_path}")

    state_path = result.get("review_state_path")
    if state_path:
        print(f"  State: {state_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
