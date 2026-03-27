#!/usr/bin/env python3
"""Drug master builder — canonical entity resolution for universe drugs.

Queries NCATS Inxight Drugs API, ChEMBL, and RxNorm to build a normalized
drug master with: active moiety, synonyms, targets, mechanism, modality,
max clinical phase, and cross-references.

Output:
    data/enrichment/drug_master_{date}.json

Usage:
    python tools/enrich_drug_master.py
    python tools/enrich_drug_master.py --max-tickers 10
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("drug_master")

SCHEMA_VERSION = "drug_master.v1"

INXIGHT_API = "https://drugs.ncats.io/api/v1"
CHEMBL_API = "https://www.ebi.ac.uk/chembl/api/data"
RXNORM_API = "https://rxnav.nlm.nih.gov/REST"


def _api_get(url: str, timeout: int = 5) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "biotech-screener/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def load_universe_interventions(cache_dir: Path) -> Dict[str, Set[str]]:
    """Extract unique intervention names per ticker from CTgov cache."""
    candidates = sorted(p for p in cache_dir.glob("trial_records_*.json") if not p.name.endswith(".meta.json"))
    if not candidates:
        return {}
    with open(candidates[-1], encoding="utf-8") as f:
        records = json.load(f)

    ticker_drugs: Dict[str, Set[str]] = defaultdict(set)
    for r in records:
        ticker = r.get("ticker", "")
        for drug in r.get("interventions", []):
            if drug and len(drug) > 2 and len(drug) < 80:
                ticker_drugs[ticker].add(drug)
    return dict(ticker_drugs)


def query_inxight(drug_name: str) -> Dict[str, Any]:
    """Query NCATS Inxight Drugs for a substance."""
    encoded = urllib.parse.quote(drug_name)
    data = _api_get(f"{INXIGHT_API}/substances/search?q={encoded}&top=1")
    if not data or not data.get("content"):
        return {}

    hit = data["content"][0]
    result = {
        "inxight_uuid": hit.get("uuid", ""),
        "inxight_name": hit.get("_name", ""),
        "substance_class": hit.get("substanceClass", ""),
        "status": hit.get("status", ""),
        "approval_id": hit.get("approvalID", ""),
    }

    # Extract codes (UNII, CAS, etc.)
    for code in hit.get("codes", []):
        system = code.get("codeSystem", "")
        if system == "CAS":
            result["cas"] = code.get("code", "")
        elif system == "UNII":
            result["unii"] = code.get("code", "")
        elif system == "NCI_THESAURUS":
            result["nci_code"] = code.get("code", "")

    # Extract names/synonyms
    names = set()
    for name_obj in hit.get("names", []):
        n = name_obj.get("name", "")
        if n:
            names.add(n)
    result["synonyms"] = sorted(names)[:10]

    return result


def query_chembl(drug_name: str) -> Dict[str, Any]:
    """Query ChEMBL for molecule and mechanism data."""
    encoded = urllib.parse.quote(drug_name)
    data = _api_get(f"{CHEMBL_API}/molecule/search.json?q={encoded}&limit=1")
    if not data or not data.get("molecules"):
        return {}

    mol = data["molecules"][0]
    chembl_id = mol.get("molecule_chembl_id", "")

    result = {
        "chembl_id": chembl_id,
        "pref_name": mol.get("pref_name", ""),
        "molecule_type": mol.get("molecule_type", ""),
        "max_phase": mol.get("max_phase", ""),
        "first_approval": mol.get("first_approval"),
        "oral": mol.get("oral", False),
        "parenteral": mol.get("parenteral", False),
        "topical": mol.get("topical", False),
    }

    # Get mechanism if we have a ChEMBL ID
    if chembl_id:
        mech_data = _api_get(f"{CHEMBL_API}/mechanism.json?molecule_chembl_id={chembl_id}&limit=5")
        if mech_data and mech_data.get("mechanisms"):
            mechanisms = []
            for m in mech_data["mechanisms"][:3]:
                mechanisms.append(
                    {
                        "mechanism": m.get("mechanism_of_action", ""),
                        "target_name": m.get("target_chembl_id", ""),
                        "action_type": m.get("action_type", ""),
                    }
                )
            result["mechanisms"] = mechanisms

    return result


def query_rxnorm(drug_name: str) -> Dict[str, Any]:
    """Query RxNorm for normalized drug name and RxCUI."""
    encoded = urllib.parse.quote(drug_name)
    data = _api_get(f"{RXNORM_API}/approximateTerm.json?term={encoded}&maxEntries=1")
    if not data:
        return {}

    candidates = data.get("approximateGroup", {}).get("candidate", [])
    if not candidates:
        return {}

    rxcui = candidates[0].get("rxcui", "")
    name = candidates[0].get("name", "") if "name" in candidates[0] else ""

    # Get properties
    if rxcui:
        props = _api_get(f"{RXNORM_API}/rxcui/{rxcui}/properties.json")
        if props and props.get("properties"):
            p = props["properties"]
            return {
                "rxcui": rxcui,
                "rxnorm_name": p.get("name", ""),
                "tty": p.get("tty", ""),  # Term type
            }

    return {"rxcui": rxcui, "rxnorm_name": name}


def build_drug_master(
    *,
    cache_dir: Path = REPO_ROOT / "cache" / "ctgov",
    output_dir: Path = REPO_ROOT / "data" / "enrichment",
    max_tickers: int = 0,
) -> Dict[str, Any]:
    """Build the drug master artifact."""
    ticker_drugs = load_universe_interventions(cache_dir)
    if not ticker_drugs:
        return {"error": "no intervention data"}

    tickers = sorted(ticker_drugs.keys())
    if max_tickers > 0:
        tickers = tickers[:max_tickers]

    logger.info("Building drug master for %d tickers", len(tickers))

    drug_entries: Dict[str, List[Dict]] = {}
    n_inxight = 0
    n_chembl = 0
    n_rxnorm = 0

    for i, ticker in enumerate(tickers):
        drugs = sorted(ticker_drugs[ticker])[:5]  # Top 5 per ticker
        ticker_entries = []

        for drug_name in drugs:
            entry = {"raw_name": drug_name, "ticker": ticker}

            # Query each source with rate limiting
            inxight = query_inxight(drug_name)
            if inxight:
                entry["inxight"] = inxight
                n_inxight += 1
            time.sleep(0.15)

            chembl = query_chembl(drug_name)
            if chembl:
                entry["chembl"] = chembl
                n_chembl += 1
            time.sleep(0.15)

            rxnorm = query_rxnorm(drug_name)
            if rxnorm:
                entry["rxnorm"] = rxnorm
                n_rxnorm += 1
            time.sleep(0.1)

            ticker_entries.append(entry)

        if ticker_entries:
            drug_entries[ticker] = ticker_entries

        if (i + 1) % 20 == 0:
            logger.info(
                "  %d/%d tickers (%d inxight, %d chembl, %d rxnorm)", i + 1, len(tickers), n_inxight, n_chembl, n_rxnorm
            )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(tickers),
        "n_tickers_with_data": len(drug_entries),
        "n_inxight_hits": n_inxight,
        "n_chembl_hits": n_chembl,
        "n_rxnorm_hits": n_rxnorm,
        "entries": drug_entries,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"drug_master_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", out_path)

    return result


def main():
    parser = argparse.ArgumentParser(description="Drug master builder")
    parser.add_argument("--max-tickers", type=int, default=0)
    args = parser.parse_args()
    result = build_drug_master(max_tickers=args.max_tickers)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
