#!/usr/bin/env bash
# cron_one_shot_2026_05_07.sh — First-snapshot verification of catalyst_quality
# (Spec 078 Lanes A+B), one day after Spec 071+078 shipped to origin/main on
# 2026-05-06.
#
# Confirms the new `catalyst_quality` column lands in 2026-05-07 rankings.csv,
# reports per-bucket distribution + top-30/top-60 counts, lists every ticker
# flagged as `corporate_update` or `low_confidence`, and surfaces stale-looking
# `registry_only` rows (PCD in past or catalyst_days < 0) for false-stale review.
#
# Read-only / report-only: no scoring change, no rerun, no commit.
#
# Cron entry (annual recurrence; marker prevents re-runs within the same year):
#   0 17 7 5 * /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_one_shot_2026_05_07.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/one_shot.log 2>&1

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
TARGET_DATE="2026-05-07"
MARKER="${REPO_ROOT}/logs/.one_shot_${TARGET_DATE}_catalyst_quality.done"
REPORT="${REPO_ROOT}/artifacts/audit/catalyst_quality_first_snapshot_${TARGET_DATE}.md"
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

SNAPSHOT="${REPO_ROOT}/data/snapshots/${TARGET_DATE}/rankings.csv"
if [ ! -f "$SNAPSHOT" ]; then
    echo "${LOG_PREFIX} SNAPSHOT_MISSING: $SNAPSHOT not found; not writing marker — will retry on next cron tick if rescheduled"
    exit 0
fi

echo "${LOG_PREFIX} Firing catalyst_quality first-snapshot review on $SNAPSHOT"

cd "$REPO_ROOT"
mkdir -p "$(dirname "$REPORT")"

/usr/bin/python3 - "$SNAPSHOT" "$REPORT" "$TARGET_DATE" <<'PYEOF'
"""Inline catalyst_quality first-snapshot review.

Args (sys.argv): snapshot_csv, report_path, target_date
"""
import csv
import sys
from collections import Counter
from datetime import date

SNAPSHOT = sys.argv[1]
REPORT = sys.argv[2]
TARGET_DATE = sys.argv[3]
TODAY = date.fromisoformat(TARGET_DATE)

with open(SNAPSHOT, newline="") as f:
    rows = list(csv.DictReader(f))

cols = list(rows[0].keys()) if rows else []
has_cq = "catalyst_quality" in cols

lines = []
lines.append(f"# catalyst_quality — first-snapshot verification ({TARGET_DATE})")
lines.append("")
lines.append(f"**Source:** `{SNAPSHOT}`  ")
lines.append(f"**Total rows:** {len(rows)}  ")
lines.append(f"**`catalyst_quality` column present:** {'YES' if has_cq else 'NO'}")
lines.append("")

if not has_cq:
    lines.append("## STATUS: COLUMN MISSING")
    lines.append("")
    lines.append(
        "The `catalyst_quality` field was not emitted on this snapshot. "
        "Spec 078 Lane B writes it inside `save_validation_snapshot()` in `run_screen.py` "
        "via `classify_catalyst_quality(...)`. Investigate run_daily / run_screen path before reading anything else."
    )
    open(REPORT, "w").write("\n".join(lines) + "\n")
    print("WROTE", REPORT, "(catalyst_quality column missing)")
    sys.exit(0)

def rank_key(r):
    for f in ("final_rank", "rank", "rank_overall"):
        v = r.get(f)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 9999.0

rows_sorted = sorted(rows, key=rank_key)
dist_all = Counter(r.get("catalyst_quality", "") for r in rows)

lines.append("## Distribution (full universe)")
lines.append("")
lines.append("| bucket | n |")
lines.append("|---|---|")
for k in ("binary_alpha", "registry_only", "corporate_update", "low_confidence", ""):
    label = k if k else "(empty)"
    lines.append(f"| {label} | {dist_all.get(k, 0)} |")
unexpected = {k: v for k, v in dist_all.items() if k not in {"binary_alpha", "registry_only", "corporate_update", "low_confidence", ""}}
if unexpected:
    lines.append("")
    lines.append(f"⚠ Unexpected bucket values: {unexpected}")
lines.append("")

