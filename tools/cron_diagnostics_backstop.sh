#!/usr/bin/env bash
# cron_diagnostics_backstop.sh — Standalone runner for the 4 hardening
# diagnostic reports.
#
# Background: the same builders run inside cron_daily_production.sh (lines
# 196-222), but on WSL2 the wrapper's tail is unreachable when the python
# pipeline subprocess gets reaped — observed continuously 2026-04-28 →
# 2026-05-04, exposed by the 2026-05-04 hardening audit one-shot. The
# wrapper-tail block had never run in production despite shipping 2026-04-27.
#
# This script is a backstop: it runs the same 4 builders independently of
# the wrapper, gated on the snapshot's rankings.csv being present. Each
# builder is read-only and idempotent — re-running over an already-built
# report just overwrites it. If the wrapper tail does run successfully one
# day, this is harmless; if it doesn't (current default), this catches it.
#
# Cron entry (Mon-Fri 17:25 ET — after 16:30 production wrapper would have
# either finished or been reaped, before production_qa_check at 17:35):
#   25 17 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_diagnostics_backstop.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/diagnostics_backstop.log 2>&1

set -uo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
AS_OF_DATE="${1:-$(date +%Y-%m-%d)}"
SNAPSHOT_DIR="${REPO_ROOT}/data/snapshots/${AS_OF_DATE}"
LOG_PREFIX="[$(date -Iseconds)]"

cd "$REPO_ROOT"

if [ ! -f "${SNAPSHOT_DIR}/rankings.csv" ]; then
    echo "${LOG_PREFIX} SKIP: ${SNAPSHOT_DIR}/rankings.csv not present"
    exit 0
fi

echo "${LOG_PREFIX} Building diagnostic reports for ${AS_OF_DATE}"

# Rank-change monitor: same wrapper-tail dependency as the 4 hardening
# reports (originally lived only in cron_daily_production.sh:151-194). Run
# it FIRST so its artifacts exist before downstream consumers (production_qa
# at 17:35, postmortem detection, evening agents) read the snapshot.
#
# Webhook side effects intentionally NOT replicated here — the
# CRITICAL-rank-change webhook stays in the wrapper-tail to avoid duplicate
# alerts on days when both wrapper-tail and backstop succeed. Wrapper-tail
# webhook failures are already covered by the wrapper's PASS/WARN/FAIL
# webhook in cron_daily_production.sh:134-141.
${PYTHON} tools/build_rank_change_monitor.py --as-of-date "${AS_OF_DATE}" --quiet \
    2>&1 | sed "s|^|${LOG_PREFIX} build_rank_change_monitor: |"
rc=${PIPESTATUS[0]}
if [ "${rc}" -ne 0 ]; then
    echo "${LOG_PREFIX} WARN: build_rank_change_monitor exited ${rc}"
fi

for tool in build_snapshot_integrity_report \
            build_feature_coverage_report \
            build_distribution_drift_report \
            build_sentinel_ticker_report; do
    ${PYTHON} "tools/${tool}.py" --as-of-date "${AS_OF_DATE}" --quiet \
        2>&1 | sed "s|^|${LOG_PREFIX} ${tool}: |"
    rc=${PIPESTATUS[0]}
    if [ "${rc}" -ne 0 ]; then
        echo "${LOG_PREFIX} WARN: ${tool} exited ${rc}"
    fi
done

# Reconcile any null prediction_composite_score fields created in the last 7d.
# Idempotent and fast (~120 records); safe to run daily.
${PYTHON} tools/backfill_resolution_predictions.py \
    2>&1 | sed "s|^|${LOG_PREFIX} backfill_resolution_predictions: |"
rc=${PIPESTATUS[0]}
if [ "${rc}" -ne 0 ]; then
    echo "${LOG_PREFIX} WARN: backfill_resolution_predictions exited ${rc}"
fi

echo "${LOG_PREFIX} Done"
