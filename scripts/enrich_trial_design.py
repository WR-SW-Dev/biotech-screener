#!/usr/bin/env python3
"""Enrich trial_records.json with structured design fields from AACT.

Reads designs.txt and design_outcomes.txt from the latest AACT extract,
joins on nct_id, and adds:
  - allocation        (RANDOMIZED | NON_RANDOMIZED | null)
  - masking           (DOUBLE | SINGLE | TRIPLE | QUADRUPLE | NONE | null)
  - intervention_model (PARALLEL | CROSSOVER | SEQUENTIAL | SINGLE_GROUP | FACTORIAL | null)
  - primary_purpose    (TREATMENT | PREVENTION | DIAGNOSTIC | ... | null)
  - primary_endpoints  (list of primary endpoint measure texts)

These fields power the clinical_quality_score module (Spec 057).

Usage:
    python scripts/enrich_trial_design.py [--aact-dir DIR] [--dry-run]

Author: Wake Robin Capital Management
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRIAL_RECORDS = PROJECT_ROOT / "production_data" / "trial_records.json"


def _find_latest_extract(aact_dir: Path | None = None) -> Path:
    """Find the most recent extracted AACT directory."""
    if aact_dir and aact_dir.is_dir():
        return aact_dir
    downloads = PROJECT_ROOT / "data" / "aact" / "downloads"
    candidates = sorted(downloads.glob("extracted_*"), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No extracted AACT directories in {downloads}")
    return candidates[0]


def _load_designs(extract_dir: Path, nct_ids: set[str]) -> dict[str, dict]:
    """Load designs.txt filtered to our NCT IDs.

    Returns {nct_id: {allocation, masking, intervention_model, primary_purpose}}.
    """
    path = extract_dir / "designs.txt"
    if not path.exists():
        raise FileNotFoundError(f"designs.txt not found in {extract_dir}")

    result: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            nct = row.get("nct_id", "")
            if nct not in nct_ids:
                continue
            result[nct] = {
                "allocation": (row.get("allocation") or "").strip().upper() or None,
                "masking": (row.get("masking") or "").strip().upper() or None,
                "intervention_model": (row.get("intervention_model") or "").strip().upper() or None,
                "primary_purpose": (row.get("primary_purpose") or "").strip().upper() or None,
            }
    return result


def _load_primary_endpoints(extract_dir: Path, nct_ids: set[str]) -> dict[str, list[str]]:
    """Load primary endpoint measures from design_outcomes.txt.

    Returns {nct_id: [measure_text, ...]}.
    """
    path = extract_dir / "design_outcomes.txt"
    if not path.exists():
        logger.warning("design_outcomes.txt not found — skipping endpoint enrichment")
        return {}

    result: dict[str, list[str]] = {}
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            nct = row.get("nct_id", "")
            if nct not in nct_ids:
                continue
            otype = (row.get("outcome_type") or "").strip().lower()
            if otype != "primary":
                continue
            measure = (row.get("measure") or "").strip()
            if measure:
                result.setdefault(nct, []).append(measure)
    return result


def enrich(
    trial_records_path: Path = DEFAULT_TRIAL_RECORDS,
    aact_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Enrich trial_records.json with AACT design fields.

    Returns stats dict with counts.
    """
    with open(trial_records_path) as f:
        records = json.load(f)

    nct_ids = {r["nct_id"] for r in records if r.get("nct_id")}
    logger.info(f"Trial records: {len(records)}, unique NCT IDs: {len(nct_ids)}")

    extract_dir = _find_latest_extract(aact_dir)
    logger.info(f"Using AACT extract: {extract_dir.name}")

    designs = _load_designs(extract_dir, nct_ids)
    logger.info(f"Design matches: {len(designs)} / {len(nct_ids)} NCT IDs")

    endpoints = _load_primary_endpoints(extract_dir, nct_ids)
    logger.info(f"Primary endpoint matches: {len(endpoints)} NCT IDs")

    # Merge into records
    n_design = 0
    n_endpoint = 0
    for rec in records:
        nct = rec.get("nct_id", "")
        d = designs.get(nct)
        if d:
            rec["allocation"] = d["allocation"]
            rec["masking"] = d["masking"]
            rec["intervention_model"] = d["intervention_model"]
            rec["primary_purpose"] = d["primary_purpose"]
            n_design += 1
        else:
            rec.setdefault("allocation", None)
            rec.setdefault("masking", None)
            rec.setdefault("intervention_model", None)
            rec.setdefault("primary_purpose", None)

        ep = endpoints.get(nct, [])
        rec["primary_endpoints"] = ep
        if ep:
            n_endpoint += 1

    stats = {
        "total_records": len(records),
        "design_enriched": n_design,
        "endpoint_enriched": n_endpoint,
        "design_match_rate": round(n_design / len(records) * 100, 1) if records else 0,
        "endpoint_match_rate": round(n_endpoint / len(records) * 100, 1) if records else 0,
    }
    logger.info(
        f"Enrichment: {n_design} designs ({stats['design_match_rate']}%), "
        f"{n_endpoint} endpoints ({stats['endpoint_match_rate']}%)"
    )

    if dry_run:
        logger.info("DRY RUN — not writing")
        # Show a sample
        sample = [r for r in records if r.get("allocation")][:3]
        for s in sample:
            logger.info(
                f"  {s['ticker']} {s['nct_id']}: "
                f"alloc={s['allocation']}, mask={s['masking']}, "
                f"model={s['intervention_model']}, "
                f"endpoints={len(s.get('primary_endpoints', []))}"
            )
    else:
        with open(trial_records_path, "w") as f:
            json.dump(records, f, indent=2)
        logger.info(f"Written to {trial_records_path}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Enrich trial_records.json with AACT design fields")
    parser.add_argument("--aact-dir", type=Path, help="Path to extracted AACT directory")
    parser.add_argument("--trial-records", type=Path, default=DEFAULT_TRIAL_RECORDS, help="Path to trial_records.json")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    enrich(args.trial_records, args.aact_dir, args.dry_run)


if __name__ == "__main__":
    main()
