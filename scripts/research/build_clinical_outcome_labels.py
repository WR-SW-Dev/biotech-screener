#!/usr/bin/env python3
"""Build clinical outcome labels from SEC 8-K filing text.

Scans 8-K cache for resolved clinical outcome language to produce
binary success/failure labels for PoS model calibration.

Usage:
    python scripts/research/build_clinical_outcome_labels.py
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCHEMA = "clinical_outcome_labels.v1"

# Positive outcome patterns (met primary endpoint)
POSITIVE_PATTERNS = [
    re.compile(r"(?i)met\s+(?:its\s+|the\s+)?primary\s+endpoint"),
    re.compile(r"(?i)achieved\s+(?:its\s+|the\s+)?primary\s+endpoint"),
    re.compile(r"(?i)statistically\s+significant\s+(?:improvement|reduction|benefit|difference)"),
    re.compile(r"(?i)positive\s+(?:top-?line|topline)\s+(?:results?|data)"),
    re.compile(r"(?i)met\s+(?:all\s+)?(?:co-?)?primary\s+(?:and\s+key\s+secondary\s+)?endpoint"),
    re.compile(r"(?i)achieved\s+statistical\s+significance"),
    re.compile(r"(?i)demonstrated\s+(?:statistically\s+)?significant\s+(?:improvement|efficacy|benefit)"),
    re.compile(r"(?i)(?:p-value|p\s*=\s*)\s*(?:<\s*)?0\.0[0-4]\d*"),  # p < 0.05
    re.compile(r"(?i)superiority\s+(?:was\s+)?(?:achieved|demonstrated|met)"),
]

# Negative outcome patterns (failed primary endpoint)
NEGATIVE_PATTERNS = [
    re.compile(r"(?i)(?:did\s+not|failed\s+to)\s+meet\s+(?:its\s+|the\s+)?primary\s+endpoint"),
    re.compile(r"(?i)(?:did\s+not|failed\s+to)\s+achieve\s+(?:statistical\s+)?significance"),
    re.compile(r"(?i)(?:did\s+not|failed\s+to)\s+demonstrate\s+(?:statistically\s+)?significant"),
    re.compile(r"(?i)not\s+(?:statistically\s+)?significant"),
    re.compile(r"(?i)negative\s+(?:top-?line|topline)\s+(?:results?|data)"),
    re.compile(
        r"(?i)discontinued\s+(?:development|the\s+(?:study|trial|program))\s+(?:due\s+to|for|based\s+on)\s+(?:futility|lack\s+of\s+efficacy)"
    ),
    re.compile(r"(?i)terminated\s+(?:the\s+)?(?:study|trial)\s+for\s+futility"),
    re.compile(r"(?i)(?:p-value|p\s*=\s*)\s*(?:0\.[1-9]|[1-9])"),  # p >= 0.1
    re.compile(r"(?i)complete\s+response\s+letter"),
]

# Safety termination patterns
SAFETY_PATTERNS = [
    re.compile(r"(?i)discontinued\s+(?:due\s+to|for)\s+safety"),
    re.compile(r"(?i)clinical\s+hold"),
    re.compile(r"(?i)terminated\s+(?:due\s+to|for)\s+(?:safety|adverse)"),
    re.compile(r"(?i)serious\s+adverse\s+event"),
]

# Business termination (exclude from calibration)
BUSINESS_PATTERNS = [
    re.compile(r"(?i)discontinued\s+(?:due\s+to|for)\s+(?:strategic|business|commercial|financial)"),
    re.compile(r"(?i)reprioritiz"),
]


def load_universe_tickers(data_dir: Path) -> set:
    path = data_dir / "universe.json"
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    return {(e.get("ticker", e) if isinstance(e, dict) else e).upper() for e in data}


def classify_outcome(event_name: str) -> Dict[str, Any]:
    """Classify a clinical event's outcome from 8-K text."""
    text = event_name

    # Check positive
    for pat in POSITIVE_PATTERNS:
        if pat.search(text):
            return {"label": "positive", "confidence": "HIGH", "match": pat.pattern[:60]}

    # Check negative
    for pat in NEGATIVE_PATTERNS:
        if pat.search(text):
            return {"label": "negative", "confidence": "HIGH", "match": pat.pattern[:60]}

    # Check safety
    for pat in SAFETY_PATTERNS:
        if pat.search(text):
            return {"label": "negative_safety", "confidence": "MED", "match": pat.pattern[:60]}

    # Check business
    for pat in BUSINESS_PATTERNS:
        if pat.search(text):
            return {"label": "business_discontinuation", "confidence": "MED", "match": pat.pattern[:60]}

    return {"label": "unknown", "confidence": "LOW", "match": ""}


