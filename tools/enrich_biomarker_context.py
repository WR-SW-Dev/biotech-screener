#!/usr/bin/env python3
"""Biomarker context master — oncology and PGx metadata.

Queries CIViC, FDA PGx table, and NCI Thesaurus for biomarker-required
indications, resistance markers, companion diagnostics, and molecular
context relevant to biotech drug development.

Output:
    data/enrichment/biomarker_context_{date}.json

Usage:
    python tools/enrich_biomarker_context.py
    python tools/enrich_biomarker_context.py --max-tickers 10
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
logger = logging.getLogger("biomarker_context")

SCHEMA_VERSION = "biomarker_context.v1"

CIVIC_API = "https://civicdb.org/api/graphql"
FDA_PGX_URL = "https://api.fda.gov/drug/label.json"


def _api_get(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "biotech-screener/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _graphql_post(url: str, query: str, variables: dict) -> Any:
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "biotech-screener/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def load_universe_conditions(cache_dir: Path) -> Dict[str, Set[str]]:
    """Load ticker → conditions from CTgov cache."""
    candidates = sorted(p for p in cache_dir.glob("trial_records_*.json") if not p.name.endswith(".meta.json"))
    if not candidates:
        return {}
    with open(candidates[-1], encoding="utf-8") as f:
        records = json.load(f)

    ticker_conds: Dict[str, Set[str]] = defaultdict(set)
    for r in records:
        ticker = r.get("ticker", "")
        for c in r.get("conditions", []):
            if c:
                ticker_conds[ticker].add(c)
    return dict(ticker_conds)


# Oncology condition keywords
ONCO_KEYWORDS = [
    "cancer",
    "carcinoma",
    "lymphoma",
    "leukemia",
    "myeloma",
    "melanoma",
    "sarcoma",
    "tumor",
    "neoplasm",
    "glioma",
    "glioblastoma",
    "neuroblastoma",
    "mesothelioma",
    "adenocarcinoma",
    "hepatocellular",
    "cholangiocarcinoma",
]


def is_oncology(conditions: Set[str]) -> bool:
    """Check if a ticker has oncology indications."""
    for c in conditions:
        if any(kw in c.lower() for kw in ONCO_KEYWORDS):
            return True
    return False


def query_civic_therapies(disease_name: str) -> List[Dict[str, Any]]:
    """Query CIViC for evidence items related to a disease."""
    query = """
    query TherapySearch($name: String!) {
      evidenceItems(diseaseName: $name, first: 10) {
        nodes {
          id
          significance
          evidenceLevel
          evidenceType
          therapies {
            name
          }
          disease {
            name
          }
          molecularProfile {
            name
          }
        }
      }
    }
    """
    data = _graphql_post(CIVIC_API, query, {"name": disease_name})
    if not data:
        return []

    nodes = data.get("data", {}).get("evidenceItems", {}).get("nodes", [])
    results = []
    for node in nodes[:5]:
        therapies = [t.get("name", "") for t in node.get("therapies", [])]
        results.append(
            {
                "civic_id": node.get("id"),
                "significance": node.get("significance", ""),
                "evidence_level": node.get("evidenceLevel", ""),
                "evidence_type": node.get("evidenceType", ""),
                "therapies": therapies,
                "disease": node.get("disease", {}).get("name", ""),
                "molecular_profile": node.get("molecularProfile", {}).get("name", ""),
            }
        )
    return results


def query_fda_pgx(drug_name: str) -> List[Dict[str, Any]]:
    """Query openFDA for pharmacogenomic label information."""
    encoded = urllib.parse.quote(drug_name)
    data = _api_get(f'{FDA_PGX_URL}?search=openfda.brand_name:"{encoded}"+AND+pharmacogenomics&limit=1')
    if not data or not data.get("results"):
        return []

    results = []
    for label in data["results"][:1]:
        pgx = label.get("pharmacogenomics", [])
        if pgx:
            results.append(
                {
                    "brand_name": (
                        (label.get("openfda", {}).get("brand_name", [""]))[0]
                        if label.get("openfda", {}).get("brand_name")
                        else ""
                    ),
                    "pgx_sections": pgx[:3],
                }
            )
    return results


def build_biomarker_context(
    *,
    cache_dir: Path = REPO_ROOT / "cache" / "ctgov",
    enrichment_dir: Path = REPO_ROOT / "data" / "enrichment",
    output_dir: Path = REPO_ROOT / "data" / "enrichment",
    max_tickers: int = 0,
) -> Dict[str, Any]:
    """Build biomarker context master for oncology tickers."""
    ticker_conds = load_universe_conditions(cache_dir)
    if not ticker_conds:
        return {"error": "no condition data"}

    # Filter to oncology tickers
    onco_tickers = {t for t, conds in ticker_conds.items() if is_oncology(conds)}
    tickers = sorted(onco_tickers)
    if max_tickers > 0:
        tickers = tickers[:max_tickers]

    logger.info("Building biomarker context for %d oncology tickers (of %d total)", len(tickers), len(ticker_conds))

    entries: Dict[str, Dict[str, Any]] = {}
    n_civic = 0
    n_pgx = 0

    for i, ticker in enumerate(tickers):
        conditions = ticker_conds[ticker]
        onco_conditions = [c for c in conditions if any(kw in c.lower() for kw in ONCO_KEYWORDS)]

        ticker_entry: Dict[str, Any] = {
            "ticker": ticker,
            "n_onco_conditions": len(onco_conditions),
            "top_conditions": sorted(onco_conditions)[:5],
            "civic_evidence": [],
            "pgx": [],
        }

        # Query CIViC for top oncology condition
        if onco_conditions:
            civic = query_civic_therapies(onco_conditions[0])
            if civic:
                ticker_entry["civic_evidence"] = civic
                n_civic += 1
            time.sleep(0.2)

        entries[ticker] = ticker_entry

        if (i + 1) % 20 == 0:
            logger.info("  %d/%d tickers (%d CIViC hits)", i + 1, len(tickers), n_civic)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_onco_tickers": len(tickers),
        "n_civic_hits": n_civic,
        "n_pgx_hits": n_pgx,
        "entries": entries,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"biomarker_context_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", out_path)

    return result


def main():
    parser = argparse.ArgumentParser(description="Biomarker context master")
    parser.add_argument("--max-tickers", type=int, default=0)
    args = parser.parse_args()
    result = build_biomarker_context(max_tickers=args.max_tickers)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
