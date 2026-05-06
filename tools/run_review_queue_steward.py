#!/usr/bin/env python3
"""
tools/run_review_queue_steward.py
Lightweight replacement for run_agent_direct.py --agent review_queue_steward.

Reads today's review_queue.csv from the snapshot, triages into
immediate/monitor/watch buckets, and writes a memory file.
No LLM call — deterministic, fast, always produces an artifact.
"""
import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SNAPSHOT_DATE = date.today().isoformat()
SNAPSHOT_DIR = REPO / "data" / "snapshots" / SNAPSHOT_DATE
QUEUE_CSV = SNAPSHOT_DIR / "review_queue.csv"
MEMORY_DIR = REPO / "agents" / "review_queue_steward" / "memory"
MEMORY_DIR.mkdir(exist_ok=True)
MEMORY_FILE = MEMORY_DIR / f"{SNAPSHOT_DATE}.md"


def triage_action(row: dict) -> str:
    action = row.get("action", "").lower()
    if action in ("no_add_until_review", "immediate_review"):
        return "IMMEDIATE"
    if action in ("monitor", "watch"):
        return "MONITOR"
    return "WATCH"


def main():
    if not QUEUE_CSV.exists():
        print(f"[review_queue_steward] No queue for {SNAPSHOT_DATE} — skip", file=sys.stderr)
        sys.exit(0)

    rows = []
    with open(QUEUE_CSV, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    immediate = [r for r in rows if triage_action(r) == "IMMEDIATE"]
    monitor = [r for r in rows if triage_action(r) == "MONITOR"]
    watch = [r for r in rows if triage_action(r) == "WATCH"]

    # Compare to yesterday if memory file exists
    yesterday = date.fromordinal(date.today().toordinal() - 1).isoformat()
    yesterday_file = MEMORY_DIR / f"{yesterday}.md"
    prev_immediate = set()
    if yesterday_file.exists():
        for line in yesterday_file.read_text().split("\n"):
            if line.startswith("- **") or line.startswith("- "):
                ticker = line.strip().lstrip("- **").split("**")[0].split(" ")[0]
                if ticker and len(ticker) <= 6 and ticker.isupper():
                    prev_immediate.add(ticker)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    lines = [
        f"# Review Queue Steward Memory — {SNAPSHOT_DATE}",
        "",
        f"Generated: {now}  |  Total queue: {len(rows)} names",
        "",
        f"## IMMEDIATE ({len(immediate)}) — no_add_until_review / immediate_review",
        "",
    ]
    for r in immediate:
        ticker = r.get("ticker", "?")
        tier = r.get("tier", "?")
        reason = r.get("action_reason", r.get("action", ""))
        cat = r.get("catalyst_family", "")
        days = r.get("catalyst_days", "")
        new_flag = " ⚠️ NEW" if ticker not in prev_immediate else ""
        lines.append(f"- **{ticker}** ({tier}) — {reason}" + (f" | {cat} {days}d" if cat else "") + new_flag)

    lines += [
        "",
        f"## MONITOR ({len(monitor)})",
        "",
    ]
    for r in monitor[:10]:
        ticker = r.get("ticker", "?")
        tier = r.get("tier", "?")
        reason = r.get("action_reason", r.get("action", ""))
        lines.append(f"- {ticker} ({tier}) — {reason}")
    if len(monitor) > 10:
        lines.append(f"- ... and {len(monitor) - 10} more")

    lines += [
        "",
        f"## WATCH ({len(watch)})",
        "",
        "_(top 5 only)_",
    ]
    for r in watch[:5]:
        ticker = r.get("ticker", "?")
        tier = r.get("tier", "?")
        lines.append(f"- {ticker} ({tier})")

    lines += [
        "",
        "## Alert",
        "",
    ]
    if len(immediate) >= 5:
        lines.append(f"HIGH — {len(immediate)} names in IMMEDIATE bucket")
    elif len(immediate) >= 3:
        lines.append(f"MEDIUM — {len(immediate)} names in IMMEDIATE bucket")
    elif len(immediate) >= 1:
        lines.append(f"LOW — {len(immediate)} name(s) in IMMEDIATE bucket")
    else:
        lines.append("NONE — queue clean")

    MEMORY_FILE.write_text("\n".join(lines) + "\n")
    print(
        f"[review_queue_steward] {SNAPSHOT_DATE}: {len(immediate)} immediate, "
        f"{len(monitor)} monitor, {len(watch)} watch → {MEMORY_FILE}"
    )


if __name__ == "__main__":
    main()
