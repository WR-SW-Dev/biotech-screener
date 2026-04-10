#!/usr/bin/env bash
# cron_watchdog.sh — detect and recover missed cron jobs on WSL2
#
# WSL2 sleep/wake corrupts cron's internal timer. This watchdog:
#   1. Checks if today's production ran (by looking for cron.log entry)
#   2. If not, runs data_refresh + daily_production manually
#   3. Logs to logs/watchdog.log
#
# Run this from Windows Task Scheduler or a @reboot cron entry.
# Usage: bash tools/cron_watchdog.sh

set -uo pipefail

REPO="/mnt/c/Projects/biotech_screener/biotech-screener"
LOG="$REPO/logs/watchdog.log"
CRON_LOG="$REPO/logs/cron.log"

cd "$REPO" || exit 1

TODAY=$(TZ=America/Detroit date +%Y-%m-%d)
DOW=$(TZ=America/Detroit date +%u)  # 1=Mon, 7=Sun

log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] watchdog: $*" >> "$LOG"; }

# Skip weekends
if [ "$DOW" -ge 6 ]; then
    log "Weekend ($DOW) — skipping"
    exit 0
fi

# Check if cron fired today's production run
if grep -q "Starting daily production for $TODAY" "$CRON_LOG" 2>/dev/null; then
    log "Production already ran for $TODAY — no action"
    exit 0
fi

log "MISSED: No production run for $TODAY — triggering manual recovery"

# Try to restart cron (may fail without sudo)
service cron restart >> "$LOG" 2>&1 || log "cron restart failed (no sudo) — running jobs directly"

# Run data refresh first
log "Running data_refresh..."
bash "$REPO/tools/cron_data_refresh.sh" all >> "$REPO/logs/data_refresh.log" 2>&1
log "data_refresh done (exit $?)"

# Run daily production
log "Running daily_production..."
bash "$REPO/tools/cron_daily_production.sh" >> "$CRON_LOG" 2>&1
log "daily_production done (exit $?)"

log "Recovery complete for $TODAY"
