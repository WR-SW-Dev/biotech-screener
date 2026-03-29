#!/usr/bin/env python3
"""Build graveyard company rollup — per-ticker summary of graveyard events.

Reads graveyard_catalog.json and produces a per-ticker rollup with
failure counts, recency, severity scoring, and failure mix.

Phase A: Infrastructure only — no production path changes.

Output:
    data/graveyard/graveyard_company_rollup.json

Usage:
    python scripts/research/build_graveyard_rollup.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("graveyard_rollup")

SCHEMA_VERSION = "graveyard_company_rollup.v1"

# Severity weights by event type
EVENT_SEVERITY = {
    "PROGRAM_TERMINATED": 1.0,
    "TRIAL_WITHDRAWN": 0.6,
    "COMPLETED_NO_RESULTS": 0.3,
    "PIPELINE_DISCONTINUED": 1.2,
    "ACQUIRED": 0.5,
    "DELISTED": 1.5,
    "BANKRUPTCY": 2.0,
    "ASSET_SOLD": 0.4,
}

# Phase severity multipliers (later-phase failures are more impactful)
PHASE_SEVERITY = {
    "phase3": 2.0,
    "phase2": 1.0,
    "phase1": 0.5,
    "phase4": 0.3,
    "unknown": 0.3,
}


def _days_since(date_str: Optional[str], as_of: str) -> Optional[int]:
    if not date_str:
        return None
    try:
        d = datetime.fromisoformat(date_str[:10])
        a = datetime.fromisoformat(as_of[:10])
        return (a - d).days
    except (ValueError, TypeError):
        return None


def build_company_rollup(
    records: List[Dict],
    as_of_date: str,
    min_confidence: str = "MEDIUM",
    ticker_trial_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Dict]:
    """Build per-ticker rollup from graveyard records.

    Args:
        ticker_trial_counts: total trials per ticker from clinical_history_catalog,
            used to normalize severity by pipeline size. If None, raw severity only.
    """
    conf_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    min_conf = conf_rank.get(min_confidence.upper(), 1)

    # Filter by confidence
    filtered = [r for r in records if conf_rank.get(r.get("confidence", "LOW"), 0) >= min_conf]

    ticker_records: Dict[str, List[Dict]] = defaultdict(list)
    for r in filtered:
        ticker_records[r["ticker"]].append(r)

    rollup = {}
    for ticker, recs in sorted(ticker_records.items()):
        event_types = Counter(r["event_type"] for r in recs)
        phases = Counter(r.get("phase_at_failure", "unknown") for r in recs)
        reasons = Counter(r.get("failure_reason_class", "UNKNOWN") for r in recs)

        n_lead = sum(1 for r in recs if r.get("lead_asset"))
        dates = sorted(r.get("event_date", "") for r in recs if r.get("event_date"))
        last_failure = dates[-1] if dates else None
        recency_days = _days_since(last_failure, as_of_date)

        # Severity score: sum of (event_severity * phase_severity)
        severity = 0.0
        for r in recs:
            ev_sev = EVENT_SEVERITY.get(r.get("event_type", ""), 0.5)
            ph_sev = PHASE_SEVERITY.get(r.get("phase_at_failure", "unknown"), 0.3)
            severity += ev_sev * ph_sev

        # Confidence: HIGH if >50% of records are HIGH confidence
        high_pct = sum(1 for r in recs if r.get("confidence") == "HIGH") / max(len(recs), 1)
        rollup_confidence = "HIGH" if high_pct > 0.5 else "MEDIUM"

        # Normalized severity: per-trial burden
        n_total_trials = (ticker_trial_counts or {}).get(ticker, 0)
        severity_per_trial = round(severity / max(n_total_trials, 1), 4) if n_total_trials else None
        graveyard_rate = round(len(recs) / max(n_total_trials, 1), 4) if n_total_trials else None

        rollup[ticker] = {
            "ticker": ticker,
            "n_graveyard_events": len(recs),
            "n_total_trials": n_total_trials,
            "n_program_failures": event_types.get("PROGRAM_TERMINATED", 0),
            "n_trial_withdrawals": event_types.get("TRIAL_WITHDRAWN", 0),
            "n_completed_no_results": event_types.get("COMPLETED_NO_RESULTS", 0),
            "n_lead_program_failures": n_lead,
            "last_failure_date": last_failure,
            "recency_days": recency_days,
            "failure_mix": dict(reasons.most_common()),
            "phase_mix": dict(phases.most_common()),
            "graveyard_severity_score": round(severity, 2),
            "graveyard_severity_per_trial": severity_per_trial,
            "graveyard_rate": graveyard_rate,
            "graveyard_confidence": rollup_confidence,
        }

    return rollup


def build_graveyard_rollup(
    *,
    catalog_path: Path = PROJECT_ROOT / "data" / "graveyard" / "graveyard_catalog.json",
    clinical_catalog_path: Path = PROJECT_ROOT / "data" / "clinical" / "clinical_history_catalog.json",
    output_path: Path = PROJECT_ROOT / "data" / "graveyard" / "graveyard_company_rollup.json",
    min_confidence: str = "MEDIUM",
) -> Dict[str, Any]:
    """Build graveyard company rollup artifact."""
    if not catalog_path.exists():
        return {"error": f"missing catalog: {catalog_path}"}

    with open(catalog_path) as f:
        catalog = json.load(f)

    records = catalog.get("records", [])
    as_of = catalog.get("built_as_of", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    logger.info("Loaded catalog: %d records, as_of=%s", len(records), as_of)

    # Load trial counts for normalization
    ticker_trial_counts: Optional[Dict[str, int]] = None
    if clinical_catalog_path.exists():
        with open(clinical_catalog_path) as f:
            clin = json.load(f)
        ticker_trial_counts = Counter(r.get("ticker", "") for r in clin.get("records", []))
        logger.info("Loaded clinical catalog for normalization: %d tickers", len(ticker_trial_counts))

    rollup = build_company_rollup(records, as_of, min_confidence, ticker_trial_counts)

    # Summary stats
    severities = [v["graveyard_severity_score"] for v in rollup.values()]

    result = {
        "schema": SCHEMA_VERSION,
        "built_as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_confidence": min_confidence,
        "n_tickers": len(rollup),
        "total_events": sum(v["n_graveyard_events"] for v in rollup.values()),
        "severity_p50": round(sorted(severities)[len(severities) // 2], 2) if severities else 0,
        "severity_p90": round(sorted(severities)[int(len(severities) * 0.9)], 2) if severities else 0,
        "tickers": rollup,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s (%d tickers)", output_path, len(rollup))

    return result


def main():
    parser = argparse.ArgumentParser(description="Build graveyard company rollup (Spec 033)")
    parser.add_argument("--catalog", type=Path, default=PROJECT_ROOT / "data" / "graveyard" / "graveyard_catalog.json")
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "data" / "graveyard" / "graveyard_company_rollup.json"
    )
    parser.add_argument("--min-confidence", default="MEDIUM", choices=["HIGH", "MEDIUM", "LOW"])
    args = parser.parse_args()

    result = build_graveyard_rollup(
        catalog_path=args.catalog,
        output_path=args.output,
        min_confidence=args.min_confidence,
    )
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
