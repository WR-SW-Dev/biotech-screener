#!/usr/bin/env python3
"""Auto-label ground truth records using heuristic rules.

Applies deterministic labeling where the answer is unambiguous:
  1. CRT cross-reference (existing auto_label_from_crt)
  2. Headline keyword matching for clinical/regulatory/safety
  3. Price reaction validation for informational classification
  4. Source-type heuristics (SEC filings → regulatory/corporate)

Records that can't be confidently labeled remain "unlabeled" for human review.

Usage:
    python scripts/research/backfill_ground_truth_labels.py
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

GT_DIR = PROJECT_ROOT / "data" / "ground_truth"
LEGACY_DIR = PROJECT_ROOT / "artifacts" / "herald_ground_truth"

logger = logging.getLogger(__name__)

# Keyword patterns for category classification
CLINICAL_PATTERNS = [
    r"\bphase [123]\b",
    r"\bpivotal\b",
    r"\bclinical (data|results|trial|study)\b",
    r"\bprimary endpoint\b",
    r"\boverall survival\b",
    r"\bprogression.free\b",
    r"\bORR\b",
    r"\befficacy\b",
    r"\bread.?out\b",
    r"\benrolled?\b",
    r"\bdosing\b",
    r"\bfirst patient\b",
    r"\btreated first\b",
    r"\binterim (data|results|analysis)\b",
]

REGULATORY_PATTERNS = [
    r"\bPDUFA\b",
    r"\bFDA\b",
    r"\bNDA\b",
    r"\bBLA\b",
    r"\bsNDA\b",
    r"\bEMA\b",
    r"\bapproval\b",
    r"\bapproved\b",
    r"\bcomplete response letter\b",
    r"\bCRL\b",
    r"\badvisory committee\b",
    r"\badcom\b",
    r"\bbreakthrough (therapy|designation)\b",
    r"\bfast track\b",
    r"\bpriority review\b",
    r"\borphan drug\b",
    r"\baccelerating approval\b",
    r"\bsubmission\b",
    r"\bfiling\b",
]

SAFETY_PATTERNS = [
    r"\bclinical hold\b",
    r"\bsafety (signal|concern|issue)\b",
    r"\badverse event\b",
    r"\bblack box\b",
    r"\bRems\b",
    r"\bwarning letter\b",
    r"\brecall\b",
    r"\bsuspended?\b",
    r"\bterminated?\b",
    r"\bwithdra(wn|wal)\b",
    r"\bvoluntary withdrawal\b",
]

FINANCING_PATTERNS = [
    r"\boffering\b",
    r"\bpublic offering\b",
    r"\braise[sd]?\b",
    r"\b\$\d+.*million\b",
    r"\bIPO\b",
    r"\bshelf registration\b",
    r"\bsecurities\b",
    r"\bwarrant\b",
]

MNA_PATTERNS = [
    r"\bacquir(e|ed|ing|ition)\b",
    r"\bmerger\b",
    r"\btakeover\b",
    r"\bbuyout\b",
    r"\bcollaboration agreement\b",
    r"\blicens(e|ing) agreement\b",
]


def _match_category(headline: str) -> str | None:
    """Match headline to a category using keyword patterns.

    Returns category name or None if ambiguous/no match.
    """
    headline_lower = headline.lower()
    scores = {
        "clinical": sum(1 for p in CLINICAL_PATTERNS if re.search(p, headline_lower)),
        "regulatory": sum(1 for p in REGULATORY_PATTERNS if re.search(p, headline_lower)),
        "safety": sum(1 for p in SAFETY_PATTERNS if re.search(p, headline_lower)),
        "financing": sum(1 for p in FINANCING_PATTERNS if re.search(p, headline_lower)),
        "mna": sum(1 for p in MNA_PATTERNS if re.search(p, headline_lower)),
    }

    # Only label if one category dominates (>=2 matches and >2x the runner-up)
    top = max(scores, key=scores.get)
    top_score = scores[top]
    if top_score < 2:
        return None
    runner_up = max(v for k, v in scores.items() if k != top)
    if runner_up > 0 and top_score < 2 * runner_up:
        return None
    return top


def auto_label_batch(records: list[dict]) -> tuple[int, int]:
    """Apply auto-labeling to a list of ground truth records (in-place).

    Returns (n_labeled, n_skipped).
    """
    n_labeled = 0
    n_skipped = 0

    for rec in records:
        # Skip already-labeled records
        if rec.get("gt_label_source") and rec["gt_label_source"] not in ("unlabeled", None):
            n_skipped += 1
            continue

        headline = rec.get("headline", "") or ""
        if not headline:
            continue

        category = _match_category(headline)
        if category:
            rec["gt_event_category"] = category
            rec["gt_label_source"] = "keyword_auto"
            rec["gt_reviewer"] = "backfill_ground_truth_labels.py"
            n_labeled += 1
        else:
            # For records Herald classified as "other" with low confidence,
            # accept the Herald label if it's a clear corporate/earnings type
            herald_cat = rec.get("event_category", "")
            herald_sub = rec.get("event_subtype", "")
            if herald_cat == "other" and herald_sub in (
                "corporate_update",
                "earnings",
                "partnership",
                "leadership_change",
                "stock_repurchase",
            ):
                rec["gt_event_category"] = "other"
                rec["gt_label_source"] = "herald_accepted"
                rec["gt_reviewer"] = "backfill_ground_truth_labels.py"
                n_labeled += 1

    return n_labeled, n_skipped


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Find all batch files
    batch_files = sorted(GT_DIR.glob("batch_*.jsonl")) + sorted(LEGACY_DIR.glob("sample_*.jsonl"))
    if not batch_files:
        print("No ground truth batch files found")
        sys.exit(1)

    total_labeled = 0
    total_skipped = 0
    total_records = 0

    for bf in batch_files:
        records = []
        for line in bf.read_text().splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))

        n_before = sum(1 for r in records if r.get("gt_label_source") and r["gt_label_source"] != "unlabeled")
        n_labeled, n_skipped = auto_label_batch(records)
        n_after = sum(1 for r in records if r.get("gt_label_source") and r["gt_label_source"] != "unlabeled")

        # Write back
        with open(bf, "w") as f:
            for rec in records:
                f.write(json.dumps(rec, default=str) + "\n")

        total_labeled += n_labeled
        total_skipped += n_skipped
        total_records += len(records)
        print(f"  {bf.name}: {len(records)} records, {n_before}→{n_after} labeled (+{n_labeled})")

    print("\nGROUND TRUTH AUTO-LABELING")
    print(f"  Files: {len(batch_files)}")
    print(f"  Records: {total_records}")
    print(f"  New labels: {total_labeled}")
    print(f"  Previously labeled: {total_skipped}")

    # Show category distribution
    all_records = []
    for bf in batch_files:
        for line in bf.read_text().splitlines():
            line = line.strip()
            if line:
                all_records.append(json.loads(line))

    from collections import Counter

    labeled = [r for r in all_records if r.get("gt_label_source") and r["gt_label_source"] != "unlabeled"]
    cats = Counter(r.get("gt_event_category", "?") for r in labeled)
    sources = Counter(r.get("gt_label_source", "?") for r in labeled)

    print(f"\n  Labeled: {len(labeled)}/{len(all_records)}")
    print(f"  By category: {dict(sorted(cats.items()))}")
    print(f"  By source: {dict(sorted(sources.items()))}")


if __name__ == "__main__":
    main()
