#!/usr/bin/env bash
# run_post_snapshot_supervisor.sh — re-run post-snapshot tasks killed by WSL
#
# Usage: ./tools/run_post_snapshot_supervisor.sh [YYYY-MM-DD]
#   Default date: today (America/Detroit)
#
# Owns Steps 5n (AACT) and 5l.5 (Herald) from run_daily_production.py for the
# case where the parent died after snapshot promotion. Each task is idempotent
# via its own done predicate; re-running after a successful pass is a no-op.

set -uo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
LOG_FILE="${REPO_ROOT}/logs/post_snapshot_supervisor.log"
LOCK_FILE="${REPO_ROOT}/logs/.post_snapshot_supervisor.lock"
WRAPPER_TIMEOUT=2400  # 40 min — AACT (1800s) + Herald fetch (1800s) staged

AS_OF_DATE="${1:-$(TZ=America/Detroit date +%Y-%m-%d)}"

mkdir -p "$(dirname "${LOG_FILE}")"

# Defer if daily_production is actively running. Step 5n (AACT) and 5l.5
# (Herald) are still owned by the in-pipeline path; running them concurrently
# from the supervisor would clobber the same artifacts. The next watchdog tick
# (≤30 min) will retry once daily_production has released its lock.
DAILY_LOCK="${REPO_ROOT}/logs/.daily_production.lock"
if [ -f "${DAILY_LOCK}" ]; then
    DAILY_PID=$(cat "${DAILY_LOCK}" 2>/dev/null || echo "")
    if [ -n "${DAILY_PID}" ] && kill -0 "${DAILY_PID}" 2>/dev/null; then
        echo "[$(date -Iseconds)] DEFER: daily_production active (PID ${DAILY_PID}) — supervisor will retry next tick" \
            | tee -a "${LOG_FILE}"
        exit 0
    fi
fi

# Stale-lock-tolerant concurrency guard
if [ -f "${LOCK_FILE}" ]; then
    LOCK_PID=$(cat "${LOCK_FILE}" 2>/dev/null || echo "")
    if [ -n "${LOCK_PID}" ] && kill -0 "${LOCK_PID}" 2>/dev/null; then
        echo "[$(date -Iseconds)] SKIP: supervisor already running (PID ${LOCK_PID})" \
            | tee -a "${LOG_FILE}"
        exit 0
    fi
    rm -f "${LOCK_FILE}"
fi
echo $$ > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT

cd "${REPO_ROOT}"

# Load env (matches cron_daily_production.sh's parser — handles $ in values)
if [ -f "${REPO_ROOT}/.env" ]; then
    while IFS= read -r line || [ -n "${line}" ]; do
        [[ -z "${line}" || "${line}" =~ ^[[:space:]]*# ]] && continue
        key="${line%%=*}"
        val="${line#*=}"
        val="${val#\"}" ; val="${val%\"}"
        val="${val#\'}" ; val="${val%\'}"
        export "${key}=${val}"
    done < "${REPO_ROOT}/.env"
fi

echo "[$(date -Iseconds)] Supervisor invoked for ${AS_OF_DATE}" | tee -a "${LOG_FILE}"

if command -v timeout >/dev/null 2>&1; then
    timeout --signal=TERM --kill-after=60 ${WRAPPER_TIMEOUT} \
        "${PYTHON}" tools/run_post_snapshot_supervisor.py \
        --as-of-date "${AS_OF_DATE}" \
        >> "${LOG_FILE}" 2>&1
    EXIT_CODE=$?
    if [ ${EXIT_CODE} -eq 124 ]; then
        echo "[$(date -Iseconds)] TIMEOUT: supervisor exceeded ${WRAPPER_TIMEOUT}s — killed" \
            | tee -a "${LOG_FILE}"
    fi
else
    "${PYTHON}" tools/run_post_snapshot_supervisor.py \
        --as-of-date "${AS_OF_DATE}" \
        >> "${LOG_FILE}" 2>&1
    EXIT_CODE=$?
fi

case ${EXIT_CODE} in
    0) echo "[$(date -Iseconds)] Supervisor PASS for ${AS_OF_DATE}" | tee -a "${LOG_FILE}" ;;
    2) echo "[$(date -Iseconds)] Supervisor INCOMPLETE for ${AS_OF_DATE} — task(s) failed; retry next tick" \
            | tee -a "${LOG_FILE}" ;;
    *) echo "[$(date -Iseconds)] Supervisor FAIL exit=${EXIT_CODE} for ${AS_OF_DATE}" \
            | tee -a "${LOG_FILE}" ;;
esac

exit ${EXIT_CODE}
