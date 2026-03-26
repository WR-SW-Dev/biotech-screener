#!/usr/bin/env bash
# cron_daily_production.sh — Automated daily production screen runner.
#
# Designed for cron on WSL2. Runs the full daily production pipeline
# for today's date, logging output to a dated log file.
#
# Usage:
#   ./tools/cron_daily_production.sh              # run for today
#   ./tools/cron_daily_production.sh 2026-03-20   # run for specific date
#   ./tools/cron_daily_production.sh --catch-up   # backfill missed weekdays
#
# Cron example (weekdays at 4:30 PM ET, after market close):
#   30 16 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_daily_production.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/cron.log 2>&1
# On WSL2 reboot, catch up any missed days:
#   @reboot sleep 60 && /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_daily_production.sh --catch-up >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/cron.log 2>&1

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
LOG_DIR="${REPO_ROOT}/logs"
LOCK_FILE="${REPO_ROOT}/logs/.daily_production.lock"
SNAPSHOT_DIR="${REPO_ROOT}/data/snapshots"
MAX_CATCHUP_DAYS=5

# --- Catch-up mode: find and run missed weekdays ---
if [ "${1:-}" = "--catch-up" ]; then
    echo "[$(date -Iseconds)] Catch-up: scanning last ${MAX_CATCHUP_DAYS} weekdays for missed runs"
    MISSED=0
    for i in $(seq 1 ${MAX_CATCHUP_DAYS}); do
        CHECK_DATE=$(date -d "-${i} days" +%Y-%m-%d 2>/dev/null || continue)
        CHECK_DOW=$(date -d "${CHECK_DATE}" +%u 2>/dev/null || continue)
        # Skip weekends
        [ "${CHECK_DOW}" -gt 5 ] && continue
        # Skip if snapshot already exists
        if [ -d "${SNAPSHOT_DIR}/${CHECK_DATE}" ]; then
            continue
        fi
        echo "[$(date -Iseconds)] Catch-up: missed ${CHECK_DATE}, running backfill"
        "$0" "${CHECK_DATE}" || true
        MISSED=$((MISSED + 1))
    done
    if [ ${MISSED} -eq 0 ]; then
        echo "[$(date -Iseconds)] Catch-up: no missed runs found"
    else
        echo "[$(date -Iseconds)] Catch-up: backfilled ${MISSED} missed day(s)"
    fi
    exit 0
fi

# Date: use argument or today
AS_OF_DATE="${1:-$(date +%Y-%m-%d)}"

# Ensure log directory exists
mkdir -p "${LOG_DIR}"

# Prevent concurrent runs
if [ -f "${LOCK_FILE}" ]; then
    LOCK_PID=$(cat "${LOCK_FILE}" 2>/dev/null || echo "")
    if [ -n "${LOCK_PID}" ] && kill -0 "${LOCK_PID}" 2>/dev/null; then
        echo "[$(date -Iseconds)] SKIP: another daily production run is active (PID ${LOCK_PID})"
        exit 0
    else
        echo "[$(date -Iseconds)] WARN: stale lock file removed (PID ${LOCK_PID} not running)"
        rm -f "${LOCK_FILE}"
    fi
fi

# Write lock
echo $$ > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT

# Load environment
cd "${REPO_ROOT}"
if [ -f "${REPO_ROOT}/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.env"
    set +a
fi

LOG_FILE="${LOG_DIR}/daily_production_${AS_OF_DATE}.log"

echo "[$(date -Iseconds)] Starting daily production for ${AS_OF_DATE}" | tee -a "${LOG_FILE}"

# Check if it's a weekday (skip weekends)
DOW=$(date -d "${AS_OF_DATE}" +%u 2>/dev/null || echo "0")
if [ "${DOW}" -gt 5 ]; then
    echo "[$(date -Iseconds)] SKIP: ${AS_OF_DATE} is a weekend (day ${DOW})" | tee -a "${LOG_FILE}"
    exit 0
fi

# Run the production pipeline (timeout: 45 minutes)
PIPELINE_TIMEOUT=2700
if command -v timeout >/dev/null 2>&1; then
    timeout --signal=TERM --kill-after=60 ${PIPELINE_TIMEOUT} \
        ${PYTHON} tools/run_daily_production.py \
        --as-of-date "${AS_OF_DATE}" \
        >> "${LOG_FILE}" 2>&1
    EXIT_CODE=$?
    if [ ${EXIT_CODE} -eq 124 ]; then
        echo "[$(date -Iseconds)] TIMEOUT: pipeline exceeded ${PIPELINE_TIMEOUT}s — killed" | tee -a "${LOG_FILE}"
    fi
else
    ${PYTHON} tools/run_daily_production.py \
        --as-of-date "${AS_OF_DATE}" \
        >> "${LOG_FILE}" 2>&1
    EXIT_CODE=$?
fi

if [ ${EXIT_CODE} -eq 0 ]; then
    echo "[$(date -Iseconds)] PASS: daily production completed successfully" | tee -a "${LOG_FILE}"
elif [ ${EXIT_CODE} -eq 2 ]; then
    echo "[$(date -Iseconds)] WARN: daily production completed with warnings (exit 2)" | tee -a "${LOG_FILE}"
else
    echo "[$(date -Iseconds)] FAIL: daily production failed (exit ${EXIT_CODE})" | tee -a "${LOG_FILE}"
fi

# --- Housekeeping: prune pre-staging snapshots and old logs ---
# Pre-staging (__pre_*) dirs older than 7 days are removed (temporary staging).
# Regular snapshots are kept indefinitely (small, used for backtesting).
# Logs older than 60 days are removed.
PRE_STAGING_DAYS=7
LOG_RETENTION_DAYS=60

prune_count=0
for dir in "${SNAPSHOT_DIR}"/*__pre_*; do
    [ -d "${dir}" ] || continue
    dirname=$(basename "${dir}")
    snap_date="${dirname:0:10}"
    snap_epoch=$(date -d "${snap_date}" +%s 2>/dev/null || continue)
    now_epoch=$(date +%s)
    age_days=$(( (now_epoch - snap_epoch) / 86400 ))
    if [ ${age_days} -gt ${PRE_STAGING_DAYS} ]; then
        rm -rf "${dir}"
        prune_count=$((prune_count + 1))
    fi
done

# Prune old logs
for logfile in "${LOG_DIR}"/daily_production_*.log; do
    [ -f "${logfile}" ] || continue
    log_epoch=$(stat -c %Y "${logfile}" 2>/dev/null || continue)
    now_epoch=$(date +%s)
    age_days=$(( (now_epoch - log_epoch) / 86400 ))
    if [ ${age_days} -gt ${LOG_RETENTION_DAYS} ]; then
        rm -f "${logfile}"
        prune_count=$((prune_count + 1))
    fi
done

if [ ${prune_count} -gt 0 ]; then
    echo "[$(date -Iseconds)] Housekeeping: pruned ${prune_count} old pre-staging/log item(s)" | tee -a "${LOG_FILE}"
fi

# NOTE: OpenClaw agents (ops/sentinel/qa) run on their own cron schedule
# staggered after production: 5:00 / 5:15 / 5:30 PM ET.
# They are NOT triggered from this script to avoid inspecting half-built packets.

echo "[$(date -Iseconds)] Log: ${LOG_FILE}" | tee -a "${LOG_FILE}"
exit ${EXIT_CODE}
