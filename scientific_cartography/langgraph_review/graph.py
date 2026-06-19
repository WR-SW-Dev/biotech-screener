"""LangGraph workflow graph for Scientific Cartography review."""

try:
    from langgraph.graph import END, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False


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


def build_cartography_review_graph():
    """Build the LangGraph workflow for Scientific Cartography review.

    Returns a compiled graph that orchestrates the review workflow.

    Raises:
        ImportError: If LangGraph is not installed.
    """
    if not LANGGRAPH_AVAILABLE:
        raise ImportError(
            "LangGraph is not installed. "
            "Install it before running this workflow. "
            "Deterministic nodes can still be tested without LangGraph."
        )

    graph = StateGraph(CartographyReviewState)

    graph.add_node("initialize_review", initialize_review)
    graph.add_node("load_artifact_index", load_artifact_index)
    graph.add_node("validate_artifact_structure", validate_artifact_structure)
    graph.add_node("run_governance_scan", run_governance_scan)
    graph.add_node("select_review_diseases", select_review_diseases)
    graph.add_node("build_review_summary", build_review_summary)
    graph.add_node("optional_human_review_gate", optional_human_review_gate)
    graph.add_node("write_review_outputs", write_review_outputs)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("initialize_review")

    graph.add_edge("initialize_review", "load_artifact_index")
    graph.add_edge("load_artifact_index", "validate_artifact_structure")
    graph.add_edge("validate_artifact_structure", "run_governance_scan")
    graph.add_edge("run_governance_scan", "select_review_diseases")
    graph.add_edge("select_review_diseases", "build_review_summary")
    graph.add_edge("build_review_summary", "optional_human_review_gate")
    graph.add_edge("optional_human_review_gate", "write_review_outputs")
    graph.add_edge("write_review_outputs", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


def run_cartography_review_workflow(state: CartographyReviewState) -> CartographyReviewState:
    """Execute the cartography review workflow.

    Args:
        state: Initial workflow state.

    Returns:
        Final workflow state with all outputs populated.

    Raises:
        ImportError: If LangGraph is not available.
    """
    if not LANGGRAPH_AVAILABLE:
        raise ImportError(
            "LangGraph is not installed. " "Cannot run graph workflow. " "Run deterministic nodes directly instead."
        )

    compiled_graph = build_cartography_review_graph()
    result = compiled_graph.invoke(state)

    return result
