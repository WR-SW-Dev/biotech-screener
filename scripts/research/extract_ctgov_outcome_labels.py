#!/usr/bin/env python3
"""Extract clinical outcome labels from CT.gov Results API.

Fetches ResultsSection for trials with posted results and extracts
binary success/failure labels from primary endpoint p-values.

Usage:
    python scripts/research/extract_ctgov_outcome_labels.py
    python scripts/research/extract_ctgov_outcome_labels.py --max-trials 100
"""

from __future__ import annotations

import json
import logging
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCHEMA = "clinical_outcome_labels.v2"
CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
RATE_LIMIT_DELAY = 0.35  # seconds between requests


def parse_pvalue(pval_str: str) -> Optional[float]:
    """Parse a p-value string from CT.gov results."""
    if not pval_str:
        return None
    cleaned = pval_str.strip().replace("<", "").replace(">", "").replace("=", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def label_from_results(results_section: dict) -> Dict[str, Any]:
    """Extract binary outcome label from CT.gov ResultsSection."""
    empty = {
        "binary_outcome": None,
        "outcome_basis": "no_results",
        "confidence": "low",
        "raw_pvalue": None,
        "n_primary_measures": 0,
        "n_analyses": 0,
    }

    if not results_section:
        return empty

    outcome_measures = results_section.get("outcomeMeasuresModule", {}).get("outcomeMeasures", [])
    if not outcome_measures:
        return {**empty, "outcome_basis": "no_outcome_measures"}

    # Find primary outcome measures
    primary = [om for om in outcome_measures if (om.get("type") or "").upper() == "PRIMARY"]
    if not primary:
        return {**empty, "outcome_basis": "no_primary_found", "n_primary_measures": 0}

    # Collect all p-values from primary analyses
    pvalues = []
    for om in primary:
        for analysis in om.get("analyses", []):
            pval_str = analysis.get("pValue")
            pval = parse_pvalue(pval_str)
            if pval is not None:
                pvalues.append(pval)

    n_analyses = len(pvalues)
    if not pvalues:
        return {
            "binary_outcome": None,
            "outcome_basis": "no_pvalue_found",
            "confidence": "low",
            "raw_pvalue": None,
            "n_primary_measures": len(primary),
            "n_analyses": 0,
        }

    # Use the most significant p-value from primary analyses
    best_pval = min(pvalues)

    if best_pval < 0.05:
        return {
            "binary_outcome": 1,
            "outcome_basis": "pvalue",
            "confidence": "high",
            "raw_pvalue": best_pval,
            "n_primary_measures": len(primary),
            "n_analyses": n_analyses,
        }
    elif best_pval >= 0.05:
        return {
            "binary_outcome": 0,
            "outcome_basis": "pvalue",
            "confidence": "high",
            "raw_pvalue": best_pval,
            "n_primary_measures": len(primary),
            "n_analyses": n_analyses,
        }

    return {**empty, "n_primary_measures": len(primary), "n_analyses": n_analyses}


def fetch_results(nct_id: str) -> Optional[dict]:
    """Fetch ResultsSection from CT.gov API v2."""
    url = f"{CTGOV_API}/{nct_id}?fields=ResultsSection"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BiotechScreener/1.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        return data.get("resultsSection")
    except Exception:
        return None


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Extract CT.gov outcome labels")
    parser.add_argument("--max-trials", type=int, default=0, help="Max trials to fetch (0=all)")
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_ROOT / "cache" / "ctgov_results")
    args = parser.parse_args()

    # Load outcome events (trials with results_first_posted)
    events_path = PROJECT_ROOT / "data" / "clinical" / "clinical_outcome_events.json"
    events_data = json.loads(events_path.read_text())
    events = events_data.get("events", [])
    logger.info("Loaded %d outcome events", len(events))

    # Deduplicate by NCT ID
    nct_ids = {}
    for ev in events:
        nct = ev.get("nct_id", "")
        if nct and nct not in nct_ids:
            nct_ids[nct] = ev

    unique_ncts = list(nct_ids.keys())
    if args.max_trials > 0:
        unique_ncts = unique_ncts[: args.max_trials]
    logger.info("Unique NCT IDs to fetch: %d", len(unique_ncts))

    # Cache setup
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    labels = []
    n_fetched = 0
    n_cached = 0
    n_labeled = 0

    for i, nct_id in enumerate(unique_ncts):
        if i % 100 == 0 and i > 0:
            logger.info("  Progress: %d/%d (labeled=%d)", i, len(unique_ncts), n_labeled)

        # Check cache
        cache_file = args.cache_dir / f"{nct_id}.json"
        if cache_file.exists():
            try:
                results = json.loads(cache_file.read_text())
                n_cached += 1
            except (json.JSONDecodeError, OSError):
                results = None
        else:
            results = fetch_results(nct_id)
            n_fetched += 1
            # Cache result (even if None)
            cache_file.write_text(json.dumps(results, default=str) + "\n")
            time.sleep(RATE_LIMIT_DELAY)

        # Label
        label = label_from_results(results)
        ev = nct_ids[nct_id]

        record = {
            "nct_id": nct_id,
            "ticker": ev.get("ticker", ""),
            "phase": ev.get("phase", ""),
            "public_disclosure_date": ev.get("public_disclosure_date", ""),
            "binary_outcome": label["binary_outcome"],
            "outcome_basis": label["outcome_basis"],
            "raw_pvalue": label["raw_pvalue"],
            "confidence": label["confidence"],
            "n_primary_measures": label["n_primary_measures"],
            "n_analyses": label["n_analyses"],
            "label_source": "CT_GOV_RESULTS_API",
            "pit_anchor": ev.get("public_disclosure_date", ""),
        }
        labels.append(record)
        if label["binary_outcome"] is not None:
            n_labeled += 1

    logger.info("Done: %d fetched, %d cached, %d labeled", n_fetched, n_cached, n_labeled)

    # Stats
    from collections import Counter

    by_outcome = Counter(r["binary_outcome"] for r in labels)
    by_basis = Counter(r["outcome_basis"] for r in labels)
    by_conf = Counter(r["confidence"] for r in labels)

    logger.info("  By outcome: %s", dict(by_outcome))
    logger.info("  By basis: %s", dict(by_basis))
    logger.info("  By confidence: %s", dict(by_conf))

    # Write
    output = {
        "schema": SCHEMA,
        "built_as_of": date.today().isoformat(),
        "n_labels": len(labels),
        "n_high_confidence": sum(1 for r in labels if r["confidence"] == "high"),
        "n_success": by_outcome.get(1, 0),
        "n_failure": by_outcome.get(0, 0),
        "n_unresolved": by_outcome.get(None, 0),
        "by_outcome": {str(k): v for k, v in by_outcome.items()},
        "by_basis": dict(by_basis),
        "by_confidence": dict(by_conf),
        "labels": labels,
    }

    out_path = PROJECT_ROOT / "data" / "clinical" / "clinical_outcome_labels_v2.json"
    out_path.write_text(json.dumps(output, indent=2, default=str) + "\n")
    logger.info("Output → %s", out_path)

    # Success rate among high-confidence labels
    high_conf = [r for r in labels if r["confidence"] == "high"]
    if high_conf:
        sr = sum(1 for r in high_conf if r["binary_outcome"] == 1) / len(high_conf)
        logger.info("  High-confidence success rate: %.1f%% (n=%d)", sr * 100, len(high_conf))

    return 0


if __name__ == "__main__":
    sys.exit(main())
