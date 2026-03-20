#!/usr/bin/env bash
# cron_daily_production.sh — Automated daily production screen runner.
#
# Designed for cron on WSL2. Runs the full daily production pipeline
# for today's date, logging output to a dated log file.
#
# Usage:
#   ./tools/cron_daily_production.sh           # run for today
#   ./tools/cron_daily_production.sh 2026-03-20 # run for specific date
#
# Cron example (weekdays at 5:30 PM ET, after market close):
#   30 17 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_daily_production.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/cron.log 2>&1

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
LOG_DIR="${REPO_ROOT}/logs"
LOCK_FILE="${REPO_ROOT}/logs/.daily_production.lock"

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

# Run the production pipeline
${PYTHON} tools/run_daily_production.py \
    --as-of-date "${AS_OF_DATE}" \
    >> "${LOG_FILE}" 2>&1

EXIT_CODE=$?

if [ ${EXIT_CODE} -eq 0 ]; then
    echo "[$(date -Iseconds)] PASS: daily production completed successfully" | tee -a "${LOG_FILE}"
elif [ ${EXIT_CODE} -eq 2 ]; then
    echo "[$(date -Iseconds)] WARN: daily production completed with warnings (exit 2)" | tee -a "${LOG_FILE}"
else
    echo "[$(date -Iseconds)] FAIL: daily production failed (exit ${EXIT_CODE})" | tee -a "${LOG_FILE}"
fi

echo "[$(date -Iseconds)] Log: ${LOG_FILE}" | tee -a "${LOG_FILE}"
exit ${EXIT_CODE}
