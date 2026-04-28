#!/usr/bin/env bash
# cron_one_shot_2026_04_29.sh — Verify the first production snapshot under the
# 8-K + 6-K producer (commit a4c15bf0).
#
# Fires once on Wednesday 2026-04-29 ~18:00 ET, after the day's production run
# (16:30) has produced cache/sec/8k_catalysts/8k_catalysts_2026-04-29_*.json.
# Runs four checks and writes artifacts/audit/sec_6k_first_run_2026-04-29.json.
#
# Self-skips on any other date and on re-invocations (marker file).
#
# Cron entry (annual recurrence is fine — the marker file prevents re-runs):
#   0 18 29 4 * /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_one_shot_2026_04_29.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/one_shot.log 2>&1
#
# After it has fired once, you can either leave the entry (it self-skips via
# marker) or remove it from crontab.

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
TARGET_DATE="2026-04-29"
BASELINE_DATE="2026-04-28"
BASELINE_EVENT_COUNT="357"
MARKER="${REPO_ROOT}/logs/.one_shot_${TARGET_DATE}.done"
AUDIT_LOG="${REPO_ROOT}/logs/audit_sec_6k_first_run_${TARGET_DATE}.log"
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

echo "${LOG_PREFIX} Firing SEC 6-K first-run audit for ${TARGET_DATE}"

cd "$REPO_ROOT"
mkdir -p logs

# Audit tool exits 1 on a check failure (still writes artifact); we capture both.
set +e
/usr/bin/python3 tools/audit_sec_6k_first_run.py \
    --target-date "${TARGET_DATE}" \
    --baseline-date "${BASELINE_DATE}" \
    --baseline-event-count "${BASELINE_EVENT_COUNT}" \
    > "${AUDIT_LOG}" 2>&1
RC=$?
set -e

echo "${LOG_PREFIX} Audit report ↓↓↓"
cat "${AUDIT_LOG}"
echo "${LOG_PREFIX} Audit report ↑↑↑"
echo "${LOG_PREFIX} Full log: ${AUDIT_LOG}"
echo "${LOG_PREFIX} Artifact: ${REPO_ROOT}/artifacts/audit/sec_6k_first_run_${TARGET_DATE}.json"
echo "${LOG_PREFIX} Audit exit code: ${RC}"

touch "$MARKER"
echo "${LOG_PREFIX} Done. Marker written: $MARKER"
