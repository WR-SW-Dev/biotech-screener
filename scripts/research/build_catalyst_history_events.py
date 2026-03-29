#!/usr/bin/env python3
"""Build catalyst history event ledger from existing caches.

Reads SEC 8-K cache, PDUFA dates, ADCOM calendar, CTgov catalyst events,
and Federal Register/openFDA caches to produce a unified PIT-safe event
ledger. Every row is one publicly knowable event instance.

Phase A: Infrastructure only — no scoring changes.

Output:
    data/catalyst_history/catalyst_history_events.jsonl

Usage:
    python scripts/research/build_catalyst_history_events.py
    python scripts/research/build_catalyst_history_events.py --as-of-date 2026-03-28
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("catalyst_history")

SCHEMA_VERSION = "catalyst_history_event.v1"


def _event_id(ticker: str, event_type: str, event_date: str, source: str) -> str:
    key = f"{ticker}|{event_type}|{event_date}|{source}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _dedupe_key(ticker: str, event_type: str, event_date: str, source_family: str) -> str:
    return f"{ticker}|{event_type}|{event_date}|{source_family}"


def _source_family(source: str) -> str:
    """Collapse source into family for dedup."""
    s = source.upper()
    if "SEC" in s or "8K" in s or "10Q" in s or "10K" in s or "6K" in s:
        return "SEC"
    if "FDA" in s or "ADCOM" in s or "PDUFA" in s:
        return "FDA"
    if "FEDERAL" in s or "REGISTER" in s:
        return "FEDERAL_REGISTER"
    if "CTGOV" in s or "TRIAL" in s:
        return "CTGOV"
    if "OPENFDA" in s:
        return "FDA"
    return "OTHER"


def collect_sec_8k_events(cache_dir: Path) -> List[Dict]:
    """Collect events from SEC 8-K cache files."""
    events = []
    for path in sorted(cache_dir.glob("8k_catalysts_*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(data, list):
            continue

        for rec in data:
            ticker = rec.get("ticker", "")
            event_type = rec.get("event_type", "")
            event_date = rec.get("event_date", "")
            if not ticker or not event_date:
                continue

            events.append(
                {
                    "ticker": ticker,
                    "event_type": event_type,
                    "event_date": event_date[:10],
                    "pit_available_at": (rec.get("disclosed_at") or event_date)[:10],
                    "source": rec.get("source", "SEC_8K_FILING"),
                    "confidence": rec.get("confidence", "MEDIUM"),
                    "event_name": rec.get("event_name", ""),
                    "document_ref": rec.get("accession_number", ""),
                    "filing_form": "8-K",
                }
            )

    return events


def collect_pdufa_events(data_dir: Path) -> List[Dict]:
    """Collect events from PDUFA dates file."""
    path = data_dir / "pdufa_dates.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    entries = data if isinstance(data, list) else data.get("entries", [])

    events = []
    for rec in entries:
        ticker = rec.get("ticker", "")
        pdufa_date = rec.get("pdufa_date", "")
        if not ticker or not pdufa_date:
            continue

        events.append(
            {
                "ticker": ticker,
                "event_type": "FDA_PDUFA_DATE",
                "event_date": pdufa_date[:10],
                "pit_available_at": pdufa_date[:10],
                "source": "FDA_CALENDAR",
                "confidence": rec.get("confidence", "HIGH"),
                "event_name": f"PDUFA: {rec.get('drug_name', '')} — {rec.get('indication', '')}",
                "drug_name": rec.get("drug_name"),
                "document_ref": rec.get("source_url", ""),
            }
        )

    return events


def collect_adcom_events(cache_dir: Path) -> List[Dict]:
    """Collect events from FDA ADCOM calendar cache."""
    events = []
    for path in sorted(cache_dir.glob("adcom_calendar_*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        entries = data if isinstance(data, list) else data.get("events", [])
        for rec in entries:
            ticker = rec.get("ticker", "")
            event_date = rec.get("event_date") or rec.get("meeting_date", "")
            if not ticker or not event_date:
                continue

            events.append(
                {
                    "ticker": ticker,
                    "event_type": "FDA_ADCOM",
                    "event_date": event_date[:10],
                    "pit_available_at": event_date[:10],
                    "source": "FDA_ADCOM_CALENDAR",
                    "confidence": rec.get("confidence", "HIGH"),
                    "event_name": rec.get("event_name", rec.get("drug_name", "")),
                    "drug_name": rec.get("drug_name"),
                    "document_ref": rec.get("source_url", ""),
                }
            )

    return events


def collect_ctgov_catalyst_events(production_dir: Path, max_files: int = 0) -> List[Dict]:
    """Collect events from historical catalyst_events_*.json files."""
    events = []
    files = sorted(f for f in production_dir.glob("catalyst_events_*.json") if "vnext" not in f.name)
    if max_files > 0:
        files = files[-max_files:]

    for path in files:
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        summaries = data.get("summaries", [])
        if isinstance(summaries, dict):
            summaries = list(summaries.values())
        if not isinstance(summaries, list):
            continue
        as_of = data.get("run_metadata", {}).get("as_of_date", "")

        for summary in summaries:
            if not isinstance(summary, dict):
                continue
            ticker = summary.get("ticker", "")
            for ev in summary.get("events", []):
                event_date = ev.get("event_date") or ev.get("actual_date") or ev.get("disclosed_at", "")
                event_type = ev.get("event_type", ev.get("type", ""))
                if not ticker or not event_date or not event_type:
                    continue

                events.append(
                    {
                        "ticker": ticker,
                        "event_type": event_type,
                        "event_date": event_date[:10],
                        "pit_available_at": (ev.get("disclosed_at") or as_of or event_date)[:10],
                        "source": ev.get("source", "CTGOV_CALENDAR"),
                        "confidence": str(ev.get("confidence", "MEDIUM")),
                        "event_name": ev.get("event_name", ev.get("description", "")),
                        "nct_id": ev.get("nct_id"),
                        "document_ref": ev.get("nct_id", ""),
                    }
                )

    return events


def collect_openfda_events(cache_dir: Path) -> List[Dict]:
    """Collect events from openFDA approval cache."""
    events = []
    openfda_dir = cache_dir / "openfda"
    if not openfda_dir.exists():
        return events

    for path in sorted(openfda_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        entries = data if isinstance(data, list) else data.get("events", [])
        for rec in entries:
            ticker = rec.get("ticker", "")
            event_date = rec.get("event_date") or rec.get("approval_date", "")
            if not ticker or not event_date:
                continue

            events.append(
                {
                    "ticker": ticker,
                    "event_type": rec.get("event_type", "FDA_APPROVAL"),
                    "event_date": event_date[:10],
                    "pit_available_at": event_date[:10],
                    "source": "OPENFDA",
                    "confidence": "HIGH",
                    "event_name": rec.get("event_name", rec.get("drug_name", "")),
                    "drug_name": rec.get("drug_name"),
                    "document_ref": rec.get("application_number", ""),
                }
            )

    return events


def deduplicate_events(events: List[Dict]) -> List[Dict]:
    """Deduplicate events by canonical key, keeping highest-confidence."""
    conf_rank = {"HIGH": 3, "MEDIUM": 2, "MED": 2, "LOW": 1}

    by_key: Dict[str, Dict] = {}
    for ev in events:
        sf = _source_family(ev.get("source", ""))
        key = _dedupe_key(ev["ticker"], ev["event_type"], ev["event_date"], sf)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = ev
        else:
            # Keep higher confidence
            new_conf = conf_rank.get(str(ev.get("confidence", "")).upper(), 0)
            old_conf = conf_rank.get(str(existing.get("confidence", "")).upper(), 0)
            if new_conf > old_conf:
                by_key[key] = ev

    return list(by_key.values())


def build_catalyst_history_events(
    *,
    sec_cache_dir: Path = PROJECT_ROOT / "cache" / "sec" / "8k_catalysts",
    fda_cache_dir: Path = PROJECT_ROOT / "cache" / "fda",
    production_dir: Path = PROJECT_ROOT / "production_data",
    output_path: Path = PROJECT_ROOT / "data" / "catalyst_history" / "catalyst_history_events.jsonl",
    as_of_date: Optional[str] = None,
    max_ctgov_files: int = 50,
) -> Dict[str, Any]:
    """Build catalyst history event ledger."""
    all_events: List[Dict] = []

    # Collect from all sources
    sec_events = collect_sec_8k_events(sec_cache_dir)
    logger.info("SEC 8-K: %d raw events", len(sec_events))
    all_events.extend(sec_events)

    pdufa_events = collect_pdufa_events(production_dir)
    logger.info("PDUFA: %d events", len(pdufa_events))
    all_events.extend(pdufa_events)

    adcom_events = collect_adcom_events(fda_cache_dir)
    logger.info("ADCOM: %d events", len(adcom_events))
    all_events.extend(adcom_events)

    ctgov_events = collect_ctgov_catalyst_events(production_dir, max_ctgov_files)
    logger.info("CTgov catalyst: %d raw events", len(ctgov_events))
    all_events.extend(ctgov_events)

    openfda_events = collect_openfda_events(fda_cache_dir)
    logger.info("openFDA: %d events", len(openfda_events))
    all_events.extend(openfda_events)

    # PIT filter
    if as_of_date:
        before = len(all_events)
        all_events = [e for e in all_events if e.get("pit_available_at", "9999") <= as_of_date]
        logger.info("PIT filter (%s): %d → %d events", as_of_date, before, len(all_events))

    # Assign event IDs and dedupe keys
    for ev in all_events:
        ev["event_id"] = _event_id(ev["ticker"], ev["event_type"], ev["event_date"], ev.get("source", ""))
        sf = _source_family(ev.get("source", ""))
        ev["dedupe_key"] = _dedupe_key(ev["ticker"], ev["event_type"], ev["event_date"], sf)
        ev["source_family"] = sf
        ev["schema_version"] = SCHEMA_VERSION

    # Deduplicate
    before_dedup = len(all_events)
    all_events = deduplicate_events(all_events)
    logger.info("Dedup: %d → %d events", before_dedup, len(all_events))

    # Sort by event_date
    all_events.sort(key=lambda e: (e.get("event_date", ""), e.get("ticker", "")))

    # Summary
    sources = Counter(e.get("source_family", "") for e in all_events)
    event_types = Counter(e.get("event_type", "") for e in all_events)
    tickers = set(e["ticker"] for e in all_events)

    result = {
        "n_events": len(all_events),
        "n_tickers": len(tickers),
        "source_counts": dict(sources.most_common()),
        "event_type_counts": dict(event_types.most_common(20)),
    }

    # Write JSONL
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for ev in all_events:
            f.write(json.dumps(ev, default=str) + "\n")
    logger.info("Wrote %s (%d events, %d tickers)", output_path, len(all_events), len(tickers))

    return result


def main():
    parser = argparse.ArgumentParser(description="Build catalyst history event ledger (Spec 034)")
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--max-ctgov-files", type=int, default=50)
    args = parser.parse_args()

    result = build_catalyst_history_events(
        as_of_date=args.as_of_date,
        max_ctgov_files=args.max_ctgov_files,
    )
    if "error" in result:
        logger.error(result["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
