"""
openfda_drugs_collector.py - openFDA Drugs@FDA Collector

Fetches FDA approval data from the openFDA Drugs@FDA API to identify
upcoming PDUFA dates, recent approvals, CRLs, and regulatory milestones.

Source: https://api.fda.gov/drug/drugsfda.json (free, structured, no auth)
Rate limiting: openFDA allows 240 req/min without API key, 120K/day with key
Cache: results cached per as_of_date
"""

import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from common.robustness import create_resilient_session

logger = logging.getLogger(__name__)

OPENFDA_URL = "https://api.fda.gov/drug/drugsfda.json"

# Rate limit: 4 req/sec (conservative, well under 240/min)
_MIN_INTERVAL = 0.25

# Cache directory (relative to project root)
DEFAULT_CACHE_DIR = Path("data") / "caches" / "openfda"

# Submission status codes that indicate regulatory events
_APPROVAL_STATUSES = {"AP"}  # Approved
_CRL_STATUSES = {"TA"}  # Tentative approval (often maps to CRL context)
_WITHDRAWAL_STATUSES = {"WD"}  # Withdrawn


def _normalize_sponsor(name: str) -> str:
    """Normalize sponsor name for matching."""
    name = name.lower().strip()
    # Remove common suffixes
    for suffix in (
        ", inc.",
        ", inc",
        " inc.",
        " inc",
        ", llc",
        " llc",
        ", ltd",
        " ltd",
        " ltd.",
        ", corp",
        " corp",
        " corp.",
        " incorporated",
        " corporation",
        " company",
        ", plc",
        " plc",
        " pharmaceuticals",
        " pharmaceutical",
        " therapeutics",
        " biosciences",
        " biotech",
        " biotechnology",
        " sciences",
        " holdings",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def build_sponsor_ticker_map(data_dir: Path) -> Dict[str, str]:
    """Build sponsor_name → ticker map from universe.json company names.

    Returns {normalized_sponsor: ticker}.
    """
    universe_path = data_dir / "universe.json"
    if not universe_path.exists():
        logger.warning("universe.json not found at %s", universe_path)
        return {}

    with open(universe_path, "r", encoding="utf-8") as f:
        universe = json.load(f)

    sponsor_map: Dict[str, str] = {}
    for entry in universe:
        ticker = entry.get("ticker", "")
        if not ticker:
            continue

        # Try company_name from market_data
        company = (entry.get("market_data") or {}).get("company_name", "")
        if company:
            norm = _normalize_sponsor(company)
            if norm and len(norm) >= 3:
                sponsor_map[norm] = ticker

        # Also try the top-level name
        name = entry.get("name", "")
        if name and name != ticker:
            norm = _normalize_sponsor(name)
            if norm and len(norm) >= 3:
                sponsor_map[norm] = ticker

    logger.info("Built sponsor→ticker map: %d entries", len(sponsor_map))
    return sponsor_map


def _match_sponsor_to_ticker(
    sponsor: str,
    sponsor_map: Dict[str, str],
) -> Optional[str]:
    """Try to match an openFDA sponsor name to a ticker.

    Uses exact match first, then substring matching.
    """
    norm = _normalize_sponsor(sponsor)
    if not norm:
        return None

    # Exact match
    if norm in sponsor_map:
        return sponsor_map[norm]

    # Substring: sponsor contains ticker's company name or vice versa
    for company, ticker in sponsor_map.items():
        if len(company) >= 5 and company in norm:
            return ticker
        if len(norm) >= 5 and norm in company:
            return ticker

    return None


def collect_openfda_approvals(
    data_dir: Path,
    as_of_date: date,
    lookback_days: int = 365,
    sponsor_map: Optional[Dict[str, str]] = None,
    cache_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Collect FDA approval/action data from openFDA Drugs@FDA API.

    Searches for recent submissions (approvals, CRLs) from sponsors
    matching our universe tickers.

    Returns list of event dicts with keys:
        ticker, event_type, event_date, drug_name, application_number,
        sponsor_name, submission_type, source, confidence
    """
    if cache_dir is None:
        cache_dir = DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_file = cache_dir / f"openfda_{as_of_date.isoformat()}.json"
    if cache_file.exists():
        logger.info("openFDA cache hit: %s", cache_file)
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    if sponsor_map is None:
        sponsor_map = build_sponsor_ticker_map(data_dir)

    session = create_resilient_session(timeout=30)

    start_date = as_of_date - timedelta(days=lookback_days)
    # openFDA date format: YYYYMMDD
    date_range = f"[{start_date.strftime('%Y%m%d')}+TO+{as_of_date.strftime('%Y%m%d')}]"

    events: List[Dict[str, Any]] = []
    skip = 0
    limit = 100
    total_fetched = 0
    max_results = 1000

    while total_fetched < max_results:
        search = f"submissions.submission_status_date:{date_range}"
        url = f"{OPENFDA_URL}?search={search}&limit={limit}&skip={skip}"

        try:
            resp = session.get(url)
            time.sleep(_MIN_INTERVAL)

            if resp.status_code == 404:
                logger.debug("openFDA: no more results at skip=%d", skip)
                break
            resp.raise_for_status()

            data = resp.json()
            results = data.get("results", [])
            if not results:
                break

            for drug in results:
                sponsor = drug.get("sponsor_name", "")
                ticker = _match_sponsor_to_ticker(sponsor, sponsor_map)
                if not ticker:
                    continue

                app_no = drug.get("application_number", "")
                products = drug.get("products", [])
                drug_name = products[0].get("brand_name", "") if products else ""

                for sub in drug.get("submissions", []):
                    sub_date_str = sub.get("submission_status_date", "")
                    sub_status = sub.get("submission_status", "")
                    sub_type = sub.get("submission_type", "")
                    sub_class_code = sub.get("submission_class_code", "")

                    if not sub_date_str:
                        continue

                    # Parse date (YYYYMMDD format)
                    try:
                        sub_date = datetime.strptime(sub_date_str, "%Y%m%d").date()
                    except ValueError:
                        continue

                    # Only include events in our date window
                    if sub_date < start_date or sub_date > as_of_date:
                        continue

                    # Classify event type
                    if sub_status in _APPROVAL_STATUSES:
                        event_type = "FDA_APPROVAL"
                        confidence = "HIGH"
                    elif sub_status in _WITHDRAWAL_STATUSES:
                        event_type = "FDA_CRL"
                        confidence = "MED"
                    else:
                        continue  # Skip other statuses

                    events.append(
                        {
                            "ticker": ticker,
                            "event_type": event_type,
                            "event_date": sub_date.isoformat(),
                            "drug_name": drug_name,
                            "application_number": app_no,
                            "sponsor_name": sponsor,
                            "submission_type": sub_type,
                            "submission_class_code": sub_class_code,
                            "source": "OPENFDA_DRUGS",
                            "confidence": confidence,
                        }
                    )

            total_fetched += len(results)
            skip += limit

            if len(results) < limit:
                break

        except Exception as e:
            logger.warning("openFDA request failed at skip=%d: %s", skip, e)
            break

    logger.info(
        "openFDA: fetched %d results, matched %d events to %d tickers",
        total_fetched,
        len(events),
        len(set(e["ticker"] for e in events)),
    )

    # Deduplicate by (ticker, event_type, event_date)
    seen: Set[Tuple[str, str, str]] = set()
    deduped = []
    for ev in events:
        key = (ev["ticker"], ev["event_type"], ev["event_date"])
        if key not in seen:
            seen.add(key)
            deduped.append(ev)
    events = deduped

    # Cache
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, default=str)
        f.write("\n")

    return events
