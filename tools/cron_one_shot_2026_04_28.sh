#!/usr/bin/env bash
# cron_one_shot_2026_04_28.sh — One-shot wrapper that runs the cohort-expansion diff
# on Tuesday 2026-04-28 ~09:00 ET, then self-skips on every subsequent invocation.
#
# Cron entry (annual recurrence is fine — the marker file prevents re-runs):
#   0 9 28 4 * /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_one_shot_2026_04_28.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/one_shot.log 2>&1
#
# After it has fired once, you can either leave the entry (it self-skips via marker)
# or remove it from crontab.

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
TARGET_DATE="2026-04-28"
MARKER="${REPO_ROOT}/logs/.one_shot_${TARGET_DATE}.done"
LOG_PREFIX="[$(date -Iseconds)]"

# Self-skip if already fired
if [ -f "$MARKER" ]; then
    echo "${LOG_PREFIX} SKIP: already fired (marker $MARKER exists)"
    exit 0
fi

# Self-skip if today is not the target date (cron's "28 4" matches every Apr 28 forever)
TODAY=$(date +%Y-%m-%d)
if [ "$TODAY" != "$TARGET_DATE" ]; then
    echo "${LOG_PREFIX} SKIP: today=${TODAY} != target=${TARGET_DATE}"
    exit 0
fi

echo "${LOG_PREFIX} Firing cohort-expansion diff for ${TARGET_DATE}"

cd "$REPO_ROOT"
/usr/bin/python3 tools/diff_cohort_expansion_artifact.py \
    --saturday 2026-04-25 \
    --monday   2026-04-27

# Mark done so re-runs (e.g. via watchdog) skip
touch "$MARKER"
echo "${LOG_PREFIX} Done. Marker written: $MARKER"
