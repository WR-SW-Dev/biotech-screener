#!/usr/bin/env python3
"""Expand AACT sponsor alias map by fuzzy-matching universe tickers to AACT sponsors.

Reads the AACT sponsors.txt pipe-delimited file and matches against company names
in universe.json. Outputs candidates with confidence scores for human review.

Usage:
    python tools/expand_aact_sponsor_map.py
    python tools/expand_aact_sponsor_map.py --auto-merge --min-confidence 0.90
    python tools/expand_aact_sponsor_map.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROD_DATA = REPO_ROOT / "production_data"
AACT_DOWNLOADS = REPO_ROOT / "data" / "aact" / "downloads"
SPONSOR_MAP_PATH = PROD_DATA / "sponsor_alias_map.json"
UNIVERSE_PATH = PROD_DATA / "universe.json"
OUTPUT_PATH = REPO_ROOT / "output" / "pit" / "aact_sponsor_expansion_candidates.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("expand_aact_sponsor_map")

# Noise words to strip for matching
NOISE = {
    "inc",
    "inc.",
    "corp",
    "corp.",
    "corporation",
    "co",
    "co.",
    "ltd",
    "ltd.",
    "limited",
    "llc",
    "lp",
    "plc",
    "sa",
    "se",
    "nv",
    "bv",
    "therapeutics",
    "pharmaceuticals",
    "pharmaceutical",
    "biosciences",
    "biopharmaceuticals",
    "biopharma",
    "biotech",
    "biotechnology",
    "sciences",
    "holdings",
    "group",
    "the",
    "of",
    "and",
    "&",
}


def normalize(name: str) -> str:
    """Normalize a company name for matching."""
    s = name.lower().strip()
    s = re.sub(r"[,.()\[\]\"']", " ", s)
    tokens = s.split()
    tokens = [t for t in tokens if t not in NOISE]
    return " ".join(tokens)


def token_set(name: str) -> set[str]:
    return set(normalize(name).split())


def token_overlap_score(a: str, b: str) -> float:
    """Jaccard-like token overlap, boosted for longer matches."""
    ta = token_set(a)
    tb = token_set(b)
    if not ta or not tb:
        return 0.0
    overlap = ta & tb
    if not overlap:
        return 0.0
    # Jaccard
    jaccard = len(overlap) / len(ta | tb)
    # Boost if one is a subset of the other
    subset_bonus = 0.0
    if ta <= tb or tb <= ta:
        subset_bonus = 0.15
    # Boost for longer overlap (more tokens matched = more confident)
    length_bonus = min(0.10, 0.03 * len(overlap))
    return min(1.0, jaccard + subset_bonus + length_bonus)


def starts_with_match(norm_a: str, norm_b: str) -> bool:
    """Check if one normalized name starts with the other."""
    return norm_a.startswith(norm_b) or norm_b.startswith(norm_a)


def find_latest_extract() -> Path | None:
    """Find the most recent AACT extracted directory."""
    dirs = sorted(AACT_DOWNLOADS.glob("extracted_*"))
    return dirs[-1] if dirs else None


def load_aact_sponsors(extract_dir: Path) -> dict[str, set[str]]:
    """Load unique lead sponsor names from AACT sponsors.txt.

    Returns {normalized_name: {original_name, ...}} for lead sponsors only.
    """
    sponsors_path = extract_dir / "sponsors.txt"
    if not sponsors_path.exists():
        log.error("sponsors.txt not found in %s", extract_dir)
        return {}

    sponsor_names: dict[str, set[str]] = defaultdict(set)
    with open(sponsors_path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            if row.get("lead_or_collaborator") != "lead":
                continue
            name = (row.get("name") or "").strip()
            if not name or len(name) < 3:
                continue
            norm = normalize(name)
            if norm:
                sponsor_names[norm].add(name)

    return sponsor_names


def load_universe() -> list[dict]:
    with open(UNIVERSE_PATH) as f:
        return json.load(f)


def load_existing_map() -> dict[str, str]:
    if SPONSOR_MAP_PATH.exists():
        with open(SPONSOR_MAP_PATH) as f:
            return json.load(f)
    return {}


def find_matches(
    universe: list[dict],
    sponsor_names: dict[str, set[str]],
    existing_map: dict[str, str],
) -> list[dict]:
    """Find candidate sponsor matches for unmapped tickers."""
    existing_tickers = set(existing_map.values())
    candidates = []

    for entry in universe:
        ticker = entry.get("ticker", "")
        if not ticker or ticker in existing_tickers:
            continue

        company_name = entry.get("name", "")
        if not company_name or company_name == ticker:
            continue

        norm_company = normalize(company_name)
        if not norm_company:
            continue

        best_score = 0.0
        best_sponsor = ""
        best_originals: set[str] = set()

        for norm_sponsor, originals in sponsor_names.items():
            score = token_overlap_score(company_name, next(iter(originals)))

            # Bonus for starts-with match
            if starts_with_match(norm_company, norm_sponsor):
                score = max(score, 0.85)

            # Exact normalized match
            if norm_company == norm_sponsor:
                score = 1.0

            if score > best_score:
                best_score = score
                best_sponsor = norm_sponsor
                best_originals = originals

        if best_score >= 0.40:
            candidates.append(
                {
                    "ticker": ticker,
                    "company_name": company_name,
                    "matched_sponsor": sorted(best_originals)[0],
                    "all_sponsor_variants": sorted(best_originals),
                    "confidence": round(best_score, 3),
                    "normalized_company": norm_company,
                    "normalized_sponsor": best_sponsor,
                }
            )

    candidates.sort(key=lambda c: -c["confidence"])
    return candidates


def main():
    parser = argparse.ArgumentParser(description="Expand AACT sponsor alias map")
    parser.add_argument("--dry-run", action="store_true", help="Show candidates without writing")
    parser.add_argument(
        "--auto-merge",
        action="store_true",
        help="Automatically merge high-confidence matches into sponsor_alias_map.json",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.85,
        help="Minimum confidence for auto-merge (default: 0.85)",
    )
    args = parser.parse_args()

    # Find latest AACT extract
    extract_dir = find_latest_extract()
    if not extract_dir:
        log.error("No AACT extracted data found in %s", AACT_DOWNLOADS)
        return

    log.info("Using AACT extract: %s", extract_dir.name)

    # Load data
    log.info("Loading AACT sponsors...")
    sponsor_names = load_aact_sponsors(extract_dir)
    log.info("  %d unique normalized lead sponsor names", len(sponsor_names))

    universe = load_universe()
    existing_map = load_existing_map()
    existing_tickers = set(existing_map.values())
    log.info(
        "Universe: %d tickers, existing map: %d entries (%d tickers)",
        len(universe),
        len(existing_map),
        len(existing_tickers),
    )

    # Find matches
    candidates = find_matches(universe, sponsor_names, existing_map)

    # Partition by confidence
    high = [c for c in candidates if c["confidence"] >= 0.85]
    medium = [c for c in candidates if 0.60 <= c["confidence"] < 0.85]
    low = [c for c in candidates if c["confidence"] < 0.60]

    print(f"\n{'='*70}")
    print("AACT SPONSOR MAP EXPANSION CANDIDATES")
    print(f"{'='*70}")
    print(f"High confidence (>= 0.85):  {len(high)}")
    print(f"Medium confidence (0.60-0.85): {len(medium)}")
    print(f"Low confidence (< 0.60):    {len(low)}")
    print(f"Total unmapped tickers:     {len(universe) - len(existing_tickers & {e['ticker'] for e in universe})}")

    if high:
        print("\n--- HIGH CONFIDENCE (auto-mergeable) ---")
        for c in high:
            print(f"  {c['ticker']:6s} ({c['confidence']:.2f}) {c['company_name']}")
            print(f"         → {c['matched_sponsor']}")

    if medium:
        print("\n--- MEDIUM CONFIDENCE (review needed) ---")
        for c in medium:
            print(f"  {c['ticker']:6s} ({c['confidence']:.2f}) {c['company_name']}")
            print(f"         → {c['matched_sponsor']}")

    if low:
        print("\n--- LOW CONFIDENCE (likely wrong) ---")
        for c in low[:10]:
            print(f"  {c['ticker']:6s} ({c['confidence']:.2f}) {c['company_name']}")
            print(f"         → {c['matched_sponsor']}")
        if len(low) > 10:
            print(f"  ... and {len(low) - 10} more")

    # Save candidates
    if not args.dry_run:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(
                {
                    "high_confidence": high,
                    "medium_confidence": medium,
                    "low_confidence": low,
                    "summary": {
                        "total_candidates": len(candidates),
                        "high": len(high),
                        "medium": len(medium),
                        "low": len(low),
                    },
                },
                f,
                indent=2,
            )
        print(f"\nCandidates saved: {OUTPUT_PATH}")

    # Auto-merge high confidence
    if args.auto_merge and high:
        merged = 0
        for c in high:
            if c["confidence"] >= args.min_confidence:
                for sponsor_name in c["all_sponsor_variants"]:
                    if sponsor_name not in existing_map:
                        existing_map[sponsor_name] = c["ticker"]
                        merged += 1

        if merged > 0 and not args.dry_run:
            # Sort map for readability
            sorted_map = dict(sorted(existing_map.items()))
            with open(SPONSOR_MAP_PATH, "w") as f:
                json.dump(sorted_map, f, indent=2)
            print(f"\nAuto-merged {merged} sponsor aliases for {len(high)} tickers")
            print(f"Updated: {SPONSOR_MAP_PATH}")
            print(f"New map size: {len(sorted_map)} entries → {len(set(sorted_map.values()))} tickers")
        elif args.dry_run:
            print(f"\n[DRY-RUN] Would merge {merged} aliases for {len(high)} tickers")


if __name__ == "__main__":
    main()
