#!/usr/bin/env python3
"""Build graveyard catalog — PIT-safe dataset of failed/retired biotech programs.

Reads clinical_history_catalog, outcome labels, and optional manual curation
to produce a deterministic graveyard catalog. Every record has source,
timestamp, and confidence. No look-ahead violations.

Phase A: Infrastructure only — no production path changes.

Output:
    data/graveyard/graveyard_catalog.json

Usage:
    python scripts/research/build_graveyard_catalog.py
    python scripts/research/build_graveyard_catalog.py --as-of-date 2026-03-28
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("graveyard_catalog")

SCHEMA_VERSION = "graveyard_catalog.v1"

# Status values that indicate program-level failure
TERMINAL_STATUSES = frozenset({"TERMINATED", "WITHDRAWN"})

# Minimum lag (days) before completed-no-results becomes a research candidate
COMPLETED_NO_RESULTS_LAG_DAYS = 730  # 2 years

# Phase normalization
PHASE_MAP = {
    "PHASE1": "phase1",
    "PHASE2": "phase2",
    "PHASE3": "phase3",
    "PHASE4": "phase4",
    "EARLY_PHASE1": "phase1",
    "NA": "unknown",
    "": "unknown",
}


def _normalize_phase(raw: str) -> str:
    return PHASE_MAP.get(raw.upper().replace(" ", "").replace("/", ""), raw.lower() if raw else "unknown")


def _graveyard_id(ticker: str, nct_id: str, event_type: str) -> str:
    """Deterministic hash for dedup."""
    key = f"{ticker}|{nct_id}|{event_type}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _days_between(date_a: Optional[str], date_b: Optional[str]) -> Optional[int]:
    """Days between two ISO date strings."""
    if not date_a or not date_b:
        return None
    try:
        a = datetime.fromisoformat(date_a[:10])
        b = datetime.fromisoformat(date_b[:10])
        return (b - a).days
    except (ValueError, TypeError):
        return None


def _infer_failure_reason(record: Dict) -> str:
    """Infer failure reason class from available data."""
    status = record.get("status", "")
    title = (record.get("title") or "").lower()

    # Safety signals in title
    safety_keywords = ["safety", "adverse", "toxicity", "dlt", "dose-limiting"]
    if any(kw in title for kw in safety_keywords) and status == "TERMINATED":
        return "SAFETY"

    # If terminated early, default is UNKNOWN (most common)
    if status == "TERMINATED":
        return "UNKNOWN"

    if status == "WITHDRAWN":
        return "OPERATIONAL"

    return "UNKNOWN"


def _is_lead_program(ticker: str, nct_id: str, phase: str, all_trials: List[Dict]) -> bool:
    """Heuristic: a trial is lead-program if it's the highest-phase trial for the ticker."""
    phase_rank = {"phase4": 4, "phase3": 3, "phase2": 2, "phase1": 1, "unknown": 0}
    this_rank = phase_rank.get(phase, 0)

    ticker_trials = [t for t in all_trials if t.get("ticker") == ticker]
    max_rank = max((phase_rank.get(_normalize_phase(t.get("phase", "")), 0) for t in ticker_trials), default=0)

    return this_rank >= max_rank and this_rank >= 2  # At least phase2


