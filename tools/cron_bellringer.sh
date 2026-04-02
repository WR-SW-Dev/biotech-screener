#!/usr/bin/env bash
# cron_bellringer.sh — Bellringer earnings calendar sync + email alerts.
#
# Stages:
#   fetch     Fetch earnings from yfinance (60-day lookahead)
#   ics       Generate ICS calendar file from latest raw fetch
#   reminder  Send pre-earnings email digest (today + tomorrow)
#   results   Send post-earnings results email (today's reporters)
#   all       Run fetch + ics + reminder (default)
#
# Usage:
#   ./tools/cron_bellringer.sh                  # fetch + ics + reminder
#   ./tools/cron_bellringer.sh fetch            # just fetch
#   ./tools/cron_bellringer.sh results          # just results email
#   ./tools/cron_bellringer.sh all              # fetch + ics + reminder
#
# Cron schedule (all times ET, weekdays only):
#   06:30  fetch + ics + reminder
#   18:30  results

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
LOG_DIR="${REPO_ROOT}/logs"
ARTIFACTS="${REPO_ROOT}/artifacts/earnings_sync"

cd "$REPO_ROOT"
source .env 2>/dev/null || true

TODAY=$(date +%Y-%m-%d)
END=$(date -d "+60 days" +%Y-%m-%d 2>/dev/null || date -v+60d +%Y-%m-%d)
RAW_FILE="${ARTIFACTS}/earnings_raw_${TODAY}.json"
ICS_FILE="${ARTIFACTS}/biotech_earnings.ics"

mkdir -p "$LOG_DIR" "$ARTIFACTS"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] bellringer: $*"
}

stage_fetch() {
    log "Stage 1: fetching earnings ${TODAY} → ${END}"
    $PYTHON scripts/fetch_earnings_calendar.py \
        --symbols-file production_data/universe.json \
        --start "$TODAY" \
        --end "$END" \
        --output "$RAW_FILE"
    log "fetch done: $(python3 -c "import json; print(len(json.load(open('${RAW_FILE}')).get('rows',[])))") events"
}

stage_ics() {
    # Use today's raw file, or fall back to most recent
    local rf="$RAW_FILE"
    if [ ! -f "$rf" ]; then
        rf=$(ls -t "${ARTIFACTS}"/earnings_raw_*.json 2>/dev/null | head -1)
    fi
    if [ -z "$rf" ] || [ ! -f "$rf" ]; then
        log "ERROR: no raw file found, skipping ICS"
        return 1
    fi
    log "Stage 2: generating ICS from $rf"
    $PYTHON scripts/sync_earnings_to_outlook.py \
        --raw-file "$rf" \
        --ics-out "$ICS_FILE" \
        --timezone US/Eastern
    log "ics done: $ICS_FILE"
}

stage_reminder() {
    local rf="$RAW_FILE"
    if [ ! -f "$rf" ]; then
        rf=$(ls -t "${ARTIFACTS}"/earnings_raw_*.json 2>/dev/null | head -1)
    fi
    if [ -z "$rf" ] || [ ! -f "$rf" ]; then
        log "ERROR: no raw file for reminder"
        return 1
    fi
    log "Sending reminder email"
    $PYTHON scripts/earnings_email_alerts.py --mode reminder --raw-file "$rf"
}

stage_results() {
    local rf="$RAW_FILE"
    if [ ! -f "$rf" ]; then
        rf=$(ls -t "${ARTIFACTS}"/earnings_raw_*.json 2>/dev/null | head -1)
    fi
    if [ -z "$rf" ] || [ ! -f "$rf" ]; then
        log "ERROR: no raw file for results"
        return 1
    fi
    log "Checking earnings results"
    $PYTHON scripts/earnings_email_alerts.py --mode results --raw-file "$rf"
}

MODE="${1:-all}"

case "$MODE" in
    fetch)
        stage_fetch
        ;;
    ics)
        stage_ics
        ;;
    reminder)
        stage_reminder
        ;;
    results)
        stage_results
        ;;
    all)
        stage_fetch
        stage_ics
        stage_reminder
        ;;
    *)
        echo "Usage: $0 {fetch|ics|reminder|results|all}"
        exit 1
        ;;
esac

log "done ($MODE)"
