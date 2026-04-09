#!/usr/bin/env python3
"""Fetch Form 4 insider transaction data from SEC EDGAR.

Downloads and parses Form 4 XML filings for all tickers in the universe.
Uses EDGAR acceptance timestamp (not transaction date) as the PIT-safe signal date.

Output:
    data/form4/raw/{TICKER}.json         — raw parsed transactions per ticker
    data/form4/form4_panel.csv           — flat panel for research harness
    data/form4/fetch_state.json          — last-fetched metadata

Usage:
    python3 tools/fetch_form4_insider.py
    python3 tools/fetch_form4_insider.py --tickers RVMD KURA
    python3 tools/fetch_form4_insider.py --since 2020-01-01
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# EDGAR config
USER_AGENT = "Wake Robin Capital Management institutional.validation@wakerobincapital.com"
EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
REQUEST_DELAY = 0.11  # ~9 req/s, under SEC 10/s limit
MAX_WORKERS = 8  # concurrent ticker fetches

# Global rate limiter: ensures total requests across all threads stay under SEC limit
_rate_lock = threading.Lock()
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.11  # ~9 req/s max across all threads (under SEC 10/s limit)

RAW_DIR = PROJECT_ROOT / "data" / "form4" / "raw"
PANEL_CSV = PROJECT_ROOT / "data" / "form4" / "form4_panel.csv"
STATE_FILE = PROJECT_ROOT / "data" / "form4" / "fetch_state.json"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class InsiderTransaction:
    """A single insider transaction from Form 4."""

    ticker: str
    cik: str  # issuer CIK
    filer_cik: str  # reporting person CIK
    filer_name: str
    filing_date: str  # EDGAR acceptance date (PIT-safe)
    transaction_date: str  # actual transaction date (NOT used for signal timing)
    form_type: str  # "4", "4/A"
    accession_number: str

    # Transaction details
    is_director: bool = False
    is_officer: bool = False
    officer_title: str = ""
    is_ten_pct_owner: bool = False

    # Securities
    security_title: str = ""
    transaction_code: str = ""  # P=purchase, S=sale, A=award, M=exercise, etc.
    shares: float = 0.0
    price_per_share: float = 0.0
    value: float = 0.0  # shares * price
    acquired_disposed: str = ""  # A=acquired, D=disposed
    shares_owned_after: float = 0.0
    direct_indirect: str = ""  # D=direct, I=indirect

    # Derived
    is_buy: bool = False
    is_sell: bool = False
    is_derivative: bool = False


# ---------------------------------------------------------------------------
# EDGAR API helpers
# ---------------------------------------------------------------------------


def _fetch_url(url: str) -> bytes:
    """Fetch URL with global rate limiting and SEC-compliant headers."""
    global _last_request_time
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # Global rate limiter: serialize the timing check across threads
    with _rate_lock:
        now = time.monotonic()
        wait = _MIN_REQUEST_INTERVAL - (now - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            log.warning("Rate limited, sleeping 10s...")
            time.sleep(10)
            return _fetch_url(url)
        raise


def _fetch_json(url: str) -> Any:
    return json.loads(_fetch_url(url))


def get_form4_filings(cik: str, since: str = "2020-01-01") -> List[Dict[str, Any]]:
    """Get Form 4 filing metadata for a CIK from EDGAR submissions API."""
    cik_padded = cik.lstrip("0").zfill(10)
    url = f"{SUBMISSIONS_BASE}/CIK{cik_padded}.json"

    try:
        data = _fetch_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.debug(f"CIK {cik} not found in EDGAR")
            return []
        raise

    filings = []
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    for i, form in enumerate(forms):
        if form not in ("4", "4/A"):
            continue
        filing_date = dates[i] if i < len(dates) else ""
        if filing_date < since:
            continue
        filings.append(
            {
                "form": form,
                "filingDate": filing_date,
                "accessionNumber": accessions[i] if i < len(accessions) else "",
                "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
            }
        )

    return filings


def parse_form4_xml(
    xml_bytes: bytes, ticker: str, cik: str, filing_date: str, accession: str
) -> List[InsiderTransaction]:
    """Parse a Form 4 XML document into transactions."""
    txns = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        log.warning(f"XML parse error for {ticker} {accession}")
        return []

    # Namespace handling — Form 4 XML can have various namespace prefixes
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    # Reporting person info
    rp = root.find(f".//{ns}reportingOwner")
    filer_cik = ""
    filer_name = ""
    is_director = False
    is_officer = False
    officer_title = ""
    is_ten_pct = False

    if rp is not None:
        rid = rp.find(f"{ns}reportingOwnerId")
        if rid is not None:
            filer_cik = (rid.findtext(f"{ns}rptOwnerCik") or "").strip()
            filer_name = (rid.findtext(f"{ns}rptOwnerName") or "").strip()

        rel = rp.find(f"{ns}reportingOwnerRelationship")
        if rel is not None:
            is_director = (rel.findtext(f"{ns}isDirector") or "").strip().lower() in ("1", "true")
            is_officer = (rel.findtext(f"{ns}isOfficer") or "").strip().lower() in ("1", "true")
            officer_title = (rel.findtext(f"{ns}officerTitle") or "").strip()
            is_ten_pct = (rel.findtext(f"{ns}isTenPercentOwner") or "").strip().lower() in ("1", "true")

    # Non-derivative transactions
    for txn_el in root.findall(f".//{ns}nonDerivativeTransaction"):
        txn = _parse_transaction_element(
            txn_el,
            ns,
            ticker,
            cik,
            filer_cik,
            filer_name,
            filing_date,
            accession,
            is_director,
            is_officer,
            officer_title,
            is_ten_pct,
            is_derivative=False,
        )
        if txn:
            txns.append(txn)

    # Derivative transactions
    for txn_el in root.findall(f".//{ns}derivativeTransaction"):
        txn = _parse_transaction_element(
            txn_el,
            ns,
            ticker,
            cik,
            filer_cik,
            filer_name,
            filing_date,
            accession,
            is_director,
            is_officer,
            officer_title,
            is_ten_pct,
            is_derivative=True,
        )
        if txn:
            txns.append(txn)

    return txns


def _parse_transaction_element(
    el,
    ns: str,
    ticker: str,
    cik: str,
    filer_cik: str,
    filer_name: str,
    filing_date: str,
    accession: str,
    is_director: bool,
    is_officer: bool,
    officer_title: str,
    is_ten_pct: bool,
    is_derivative: bool,
) -> Optional[InsiderTransaction]:
    """Parse a single transaction element."""
    sec_title = (el.findtext(f".//{ns}securityTitle/{ns}value") or "").strip()

    # Transaction coding (contains transactionCode)
    coding = el.find(f"{ns}transactionCoding")
    code_el = ""
    if coding is not None:
        code_el = (coding.findtext(f"{ns}transactionCode") or "").strip()

    # Transaction amounts
    amounts = el.find(f"{ns}transactionAmounts")
    if amounts is None:
        return None

    shares_str = amounts.findtext(f"{ns}transactionShares/{ns}value") or "0"
    price_str = amounts.findtext(f"{ns}transactionPricePerShare/{ns}value") or "0"
    ad = (amounts.findtext(f"{ns}transactionAcquiredDisposedCode/{ns}value") or "").strip()

    # Transaction date
    txn_date = (el.findtext(f".//{ns}transactionDate/{ns}value") or "").strip()

    # Post-transaction ownership
    ownership = el.find(f"{ns}postTransactionAmounts")
    shares_after = 0.0
    if ownership is not None:
        shares_after_str = ownership.findtext(f"{ns}sharesOwnedFollowingTransaction/{ns}value") or "0"
        try:
            shares_after = float(shares_after_str)
        except ValueError:
            pass

    # Ownership nature
    own_nature = el.find(f"{ns}ownershipNature")
    di = ""
    if own_nature is not None:
        di = (own_nature.findtext(f"{ns}directOrIndirectOwnership/{ns}value") or "").strip()

    try:
        shares = float(shares_str)
    except ValueError:
        shares = 0.0
    try:
        price = float(price_str)
    except ValueError:
        price = 0.0

    value = shares * price
    is_buy = code_el in ("P",) and ad == "A"  # Open market purchase
    is_sell = code_el in ("S",) and ad == "D"  # Open market sale

    return InsiderTransaction(
        ticker=ticker,
        cik=cik,
        filer_cik=filer_cik,
        filer_name=filer_name,
        filing_date=filing_date,
        transaction_date=txn_date,
        form_type="4",
        accession_number=accession,
        is_director=is_director,
        is_officer=is_officer,
        officer_title=officer_title,
        is_ten_pct_owner=is_ten_pct,
        security_title=sec_title,
        transaction_code=code_el,
        shares=shares,
        price_per_share=price,
        value=value,
        acquired_disposed=ad,
        shares_owned_after=shares_after,
        direct_indirect=di,
        is_buy=is_buy,
        is_sell=is_sell,
        is_derivative=is_derivative,
    )


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------

EXEC_TITLES = {
    "ceo",
    "cfo",
    "coo",
    "president",
    "chief executive",
    "chief financial",
    "chief operating",
    "chief medical",
    "chief scientific",
}


def is_executive(title: str) -> bool:
    """Check if officer title indicates C-suite/president."""
    t = title.lower()
    return any(ex in t for ex in EXEC_TITLES)


def compute_insider_features(
    txns: List[InsiderTransaction],
    as_of_date: str,
    windows: tuple[int, ...] = (30, 60, 90),
) -> Dict[str, Any]:
    """Compute insider signal features as of a date using filing_date (PIT-safe).

    Only considers transactions where filing_date <= as_of_date.
    """
    from datetime import datetime as dt

    as_of = dt.strptime(as_of_date, "%Y-%m-%d").date()
    features: Dict[str, Any] = {}

    for window in windows:
        cutoff = as_of - __import__("datetime").timedelta(days=window)
        window_txns = [
            t for t in txns if t.filing_date and cutoff <= dt.strptime(t.filing_date, "%Y-%m-%d").date() <= as_of
        ]

        buys = [t for t in window_txns if t.is_buy and not t.is_derivative]
        sells = [t for t in window_txns if t.is_sell and not t.is_derivative]

        buy_value = sum(t.value for t in buys)
        sell_value = sum(t.value for t in sells)
        buy_shares = sum(t.shares for t in buys)
        sell_shares = sum(t.shares for t in sells)

        # Unique buyers/sellers
        buyers = {t.filer_cik for t in buys}
        sellers = {t.filer_cik for t in sells}

        # Executive buys
        exec_buys = [t for t in buys if t.is_officer and is_executive(t.officer_title)]

        sfx = f"_{window}d"
        features[f"insider_net_buy_value{sfx}"] = buy_value - sell_value
        features[f"insider_buy_value{sfx}"] = buy_value
        features[f"insider_sell_value{sfx}"] = sell_value
        features[f"insider_net_buy_shares{sfx}"] = buy_shares - sell_shares
        features[f"insider_buy_count{sfx}"] = len(buys)
        features[f"insider_sell_count{sfx}"] = len(sells)
        features[f"insider_net_buyer_flag{sfx}"] = 1 if buy_value > sell_value else 0
        features[f"insider_buying_by_exec_flag{sfx}"] = 1 if exec_buys else 0
        features[f"insider_cluster_buy_flag{sfx}"] = 1 if len(buyers) >= 2 else 0
        features[f"insider_unique_buyers{sfx}"] = len(buyers)
        features[f"insider_unique_sellers{sfx}"] = len(sellers)
        features[f"insider_exec_buy_value{sfx}"] = sum(t.value for t in exec_buys)

    return features


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def _find_raw_xml_url(cik: str, acc_path: str) -> Optional[str]:
    """Find the raw ownership XML URL from the filing index."""
    cik_clean = cik.lstrip("0")
    index_url = f"{ARCHIVES_BASE}/{cik_clean}/{acc_path}/index.json"
    try:
        data = _fetch_json(index_url)
    except Exception:
        return None

    for item in data.get("directory", {}).get("item", []):
        name = item.get("name", "")
        # Raw XML files: ownership.xml, doc4.xml, primary_doc.xml, etc.
        if name.endswith(".xml") and "xsl" not in name.lower() and "R" not in name:
            return f"{ARCHIVES_BASE}/{cik_clean}/{acc_path}/{name}"
    return None


def fetch_ticker(ticker: str, cik: str, since: str) -> List[InsiderTransaction]:
    """Fetch and parse all Form 4 filings for a ticker."""
    filings = get_form4_filings(cik, since=since)
    log.info(f"  {ticker} (CIK {cik}): {len(filings)} Form 4 filings since {since}")

    all_txns = []
    for f in filings:
        acc = f["accessionNumber"]
        acc_path = acc.replace("-", "")
        primary = f.get("primaryDocument", "")

        # Try direct raw XML first (strip XSL prefix if present)
        cik_clean = cik.lstrip("0")
        if "/" in primary:
            # e.g. "xslF345X06/ownership.xml" -> try "ownership.xml" directly
            base_name = primary.split("/")[-1]
            url = f"{ARCHIVES_BASE}/{cik_clean}/{acc_path}/{base_name}"
        elif primary:
            url = f"{ARCHIVES_BASE}/{cik_clean}/{acc_path}/{primary}"
        else:
            url = None

        xml_bytes = None
        if url:
            try:
                xml_bytes = _fetch_url(url)
                # Verify it's actual XML, not HTML
                if xml_bytes[:50].lstrip().startswith(b"<!") or b"<html" in xml_bytes[:200].lower():
                    xml_bytes = None  # HTML, need to find raw XML
            except Exception:
                xml_bytes = None

        # Fallback: look up filing index for raw XML
        if xml_bytes is None:
            raw_url = _find_raw_xml_url(cik, acc_path)
            if raw_url:
                try:
                    xml_bytes = _fetch_url(raw_url)
                except Exception as e:
                    log.warning(f"    Failed to fetch {acc}: {e}")
                    continue
            else:
                log.debug(f"    No raw XML found for {acc}")
                continue

        txns = parse_form4_xml(xml_bytes, ticker, cik, f["filingDate"], acc)
        all_txns.extend(txns)

    return all_txns


def build_panel(raw_dir: Path, panel_path: Path) -> int:
    """Build flat CSV panel from raw JSON files."""
    import csv

    rows = []
    for jf in sorted(raw_dir.glob("*.json")):
        ticker = jf.stem
        data = json.loads(jf.read_text())
        txns = [InsiderTransaction(**t) for t in data]

        # Compute features at each unique filing date
        filing_dates = sorted({t.filing_date for t in txns if t.filing_date})
        for fd in filing_dates:
            feats = compute_insider_features(txns, fd)
            feats["ticker"] = ticker
            feats["as_of_date"] = fd
            rows.append(feats)

    if not rows:
        log.warning("No data for panel")
        return 0

    # Write CSV
    all_keys = sorted({k for r in rows for k in r.keys()})
    # Ensure ticker and as_of_date are first
    cols = ["ticker", "as_of_date"] + [k for k in all_keys if k not in ("ticker", "as_of_date")]
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    with open(panel_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["ticker"], x["as_of_date"])):
            w.writerow(r)

    log.info(f"Panel: {len(rows)} rows, {len(cols)} columns -> {panel_path}")
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Fetch Form 4 insider data from SEC EDGAR")
    parser.add_argument("--tickers", nargs="*", help="Specific tickers (default: all universe)")
    parser.add_argument("--since", default="2020-01-01", help="Earliest filing date")
    parser.add_argument("--panel-only", action="store_true", help="Skip fetch, just rebuild panel")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if not args.panel_only:
        # Load universe
        universe = json.loads((PROJECT_ROOT / "production_data" / "universe.json").read_text())
        tickers = {}
        for entry in universe:
            t = entry["ticker"]
            cik = entry.get("cik") or entry.get("financial_data", {}).get("cik", "")
            if cik and (not args.tickers or t in args.tickers):
                tickers[t] = cik.lstrip("0")

        # Filter out already-fetched tickers (skip if file exists and not explicit --tickers)
        to_fetch = {}
        skipped = 0
        for t, cik in sorted(tickers.items()):
            raw_file = RAW_DIR / f"{t}.json"
            if raw_file.exists() and not args.tickers:
                skipped += 1
                continue
            to_fetch[t] = cik

        log.info(
            f"Fetching Form 4 for {len(to_fetch)} tickers since {args.since} "
            f"(skipping {skipped} already fetched, {MAX_WORKERS} workers)"
        )

        fetched = 0
        failed = 0
        total_txns = 0
        _counter_lock = threading.Lock()

        def _fetch_one(ticker_cik):
            nonlocal fetched, failed, total_txns
            ticker, cik = ticker_cik
            try:
                txns = fetch_ticker(ticker, cik, args.since)
                raw_file = RAW_DIR / f"{ticker}.json"
                raw_file.write_text(json.dumps([asdict(t) for t in txns], indent=1))
                with _counter_lock:
                    fetched += 1
                    total_txns += len(txns)
                    if fetched % 25 == 0:
                        log.info(f"  Progress: {fetched}/{len(to_fetch)} tickers, {total_txns} txns")
                return ticker, len(txns), None
            except Exception as e:
                with _counter_lock:
                    failed += 1
                log.error(f"  {ticker}: {e}")
                return ticker, 0, str(e)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(_fetch_one, (t, c)) for t, c in to_fetch.items()]
            for f in as_completed(futures):
                f.result()  # propagate exceptions

        log.info(f"Fetched {fetched} tickers ({failed} failed), {total_txns} total transactions")

        # Save state
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(
                {
                    "last_fetch": datetime.now(timezone.utc).isoformat(),
                    "tickers_fetched": fetched,
                    "total_transactions": total_txns,
                    "since": args.since,
                },
                indent=2,
            )
        )

    # Build panel
    n = build_panel(RAW_DIR, PANEL_CSV)
    log.info(f"Done. Panel has {n} rows.")


if __name__ == "__main__":
    main()
