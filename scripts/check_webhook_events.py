#!/usr/bin/env python
"""Check for new webhook events and report them.

Designed to run as a cron job — stays SILENT when no new events.
When new events are found, prints them for agent delivery.

Usage:
    python scripts/check_webhook_events.py

Cron integration:
    Schedule every 15 minutes to check for new FDA/CT.gov events.
    Output is delivered to the user when events are found.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("BIOTECH_PROJECT_DIR", Path(__file__).resolve().parent.parent))
EVENTS_FILE = PROJECT_DIR / "output" / "webhook_events.jsonl"
SEEN_FILE = PROJECT_DIR / "output" / ".webhook_seen_ids"


def load_seen_ids() -> set[str]:
    """Load previously seen event IDs."""
    if not SEEN_FILE.exists():
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_seen_ids(ids: set[str]) -> None:
    """Save seen event IDs."""
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        for eid in sorted(ids):
            f.write(eid + "\n")


def load_new_events() -> list[dict]:
    """Load events that haven't been seen yet."""
    if not EVENTS_FILE.exists():
        return []

    seen = load_seen_ids()
    new_events = []

    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                eid = event.get("event_id", "")
                if eid and eid not in seen:
                    new_events.append(event)
                    seen.add(eid)
            except json.JSONDecodeError:
                continue

    if new_events:
        save_seen_ids(seen)

    return new_events


def main():
    new_events = load_new_events()

    if not new_events:
        return  # Silent — nothing to report

    print(f"📡 {len(new_events)} new biotech event(s) detected")
    print()

    for event in new_events:
        source = event.get("source", "Unknown")
        etype = event.get("event_type", "unknown")
        ticker = event.get("ticker", "—")
        desc = event.get("description", "")

        # Format based on source
        if source == "FDA":
            drug = event.get("drug", "Unknown drug")
            print(f"  🔵 FDA Alert: {etype} — {drug}")
            if ticker and ticker != "—":
                print(f"     Ticker: {ticker}")
            print(f"     {desc}")
        elif source == "ClinicalTrials.gov":
            nct = event.get("nct_id", "")
            new_status = event.get("new_status", "")
            print(f"  🟡 CT.gov Update: {etype} — {nct}")
            if ticker and ticker != "—":
                print(f"     Ticker: {ticker}")
            if new_status:
                print(f"     New status: {new_status}")
            print(f"     {desc}")
        else:
            print(f"  ⚪ {source}: {etype}")
            if ticker and ticker != "—":
                print(f"     Ticker: {ticker}")
            print(f"     {desc}")

        print()

    print(f"Total new events: {len(new_events)}")
    print("Run `hermes -z 'Analyze the latest biotech webhook events'` for agent analysis.")


if __name__ == "__main__":
    main()
