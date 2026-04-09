#!/usr/bin/env bash
# cron_data_auditor.sh — Run data integrity audits after daily production.
#
# Schedule (crontab -e):
#   Daily (weekdays ~5:30 PM ET, after production completes):
#     30 17 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_data_auditor.sh --daily-only >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/cron.log 2>&1
#   Weekly (Saturday ~6 AM ET):
#     0 6 * * 6 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_data_auditor.sh --weekly-only >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/cron.log 2>&1

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
LOG_DIR="${REPO_ROOT}/logs"
AS_OF_DATE="${AS_OF_DATE:-$(date +%Y-%m-%d)}"

mkdir -p "${LOG_DIR}"

MODE_FLAG="${1:-}"

echo "[$(date -Iseconds)] data_auditor: starting ${MODE_FLAG:-all} audit for ${AS_OF_DATE}"

cd "${REPO_ROOT}"
${PYTHON} agents/data_auditor/run_audit.py --as-of-date "${AS_OF_DATE}" ${MODE_FLAG}
EXIT_CODE=$?

case ${EXIT_CODE} in
    0) STATUS="PASS" ;;
    1) STATUS="FAIL" ;;
    2) STATUS="WARN" ;;
    *) STATUS="ERROR" ;;
esac

echo "[$(date -Iseconds)] data_auditor: ${STATUS} (exit ${EXIT_CODE})"
exit ${EXIT_CODE}
