#!/usr/bin/env python3
"""Build clinical history catalog from trial_records.json.

Creates a PIT-safe clinical warehouse with explicit availability timestamps,
design quality fields, and outcome event extraction.

Usage:
    python scripts/research/build_clinical_history_catalog.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CATALOG_SCHEMA = "clinical_history_catalog.v1"
OUTCOME_SCHEMA = "clinical_outcome_events.v1"

# Phase normalization
PHASE_MAP = {
    "PHASE1": "phase1",
    "PHASE 1": "phase1",
    "1": "phase1",
    "PHASE2": "phase2",
    "PHASE 2": "phase2",
    "2": "phase2",
    "PHASE3": "phase3",
    "PHASE 3": "phase3",
    "3": "phase3",
    "PHASE4": "phase4",
    "PHASE 4": "phase4",
    "4": "phase4",
    "EARLY_PHASE1": "phase1",
    "PHASE1/PHASE2": "phase1_2",
    "PHASE2/PHASE3": "phase2_3",
}

# Status that means trial completed
COMPLETED_STATUSES = {"COMPLETED", "TERMINATED", "WITHDRAWN", "SUSPENDED"}

# Endpoint classification keywords
ENDPOINT_OS = {"overall survival", "os", "death"}
ENDPOINT_PFS = {"progression-free survival", "pfs", "progression free"}
ENDPOINT_ORR = {"objective response rate", "orr", "response rate", "overall response"}
ENDPOINT_SURROGATE = {"biomarker", "ctdna", "mrd", "pathological complete response", "pcr"}


def classify_endpoint(text: str) -> str:
    """Classify primary endpoint type from text."""
    t = text.lower()
    if any(kw in t for kw in ENDPOINT_OS):
        return "overall_survival"
    if any(kw in t for kw in ENDPOINT_PFS):
        return "progression_free_survival"
    if any(kw in t for kw in ENDPOINT_ORR):
        return "objective_response_rate"
    if any(kw in t for kw in ENDPOINT_SURROGATE):
        return "surrogate"
    return "other"


def has_biomarker_selection(conditions: list, interventions: list, title: str) -> bool:
    """Check if trial uses biomarker selection."""
    text = " ".join(str(x) for x in (conditions + interventions + [title]) if x).lower()
    markers = [
        "biomarker",
        "mutation",
        "her2",
        "egfr",
        "braf",
        "kras",
        "pd-l1",
        "microsatellite",
        "msi",
        "tmb",
        "ctdna",
        "gene expression",
        "receptor positive",
        "receptor negative",
    ]
    return any(m in text for m in markers)


def build_catalog(trials: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build clinical history catalog from trial_records.json entries."""
    catalog = []

    for trial in trials:
        ticker = (trial.get("ticker") or "").upper()
        nct_id = trial.get("nct_id", "")
        if not ticker or not nct_id:
            continue

        # PIT anchors
        first_posted = trial.get("first_posted", "")
        last_update = trial.get("last_update_posted", "")
        results_posted = trial.get("results_first_posted")
        pcd = trial.get("primary_completion_date", "")
        cd = trial.get("completion_date", "")

        # Data availability
        data_available = first_posted or last_update
        results_available = results_posted if results_posted else None

        # Phase
        phase_raw = (trial.get("phase") or "").upper().strip()
        phase = PHASE_MAP.get(phase_raw, phase_raw.lower() if phase_raw else "unknown")

        # Status
        status = (trial.get("status") or "").upper().strip()

        # Design fields
        conditions = trial.get("conditions", []) or []
        interventions = trial.get("interventions", []) or []
        title = trial.get("title", "")
        enrollment = trial.get("enrollment")
        sponsor = trial.get("sponsor", "")

        # Endpoint classification from title + conditions (best available without full protocol)
        endpoint_class = classify_endpoint(title)

        # Biomarker selection
        biomarker = has_biomarker_selection(conditions, interventions, title)

        # Enrollment bucket
        try:
            enroll_n = int(enrollment) if enrollment else None
        except (ValueError, TypeError):
            enroll_n = None

        if enroll_n is not None:
            if enroll_n < 50:
                enroll_bucket = "small"
            elif enroll_n < 200:
                enroll_bucket = "medium"
            elif enroll_n < 500:
                enroll_bucket = "large"
            else:
                enroll_bucket = "very_large"
        else:
            enroll_bucket = "unknown"

        record = {
            "ticker": ticker,
            "nct_id": nct_id,
            "title": title[:200],
            "phase": phase,
            "status": status,
            "sponsor": sponsor,
            "first_posted": first_posted,
            "last_update_posted": last_update,
            "results_first_posted": results_available,
            "primary_completion_date": pcd,
            "completion_date": cd,
            "data_available_as_of": data_available,
            "results_available_as_of": results_available,
            "pit_date_used": "first_posted" if first_posted else "last_update_posted",
            "design": {
                "enrollment": enroll_n,
                "enrollment_bucket": enroll_bucket,
                "biomarker_selected": biomarker,
                "endpoint_class": endpoint_class,
            },
            "lifecycle": {
                "is_completed": status in COMPLETED_STATUSES,
                "is_terminated": status in {"TERMINATED", "WITHDRAWN"},
                "has_posted_results": results_available is not None,
            },
            "provenance": {
                "source": "CTGOV",
                "collected_at": trial.get("collected_at", ""),
            },
        }
        catalog.append(record)

    return catalog


