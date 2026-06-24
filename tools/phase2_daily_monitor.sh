#!/usr/bin/env bash
# Phase 2 daily gate monitoring wrapper (updated 2026-06-24).
# Phase 2 window: 2026-06-01 to 2026-07-01 (extended from 2026-06-17).
# Logs to logs/phase2_monitor.log with timestamp.
#
# Usage:
#   ./tools/phase2_daily_monitor.sh              # run for today
#   ./tools/phase2_daily_monitor.sh 2026-06-24   # run for specific date

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${REPO_ROOT}/logs/phase2_monitor.log"
PYTHON="/usr/bin/python3"

DATE_ARG="${1:-$(date +%Y-%m-%d)}"

mkdir -p "${REPO_ROOT}/logs"

{
    echo "[$(date -Iseconds)] Phase 2 daily monitor — ${DATE_ARG}"
    cd "${REPO_ROOT}"
    "${PYTHON}" tools/verify_phase2_gates.py --as-of-date "${DATE_ARG}"
    echo "[$(date -Iseconds)] Done"
} 2>&1 | tee -a "${LOG_FILE}"
