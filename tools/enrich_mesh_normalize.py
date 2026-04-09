#!/usr/bin/env python3
"""MeSH condition normalization — standardize CTgov conditions into taxonomy.

Maps the ~3,100 raw CTgov condition strings to standardized MeSH terms
using the NCBI MeSH API. Groups conditions into therapeutic areas for
cleaner competitive intelligence.

Output:
    data/enrichment/mesh_normalized_{date}.json

Usage:
    python tools/enrich_mesh_normalize.py
    python tools/enrich_mesh_normalize.py --max-conditions 100
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("mesh_normalize")

SCHEMA_VERSION = "mesh_normalization.v1"
MESH_API = "https://id.nlm.nih.gov/mesh/lookup/descriptor"

# Manual mapping for common biotech conditions that MeSH handles poorly
MANUAL_MAPPING = {
    "Healthy": None,  # Exclude
    "Healthy Volunteers": None,
    "Healthy Volunteer": None,
    "Safety": None,
    "Pharmacokinetics": None,
    "Drug Interaction": None,
    "COVID-19": "Coronavirus Infections",
    "Non-Small Cell Lung Cancer": "Carcinoma, Non-Small-Cell Lung",
    "NSCLC": "Carcinoma, Non-Small-Cell Lung",
    "Breast Cancer": "Breast Neoplasms",
    "Solid Tumor": "Neoplasms",
    "Advanced Solid Tumors": "Neoplasms",
    "Solid Tumors": "Neoplasms",
    "Prostate Cancer": "Prostatic Neoplasms",
    "Colorectal Cancer": "Colorectal Neoplasms",
    "Melanoma": "Melanoma",
    "Acute Myeloid Leukemia": "Leukemia, Myeloid, Acute",
    "AML": "Leukemia, Myeloid, Acute",
    "Multiple Myeloma": "Multiple Myeloma",
    "NHL": "Lymphoma, Non-Hodgkin",
    "Non-Hodgkin Lymphoma": "Lymphoma, Non-Hodgkin",
    "DLBCL": "Lymphoma, Large B-Cell, Diffuse",
    "Atopic Dermatitis": "Dermatitis, Atopic",
    "Rheumatoid Arthritis": "Arthritis, Rheumatoid",
    "Lupus": "Lupus Erythematosus, Systemic",
    "SLE": "Lupus Erythematosus, Systemic",
    "Crohn's Disease": "Crohn Disease",
    "Ulcerative Colitis": "Colitis, Ulcerative",
    "Type 2 Diabetes": "Diabetes Mellitus, Type 2",
    "Obesity": "Obesity",
    "NASH": "Non-alcoholic Fatty Liver Disease",
    "Sickle Cell Disease": "Anemia, Sickle Cell",
    "Cystic Fibrosis": "Cystic Fibrosis",
    "Parkinson's Disease": "Parkinson Disease",
    "Alzheimer's Disease": "Alzheimer Disease",
    "Schizophrenia": "Schizophrenia",
    "Depression": "Depressive Disorder",
    "MDD": "Depressive Disorder, Major",
    "Asthma": "Asthma",
    "COPD": "Pulmonary Disease, Chronic Obstructive",
    "Heart Failure": "Heart Failure",
    "Psoriasis": "Psoriasis",
    "Migraine": "Migraine Disorders",
}

# Therapeutic area groupings
THERAPEUTIC_AREAS = {
    "Oncology": ["neoplasm", "cancer", "carcinoma", "lymphoma", "leukemia", "myeloma", "melanoma", "tumor", "sarcoma"],
    "Immunology": ["arthritis", "lupus", "dermatitis", "psoriasis", "colitis", "crohn", "autoimmune", "immune"],
    "Neurology": [
        "parkinson",
        "alzheimer",
        "sclerosis",
        "epilepsy",
        "migraine",
        "schizophrenia",
        "depression",
        "neuropath",
    ],
    "Hematology": ["anemia", "sickle cell", "hemophilia", "thrombocytopenia", "myelodysplastic"],
    "Rare Disease": ["dystrophy", "fibrosis", "gaucher", "fabry", "huntington", "atrophy"],
    "Metabolic": ["diabetes", "obesity", "lipodystrophy", "fatty liver"],
    "Infectious": ["hiv", "hepatitis", "covid", "coronavirus", "influenza", "bacterial"],
    "Cardiovascular": ["heart failure", "hypertension", "cardiomyopathy", "atrial fibrillation"],
    "Respiratory": ["asthma", "copd", "pulmonary", "respiratory"],
    "Ophthalmology": ["macular", "retinal", "glaucoma", "uveitis", "ophthalmol"],
}


def classify_therapeutic_area(condition: str) -> str:
    """Classify a condition into a therapeutic area."""
    cond_lower = condition.lower()
    for area, keywords in THERAPEUTIC_AREAS.items():
        for kw in keywords:
            if kw in cond_lower:
                return area
    return "Other"


def query_mesh(term: str) -> str:
    """Query NCBI MeSH API for a standardized descriptor."""
    params = urllib.parse.urlencode({"label": term, "match": "contains", "limit": 1})
    url = f"{MESH_API}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "biotech-screener/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data and isinstance(data, list) and data[0].get("label"):
            return data[0]["label"]
    except Exception:
        pass
    return ""


def enrich_mesh_normalize(
    *,
    cache_dir: Path = REPO_ROOT / "cache" / "ctgov",
    output_dir: Path = REPO_ROOT / "data" / "enrichment",
    max_conditions: int = 0,
) -> Dict[str, Any]:
    """Normalize CTgov conditions to MeSH terms and therapeutic areas."""
    # Load all conditions from CTgov cache
    candidates = sorted(p for p in cache_dir.glob("trial_records_*.json") if not p.name.endswith(".meta.json"))
    if not candidates:
        return {"error": "no CTgov cache found"}

    with open(candidates[-1], encoding="utf-8") as f:
        records = json.load(f)

    # Count all conditions
    condition_counts = Counter()
    condition_tickers: Dict[str, Set[str]] = defaultdict(set)
    for r in records:
        ticker = r.get("ticker", "")
        for cond in r.get("conditions", []):
            if cond:
                condition_counts[cond] += 1
                condition_tickers[cond].add(ticker)

    logger.info("Found %d unique conditions", len(condition_counts))

    # Sort by frequency, apply limit
    sorted_conditions = [c for c, _ in condition_counts.most_common()]
    if max_conditions > 0:
        sorted_conditions = sorted_conditions[:max_conditions]

    # Normalize: manual mapping first, then MeSH API for unknowns
    normalized = {}
    n_manual = 0
    n_mesh = 0
    n_api_queries = 0

    for i, cond in enumerate(sorted_conditions):
        # Manual mapping
        if cond in MANUAL_MAPPING:
            mesh_term = MANUAL_MAPPING[cond]
            if mesh_term is None:
                normalized[cond] = {"mesh_term": None, "excluded": True, "source": "manual_exclude"}
            else:
                normalized[cond] = {"mesh_term": mesh_term, "source": "manual"}
            n_manual += 1
            continue

        # Try MeSH API (rate limited)
        if n_api_queries < 500:  # Cap API calls
            mesh_term = query_mesh(cond)
            n_api_queries += 1
            if mesh_term:
                normalized[cond] = {"mesh_term": mesh_term, "source": "mesh_api"}
                n_mesh += 1
            else:
                normalized[cond] = {"mesh_term": cond, "source": "passthrough"}
            time.sleep(0.1)
        else:
            normalized[cond] = {"mesh_term": cond, "source": "passthrough"}

        if (i + 1) % 100 == 0:
            logger.info("  %d/%d conditions processed", i + 1, len(sorted_conditions))

    # Add therapeutic area classification
    ta_counts = Counter()
    for cond, info in normalized.items():
        if info.get("excluded"):
            continue
        mesh = info.get("mesh_term", cond)
        ta = classify_therapeutic_area(mesh or cond)
        info["therapeutic_area"] = ta
        ta_counts[ta] += condition_counts.get(cond, 0)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_conditions_total": len(condition_counts),
        "n_conditions_processed": len(sorted_conditions),
        "n_manual_mapped": n_manual,
        "n_mesh_resolved": n_mesh,
        "n_api_queries": n_api_queries,
        "therapeutic_area_distribution": dict(ta_counts.most_common()),
        "normalizations": normalized,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"mesh_normalized_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s (%d conditions)", out_path, len(normalized))

    return result


def main():
    parser = argparse.ArgumentParser(description="MeSH condition normalization")
    parser.add_argument("--max-conditions", type=int, default=0)
    args = parser.parse_args()

    result = enrich_mesh_normalize(max_conditions=args.max_conditions)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
