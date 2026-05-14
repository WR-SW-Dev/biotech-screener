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
    # If daily_production is currently mid-flight (lock held by an active PID),
    # skip the recovery — it's already running. The wrapper has its own lock,
    # so re-invoking would just emit "SKIP", but we'd waste 1.5 min on
    # data_refresh first. Avoiding that by short-circuiting here.
    DAILY_LOCK="$REPO/logs/.daily_production.lock"
    if [ -f "$DAILY_LOCK" ]; then
        DAILY_PID=$(cat "$DAILY_LOCK" 2>/dev/null || echo "")
        if [ -n "$DAILY_PID" ] && kill -0 "$DAILY_PID" 2>/dev/null; then
            log "Production active (PID $DAILY_PID) — skipping recovery to avoid wasteful data_refresh"
            PROD_RAN=skip
        fi
    fi
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
elif [ "$PROD_RAN" = "skip" ]; then
    : # already logged above
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
#
# Idempotency: artifacts/phase2_recovery_done/$YESTERDAY.complete prevents
# repeated recovery on the same date. Without this marker, each watchdog tick
# sees the same MISSED state and re-fires recovery indefinitely.
YESTERDAY=$(TZ=America/Detroit date -d "yesterday" +%Y-%m-%d)
YESTERDAY_COMPACT=$(echo "$YESTERDAY" | tr -d '-')
AGENTS_LOG="$REPO/logs/agents.log"
AGENTS_DIRECT_DIR="$REPO/logs/agents_direct"
# NOTE: event_analyst removed from PHASE2_AGENTS on 2026-05-06 (P1 #4): cadence
# reduced from daily to weekly Friday. Watchdog must not auto-recover it on
# Mon-Thu, or it would re-fire daily and undo the cadence reduction.
PHASE2_AGENTS="price_action_watch postmortem options_watch review_queue_steward"
PHASE2_MARKER_DIR="$REPO/artifacts/phase2_recovery_done"
PHASE2_MARKER="$PHASE2_MARKER_DIR/$YESTERDAY.complete"

mkdir -p "$PHASE2_MARKER_DIR"

# Skip recovery if already completed for this date
if [ -f "$PHASE2_MARKER" ]; then
    log "Phase-2 recovery already completed for $YESTERDAY — skipping"
else
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

        # Write completion marker to prevent re-firing
        echo "phase2_recovery_complete: $YESTERDAY" > "$PHASE2_MARKER"
        echo "recovered_agents:$missed_agents" >> "$PHASE2_MARKER"
        echo "recovery_timestamp: $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$PHASE2_MARKER"
    else
        log "All phase-2 agents ran on $YESTERDAY — no agent recovery needed"
        # Write marker even when no recovery needed (all agents present)
        echo "phase2_recovery_complete: $YESTERDAY" > "$PHASE2_MARKER"
        echo "recovered_agents: none" >> "$PHASE2_MARKER"
        echo "recovery_timestamp: $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$PHASE2_MARKER"
    fi
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

# Trapops monitor recovery — check artifact, not log mtime.
# The production pipeline writes trapops_daily_summary.json into the promoted
# snapshot dir. If that file is missing, run trapops standalone to generate it.
# Using artifact presence avoids false-negative from log touched by earlier run.
TRAPOPS_LOG="$REPO/logs/trapops_cron.log"
TRAPOPS_ARTIFACT="$REPO/data/snapshots/$TODAY/trapops_daily_summary.json"
if [ ! -f "$TRAPOPS_ARTIFACT" ]; then
    log "MISSED trapops artifact for $TODAY — recovering"
    (cd "$REPO" && $PYTHON "$REPO/tools/trapops_monitor.py" --snapshot-date "$TODAY" >> "$TRAPOPS_LOG" 2>&1) \
        && log "Trapops recovery OK — artifact written" \
        || log "Trapops recovery FAILED (exit $?) — artifact may still be missing"
else
    log "Trapops artifact present for $TODAY — skipping recovery"
fi

# Evening cron recovery — jobs that run 17:45–20:40 ET and stalled 05-09→05-13.
# Check for artifacts; if missing, re-run the scripts.
# These jobs fire every weekday in evening windows and do not self-heal on reboot.
EVENING_JOBS=(
    "inst_delta_forward_shadow:19:30:/mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_inst_delta_forward_compare.sh:logs/inst_delta_forward_shadow.log"
    "cross_signal_forward_shadow:19:40:/mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_cross_signal_forward_logger.sh:logs/cross_signal_forward_shadow.log"
    "blast_radius_daily:19:15:/mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_blast_radius_daily.sh:logs/blast_radius.log"
    "build_event_feedback:17:45:/mnt/c/Projects/biotech_screener/biotech-screener/tools/build_event_feedback.py:logs/event_feedback.log"
    "build_policy_shadow_compare:18:05:/mnt/c/Projects/biotech_screener/biotech-screener/tools/build_policy_shadow_compare.py:logs/agents_direct_cron.log"
)

EVENING_MARKER_DIR="$REPO/artifacts/evening_recovery_done"
EVENING_MARKER="$EVENING_MARKER_DIR/$TODAY.complete"
mkdir -p "$EVENING_MARKER_DIR"

# Only attempt evening recovery if production ran successfully today
# Evening jobs are sentinel jobs — they depend on today's snapshot existing
if [ "$PROD_RAN" = true ] && [ ! -f "$EVENING_MARKER" ]; then
    log "Checking evening cron jobs for $TODAY..."

    for job_spec in "${EVENING_JOBS[@]}"; do
        IFS=':' read -r job_name job_time job_script job_log <<< "$job_spec"
        job_log="$REPO/$job_log"

        # Simple check: if the log file has recent output (today), assume job ran
        # More robust: check for specific artifact files, but evening jobs vary in their outputs
        if [ -f "$job_log" ] && grep -q "$TODAY" "$job_log" 2>/dev/null; then
            log "Evening job $job_name OK (log shows $TODAY)"
        else
            log "MISSED evening job $job_name for $TODAY — recovering"
            if [ "$job_script" = *.sh ]; then
                bash "$job_script" >> "$job_log" 2>&1 || log "Evening job $job_name recovery failed (exit $?)"
            else
                # Python script
                (cd "$REPO" && source .env 2>/dev/null && $PYTHON "$job_script" --as-of-date "$TODAY" >> "$job_log" 2>&1) \
                    || log "Evening job $job_name recovery failed (exit $?)"
            fi
        fi
    done

    # Write marker to prevent repeated recovery on same date
    echo "evening_recovery_complete: $TODAY" > "$EVENING_MARKER"
    echo "recovery_timestamp: $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$EVENING_MARKER"
    log "Evening cron recovery complete for $TODAY"
fi

log "Recovery complete for $TODAY"
