#!/usr/bin/env python3
"""Grok classification layer for company press releases (Spec 044 Phase 2).

Takes raw PR records from fetch_company_press_releases.py and classifies
them into typed event records using xAI's structured outputs.

Usage:
    python tools/classify_press_releases.py --input data/press_releases/releases_2026-03-31.jsonl
    python tools/classify_press_releases.py --input data/press_releases/releases_2026-03-31.jsonl --dry-run
    python tools/classify_press_releases.py --input data/press_releases/releases_2026-03-31.jsonl --stdout-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "dem_grok_news_feed.v1"
OUTPUT_DIR = PROJECT_ROOT / "data" / "press_releases" / "classified"

# Try to import OpenAI client for xAI
try:
    from openai import OpenAI

    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


SYSTEM_PROMPT = """You are a point-in-time biotech event normalizer for the Wake Robin DEM/CRT pipeline.

Your job: classify a company press release into a structured event record.

Rules:
1. Separate event_outcome_guess from price_direction_guess. A CRL is a MISS even if the stock goes up.
2. Mark informational_only=true for non-catalyst updates: earnings schedules, conference appearances, enrollment updates with no data, generic business updates.
3. Tag exogenous events (M&A, unrelated corporate actions) that are not the tracked catalyst.
4. Be conservative with confidence — 0.5 if uncertain, 0.9+ only for definitive events with official sources.

Event categories: mna, clinical, regulatory, financing, leadership, safety, legal, competitor, sector, other
Severity: critical (definitive M&A/approval/CRL/pivotal topline), high (thesis-changing), medium (meaningful), low (minor)
Outcome: hit, miss, mixed, unclear, not_applicable
Price direction: up, down, flat, unclear, not_applicable

Output JSON only. No commentary."""

USER_PROMPT_TEMPLATE = """Classify this press release:

Ticker: {ticker}
Company: {company}
Headline: {headline}
Source URL: {source_url}
Published: {published_at}

