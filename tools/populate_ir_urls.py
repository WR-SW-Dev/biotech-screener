"""
populate_ir_urls.py — Option 2+3 IR URL discovery for company_ir_sources.json

Strategy (applied in order per ticker):
  1. EDGAR submissions API (CIK → investorWebsite / website field)
     Uses: https://data.sec.gov/submissions/CIK{padded_cik}.json
     Best source: SEC-registered, deterministic, no network guessing.
  2. URL pattern matching (HEAD request validation)
     Tries: https://ir.<slug>.com/news-releases
             https://investors.<slug>.com/news-releases
             https://investor.<slug>.com/news-releases
     Where <slug> is derived from company name (lowercased, cleaned).
  3. Falls back to empty — records for manual review.

Output:
  tools/ir_url_discovery_results.json — full results per ticker
    {ticker: {method, url, status, confidence}}
  tools/ir_url_patch_ready.json — entries ready to patch (confidence=high/medium)

Usage:
  python tools/populate_ir_urls.py --dry-run --limit 10
  python tools/populate_ir_urls.py --dry-run          # all 300 empty tickers
  python tools/populate_ir_urls.py --apply            # write to company_ir_sources.json

DO NOT RUN with --apply without operator approval. --dry-run is always safe.

Notes:
  - EDGAR API requires User-Agent header (SEC policy). Set SEC_USER_AGENT env var
    or defaults to "biotech-screener research@wakerobincapital.com"
  - Rate limit: 10 req/sec per SEC fair-use policy. Script enforces 120ms delay.
  - WSL2 Cloudflare blocks: HEAD requests to some IR pages will 403/000.
    Any non-200 HEAD is recorded as unconfirmed (not discarded).
  - EDGAR approach is high-confidence even without HEAD validation because
    the URL comes directly from the company's SEC filing.
"""

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

REPO = Path(__file__).parent.parent
IR_SOURCES_PATH = REPO / "production_data" / "company_ir_sources.json"
UNIVERSE_PATH = REPO / "production_data" / "universe.json"
RESULTS_PATH = REPO / "tools" / "ir_url_discovery_results.json"
PATCH_READY_PATH = REPO / "tools" / "ir_url_patch_ready.json"

EDGAR_BASE = "https://data.sec.gov/submissions"
EDGAR_DELAY = 0.12  # 120ms between requests → ~8 req/sec, under 10 req/sec limit
PATTERN_DELAY = 0.5  # 500ms between HEAD requests

SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "biotech-screener research@wakerobincapital.com")

PRESS_RELEASE_PATHS = [
    "/news-releases",
    "/press-releases",
    "/news-events/press-releases",
    "/news-events/news-releases",
    "/news",
]

IR_SUBDOMAINS = ["ir", "investors", "investor"]


def load_sources() -> list[dict]:
    with open(IR_SOURCES_PATH) as f:
        data = json.load(f)
    return data["sources"]


def load_universe_cik_map() -> dict[str, str]:
    """Returns {ticker: cik_padded} for all universe entries with CIK."""
    with open(UNIVERSE_PATH) as f:
        universe = json.load(f)
    result = {}
    for entry in universe:
        ticker = entry.get("ticker")
        cik = entry.get("cik")
        if ticker and cik:
            result[ticker] = str(cik).zfill(10)
    return result


def fetch_edgar_ir_url(cik_padded: str) -> tuple[Optional[str], str]:
    """
    Query EDGAR submissions API for a company's investor/website URL.
    Returns (url_or_None, method_note).
    """
    url = f"{EDGAR_BASE}/CIK{cik_padded}.json"
    try:
        r = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=10)
        time.sleep(EDGAR_DELAY)
        if r.status_code != 200:
            return None, f"edgar_http_{r.status_code}"
        data = r.json()
        # Prefer investorWebsite, then website
        for field in ("investorWebsite", "website"):
            site = data.get(field, "").strip()
            if site and site.startswith("http"):
                # Append /news-releases if it looks like a bare IR homepage
                parsed = urlparse(site)
                if not parsed.path or parsed.path in ("/", ""):
                    site = site.rstrip("/") + "/news-releases"
                return site, f"edgar_{field}"
        return None, "edgar_no_url"
    except Exception as e:
        return None, f"edgar_error:{type(e).__name__}"


