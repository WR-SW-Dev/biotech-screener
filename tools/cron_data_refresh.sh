#!/usr/bin/env bash
# cron_data_refresh.sh — Daily data pipeline refresh.
#
# Runs data collection/refresh jobs that feed the production pipeline.
# Designed to run BEFORE the main production screen (16:30 ET).
#
# Stages:
#   ctgov     Warm CTgov trial cache (trial_records.json)
#   herald    Fetch + classify company press releases
#   iv        Rebuild historical IV features from surface data
#   universe  Run universe maintenance health check
#   all       Run all stages (default)
#
# Cron schedule:
#   0 14 * * 1-5  (2:00 PM ET weekdays — 2.5 hours before production)

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
LOG_DIR="${REPO_ROOT}/logs"

cd "$REPO_ROOT"
source .env 2>/dev/null || true

TODAY=$(date +%Y-%m-%d)

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] data-refresh: $*"
}

stage_ctgov() {
    log "CTgov warm cache..."
    $PYTHON warm_caches.py --sources ctgov --as-of-date "$TODAY" 2>&1 | tail -5
    log "CTgov done"
}

stage_herald() {
    log "Herald press release fetch (timeout 600s)..."
    local rc=0
    timeout 600 $PYTHON tools/fetch_company_press_releases.py --as-of-date "$TODAY" 2>&1 | tail -5 || rc=$?
    if [ $rc -eq 124 ]; then
        log "Herald fetch TIMED OUT after 600s — continuing with partial data"
    elif [ $rc -ne 0 ]; then
        log "Herald fetch failed (exit $rc) — continuing"
    else
        log "Herald fetch done"
    fi

    # Classify new releases (timeout 300s)
    RELEASES_FILE="data/press_releases/releases_${TODAY}.jsonl"
    if [ -f "$RELEASES_FILE" ]; then
        log "Herald classify (timeout 300s)..."
        local rc2=0
        timeout 300 $PYTHON tools/classify_press_releases.py --input "$RELEASES_FILE" 2>&1 | tail -5 || rc2=$?
        if [ $rc2 -eq 124 ]; then
            log "Herald classify TIMED OUT after 300s"
        else
            log "Herald classify done"
        fi
    else
        log "No new releases file for $TODAY"
    fi
}

stage_iv() {
    log "IV features rebuild..."
    $PYTHON scripts/research/build_historical_iv_features.py 2>&1 | tail -5
    log "IV features done"
}

stage_universe() {
    log "Universe maintenance..."
    $PYTHON tools/build_universe_maintenance.py --as-of-date "$TODAY" 2>&1 | tail -5
    log "Universe done"
}

MODE="${1:-all}"

case "$MODE" in
    ctgov)
        stage_ctgov
        ;;
    herald)
        stage_herald
        ;;
    iv)
        stage_iv
        ;;
    universe)
        stage_universe
        ;;
    all)
        stage_ctgov
        stage_herald
        stage_iv
        stage_universe
        ;;
    *)
        echo "Usage: $0 {ctgov|herald|iv|universe|all}"
        exit 1
        ;;
esac

log "done ($MODE)"