Return a JSON object with these fields:
- event_category (string)
- event_subtype (string, e.g. "phase3_topline", "earnings", "conference_presentation")
- severity (string)
- materiality (string: high/medium/low)
- new_or_stale (string: new/follow_on/stale)
- informational_only (boolean)
- informational_reason (string, empty if not informational)
- event_outcome_guess (string)
- event_outcome_reason (string)
- price_direction_guess (string)
- price_direction_reason (string)
- exogenous_to_primary_catalyst (boolean)
- exogenous_reason (string)
- safety_signal_flag (boolean)
- financing_signal_flag (boolean)
- mna_signal_flag (boolean)
- thesis_change_flag (boolean)
- why_it_matters (string, 1-2 sentences)
- confidence (float, 0-1)
- needs_review (boolean)
"""


def _classify_with_grok(
    ticker: str,
    company: str,
    headline: str,
    source_url: str,
    published_at: str,
    client: Any,
    model: str,
) -> Dict[str, Any]:
    """Classify a single PR using xAI Grok."""
    user_prompt = USER_PROMPT_TEMPLATE.format(
        ticker=ticker,
        company=company,
        headline=headline,
        source_url=source_url,
        published_at=published_at,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=800,
        response_format={"type": "json_object"},
    )

    text = response.choices[0].message.content
    return json.loads(text)


def _classify_locally(headline: str) -> Dict[str, Any]:
    """Fast local classification using keyword rules (no API call).

    Used as fallback when XAI_API_KEY is not set or for dry-run mode.
    """
    hl = headline.lower()

    # Informational patterns
    informational_keywords = [
        "financial results",
        "quarterly report",
        "conference",
        "investor",
        "presentation",
        "schedules release",
        "participate in",
        "upcoming",
        "appoints",
        "board of directors",
    ]
    if any(kw in hl for kw in informational_keywords):
        return {
            "event_category": "other",
            "event_subtype": "corporate_update",
            "severity": "low",
            "materiality": "low",
            "new_or_stale": "new",
            "informational_only": True,
            "informational_reason": "Corporate/financial update",
            "event_outcome_guess": "not_applicable",
            "event_outcome_reason": "",
            "price_direction_guess": "not_applicable",
            "price_direction_reason": "",
            "exogenous_to_primary_catalyst": False,
            "exogenous_reason": "",
            "safety_signal_flag": False,
            "financing_signal_flag": False,
            "mna_signal_flag": False,
            "thesis_change_flag": False,
            "why_it_matters": "Informational corporate update",
            "confidence": 0.7,
            "needs_review": False,
        }

    # Clinical patterns
    clinical_keywords = [
        "phase 3",
        "phase 2",
        "phase 1",
        "topline",
        "primary endpoint",
        "readout",
        "clinical data",
        "trial results",
        "pivotal",
    ]
    if any(kw in hl for kw in clinical_keywords):
        is_positive = any(kw in hl for kw in ["positive", "met", "significant", "approved"])
        is_negative = any(kw in hl for kw in ["did not meet", "failed", "discontinued", "hold"])
        return {
            "event_category": "clinical",
            "event_subtype": "clinical_data",
            "severity": "high",
            "materiality": "high",
            "new_or_stale": "new",
            "informational_only": False,
            "informational_reason": "",
            "event_outcome_guess": "hit" if is_positive else "miss" if is_negative else "unclear",
            "event_outcome_reason": headline[:100],
            "price_direction_guess": "up" if is_positive else "down" if is_negative else "unclear",
            "price_direction_reason": "",
            "exogenous_to_primary_catalyst": False,
            "exogenous_reason": "",
            "safety_signal_flag": False,
            "financing_signal_flag": False,
            "mna_signal_flag": False,
            "thesis_change_flag": True,
            "why_it_matters": headline[:150],
            "confidence": 0.6,
            "needs_review": True,
        }

    # Regulatory patterns
    regulatory_keywords = [
        "fda",
        "approval",
        "nda",
        "bla",
        "pdufa",
        "breakthrough",
        "priority review",
        "complete response",
        "crl",
    ]
    if any(kw in hl for kw in regulatory_keywords):
        return {
            "event_category": "regulatory",
            "event_subtype": "regulatory_update",
            "severity": "high",
            "materiality": "high",
            "new_or_stale": "new",
            "informational_only": False,
            "informational_reason": "",
            "event_outcome_guess": "unclear",
            "event_outcome_reason": headline[:100],
            "price_direction_guess": "unclear",
            "price_direction_reason": "",
            "exogenous_to_primary_catalyst": False,
            "exogenous_reason": "",
            "safety_signal_flag": False,
            "financing_signal_flag": False,
            "mna_signal_flag": False,
            "thesis_change_flag": True,
            "why_it_matters": headline[:150],
            "confidence": 0.5,
            "needs_review": True,
        }

    # Default
    return {
        "event_category": "other",
        "event_subtype": "unclassified",
        "severity": "low",
        "materiality": "low",
        "new_or_stale": "new",
        "informational_only": False,
        "informational_reason": "",
        "event_outcome_guess": "unclear",
        "event_outcome_reason": "",
        "price_direction_guess": "unclear",
        "price_direction_reason": "",
        "exogenous_to_primary_catalyst": False,
        "exogenous_reason": "",
        "safety_signal_flag": False,
        "financing_signal_flag": False,
        "mna_signal_flag": False,
        "thesis_change_flag": False,
        "why_it_matters": headline[:150],
        "confidence": 0.3,
        "needs_review": True,
    }


def classify_releases(
    raw_records: List[Dict[str, Any]],
    use_grok: bool = False,
    model: str = "grok-4-1-fast",
) -> List[Dict[str, Any]]:
    """Classify a batch of raw PR records."""
    client = None
    if use_grok and HAS_OPENAI:
        api_key = os.getenv("XAI_API_KEY")
        if api_key:
            client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        else:
            logger.warning("XAI_API_KEY not set, falling back to local classification")

    classified = []
    for rec in raw_records:
        ticker = rec.get("ticker", "")
        headline = rec.get("headline", "")
        if not ticker or not headline:
            continue

        if client:
            try:
                result = _classify_with_grok(
                    ticker=ticker,
                    company=rec.get("company", ""),
                    headline=headline,
                    source_url=rec.get("source_url", ""),
                    published_at=rec.get("published_at_utc", ""),
                    client=client,
                    model=model,
                )
            except Exception as e:
                logger.warning("Grok classification failed for %s: %s, using local", ticker, e)
                result = _classify_locally(headline)
        else:
            result = _classify_locally(headline)

        # Build normalized event record
        event_id = str(uuid.uuid4())
        dedupe_raw = f"{ticker}|{result.get('event_category', '')}|{result.get('event_subtype', '')}|{rec.get('published_at_utc', '')}|{rec.get('source_url', '')}"
        dedupe_key = hashlib.sha256(dedupe_raw.encode()).hexdigest()[:16]

        normalized = {
            "event_id": event_id,
            "dedupe_key": dedupe_key,
            "ticker": ticker,
            "company": rec.get("company", ""),
            "headline": headline,
            "source_url": rec.get("source_url", ""),
            "source_type": rec.get("source_type", "company_ir"),
            "published_at_utc": rec.get("published_at_utc", ""),
            "classified_at_utc": datetime.now(timezone.utc).isoformat(),
            "classification_method": "grok" if client else "local_keywords",
            **result,
        }
        classified.append(normalized)

    return classified


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="PR classification (Spec 044 Phase 2)")
    parser.add_argument("--input", type=Path, required=True, help="Path to raw releases JSONL")
    parser.add_argument("--use-grok", action="store_true", help="Use xAI Grok API (requires XAI_API_KEY)")
    parser.add_argument("--model", default="grok-4-1-fast")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stdout-only", action="store_true")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input file not found: {args.input}")
        return 1

    # Load raw records
    records = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"Loaded {len(records)} raw PR records")

    # Classify
    classified = classify_releases(records, use_grok=args.use_grok, model=args.model)
    print(f"Classified {len(classified)} records")

    # Summary
    from collections import Counter

    cats = Counter(r.get("event_category", "?") for r in classified)
    info = sum(1 for r in classified if r.get("informational_only"))
    review = sum(1 for r in classified if r.get("needs_review"))
    print(f"\nCategories: {dict(cats)}")
    print(f"Informational: {info}/{len(classified)}")
    print(f"Needs review: {review}/{len(classified)}")

    if args.stdout_only or args.dry_run:
        for r in classified:
            print(json.dumps(r, indent=2, default=str))
        return 0

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = args.input.stem.replace("releases_", "classified_")
    out_path = OUTPUT_DIR / f"{stem}.jsonl"
    with open(out_path, "w") as f:
        for r in classified:
            f.write(json.dumps(r, default=str) + "\n")
    print(f"Wrote {len(classified)} classified records to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
