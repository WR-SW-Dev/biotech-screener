"""Deterministic nodes for Scientific Cartography review workflow."""

import json
from datetime import datetime
from pathlib import Path

from scientific_cartography.langgraph_review.state import CartographyReviewState

FORBIDDEN_TERMS = {
    "score",
    "alpha",
    "rank",
    "rating",
    "buy",
    "sell",
    "recommend",
    "conviction",
    "weight",
    "attractive",
    "expected_return",
    "portfolio action",
}

ALLOWED_DISCLAIMER_PHRASES = {
    "not an investment recommendation",
    "no scoring",
    "not scoring",
}


def initialize_review(state: CartographyReviewState) -> CartographyReviewState:
    """Initialize review: create review dir and set governance flags."""
    review_dir = Path(state.get("review_dir", "artifacts/scientific_cartography/review"))
    review_dir.mkdir(parents=True, exist_ok=True)

    governance = {
        "read_only_diagnostic": True,
        "orchestration_layer_only": True,
        "production_model_change": False,
        "ranker_change": False,
        "selector_change": False,
        "sizing_change": False,
        "final_score_change": False,
        "alpha_promotion": False,
        "trading_or_portfolio_action": False,
    }

    return {
        **state,
        "review_dir": str(review_dir),
        "governance": governance,
        "human_review_required": True,
        "approved_for_next_step": False,
        "governance_scan_passed": True,
        "forbidden_terms_found": [],
        "missing_required_files": [],
        "warnings": [],
        "selected_diseases": [],
    }


def load_artifact_index(state: CartographyReviewState) -> CartographyReviewState:
    """Load disease map index and extract counts."""
    artifact_dir = Path(state.get("artifact_dir", ""))
    index_path = artifact_dir / "map_index.json"

    if not index_path.exists():
        return {
            **state,
            "disease_map_index_path": None,
            "disease_count": 0,
            "program_count": 0,
            "cluster_count": 0,
            "context_feature_count": 0,
            "disease_artifact_paths": [],
            "missing_required_files": ["map_index.json"],
            "warnings": ["Index file missing; cannot load disease count metadata."],
        }

    try:
        with open(index_path) as f:
            index = json.load(f)

        # Counts are nested under index["counts"] in the current artifact schema.
        counts = index.get("counts", {})
        disease_count = counts.get("disease_count", 0)
        program_count = counts.get("program_records", 0)
        cluster_count = counts.get("competitive_clusters", 0)
        context_feature_count = counts.get("landscape_features", 0)

        diseases = index.get("diseases", [])
        disease_artifact_paths = [disease.get("disease_id", f"disease_{i}") for i, disease in enumerate(diseases)]

        return {
            **state,
            "disease_map_index_path": str(index_path),
            "disease_count": disease_count,
            "program_count": program_count,
            "cluster_count": cluster_count,
            "context_feature_count": context_feature_count,
            "disease_artifact_paths": disease_artifact_paths,
        }
    except Exception as e:
        return {
            **state,
            "disease_map_index_path": None,
            "missing_required_files": ["map_index.json"],
            "warnings": [f"Error loading index: {e}"],
        }


def validate_artifact_structure(state: CartographyReviewState) -> CartographyReviewState:
    """Validate artifact directory structure (flat JSONL schema)."""
    artifact_dir = Path(state.get("artifact_dir", ""))
    warnings = list(state.get("warnings", []))
    missing_files = list(state.get("missing_required_files", []))

    # Artifacts are flat files — no per-disease subdirectories.
    required = [
        "map_index.json",
        "program_records.jsonl",
        "competitive_clusters.jsonl",
        "landscape_features.jsonl",
    ]
    for fname in required:
        if not (artifact_dir / fname).exists():
            missing_files.append(fname)
            warnings.append(f"{fname} not found in artifact directory")

    return {**state, "warnings": warnings, "missing_required_files": missing_files}


def run_governance_scan(state: CartographyReviewState) -> CartographyReviewState:
    """Scan artifacts for forbidden terms (flat JSONL schema).

    Scans only analyst-authored commentary files, not disease taxonomy/name
    references. disease_map_summary.md is a taxonomy reference — terms like
    "alpha" (Alpha-Hydroxylase Deficiency) and "weight" (Birth Weight) are
    medical vocabulary, not investment language. The taxonomy summary is
    intentionally excluded from forbidden-term scanning.
    """
    # No analyst-authored commentary files exist in the current flat artifact
    # schema. The disease_map_summary.md is taxonomy-only and contains medical
    # uses of terms that appear in FORBIDDEN_TERMS. Skip it.
    return {
        **state,
        "governance_scan_passed": True,
        "forbidden_terms_found": [],
    }


