#!/usr/bin/env python3
"""Stage 2: Normalize earnings events and generate an ICS calendar file.

Outlook can subscribe to the .ics file (local or served via file share / HTTP).
Each rerun overwrites the file with the current state — Outlook picks up changes
on its next refresh.

Usage:
    python scripts/sync_earnings_to_outlook.py \
        --raw-file artifacts/earnings_sync/earnings_raw_2026-04-02.json \
        --ics-out artifacts/earnings_sync/biotech_earnings.ics \
        --timezone US/Eastern
"""

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from icalendar import Calendar, Event

MANAGED_TAG = "Managed by Bellringer"
CALENDAR_NAME = "Biotech Earnings"

TIME_HINTS = {
    "bmo": (8, 0),  # before market open
    "amc": (16, 5),  # after market close
    "unknown": (12, 0),
}

DURATION_MINUTES = 30


def normalize_events(raw: dict) -> list[dict]:
    events = []
    for row in raw.get("rows", []):
        symbol = row["symbol"]
        edate = row["earnings_date"]
        hint = row.get("earnings_time_hint", "unknown")
        hour, minute = TIME_HINTS.get(hint, TIME_HINTS["unknown"])
        confidence = "low" if hint == "unknown" else "medium"

        events.append(
            {
                "external_id": f"earnings:{symbol}:{edate}",
                "symbol": symbol,
                "company": row.get("company", symbol),
                "earnings_date": edate,
                "earnings_time_hint": hint,
                "hour": hour,
                "minute": minute,
                "source_confidence": confidence,
                "eps_estimate": row.get("eps_estimate"),
                "revenue_estimate": row.get("revenue_estimate"),
            }
        )
    return events


def build_ics(events: list[dict], tz_name: str, fetched_at: str) -> Calendar:
    cal = Calendar()
    cal.add("prodid", "-//Bellringer//Biotech Earnings Sync//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", CALENDAR_NAME)
    cal.add("x-wr-timezone", tz_name)

    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except ImportError:
        from dateutil import tz as tz_mod

        tz = tz_mod.gettz(tz_name)

    for ev in events:
        year, month, day = (int(x) for x in ev["earnings_date"].split("-"))
        dt_start = datetime(year, month, day, ev["hour"], ev["minute"], tzinfo=tz)
        dt_end = dt_start + timedelta(minutes=DURATION_MINUTES)

        event = Event()
        event.add("summary", f"{ev['symbol']} earnings")
        event.add("dtstart", dt_start)
        event.add("dtend", dt_end)
        event.add("dtstamp", datetime.now(timezone.utc))

        # Stable UID so Outlook can match updates across file rewrites
        uid_input = ev["external_id"].encode()
        uid_hash = hashlib.sha256(uid_input).hexdigest()[:16]
        event.add("uid", f"{uid_hash}@bellringer")

        # Description with metadata
        lines = [
            f"Company: {ev['company']}",
            f"Symbol: {ev['symbol']}",
            f"Timing: {ev['earnings_time_hint']}",
            f"Confidence: {ev['source_confidence']}",
        ]
        if ev.get("eps_estimate"):
            lines.append(f"EPS estimate: {ev['eps_estimate']:.2f}")
        if ev.get("revenue_estimate"):
            rev_m = ev["revenue_estimate"] / 1e6
            lines.append(f"Revenue estimate: ${rev_m:.0f}M")
        lines.append(f"\nSource: yfinance | Fetched: {fetched_at}")
        lines.append(f"[{MANAGED_TAG}]")
        event.add("description", "\n".join(lines))

        # Categories for Outlook filtering
        event.add("categories", ["Earnings", "Biotech"])

        # 1 hour reminder
        from icalendar import Alarm

        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", f"{ev['symbol']} earnings in 1 hour")
        alarm.add("trigger", timedelta(hours=-1))
        event.add_component(alarm)

        cal.add_component(event)

    return cal


def main():
    parser = argparse.ArgumentParser(description="Generate ICS from earnings events")
    parser.add_argument("--raw-file", required=True, type=Path)
    parser.add_argument("--ics-out", required=True, type=Path)
    parser.add_argument("--timezone", default="US/Eastern")
    args = parser.parse_args()

    raw = json.loads(args.raw_file.read_text())
    print(f"Loaded {len(raw.get('rows', []))} raw events from {args.raw_file}")

    events = normalize_events(raw)
    print(f"Normalized {len(events)} events")

    # Write normalized artifact
    norm_path = args.raw_file.parent / args.raw_file.name.replace("raw", "normalized")
    norm_path.write_text(
        json.dumps(
            {"schema": "earnings_normalized.v1", "events": events},
            indent=2,
            default=str,
        )
    )
    print(f"Wrote {norm_path}")

    # Build and write ICS
    cal = build_ics(events, args.timezone, raw.get("fetched_at_utc", ""))
    args.ics_out.parent.mkdir(parents=True, exist_ok=True)
    args.ics_out.write_bytes(cal.to_ical())
    print(f"Wrote {args.ics_out} ({len(events)} events)")

    # Summary by date
    from collections import Counter

    dates = Counter(e["earnings_date"] for e in events)
    print("\nEarnings by date:")
    for dt, cnt in sorted(dates.items()):
        print(f"  {dt}: {cnt}")


if __name__ == "__main__":
    main()
