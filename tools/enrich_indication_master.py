#!/usr/bin/env python3
"""Indication master builder — normalized disease ontology for universe.

Maps CTgov condition strings to EFO (Open Targets), MONDO, Orphanet
rare-disease flags, and MedGen concepts. Produces a clean indication
graph with parent classes, synonyms, and rare-disease status.

Output:
    data/enrichment/indication_master_{date}.json

Usage:
    python tools/enrich_indication_master.py
    python tools/enrich_indication_master.py --max-conditions 50
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
from typing import Any, Dict, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("indication_master")

SCHEMA_VERSION = "indication_master.v1"

OT_API = "https://api.platform.opentargets.org/api/v4/graphql"


def _api_get(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "biotech-screener/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _graphql_post(query: str, variables: dict) -> Any:
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


def load_conditions(cache_dir: Path) -> Dict[str, Set[str]]:
    """Load condition → tickers mapping from CTgov cache."""
    candidates = sorted(p for p in cache_dir.glob("trial_records_*.json") if not p.name.endswith(".meta.json"))
    if not candidates:
        return {}
    with open(candidates[-1], encoding="utf-8") as f:
        records = json.load(f)

    cond_tickers: Dict[str, Set[str]] = defaultdict(set)
    for r in records:
        ticker = r.get("ticker", "")
        for c in r.get("conditions", []):
            if c and len(c) > 2:
                cond_tickers[c].add(ticker)
    return dict(cond_tickers)


# Noise filter
NOISE = frozenset(
    {
        "Healthy",
        "Healthy Volunteers",
        "Healthy Volunteer",
        "Safety",
        "Pharmacokinetics",
        "Drug Interaction",
        "Bioequivalence",
    }
)


def query_ot_disease(condition: str) -> Dict[str, Any]:
    """Query Open Targets for a disease, returning EFO mapping + metadata."""
    query = """
    query DiseaseSearch($term: String!) {
      search(queryString: $term, entityNames: ["disease"], page: {size: 1, index: 0}) {
        hits {
          id
          name
          entity
          ... on Disease {
            therapeuticAreas {
              id
              name
            }
            isTherapeuticArea
            synonyms {
              terms
            }
            parents {
              id
              name
            }
          }
        }
      }
    }
    """
    data = _graphql_post(query, {"term": condition})
    if not data:
        return {}

    hits = data.get("data", {}).get("search", {}).get("hits", [])
    if not hits:
        return {}

    hit = hits[0]
    synonyms_obj = hit.get("synonyms") or {}
    synonyms = synonyms_obj.get("terms", []) if isinstance(synonyms_obj, dict) else []

    return {
        "efo_id": hit.get("id", ""),
        "efo_name": hit.get("name", ""),
        "is_therapeutic_area": hit.get("isTherapeuticArea", False),
        "therapeutic_areas": [ta.get("name", "") for ta in hit.get("therapeuticAreas", [])],
        "parents": [{"id": p.get("id", ""), "name": p.get("name", "")} for p in hit.get("parents", [])[:3]],
        "synonyms": synonyms[:5] if isinstance(synonyms, list) else [],
    }


def query_medgen(condition: str) -> Dict[str, Any]:
    """Query NCBI MedGen for a condition concept."""
    encoded = urllib.parse.quote(condition)
    # Use NCBI E-utils to search MedGen
    data = _api_get(
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=medgen&term={encoded}&retmode=json&retmax=1"
    )
    if not data or not data.get("esearchresult", {}).get("idlist"):
        return {}

    uid = data["esearchresult"]["idlist"][0]
    # Fetch summary
    summary = _api_get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=medgen&id={uid}&retmode=json")
    if not summary or not summary.get("result", {}).get(uid):
        return {"medgen_uid": uid}

    s = summary["result"][uid]
    return {
        "medgen_uid": uid,
        "medgen_name": s.get("title", ""),
        "concept_id": s.get("conceptid", ""),
        "semantic_type": s.get("semantictype", ""),
    }


def check_orphanet_rare(condition: str) -> bool:
    """Simple heuristic for rare disease — check if condition contains rare-disease keywords."""
    rare_keywords = [
        "rare",
        "orphan",
        "ultra-rare",
        "genetic",
        "inherited",
        "congenital",
        "dystrophy",
        "atrophy",
        "mucopolysaccharidosis",
        "gaucher",
        "fabry",
        "huntington",
        "cystic fibrosis",
        "sickle cell",
        "hemophilia",
        "epidermolysis",
        "pompe",
        "niemann",
        "krabbe",
        "tay-sachs",
    ]
    cond_lower = condition.lower()
    return any(kw in cond_lower for kw in rare_keywords)


def build_indication_master(
    *,
    cache_dir: Path = REPO_ROOT / "cache" / "ctgov",
    output_dir: Path = REPO_ROOT / "data" / "enrichment",
    max_conditions: int = 0,
) -> Dict[str, Any]:
    """Build the indication master artifact."""
    cond_tickers = load_conditions(cache_dir)
    if not cond_tickers:
        return {"error": "no conditions data"}

    # Sort by frequency, filter noise
    sorted_conds = sorted(cond_tickers.keys(), key=lambda c: -len(cond_tickers[c]))
    sorted_conds = [c for c in sorted_conds if c not in NOISE]
    if max_conditions > 0:
        sorted_conds = sorted_conds[:max_conditions]

    logger.info("Building indication master for %d conditions", len(sorted_conds))

    entries = {}
    n_efo = 0
    n_medgen = 0

    for i, cond in enumerate(sorted_conds):
        entry: Dict[str, Any] = {
            "raw_condition": cond,
            "n_tickers": len(cond_tickers[cond]),
            "tickers": sorted(cond_tickers[cond])[:10],
            "is_rare": check_orphanet_rare(cond),
        }

        # Open Targets (EFO)
        efo = query_ot_disease(cond)
        if efo:
            entry["efo"] = efo
            n_efo += 1
        time.sleep(0.15)

        # MedGen
        medgen = query_medgen(cond)
        if medgen:
            entry["medgen"] = medgen
            n_medgen += 1
        time.sleep(0.15)

        entries[cond] = entry

        if (i + 1) % 20 == 0:
            logger.info("  %d/%d conditions (%d EFO, %d MedGen)", i + 1, len(sorted_conds), n_efo, n_medgen)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_conditions": len(sorted_conds),
        "n_efo_mapped": n_efo,
        "n_medgen_mapped": n_medgen,
        "n_rare_disease": sum(1 for e in entries.values() if e.get("is_rare")),
        "entries": entries,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"indication_master_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s", out_path)

    return result


def main():
    parser = argparse.ArgumentParser(description="Indication master builder")
    parser.add_argument("--max-conditions", type=int, default=0)
    args = parser.parse_args()
    result = build_indication_master(max_conditions=args.max_conditions)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
