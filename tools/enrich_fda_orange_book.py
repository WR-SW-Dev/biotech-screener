#!/usr/bin/env python3
"""FDA Orange Book enrichment — patent expiry and exclusivity data.

Downloads the FDA Orange Book data files and extracts patent expiry dates
and exclusivity windows for universe tickers' approved drugs. Identifies
names facing generic/biosimilar competition risk.

Output:
    data/enrichment/orange_book_{date}.json

Usage:
    python tools/enrich_fda_orange_book.py
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("orange_book")

SCHEMA_VERSION = "orange_book_enrichment.v1"

# FDA Orange Book download URL (ZIP file containing .txt files)
OB_ZIP_URL = "https://www.fda.gov/media/76860/download"


def download_orange_book_zip() -> Dict[str, List[Dict[str, str]]]:
    """Download and extract the Orange Book ZIP file from FDA.

    Returns dict with keys 'products', 'patents', 'exclusivity'.
    """
    req = urllib.request.Request(OB_ZIP_URL, headers={"User-Agent": "biotech-screener/1.0"})
    result: Dict[str, List[Dict[str, str]]] = {"products": [], "patents": [], "exclusivity": []}

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()

        zf = zipfile.ZipFile(io.BytesIO(raw))
        logger.info("Orange Book ZIP: %d files", len(zf.namelist()))

        for name in zf.namelist():
            name_lower = name.lower()
            content = zf.read(name).decode("latin-1", errors="replace")

            # Determine delimiter (Orange Book uses ~ as separator)
            first_line = content.split("\n")[0] if content else ""
            delimiter = "~" if "~" in first_line else ","

            reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
            rows = list(reader)

            if "product" in name_lower:
                result["products"] = rows
                logger.info("  products (%s): %d rows", name, len(rows))
            elif "patent" in name_lower:
                result["patents"] = rows
                logger.info("  patents (%s): %d rows", name, len(rows))
            elif "exclus" in name_lower:
                result["exclusivity"] = rows
                logger.info("  exclusivity (%s): %d rows", name, len(rows))

        return result
    except Exception as e:
        logger.warning("Failed to download Orange Book: %s", e)
        return result


def build_company_to_ticker(universe: List[Dict]) -> Dict[str, str]:
    """Build approximate company name → ticker mapping."""
    mapping = {}
    for u in universe:
        ticker = u.get("ticker", "")
        name = u.get("name", "").upper()
        if ticker and name:
            mapping[name] = ticker
            # Also try short forms
            for suffix in [
                " INC",
                " INC.",
                " CORP",
                " CORP.",
                " THERAPEUTICS",
                " BIOSCIENCES",
                " PHARMACEUTICALS",
                " PHARMA",
                " SCIENCES",
                " BIOTECH",
            ]:
                if name.endswith(suffix):
                    mapping[name[: -len(suffix)].strip()] = ticker
    return mapping


def match_applicant_to_ticker(
    applicant: str,
    company_map: Dict[str, str],
) -> str:
    """Try to match an FDA applicant name to a universe ticker."""
    if not applicant:
        return ""
    applicant_upper = applicant.upper().strip()

    # Direct match
    if applicant_upper in company_map:
        return company_map[applicant_upper]

    # Substring match
    for company, ticker in company_map.items():
        if company in applicant_upper or applicant_upper in company:
            return ticker

    return ""


def enrich_fda_orange_book(
    *,
    output_dir: Path = REPO_ROOT / "data" / "enrichment",
    universe_path: Path = REPO_ROOT / "production_data" / "universe.json",
) -> Dict[str, Any]:
    """Download and process FDA Orange Book data."""
    # Load universe
    with open(universe_path, encoding="utf-8") as f:
        universe = json.load(f)
    company_map = build_company_to_ticker(universe)
    universe_tickers = {u["ticker"] for u in universe if u.get("ticker")}

    # Download Orange Book ZIP
    ob_data = download_orange_book_zip()
    products = ob_data.get("products", [])
    patents = ob_data.get("patents", [])
    exclusivity = ob_data.get("exclusivity", [])

    # Match products to universe tickers
    matched_products = []
    for p in products:
        applicant = p.get("Applicant", p.get("applicant", ""))
        ticker = match_applicant_to_ticker(applicant, company_map)
        if ticker and ticker in universe_tickers:
            matched_products.append(
                {
                    "ticker": ticker,
                    "applicant": applicant,
                    "drug_name": p.get("Trade_Name", p.get("Ingredient", "")),
                    "ingredient": p.get("Ingredient", ""),
                    "appl_no": p.get("Appl_No", ""),
                    "product_no": p.get("Product_No", ""),
                    "approval_date": p.get("Approval_Date", ""),
                    "type": p.get("Type", p.get("Appl_Type", "")),
                }
            )

    # Match patents to matched products
    appl_nos = {p["appl_no"] for p in matched_products}
    matched_patents = []
    for pat in patents:
        appl_no = pat.get("Appl_No", "")
        if appl_no in appl_nos:
            matched_patents.append(
                {
                    "appl_no": appl_no,
                    "patent_no": pat.get("Patent_No", ""),
                    "patent_expire_date": pat.get("Patent_Expire_Date_Text", pat.get("Patent_Expire_Date", "")),
                    "drug_substance_claim": pat.get("Drug_Substance_Claim", ""),
                    "drug_product_claim": pat.get("Drug_Product_Claim", ""),
                }
            )

    # Match exclusivity
    matched_exclusivity = []
    for exc in exclusivity:
        appl_no = exc.get("Appl_No", "")
        if appl_no in appl_nos:
            matched_exclusivity.append(
                {
                    "appl_no": appl_no,
                    "exclusivity_code": exc.get("Exclusivity_Code", ""),
                    "exclusivity_date": exc.get("Exclusivity_Date", ""),
                }
            )

    # Group by ticker
    from collections import defaultdict

    by_ticker: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"products": [], "patents": [], "exclusivity": []})
    for p in matched_products:
        by_ticker[p["ticker"]]["products"].append(p)
    for pat in matched_patents:
        # Find ticker via appl_no
        for p in matched_products:
            if p["appl_no"] == pat["appl_no"]:
                by_ticker[p["ticker"]]["patents"].append(pat)
                break
    for exc in matched_exclusivity:
        for p in matched_products:
            if p["appl_no"] == exc["appl_no"]:
                by_ticker[p["ticker"]]["exclusivity"].append(exc)
                break

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_products_total": len(products),
        "n_products_matched": len(matched_products),
        "n_tickers_matched": len(by_ticker),
        "n_patents_matched": len(matched_patents),
        "n_exclusivity_matched": len(matched_exclusivity),
        "by_ticker": dict(by_ticker),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"orange_book_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s (%d tickers matched)", out_path, len(by_ticker))

    return result


def main():
    argparse.ArgumentParser(description="FDA Orange Book enrichment").parse_args()

    result = enrich_fda_orange_book()
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
