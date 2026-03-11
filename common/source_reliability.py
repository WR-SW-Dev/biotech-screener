"""Empirical catalyst-source reliability policy.

Aggregates historical calendar slip data by source × confidence × family
and maps observed error rates to deterministic trust actions:

    ALLOW     — source is reliable, full priority
    DEMOTE    — source is noisy, usable only as fallback (priority penalty)
    SUPPRESS  — source is unreliable, excluded when a cleaner source exists
    UNKNOWN   — insufficient data, preserve current behavior (no penalty)

Thresholds are centralized here for easy tuning.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "source_reliability.v1"

# ---------------------------------------------------------------------------
# Tunable thresholds (all in one place)
# ---------------------------------------------------------------------------

MIN_SAMPLE_COUNT = 5
"""Minimum observations to form a reliability opinion."""

SUPPRESS_LARGE_SLIP_RATE = 0.40
"""Suppress if >= 40% of observations are large slips (|slip| >= 14d)."""

SUPPRESS_MEDIAN_ABS_SLIP = 21
"""Suppress if median |slip| >= 21 days."""

DEMOTE_LARGE_SLIP_RATE = 0.20
"""Demote if >= 20% of observations are large slips."""

DEMOTE_MEDIAN_ABS_SLIP = 14
"""Demote if median |slip| >= 14 days."""

# Priority penalty applied in _compute_entry_priority
DEMOTE_PRIORITY_PENALTY = 2.0
"""Subtracted from priority score for DEMOTE sources."""

SUPPRESS_PRIORITY_PENALTY = 5.0
"""Subtracted from priority score for SUPPRESS sources."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReliabilityBucket:
    """Aggregated stats for a source × confidence × family bucket."""

    source: str
    confidence: str
    family: str
    sample_count: int
    mean_abs_slip_days: float
    median_abs_slip_days: float
    large_slip_rate: float
    imminent_large_slip_rate: float
    dropped_rate: float
    new_rate: float
    action: str  # ALLOW, DEMOTE, SUPPRESS, UNKNOWN
    reason: str


# ---------------------------------------------------------------------------
# Aggregation from raw slip rows
# ---------------------------------------------------------------------------


