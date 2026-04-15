#!/usr/bin/env python3
"""Fetch conference abstracts via Grok web search + structured extraction.

Conference abstract databases (AACR abstractsonline.com, ASCO meetings.asco.org)
are JavaScript SPAs that can't be scraped with HTTP fetches. This tool uses
xAI Grok's web search to discover and extract abstract data, then normalizes
it into the conference_program_collector cache format.

Usage:
    python tools/fetch_conference_abstracts_grok.py --conference aacr
    python tools/fetch_conference_abstracts_grok.py --conference asco --year 2026
    python tools/fetch_conference_abstracts_grok.py --all
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("conference_grok")

CACHE_DIR = PROJECT_ROOT / "cache" / "conferences"
PROD_DATA = PROJECT_ROOT / "production_data"

XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_BASE_URL = "https://api.x.ai/v1"

# Tickers in universe for matching
_UNIVERSE_TICKERS: set = set()

# Conference metadata
CONFERENCES = {
    "aacr": {
        "full_name": "AACR Annual Meeting",
        "search_terms": ["AACR 2026 abstract", "AACR 2026 late-breaking"],
    },
    "asco": {
        "full_name": "ASCO Annual Meeting",
        "search_terms": ["ASCO 2026 abstract", "ASCO 2026 late-breaking LBA"],
    },
    "esmo": {
        "full_name": "ESMO Congress",
        "search_terms": ["ESMO 2026 abstract", "ESMO 2026 late-breaking LBA"],
    },
    "ash": {
        "full_name": "ASH Annual Meeting",
        "search_terms": ["ASH 2026 abstract", "ASH 2026 late-breaking"],
    },
    "aan": {
        "full_name": "AAN Annual Meeting",
        "search_terms": ["AAN 2026 abstract", "AAN 2026 emerging science"],
    },
    "sabcs": {
        "full_name": "San Antonio Breast Cancer Symposium",
        "search_terms": ["SABCS 2026 abstract", "SABCS 2026 spotlight"],
    },
}

NCT_RE = re.compile(r"NCT\d{8}")


def _load_universe() -> set:
    global _UNIVERSE_TICKERS
    if _UNIVERSE_TICKERS:
        return _UNIVERSE_TICKERS
    uni_path = PROD_DATA / "universe.json"
    if uni_path.exists():
        data = json.loads(uni_path.read_text())
        if isinstance(data, list) and data and isinstance(data[0], dict):
            _UNIVERSE_TICKERS = {d["ticker"] for d in data if "ticker" in d}
        else:
            _UNIVERSE_TICKERS = {s for s in data if isinstance(s, str)}
    return _UNIVERSE_TICKERS


def _load_sponsor_map() -> Dict[str, str]:
    path = PROD_DATA / "sponsor_alias_map.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _grok_web_search(query: str, system_prompt: str) -> str:
    """Call xAI Grok Responses API with web_search tool."""
    import requests as req

    resp = req.post(
        f"{XAI_BASE_URL}/responses",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {XAI_API_KEY}",
        },
        json={
            "model": "grok-4-fast-non-reasoning",
            "tools": [{"type": "web_search"}],
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
        },
        timeout=120,
    )

    if resp.status_code != 200:
        logger.warning("Grok API %d: %s", resp.status_code, resp.text[:200])
        return ""

    data = resp.json()
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    return content["text"]
    return ""


def _search_conference_abstracts(
    conference: str,
    year: int,
    search_terms: List[str],
    universe: set,
    sponsor_map: Dict[str, str],
) -> List[Dict]:
    """Use Grok to search for and extract conference abstract data."""
    universe_sample = sorted(universe)[:50]  # Top tickers for context

    system_prompt = f"""You are a biotech research assistant extracting conference abstract data.
Given a medical conference name and year, search for published abstracts and presentations.

For each abstract/presentation found, extract:
- ticker: stock ticker of the presenting company (from this universe: {', '.join(universe_sample[:30])}...)
- drug_name: the drug/compound name
- indication: disease/condition being studied
- phase: clinical trial phase (1, 1/2, 2, 3, or approved)
- presentation_type: one of [plenary, lbct, oral, poster, other]
- abstract_number: the abstract code (e.g., LBA1, CT001, 4502)
- nct_id: ClinicalTrials.gov NCT ID if mentioned
- title: abstract title (abbreviated if long)
- is_late_breaker: true/false

Return ONLY a JSON array of objects. No explanation text. If no abstracts found, return [].
Focus on biotech companies in our universe. Prioritize late-breaking abstracts and plenary presentations.

