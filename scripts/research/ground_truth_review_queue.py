#!/usr/bin/env python3
"""Generate a prioritized review queue for ground-truth labeling.

Identifies records that need human review: low auto-label confidence,
Herald/auto-label disagreements, and outlier price reactions.

Usage:
    python3 scripts/research/ground_truth_review_queue.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

GT_DIR = PROJECT_ROOT / "data" / "ground_truth"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "ground_truth_review"


def load_all_gt_records() -> list[dict]:
    records = []
    for f in sorted(GT_DIR.glob("batch_*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    rec["_source_file"] = f.name
                    records.append(rec)
    return records


def build_review_queue(records: list[dict]) -> dict:
    queue = []

    for rec in records:
        source = rec.get("gt_label_source", "unlabeled")
        confidence = rec.get("gt_auto_confidence", 0)
        herald_cat = rec.get("event_category", "other")
        gt_cat = rec.get("gt_event_category", "")
        ticker = rec.get("ticker", "?")
        headline = rec.get("headline", "")[:80]
        ret_pct = rec.get("gt_return_pct")

        urgency = 0
        reasons = []

        # Still unlabeled
        if source == "unlabeled" or not source:
            urgency += 5
            reasons.append("UNLABELED")

        # Low auto-label confidence
        if source == "price_reaction_low_conf":
            urgency += 4
            reasons.append("LOW_CONF_AUTO_LABEL")

        # Herald disagrees with auto-label
        if gt_cat and herald_cat and gt_cat != herald_cat:
            urgency += 3
            reasons.append(f"HERALD_DISAGREE({herald_cat}→{gt_cat})")

        # Informational but large move (false informational)
        if rec.get("informational_only") and ret_pct is not None and abs(ret_pct) > 10:
            urgency += 3
            reasons.append(f"FALSE_INFORMATIONAL(ret={ret_pct:+.1f}%)")

        # Material but no move
        if not rec.get("informational_only") and ret_pct is not None and abs(ret_pct) < 2:
            urgency += 2
            reasons.append(f"MATERIAL_NO_MOVE(ret={ret_pct:+.1f}%)")

        if urgency > 0:
            queue.append(
                {
                    "ticker": ticker,
                    "headline": headline,
                    "herald_category": herald_cat,
                    "gt_category": gt_cat or "—",
                    "label_source": source,
                    "confidence": round(confidence, 2) if confidence else None,
                    "return_pct": ret_pct,
                    "urgency": urgency,
                    "reasons": reasons,
                    "pub_date": rec.get("published_at_utc", "")[:10],
                }
            )

    queue.sort(key=lambda x: -x["urgency"])

    # Stats
    n_total = len(records)
    n_labeled = sum(1 for r in records if r.get("gt_label_source") not in ("unlabeled", "", None))
    n_review = len(queue)

    return {
        "n_total_records": n_total,
        "n_labeled": n_labeled,
        "n_needing_review": n_review,
        "target_labeled": 300,
        "gap_to_target": max(0, 300 - n_labeled),
        "queue": queue,
    }


def render_markdown(result: dict) -> str:
    lines = [
        "# Ground Truth Review Queue",
        "",
        f"**Total records:** {result['n_total_records']}  ",
        f"**Labeled:** {result['n_labeled']}  ",
        f"**Needing review:** {result['n_needing_review']}  ",
        f"**Gap to 300 target:** {result['gap_to_target']}",
        "",
        "## Priority Queue",
        "",
        "| Urgency | Ticker | Date | Herald | GT | Reasons | Return |",
        "|---------|--------|------|--------|----|---------|--------|",
    ]
    for item in result["queue"][:50]:
        reasons = ", ".join(item["reasons"])
        ret = f"{item['return_pct']:+.1f}%" if item["return_pct"] is not None else "—"
        lines.append(
            f"| {item['urgency']} | {item['ticker']} | {item['pub_date']} "
            f"| {item['herald_category']} | {item['gt_category']} "
            f"| {reasons} | {ret} |"
        )
    return "\n".join(lines)


def main():
    records = load_all_gt_records()
    if not records:
        print("No ground truth records found")
        return

    result = build_review_queue(records)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "review_queue.json"
    md_path = OUTPUT_DIR / "review_queue.md"

    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    with open(md_path, "w") as f:
        f.write(render_markdown(result))

    print(f"Total: {result['n_total_records']}, Labeled: {result['n_labeled']}, Review: {result['n_needing_review']}")
    print(f"Gap to 300 target: {result['gap_to_target']}")
    print("Top 5 review items:")
    for item in result["queue"][:5]:
        print(f"  [{item['urgency']}] {item['ticker']} {item['pub_date']}: {', '.join(item['reasons'])}")
    print(f"\nSaved: {json_path}, {md_path}")


if __name__ == "__main__":
    main()
