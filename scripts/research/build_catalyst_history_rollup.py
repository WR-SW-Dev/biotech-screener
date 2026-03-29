#!/usr/bin/env python3
"""Build catalyst history rollup — per-ticker summary of event history.

Reads catalyst_history_events.jsonl and produces per-ticker rollup
with event counts, source mix, and recency metrics.

Phase A: Infrastructure only.

Output:
    data/catalyst_history/catalyst_history_rollup.json

Usage:
    python scripts/research/build_catalyst_history_rollup.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("catalyst_history_rollup")

SCHEMA_VERSION = "catalyst_history_rollup.v1"

NEGATIVE_EVENT_TYPES = frozenset(
    {
        "FDA_CRL",
        "FDA_RTF",
        "FDA_WARNING_LETTER",
    }
)


def load_events(events_path: Path) -> List[Dict]:
    """Load events from JSONL file."""
    events = []
    if not events_path.exists():
        return events
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def _days_since(date_str: str, as_of: str) -> int:
    try:
        d = datetime.fromisoformat(date_str[:10])
        a = datetime.fromisoformat(as_of[:10])
        return (a - d).days
    except (ValueError, TypeError):
        return 9999


def build_rollup(events: List[Dict], as_of_date: str) -> Dict[str, Dict]:
    """Build per-ticker rollup from event list."""
    ticker_events: Dict[str, List[Dict]] = defaultdict(list)
    for ev in events:
        ticker_events[ev.get("ticker", "")].append(ev)

    rollup = {}
    for ticker, evts in sorted(ticker_events.items()):
        if not ticker:
            continue

        sources = Counter(e.get("source_family", "") for e in evts)
        event_types = Counter(e.get("event_type", "") for e in evts)
        dates = sorted(e.get("event_date", "") for e in evts if e.get("event_date"))

        # Window counts
        n_365d = sum(1 for e in evts if _days_since(e.get("event_date", ""), as_of_date) <= 365)
        n_neg_365d = sum(
            1
            for e in evts
            if e.get("event_type", "") in NEGATIVE_EVENT_TYPES
            and _days_since(e.get("event_date", ""), as_of_date) <= 365
        )
        n_fda_365d = sum(
            1
            for e in evts
            if e.get("source_family") == "FDA" and _days_since(e.get("event_date", ""), as_of_date) <= 365
        )
        n_sec_365d = sum(
            1
            for e in evts
            if e.get("source_family") == "SEC" and _days_since(e.get("event_date", ""), as_of_date) <= 365
        )

        # Last material event
        neg_dates = sorted(e.get("event_date", "") for e in evts if e.get("event_type", "") in NEGATIVE_EVENT_TYPES)

        rollup[ticker] = {
            "ticker": ticker,
            "n_events_total": len(evts),
            "n_events_365d": n_365d,
            "n_negative_reg_events_365d": n_neg_365d,
            "n_fda_events_365d": n_fda_365d,
            "n_sec_events_365d": n_sec_365d,
            "source_mix": dict(sources.most_common()),
            "event_type_top5": dict(event_types.most_common(5)),
            "last_event_date": dates[-1] if dates else None,
            "last_negative_reg_event_date": neg_dates[-1] if neg_dates else None,
        }

    return rollup


def main():
    parser = argparse.ArgumentParser(description="Build catalyst history rollup (Spec 034)")
    parser.add_argument(
        "--events", type=Path, default=PROJECT_ROOT / "data" / "catalyst_history" / "catalyst_history_events.jsonl"
    )
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "data" / "catalyst_history" / "catalyst_history_rollup.json"
    )
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    events = load_events(args.events)
    logger.info("Loaded %d events", len(events))

    rollup = build_rollup(events, args.as_of_date)

    result = {
        "schema": SCHEMA_VERSION,
        "as_of_date": args.as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(rollup),
        "n_events_total": sum(v["n_events_total"] for v in rollup.values()),
        "tickers": rollup,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Wrote %s (%d tickers)", args.output, len(rollup))


if __name__ == "__main__":
    main()
