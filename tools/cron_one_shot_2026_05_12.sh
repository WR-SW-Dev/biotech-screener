#!/usr/bin/env bash
# cron_one_shot_2026_05_12.sh — Verify the build_event_analyst.py cron entry
# (added 2026-05-01: `10 19 * * 1-5`) has been firing daily and writing
# artifacts/event_analyst/{date}_summary.json.
#
# Fires once on 2026-05-12 09:00 ET, after one full week of natural fires.
# Self-skips on any other date and on re-invocations (marker file).
#
# Cron entry:
#   0 9 12 5 * /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_one_shot_2026_05_12.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/one_shot.log 2>&1

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
TARGET_DATE="2026-05-12"
MARKER="${REPO_ROOT}/logs/.one_shot_${TARGET_DATE}.done"
ARTIFACT_DIR="${REPO_ROOT}/artifacts/audit"
ARTIFACT="${ARTIFACT_DIR}/event_analyst_builder_verify_${TARGET_DATE}.md"
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

echo "${LOG_PREFIX} Firing event_analyst builder verification for ${TARGET_DATE}"

cd "$REPO_ROOT"
mkdir -p "$ARTIFACT_DIR" logs

# Cadence note: event_analyst was reduced to weekly Friday on 2026-05-06
# (P1 #4). The original daily-cadence verification window 2026-05-04 →
# 2026-05-11 now expects only Friday 2026-05-08 to have a fresh post-cadence-
# change artifact. Pre-change daily artifacts (2026-05-04, 2026-05-05) may
# still exist on disk from the prior daily cron — they are noted but not
# required for PASS.
EXPECTED_DATES=(2026-05-08)
HISTORICAL_DATES=(2026-05-04 2026-05-05)
PRESENT=()
MISSING=()
SIZE_FLAGS=()

for d in "${EXPECTED_DATES[@]}"; do
    f="artifacts/event_analyst/${d}_summary.json"
    if [ -f "$f" ]; then
        PRESENT+=("$d")
        # Flag if file is suspiciously small (< 500 bytes suggests empty/error)
        sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
        if [ "$sz" -lt 500 ]; then
            SIZE_FLAGS+=("${d} (${sz} bytes)")
        fi
    else
        MISSING+=("$d")
    fi
done

PRESENT_STR="${PRESENT[*]:-(none)}"
MISSING_STR="${MISSING[*]:-(none)}"
SIZE_FLAGS_STR="${SIZE_FLAGS[*]:-(none)}"

if [ ${#MISSING[@]} -eq 0 ] && [ ${#SIZE_FLAGS[@]} -eq 0 ]; then
    VERDICT="PASS — Friday 2026-05-08 weekly-cadence artifact present and non-trivially sized (P1 #4 reduced to weekly 2026-05-06)"
elif [ ${#MISSING[@]} -eq 0 ]; then
    VERDICT="WARN — Friday artifact present but suspiciously small (${#SIZE_FLAGS[@]} flagged)"
else
    VERDICT="FAIL — ${#MISSING[@]}/${#EXPECTED_DATES[@]} Friday artifact(s) missing (post-2026-05-06 weekly cadence)"
fi

# Informational: list any historical (pre-cadence-change) artifacts still on disk.
HIST_PRESENT=()
for d in "${HISTORICAL_DATES[@]}"; do
    f="artifacts/event_analyst/${d}_summary.json"
    if [ -f "$f" ]; then HIST_PRESENT+=("$d"); fi
done
HIST_PRESENT_STR="${HIST_PRESENT[*]:-(none)}"

LOG_FILE="logs/event_analyst_builder.log"
if [ -f "$LOG_FILE" ]; then
    LOG_TAIL=$(tail -50 "$LOG_FILE")
    LOG_BYTES=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
else
    LOG_TAIL="(log file does not exist — cron entry may not have fired at all)"
    LOG_BYTES=0
fi

ERROR_HITS=$(grep -ciE "error|exception|traceback|failed" "$LOG_FILE" 2>/dev/null || echo 0)

{
    echo "# Event Analyst Builder Verification — ${TARGET_DATE}"
    echo
    echo "Cron entry under verification: \`10 19 * * 5\` (added 2026-05-01 as weekday daily; reduced to Friday-only on 2026-05-06 per P1 #4)."
    echo "Reason: build_event_analyst.py was unscheduled in early April — only LLM HEARTBEAT was wired, so artifacts/event_analyst/ was frozen at 2026-04-03. Daily cron added 2026-05-01 to backfill; cadence then reduced to weekly Friday on 2026-05-06 (P1 #4 cadence reduction)."
    echo
    echo "## Verdict: ${VERDICT}"
    echo
    echo "## Expected post-cadence-change artifact (Friday 2026-05-08)"
    echo
    echo "- Present (${#PRESENT[@]}): ${PRESENT_STR}"
    echo "- Missing (${#MISSING[@]}): ${MISSING_STR}"
    echo "- Size-flagged (<500 bytes): ${SIZE_FLAGS_STR}"
    echo
    echo "## Historical (pre-cadence-change) artifacts still on disk"
    echo
    echo "- Present (${#HIST_PRESENT[@]} of ${#HISTORICAL_DATES[@]}): ${HIST_PRESENT_STR}"
    echo "- (Informational only — these are not required for PASS post-2026-05-06.)"
    echo
    echo "## Builder log"
    echo
    echo "- Path: ${LOG_FILE}"
    echo "- Size: ${LOG_BYTES} bytes"
    echo "- Error/exception/traceback line count: ${ERROR_HITS}"
    echo
    echo "### Last 50 lines"
    echo
    echo '```'
    echo "${LOG_TAIL}"
    echo '```'
    echo
    echo "## Failure-mode hint"
    echo
    if [ ${#MISSING[@]} -eq ${#EXPECTED_DATES[@]} ]; then
        echo "Friday 2026-05-08 artifact missing → weekly cron likely not firing. Check \`crontab -l | grep build_event_analyst\` (expect \`10 19 * * 5\`) and WSL uptime during 19:10 ET on 2026-05-08."
    elif [ ${#MISSING[@]} -gt 0 ]; then
        echo "Partial coverage — Friday artifact missing but historical present. WSL likely down on 2026-05-08 19:10 ET."
    elif [ ${#SIZE_FLAGS[@]} -gt 0 ]; then
        echo "Friday artifact exists but small — script ran but produced near-empty output. Check log for postmortem source data issues."
    elif [ "$ERROR_HITS" -gt 0 ]; then
        echo "Friday artifact present but log contains error tokens — review log tail for context."
    else
        echo "Clean — weekly cadence working. Mark P1 #4 verification closed in MEMORY.md."
    fi
} > "$ARTIFACT"

echo "${LOG_PREFIX} Wrote ${ARTIFACT}"
echo "${LOG_PREFIX} Verdict report ↓↓↓"
cat "$ARTIFACT"
echo "${LOG_PREFIX} Verdict report ↑↑↑"

touch "$MARKER"
echo "${LOG_PREFIX} Done. Marker: $MARKER"