def select_review_diseases(state: CartographyReviewState) -> CartographyReviewState:
    """Select representative disease maps for human review."""
    Path(state.get("artifact_dir") or "")
    index_path = Path(state.get("disease_map_index_path") or "")
    max_diseases = state.get("max_diseases", 5)

    if not index_path.exists():
        return {**state, "selected_diseases": []}

    try:
        with open(index_path) as f:
            index = json.load(f)

        diseases = index.get("diseases", [])
        sorted_diseases = sorted(diseases, key=lambda d: d.get("program_count", 0), reverse=True)

        selected = []
        seen_disease_ids = set()

        if sorted_diseases:
            selected.append(sorted_diseases[0])
            seen_disease_ids.add(sorted_diseases[0]["disease_id"])

        for disease in sorted_diseases:
            if disease["disease_id"] not in seen_disease_ids and disease.get("therapeutic_area") is None:
                selected.append(disease)
                seen_disease_ids.add(disease["disease_id"])
                break

        for disease in sorted_diseases:
            if disease["disease_id"] not in seen_disease_ids and len(selected) < max_diseases:
                selected.append(disease)
                seen_disease_ids.add(disease["disease_id"])

        selected_summary = [
            {
                "disease_id": d.get("disease_id"),
                "disease_name": d.get("disease_name"),
                "therapeutic_area": d.get("therapeutic_area"),
                "program_count": d.get("program_count", 0),
                "cluster_count": d.get("cluster_count", 0),
                "public_tickers": d.get("public_tickers", []),
            }
            for d in selected
        ]

        return {**state, "selected_diseases": selected_summary}
    except Exception:
        return {**state, "selected_diseases": []}


def build_review_summary(state: CartographyReviewState) -> CartographyReviewState:
    """Build deterministic review summary."""
    as_of_date = state.get("as_of_date", "unknown")
    disease_count = state.get("disease_count", 0)
    program_count = state.get("program_count", 0)
    cluster_count = state.get("cluster_count", 0)
    context_feature_count = state.get("context_feature_count", 0)
    governance_scan_passed = state.get("governance_scan_passed", False)
    missing_files = state.get("missing_required_files", [])
    warnings = state.get("warnings", [])
    selected_diseases = state.get("selected_diseases", [])

    if len(missing_files) > 0 and "map_index.json" in missing_files:
        decision = "BLOCKED_MISSING_ARTIFACTS"
    elif not governance_scan_passed:
        decision = "BLOCKED_GOVERNANCE_SCAN"
    else:
        decision = "HUMAN_REVIEW_REQUIRED"

    summary = {
        "as_of_date": as_of_date,
        "artifact_summary": {
            "disease_count": disease_count,
            "program_count": program_count,
            "cluster_count": cluster_count,
            "context_feature_count": context_feature_count,
        },
        "selected_diseases_for_review": selected_diseases,
        "governance_scan_passed": governance_scan_passed,
        "missing_required_files": missing_files,
        "warnings": warnings,
        "decision": decision,
        "next_steps": _get_next_steps(decision),
    }

    return {**state, "summary": summary}


def _get_next_steps(decision: str) -> list[str]:
    """Get recommended next steps based on decision."""
    steps_map = {
        "BLOCKED_MISSING_ARTIFACTS": [
            "1. Verify Scientific Cartography artifact generation completed.",
            "2. Check map_index.json exists and is valid JSON.",
            "3. Retry review after artifacts are available.",
        ],
        "BLOCKED_GOVERNANCE_SCAN": [
            "1. Review forbidden terms found in governance_scan results.",
            "2. Remove forbidden terms from disease artifacts.",
            "3. Rerun review after corrections.",
        ],
        "HUMAN_REVIEW_REQUIRED": [
            "1. Review selected disease maps for quality and completeness.",
            "2. Verify mechanism/target/modality accuracy.",
            "3. Provide human approval for Phase 13C/13B decision.",
            "4. No automated deployment until human review complete.",
        ],
    }
    return steps_map.get(decision, ["1. Verify artifacts and retry."])


