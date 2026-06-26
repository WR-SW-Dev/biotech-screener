#!/bin/bash
# Hermes Skill Sync Guard — repo-side wrapper
#
# Called by ~/.hermes/scripts/hermes_skill_sync_agent.sh (the Hermes cron entry point).
# Do not invoke directly from Linux crontab. Register via:
#
#   hermes cron add \
#     --name "hermes-skill-sync-guard" \
#     --schedule "0 8 * * 0" \
#     --no-agent \
#     --script hermes_skill_sync_agent.sh \
#     --workdir /mnt/c/Projects/biotech_screener/biotech-screener
#
# Mode defaults to "audit" (report only; exit 1 on DRIFT_CRITICAL).
# Pass MODE=sync to also regenerate out-of-date mirrors (capped at 3 files).

set -euo pipefail

REPO=/mnt/c/Projects/biotech_screener/biotech-screener
LOG_DIR=$REPO/logs
LOG=$LOG_DIR/hermes_skill_sync_agent.log
LOCK=/tmp/hermes_skill_sync_agent.lock
DATE=$(date +%Y-%m-%d)
MODE=${MODE:-audit}

mkdir -p "$LOG_DIR"

# Prevent concurrent runs (weekly job should never overlap, but be safe)
exec 200>"$LOCK"
if ! flock -n 200; then
    echo "[$(date -Iseconds)] SKIP: lock held by another instance" >> "$LOG"
    exit 0
fi

echo "[$(date -Iseconds)] START hermes-skill-sync-guard mode=$MODE date=$DATE" | tee -a "$LOG"

cd "$REPO"

/usr/bin/python3 tools/hermes_skill_sync_audit.py \
    --mode "$MODE" \
    --as-of-date "$DATE" \
    2>&1 | tee -a "$LOG"
EXIT_CODE=${PIPESTATUS[0]}

echo "[$(date -Iseconds)] END exit=$EXIT_CODE" | tee -a "$LOG"
exit "$EXIT_CODE"
