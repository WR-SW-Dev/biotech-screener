#!/usr/bin/env python3
"""Deduplicate company press releases (Spec 044).

Takes raw JSONL from Herald and produces deduped output with metrics.

Dedupe strategy:
1. Exact: ticker + normalized headline + published_date
2. Fuzzy: ticker + date + headline similarity >= 0.85
3. Cross-source: same story from IR + GlobeNewswire collapsed to one record

Usage:
    python tools/dedupe_press_releases.py --input data/press_releases/releases_2026-03-31.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "press_releases" / "deduped"


def normalize_headline(headline: str) -> str:
    """Normalize headline for dedup comparison."""
    h = headline.lower().strip()
    # Remove HTML entities
    h = re.sub(r"&#\w+;", " ", h)
    h = re.sub(r"&\w+;", " ", h)
    # Remove punctuation except apostrophes
    h = re.sub(r"[^\w\s']", " ", h)
    # Collapse whitespace
    h = re.sub(r"\s+", " ", h).strip()
    return h


def headline_similarity(a: str, b: str) -> float:
    """Simple word-overlap Jaccard similarity."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def dedupe_key(ticker: str, headline: str, date: str) -> str:
    """Exact dedupe key."""
    norm = normalize_headline(headline)
    raw = f"{ticker.upper()}|{norm}|{date[:10]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def dedupe_releases(records: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Deduplicate press releases.

    Returns (deduped_records, metrics).
    """
    # Phase 1: exact dedup by normalized headline + ticker + date
    seen_keys: Dict[str, Dict[str, Any]] = {}
    exact_dupes = 0

    for rec in records:
        ticker = rec.get("ticker", "")
        headline = rec.get("headline", "")
        date = rec.get("published_at_utc", "")
        key = dedupe_key(ticker, headline, date)

        if key in seen_keys:
            exact_dupes += 1
            # Keep the one with more info (prefer company_ir over globenewswire)
            existing = seen_keys[key]
            if rec.get("source_type") == "company_ir" and existing.get("source_type") != "company_ir":
                rec["_dedup_sources"] = [existing.get("source_type", "?"), rec.get("source_type", "?")]
                seen_keys[key] = rec
            else:
                existing.setdefault("_dedup_sources", [existing.get("source_type", "?")])
                existing["_dedup_sources"].append(rec.get("source_type", "?"))
        else:
            seen_keys[key] = rec

    after_exact = list(seen_keys.values())

    # Phase 2: fuzzy dedup within same ticker + date
    fuzzy_dupes = 0
    by_ticker_date: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for rec in after_exact:
        ticker = rec.get("ticker", "").upper()
        date = rec.get("published_at_utc", "")[:10]
        by_ticker_date[(ticker, date)].append(rec)

    final = []
    for (ticker, date), group in by_ticker_date.items():
        if len(group) <= 1:
            final.extend(group)
            continue

        # Cluster by headline similarity
        used = set()
        for i, rec_a in enumerate(group):
            if i in used:
                continue
            cluster = [rec_a]
            norm_a = normalize_headline(rec_a.get("headline", ""))
            for j, rec_b in enumerate(group):
                if j <= i or j in used:
                    continue
                norm_b = normalize_headline(rec_b.get("headline", ""))
                if headline_similarity(norm_a, norm_b) >= 0.85:
                    cluster.append(rec_b)
                    used.add(j)
                    fuzzy_dupes += 1

            # Keep the best record from the cluster
            # Prefer company_ir, then longest headline
            best = max(
                cluster,
                key=lambda r: (r.get("source_type") == "company_ir", len(r.get("headline", ""))),
            )
            if len(cluster) > 1:
                best["_dedup_cluster_size"] = len(cluster)
                best["_dedup_sources"] = list(set(r.get("source_type", "?") for r in cluster))
            final.append(best)
            used.add(group.index(best))

    # Add dedupe metadata
    for rec in final:
        rec["dedupe_key"] = dedupe_key(rec.get("ticker", ""), rec.get("headline", ""), rec.get("published_at_utc", ""))

    metrics = {
        "schema": "herald_dedupe.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_count": len(records),
        "after_exact_dedup": len(after_exact),
        "exact_dupes_removed": exact_dupes,
        "after_fuzzy_dedup": len(final),
        "fuzzy_dupes_removed": fuzzy_dupes,
        "total_dupes_removed": exact_dupes + fuzzy_dupes,
        "dedupe_rate": round((exact_dupes + fuzzy_dupes) / max(len(records), 1) * 100, 1),
        "unique_tickers": len(set(r.get("ticker", "") for r in final)),
        "multi_source_confirmed": sum(1 for r in final if len(r.get("_dedup_sources", [])) > 1),
    }

    return final, metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Deduplicate Herald press releases")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input not found: {args.input}")
        return 1

    records = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"Loaded {len(records)} raw records")

    deduped, metrics = dedupe_releases(records)

    print("\nDedupe results:")
    print(f"  Input:          {metrics['input_count']}")
    print(f"  Exact dupes:    {metrics['exact_dupes_removed']}")
    print(f"  Fuzzy dupes:    {metrics['fuzzy_dupes_removed']}")
    print(f"  Output:         {metrics['after_fuzzy_dedup']}")
    print(f"  Dedupe rate:    {metrics['dedupe_rate']}%")
    print(f"  Multi-source:   {metrics['multi_source_confirmed']}")
    print(f"  Unique tickers: {metrics['unique_tickers']}")

    if args.dry_run:
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = args.input.stem.replace("releases_", "deduped_")
    out_path = OUTPUT_DIR / f"{stem}.jsonl"
    with open(out_path, "w") as f:
        for rec in deduped:
            f.write(json.dumps(rec, default=str) + "\n")

    metrics_path = OUTPUT_DIR / f"{stem}_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
        f.write("\n")

    print(f"\nWrote {len(deduped)} deduped records to {out_path.name}")
    print(f"Metrics → {metrics_path.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