def scan_8k_cache(cache_dir: Path, universe: set) -> List[Dict[str, Any]]:
    """Scan all 8-K cache files for outcome language."""
    labels = []
    seen = set()

    for cache_file in sorted(cache_dir.glob("8k_catalysts_*.json")):
        try:
            events = json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        for ev in events:
            ticker = (ev.get("ticker") or "").upper()
            if not ticker or ticker not in universe:
                continue

            event_name = ev.get("event_name", "")
            event_date = ev.get("event_date", "")
            filing_date = ev.get("disclosed_at") or event_date

            outcome = classify_outcome(event_name)
            if outcome["label"] == "unknown":
                continue

            # Dedup
            key = (ticker, filing_date[:10] if filing_date else "", outcome["label"])
            if key in seen:
                continue
            seen.add(key)

            labels.append(
                {
                    "ticker": ticker,
                    "event_date": event_date,
                    "filing_date": filing_date[:10] if filing_date else "",
                    "event_type": ev.get("event_type", ""),
                    "outcome_label": outcome["label"],
                    "outcome_confidence": outcome["confidence"],
                    "match_pattern": outcome["match"],
                    "event_text": event_name[:200],
                    "source": "SEC_8K",
                    "source_file": cache_file.name,
                }
            )

    return labels


def main() -> int:
    cache_dir = PROJECT_ROOT / "cache" / "sec" / "8k_catalysts"
    data_dir = PROJECT_ROOT / "production_data"
    output_dir = PROJECT_ROOT / "data" / "clinical"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading universe ...")
    universe = load_universe_tickers(data_dir)

    logger.info("Scanning 8-K cache for outcome language ...")
    labels = scan_8k_cache(cache_dir, universe)
    logger.info("Found %d outcome labels", len(labels))

    if not labels:
        logger.warning("No outcome labels found")
        return 1

    # Stats
    from collections import Counter

    by_label = Counter(rec["outcome_label"] for rec in labels)
    by_conf = Counter(rec["outcome_confidence"] for rec in labels)

    logger.info("  By label: %s", dict(by_label))
    logger.info("  By confidence: %s", dict(by_conf))

    # Binary mapping for calibration
    binary_map = {
        "positive": 1,
        "negative": 0,
        "negative_safety": 0,
    }
    calibration_labels = [rec for rec in labels if rec["outcome_label"] in binary_map]
    n_success = sum(1 for rec in calibration_labels if binary_map[rec["outcome_label"]] == 1)
    n_failure = sum(1 for rec in calibration_labels if binary_map[rec["outcome_label"]] == 0)
    logger.info("  Calibration-eligible: %d (success=%d, failure=%d)", len(calibration_labels), n_success, n_failure)

    # Write
    output = {
        "schema": SCHEMA,
        "built_as_of": date.today().isoformat(),
        "n_labels": len(labels),
        "n_calibration_eligible": len(calibration_labels),
        "by_label": dict(by_label),
        "by_confidence": dict(by_conf),
        "labels": labels,
    }
    out_path = output_dir / "clinical_outcome_labels_8k.json"
    out_path.write_text(json.dumps(output, indent=2) + "\n")
    logger.info("Output → %s", out_path)

    # Show examples
    for rec in sorted(labels, key=lambda x: x["filing_date"])[:10]:
        logger.info(
            "  %s %s %s: %s — %s",
            rec["ticker"],
            rec["filing_date"],
            rec["outcome_label"],
            rec["match_pattern"][:40],
            rec["event_text"][:60],
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