def aggregate_reliability(
    slip_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Aggregate slip rows by source × confidence × family.

    Parameters
    ----------
    slip_rows : list of dicts with fields from slips.csv
        Required: current_source, current_confidence, family, slip_days,
        large_slip, imminent, new_flag, dropped_flag

    Returns
    -------
    List of bucket dicts sorted by (source, confidence, family).
    """
    buckets: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for row in slip_rows:
        source = row.get("current_source") or row.get("prior_source") or "UNKNOWN"
        confidence = row.get("current_confidence") or row.get("prior_confidence") or "UNKNOWN"
        family = row.get("family", "OTHER")

        key = (source, confidence, family)
        if key not in buckets:
            buckets[key] = {
                "source": source,
                "confidence": confidence,
                "family": family,
                "abs_slips": [],
                "large_slip_count": 0,
                "imminent_count": 0,
                "imminent_large_slip_count": 0,
                "new_count": 0,
                "dropped_count": 0,
                "total": 0,
            }

        b = buckets[key]
        b["total"] += 1

        # Parse slip_days
        raw_slip = row.get("slip_days", "")
        if raw_slip != "" and raw_slip is not None:
            try:
                b["abs_slips"].append(abs(int(float(raw_slip))))
            except (ValueError, TypeError):
                pass

        if str(row.get("large_slip", "0")) == "1":
            b["large_slip_count"] += 1
        if str(row.get("imminent", "0")) == "1":
            b["imminent_count"] += 1
            if str(row.get("large_slip", "0")) == "1":
                b["imminent_large_slip_count"] += 1
        if str(row.get("new_flag", "0")) == "1":
            b["new_count"] += 1
        if str(row.get("dropped_flag", "0")) == "1":
            b["dropped_count"] += 1

    results = []
    for key in sorted(buckets):
        b = buckets[key]
        total = b["total"]
        abs_slips = sorted(b["abs_slips"])
        n_slips = len(abs_slips)

        mean_abs = sum(abs_slips) / n_slips if n_slips else 0.0
        median_abs = abs_slips[n_slips // 2] if n_slips else 0.0
        large_rate = b["large_slip_count"] / total if total else 0.0
        imm_large_rate = b["imminent_large_slip_count"] / b["imminent_count"] if b["imminent_count"] else 0.0
        dropped_rate = b["dropped_count"] / total if total else 0.0
        new_rate = b["new_count"] / total if total else 0.0

        results.append(
            {
                "source": b["source"],
                "confidence": b["confidence"],
                "family": b["family"],
                "sample_count": total,
                "mean_abs_slip_days": round(mean_abs, 1),
                "median_abs_slip_days": round(median_abs, 1),
                "large_slip_rate": round(large_rate, 4),
                "imminent_large_slip_rate": round(imm_large_rate, 4),
                "dropped_rate": round(dropped_rate, 4),
                "new_rate": round(new_rate, 4),
            }
        )

    return results


# ---------------------------------------------------------------------------
# Policy mapper
# ---------------------------------------------------------------------------


def apply_reliability_policy(
    buckets: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Apply deterministic policy to each bucket.

    Mutates each bucket dict in-place (adds 'action' and 'reason' keys).
    Returns the same list for convenience.
    """
    for b in buckets:
        action, reason = _classify_bucket(b)
        b["action"] = action
        b["reason"] = reason
    return buckets


def _classify_bucket(b: Dict[str, Any]) -> Tuple[str, str]:
    """Classify a single bucket into ALLOW / DEMOTE / SUPPRESS / UNKNOWN."""
    n = b.get("sample_count", 0)
    if n < MIN_SAMPLE_COUNT:
        return "UNKNOWN", f"n={n} < {MIN_SAMPLE_COUNT}"

    large_rate = b.get("large_slip_rate", 0)
    median_abs = b.get("median_abs_slip_days", 0)

    # SUPPRESS: clearly unreliable
    if large_rate >= SUPPRESS_LARGE_SLIP_RATE:
        return "SUPPRESS", f"large_slip_rate={large_rate:.0%} >= {SUPPRESS_LARGE_SLIP_RATE:.0%}"
    if median_abs >= SUPPRESS_MEDIAN_ABS_SLIP:
        return "SUPPRESS", f"median_abs_slip={median_abs:.0f}d >= {SUPPRESS_MEDIAN_ABS_SLIP}d"

    # DEMOTE: noisy but usable as fallback
    if large_rate >= DEMOTE_LARGE_SLIP_RATE:
        return "DEMOTE", f"large_slip_rate={large_rate:.0%} >= {DEMOTE_LARGE_SLIP_RATE:.0%}"
    if median_abs >= DEMOTE_MEDIAN_ABS_SLIP:
        return "DEMOTE", f"median_abs_slip={median_abs:.0f}d >= {DEMOTE_MEDIAN_ABS_SLIP}d"

    return "ALLOW", f"n={n}; median_abs_slip={median_abs:.0f}d; large_slip_rate={large_rate:.0%}"


# ---------------------------------------------------------------------------
# Reliability table I/O
# ---------------------------------------------------------------------------


def load_reliability_table(path: Path) -> List[Dict[str, Any]]:
    """Load source_reliability.json. Returns empty list if missing."""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("buckets", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("source_reliability: failed to load %s: %s", path, exc)
        return []


def write_reliability_json(
    buckets: List[Dict[str, Any]],
    out_path: Path,
    *,
    as_of_date: str = "",
    n_weeks: int = 0,
    n_slip_rows: int = 0,
) -> None:
    """Write the reliability table JSON."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "n_weeks_aggregated": n_weeks,
        "n_slip_rows": n_slip_rows,
        "buckets": buckets,
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def render_reliability_md(
    buckets: List[Dict[str, Any]],
    *,
    as_of_date: str = "",
    n_weeks: int = 0,
) -> str:
    """Render reliability table as markdown."""
    lines = [
        f"# Source Reliability Report — {as_of_date}",
        "",
        f"**Weeks aggregated**: {n_weeks}",
        f"**Schema**: {SCHEMA_VERSION}",
        "",
        "## Policy Thresholds",
        "",
        f"- Min sample: {MIN_SAMPLE_COUNT}",
        f"- SUPPRESS: large_slip_rate >= {SUPPRESS_LARGE_SLIP_RATE:.0%} OR median_abs_slip >= {SUPPRESS_MEDIAN_ABS_SLIP}d",
        f"- DEMOTE: large_slip_rate >= {DEMOTE_LARGE_SLIP_RATE:.0%} OR median_abs_slip >= {DEMOTE_MEDIAN_ABS_SLIP}d",
        "- ALLOW: below all thresholds",
        f"- UNKNOWN: sample_count < {MIN_SAMPLE_COUNT}",
        "",
        "## Reliability Table",
        "",
        "| Source | Confidence | Family | N | Mean |Slip| | Median |Slip| | Large Rate | Action | Reason |",
        "|--------|-----------|--------|---|------------|-------------|------------|--------|--------|",
    ]

    for b in buckets:
        lines.append(
            f"| {b['source']} | {b['confidence']} | {b['family']} "
            f"| {b['sample_count']} | {b['mean_abs_slip_days']:.1f}d "
            f"| {b['median_abs_slip_days']:.1f}d | {b['large_slip_rate']:.0%} "
            f"| **{b.get('action', '?')}** | {b.get('reason', '')} |"
        )

    # Summary counts
    action_counts: Dict[str, int] = {}
    for b in buckets:
        a = b.get("action", "UNKNOWN")
        action_counts[a] = action_counts.get(a, 0) + 1

    lines.extend(
        [
            "",
            "## Summary",
            "",
        ]
    )
    for action in ("ALLOW", "DEMOTE", "SUPPRESS", "UNKNOWN"):
        lines.append(f"- {action}: {action_counts.get(action, 0)} buckets")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lookup: get action for a source in the priority pipeline
# ---------------------------------------------------------------------------


def get_source_action(
    table: List[Dict[str, Any]],
    source: str,
    confidence: str = "",
    family: str = "",
) -> Tuple[str, str]:
    """Look up the reliability action for a source.

    Tries exact match (source, confidence, family) first, then
    broadens: (source, confidence, *), then (source, *, *).

    Returns (action, reason). Falls back to ("UNKNOWN", "no data").
    """
    if not table:
        return "UNKNOWN", "no reliability data"

    # Build lookup index
    exact: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    by_src_conf: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    by_src: Dict[str, List[Dict[str, Any]]] = {}

    for b in table:
        k = (b["source"], b.get("confidence", ""), b.get("family", ""))
        exact[k] = b
        sc = (b["source"], b.get("confidence", ""))
        by_src_conf.setdefault(sc, []).append(b)
        by_src.setdefault(b["source"], []).append(b)

    # Exact match
    hit = exact.get((source, confidence, family))
    if hit:
        return hit.get("action", "UNKNOWN"), hit.get("reason", "")

    # Source + confidence match — take worst action across families
    hits = by_src_conf.get((source, confidence), [])
    if hits:
        return _worst_action(hits)

    # Source-only match — take worst action
    hits = by_src.get(source, [])
    if hits:
        return _worst_action(hits)

    return "UNKNOWN", "no data"


_ACTION_SEVERITY = {"SUPPRESS": 3, "DEMOTE": 2, "UNKNOWN": 1, "ALLOW": 0}


def _worst_action(buckets: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Return the most severe action across a set of buckets."""
    worst = max(buckets, key=lambda b: _ACTION_SEVERITY.get(b.get("action", "UNKNOWN"), 0))
    return worst.get("action", "UNKNOWN"), worst.get("reason", "")


def compute_priority_penalty(action: str) -> float:
    """Return priority penalty for a reliability action.

    ALLOW / UNKNOWN → 0 (no change)
    DEMOTE → -2.0
    SUPPRESS → -5.0
    """
    if action == "SUPPRESS":
        return SUPPRESS_PRIORITY_PENALTY
    if action == "DEMOTE":
        return DEMOTE_PRIORITY_PENALTY
    return 0.0
