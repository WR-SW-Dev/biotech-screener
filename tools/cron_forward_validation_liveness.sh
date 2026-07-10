#!/usr/bin/env bash
# Liveness monitor for forward-shadow mandate SM-20260629-001.
#
# Read-only. Intended to run after the daily production window (and the forward-
# validation capture tail). Surfaces the ways the forward feed can silently stop
# producing genuine live evidence — stale/absent live captures, candidate hash
# drift, XBI staleness, rankings mismatch, duplicate or hard-fail-skipped
# captures — so a broken evaluator is never read as weak investment evidence.
#
# Does NOT gate or mutate anything. Writes artifacts/forward_validation/
# LIVENESS_STATUS.json and logs a prominent line when alerts are present.
#
# Suggested crontab (weekdays ~19:00 ET, after production + capture + QA):
#   0 19 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_forward_validation_liveness.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/forward_validation_liveness.log 2>&1
set -uo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="${PYTHON:-/usr/bin/python3}"
cd "${REPO_ROOT}" || exit 1

"${PYTHON}" tools/forward_validation_liveness_monitor.py
rc=$?
if [ "${rc}" -ne 0 ]; then
    echo "[$(date -Iseconds)] LIVENESS ALERTS present (rc=${rc}) — see artifacts/forward_validation/LIVENESS_STATUS.json"
fi
# Never fail the cron slot; the alert signal is the log line + status JSON.
exit 0
