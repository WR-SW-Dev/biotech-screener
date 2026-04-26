#!/usr/bin/env bash
# cron_bpiq_trial.sh — daily BPIQ trial-period pull + diff + day-over-day delta.
#
# Audit-only. SUPPORTING source. No production wiring.
# Trial expires 2026-05-10; the script self-disables after that date.
#
# Add with `crontab -e` (cron runs in local ET on this host, matching the
# existing intraday-mover schedule):
#
#   # BPIQ trial-period pull (10:05 ET, weekdays; auto-expires 2026-05-10)
#   5 10 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_bpiq_trial.sh \
#     >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/bpiq_trial.log 2>&1

set -uo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
LOG_DIR="${REPO_ROOT}/logs"
LOCK_FILE="${LOG_DIR}/.bpiq_trial.lock"
EXPIRY="2026-05-10"

cd "${REPO_ROOT}" || exit 1
mkdir -p "${LOG_DIR}"

TODAY="$(date -u +%Y-%m-%d)"
echo "[$(date -Iseconds)] bpiq_trial: starting (today=${TODAY})"

# Self-expiry: bail out cleanly after the trial window closes.
if [[ "${TODAY}" > "${EXPIRY}" ]]; then
    echo "[$(date -Iseconds)] bpiq_trial: trial window closed (${EXPIRY}); exiting without action"
    echo "[$(date -Iseconds)] bpiq_trial: remove the crontab entry to silence this message"
    exit 0
fi

# Skip if a prior run is still active (cron wakeup overlap on slow WSL).
if [ -f "${LOCK_FILE}" ]; then
    PID=$(cat "${LOCK_FILE}" 2>/dev/null || echo "")
    if [ -n "${PID}" ] && kill -0 "${PID}" 2>/dev/null; then
        echo "[$(date -Iseconds)] bpiq_trial: prior run (pid ${PID}) still active; skipping"
        exit 0
    fi
fi
echo $$ > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT

# Load .env so BPIQ_API_KEY is visible to the python process.
set -a
# shellcheck disable=SC1091
source "${REPO_ROOT}/.env" 2>/dev/null || true
set +a

if [ -z "${BPIQ_API_KEY:-}" ]; then
    echo "[$(date -Iseconds)] bpiq_trial: BPIQ_API_KEY not set in .env; aborting"
    exit 2
fi

# 1. pull catalysts
"${PYTHON}" tools/bpiq_trial_diff.py pull --days 60
PULL_RC=$?
if [ "${PULL_RC}" -ne 0 ]; then
    echo "[$(date -Iseconds)] bpiq_trial: pull failed rc=${PULL_RC}"
    exit "${PULL_RC}"
fi

# 2. diff vs pdufa_dates + event_ledger (overwrites today's CSV/MD)
"${PYTHON}" tools/bpiq_trial_diff.py diff
DIFF_RC=$?
if [ "${DIFF_RC}" -ne 0 ]; then
    echo "[$(date -Iseconds)] bpiq_trial: diff failed rc=${DIFF_RC}"
fi

# 3. day-over-day delta vs prior pull (appends to bpiq_trial_log.md)
"${PYTHON}" tools/bpiq_trial_diff.py delta
DELTA_RC=$?
if [ "${DELTA_RC}" -ne 0 ]; then
    echo "[$(date -Iseconds)] bpiq_trial: delta failed rc=${DELTA_RC}"
fi

echo "[$(date -Iseconds)] bpiq_trial: done"