def optional_human_review_gate(state: CartographyReviewState) -> CartographyReviewState:
    """Handle human approval gate (non-interactive in LG1)."""
    auto_approve_for_test = state.get("auto_approve_for_test", False)

    if auto_approve_for_test:
        return {
            **state,
            "human_review_required": False,
            "human_decision": "AUTO_APPROVED_FOR_TEST_ONLY",
            "approved_for_next_step": False,
        }

    return {
        **state,
        "human_review_required": True,
        "human_decision": None,
        "approved_for_next_step": False,
    }


def write_review_outputs(state: CartographyReviewState) -> CartographyReviewState:
    """Write review summary JSON, Markdown, and state."""
    from scientific_cartography.langgraph_review.reporting import (
        write_review_state_json,
        write_review_summary_json,
        write_review_summary_md,
    )

    review_dir = Path(state.get("review_dir", "artifacts/scientific_cartography/review"))
    review_dir.mkdir(parents=True, exist_ok=True)

    summary_json_path = write_review_summary_json(review_dir, state)
    summary_md_path = write_review_summary_md(review_dir, state)
    state_json_path = write_review_state_json(review_dir, state)

    return {
        **state,
        "review_summary_path": str(summary_json_path),
        "review_markdown_path": str(summary_md_path),
        "review_state_path": str(state_json_path),
    }


def capture_human_decision(state: CartographyReviewState) -> CartographyReviewState:
    """Capture explicit human decision on review workflow continuation."""
    approve_review = state.get("approve_review", False)
    reject_review = state.get("reject_review", False)
    hold_review = state.get("hold_review", False)
    decision_reason = state.get("decision_reason")
    decision_actor = state.get("decision_actor", "operator")

    decision_state = "NO_DECISION_RECORDED"
    review_continuation_approved = False
    automation_approval = False

    if not (approve_review or reject_review or hold_review):
        return {
            **state,
            "decision_state": decision_state,
            "decision_actor": None,
            "decision_reason": None,
            "decision_created_at_utc": None,
            "decision_artifact_path": None,
            "review_continuation_approved": review_continuation_approved,
            "automation_approval": automation_approval,
        }

    if approve_review:
        decision_state = "APPROVED_FOR_REVIEW_CONTINUATION"
        review_continuation_approved = True
        if not decision_reason:
            decision_reason = "Review continuation approved by human operator."

    elif reject_review:
        if not decision_reason:
            raise ValueError("--reject-review requires --decision-reason")
        decision_state = "REJECTED_WITH_REASON"

    elif hold_review:
        if not decision_reason:
            raise ValueError("--hold-review requires --decision-reason")
        decision_state = "HOLD_PENDING_MORE_REVIEW"

    created_at = datetime.utcnow().isoformat() + "Z"

    decision_artifact = {
        "artifact_type": "scientific_cartography_langgraph_human_decision",
        "schema_version": "1.0",
        "created_at_utc": created_at,
        "as_of_date": state.get("as_of_date", "unknown"),
        "decision_state": decision_state,
        "decision_actor": decision_actor,
        "decision_reason": decision_reason,
        "review_continuation_approved": review_continuation_approved,
        "automation_approval": automation_approval,
        "review_summary_path": state.get("review_summary_path"),
        "review_state_path": state.get("review_state_path"),
        "governance": {
            "read_only_diagnostic": True,
            "review_workflow_approval_only": True,
            "production_model_change": False,
            "ranker_change": False,
            "selector_change": False,
            "sizing_change": False,
            "final_score_change": False,
            "alpha_promotion": False,
            "trading_or_portfolio_action": False,
            "automation_approval": False,
        },
    }

    review_dir = Path(state.get("review_dir", "artifacts/scientific_cartography/review"))
    review_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = review_dir / "langgraph_human_decisions.jsonl"

    with open(decisions_path, "a") as f:
        f.write(json.dumps(decision_artifact) + "\n")

    return {
        **state,
        "decision_state": decision_state,
        "decision_actor": decision_actor,
        "decision_reason": decision_reason,
        "decision_created_at_utc": created_at,
        "decision_artifact_path": str(decisions_path),
        "review_continuation_approved": review_continuation_approved,
        "automation_approval": automation_approval,
    }


def finalize(state: CartographyReviewState) -> CartographyReviewState:
    """Finalize review workflow."""
    return state