def company_name_to_slug(name: str) -> list[str]:
    """
    Derive candidate slugs from company name.
    E.g. "CRISPR Therapeutics AG" → ["crisprtx", "crispr-therapeutics", "crispr"]
    Returns list of candidates, most specific first.
    """
    name = name.lower()
    # Strip legal suffixes
    for suffix in [
        " inc.",
        " inc",
        " corp.",
        " corp",
        " ltd.",
        " ltd",
        " llc",
        " plc",
        " ag",
        " n.v.",
        " nv",
        " b.v.",
        " bv",
        ", inc",
        ", corp",
        " s.a.",
        " sa",
        " therapeutics",
        " pharma",
        " biosciences",
        " biotherapeutics",
        " biotechnology",
    ]:
        name = name.replace(suffix, "")
    name = name.strip()

    # Clean non-alphanumeric to hyphens
    slug_hyphen = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    # Remove hyphens entirely for compact slug
    slug_compact = slug_hyphen.replace("-", "")

    # Also try adding "tx" suffix (common for therapeutics companies)
    candidates = [slug_compact, slug_hyphen]
    if not slug_compact.endswith("tx"):
        candidates.append(slug_compact + "tx")
    return [c for c in candidates if c]


def probe_ir_url(slug: str, timeout: int = 6) -> Optional[str]:
    """
    Try each subdomain + path combination for a slug.
    Returns the first URL that responds 200 to a HEAD, or None.
    """
    for subdomain in IR_SUBDOMAINS:
        for path in PRESS_RELEASE_PATHS:
            candidate = f"https://{subdomain}.{slug}.com{path}"
            try:
                r = requests.head(
                    candidate,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=timeout,
                    allow_redirects=True,
                )
                time.sleep(PATTERN_DELAY)
                if r.status_code == 200:
                    return candidate
            except Exception:
                time.sleep(PATTERN_DELAY)
    return None


def discover_ir_url(
    ticker: str,
    company: str,
    cik: Optional[str],
    skip_head: bool = False,
) -> dict:
    """
    Run the full discovery pipeline for one ticker.
    Returns result dict with keys: ticker, company, url, method, confidence, notes.
    """
    result = {
        "ticker": ticker,
        "company": company,
        "url": "",
        "method": "none",
        "confidence": "none",
        "notes": "",
    }

    # --- Step 1: EDGAR ---
    if cik:
        edgar_url, edgar_note = fetch_edgar_ir_url(cik)
        if edgar_url:
            result["url"] = edgar_url
            result["method"] = edgar_note
            result["confidence"] = "high"
            result["notes"] = f"CIK={cik}"
            return result
        result["notes"] = edgar_note
    else:
        result["notes"] = "no_cik"

    if skip_head:
        result["method"] = "edgar_miss_no_head"
        result["confidence"] = "none"
        return result

    # --- Step 2: URL pattern matching ---
    slugs = company_name_to_slug(company)
    for slug in slugs:
        url = probe_ir_url(slug)
        if url:
            result["url"] = url
            result["method"] = "pattern_head_200"
            result["confidence"] = "medium"
            result["notes"] += f" slug={slug}"
            return result

    # --- Step 3: record candidates without HEAD confirmation ---
    # Store best-guess URL for manual review even if HEAD failed
    if slugs:
        best_guess = f"https://ir.{slugs[0]}.com/news-releases"
        result["url"] = best_guess
        result["method"] = "pattern_unconfirmed"
        result["confidence"] = "low"
        result["notes"] += f" slug={slugs[0]} head_failed_or_skipped"

    return result


