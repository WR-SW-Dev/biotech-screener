#!/usr/bin/env bash
# cron_intraday_mover.sh — wrapper for the intraday mover watch agent.
#
# Runs one poll (or the end-of-day digest) via
# tools/build_intraday_mover_watch.py. Designed for standard cron on WSL2.
#
# Spec: specs/changes/spec_063_intraday_mover_watch.md
# Phase: 3 (cron registration)
#
# Usage:
#   ./tools/cron_intraday_mover.sh poll               # one intraday poll
#   ./tools/cron_intraday_mover.sh digest             # EOD digest
#   ./tools/cron_intraday_mover.sh poll --no-email    # poll, skip email send
#
# Recommended crontab entries (in America/Detroit; cron inherits TZ).
# Conservative first-week cadence: 30-minute polls instead of 15, plus two
# open-window polls and one EOD digest. Upgrade to 15-min cadence once a
# week of no-spam operation is verified.
#
# Add with `crontab -e`:
#
#   # intraday mover first poll (10:30 ET, after production run completes)
#   30 10 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_intraday_mover.sh poll >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/intraday_mover.log 2>&1
#
#   # intraday mover core hours (every 30 min, 11:00–15:30 ET)
#   0,30 11-15 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_intraday_mover.sh poll >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/intraday_mover.log 2>&1
#
#   # end-of-day digest (16:15 ET)
#   15 16 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_intraday_mover.sh digest >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/intraday_mover.log 2>&1

set -uo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
LOG_DIR="${REPO_ROOT}/logs"
LOCK_FILE="${LOG_DIR}/.intraday_mover.lock"

cd "${REPO_ROOT}" || exit 1
mkdir -p "${LOG_DIR}"

# Load .env so APCA_* and SMTP_* are visible to the python process
set -a
# shellcheck disable=SC1091
source "${REPO_ROOT}/.env" 2>/dev/null || true
set +a

MODE="${1:-poll}"
shift || true
EXTRA_ARGS=("$@")

# Skip if prior run is still active (cron can overlap on slow WSL wake)
if [ -f "${LOCK_FILE}" ]; then
    PID=$(cat "${LOCK_FILE}" 2>/dev/null || echo "")
    if [ -n "${PID}" ] && kill -0 "${PID}" 2>/dev/null; then
        echo "[$(date -Iseconds)] intraday_mover: prior run (pid ${PID}) still active; skipping"
        exit 0
    fi
fi
echo $$ > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT

# Determine default send-email behavior per mode.
# SEND_FLAG can be explicitly disabled by passing --no-email.
SEND_FLAG="--send-email"
for arg in "${EXTRA_ARGS[@]:-}"; do
    if [ "${arg}" = "--no-email" ]; then
        SEND_FLAG=""
    fi
done

case "${MODE}" in
    poll)
        # Use the America/Detroit trading day for the date portion so
        # late-evening runs (>20:00 ET, after UTC midnight) still resolve
        # to today's rankings/artifacts, not tomorrow's UTC date.
        ET_DATE=$(TZ=America/Detroit date +%Y-%m-%d)
        UTC_TIME=$(date -u +%H:%M:%S)
        AS_OF_TS="${ET_DATE}T${UTC_TIME}Z"
        echo "[$(date -Iseconds)] intraday_mover: poll as_of=${AS_OF_TS} send=${SEND_FLAG:-off}"
        # shellcheck disable=SC2086
        ${PYTHON} "${REPO_ROOT}/tools/build_intraday_mover_watch.py" \
            --as-of-ts "${AS_OF_TS}" \
            ${SEND_FLAG}
        ;;
    digest)
        AS_OF_DATE=$(TZ=America/Detroit date +%Y-%m-%d)
        echo "[$(date -Iseconds)] intraday_mover: digest as_of=${AS_OF_DATE} send=${SEND_FLAG:-off}"
        # shellcheck disable=SC2086
        ${PYTHON} "${REPO_ROOT}/tools/build_intraday_mover_watch.py" \
            --as-of-date "${AS_OF_DATE}" \
            --digest-only \
            ${SEND_FLAG}

        if [ -n "${FIRECRAWL_API_KEY:-}" ]; then
            echo "[$(date -Iseconds)] intraday_mover: firecrawl digest enrichment (timeout 120s)"
            timeout 120 "${PYTHON}" "${REPO_ROOT}/tools/enrich_intraday_digest_with_research.py" \
                --date "${AS_OF_DATE}" \
                || echo "[$(date -Iseconds)] intraday_mover: firecrawl enrichment failed or timed out — digest unchanged on disk except prior step"
        else
            echo "[$(date -Iseconds)] intraday_mover: firecrawl enrichment skipped (FIRECRAWL_API_KEY unset)"
        fi
        ;;
    *)
        echo "usage: $0 {poll|digest} [--no-email]" >&2
        exit 64
        ;;
esac
