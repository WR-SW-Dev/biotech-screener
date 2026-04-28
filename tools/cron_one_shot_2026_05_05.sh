#!/usr/bin/env bash
# cron_one_shot_2026_05_05.sh — First-week review of the post-snapshot supervisor.
#
# Fires once on Tuesday 2026-05-05 ~17:00 ET, one week after the supervisor
# shipped (2026-04-28). Reads the supervisor's ledger artifacts for every
# weekday in the window, tallies per-task outcomes, cross-checks daily_production
# logs for hangs/timeouts in the OTHER post-snapshot subprocesses (5b, 5o, 5p,
# 5q, 6) that Phase 1 did NOT cover, and writes a review markdown.
#
# Self-skips on any other date and on re-invocations (marker file).
# Read-only: no code changes, no kicked-off runs.
#
# Cron entry (annual recurrence; marker prevents re-runs within the same year):
#   0 17 5 5 * /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_one_shot_2026_05_05.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/one_shot.log 2>&1

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
TARGET_DATE="2026-05-05"
MARKER="${REPO_ROOT}/logs/.one_shot_${TARGET_DATE}.done"
REPORT="${REPO_ROOT}/artifacts/post_snapshot_done/REVIEW_${TARGET_DATE}.md"
LOG_PREFIX="[$(date -Iseconds)]"

if [ -f "$MARKER" ]; then
    echo "${LOG_PREFIX} SKIP: already fired (marker $MARKER exists)"
    exit 0
fi

TODAY=$(date +%Y-%m-%d)
if [ "$TODAY" != "$TARGET_DATE" ]; then
    echo "${LOG_PREFIX} SKIP: today=${TODAY} != target=${TARGET_DATE}"
    exit 0
fi

echo "${LOG_PREFIX} Firing supervisor first-week review (window 2026-04-28 → 2026-05-05)"

cd "$REPO_ROOT"
mkdir -p "$(dirname "$REPORT")"

/usr/bin/python3 - "$REPO_ROOT" "$REPORT" <<'PYEOF'
"""Inline supervisor first-week review.

Args (sys.argv): repo_root, report_path
"""
import json
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(sys.argv[1])
REPORT = Path(sys.argv[2])
LEDGER_DIR = REPO_ROOT / "artifacts" / "post_snapshot_done"
LOG_DIR = REPO_ROOT / "logs"

# Weekdays in the review window (skip Sat 05-02, Sun 05-03)
WINDOW = []
d = date(2026, 4, 28)
end = date(2026, 5, 5)
while d <= end:
    if d.weekday() < 5:
        WINDOW.append(d.isoformat())
    d += timedelta(days=1)

# --- Per-day, per-task outcome tally ---
per_task = {"aact": Counter(), "herald": Counter()}
per_day = {}
missing_days = []
unknown_tasks = Counter()

for day in WINDOW:
    ledger = LEDGER_DIR / f"{day}.jsonl"
    complete = LEDGER_DIR / f"{day}.complete"
    if not ledger.exists():
        missing_days.append(day)
        per_day[day] = {"ledger_present": False, "complete": False, "outcomes": {}}
        continue
    outcomes = {}
    with ledger.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = rec.get("name", "?")
            status = rec.get("status", "?")
            # Last write wins per task (re-runs append; final state is what matters)
            outcomes[name] = status
            if name not in per_task:
                unknown_tasks[name] += 1
    for name, status in outcomes.items():
        if name in per_task:
            per_task[name][status] += 1
    per_day[day] = {
        "ledger_present": True,
        "complete": complete.exists(),
        "outcomes": outcomes,
    }

# --- Cross-check: did non-Phase-1 subprocesses fail during the week? ---
# Step labels from run_daily_production.py
PHASE2_STEPS = {
    "5b drift": ("[5b]", "drift"),
    "5o construction_v2_shadow": ("Construction v2 shadow", "construction_v2_shadow"),
    "5p build_daily_v2_compare": ("V2 compare", "build_daily_v2_compare"),
    "5q rolling_options_ev_summary": ("Options EV summary", "rolling_options_ev"),
    "6 PIT backfill": ("[6]", "backfill"),
}
phase2_findings = {label: [] for label in PHASE2_STEPS}

for day in WINDOW:
    log_path = LOG_DIR / f"daily_production_{day}.log"
    if not log_path.exists():
        continue
    try:
        text = log_path.read_text(errors="ignore")
    except OSError:
        continue
    for label, (marker, _hint) in PHASE2_STEPS.items():
        # Find lines mentioning the step that ALSO say timed out or non-zero exit
        for line in text.splitlines():
            if marker.lower() not in line.lower():
                continue
            if (
                "timed out" in line.lower()
                or "TIMED OUT" in line
                or re.search(r"exit (?!0)\d+", line)
                or "FAILED" in line
            ):
                phase2_findings[label].append((day, line.strip()[:180]))

