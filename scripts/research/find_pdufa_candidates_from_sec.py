#!/usr/bin/env python3
"""
find_pdufa_candidates_from_sec.py - Surface PDUFA candidate entries from SEC 8-K cache.

Scans the SEC 8-K catalyst cache for filings mentioning PDUFA/NDA/BLA keywords,
cross-references against the universe, and outputs candidate entries for manual
verification and addition to pdufa_dates.json.

Two output formats:
  --format discovery  (default) CSV for triage — ticker, keyword_excerpt, dates_found
  --format ingestion  JSON shaped for collect_pdufa_forward.py --validate/--ingest

Filters:
  --forward-only      Drop candidates whose event_date is on or before --as-of-date.
                       Also classifies imprecise quarter-level dates. Prints a
                       rejection summary by reason (past_date, duplicate_existing,
                       imprecise_date).

Usage:
    python scripts/research/find_pdufa_candidates_from_sec.py --forward-only
    python scripts/research/find_pdufa_candidates_from_sec.py --format ingestion --forward-only --out-json candidates.json
    python scripts/research/find_pdufa_candidates_from_sec.py --as-of-date 2026-03-14
"""

import argparse
import csv
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("find_pdufa_candidates")

# Keywords that suggest a PDUFA/regulatory action date.
# Grouped by category for maintainability:
#   1. Submission types: PDUFA, NDA, BLA, sNDA, sBLA
#   2. Action-date phrasing: action date, target date, target action date,
#      FDA action date, DUFA date
#   3. Review classification: priority review, standard review
#   4. Acceptance/filing: accepted for filing/review, acceptance for filing/review,
#      accepted for review, filing accepted
#   5. Post-decision: complete response, complete response letter
#   6. Advisory committee: advisory committee meeting, ADCOM
_PDUFA_KEYWORDS = re.compile(
    r"(?i)\b("
    # Submission types
    r"PDUFA|NDA|BLA|sNDA|sBLA"
    r"|user\s+fee|prescription\s+drug\s+user\s+fee|DUFA\s+date"
    # Action-date phrasing
    r"|(?:FDA\s+)?action\s+date|target\s+(?:action\s+)?date"
    # Review classification
    r"|priority\s+review|standard\s+review"
    # Acceptance / filing
    r"|accept(?:ed|ance)\s+for\s+(?:filing|review)|filing\s+accepted"
    # Post-decision
    r"|complete\s+response(?:\s+letter)?"
    # Advisory committee
    r"|advisory\s+committee\s+meeting|ADCOM"
    r")\b"
)

# Date patterns in event text: "April 30, 2026" or "2026-04-30"
_DATE_IN_TEXT = re.compile(
    r"(\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b)"
)

# Submission type extraction from keyword text
_SUBMISSION_TYPE = re.compile(r"\b(sNDA|sBLA|NDA|BLA)\b", re.IGNORECASE)

# Normalise extracted submission types to canonical form
_SUBMISSION_CANONICAL = {
    "nda": "NDA",
    "bla": "BLA",
    "snda": "sNDA",
    "sbla": "sBLA",
}

