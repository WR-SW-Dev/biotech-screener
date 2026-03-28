#!/usr/bin/env python3
"""Open Targets enrichment — disease-target-drug associations.

Queries the Open Targets Platform GraphQL API to map universe tickers'
drug targets to diseases with evidence scores. Produces a structured
disease taxonomy that replaces noisy CTgov condition strings.

Output:
    data/enrichment/open_targets_{date}.json

Usage:
    python tools/enrich_open_targets.py
    python tools/enrich_open_targets.py --max-tickers 10
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("open_targets")

SCHEMA_VERSION = "open_targets_enrichment.v1"
OT_API = "https://api.platform.opentargets.org/api/v4/graphql"


def load_universe_drugs(cache_dir: Path) -> Dict[str, List[Dict]]:
    """Extract drug names and targets from CTgov trial data."""
    candidates = sorted(p for p in cache_dir.glob("trial_records_*.json") if not p.name.endswith(".meta.json"))
    if not candidates:
        return {}

    with open(candidates[-1], encoding="utf-8") as f:
        records = json.load(f)

    # Group interventions by ticker
    ticker_drugs: Dict[str, Set[str]] = {}
    for r in records:
        ticker = r.get("ticker", "")
        interventions = r.get("interventions", [])
        if ticker and isinstance(interventions, list):
            for drug in interventions:
                if drug and len(drug) > 2:
                    ticker_drugs.setdefault(ticker, set()).add(drug)

    return {t: list(drugs) for t, drugs in ticker_drugs.items()}


def _graphql_post(query: str, variables: dict) -> Any:
    """Post a GraphQL query to Open Targets and return parsed JSON."""
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        OT_API,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "biotech-screener/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def query_open_targets_drug(drug_name: str) -> List[Dict[str, Any]]:
    """Query Open Targets for a drug name, return disease associations.

    Uses two-step approach: search returns generic SearchResult (not Drug),
    so inline fragments like ``... on Drug`` are silently ignored. We search
    for the drug ID first, then fetch full details by chemblId.
    """
    # Step 1: search to get drug ID
    search_query = """
    query DrugSearch($name: String!) {
      search(queryString: $name, entityNames: ["drug"], page: {size: 1, index: 0}) {
        hits { id name entity }
      }
    }
    """
    data = _graphql_post(search_query, {"name": drug_name})
    if not data:
        return []

    hits = data.get("data", {}).get("search", {}).get("hits", [])
    if not hits:
        return []

    drug_id = hits[0].get("id", "")
    drug_display = hits[0].get("name", drug_name)
    if not drug_id:
        return []

    # Step 2: fetch full drug details by chemblId
    detail_query = """
    query DrugDetail($id: String!) {
      drug(chemblId: $id) {
        id name
        mechanismsOfAction {
          rows {
            mechanismOfAction
            targets { approvedName approvedSymbol }
          }
        }
        indications {
          rows {
            disease {
              id name
              therapeuticAreas { id name }
            }
            maxClinicalStage
          }
        }
      }
    }
    """
    detail = _graphql_post(detail_query, {"id": drug_id})
    if not detail:
        return []

    hit = detail.get("data", {}).get("drug") or {}
    results = []

    # Extract mechanisms
    mechanisms = []
    for moa in (hit.get("mechanismsOfAction") or {}).get("rows", []):
        mech = moa.get("mechanismOfAction", "")
        targets = [t.get("approvedSymbol", "") for t in moa.get("targets", [])]
        if mech:
            mechanisms.append({"mechanism": mech, "targets": targets})

    # Extract indications with disease taxonomy
    for ind in (hit.get("indications") or {}).get("rows", []):
        disease = ind.get("disease", {})
        tas = disease.get("therapeuticAreas", [])
        results.append(
            {
                "drug_id": drug_id,
                "drug_name": hit.get("name", drug_display),
                "disease_id": disease.get("id", ""),
                "disease_name": disease.get("name", ""),
                "therapeutic_areas": [ta.get("name", "") for ta in tas],
                "max_phase": ind.get("maxClinicalStage"),
                "mechanisms": mechanisms[:3],
            }
        )

    return results


def enrich_open_targets(
    *,
    cache_dir: Path = REPO_ROOT / "cache" / "ctgov",
    output_dir: Path = REPO_ROOT / "data" / "enrichment",
    max_tickers: int = 0,
) -> Dict[str, Any]:
    """Enrich universe with Open Targets disease-target associations."""
    ticker_drugs = load_universe_drugs(cache_dir)
    if not ticker_drugs:
        return {"error": "no drug data from CTgov cache"}

    tickers = sorted(ticker_drugs.keys())
    if max_tickers > 0:
        tickers = tickers[:max_tickers]

    logger.info("Enriching %d tickers with Open Targets data", len(tickers))

    enriched = {}
    n_queries = 0
    n_hits = 0

    for i, ticker in enumerate(tickers):
        drugs = ticker_drugs[ticker]
        ticker_results = []

        # Query top 3 drugs per ticker (most common in trials)
        for drug in drugs[:3]:
            results = query_open_targets_drug(drug)
            n_queries += 1
            if results:
                n_hits += 1
                ticker_results.extend(results)
            time.sleep(0.2)  # Rate limit

        if ticker_results:
            # Deduplicate by disease
            seen = set()
            deduped = []
            for r in ticker_results:
                did = r.get("disease_id", "")
                if did and did not in seen:
                    seen.add(did)
                    deduped.append(r)
            enriched[ticker] = deduped

        if (i + 1) % 50 == 0:
            logger.info("  %d/%d tickers processed (%d hits)", i + 1, len(tickers), n_hits)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers_queried": len(tickers),
        "n_tickers_enriched": len(enriched),
        "n_queries": n_queries,
        "n_hits": n_hits,
        "enrichments": enriched,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"open_targets_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s (%d tickers enriched)", out_path, len(enriched))

    return result


def main():
    parser = argparse.ArgumentParser(description="Open Targets enrichment")
    parser.add_argument("--max-tickers", type=int, default=0, help="Limit tickers (0=all)")
    args = parser.parse_args()

    result = enrich_open_targets(max_tickers=args.max_tickers)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
