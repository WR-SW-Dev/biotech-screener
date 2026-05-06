#!/usr/bin/env python3
"""Populate company_ir_sources.json with real IR URLs.

Two-pass strategy:
  Pass 1 (EDGAR): Get company website from GNW JSON-LD on most recent 8-K news release,
                  then probe common IR URL patterns on that domain.
  Pass 2 (GNW fallback): For any ticker still empty after Pass 1, use GNW keyword
                         search URL with issuer-company filter constructed from the
                         existing backup_sources[0] search keyword.

Usage:
    python tools/populate_ir_sources.py [--dry-run] [--ticker TICKER] [--pass1-only] [--pass2-only]
    python tools/populate_ir_sources.py --dry-run   # preview, no writes
    python tools/populate_ir_sources.py             # full run, writes to company_ir_sources.json

Output: updates production_data/company_ir_sources.json in place.
        also writes a report to artifacts/ir_url_population_YYYY-MM-DD.md
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = PROJECT_ROOT / "production_data" / "company_ir_sources.json"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
LOG_FORMAT = "%(levelname)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

USER_AGENT = "WakeRobinBiotechScreener/1.0 (research)"
RATE_LIMIT = 1.5  # seconds between requests
REQUEST_TIMEOUT = 15

# Common IR URL path patterns to probe on company domain
IR_PATH_CANDIDATES = [
    "/investors/news-releases",
    "/investor-relations/news-releases",
    "/investors/press-releases",
    "/investor-relations/press-releases",
    "/news-releases",
    "/press-releases",
    "/investors/news",
    "/investor-relations/news",
    "/investors",
    "/investor-relations",
    "/ir/news-releases",
    "/ir/press-releases",
    "/ir",
]

# Common IR subdomain prefixes to try
IR_SUBDOMAIN_PREFIXES = ["investors", "investor-relations", "ir"]

EDGAR_HEADERS = {"User-Agent": "WakeRobinBiotechScreener research@wakerobincapital.com"}
HTTP_HEADERS = {"User-Agent": USER_AGENT}


def _get(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        logger.debug("GET %s failed: %s", url, e)
        return None


def _get_edgar(url: str) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        logger.debug("EDGAR GET %s failed: %s", url, e)
        return None


def _load_company_tickers() -> dict[str, int]:
    """Return {ticker: cik_int} from EDGAR company_tickers.json."""
    resp = _get_edgar("https://www.sec.gov/files/company_tickers.json")
    if not resp:
        return {}
    data = resp.json()
    return {v["ticker"]: v["cik_str"] for v in data.values()}


def _get_company_domain_from_8k(cik: int) -> Optional[str]:
    """Extract company domain from EDGAR 8-K XBRL namespace or exhibit links.

    EDGAR 8-K .txt files embed XBRL namespaces like:
      http://www.company.com/20260325
    This is a reliable source of the company's canonical domain.
    """
    cik_padded = str(cik).zfill(10)
    resp = _get_edgar(f"https://data.sec.gov/submissions/CIK{cik_padded}.json")
    if not resp:
        return None
    data = resp.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])

    # Find the most recent 8-K (try up to 3)
    checked = 0
    for form, date, acc in zip(forms, dates, accs):
        if form != "8-K":
            continue
        if checked >= 3:
            break
        checked += 1

        acc_nodash = acc.replace("-", "")
        # Check the index page first for exhibit links
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}-index.htm"
        time.sleep(0.3)
        idx_resp = _get_edgar(index_url)
        if idx_resp:
            html = idx_resp.text
            # GNW link in exhibit
            gnw_links = re.findall(
                r"(https?://www\.globenewswire\.com/news-release/[^\s\"'<>]+)",
                html,
            )
            if gnw_links:
                logger.debug("  Found GNW link in 8-K index: %s", gnw_links[0])
                return ("gnw_url", gnw_links[0])

        # Fetch the txt to get XBRL namespace domain
        txt_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}.txt"
        time.sleep(0.3)
        txt_resp = _get_edgar(txt_url)
        if not txt_resp:
            continue

        content = txt_resp.text[:200000]

        # Check for GNW links first
        gnw_links = re.findall(
            r"(https?://www\.globenewswire\.com/news-release/[^\s\"'<>]+)",
            content,
        )
        if gnw_links:
            return ("gnw_url", gnw_links[0])

        # Extract company domain from XBRL namespace: http://www.company.com/YYYYMMDD
        # or xmlns:companyname="http://company.com/YYYYMMDD"
        xbrl_domains = re.findall(
            r'xmlns[^=]*=\s*"(https?://(?:www\.)?[a-z0-9][a-z0-9\-\.]+\.[a-z]{2,6})/\d{8}"',
            content,
            re.IGNORECASE,
        )
        # Filter out known non-company domains
        excluded = {"xbrl.org", "w3.org", "sec.gov", "fasb.org", "ifrs.org", "xbrl.sec.gov"}
        company_domains = [d for d in xbrl_domains if not any(excl in d for excl in excluded)]
        if company_domains:
            return ("domain", company_domains[0])

    return None


def _extract_company_website_from_gnw(gnw_url: str) -> Optional[str]:
    """Extract company website from GNW news-release JSON-LD author.url."""
    resp = _get(gnw_url)
    if not resp:
        return None
    html = resp.text
    blobs = re.findall(r"application/ld\+json[^>]*>(.*?)</script>", html, re.DOTALL)
    for blob in blobs:
        try:
            d = json.loads(blob.strip())
            author = d.get("author", {})
            url = author.get("url", "") or author.get("@id", "")
            if url and "globenewswire.com" not in url:
                return url.rstrip("/")
        except Exception:
            continue
    return None


def _probe_ir_url(company_url: str, ticker: str) -> Optional[str]:
    """Given a company base URL, find the IR news-releases page."""
    parsed = urlparse(company_url)
    if not parsed.scheme:
        company_url = "https://" + company_url
        parsed = urlparse(company_url)

    base_domain = parsed.netloc  # e.g. 4dmoleculartherapeutics.com
    scheme = "https"

    # Strip www. for subdomain construction
    domain_no_www = re.sub(r"^www\.", "", base_domain)

    # Build ordered candidate (base_url, path) pairs to probe.
    # Try IR subdomains with specific paths BEFORE generic company domain paths —
    # subdomains (investors.company.com) are far more likely to be proper IR pages.
    candidates = []

    # Tier 1: IR subdomain + explicit paths
    for prefix in IR_SUBDOMAIN_PREFIXES:
        ir_base = f"{scheme}://{prefix}.{domain_no_www}"
        for path in IR_PATH_CANDIDATES:
            candidates.append(ir_base + path)
        # Also probe the subdomain root
        candidates.append(ir_base)

    # Tier 2: Company domain + explicit paths
    for path in IR_PATH_CANDIDATES:
        candidates.append(company_url.rstrip("/") + path)

    # Group candidates by base so we can skip an entire subdomain on first timeout/SSL error
    by_base: dict = defaultdict(list)
    ordered_bases = []
    for candidate in candidates:
        p = urlparse(candidate)
        base_key = f"{p.scheme}://{p.netloc}"
        if base_key not in by_base:
            ordered_bases.append(base_key)
        by_base[base_key].append(candidate)

    for base_key in ordered_bases:
        skip_base = False
        for candidate in by_base[base_key]:
            if skip_base:
                break
            logger.debug("Probing %s", candidate)
            try:
                resp = requests.get(
                    candidate,
                    headers=HTTP_HEADERS,
                    timeout=5,
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    text_lower = resp.text.lower()
                    if any(
                        kw in text_lower for kw in ["press release", "news release", "announcements", "investor news"]
                    ):
                        return resp.url
            except (requests.exceptions.SSLError, requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout):
                # This base is unreachable — skip remaining paths on it
                logger.debug("  Unreachable base %s, skipping", base_key)
                skip_base = True
            except requests.RequestException:
                pass
            time.sleep(0.2)

    return None


def _gnw_issuer_url_for_ticker(ticker: str, company_name: str) -> str:
    """Build a GNW keyword search URL scoped to this company.

    GNW doesn't have a clean /issuer/TICKER endpoint, but the keyword search
    with the company name is much more precise than ticker alone for biotechs.
    We use the company name stripped to key words.
    """
    # Use ticker for the search - it's already what backup_sources[0] uses
    # But we format it as an issuer-like URL so the fetcher can still parse it
    return f"https://www.globenewswire.com/Search?keyword={ticker}&lang=en"


def pass1_edgar(sources: list, ticker_to_cik: dict[str, int], dry_run: bool) -> dict[str, dict]:
    """Pass 1: Use EDGAR 8-K XBRL namespaces + GNW JSON-LD to discover company IR URLs."""
    results: dict[str, dict] = {}  # ticker -> {ir_url, method, domain}
    empty = [e for e in sources if not e.get("company_ir_url", "").strip()]
    logger.info("Pass 1 (EDGAR XBRL/GNW JSON-LD): %d tickers to process", len(empty))

    for i, entry in enumerate(empty):
        ticker = entry["ticker"]
        cik = ticker_to_cik.get(ticker)
        if not cik:
            logger.info("[%d/%d] %s: CIK not found in EDGAR", i + 1, len(empty), ticker)
            results[ticker] = {"ir_url": None, "method": "no_cik"}
            continue

        logger.info("[%d/%d] %s (CIK=%d): checking EDGAR 8-K...", i + 1, len(empty), ticker, cik)
        time.sleep(RATE_LIMIT)

        edgar_result = _get_company_domain_from_8k(cik)
        if not edgar_result:
            logger.info("  %s: no domain or GNW link found in 8-Ks", ticker)
            results[ticker] = {"ir_url": None, "method": "no_8k_domain"}
            continue

        kind, value = edgar_result

        if kind == "gnw_url":
            # Got a direct GNW news-release URL from 8-K exhibit
            logger.info("  %s: GNW URL from 8-K = %s", ticker, value[:80])
            time.sleep(RATE_LIMIT)
            company_site = _extract_company_website_from_gnw(value)
            if not company_site:
                logger.info("  %s: no company website in GNW JSON-LD", ticker)
                results[ticker] = {"ir_url": None, "method": "no_jsonld_site"}
                continue
            logger.info("  %s: company site = %s", ticker, company_site)
            time.sleep(RATE_LIMIT)
            ir_url = _probe_ir_url(company_site, ticker)
            if ir_url:
                logger.info("  %s: IR URL = %s", ticker, ir_url)
                results[ticker] = {"ir_url": ir_url, "method": "edgar_gnw_probe", "domain": company_site}
            else:
                logger.info("  %s: IR probe failed on %s", ticker, company_site)
                results[ticker] = {"ir_url": None, "method": "probe_failed", "domain": company_site}

        elif kind == "domain":
            # Got company domain from XBRL namespace
            company_site = value
            logger.info("  %s: company domain from XBRL = %s", ticker, company_site)
            time.sleep(RATE_LIMIT)
            ir_url = _probe_ir_url(company_site, ticker)
            if ir_url:
                logger.info("  %s: IR URL = %s", ticker, ir_url)
                results[ticker] = {"ir_url": ir_url, "method": "edgar_xbrl_probe", "domain": company_site}
            else:
                logger.info("  %s: IR probe failed on %s", ticker, company_site)
                results[ticker] = {"ir_url": None, "method": "probe_failed", "domain": company_site}

    return results


def pass2_gnw_fallback(sources: list, pass1_results: dict, dry_run: bool) -> dict[str, dict]:
    """Pass 2: For tickers still without IR URL, search GNW for company domain via JSON-LD."""
    results: dict[str, dict] = {}
    still_empty = [
        e
        for e in sources
        if not e.get("company_ir_url", "").strip() and not (pass1_results.get(e["ticker"], {}).get("ir_url"))
    ]
    logger.info("Pass 2 (GNW search -> JSON-LD probe): %d tickers remaining", len(still_empty))

    for i, entry in enumerate(still_empty):
        ticker = entry["ticker"]
        company = entry.get("company", ticker)
        time.sleep(RATE_LIMIT)

        # GNW redirects /Search?keyword=X to /en/search/keyword/X
        gnw_search_url = f"https://www.globenewswire.com/en/search/keyword/{ticker}"
        logger.info("[%d/%d] %s: searching GNW...", i + 1, len(still_empty), ticker)
        resp = _get(gnw_search_url)
        if not resp:
            results[ticker] = {"ir_url": None, "method": "gnw_search_failed"}
            continue

        html = resp.text
        # Extract news release links with date in URL
        # Pattern: /news-release/YYYY/MM/DD/{release_id}/{org_or_zero}/en/{slug}
        nr_matches = re.findall(
            r'/news-release/(\d{4})/(\d{2})/(\d{2})/(\d+)/\d+/en/([^"\'<>\s]+)',
            html,
        )

        # Filter for matches that look like this company (slug contains ticker-like words)
        ticker_lower = ticker.lower()
        company_words = set(re.sub(r"[^a-z0-9 ]", " ", company.lower()).split()) - {
            "inc",
            "the",
            "and",
            "of",
            "corp",
            "ltd",
            "therapeutics",
            "sciences",
            "biosciences",
        }

        best_match = None
        for yr, mo, dy, rel_id, slug in nr_matches[:20]:
            slug_lower = slug.lower().rstrip(".html")
            if ticker_lower in slug_lower or any(w in slug_lower for w in company_words if len(w) > 3):
                best_match = (yr, mo, dy, rel_id, slug)
                break

        if not best_match and nr_matches:
            # No slug match - just use the first result (likely correct since we searched by ticker)
            best_match = nr_matches[0]

        if best_match:
            yr, mo, dy, rel_id, slug = best_match
            slug_clean = slug.rstrip(".html")
            gnw_release_url = (
                f"https://www.globenewswire.com/news-release/{yr}/{mo}/{dy}/{rel_id}/0/en/{slug_clean}.html"
            )

            time.sleep(RATE_LIMIT)
            company_site = _extract_company_website_from_gnw(gnw_release_url)
            if company_site:
                logger.info("  %s: company site via GNW JSON-LD = %s", ticker, company_site)
                time.sleep(RATE_LIMIT)
                ir_url = _probe_ir_url(company_site, ticker)
                if ir_url:
                    logger.info("  %s: IR URL = %s", ticker, ir_url)
                    results[ticker] = {"ir_url": ir_url, "method": "gnw_jsonld_probe", "domain": company_site}
                    continue
                # Domain found but IR probe failed - return domain root as fallback
                logger.info("  %s: IR probe failed, using domain root", ticker)
                results[ticker] = {"ir_url": company_site, "method": "gnw_jsonld_domain", "domain": company_site}
                continue
            else:
                logger.info("  %s: no JSON-LD on GNW release page", ticker)
        else:
            logger.info("  %s: no GNW results found", ticker)

        # Absolute last resort: GNW keyword search URL (no improvement over current backup)
        results[ticker] = {"ir_url": None, "method": "gnw_no_result"}

    return results


def apply_results(sources: list, pass1: dict, pass2: dict, dry_run: bool) -> tuple[list, dict]:
    """Merge pass1 and pass2 results into sources list. Returns (updated_sources, stats)."""
    stats = {
        "total": len(sources),
        "already_populated": 0,
        "updated_pass1": 0,
        "updated_pass2": 0,
        "still_empty": 0,
        "method_counts": {},
    }

    updated = []
    for entry in sources:
        ticker = entry["ticker"]
        if entry.get("company_ir_url", "").strip():
            stats["already_populated"] += 1
            updated.append(entry)
            continue

        r1 = pass1.get(ticker)
        r2 = pass2.get(ticker)
        result = None
        from_pass = None
        if r1 and r1.get("ir_url"):
            result = r1
            from_pass = 1
        elif r2 and r2.get("ir_url"):
            result = r2
            from_pass = 2

        if result:
            method = result["method"]
            stats["method_counts"][method] = stats["method_counts"].get(method, 0) + 1

            new_entry = dict(entry)
            new_entry["company_ir_url"] = result["ir_url"]
            new_entry["_ir_population_method"] = method
            new_entry["_ir_population_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            updated.append(new_entry)
            if from_pass == 1:
                stats["updated_pass1"] += 1
            else:
                stats["updated_pass2"] += 1
        else:
            stats["still_empty"] += 1
            updated.append(entry)

    return updated, stats


def write_report(stats: dict, pass1: dict, pass2: dict, date_str: str) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS_DIR / f"ir_url_population_{date_str}.md"

    lines = [
        f"# IR URL Population Report — {date_str}",
        "",
        "## Summary",
        f"- Total entries: {stats['total']}",
        f"- Already populated (pre-run): {stats['already_populated']}",
        f"- Updated via Pass 1 (EDGAR/GNW JSON-LD): {stats['updated_pass1']}",
        f"- Updated via Pass 2 (GNW release probe/fallback): {stats['updated_pass2']}",
        f"- Still empty after both passes: {stats['still_empty']}",
        "",
        "## Method Breakdown",
    ]
    for method, count in sorted(stats["method_counts"].items(), key=lambda x: -x[1]):
        lines.append(f"- {method}: {count}")

    lines += ["", "## Pass 1 Results"]
    for ticker, r in sorted(pass1.items()):
        url = r.get("ir_url") or "(none)"
        method = r.get("method", "?")
        lines.append(f"- {ticker}: {method} -> {url}")

    lines += ["", "## Pass 2 Results"]
    for ticker, r in sorted(pass2.items()):
        url = r.get("ir_url") or "(none)"
        method = r.get("method", "?")
        lines.append(f"- {ticker}: {method} -> {url}")

    report_path.write_text("\n".join(lines) + "\n")
    return report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--ticker", help="Process only this ticker (for testing)")
    parser.add_argument("--pass1-only", action="store_true", help="Run only EDGAR pass")
    parser.add_argument("--pass2-only", action="store_true", help="Run only GNW fallback pass")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load sources
    with open(SOURCES_PATH) as f:
        data = json.load(f)
    sources = data["sources"]
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if args.ticker:
        sources = [e for e in sources if e["ticker"] == args.ticker.upper()]
        if not sources:
            logger.error("Ticker %s not found in sources", args.ticker)
            sys.exit(1)

    # Load EDGAR ticker->CIK map
    logger.info("Loading EDGAR company_tickers.json...")
    ticker_to_cik = _load_company_tickers()
    logger.info("Loaded %d ticker->CIK mappings", len(ticker_to_cik))

    pass1_results: dict = {}
    pass2_results: dict = {}

    if not args.pass2_only:
        pass1_results = pass1_edgar(sources, ticker_to_cik, args.dry_run)

    if not args.pass1_only:
        pass2_results = pass2_gnw_fallback(sources, pass1_results, args.dry_run)

    # Merge results into sources
    if args.ticker:
        # For single-ticker test, just print results
        r1 = pass1_results.get(args.ticker.upper())
        r2 = pass2_results.get(args.ticker.upper())
        print(f"Pass 1 result: {r1}")
        print(f"Pass 2 result: {r2}")
        return

    updated_sources, stats = apply_results(sources, pass1_results, pass2_results, args.dry_run)

    print("\n=== IR URL Population Results ===")
    print(f"Total entries:          {stats['total']}")
    print(f"Already populated:      {stats['already_populated']}")
    print(f"Updated (Pass 1):       {stats['updated_pass1']}")
    print(f"Updated (Pass 2):       {stats['updated_pass2']}")
    print(f"Still empty:            {stats['still_empty']}")
    print(f"Net newly populated:    {stats['updated_pass1'] + stats['updated_pass2']}")
    print("\nMethod breakdown:")
    for method, count in sorted(stats["method_counts"].items(), key=lambda x: -x[1]):
        print(f"  {method}: {count}")

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return

    # Write updated sources
    data["sources"] = updated_sources
    data["_last_ir_population"] = date_str
    with open(SOURCES_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"\nUpdated: {SOURCES_PATH}")

    # Write report
    report_path = write_report(stats, pass1_results, pass2_results, date_str)
    print(f"Report:  {report_path}")


if __name__ == "__main__":
    main()
