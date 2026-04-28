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
PYTHON="/usr/bin/python3"
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

# Check if today's production produced its snapshot. The "Starting" line in
# cron.log is written by the wrapper before any work happens, so it can't
# distinguish a successful run from one killed mid-pipeline (e.g. WSL2
# reaping the parent during a subprocess call — observed 2026-04-27 and
# 2026-04-28). data/snapshots/$TODAY/rankings.csv exists once the pipeline
# reaches promotion; this is the same gate the wrapper uses for its own
# rank-change monitor (see cron_daily_production.sh).
if [ -f "$REPO/data/snapshots/$TODAY/rankings.csv" ]; then
    PROD_RAN=true
else
    PROD_RAN=false
fi

if [ "$PROD_RAN" = false ]; then
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
else
    log "Production already ran for $TODAY — skipping production recovery"
fi

# Post-snapshot task supervisor (Spec 069 phase 1).
# When the snapshot promoted but daily_production was reaped before reaching
# Step 5n (AACT) / 5l.5 (Herald), those tasks never produced their artifacts.
# Supervisor re-runs them idempotently. Gate fires when:
#   - snapshot's rankings.csv exists (PROD_RAN=true OR we just re-ran above)
#   - complete marker missing for $TODAY
# Each task has its own done predicate, so a no-op pass is cheap.
SUPERVISOR_MARKER="$REPO/artifacts/post_snapshot_done/$TODAY.complete"
if [ -f "$REPO/data/snapshots/$TODAY/rankings.csv" ] && [ ! -f "$SUPERVISOR_MARKER" ]; then
    log "Snapshot present, post-snapshot tasks incomplete — running supervisor"
    bash "$REPO/tools/run_post_snapshot_supervisor.sh" "$TODAY" >> "$LOG" 2>&1
    log "post_snapshot_supervisor done (exit $?)"
fi

# Phase-2 agent recovery runs UNCONDITIONALLY.
# WSL sleep between 17:30 and 19:00 ET can miss the 18:00–18:55 slots even
# when morning production succeeded; 2026-04-23 lost 7 evening agents while
# ops+sentinel ran on time. Previously this block was gated behind
# PROD_RAN=false and never fired in that scenario.
#
# Detection uses logs/agents_direct/{agent}_YYYYMMDD_*.json. The prior grep
# on agents.log checked YYYY-MM-DD against the compact YYYYMMDD filename and
# silently never matched — detection was broken even before the gate issue.
YESTERDAY=$(TZ=America/Detroit date -d "yesterday" +%Y-%m-%d)
YESTERDAY_COMPACT=$(echo "$YESTERDAY" | tr -d '-')
AGENTS_LOG="$REPO/logs/agents.log"
AGENTS_DIRECT_DIR="$REPO/logs/agents_direct"
PHASE2_AGENTS="price_action_watch postmortem options_watch review_queue_steward event_analyst"

missed_agents=""
for agent in $PHASE2_AGENTS; do
    if ! ls "$AGENTS_DIRECT_DIR/${agent}_${YESTERDAY_COMPACT}_"*.json 1>/dev/null 2>&1; then
        missed_agents="$missed_agents $agent"
    fi
done

if [ -n "$missed_agents" ]; then
    log "MISSED phase-2 agents from $YESTERDAY:$missed_agents — triggering recovery"
    for agent in $missed_agents; do
        log "Recovering agent: $agent"
        $PYTHON "$REPO/tools/run_agent_direct.py" --agent "$agent" >> "$AGENTS_LOG" 2>&1 || log "Agent $agent recovery failed (exit $?)"
    done
    log "Phase-2 agent recovery complete"
else
    log "All phase-2 agents ran on $YESTERDAY — no agent recovery needed"
fi

# Pre-market feed checks run on every invocation, regardless of production state.
# Each check has its own per-run marker so a missed morning slot can recover later in the day.

# Bellringer morning reminder (06:30 ET slot)
BELLRINGER_LOG="$REPO/logs/bellringer.log"
if ! grep -qE "^\[$TODAY " "$BELLRINGER_LOG" 2>/dev/null; then
    log "MISSED bellringer for $TODAY — recovering"
    bash "$REPO/tools/cron_bellringer.sh" all >> "$BELLRINGER_LOG" 2>&1 || log "Bellringer recovery failed (exit $?)"
fi

# Conference abstracts refresh (06:00 ET slot). Grep anchored to today's cache-file
# line so it doesn't false-match older dates mentioned in summary tables.
CONF_LOG="$REPO/logs/conference_refresh.log"
if ! grep -q "abstracts_$TODAY\.json" "$CONF_LOG" 2>/dev/null; then
    log "MISSED conference abstracts for $TODAY — recovering"
    source "$REPO/.env" 2>/dev/null || true
    $PYTHON "$REPO/tools/fetch_conference_abstracts_grok.py" --all >> "$CONF_LOG" 2>&1 || log "Conference refresh failed (exit $?)"
fi

# Trapops monitor (06:17 ET slot). No pre-existing marker, so use log-file mtime.
# Missing file or log not touched today => recovery.
TRAPOPS_LOG="$REPO/logs/trapops_cron.log"
TRAPOPS_MTIME=$(date -r "$TRAPOPS_LOG" +%Y-%m-%d 2>/dev/null || echo "")
if [ "$TRAPOPS_MTIME" != "$TODAY" ]; then
    log "MISSED trapops for $TODAY — recovering"
    (cd "$REPO" && $PYTHON "$REPO/tools/trapops_monitor.py" >> "$TRAPOPS_LOG" 2>&1) || log "Trapops recovery failed (exit $?)"
fi

log "Recovery complete for $TODAY"