def build_graveyard_from_catalog(
    catalog_records: List[Dict],
    labels: Dict[str, Dict],
    manual_events: List[Dict],
    as_of_date: Optional[str] = None,
) -> List[Dict]:
    """Build graveyard records from clinical catalog + labels + manual curation."""
    records = []
    seen_ids: Set[str] = set()

    for trial in catalog_records:
        ticker = trial.get("ticker", "")
        nct_id = trial.get("nct_id", "")
        status = trial.get("status", "")

        if not ticker or not nct_id:
            continue

        # PIT gate: use last_update_posted as the date the status became public
        event_date = trial.get("last_update_posted") or trial.get("completion_date")
        data_available = trial.get("last_update_posted")
        if not event_date or not data_available:
            continue

        # PIT filter
        if as_of_date and data_available[:10] > as_of_date:
            continue

        phase = _normalize_phase(trial.get("phase", ""))
        lifecycle = trial.get("lifecycle", {})

        # --- TERMINATED trials ---
        if status == "TERMINATED":
            gid = _graveyard_id(ticker, nct_id, "PROGRAM_TERMINATED")
            if gid in seen_ids:
                continue
            seen_ids.add(gid)

            # Check if we have a label for this trial
            label = labels.get(nct_id)
            has_label = label is not None
            label_outcome = label.get("binary_outcome") if label else None

            records.append(
                {
                    "graveyard_id": gid,
                    "ticker": ticker,
                    "company_name": trial.get("sponsor", ""),
                    "program_key": f"{ticker}|{nct_id}",
                    "nct_id": nct_id,
                    "trial_title": trial.get("title", ""),
                    "event_type": "PROGRAM_TERMINATED",
                    "event_date": event_date[:10],
                    "data_available_as_of": data_available[:10],
                    "pit_safe": True,
                    "source_type": "CTGOV",
                    "source_ref": nct_id,
                    "confidence": "HIGH",
                    "phase_at_failure": phase,
                    "status_before_event": status,
                    "failure_reason_class": _infer_failure_reason(trial),
                    "lead_asset": _is_lead_program(ticker, nct_id, phase, catalog_records),
                    "has_outcome_label": has_label,
                    "outcome_label": label_outcome,
                }
            )

        # --- WITHDRAWN trials ---
        elif status == "WITHDRAWN":
            gid = _graveyard_id(ticker, nct_id, "TRIAL_WITHDRAWN")
            if gid in seen_ids:
                continue
            seen_ids.add(gid)

            records.append(
                {
                    "graveyard_id": gid,
                    "ticker": ticker,
                    "company_name": trial.get("sponsor", ""),
                    "program_key": f"{ticker}|{nct_id}",
                    "nct_id": nct_id,
                    "trial_title": trial.get("title", ""),
                    "event_type": "TRIAL_WITHDRAWN",
                    "event_date": event_date[:10],
                    "data_available_as_of": data_available[:10],
                    "pit_safe": True,
                    "source_type": "CTGOV",
                    "source_ref": nct_id,
                    "confidence": "HIGH",
                    "phase_at_failure": phase,
                    "status_before_event": status,
                    "failure_reason_class": "OPERATIONAL",
                    "lead_asset": _is_lead_program(ticker, nct_id, phase, catalog_records),
                    "has_outcome_label": False,
                    "outcome_label": None,
                }
            )

        # --- COMPLETED with no results (research candidate, MEDIUM confidence) ---
        elif status == "COMPLETED" and not lifecycle.get("has_posted_results"):
            completion_date = trial.get("completion_date") or trial.get("primary_completion_date")
            lag = _days_between(completion_date, data_available)

            if lag is not None and lag >= COMPLETED_NO_RESULTS_LAG_DAYS:
                gid = _graveyard_id(ticker, nct_id, "COMPLETED_NO_RESULTS")
                if gid in seen_ids:
                    continue
                seen_ids.add(gid)

                records.append(
                    {
                        "graveyard_id": gid,
                        "ticker": ticker,
                        "company_name": trial.get("sponsor", ""),
                        "program_key": f"{ticker}|{nct_id}",
                        "nct_id": nct_id,
                        "trial_title": trial.get("title", ""),
                        "event_type": "COMPLETED_NO_RESULTS",
                        "event_date": event_date[:10],
                        "data_available_as_of": data_available[:10],
                        "pit_safe": True,
                        "source_type": "CTGOV",
                        "source_ref": nct_id,
                        "confidence": "MEDIUM",
                        "phase_at_failure": phase,
                        "status_before_event": status,
                        "failure_reason_class": "UNKNOWN",
                        "lead_asset": _is_lead_program(ticker, nct_id, phase, catalog_records),
                        "has_outcome_label": False,
                        "outcome_label": None,
                        "results_lag_days": lag,
                    }
                )

    # --- Manual curation events ---
    for manual in manual_events:
        gid = manual.get("graveyard_id") or _graveyard_id(
            manual.get("ticker", ""),
            manual.get("source_ref", "manual"),
            manual.get("event_type", "MANUAL"),
        )
        if gid in seen_ids:
            continue

        # PIT gate for manual events
        da = manual.get("data_available_as_of")
        if not da:
            logger.warning("Manual event missing data_available_as_of, skipping: %s", manual.get("ticker"))
            continue
        if as_of_date and da > as_of_date:
            continue

        seen_ids.add(gid)
        manual["graveyard_id"] = gid
        manual["pit_safe"] = True
        manual["source_type"] = manual.get("source_type", "MANUAL_CURATION")
        records.append(manual)

    return records


