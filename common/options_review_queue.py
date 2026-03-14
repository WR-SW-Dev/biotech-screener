"""Daily options mispricing review queue.

Identifies names where options markets may be mispricing event magnitude,
catalyst timing, or model-vs-market disagreement. Non-ranking, review-only.

Triggers:
  A. Cheap/rich straddle vs historical hard-catalyst moves
  B. High market-model disagreement
  C. Term structure flags (mismatch, blind spot, not pricing)
  D. Extreme skew (RR_25d)
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List

from common.hard_catalyst import classify_hard_catalyst


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def derive_review_reasons(row: dict) -> List[str]:
    """Determine which review triggers a row satisfies."""
    reasons = []

    hc = classify_hard_catalyst(
        row.get("catalyst_event_type", ""),
        row.get("catalyst_source", ""),
    )
    if hc["is_hard_catalyst"]:
        reasons.append("hard_catalyst")

    cvs = _safe_float(row.get("cheap_vol_score"))
    if cvs >= 1.30:
        reasons.append("cheap_straddle")
    elif cvs > 0 and cvs <= 0.70:
        reasons.append("rich_straddle")

    if row.get("market_model_disagreement") == "high":
        reasons.append("high_disagreement")

    if row.get("ts_flag") == "1":
        ts_type = row.get("ts_flag_type", "")
        reasons.append(f"term_structure_{ts_type.lower()}" if ts_type else "term_structure_flag")

    rr = _safe_float(row.get("opt_rr_25d"))
    if abs(rr) >= 0.15:
        reasons.append("extreme_skew")

    return reasons


def compute_review_priority(row: dict, reasons: List[str]) -> int:
    """Compute priority score for queue ordering."""
    score = 0
    if "high_disagreement" in reasons:
        score += 3
    if any(r.startswith("term_structure") for r in reasons):
        score += 2
    if "hard_catalyst" in reasons:
        score += 2
    if "cheap_straddle" in reasons or "rich_straddle" in reasons:
        score += 2
    if "extreme_skew" in reasons:
        score += 1

    cat_days = _safe_float(row.get("catalyst_days"), 9999)
    if 0 < cat_days <= 90:
        score += 1

    return score


QUEUE_COLUMNS = [
    "ticker",
    "tier_any",
    "eligible",
    "archetype",
    "catalyst_days",
    "catalyst_mode",
    "catalyst_family",
    "catalyst_event_type",
    "catalyst_source",
    "is_hard_catalyst",
    "hard_catalyst_reason",
    "composite_score",
    "opt_atm_iv",
    "opt_term_slope",
    "opt_rr_25d",
    "opt_put_call_skew",
    "implied_event_move",
    "pos_divergence",
    "market_model_disagreement",
    "ts_flag",
    "ts_flag_type",
    "cheap_vol_score",
    "vol_classification",
    "iv_crush_breakeven_pct",
    "crush_adjusted_implied_move",
    "review_priority_score",
    "review_reasons",
]


def build_options_review_queue(
    csv_rows: List[dict],
    max_rows: int = 0,
    hard_only: bool = True,
) -> Dict[str, Any]:
    """Build the daily options mispricing review queue.

    Args:
        hard_only: If True (default), only include rows where is_hard_catalyst
            is True.  Soft/CTGov-calendar rows are excluded to avoid polluting
            the queue with PCD noise.

    Returns dict with summary and rows list.
    """
    queue_rows: List[Dict[str, Any]] = []
    n_soft_skipped = 0

    for row in csv_rows:
        hc = classify_hard_catalyst(
            row.get("catalyst_event_type", ""),
            row.get("catalyst_source", ""),
        )

        if hard_only and not hc["is_hard_catalyst"]:
            n_soft_skipped += 1
            continue

        reasons = derive_review_reasons(row)
        if not reasons:
            continue
        priority = compute_review_priority(row, reasons)

        entry: Dict[str, Any] = {}
        for col in QUEUE_COLUMNS:
            if col == "is_hard_catalyst":
                entry[col] = "1" if hc["is_hard_catalyst"] else "0"
            elif col == "hard_catalyst_reason":
                entry[col] = hc["reason"]
            elif col == "review_priority_score":
                entry[col] = priority
            elif col == "review_reasons":
                entry[col] = ";".join(reasons)
            else:
                entry[col] = row.get(col, "")

        queue_rows.append(entry)

    # Sort by priority descending, then catalyst_days ascending
    queue_rows.sort(
        key=lambda r: (
            -r.get("review_priority_score", 0),
            _safe_float(r.get("catalyst_days"), 9999),
            -abs(_safe_float(r.get("pos_divergence"))),
        )
    )

    if max_rows > 0:
        queue_rows = queue_rows[:max_rows]

    # Summary
    n_hard = sum(1 for r in queue_rows if r.get("is_hard_catalyst") == "1")
    n_disagree = sum(1 for r in queue_rows if "high_disagreement" in r.get("review_reasons", ""))
    n_ts = sum(1 for r in queue_rows if "term_structure" in r.get("review_reasons", ""))
    n_cheap = sum(1 for r in queue_rows if "cheap_straddle" in r.get("review_reasons", ""))
    n_rich = sum(1 for r in queue_rows if "rich_straddle" in r.get("review_reasons", ""))
    n_skew = sum(1 for r in queue_rows if "extreme_skew" in r.get("review_reasons", ""))

    return {
        "schema_version": "options_review_queue.v2",
        "hard_only": hard_only,
        "summary": {
            "n_total": len(queue_rows),
            "n_soft_skipped": n_soft_skipped,
            "n_hard_catalyst": n_hard,
            "n_high_disagreement": n_disagree,
            "n_term_structure_flag": n_ts,
            "n_cheap_straddle": n_cheap,
            "n_rich_straddle": n_rich,
            "n_extreme_skew": n_skew,
        },
        "rows": queue_rows,
    }


def write_options_review_queue(
    queue: Dict[str, Any],
    snap_path: Path,
    as_of_date: str,
) -> None:
    """Write CSV, JSON, and Markdown queue artifacts."""
    rows = queue.get("rows", [])
    summary = queue.get("summary", {})

    # CSV
    csv_path = snap_path / "options_review_queue.csv"
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=QUEUE_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    # JSON
    json_path = snap_path / "options_review_queue.json"
    output = {**queue, "as_of_date": as_of_date}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
        f.write("\n")

    # Markdown
    hard_only = queue.get("hard_only", False)
    md_lines = [
        f"# Options Mispricing Review Queue — {as_of_date}",
        "",
        f"**Filter:** {'hard catalysts only' if hard_only else 'all triggers'}",
        "",
        "## Summary",
        "",
        f"- Total queued: {summary.get('n_total', 0)}",
        f"- Soft/PCD skipped: {summary.get('n_soft_skipped', 0)}",
        f"- Hard catalysts: {summary.get('n_hard_catalyst', 0)}",
        f"- High disagreement: {summary.get('n_high_disagreement', 0)}",
        f"- Term structure flags: {summary.get('n_term_structure_flag', 0)}",
        f"- Cheap straddle: {summary.get('n_cheap_straddle', 0)}",
        f"- Rich straddle: {summary.get('n_rich_straddle', 0)}",
        f"- Extreme skew: {summary.get('n_extreme_skew', 0)}",
        "",
    ]

    if rows:
        md_lines.append("## Top Review Names")
        md_lines.append("")
        md_lines.append("| Ticker | Priority | CatDays | Hard? | Disagree | TS Flag | RR_25d | Reasons |")
        md_lines.append("|--------|----------|---------|-------|----------|---------|--------|---------|")
        for r in rows[:25]:
            hard = "Y" if r.get("is_hard_catalyst") == "1" else ""
            disagree = r.get("market_model_disagreement", "")
            ts = r.get("ts_flag_type", "")
            rr = r.get("opt_rr_25d", "")
            if rr:
                try:
                    rr = f"{float(rr):.3f}"
                except (ValueError, TypeError):
                    pass
            reasons = r.get("review_reasons", "")
            md_lines.append(
                f"| {r['ticker']} | {r['review_priority_score']} | {r.get('catalyst_days', '')} "
                f"| {hard} | {disagree} | {ts} | {rr} | {reasons} |"
            )
        md_lines.append("")
    else:
        md_lines.append("No names queued.")
        md_lines.append("")

    md_path = snap_path / "options_review_queue.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
