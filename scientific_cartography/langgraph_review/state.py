"""State schema for LangGraph-based Scientific Cartography review orchestrator."""

from typing import Any, TypedDict


class CartographyReviewState(TypedDict, total=False):
    """Typed state for the cartography review workflow.

    All fields are optional (total=False) to allow progressive state building.
    State is JSON-serializable and stores paths, counts, summaries only (not large artifacts).
    """

    # Input parameters
    as_of_date: str
    artifact_dir: str
    review_dir: str

    # Index metadata
    disease_map_index_path: str | None
    disease_count: int
    program_count: int
    cluster_count: int
    context_feature_count: int

    # Artifact discovery
    disease_artifact_paths: list[str]

    # Disease selection
    selected_diseases: list[dict[str, Any]]
    max_diseases: int

    # Governance & validation
    governance_scan_passed: bool
    forbidden_terms_found: list[dict[str, Any]]
    missing_required_files: list[str]
    warnings: list[str]

    # Output paths
    review_summary_path: str | None
    review_markdown_path: str | None
    review_state_path: str | None

    # Human-in-the-loop
    human_review_required: bool
    human_decision: str | None
    approved_for_next_step: bool

    # Test/CLI flags
    auto_approve_for_test: bool
    strict: bool
    require_human_review: bool

    # Governance block (explicit immutable flags)
    governance: dict[str, Any]

    # Summary (deterministic, audit-friendly)
    summary: dict[str, Any]
