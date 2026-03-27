#!/usr/bin/env python3
"""CTgov endpoint enrichment — extract primary endpoints, sample size, design.

Queries ClinicalTrials.gov API v2 for detailed protocol information beyond
what the base trial_records cache stores: primary/secondary endpoints,
planned enrollment, statistical design, masking, and allocation.

Output:
    data/enrichment/ctgov_endpoints_{date}.json

Usage:
    python tools/enrich_ctgov_endpoints.py
    python tools/enrich_ctgov_endpoints.py --max-trials 50
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
logger = logging.getLogger("ctgov_endpoints")

SCHEMA_VERSION = "ctgov_endpoint_enrichment.v1"
CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"


def load_active_trials(cache_dir: Path, universe_tickers: set) -> List[Dict]:
    """Load active/recruiting trials for universe tickers from cache."""
    candidates = sorted(p for p in cache_dir.glob("trial_records_*.json") if not p.name.endswith(".meta.json"))
    if not candidates:
        return []

    with open(candidates[-1], encoding="utf-8") as f:
        records = json.load(f)

    active_statuses = {"RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING"}
    return [
        r
        for r in records
        if r.get("ticker") in universe_tickers
        and r.get("status") in active_statuses
        and r.get("phase") in ("PHASE2", "PHASE2_PHASE3", "PHASE3")
    ]


def fetch_trial_details(nct_id: str) -> Dict[str, Any]:
    """Fetch detailed protocol from CTgov API v2 for one trial."""
    url = f"{CTGOV_API}/{nct_id}?format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "biotech-screener/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        proto = data.get("protocolSection", {})
        design = proto.get("designModule", {})
        outcomes = proto.get("outcomesModule", {})
        eligibility = proto.get("eligibilityModule", {})
        status = proto.get("statusModule", {})

        # Primary outcomes
        primary_outcomes = []
        for po in outcomes.get("primaryOutcomes", []):
            primary_outcomes.append(
                {
                    "measure": po.get("measure", ""),
                    "timeFrame": po.get("timeFrame", ""),
                    "description": po.get("description", "")[:200],
                }
            )

        # Secondary outcomes
        secondary_outcomes = []
        for so in outcomes.get("secondaryOutcomes", [])[:5]:
            secondary_outcomes.append(
                {
                    "measure": so.get("measure", ""),
                    "timeFrame": so.get("timeFrame", ""),
                }
            )

        # Design details
        enrollment_info = status.get("enrollmentInfo", {})

        return {
            "nct_id": nct_id,
            "primary_outcomes": primary_outcomes,
            "secondary_outcomes": secondary_outcomes,
            "n_primary_outcomes": len(primary_outcomes),
            "n_secondary_outcomes": len(outcomes.get("secondaryOutcomes", [])),
            "planned_enrollment": enrollment_info.get("count"),
            "enrollment_type": enrollment_info.get("type", ""),
            "study_type": design.get("studyType", ""),
            "allocation": design.get("designInfo", {}).get("allocation", ""),
            "masking": design.get("designInfo", {}).get("maskingInfo", {}).get("masking", ""),
            "primary_purpose": design.get("designInfo", {}).get("primaryPurpose", ""),
            "phases": design.get("phases", []),
            "min_age": eligibility.get("minimumAge", ""),
            "max_age": eligibility.get("maximumAge", ""),
            "sex": eligibility.get("sex", ""),
        }

    except Exception as e:
        logger.debug("Failed to fetch %s: %s", nct_id, e)
        return {}


def enrich_ctgov_endpoints(
    *,
    cache_dir: Path = REPO_ROOT / "cache" / "ctgov",
    output_dir: Path = REPO_ROOT / "data" / "enrichment",
    universe_path: Path = REPO_ROOT / "production_data" / "universe.json",
    max_trials: int = 0,
) -> Dict[str, Any]:
    """Enrich active Phase 2/3 trials with endpoint and design data."""
    # Load universe
    with open(universe_path, encoding="utf-8") as f:
        universe = json.load(f)
    universe_tickers = {u["ticker"] for u in universe if u.get("ticker")}

    trials = load_active_trials(cache_dir, universe_tickers)
    if not trials:
        return {"error": "no active Phase 2/3 trials found"}

    if max_trials > 0:
        trials = trials[:max_trials]

    logger.info("Enriching %d active Phase 2/3 trials", len(trials))

    enriched = []
    for i, trial in enumerate(trials):
        nct_id = trial.get("nct_id", "")
        if not nct_id:
            continue

        details = fetch_trial_details(nct_id)
        if details:
            details["ticker"] = trial.get("ticker", "")
            details["title"] = trial.get("title", "")[:100]
            details["phase"] = trial.get("phase", "")
            details["status"] = trial.get("status", "")
            enriched.append(details)

        time.sleep(0.2)  # Rate limit

        if (i + 1) % 50 == 0:
            logger.info("  %d/%d trials processed", i + 1, len(trials))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_trials_queried": len(trials),
        "n_trials_enriched": len(enriched),
        "enrichments": enriched,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"ctgov_endpoints_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s (%d trials)", out_path, len(enriched))

    return result


def main():
    parser = argparse.ArgumentParser(description="CTgov endpoint enrichment")
    parser.add_argument("--max-trials", type=int, default=0)
    args = parser.parse_args()

    result = enrich_ctgov_endpoints(max_trials=args.max_trials)
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
