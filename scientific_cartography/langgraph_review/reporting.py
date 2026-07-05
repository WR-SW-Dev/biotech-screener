"""Reporting writers for Scientific Cartography review workflow."""

import json
from pathlib import Path

from scientific_cartography.langgraph_review.state import CartographyReviewState
from scientific_cartography.langgraph_review.timestamps import generated_at_from_state


def write_review_summary_json(review_dir: Path, state: CartographyReviewState) -> Path:
    """Write review summary as JSON."""
    summary = state.get("summary", {})
    governance = state.get("governance", {})

    output = {
        "artifact_type": "scientific_cartography_langgraph_review_summary",
        "generated_at": generated_at_from_state(state),
        "governance": governance,
        **summary,
    }

    decision_state = state.get("decision_state", "NO_DECISION_RECORDED")
    if decision_state and decision_state != "NO_DECISION_RECORDED":
        output["human_decision"] = {
            "decision_state": decision_state,
            "decision_actor": state.get("decision_actor"),
            "decision_reason": state.get("decision_reason"),
            "review_continuation_approved": state.get("review_continuation_approved", False),
            "automation_approval": state.get("automation_approval", False),
        }

    output_path = review_dir / "langgraph_review_summary.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    return output_path


def write_review_summary_md(review_dir: Path, state: CartographyReviewState) -> Path:
    """Write review summary as Markdown."""
    summary = state.get("summary", {})
    governance = state.get("governance", {})
    selected_diseases = state.get("selected_diseases", [])
    forbidden_terms = state.get("forbidden_terms_found", [])
    missing_files = state.get("missing_required_files", [])
    warnings = state.get("warnings", [])

    lines = []

    lines.append("# Scientific Cartography LangGraph Review")
    lines.append("")
    lines.append(f"Generated: {generated_at_from_state(state)}")
    lines.append("")

    lines.append("## Governance")
    lines.append("")
    for key, value in governance.items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")

    lines.append("## Artifact Summary")
    lines.append("")
    artifact_summary = summary.get("artifact_summary", {})
    lines.append(f"- **Date**: {summary.get('as_of_date', 'unknown')}")
    lines.append(f"- **Diseases**: {artifact_summary.get('disease_count', 0)}")
    lines.append(f"- **Programs**: {artifact_summary.get('program_count', 0)}")
    lines.append(f"- **Clusters**: {artifact_summary.get('cluster_count', 0)}")
    lines.append(f"- **Context Features**: {artifact_summary.get('context_feature_count', 0)}")
    lines.append("")

    lines.append("## Selected Diseases for Human Review")
    lines.append("")
    if selected_diseases:
        for i, disease in enumerate(selected_diseases, 1):
            name = disease.get("disease_name") or disease.get("normalized_disease_name", "unknown")
            area = disease.get("therapeutic_area") or disease.get("mondo_id", "unknown")
            prog_count = disease.get("program_count", 0)
            cluster_count = disease.get("cluster_count", 0)
            tickers = disease.get("public_tickers", [])
            lines.append(f"{i}. **{name}**")
            lines.append(f"   - Therapeutic Area: {area}")
            lines.append(f"   - Programs: {prog_count}")
            lines.append(f"   - Clusters: {cluster_count}")
            if tickers:
                lines.append(f"   - Public Tickers: {', '.join(tickers[:5])}")
            lines.append("")
    else:
        lines.append("(No diseases selected)")
        lines.append("")

    lines.append("## Governance Scan")
    lines.append("")
    governance_passed = summary.get("governance_scan_passed", False)
    lines.append(f"**Status**: {'PASS' if governance_passed else 'FAIL'}")
    lines.append("")

    if forbidden_terms:
        lines.append("**Forbidden Terms Found**:")
        lines.append("")
        for term_match in forbidden_terms[:10]:
            disease = term_match.get("disease", "unknown")
            term = term_match.get("term", "unknown")
            lines.append(f"- {disease}: `{term}`")
        lines.append("")
    else:
        lines.append("No forbidden terms detected.")
        lines.append("")

    if missing_files:
        lines.append("## Missing Files")
        lines.append("")
        for file in missing_files:
            lines.append(f"- {file}")
        lines.append("")

    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    decision_state = state.get("decision_state", "NO_DECISION_RECORDED")
    if decision_state and decision_state != "NO_DECISION_RECORDED":
        lines.append("## Human Decision")
        lines.append("")
        lines.append(f"**Decision State**: {decision_state}")
        lines.append(f"**Decision Actor**: {state.get('decision_actor', 'unknown')}")
        decision_reason = state.get("decision_reason")
        if decision_reason:
            lines.append(f"**Decision Reason**: {decision_reason}")
        lines.append(f"**Review Continuation Approved**: {state.get('review_continuation_approved', False)}")
        lines.append(f"**Automation Approval**: {state.get('automation_approval', False)}")
        lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    decision = summary.get("decision", "UNKNOWN")
    lines.append(f"**Recommended Decision**: {decision}")
    lines.append("")

    lines.append("## Next Steps")
    lines.append("")
    next_steps = summary.get("next_steps", [])
    for step in next_steps:
        lines.append(f"- {step}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Note**: This is a read-only diagnostic review summary.")
    lines.append("")
    lines.append("**Governance**: No scoring, ranking, or portfolio decisions are made by this workflow.")
    lines.append("Human review and explicit approval are required before any deployment decisions.")

    output_path = review_dir / "langgraph_review_summary.md"
    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    return output_path


def write_review_state_json(review_dir: Path, state: CartographyReviewState) -> Path:
    """Write full review state as JSON (for debugging and audit)."""
    serializable_state = {}

    for key, value in state.items():
        try:
            json.dumps({key: value})
            serializable_state[key] = value
        except (TypeError, ValueError):
            pass

    output = {
        "artifact_type": "scientific_cartography_langgraph_review_state",
        "generated_at": generated_at_from_state(state),
        "state": serializable_state,
    }

    output_path = review_dir / "langgraph_review_state.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    return output_path
