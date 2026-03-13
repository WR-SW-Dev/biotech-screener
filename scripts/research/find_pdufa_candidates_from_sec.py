#!/usr/bin/env python3
"""
find_pdufa_candidates_from_sec.py - Surface PDUFA candidate entries from SEC 8-K cache.

Scans the SEC 8-K catalyst cache for filings mentioning PDUFA/NDA/BLA keywords,
cross-references against the universe, and outputs candidate entries for manual
verification and addition to pdufa_dates.json.

Usage:
    python scripts/research/find_pdufa_candidates_from_sec.py
    python scripts/research/find_pdufa_candidates_from_sec.py --as-of-date 2026-03-12
    python scripts/research/find_pdufa_candidates_from_sec.py --out-csv output/pdufa_candidates.csv
"""

import argparse
import csv
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("find_pdufa_candidates")

# Keywords that suggest a PDUFA/regulatory action date
_PDUFA_KEYWORDS = re.compile(
    r"(?i)\b(PDUFA|NDA|BLA|sNDA|sBLA|action\s+date|target\s+date|user\s+fee|"
    r"prescription\s+drug\s+user\s+fee|priority\s+review|standard\s+review|"
    r"complete\s+response|accept(?:ed|ance)\s+for\s+(?:filing|review))\b"
)

# Date patterns in event text: "April 30, 2026" or "2026-04-30"
_DATE_IN_TEXT = re.compile(
    r"(\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b)"
)


def load_universe(data_dir: Path) -> set:
    """Load universe tickers from universe.json."""
    universe_path = data_dir / "universe.json"
    if not universe_path.exists():
        logger.error(f"universe.json not found at {universe_path}")
        return set()
    with open(universe_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {entry.get("ticker", entry) if isinstance(entry, dict) else entry for entry in data}
    if isinstance(data, dict):
        return set(data.get("tickers", data.keys()))
    return set()


def load_existing_pdufa(data_dir: Path) -> set:
    """Load existing PDUFA tickers to exclude from candidates."""
    pdufa_path = data_dir / "pdufa_dates.json"
    if not pdufa_path.exists():
        return set()
    with open(pdufa_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data if isinstance(data, list) else data.get("events", [])
    return {e.get("ticker", "") for e in entries}


def scan_8k_cache(cache_dir: Path, universe: set, existing_pdufa: set) -> list:
    """Scan SEC 8-K cache files for PDUFA keyword matches."""
    candidates = []
    cache_files = sorted(cache_dir.glob("8k_catalysts_*.json"), reverse=True)

    if not cache_files:
        logger.warning(f"No 8-K cache files found in {cache_dir}")
        return candidates

    # Use only the most recent cache file
    latest = cache_files[0]
    logger.info(f"Scanning {latest.name} ({len(cache_files)} total cache files)")

    try:
        events = json.loads(latest.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Error reading {latest}: {e}")
        return candidates

    seen = set()
    for ev in events:
        ticker = ev.get("ticker", "")
        if not ticker or ticker not in universe:
            continue
        if ticker in existing_pdufa:
            continue

        event_name = ev.get("event_name", "")
        event_type = ev.get("event_type", "")
        event_date = ev.get("event_date", "")
        disclosed_at = ev.get("disclosed_at", "")
        confidence = ev.get("confidence", "")

        # Check for PDUFA-related keywords
        text_to_search = f"{event_name} {event_type}"
        if not _PDUFA_KEYWORDS.search(text_to_search):
            continue

        # Deduplicate by ticker (we want one candidate per ticker)
        if ticker in seen:
            continue
        seen.add(ticker)

        # Extract any dates mentioned in the event text
        date_matches = _DATE_IN_TEXT.findall(event_name)
        date_excerpt = ", ".join(date_matches[:3]) if date_matches else ""

        candidates.append(
            {
                "ticker": ticker,
                "event_type": event_type,
                "event_date": event_date,
                "disclosed_at": disclosed_at,
                "confidence": confidence,
                "keyword_excerpt": event_name[:120],
                "dates_found": date_excerpt,
                "source_file": latest.name,
            }
        )

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Find PDUFA candidates from SEC 8-K cache for manual verification.")
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(_PROJECT_ROOT / "production_data"),
        help="Production data directory",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=str(_PROJECT_ROOT / "cache" / "sec" / "8k_catalysts"),
        help="SEC 8-K cache directory",
    )
    parser.add_argument(
        "--out-csv",
        type=str,
        default=None,
        help="Output CSV path (default: stdout)",
    )
    parser.add_argument(
        "--as-of-date",
        type=str,
        default=date.today().isoformat(),
        help="Reference date (for logging only)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    cache_dir = Path(args.cache_dir)

    logger.info(f"Reference date: {args.as_of_date}")

    universe = load_universe(data_dir)
    if not universe:
        logger.error("Empty universe — aborting")
        return 1
    logger.info(f"Universe: {len(universe)} tickers")

    existing_pdufa = load_existing_pdufa(data_dir)
    logger.info(f"Existing PDUFA entries: {len(existing_pdufa)} tickers ({', '.join(sorted(existing_pdufa))})")

    candidates = scan_8k_cache(cache_dir, universe, existing_pdufa)
    logger.info(f"Found {len(candidates)} PDUFA candidates (excluding existing)")

    if not candidates:
        logger.info("No new PDUFA candidates found")
        return 0

    # Sort by ticker
    candidates.sort(key=lambda c: c["ticker"])

    # Output
    fieldnames = [
        "ticker",
        "event_type",
        "event_date",
        "disclosed_at",
        "confidence",
        "keyword_excerpt",
        "dates_found",
        "source_file",
    ]

    if args.out_csv:
        out_path = Path(args.out_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(candidates)
        logger.info(f"Wrote {len(candidates)} candidates → {out_path}")
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(candidates)

    return 0


if __name__ == "__main__":
    sys.exit(main())
