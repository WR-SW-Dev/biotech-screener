#!/usr/bin/env python3
"""Company press release fetcher — deterministic IR/newsroom polling.

Spec 044 Phase 1: guaranteed coverage via direct source polling.
Grok classification happens in a separate step (Phase 2).

Usage:
    python tools/fetch_company_press_releases.py --as-of-date 2026-03-31
    python tools/fetch_company_press_releases.py --as-of-date 2026-03-31 --ticker SION
    python tools/fetch_company_press_releases.py --health-check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "company_pr_raw.v1"
SOURCES_PATH = PROJECT_ROOT / "production_data" / "company_ir_sources.json"
OUTPUT_DIR = PROJECT_ROOT / "data" / "press_releases"
STATE_PATH = OUTPUT_DIR / "fetch_state.json"
USER_AGENT = "WakeRobinBiotechScreener/1.0 (research)"
REQUEST_TIMEOUT = 20
RATE_LIMIT_SECONDS = 2


@dataclass
class PressRelease:
    ticker: str
    headline: str
    published_at_utc: str
    source_url: str
    source_type: str  # company_ir, globenewswire, businesswire, sec_8k
    body_snippet: str = ""
    content_hash: str = ""
    fetched_at_utc: str = ""

    def compute_hash(self) -> str:
        raw = f"{self.ticker}|{self.headline}|{self.published_at_utc}|{self.source_url}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if not d["content_hash"]:
            d["content_hash"] = self.compute_hash()
        return d


@dataclass
class FetchResult:
    ticker: str
    source_type: str
    source_url: str
    success: bool
    releases_found: int = 0
    error: str = ""
    fetched_at: str = ""


def _load_sources() -> List[Dict[str, Any]]:
    if not SOURCES_PATH.exists():
        return []
    with open(SOURCES_PATH) as f:
        data = json.load(f)
    return data.get("sources", [])


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    with open(STATE_PATH) as f:
        return json.load(f)


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)
        f.write("\n")


def _fetch_url(url: str) -> Optional[str]:
    """Fetch URL content with rate limiting and error handling."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.warning("Fetch failed for %s: %s", url, e)
        return None


