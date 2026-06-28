#!/usr/bin/env bash
# cron_allocation_lens.sh — Daily biotech allocation lens artifact generator.
#
# Reads existing pipeline outputs (rankings snapshot, ops_digest, catalyst_delta,
# EES scorecard, Scientific Cartography) and writes:
#   artifacts/surveillance/YYYY-MM-DD_allocation_lens.md
#   artifacts/surveillance/YYYY-MM-DD_allocation_lens.json
#
# Classification: ALLOCATION_LENS_STEP_1_ATTENTION_ROUTING_NO_MODEL_CHANGE
# Constraints: NO_RANKER_CHANGE  NO_SELECTOR_CHANGE  NO_FINAL_SCORE_CHANGE
#              WRITE: artifacts/surveillance/ only
#
# Usage:
#   ./tools/cron_allocation_lens.sh              # run for today
#   ./tools/cron_allocation_lens.sh 2026-06-26   # run for specific date
#
# Cron schedule (ET, weekdays only — after daily production run):
#   30 20 * * 1-5

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
LOG_DIR="${REPO_ROOT}/logs"

cd "$REPO_ROOT"
source .env 2>/dev/null || true

TODAY="${1:-$(date +%Y-%m-%d)}"

mkdir -p "$LOG_DIR" "${REPO_ROOT}/artifacts/surveillance"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] allocation_lens: $*"
}

log "Starting for ${TODAY}"

$PYTHON tools/generate_allocation_lens.py --as-of-date "$TODAY" --no-overwrite 2>&1 | while IFS= read -r line; do
    log "$line"
done

EXIT_CODE="${PIPESTATUS[0]}"

if [ "$EXIT_CODE" -eq 0 ]; then
    log "Done — artifacts/surveillance/${TODAY}_allocation_lens.{md,json} (created/overwrote/skipped logged above)"
else
    log "ERROR: generator exited with code $EXIT_CODE"
    exit "$EXIT_CODE"
fi
