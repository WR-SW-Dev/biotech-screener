"""Deterministic timestamp helpers for LangGraph review artifacts."""

from __future__ import annotations

from scientific_cartography.langgraph_review.state import CartographyReviewState


def generated_at_from_state(state: CartographyReviewState) -> str:
    """Derive a stable UTC timestamp from the review as_of_date."""
    as_of_date = state.get("as_of_date") or "1970-01-01"
    return f"{as_of_date}T00:00:00.000000Z"


def generated_at_from_as_of_date(as_of_date: str | None) -> str:
    """Derive a stable UTC timestamp from an ISO date string."""
    date = as_of_date or "1970-01-01"
    return f"{date}T00:00:00.000000Z"