def _extract_globenewswire_releases(html: str, ticker: str) -> List[PressRelease]:
    """Extract press releases from GlobeNewswire search results."""
    releases = []
    # Simple pattern matching for GlobeNewswire result pages
    # Look for result links with dates
    pattern = re.compile(
        r'href="(/news-release/\d{4}/\d{2}/\d{2}/\d+/\d+/en/[^"]+)"[^>]*>' r"[^<]*<[^>]*>([^<]+)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        path, headline = match.groups()
        headline = headline.strip()
        if not headline or len(headline) < 10:
            continue
        url = urljoin("https://www.globenewswire.com", path)
        # Extract date from URL path
        date_match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", path)
        pub_date = ""
        if date_match:
            pub_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

        releases.append(
            PressRelease(
                ticker=ticker,
                headline=headline,
                published_at_utc=pub_date,
                source_url=url,
                source_type="globenewswire",
                fetched_at_utc=datetime.now(timezone.utc).isoformat(),
            )
        )
    return releases[:20]  # Cap at 20 most recent


def _extract_generic_ir_releases(html: str, ticker: str, base_url: str) -> List[PressRelease]:
    """Best-effort extraction from company IR pages.

    Handles multiple common IR platform patterns:
    1. Notified/GlobeNewswire IR: /news-releases/news-release-details/...
    2. Business Wire IR: /press-releases/press-release-details/...
    3. Generic link patterns with news/press/release in the path
    """
    releases = []
    seen_urls: set = set()
    now = datetime.now(timezone.utc).isoformat()

    # Pattern 1: Notified IR platform (most common for biotech)
    # Links like /news-releases/news-release-details/company-announces-something
    notified_pattern = re.compile(
        r'href="(/news-releases/news-release-details/[^"]+)"',
        re.IGNORECASE,
    )
    for match in notified_pattern.finditer(html):
        path = match.group(1)
        url = urljoin(base_url, path)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Extract headline from the slug
        slug = path.split("/")[-1]
        headline = slug.replace("-", " ").strip().title()

        # Try to find the actual headline text near this link
        # Look for text content after the link tag
        idx = match.end()
        text_match = re.search(r">([^<]{20,300})<", html[idx : idx + 500])
        if text_match:
            candidate = text_match.group(1).strip()
            # Filter out navigation text
            if len(candidate) > 20 and not candidate.startswith(("News", "Events", "SEC", "Stock")):
                headline = candidate

        # Try to extract date from nearby context
        pub_date = ""
        date_match = re.search(
            r"(\w+ \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})",
            html[max(0, match.start() - 200) : match.end() + 200],
        )
        if date_match:
            pub_date = date_match.group(1)

        releases.append(
            PressRelease(
                ticker=ticker,
                headline=headline,
                published_at_utc=pub_date,
                source_url=url,
                source_type="company_ir",
                fetched_at_utc=now,
            )
        )

    # Pattern 2: Business Wire / other platforms
    # Links with press-release-details or similar
    if not releases:
        bw_pattern = re.compile(
            r'href="([^"]*(?:press-release|news-release)[^"]*details[^"]*)"',
            re.IGNORECASE,
        )
        for match in bw_pattern.finditer(html):
            path = match.group(1)
            url = urljoin(base_url, path) if not path.startswith("http") else path
            if url in seen_urls:
                continue
            seen_urls.add(url)
            slug = path.split("/")[-1]
            headline = slug.replace("-", " ").strip().title()
            releases.append(
                PressRelease(
                    ticker=ticker,
                    headline=headline,
                    published_at_utc="",
                    source_url=url,
                    source_type="company_ir",
                    fetched_at_utc=now,
                )
            )

    # Pattern 3: Generic fallback
    if not releases:
        fallback_pattern = re.compile(
            r'href="([^"]*(?:news|press|release|announcement)[^"]*)"[^>]*>\s*([^<]{20,300})',
            re.IGNORECASE,
        )
        for match in fallback_pattern.finditer(html):
            path, headline = match.groups()
            headline = headline.strip()
            if not headline or headline.startswith(("News", "Events", "SEC", "Stock", "IR ")):
                continue
            url = urljoin(base_url, path) if not path.startswith("http") else path
            if url in seen_urls:
                continue
            seen_urls.add(url)
            releases.append(
                PressRelease(
                    ticker=ticker,
                    headline=headline,
                    published_at_utc="",
                    source_url=url,
                    source_type="company_ir",
                    fetched_at_utc=now,
                )
            )

    return releases[:20]


def fetch_ticker_releases(
    ticker: str,
    source: Dict[str, Any],
    state: Dict[str, Any],
) -> tuple[List[PressRelease], List[FetchResult]]:
    """Fetch press releases for one ticker from all configured sources."""
    releases: List[PressRelease] = []
    results: List[FetchResult] = []
    seen_hashes: set = set()

    # Track what we've already seen
    ticker_state = state.get(ticker, {})
    last_hashes = set(ticker_state.get("seen_hashes", []))

    # Source 1: Company IR page
    ir_url = source.get("company_ir_url", "")
    if ir_url:
        html = _fetch_url(ir_url)
        if html:
            prs = _extract_generic_ir_releases(html, ticker, ir_url)
            new_prs = [p for p in prs if p.compute_hash() not in last_hashes]
            releases.extend(new_prs)
            results.append(
                FetchResult(
                    ticker=ticker,
                    source_type="company_ir",
                    source_url=ir_url,
                    success=True,
                    releases_found=len(new_prs),
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        else:
            results.append(
                FetchResult(
                    ticker=ticker,
                    source_type="company_ir",
                    source_url=ir_url,
                    success=False,
                    error="fetch_failed",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        time.sleep(RATE_LIMIT_SECONDS)

    # Source 2: Backup sources (GlobeNewswire etc)
    for backup_url in source.get("backup_sources", []):
        html = _fetch_url(backup_url)
        if html:
            if "globenewswire" in backup_url.lower():
                prs = _extract_globenewswire_releases(html, ticker)
            else:
                prs = _extract_generic_ir_releases(html, ticker, backup_url)
            new_prs = [p for p in prs if p.compute_hash() not in last_hashes]
            releases.extend(new_prs)
            results.append(
                FetchResult(
                    ticker=ticker,
                    source_type="backup",
                    source_url=backup_url,
                    success=True,
                    releases_found=len(new_prs),
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        else:
            results.append(
                FetchResult(
                    ticker=ticker,
                    source_type="backup",
                    source_url=backup_url,
                    success=False,
                    error="fetch_failed",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        time.sleep(RATE_LIMIT_SECONDS)

    # Dedupe by content hash
    deduped = []
    for pr in releases:
        h = pr.compute_hash()
        if h not in seen_hashes:
            pr.content_hash = h
            deduped.append(pr)
            seen_hashes.add(h)

    return deduped, results


def run_health_check(sources: List[Dict[str, Any]]) -> None:
    """Check source coverage and staleness."""
    state = _load_state()
    total = len(sources)
    has_ir = sum(1 for s in sources if s.get("company_ir_url"))
    has_backup = sum(1 for s in sources if s.get("backup_sources"))

    print(f"Source Health Check — {total} tickers")
    print(f"  With IR URL: {has_ir}/{total} ({has_ir/total*100:.0f}%)")
    print(f"  With backup: {has_backup}/{total} ({has_backup/total*100:.0f}%)")
    print()

    stale = []
    for s in sources:
        t = s["ticker"]
        ts = state.get(t, {})
        last_fetch = ts.get("last_fetch_utc", "never")
        n_seen = len(ts.get("seen_hashes", []))
        if last_fetch == "never":
            stale.append((t, "never fetched"))
        print(
            f"  {t:<8} last_fetch={last_fetch[:10] if last_fetch != 'never' else 'never':>12} releases_seen={n_seen:>3}"
        )

    if stale:
        print(f"\n  WARNING: {len(stale)} tickers never fetched")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Company press release fetcher (Spec 044)")
    parser.add_argument("--as-of-date", default="", help="Date label for output")
    parser.add_argument("--ticker", default="", help="Fetch single ticker only")
    parser.add_argument("--health-check", action="store_true", help="Source health report only")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sources = _load_sources()
    if not sources:
        print("No sources configured")
        return 1

    if args.health_check:
        run_health_check(sources)
        return 0

    if args.ticker:
        sources = [s for s in sources if s["ticker"].upper() == args.ticker.upper()]

    state = _load_state()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_releases: List[PressRelease] = []
    all_results: List[FetchResult] = []

    for source in sources:
        ticker = source["ticker"]
        logger.info("Fetching %s...", ticker)
        releases, results = fetch_ticker_releases(ticker, source, state)
        all_releases.extend(releases)
        all_results.extend(results)

        # Update state
        ticker_state = state.get(ticker, {"seen_hashes": []})
        ticker_state["last_fetch_utc"] = datetime.now(timezone.utc).isoformat()
        if releases:
            ticker_state["last_release_date"] = max(
                r.published_at_utc for r in releases if r.published_at_utc
            ) or ticker_state.get("last_release_date", "")
        new_hashes = [r.content_hash for r in releases]
        existing = set(ticker_state.get("seen_hashes", []))
        ticker_state["seen_hashes"] = list(existing | set(new_hashes))[-200:]  # keep last 200
        state[ticker] = ticker_state

    # Write results
    if not args.dry_run:
        date_label = args.as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_path = OUTPUT_DIR / f"releases_{date_label}.jsonl"
        with open(out_path, "a") as f:
            for pr in all_releases:
                f.write(json.dumps(pr.to_dict(), default=str) + "\n")
        _save_state(state)
        logger.info("Wrote %d releases to %s", len(all_releases), out_path.name)

    # Summary
    success = sum(1 for r in all_results if r.success)
    failed = sum(1 for r in all_results if not r.success)
    print(f"\nPR Fetch: {len(all_releases)} new releases from {len(sources)} tickers")
    print(f"  Sources polled: {len(all_results)} ({success} ok, {failed} failed)")

    # Write health artifact
    if not args.dry_run:
        health = {
            "schema": "herald_health.v1",
            "as_of_date": date_label,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tickers_attempted": len(sources),
            "sources_polled": len(all_results),
            "sources_succeeded": success,
            "sources_failed": failed,
            "new_releases": len(all_releases),
            "direct_ir_hits": sum(1 for r in all_results if r.success and r.source_type == "company_ir"),
            "backup_hits": sum(1 for r in all_results if r.success and r.source_type == "backup"),
            "failures": [
                {"ticker": r.ticker, "source_type": r.source_type, "url": r.source_url, "error": r.error}
                for r in all_results
                if not r.success
            ],
            "stale_tickers": [
                t
                for t, ts in state.items()
                if isinstance(ts, dict)
                and ts.get("last_fetch_utc", "never") != "never"
                and len(ts.get("seen_hashes", [])) == 0
            ],
        }
        health_path = OUTPUT_DIR / f"health_{date_label}.json"
        with open(health_path, "w") as f:
            json.dump(health, f, indent=2, default=str)
            f.write("\n")
        logger.info("Health artifact → %s", health_path.name)

    return 0


if __name__ == "__main__":
    sys.exit(main())
