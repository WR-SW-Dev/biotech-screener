#!/usr/bin/env bash
# cron_inst_delta_forward_compare.sh — Daily forward-shadow comparison for the
# inst_delta cohort-rebuild study. Runs Mon–Fri at 19:30 ET, after production
# cron (16:30) has refreshed production_data/price_history.csv with today's
# closes. Self-skips on weekends and pre-T0 dates.
#
# T0 = 2026-04-28. Horizons: 1d, 5d, 10d, 20d, 60d (last ~2026-07-21).
# After 60d horizon clears, this entry can be removed from crontab.
#
# Crontab:
#   30 19 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_inst_delta_forward_compare.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/inst_delta_forward_shadow.log 2>&1

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
T0="2026-04-28"
LAST_HORIZON_DATE="2026-07-21"  # ~60 trading days after T0
LOG_PREFIX="[$(date -Iseconds)]"

cd "$REPO_ROOT"

TODAY=$(date +%Y-%m-%d)

# Skip pre-T0
if [ "$TODAY" \< "$T0" ] || [ "$TODAY" = "$T0" ]; then
    echo "${LOG_PREFIX} SKIP: today=${TODAY} <= T0=${T0}; no comparison yet"
    exit 0
fi

# Skip after horizon-60 window (entry can be removed at that point)
if [ "$TODAY" \> "$LAST_HORIZON_DATE" ]; then
    echo "${LOG_PREFIX} SKIP: today=${TODAY} > LAST_HORIZON_DATE=${LAST_HORIZON_DATE}; shadow window closed"
    exit 0
fi

# Skip weekends (cron 1-5 already does this; defensive)
DOW=$(date +%u)
if [ "$DOW" -gt 5 ]; then
    echo "${LOG_PREFIX} SKIP: today=${TODAY} is weekend (DOW=${DOW})"
    exit 0
fi

echo "${LOG_PREFIX} Running inst_delta forward-shadow comparison for ${TODAY}"
/usr/bin/python3 tools/inst_delta_forward_compare.py
