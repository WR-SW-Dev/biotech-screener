#!/usr/bin/env bash
# cron_cross_signal_forward_logger.sh — Daily forward bucket logger for the
# DEM × cross-signal study. Runs Mon–Fri at 19:40 ET, ~10 min after the
# inst_delta forward-shadow comparison and ~3h after the production cron.
# Reads today's rankings.csv (no model rerun) and persists bucket memberships
# under artifacts/audit/cross_signal_forward_shadow/.
#
# Crontab:
#   40 19 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_cross_signal_forward_logger.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/cross_signal_forward_shadow.log 2>&1
#
# No auto-disable — this is an open-ended forward log. Remove the crontab
# entry manually when the study concludes.

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
LOG_PREFIX="[$(date -Iseconds)]"

cd "$REPO_ROOT"

TODAY=$(date +%Y-%m-%d)

# Defensive weekend skip (cron 1-5 already handles this)
DOW=$(date +%u)
if [ "$DOW" -gt 5 ]; then
    echo "${LOG_PREFIX} SKIP: today=${TODAY} is weekend (DOW=${DOW})"
    exit 0
fi

# Skip if today's snapshot doesn't exist yet (production cron may have failed
# or be in progress).
if [ ! -f "data/snapshots/${TODAY}/rankings.csv" ]; then
    echo "${LOG_PREFIX} SKIP: data/snapshots/${TODAY}/rankings.csv not present yet"
    exit 0
fi

echo "${LOG_PREFIX} Logging cross-signal buckets for ${TODAY}"
/usr/bin/python3 tools/cross_signal_forward_logger.py