def main():
    parser = argparse.ArgumentParser(description="Discover IR URLs for company_ir_sources.json")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Discover and write results files but do NOT patch company_ir_sources.json (default)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply high+medium confidence results to company_ir_sources.json"
    )
    parser.add_argument("--limit", type=int, default=0, help="Process only first N empty tickers (0 = all)")
    parser.add_argument("--skip-head", action="store_true", help="Skip HEAD validation (faster; EDGAR-only discovery)")
    parser.add_argument("--ticker", type=str, default="", help="Process only this ticker (for testing)")
    args = parser.parse_args()

    if args.apply:
        args.dry_run = False

    sources = load_sources()
    cik_map = load_universe_cik_map()

    # Only process tickers with empty company_ir_url
    empty = [s for s in sources if not s.get("company_ir_url", "").strip()]
    if args.ticker:
        empty = [s for s in empty if s["ticker"] == args.ticker.upper()]
    if args.limit:
        empty = empty[: args.limit]

    print(f"Discovering IR URLs for {len(empty)} tickers " f"({'dry-run' if args.dry_run else 'APPLY MODE'})")
    print(f"  EDGAR API: {'yes' if not args.skip_head else 'yes (HEAD skipped)'}")
    print(f"  Pattern HEAD: {'no' if args.skip_head else 'yes'}")
    print()

    results = []
    for i, source in enumerate(empty, 1):
        ticker = source["ticker"]
        company = source.get("company", ticker)
        cik = cik_map.get(ticker)
        print(f"  [{i:3d}/{len(empty)}] {ticker:8} {company[:40]}", end="", flush=True)
        r = discover_ir_url(ticker, company, cik, skip_head=args.skip_head)
        results.append(r)
        conf_tag = {"high": "HI", "medium": "MED", "low": "LOW", "none": "---"}[r["confidence"]]
        print(f"  [{conf_tag}] {r['url'][:60] if r['url'] else '(none)'}")

    # Write full results
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results written: {RESULTS_PATH}")

    # Summary
    by_conf = {"high": [], "medium": [], "low": [], "none": []}
    for r in results:
        by_conf[r["confidence"]].append(r["ticker"])

    print("\nSummary:")
    print(f"  High confidence (EDGAR):    {len(by_conf['high'])} tickers")
    print(f"  Medium confidence (pattern HEAD 200): {len(by_conf['medium'])} tickers")
    print(f"  Low confidence (unconfirmed guess):   {len(by_conf['low'])} tickers")
    print(f"  No URL found:               {len(by_conf['none'])} tickers")

    # Write patch-ready subset
    patch_ready = [r for r in results if r["confidence"] in ("high", "medium")]
    with open(PATCH_READY_PATH, "w") as f:
        json.dump(patch_ready, f, indent=2)
    print(f"Patch-ready entries written:  {PATCH_READY_PATH}  ({len(patch_ready)} tickers)")

    if args.dry_run:
        print("\nDRY RUN — company_ir_sources.json NOT modified.")
        print("Review tools/ir_url_discovery_results.json then re-run with --apply")
        return

    # --apply: patch company_ir_sources.json with high+medium results
    print(f"\nApplying {len(patch_ready)} URLs to {IR_SOURCES_PATH} ...")
    ticker_to_url = {r["ticker"]: r["url"] for r in patch_ready}
    patched = 0
    for source in sources:
        if source["ticker"] in ticker_to_url:
            source["company_ir_url"] = ticker_to_url[source["ticker"]]
            # Keep GNW backup as fallback
            patched += 1

    with open(IR_SOURCES_PATH, "w") as f:
        json.dump({"schema": "company_ir_sources.v1", "sources": sources}, f, indent=2)
    print(f"Patched {patched} entries. Done.")
    print("Run: python tools/fetch_company_press_releases.py --health-check")


if __name__ == "__main__":
    main()