# --- Build report ---
def fmt_counter(c: Counter) -> str:
    if not c:
        return "(no entries)"
    return ", ".join(f"{k}={v}" for k, v in sorted(c.items()))

lines = []
lines.append(f"# Post-snapshot supervisor — first-week review")
lines.append("")
lines.append(f"**Window:** 2026-04-28 → 2026-05-05 (6 weekdays)  ")
lines.append(f"**Phase 1 tasks:** AACT (Step 5n), Herald (Step 5l.5)")
lines.append("")
lines.append("## Per-task tally")
lines.append("")
lines.append("| Task | ok | skipped | not_applicable | fail | timeout |")
lines.append("|---|---|---|---|---|---|")
for name in ("aact", "herald"):
    c = per_task[name]
    lines.append(
        f"| {name} | {c.get('ok', 0)} | {c.get('skipped', 0)} | "
        f"{c.get('not_applicable', 0)} | {c.get('fail', 0)} | {c.get('timeout', 0)} |"
    )
lines.append("")

if unknown_tasks:
    lines.append(f"⚠ Unknown task names in ledgers: {dict(unknown_tasks)}")
    lines.append("")

lines.append("## Per-day completion")
lines.append("")
lines.append("| Date | ledger | complete marker | aact | herald |")
lines.append("|---|---|---|---|---|")
for day in WINDOW:
    info = per_day[day]
    lp = "✓" if info["ledger_present"] else "✗"
    cp = "✓" if info["complete"] else "✗"
    a = info["outcomes"].get("aact", "—")
    h = info["outcomes"].get("herald", "—")
    lines.append(f"| {day} | {lp} | {cp} | {a} | {h} |")
lines.append("")

if missing_days:
    lines.append(f"⚠ Days with no supervisor ledger: {', '.join(missing_days)}")
    lines.append("")

lines.append("## Phase 2 candidates (non-Phase-1 subprocess hangs/timeouts)")
lines.append("")
any_phase2_hits = False
for label, hits in phase2_findings.items():
    if not hits:
        continue
    any_phase2_hits = True
    lines.append(f"### {label}")
    lines.append("")
    for day, line in hits:
        lines.append(f"- `{day}` — `{line}`")
    lines.append("")
if not any_phase2_hits:
    lines.append("No timeouts/non-zero-exits observed for any non-Phase-1 subprocess in the window.")
    lines.append("")

# --- Recommendation ---
lines.append("## Recommendation")
lines.append("")
hard_fails = sum(per_task[t].get("fail", 0) + per_task[t].get("timeout", 0) for t in per_task)
phase1_attempts = sum(per_task[t].get("ok", 0) + per_task[t].get("fail", 0) + per_task[t].get("timeout", 0) for t in per_task)
phase2_failed_steps = sum(1 for hits in phase2_findings.values() if hits)

if any_phase2_hits and phase2_failed_steps >= 2:
    lines.append(
        f"**BUILD PHASE 2** — {phase2_failed_steps} non-Phase-1 step(s) hit a hang/timeout in the window. "
        "Lift them into the supervisor next."
    )
elif any_phase2_hits:
    lines.append(
        f"**REVISIT IN ANOTHER WEEK** — exactly 1 non-Phase-1 step hit a fault; could be transient. "
        "If the same step fails again next week, build Phase 2 covering at minimum that step."
    )
elif hard_fails > 0:
    lines.append(
        f"**HOLD ON PHASE 2** — {hard_fails} Phase-1 task fault(s) occurred but no Phase-2 candidates surfaced. "
        "Investigate Phase-1 fault root cause before expanding scope."
    )
elif phase1_attempts == 0:
    lines.append(
        "**REVISIT IN ANOTHER WEEK** — supervisor did no real work this week (all skips / not_applicable). "
        "Cannot evaluate without observed faults."
    )
else:
    lines.append(
        f"**HOLD ON PHASE 2** — supervisor completed cleanly across the window "
        f"({phase1_attempts} active attempts, 0 faults; no non-Phase-1 hangs). "
        "Re-evaluate after another month or on next observed kill."
    )

lines.append("")
lines.append("---")
lines.append("")
lines.append(f"_Generated by `tools/cron_one_shot_2026_05_05.sh` at audit time._")

REPORT.write_text("\n".join(lines))
print(f"Wrote review → {REPORT}")
PYEOF

echo "${LOG_PREFIX} Review report ↓↓↓"
cat "$REPORT"
echo "${LOG_PREFIX} Review report ↑↑↑"
echo "${LOG_PREFIX} Full report: $REPORT"

touch "$MARKER"
echo "${LOG_PREFIX} Done. Marker written: $MARKER"
