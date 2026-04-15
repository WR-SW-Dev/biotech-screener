#!/usr/bin/env python3
"""Refresh conference program + abstract cache from live sources.

Fetches session programs and abstracts for upcoming/recent conferences,
maps entities to tickers, and derives catalyst events.

Usage:
    python tools/refresh_conference_cache.py
    python tools/refresh_conference_cache.py --conference asco
    python tools/refresh_conference_cache.py --conference aacr --year 2026
    python tools/refresh_conference_cache.py --all
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "wake_robin_data_pipeline"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("refresh_conferences")

CACHE_DIR = PROJECT_ROOT / "cache" / "conferences"
PROD_DATA = PROJECT_ROOT / "production_data"

# Conference schedule: approximate abstract release and meeting dates for 2026
CONFERENCE_SCHEDULE_2026 = {
    "asco": {"year": 2026, "abstracts_available": "2026-05-14", "meeting_start": "2026-05-29"},
    "aacr": {"year": 2026, "abstracts_available": "2026-03-15", "meeting_start": "2026-04-08"},
    "esmo": {"year": 2026, "abstracts_available": "2026-09-01", "meeting_start": "2026-09-26"},
    "ash": {"year": 2026, "abstracts_available": "2026-11-15", "meeting_start": "2026-12-05"},
    "aan": {"year": 2026, "abstracts_available": "2026-03-01", "meeting_start": "2026-04-05"},
    "sabcs": {"year": 2026, "abstracts_available": "2026-11-01", "meeting_start": "2026-12-09"},
    "sitc": {"year": 2026, "abstracts_available": "2026-10-15", "meeting_start": "2026-11-04"},
    "acr": {"year": 2026, "abstracts_available": "2026-10-01", "meeting_start": "2026-11-13"},
}


def _load_ticker_maps() -> tuple:
    """Load product→ticker and company→ticker maps for entity resolution."""
    # Sponsor alias map (company name → ticker)
    company_map: Dict[str, str] = {}
    sponsor_path = PROD_DATA / "sponsor_alias_map.json"
    if sponsor_path.exists():
        company_map = json.loads(sponsor_path.read_text())
        logger.info("Loaded sponsor_alias_map: %d entries", len(company_map))

    # Product/drug → ticker (from universe + known drug names)
    product_map: Dict[str, str] = {}
    universe_path = PROD_DATA / "universe.json"
    if universe_path.exists():
        uni = json.loads(universe_path.read_text())
        if isinstance(uni, list) and uni and isinstance(uni[0], dict):
            for entry in uni:
                ticker = entry.get("ticker", "")
                name = entry.get("name", "")
                if ticker and name:
                    product_map[name.lower()] = ticker

    # NCT → ticker (from AACT sponsor map)
    nct_map: Optional[Dict[str, str]] = None

    return product_map, company_map, nct_map


def refresh_conference(
    slug: str,
    year: int,
    as_of: date,
    product_map: Dict[str, str],
    company_map: Dict[str, str],
    nct_map: Optional[Dict[str, str]],
) -> Dict:
    """Fetch and cache one conference."""
    from collectors.conference_program_collector import collect_conference_derived_events

    logger.info("Refreshing %s %d ...", slug.upper(), year)

    events = collect_conference_derived_events(
        conference_slug=slug,
        edition_year=year,
        as_of_date=as_of,
        cache_dir=CACHE_DIR,
        product_ticker_map=product_map,
        company_ticker_map=company_map,
        nct_ticker_map=nct_map,
        fetch_live=True,
    )

    # Read stats from the cached meta file
    meta_path = CACHE_DIR / slug / f"meta_{as_of.isoformat()}.json"
    if meta_path.exists():
        json.loads(meta_path.read_text())  # validate readable

    sessions_path = CACHE_DIR / slug / f"sessions_{as_of.isoformat()}.json"
    n_sessions = 0
    if sessions_path.exists():
        sdata = json.loads(sessions_path.read_text())
        n_sessions = sdata.get("stats", {}).get("sessions", len(sdata.get("records", [])))

    abstracts_path = CACHE_DIR / slug / f"abstracts_{as_of.isoformat()}.json"
    n_abstracts = 0
    if abstracts_path.exists():
        adata = json.loads(abstracts_path.read_text())
        n_abstracts = adata.get("stats", {}).get("abstracts", len(adata.get("records", [])))

    result = {
        "conference": slug,
        "year": year,
        "sessions": n_sessions,
        "abstracts": n_abstracts,
        "derived_events": len(events),
    }
    logger.info(
        "  %s %d: %d sessions, %d abstracts, %d derived events",
        slug.upper(),
        year,
        n_sessions,
        n_abstracts,
        len(events),
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="Refresh conference cache")
    parser.add_argument("--conference", help="Single conference slug (asco, aacr, etc.)")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--all", action="store_true", help="Refresh all conferences")
    args = parser.parse_args()

    today = date.today()
    product_map, company_map, nct_map = _load_ticker_maps()

    if args.conference:
        slugs = [args.conference.lower()]
    elif args.all:
        slugs = list(CONFERENCE_SCHEDULE_2026.keys())
    else:
        # Default: refresh conferences whose abstracts should be available by now
        slugs = []
        for slug, sched in CONFERENCE_SCHEDULE_2026.items():
            avail = date.fromisoformat(sched["abstracts_available"])
            if avail <= today:
                slugs.append(slug)
        if not slugs:
            logger.info("No conferences with abstracts available yet. Use --all to force.")
            return

    results = []
    for slug in slugs:
        sched = CONFERENCE_SCHEDULE_2026.get(slug, {})
        year = args.year or sched.get("year", 2026)
        try:
            r = refresh_conference(slug, year, today, product_map, company_map, nct_map)
            results.append(r)
        except Exception as e:
            logger.warning("Failed to refresh %s: %s", slug, e)
            results.append({"conference": slug, "year": year, "error": str(e)})

    # Summary
    print()
    print(f"{'Conference':<10s} {'Year':>5s} {'Sessions':>9s} {'Abstracts':>10s} {'Events':>7s}")
    print("-" * 45)
    for r in results:
        if "error" in r:
            print(f"{r['conference']:<10s} {r['year']:>5d}   ERROR: {r['error'][:40]}")
        else:
            print(
                f"{r['conference']:<10s} {r['year']:>5d} {r['sessions']:>9d} {r['abstracts']:>10d} {r['derived_events']:>7d}"
            )


if __name__ == "__main__":
    main()