# Quarter-boundary dates that signal imprecise "Q1/Q2/H1/H2" estimates
_QUARTER_BOUNDARIES = frozenset(
    {
        "01-01",
        "04-01",
        "07-01",
        "10-01",
        "06-01",
        "12-01",
        "01-31",
        "03-31",
        "06-30",
        "09-30",
        "12-31",
    }
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


def load_existing_pdufa_keys(data_dir: Path) -> Tuple[Set[str], Set[Tuple[str, str]]]:
    """Load existing PDUFA entries.

    Returns (ticker_set, (ticker, pdufa_date) key_set) for dedup reporting.
    """
    pdufa_path = data_dir / "pdufa_dates.json"
    if not pdufa_path.exists():
        return set(), set()
    with open(pdufa_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data if isinstance(data, list) else data.get("events", [])
    tickers = {e.get("ticker", "") for e in entries}
    keys = {(e.get("ticker", "").upper(), e.get("pdufa_date", "")) for e in entries}
    return tickers, keys


def _is_imprecise_date(event_date: str, confidence: str) -> bool:
    """Detect quarter-level placeholder dates."""
    if confidence == "LOW":
        return True
    if len(event_date) >= 10:
        md = event_date[5:10]  # "MM-DD"
        if md in _QUARTER_BOUNDARIES:
            return True
    return False


def scan_8k_cache(cache_dir: Path, universe: set, existing_tickers: set) -> list:
    """Scan SEC 8-K cache files for PDUFA keyword matches.

    Note: existing_tickers filter is applied here for backward compatibility.
    """
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
        if ticker in existing_tickers:
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


def filter_forward_only(
    candidates: List[Dict[str, str]],
    as_of_date: str,
    existing_keys: Set[Tuple[str, str]],
) -> Tuple[List[Dict[str, str]], Dict[str, List[Dict[str, str]]]]:
    """Filter candidates to forward-looking only.

    Returns (survivors, rejections_by_reason).
    Rejection reasons: past_date, duplicate_existing, imprecise_date.
    """
    survivors = []
    rejections: Dict[str, List[Dict[str, str]]] = {
        "past_date": [],
        "duplicate_existing": [],
        "imprecise_date": [],
    }

    for c in candidates:
        ticker = c.get("ticker", "")
        event_date = c.get("event_date", "")
        confidence = c.get("confidence", "")

        # Check duplicate against existing (ticker, date) keys
        if event_date and (ticker.upper(), event_date) in existing_keys:
            rejections["duplicate_existing"].append(c)
            continue

        # Check past date
        if event_date and event_date <= as_of_date:
            rejections["past_date"].append(c)
            continue

        # Check imprecise date
        if event_date and _is_imprecise_date(event_date, confidence):
            rejections["imprecise_date"].append(c)
            continue

        survivors.append(c)

    return survivors, rejections


def _extract_submission_type(text: str) -> str:
    """Extract submission type (NDA/BLA/sNDA/sBLA) from text."""
    m = _SUBMISSION_TYPE.search(text)
    if m:
        return _SUBMISSION_CANONICAL.get(m.group(1).lower(), "")
    return ""


def format_for_ingestion(
    candidates: List[Dict[str, str]],
    as_of_date: str = "",
) -> List[Dict[str, str]]:
    """Convert discovery-format candidates to ingestion-format records.

    Ingestion records are shaped for collect_pdufa_forward.py --validate/--ingest.
    Fields that require manual review are left empty with a _review_status marker.

    Field mapping:
        event_date      → pdufa_date (NEEDS_REVIEW — may be imprecise)
        disclosed_at    → as_of_disclosed_at
        (hardcoded)     → source = "SEC_8K"
        (empty)         → source_url (reviewer fills in from EDGAR)
        keyword_excerpt → notes (with dates_found context)
        (extracted)     → submission_type (from keyword text)
    """
    ingestion_records: List[Dict[str, str]] = []
    ref_date = as_of_date or date.today().isoformat()

    for c in candidates:
        keyword_excerpt = c.get("keyword_excerpt", "")
        dates_found = c.get("dates_found", "")
        source_file = c.get("source_file", "")

        # Build notes with discovery context for the reviewer
        notes_parts = [f"SEC 8-K keyword match: {keyword_excerpt}"]
        if dates_found:
            notes_parts.append(f"Dates mentioned: {dates_found}")
        notes_parts.append(f"Source cache: {source_file}")
        notes_parts.append(f"Scanned: {ref_date}")

        ingestion_records.append(
            {
                "ticker": c.get("ticker", ""),
                "pdufa_date": c.get("event_date", ""),
                "event_type": "PDUFA",
                "submission_type": _extract_submission_type(keyword_excerpt),
                "confidence": c.get("confidence", ""),
                "source": "SEC_8K",
                "source_url": "",
                "as_of_disclosed_at": c.get("disclosed_at", ""),
                "drug_name": "",
                "indication": "",
                "notes": "; ".join(notes_parts),
                "_review_status": "NEEDS_REVIEW",
                "_source_file": source_file,
            }
        )

    return ingestion_records


_DISCOVERY_FIELDNAMES = [
    "ticker",
    "event_type",
    "event_date",
    "disclosed_at",
    "confidence",
    "keyword_excerpt",
    "dates_found",
    "source_file",
]


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
        help="Output CSV path (discovery format only, default: stdout)",
    )
    parser.add_argument(
        "--out-json",
        type=str,
        default=None,
        help="Output JSON path (ingestion format only)",
    )
    parser.add_argument(
        "--format",
        choices=["discovery", "ingestion"],
        default="discovery",
        dest="output_format",
        help="Output format: discovery (CSV triage) or ingestion (JSON for collect_pdufa_forward)",
    )
    parser.add_argument(
        "--forward-only",
        action="store_true",
        help="Drop past-date, duplicate, and imprecise candidates; print rejection summary",
    )
    parser.add_argument(
        "--as-of-date",
        type=str,
        default=date.today().isoformat(),
        help="Reference date (used for --forward-only filter and ingestion notes)",
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

    existing_tickers, existing_keys = load_existing_pdufa_keys(data_dir)
    logger.info(f"Existing PDUFA entries: {len(existing_tickers)} tickers ({', '.join(sorted(existing_tickers))})")

    candidates = scan_8k_cache(cache_dir, universe, existing_tickers)
    logger.info(f"Found {len(candidates)} PDUFA candidates (excluding existing tickers)")

    if not candidates:
        logger.info("No new PDUFA candidates found")
        return 0

    # Apply forward-only filter
    if args.forward_only:
        candidates, rejections = filter_forward_only(candidates, args.as_of_date, existing_keys)
        total_rejected = sum(len(v) for v in rejections.values())
        logger.info(f"Forward-only filter: {len(candidates)} survivors, {total_rejected} rejected")
        for reason, items in rejections.items():
            if items:
                tickers = ", ".join(c["ticker"] for c in items)
                logger.info(f"  {reason}: {len(items)} ({tickers})")
        if not candidates:
            logger.info("No forward-looking candidates after filtering")
            return 0

    # Sort by ticker
    candidates.sort(key=lambda c: c["ticker"])

    if args.output_format == "ingestion":
        records = format_for_ingestion(candidates, as_of_date=args.as_of_date)
        out_path = Path(args.out_json) if args.out_json else None
        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(records, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            logger.info(f"Wrote {len(records)} ingestion candidates → {out_path}")
        else:
            print(json.dumps(records, indent=2, ensure_ascii=False))
        return 0

    # Discovery format (CSV)
    if args.out_csv:
        out_path = Path(args.out_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_DISCOVERY_FIELDNAMES)
            writer.writeheader()
            writer.writerows(candidates)
        logger.info(f"Wrote {len(candidates)} candidates → {out_path}")
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=_DISCOVERY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(candidates)

    return 0


if __name__ == "__main__":
    sys.exit(main())