for n in (30, 60):
    top = rows_sorted[:n]
    cnt = Counter(r.get("catalyst_quality", "") for r in top)
    flagged = cnt.get("corporate_update", 0) + cnt.get("low_confidence", 0)
    lines.append(f"## Top-{n}")
    lines.append("")
    lines.append("| bucket | n |")
    lines.append("|---|---|")
    for k in ("binary_alpha", "registry_only", "corporate_update", "low_confidence", ""):
        label = k if k else "(empty)"
        lines.append(f"| {label} | {cnt.get(k, 0)} |")
    lines.append("")
    lines.append(f"**Flagged in top-{n} (corporate_update + low_confidence):** {flagged}")
    lines.append("")

flagged_rows = [
    r for r in rows_sorted
    if r.get("catalyst_quality") in ("corporate_update", "low_confidence")
]

lines.append("## Flagged: corporate_update + low_confidence (full universe)")
lines.append("")
if flagged_rows:
    lines.append("| ticker | quality | rank | catalyst_source | catalyst_event_type | calendar_confidence | next_catalyst_date | catalyst_days |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in flagged_rows:
        lines.append(
            f"| {r.get('ticker','?')} | {r.get('catalyst_quality','')} | "
            f"{r.get('final_rank') or r.get('rank') or '—'} | "
            f"{r.get('catalyst_source','')} | {r.get('catalyst_event_type','')} | "
            f"{r.get('calendar_confidence','')} | {r.get('next_catalyst_date','')} | "
            f"{r.get('catalyst_days','')} |"
        )
else:
    lines.append("_None._ (consistent with hygiene-gate behavior — flag fires only on edge cases.)")
lines.append("")

def parse_iso(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip()[:10])
    except (TypeError, ValueError):
        return None

stale_candidates = []
for r in rows_sorted:
    if r.get("catalyst_quality") != "registry_only":
        continue
    pcd = parse_iso(r.get("next_catalyst_date", ""))
    cd_raw = r.get("catalyst_days", "")
    try:
        cd_int = int(float(cd_raw)) if cd_raw not in (None, "") else None
    except (TypeError, ValueError):
        cd_int = None
    pcd_in_past = pcd is not None and pcd < TODAY
    cd_negative = cd_int is not None and cd_int < 0
    if pcd_in_past or cd_negative:
        stale_candidates.append((r, pcd, cd_int))

lines.append("## Stale-looking registry_only (PCD in past OR catalyst_days < 0)")
lines.append("")
if stale_candidates:
    lines.append("| ticker | rank | next_catalyst_date | catalyst_days | catalyst_source | catalyst_event_type |")
    lines.append("|---|---|---|---|---|---|")
    for r, pcd, cd_int in stale_candidates:
        lines.append(
            f"| {r.get('ticker','?')} | "
            f"{r.get('final_rank') or r.get('rank') or '—'} | "
            f"{r.get('next_catalyst_date','')} | {cd_int if cd_int is not None else '—'} | "
            f"{r.get('catalyst_source','')} | {r.get('catalyst_event_type','')} |"
        )
    lines.append("")
    lines.append(
        f"⚠ {len(stale_candidates)} registry_only row(s) have a past PCD or negative catalyst_days. "
        "These are candidates for false-stale review (Spec 071 Lane 1 should have rejected if the trial moved to a terminal status, but PCDs can drift independently of status). "
        "Do NOT change scoring on this first observation."
    )
else:
    lines.append("_None._")
lines.append("")

lines.append("---")
lines.append("")
lines.append(
    "_Generated by `tools/cron_one_shot_2026_05_07.sh`. Read-only verification — no scoring change. "
    "Per closure note (Spec 071+078, 2026-05-06): wait for post-13F window close (~2026-05-15) and sufficient resolved-event counts before touching Specs 079–082._"
)

open(REPORT, "w").write("\n".join(lines) + "\n")
print("WROTE", REPORT)
PYEOF

echo "${LOG_PREFIX} Report ↓↓↓"
cat "$REPORT"
echo "${LOG_PREFIX} Report ↑↑↑"
echo "${LOG_PREFIX} Full report: $REPORT"

touch "$MARKER"
echo "${LOG_PREFIX} Done. Marker written: $MARKER"