def build_graveyard_catalog(
    *,
    catalog_path: Path = PROJECT_ROOT / "data" / "clinical" / "clinical_history_catalog.json",
    labels_path: Path = PROJECT_ROOT / "data" / "clinical" / "clinical_outcome_labels_v2.json",
    manual_path: Path = PROJECT_ROOT / "data" / "graveyard" / "manual_events.json",
    output_path: Path = PROJECT_ROOT / "data" / "graveyard" / "graveyard_catalog.json",
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the graveyard catalog artifact."""

    # Load catalog
    if not catalog_path.exists():
        return {"error": f"missing catalog: {catalog_path}"}
    with open(catalog_path) as f:
        catalog = json.load(f)
    catalog_records = catalog.get("records", [])
    logger.info("Loaded catalog: %d records", len(catalog_records))

    # Load labels
    labels: Dict[str, Dict] = {}
    if labels_path.exists():
        with open(labels_path) as f:
            labels_obj = json.load(f)
        for rec in labels_obj.get("labels", labels_obj.get("records", [])):
            nct = rec.get("nct_id", "")
            if nct:
                labels[nct] = rec
        logger.info("Loaded labels: %d", len(labels))

    # Load manual curation
    manual_events: List[Dict] = []
    if manual_path.exists():
        with open(manual_path) as f:
            manual_obj = json.load(f)
        manual_events = manual_obj if isinstance(manual_obj, list) else manual_obj.get("events", [])
        logger.info("Loaded manual events: %d", len(manual_events))

    # Build records
    records = build_graveyard_from_catalog(catalog_records, labels, manual_events, as_of_date)

    # Sort by event_date
    records.sort(key=lambda r: r.get("event_date", ""))

    # Summary stats
    from collections import Counter

    event_types = Counter(r["event_type"] for r in records)
    confidence_dist = Counter(r.get("confidence", "UNKNOWN") for r in records)
    phase_dist = Counter(r.get("phase_at_failure", "unknown") for r in records)
    tickers = set(r["ticker"] for r in records)
    lead_failures = sum(1 for r in records if r.get("lead_asset"))

    result = {
        "schema": SCHEMA_VERSION,
        "built_as_of": as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": len(records),
        "n_tickers": len(tickers),
        "n_lead_failures": lead_failures,
        "event_type_counts": dict(event_types.most_common()),
        "confidence_counts": dict(confidence_dist.most_common()),
        "phase_counts": dict(phase_dist.most_common()),
        "records": records,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s (%d records, %d tickers)", output_path, len(records), len(tickers))

    return result


def main():
    parser = argparse.ArgumentParser(description="Build graveyard catalog (Spec 033)")
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument(
        "--catalog", type=Path, default=PROJECT_ROOT / "data" / "clinical" / "clinical_history_catalog.json"
    )
    parser.add_argument(
        "--labels", type=Path, default=PROJECT_ROOT / "data" / "clinical" / "clinical_outcome_labels_v2.json"
    )
    parser.add_argument("--manual", type=Path, default=PROJECT_ROOT / "data" / "graveyard" / "manual_events.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "graveyard" / "graveyard_catalog.json")
    args = parser.parse_args()

    result = build_graveyard_catalog(
        catalog_path=args.catalog,
        labels_path=args.labels,
        manual_path=args.manual,
        output_path=args.output,
        as_of_date=args.as_of_date,
    )
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