CRITICAL: Only include abstracts you can verify from actual published sources.
Do NOT fabricate or hallucinate abstract numbers, drug names, or results.
If you are not certain an abstract exists, do not include it. Return [] rather than guess."""

    all_abstracts: List[Dict] = []
    seen_keys: set = set()

    for query_template in search_terms:
        query = query_template.replace("2026", str(year))
        full_query = f"{query} biotech pharma drug results"
        logger.info("  Searching: %s", full_query)

        user_query = (
            f"Search the web for {conference} {year} biotech presentations. "
            f'Query: "{full_query}"\n\n'
            f"Find press releases from biotech companies announcing accepted abstracts. "
            f"Return a JSON array of abstract records. Include as many as you can find."
        )

        try:
            response = _grok_web_search(user_query, system_prompt)
        except Exception as e:
            logger.warning("  Grok API error: %s", e)
            continue

        # Parse JSON from response
        try:
            # Extract JSON array from response (may have markdown wrapping)
            json_match = re.search(r"\[[\s\S]*\]", response)
            if json_match:
                records = json.loads(json_match.group())
            else:
                records = []
        except json.JSONDecodeError:
            logger.warning("  Failed to parse Grok response as JSON")
            records = []

        for rec in records:
            if not isinstance(rec, dict):
                continue
            ticker = (rec.get("ticker") or "").upper()
            if ticker and ticker in universe:
                key = f"{ticker}|{rec.get('abstract_number', '')}|{rec.get('drug_name', '')}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_abstracts.append(rec)

        logger.info("  Found %d universe-matched abstracts from this query", len(records))
        time.sleep(2)  # Rate limit

    return all_abstracts


def _normalize_to_cache_format(
    abstracts: List[Dict],
    conference_slug: str,
    year: int,
    as_of: date,
) -> Dict:
    """Convert Grok-extracted abstracts to conference_program_collector cache format."""
    normalized = []
    for i, a in enumerate(abstracts):
        abstract_code = a.get("abstract_number", f"GROK_{i:04d}")
        ptype = a.get("presentation_type", "other").lower()
        if ptype not in ("plenary", "lbct", "oral", "poster"):
            ptype = "other"

        normalized.append(
            {
                "id": f"grok_{conference_slug}_{year}_{i:04d}",
                "abstract_code": abstract_code,
                "title": a.get("title", ""),
                "presentation_type": ptype,
                "session_id": None,
                "entities": {
                    "drugs": [a["drug_name"]] if a.get("drug_name") else [],
                    "companies": [],
                    "nct_ids": [a["nct_id"]] if a.get("nct_id") else [],
                },
                "sponsor_company": None,
                "ticker": a.get("ticker", ""),
                "indication": a.get("indication", ""),
                "phase": a.get("phase", ""),
                "is_late_breaker": a.get("is_late_breaker", False),
                "source": "grok_web_search",
                "disclosed_at": as_of.isoformat(),
            }
        )

    return {
        "schema": "conference_abstracts.v1",
        "as_of_date": as_of.isoformat(),
        "conference": conference_slug.upper(),
        "edition_year": year,
        "collector_version": "grok_conference_fetch.v1",
        "records": normalized,
        "stats": {
            "fetched_via": "grok_web_search",
            "abstracts": len(normalized),
            "n_late_breakers": sum(1 for a in normalized if a.get("is_late_breaker")),
        },
    }


def fetch_conference(slug: str, year: int) -> Dict:
    """Fetch abstracts for one conference via Grok."""
    conf = CONFERENCES.get(slug)
    if not conf:
        logger.warning("Unknown conference: %s", slug)
        return {"conference": slug, "error": "unknown"}

    today = date.today()
    universe = _load_universe()
    sponsor_map = _load_sponsor_map()

    logger.info("Fetching %s %d abstracts via Grok...", slug.upper(), year)

    abstracts = _search_conference_abstracts(
        conf["full_name"],
        year,
        conf["search_terms"],
        universe,
        sponsor_map,
    )

    logger.info("Total universe-matched abstracts: %d", len(abstracts))

    if abstracts:
        # Write to cache
        cache_data = _normalize_to_cache_format(abstracts, slug, year, today)
        cache_path = CACHE_DIR / slug / f"abstracts_{today.isoformat()}.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f, indent=2)
        logger.info("Cached %d abstracts → %s", len(abstracts), cache_path)

    return {
        "conference": slug,
        "year": year,
        "abstracts": len(abstracts),
        "late_breakers": sum(1 for a in abstracts if a.get("is_late_breaker")),
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch conference abstracts via Grok")
    parser.add_argument("--conference", help="Conference slug (aacr, asco, etc.)")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if not XAI_API_KEY:
        logger.error("XAI_API_KEY not set")
        sys.exit(1)

    if args.conference:
        slugs = [args.conference.lower()]
    elif args.all:
        slugs = list(CONFERENCES.keys())
    else:
        slugs = ["aacr"]  # Default: AACR (happening this week)

    results = []
    for slug in slugs:
        try:
            r = fetch_conference(slug, args.year)
            results.append(r)
        except Exception as e:
            logger.warning("Failed: %s — %s", slug, e)
            results.append({"conference": slug, "error": str(e)})

    print()
    print(f"{'Conference':<10s} {'Year':>5s} {'Abstracts':>10s} {'Late-Breaking':>14s}")
    print("-" * 45)
    for r in results:
        if "error" in r:
            print(f"{r['conference']:<10s}   ERROR: {r['error'][:40]}")
        else:
            print(f"{r['conference']:<10s} {r['year']:>5d} {r['abstracts']:>10d} {r.get('late_breakers', 0):>14d}")


if __name__ == "__main__":
    main()
