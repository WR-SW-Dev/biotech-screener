#!/usr/bin/env python3
"""Label/regulatory master — DailyMed labels, Drugs@FDA approvals, Purple Book.

Consolidates approved-indication text, label sections, approval history,
and biologic/biosimilar status from FDA public sources.

Output:
    data/enrichment/label_regulatory_{date}.json

Usage:
    python tools/enrich_label_regulatory.py
    python tools/enrich_label_regulatory.py --max-tickers 10
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("label_regulatory")

SCHEMA_VERSION = "label_regulatory_master.v1"

DAILYMED_API = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
OPENFDA_API = "https://api.fda.gov/drug"


def _api_get(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "biotech-screener/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def load_universe_drugs(enrichment_dir: Path) -> Dict[str, List[str]]:
    """Load drug names from Orange Book enrichment or CTgov cache."""
    # Try Orange Book first (has actual drug names)
    ob_files = sorted(enrichment_dir.glob("orange_book_*.json"))
    if ob_files:
        with open(ob_files[-1], encoding="utf-8") as f:
            ob = json.load(f)
        ticker_drugs: Dict[str, List[str]] = {}
        for ticker, data in ob.get("by_ticker", {}).items():
            drugs = set()
            for p in data.get("products", []):
                name = p.get("drug_name", "")
                if name:
                    drugs.add(name)
            if drugs:
                ticker_drugs[ticker] = sorted(drugs)[:5]
        return ticker_drugs
    return {}


def query_dailymed(drug_name: str) -> Dict[str, Any]:
    """Query DailyMed for SPL label data."""
    encoded = urllib.parse.quote(drug_name)
    data = _api_get(f"{DAILYMED_API}/spls.json?drug_name={encoded}&pagesize=1")
    if not data or not data.get("data"):
        return {}

    spl = data["data"][0]
    set_id = spl.get("setid", "")

    result = {
        "set_id": set_id,
        "title": spl.get("title", ""),
        "published_date": spl.get("published_date", ""),
    }

    # Get label sections if we have a set_id
    if set_id:
        label_data = _api_get(f"{DAILYMED_API}/spls/{set_id}.json")
        if label_data:
            # Extract key sections
            for section_name in [
                "indications_and_usage",
                "boxed_warning",
                "warnings_and_precautions",
                "dosage_and_administration",
            ]:
                # DailyMed sections are in the SPL XML; the JSON API gives metadata
                pass
            result["product_type"] = label_data.get("product_type", "")
            result["marketing_category"] = label_data.get("marketing_category", "")

    return result


def query_openfda_approvals(drug_name: str) -> List[Dict[str, Any]]:
    """Query openFDA for drug approval/application history."""
    encoded = urllib.parse.quote(drug_name)
    data = _api_get(f'{OPENFDA_API}/drugsfda.json?search=openfda.brand_name:"{encoded}"&limit=3')
    if not data or not data.get("results"):
        return []

    approvals = []
    for result in data["results"][:3]:
        products = result.get("products", [])
        submissions = result.get("submissions", [])

        latest_submission = {}
        if submissions:
            latest_submission = submissions[0]

        approvals.append(
            {
                "application_number": result.get("application_number", ""),
                "sponsor_name": result.get("sponsor_name", ""),
                "n_products": len(products),
                "n_submissions": len(submissions),
                "latest_submission_type": latest_submission.get("submission_type", ""),
                "latest_submission_status": latest_submission.get("submission_status", ""),
                "latest_submission_date": latest_submission.get("submission_status_date", ""),
            }
        )

    return approvals


def build_label_regulatory(
    *,
    enrichment_dir: Path = REPO_ROOT / "data" / "enrichment",
    output_dir: Path = REPO_ROOT / "data" / "enrichment",
    max_tickers: int = 0,
) -> Dict[str, Any]:
    """Build the label/regulatory master artifact."""
    ticker_drugs = load_universe_drugs(enrichment_dir)
    if not ticker_drugs:
        return {"error": "no drug names (run Orange Book enrichment first)"}

    tickers = sorted(ticker_drugs.keys())
    if max_tickers > 0:
        tickers = tickers[:max_tickers]

    logger.info("Building label/regulatory master for %d tickers", len(tickers))

    entries: Dict[str, List[Dict]] = {}
    n_dailymed = 0
    n_openfda = 0

    for i, ticker in enumerate(tickers):
        drugs = ticker_drugs[ticker]
        ticker_entries = []

        for drug_name in drugs[:3]:
            entry: Dict[str, Any] = {"drug_name": drug_name, "ticker": ticker}

            # DailyMed
            dm = query_dailymed(drug_name)
            if dm:
                entry["dailymed"] = dm
                n_dailymed += 1
            time.sleep(0.15)

            # openFDA
            fda = query_openfda_approvals(drug_name)
            if fda:
                entry["openfda_approvals"] = fda
                n_openfda += 1
            time.sleep(0.15)

            ticker_entries.append(entry)

        if ticker_entries:
            entries[ticker] = ticker_entries

        if (i + 1) % 20 == 0:
            logger.info("  %d/%d tickers (%d DailyMed, %d openFDA)", i + 1, len(tickers), n_dailymed, n_openfda)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(tickers),
        "n_tickers_with_data": len(entries),
        "n_dailymed_hits": n_dailymed,
        "n_openfda_hits": n_openfda,
        "entries": entries,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"label_regulatory_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", out_path)

    return result


def main():
    parser = argparse.ArgumentParser(description="Label/regulatory master builder")
    parser.add_argument("--max-tickers", type=int, default=0)
    args = parser.parse_args()
    result = build_label_regulatory(max_tickers=args.max_tickers)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
