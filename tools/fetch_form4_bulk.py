#!/usr/bin/env python3
"""Bulk Form 4 fetcher using SEC EDGAR quarterly index files.

Much faster than per-ticker API: downloads ~24 quarterly index files,
filters to universe CIKs, then batch-fetches only matching XML filings.

Output: same as fetch_form4_insider.py (data/form4/raw/{TICKER}.json + panel CSV)

Usage:
    python3 tools/fetch_form4_bulk.py
    python3 tools/fetch_form4_bulk.py --since 2023-01-01
    python3 tools/fetch_form4_bulk.py --workers 4
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.fetch_form4_insider import InsiderTransaction, build_panel, parse_form4_xml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

USER_AGENT = "Wake Robin Capital Management institutional.validation@wakerobincapital.com"
ARCHIVES_BASE = "https://www.sec.gov/Archives"
REQUEST_DELAY = 0.12
RAW_DIR = PROJECT_ROOT / "data" / "form4" / "raw"
PANEL_CSV = PROJECT_ROOT / "data" / "form4" / "form4_panel.csv"
STATE_FILE = PROJECT_ROOT / "data" / "form4" / "fetch_state.json"

# Rate limiter: shared across threads
_last_request_time = 0.0
import threading

_rate_lock = threading.Lock()


def _fetch_url(url: str) -> bytes:
    global _last_request_time
    with _rate_lock:
        elapsed = time.time() - _last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        _last_request_time = time.time()

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            log.warning("Rate limited, sleeping 10s...")
            time.sleep(10)
            return _fetch_url(url)
        raise


# ---------------------------------------------------------------------------
# Step 1: Download quarterly index files
# ---------------------------------------------------------------------------


def get_quarters(since: str) -> List[Tuple[int, int]]:
    """Generate (year, qtr) tuples from since date to now."""
    since_date = datetime.strptime(since, "%Y-%m-%d").date()
    start_year = since_date.year
    start_qtr = (since_date.month - 1) // 3 + 1

    today = date.today()
    end_year = today.year
    end_qtr = (today.month - 1) // 3 + 1

    quarters = []
    for year in range(start_year, end_year + 1):
        for qtr in range(1, 5):
            if (year, qtr) < (start_year, start_qtr):
                continue
            if (year, qtr) > (end_year, end_qtr):
                break
            quarters.append((year, qtr))
    return quarters


def download_index(year: int, qtr: int) -> List[Tuple[str, str, str]]:
    """Download master.idx for a quarter, return list of (cik, filing_date, path) for Form 4."""
    url = f"{ARCHIVES_BASE}/edgar/full-index/{year}/QTR{qtr}/master.idx"
    try:
        content = _fetch_url(url).decode("latin-1")
    except Exception as e:
        log.warning(f"Failed to download {year}/QTR{qtr}: {e}")
        return []

    results = []
    for line in content.split("\n"):
        parts = line.split("|")
        if len(parts) >= 5 and parts[2].strip() in ("4", "4/A"):
            cik = parts[0].strip()
            filing_date = parts[3].strip()
            path = parts[4].strip()
            results.append((cik, filing_date, path))

    return results


# ---------------------------------------------------------------------------
# Step 2: Filter to universe CIKs
# ---------------------------------------------------------------------------


def load_universe_ciks() -> Dict[str, str]:
    """Return {cik_stripped: ticker} mapping."""
    universe = json.loads((PROJECT_ROOT / "production_data" / "universe.json").read_text())
    cik_to_ticker = {}
    for entry in universe:
        ticker = entry["ticker"]
        cik = entry.get("cik") or entry.get("financial_data", {}).get("cik", "")
        if cik:
            cik_to_ticker[cik.lstrip("0")] = ticker
    return cik_to_ticker


# ---------------------------------------------------------------------------
# Step 3: Fetch and parse XML filings
# ---------------------------------------------------------------------------


def fetch_and_parse_filing(
    ticker: str,
    cik: str,
    filing_date: str,
    index_path: str,
) -> List[InsiderTransaction]:
    """Fetch the XML for one filing and parse it."""
    # index_path like: edgar/data/1234567/0001234567-25-000001.txt
    # We need the directory, then find ownership.xml
    dir_path = index_path.rsplit("/", 1)[0]
    _ = index_path.rsplit("/", 1)[-1].replace(".txt", "").replace("-", "")

    # Try ownership.xml first (most common)
    xml_url = f"{ARCHIVES_BASE}/{dir_path}/ownership.xml"
    try:
        xml_bytes = _fetch_url(xml_url)
        if xml_bytes[:50].lstrip().startswith(b"<!") or b"<html" in xml_bytes[:200].lower():
            xml_bytes = None
    except Exception:
        xml_bytes = None

    # Fallback: try index.json to find XML
    if xml_bytes is None:
        try:
            index_json = json.loads(_fetch_url(f"{ARCHIVES_BASE}/{dir_path}/index.json"))
            for item in index_json.get("directory", {}).get("item", []):
                name = item.get("name", "")
                if name.endswith(".xml") and "xsl" not in name.lower() and "R" not in name:
                    xml_bytes = _fetch_url(f"{ARCHIVES_BASE}/{dir_path}/{name}")
                    break
        except Exception:
            pass

    if xml_bytes is None:
        return []

    accession = index_path.rsplit("/", 1)[-1].replace(".txt", "")
    return parse_form4_xml(xml_bytes, ticker, cik, filing_date, accession)


def fetch_ticker_filings(
    ticker: str,
    filings: List[Tuple[str, str, str]],
    workers: int = 1,
) -> List[InsiderTransaction]:
    """Fetch all filings for one ticker."""
    all_txns = []

    for cik, filing_date, path in filings:
        try:
            txns = fetch_and_parse_filing(ticker, cik, filing_date, path)
            all_txns.extend(txns)
        except Exception as e:
            log.debug(f"  Failed {path}: {e}")

    return all_txns


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Bulk Form 4 fetch via EDGAR quarterly indexes")
    parser.add_argument("--since", default="2020-01-01", help="Earliest filing date")
    parser.add_argument("--workers", type=int, default=1, help="Parallel ticker workers (rate limit shared)")
    parser.add_argument("--panel-only", action="store_true", help="Skip fetch, rebuild panel only")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if args.panel_only:
        n = build_panel(RAW_DIR, PANEL_CSV)
        log.info(f"Panel rebuilt: {n} rows")
        return

    # Step 1: Load universe CIKs
    cik_to_ticker = load_universe_ciks()
    log.info(f"Universe: {len(cik_to_ticker)} tickers with CIKs")

    # Step 2: Download quarterly indexes
    quarters = get_quarters(args.since)
    log.info(f"Downloading {len(quarters)} quarterly indexes ({quarters[0]} to {quarters[-1]})")

    # Group filings by ticker
    ticker_filings: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    total_form4 = 0

    for year, qtr in quarters:
        entries = download_index(year, qtr)
        matched = 0
        for cik, filing_date, path in entries:
            ticker = cik_to_ticker.get(cik)
            if ticker and filing_date >= args.since:
                ticker_filings[ticker].append((cik, filing_date, path))
                matched += 1
        total_form4 += matched
        log.info(f"  {year}/QTR{qtr}: {len(entries)} Form 4 total, {matched} matched universe")

    log.info(f"Total matched filings: {total_form4} across {len(ticker_filings)} tickers")

    # Step 3: Fetch XML for each ticker
    fetched = 0
    skipped = 0

    for i, (ticker, filings) in enumerate(sorted(ticker_filings.items())):
        # Skip if already fetched today
        raw_file = RAW_DIR / f"{ticker}.json"
        if raw_file.exists():
            mtime = datetime.fromtimestamp(raw_file.stat().st_mtime)
            if mtime.date() == date.today():
                skipped += 1
                continue

        txns = fetch_ticker_filings(ticker, filings)
        raw_file.write_text(json.dumps([asdict(t) for t in txns], indent=1))
        fetched += 1

        if (fetched) % 25 == 0:
            log.info(
                f"  Progress: {fetched} fetched, {skipped} skipped, {len(ticker_filings) - fetched - skipped} remaining"
            )

    log.info(f"Fetched {fetched} tickers ({skipped} skipped), {total_form4} filings")

    # Step 4: Build panel
    n = build_panel(RAW_DIR, PANEL_CSV)

    # Save state
    STATE_FILE.write_text(
        json.dumps(
            {
                "last_fetch": datetime.now(timezone.utc).isoformat(),
                "method": "bulk_index",
                "tickers_fetched": fetched,
                "tickers_skipped": skipped,
                "total_filings_matched": total_form4,
                "since": args.since,
                "quarters": len(quarters),
            },
            indent=2,
        )
    )

    log.info(f"Done. Panel: {n} rows.")


if __name__ == "__main__":
    main()
