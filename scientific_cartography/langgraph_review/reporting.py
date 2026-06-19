"""Reporting writers for Scientific Cartography review workflow."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scientific_cartography.langgraph_review.state import CartographyReviewState


def write_review_summary_json(review_dir: Path, state: CartographyReviewState) -> Path:
    """Write review summary as JSON."""
    summary = state.get("summary", {})
    governance = state.get("governance", {})

    output = {
        "artifact_type": "scientific_cartography_langgraph_review_summary",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "governance": governance,
        **summary,
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
    lines.append(f"Generated: {datetime.utcnow().isoformat()}Z")
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
            name = disease.get("normalized_disease_name", "unknown")
            mondo = disease.get("mondo_id", "unknown")
            prog_count = disease.get("program_count", 0)
            cluster_count = disease.get("cluster_count", 0)
            lines.append(f"{i}. **{name}**")
            lines.append(f"   - MONDO ID: {mondo}")
            lines.append(f"   - Programs: {prog_count}")
            lines.append(f"   - Clusters: {cluster_count}")
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

    lines.append("## Decision")
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
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "state": serializable_state,
    }

    output_path = review_dir / "langgraph_review_state.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    return output_path
