#!/usr/bin/env bash
# cron_one_shot_2026_05_04.sh — First-week audit of the hardening diagnostics.
#
# Fires once on Monday 2026-05-04 ~17:00 ET, after the day's production run
# has completed and emitted today's diagnostic artifacts. Reads the four
# diagnostic artifacts (integrity, feature coverage, drift, sentinel) for
# every weekday from 2026-04-28 → 2026-05-04 and prints a calibration
# report to logs/audit_hardening_diagnostics.log.
#
# Self-skips on any other date and on re-invocations (marker file).
#
# Cron entry (annual recurrence is fine — the marker prevents re-runs):
#   0 17 4 5 * /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_one_shot_2026_05_04.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/one_shot.log 2>&1

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
TARGET_DATE="2026-05-04"
WINDOW_START="2026-04-28"
WINDOW_END="${TARGET_DATE}"
MARKER="${REPO_ROOT}/logs/.one_shot_${TARGET_DATE}.done"
AUDIT_LOG="${REPO_ROOT}/logs/audit_hardening_diagnostics_${TARGET_DATE}.log"
JSON_OUT="${REPO_ROOT}/artifacts/audit/hardening_diagnostics_${TARGET_DATE}.json"
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

echo "${LOG_PREFIX} Firing hardening diagnostics audit for window ${WINDOW_START} → ${WINDOW_END}"

cd "$REPO_ROOT"
mkdir -p "$(dirname "$JSON_OUT")"

/usr/bin/python3 tools/audit_hardening_diagnostics.py \
    --start-date "${WINDOW_START}" \
    --end-date "${WINDOW_END}" \
    --json-out "${JSON_OUT}" \
    > "${AUDIT_LOG}" 2>&1

echo "${LOG_PREFIX} Audit report ↓↓↓"
cat "${AUDIT_LOG}"
echo "${LOG_PREFIX} Audit report ↑↑↑"
echo "${LOG_PREFIX} Full report: ${AUDIT_LOG}"
echo "${LOG_PREFIX} Aggregated JSON: ${JSON_OUT}"

touch "$MARKER"
echo "${LOG_PREFIX} Done. Marker written: $MARKER"
