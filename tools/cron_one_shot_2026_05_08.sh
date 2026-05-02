#!/usr/bin/env bash
# cron_one_shot_2026_05_08.sh — Verify calibration_evidence ran with data after
# the 2026-05-02 postmortem detection fix.
#
# Fires once on Friday 2026-05-08 at 19:30 ET, 30 minutes after the weekly
# calibration_evidence cron (0 19 * * 5). Confirms (a) the cron fired, (b) it
# did NOT exit NO_DATA, (c) the postmortem corpus consumed is meaningfully
# larger than the pre-fix count of 19.
#
# Self-skips on any other date and on re-invocations (marker file).
#
# Cron entry:
#   30 19 8 5 * /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_one_shot_2026_05_08.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/one_shot.log 2>&1
#
# Background: memory/postmortem_detection_fix_2026_05_02.md

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
TARGET_DATE="2026-05-08"
PRE_FIX_COUNT=19
MARKER="${REPO_ROOT}/logs/.one_shot_${TARGET_DATE}.done"
AUDIT_LOG="${REPO_ROOT}/logs/audit_postmortem_pipeline_${TARGET_DATE}.log"
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

echo "${LOG_PREFIX} Verifying calibration_evidence pipeline for ${TARGET_DATE}"

cd "$REPO_ROOT"

CAL_LOG="logs/calibration_evidence.log"
EVIDENCE_JSON="artifacts/calibration_evidence/${TARGET_DATE}_evidence.json"

{
    echo "=== Postmortem pipeline verification — ${TARGET_DATE} ==="
    echo

    # (a) Did the Friday 19:00 cron fire?
    if [ ! -s "$CAL_LOG" ]; then
        echo "STATUS: NOT_FIRED — ${CAL_LOG} missing or empty"
        exit_status="NOT_FIRED"
    elif ! grep -q "${TARGET_DATE}" "$CAL_LOG"; then
        echo "STATUS: NOT_FIRED — no ${TARGET_DATE} entries in ${CAL_LOG}"
        echo "Last 10 log lines:"
        tail -10 "$CAL_LOG"
        exit_status="NOT_FIRED"
    elif [ ! -f "$EVIDENCE_JSON" ]; then
        echo "STATUS: STILL_NO_DATA — cron fired but produced no ${EVIDENCE_JSON}"
        echo "Recent log lines:"
        grep -A2 -B2 "${TARGET_DATE}" "$CAL_LOG" | tail -30
        exit_status="STILL_NO_DATA"
    else
        # (b)+(c) Read postmortem count from the evidence JSON
        PM_COUNT=$(/usr/bin/python3 -c "
import json
d = json.load(open('${EVIDENCE_JSON}'))
# Try common keys
for k in ('n_postmortems', 'postmortem_count', 'num_postmortems'):
    if k in d:
        print(d[k]); break
else:
    # Fallback — count any list-of-postmortems field
    for k, v in d.items():
        if isinstance(v, list) and v and isinstance(v[0], dict) and 'ticker' in v[0]:
            print(len(v)); break
    else:
        print('UNKNOWN')
" 2>/dev/null || echo "PARSE_ERROR")

        echo "Evidence file: ${EVIDENCE_JSON}"
        echo "Postmortems consumed: ${PM_COUNT} (pre-fix baseline: ${PRE_FIX_COUNT})"
        echo
        echo "Recent log lines:"
        grep -B1 -A2 "${TARGET_DATE}" "$CAL_LOG" | tail -20
        echo

        if [ "$PM_COUNT" = "UNKNOWN" ] || [ "$PM_COUNT" = "PARSE_ERROR" ]; then
            echo "STATUS: PARTIAL — file exists but could not parse postmortem count"
            exit_status="PARTIAL"
        elif [ "$PM_COUNT" -le "$PRE_FIX_COUNT" ]; then
            echo "STATUS: STILL_NO_DATA — postmortem count ${PM_COUNT} not above pre-fix ${PRE_FIX_COUNT}"
            echo "  → Bug is in calibration_evidence's own filter, not detection"
            exit_status="STILL_NO_DATA"
        else
            echo "STATUS: OK — calibration_evidence consumed ${PM_COUNT} postmortems (${PRE_FIX_COUNT} pre-fix)"
            exit_status="OK"
        fi
    fi

    echo
    echo "exit_status=${exit_status}"
    echo "=== End verification ==="
} > "$AUDIT_LOG" 2>&1

# Surface into one_shot.log
echo "${LOG_PREFIX} Verification report ↓↓↓"
cat "$AUDIT_LOG"
echo "${LOG_PREFIX} Verification report ↑↑↑"
echo "${LOG_PREFIX} Full report: ${AUDIT_LOG}"

touch "$MARKER"
echo "${LOG_PREFIX} Done. Marker written: $MARKER"