def extract_outcome_events(catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract clinical outcome events from catalog entries with posted results."""
    events = []
    for rec in catalog:
        if not rec["lifecycle"]["has_posted_results"]:
            continue

        results_date = rec["results_available_as_of"]
        if not results_date:
            continue

        event_id = f"{rec['ticker']}_{rec['nct_id']}_RESULTS_{results_date}"

        # Compute days from completion to results posting
        pcd = rec.get("primary_completion_date", "")
        days_to_results = None
        if pcd and results_date:
            try:
                d_pcd = date.fromisoformat(pcd[:10])
                d_res = date.fromisoformat(results_date[:10])
                days_to_results = (d_res - d_pcd).days
            except (ValueError, TypeError):
                pass

        events.append(
            {
                "event_id": hashlib.md5(event_id.encode()).hexdigest()[:12],
                "ticker": rec["ticker"],
                "nct_id": rec["nct_id"],
                "event_type": "CT_RESULTS_POSTED",
                "phase": rec["phase"],
                "public_disclosure_date": results_date,
                "first_market_known_date": results_date,
                "pit_safe": True,
                "days_from_completion_to_results": days_to_results,
                "design_endpoint_class": rec["design"]["endpoint_class"],
                "design_biomarker_selected": rec["design"]["biomarker_selected"],
                "provenance": {"source": "CTGOV", "results_first_posted": results_date},
            }
        )

    return events


def main() -> int:
    trials_path = PROJECT_ROOT / "production_data" / "trial_records.json"
    if not trials_path.exists():
        logger.error("Missing %s", trials_path)
        return 1

    logger.info("Loading trial records ...")
    trials = json.loads(trials_path.read_text())
    logger.info("Loaded %d trials", len(trials))

    logger.info("Building catalog ...")
    catalog = build_catalog(trials)
    logger.info("Catalog: %d records", len(catalog))

    # Stats
    n_with_results = sum(1 for r in catalog if r["lifecycle"]["has_posted_results"])
    n_completed = sum(1 for r in catalog if r["lifecycle"]["is_completed"])
    n_biomarker = sum(1 for r in catalog if r["design"]["biomarker_selected"])
    phases = {}
    for r in catalog:
        p = r["phase"]
        phases[p] = phases.get(p, 0) + 1
    tickers = sorted(set(r["ticker"] for r in catalog))

    logger.info("  Tickers: %d", len(tickers))
    logger.info("  With results: %d", n_with_results)
    logger.info("  Completed: %d", n_completed)
    logger.info("  Biomarker selected: %d", n_biomarker)
    logger.info("  By phase: %s", phases)

    # Write catalog
    out_dir = PROJECT_ROOT / "data" / "clinical"
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog_out = {
        "schema_version": CATALOG_SCHEMA,
        "built_as_of": date.today().isoformat(),
        "n_records": len(catalog),
        "n_tickers": len(tickers),
        "n_with_results": n_with_results,
        "n_completed": n_completed,
        "n_biomarker_selected": n_biomarker,
        "by_phase": phases,
        "records": catalog,
    }
    cat_path = out_dir / "clinical_history_catalog.json"
    cat_path.write_text(json.dumps(catalog_out, indent=2, default=str) + "\n")
    logger.info("Catalog → %s", cat_path)

    # Extract outcome events
    logger.info("Extracting outcome events ...")
    outcomes = extract_outcome_events(catalog)
    logger.info("Outcome events: %d", len(outcomes))

    outcome_out = {
        "schema_version": OUTCOME_SCHEMA,
        "built_as_of": date.today().isoformat(),
        "n_events": len(outcomes),
        "events": outcomes,
    }
    out_path = out_dir / "clinical_outcome_events.json"
    out_path.write_text(json.dumps(outcome_out, indent=2, default=str) + "\n")
    logger.info("Outcome events → %s", out_path)

    # Quick calibration: days from completion to results posting
    lag_days = [
        e["days_from_completion_to_results"] for e in outcomes if e["days_from_completion_to_results"] is not None
    ]
    if lag_days:
        import statistics

        logger.info(
            "  Results posting lag: median=%d days, mean=%d days, n=%d",
            statistics.median(lag_days),
            sum(lag_days) // len(lag_days),
            len(lag_days),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
