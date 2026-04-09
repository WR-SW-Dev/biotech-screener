#!/usr/bin/env python3
"""Build historical regulatory event catalog from FDA Drugs@FDA data files.

Downloads and parses the Drugs@FDA data tables to create a comprehensive
catalog of NDA/BLA submissions, action dates, and outcomes for universe
tickers from 2022 onward.

Usage:
    python scripts/research/build_historical_regulatory_catalog.py
    python scripts/research/build_historical_regulatory_catalog.py --start-year 2020
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CATALOG_SCHEMA = "historical_regulatory_events.v1"

# Submission statuses that represent decisions
DECISION_MAP = {
    "AP": {"decision_outcome": "APPROVED", "binary_outcome": 1},
    "TA": {"decision_outcome": "TENTATIVE_APPROVAL", "binary_outcome": 1},
}

# We track CRLs separately via SubmissionType patterns
# FDA doesn't have a "CRL" SubmissionStatus — CRLs show up as specific submission types


def load_universe_sponsors(data_dir: Path) -> Dict[str, str]:
    """Build sponsor_name → ticker mapping from universe.json."""
    path = data_dir / "universe.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    mapping = {}
    for entry in data:
        ticker = entry.get("ticker", "")
        company = (entry.get("market_data") or {}).get("company_name", "")
        if ticker and company:
            norm = _normalize(company)
            if norm:
                mapping[norm] = ticker
    return mapping


def _normalize(name: str) -> str:
    name = name.lower().strip()
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


def match_sponsor(sponsor: str, mapping: Dict[str, str]) -> Tuple[str, float, str]:
    """Match FDA sponsor to universe ticker. Returns (ticker, confidence, method)."""
    norm = _normalize(sponsor)
    if not norm:
        return "", 0, ""

    # Exact
    if norm in mapping:
        return mapping[norm], 0.95, "exact"

    # Substring
    for company, ticker in mapping.items():
        if len(company) >= 5 and company in norm:
            return ticker, 0.80, "substring"
        if len(norm) >= 5 and norm in company:
            return ticker, 0.80, "substring"

    return "", 0, ""


def load_fda_tables(reg_dir: Path) -> Tuple[Dict, Dict, Dict]:
    """Load Applications, Submissions, Products from Drugs@FDA."""
    # Applications: ApplNo → {SponsorName, ApplType}
    apps = {}
    with open(reg_dir / "Applications.txt", newline="", encoding="latin-1") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            apps[row["ApplNo"]] = {
                "sponsor": row.get("SponsorName", ""),
                "appl_type": row.get("ApplType", ""),
            }

    # Products: ApplNo → [{DrugName, ActiveIngredient}]
    products: Dict[str, List] = defaultdict(list)
    with open(reg_dir / "Products.txt", newline="", encoding="latin-1") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            products[row["ApplNo"]].append(
                {
                    "drug_name": row.get("DrugName", ""),
                    "active_ingredient": row.get("ActiveIngredient", ""),
                }
            )

    # Submissions: list of all submission rows
    submissions = []
    with open(reg_dir / "Submissions.txt", newline="", encoding="latin-1") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            submissions.append(row)

    return apps, dict(products), submissions


def build_catalog(
    apps: Dict,
    products: Dict,
    submissions: List,
    sponsor_mapping: Dict[str, str],
    start_year: int,
) -> List[Dict[str, Any]]:
    """Build the historical event catalog."""
    events = []
    seen: Set[str] = set()

    for sub in submissions:
        appl_no = sub.get("ApplNo", "")
        status_date = sub.get("SubmissionStatusDate", "")
        status = sub.get("SubmissionStatus", "")
        sub_type = sub.get("SubmissionType", "")
        review_priority = sub.get("ReviewPriority", "")

        if not status_date or not appl_no:
            continue

        # Date filter
        try:
            dt = date.fromisoformat(status_date[:10])
        except (ValueError, TypeError):
            continue
        if dt.year < start_year:
            continue

        # Only original and supplement efficacy submissions
        if sub_type not in ("ORIG", "SUPPL"):
            continue

        # Get application info
        app = apps.get(appl_no, {})
        sponsor = app.get("sponsor", "")
        appl_type = app.get("appl_type", "")

        # Only NDA and BLA
        if appl_type not in ("NDA", "BLA"):
            continue

        # Match to universe ticker
        ticker, conf, method = match_sponsor(sponsor, sponsor_mapping)
        if not ticker:
            continue

        # Get drug info
        prods = products.get(appl_no, [])
        drug_name = prods[0]["drug_name"] if prods else ""

        # Determine event type and outcome
        decision = DECISION_MAP.get(status, {})
        if not decision:
            continue

        # Review type normalization
        review_type = "unknown"
        rp = review_priority.upper()
        if "PRIORITY" in rp:
            review_type = "priority"
        elif "STANDARD" in rp:
            review_type = "standard"

        # Build event
        event_id = hashlib.md5(f"{ticker}:{appl_no}:{status_date}:{sub_type}".encode()).hexdigest()[:12]

        if event_id in seen:
            continue
        seen.add(event_id)

        events.append(
            {
                "event_id": event_id,
                "ticker": ticker,
                "application_number": f"{appl_type}{appl_no}",
                "drug_name": drug_name,
                "submission_type": appl_type,
                "submission_sub_type": sub_type,
                "review_type": review_type,
                "decision_date": status_date[:10],
                "decision_outcome": decision["decision_outcome"],
                "binary_outcome": decision["binary_outcome"],
                "sponsor_name": sponsor,
                "sources": ["FDA_DRUGSATFDA"],
                "confidence": "HIGH",
                "universe_ticker_confidence": conf,
                "match_method": method,
            }
        )

    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Build historical regulatory catalog from FDA Drugs@FDA")
    parser.add_argument("--reg-dir", type=Path, default=PROJECT_ROOT / "data" / "regulatory")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "production_data")
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "data" / "regulatory" / "historical_regulatory_events.json"
    )
    args = parser.parse_args()

    logger.info("Loading universe sponsor mapping ...")
    sponsor_mapping = load_universe_sponsors(args.data_dir)
    logger.info("Sponsor mapping: %d entries", len(sponsor_mapping))

    logger.info("Loading FDA tables ...")
    apps, products, submissions = load_fda_tables(args.reg_dir)
    logger.info("Applications: %d, Products: %d, Submissions: %d", len(apps), len(products), len(submissions))

    logger.info("Building catalog from %d onward ...", args.start_year)
    events = build_catalog(apps, products, submissions, sponsor_mapping, args.start_year)
    logger.info("Catalog: %d events", len(events))

    if not events:
        logger.warning("No events found")
        return 1

    # Stats
    from collections import Counter

    by_outcome = Counter(e["decision_outcome"] for e in events)
    by_review = Counter(e["review_type"] for e in events)
    by_year = Counter(e["decision_date"][:4] for e in events)
    tickers = sorted(set(e["ticker"] for e in events))

    catalog = {
        "schema": CATALOG_SCHEMA,
        "built_as_of": date.today().isoformat(),
        "date_range": {"start": f"{args.start_year}-01-01", "end": date.today().isoformat()},
        "n_events": len(events),
        "n_tickers": len(tickers),
        "by_outcome": dict(by_outcome),
        "by_review_type": dict(by_review),
        "by_year": dict(by_year),
        "tickers": tickers,
        "events": sorted(events, key=lambda e: e["decision_date"]),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2) + "\n")
    logger.info("Catalog → %s", args.output)

    # Summary
    logger.info("  Events: %d", len(events))
    logger.info("  Tickers: %d", len(tickers))
    logger.info("  By outcome: %s", dict(by_outcome))
    logger.info("  By review: %s", dict(by_review))
    logger.info("  By year: %s", dict(by_year))

    return 0


if __name__ == "__main__":
    sys.exit(main())
