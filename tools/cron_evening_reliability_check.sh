#!/usr/bin/env bash
# cron_evening_reliability_check.sh — Morning watchdog for evening forward-shadow jobs.
#
# Runs ~09:15 ET on weekdays after daily_production completes. Detects whether
# inst_delta_forward_compare and cross_signal_forward_logger ran the prior trading
# day. If either job missed its run, backfills from cached snapshots (safe, deterministic).
#
# Artifacts checked:
#   - inst_delta: artifacts/audit/inst_delta_forward_shadow/checkpoint_{DATE}.json
#   - cross_signal: artifacts/audit/cross_signal_forward_shadow/buckets_{DATE}.json
#
# Backfill behavior:
#   - If missing, runs Python script with --as-of {DATE}
#   - Idempotent: safe to re-run
#   - Logs: artifacts/audit/evening_reliability_checks/watchdog_{TODAY}.log
#
# Crontab (optional):
#   15 09 * * 1-5 /mnt/c/Projects/biotech_screener/biotech-screener/tools/cron_evening_reliability_check.sh >> /mnt/c/Projects/biotech_screener/biotech-screener/logs/evening_reliability_check.log 2>&1

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
AUDIT_DIR="${REPO_ROOT}/artifacts/audit"
CHECKS_LOG_DIR="${AUDIT_DIR}/evening_reliability_checks"
LOG_PREFIX="[$(date -Iseconds)]"

cd "$REPO_ROOT"

# Ensure log directory exists
mkdir -p "$CHECKS_LOG_DIR"

TODAY=$(date +%Y-%m-%d)
LOG_FILE="${CHECKS_LOG_DIR}/watchdog_${TODAY}.log"

# Determine prior trading day (skip weekends)
PRIOR_DAY=$(date -d "1 day ago" +%Y-%m-%d)
PRIOR_DOW=$(date -d "$PRIOR_DAY" +%u)

# If prior day is Saturday (6) or Sunday (0), go back to Friday
if [ "$PRIOR_DOW" -eq 6 ]; then
    PRIOR_DAY=$(date -d "3 days ago" +%Y-%m-%d)
elif [ "$PRIOR_DOW" -eq 0 ]; then
    PRIOR_DAY=$(date -d "2 days ago" +%Y-%m-%d)
fi

# Skip if today is Saturday/Sunday (weekend)
DOW=$(date +%u)
if [ "$DOW" -gt 5 ]; then
    echo "${LOG_PREFIX} SKIP: today=${TODAY} is weekend (DOW=${DOW})" | tee -a "$LOG_FILE"
    exit 0
fi

{
    echo "${LOG_PREFIX} Evening reliability check for prior trading day: ${PRIOR_DAY}"

    # Check inst_delta artifact
    INST_DELTA_ARTIFACT="${AUDIT_DIR}/inst_delta_forward_shadow/checkpoint_${PRIOR_DAY}.json"
    if [ -f "$INST_DELTA_ARTIFACT" ]; then
        echo "${LOG_PREFIX} ✅ inst_delta checkpoint exists: ${PRIOR_DAY}"
    else
        echo "${LOG_PREFIX} ⚠️  Missing inst_delta checkpoint for ${PRIOR_DAY}; running backfill..."
        if /usr/bin/python3 "${REPO_ROOT}/tools/inst_delta_forward_compare.py" --as-of "$PRIOR_DAY" 2>&1 | grep -q "ERROR\|FATAL\|Traceback"; then
            echo "${LOG_PREFIX} ❌ inst_delta backfill FAILED for ${PRIOR_DAY}"
        else
            echo "${LOG_PREFIX} ✅ inst_delta backfill completed for ${PRIOR_DAY}"
        fi
    fi

    # Check cross_signal artifact
    CROSS_SIGNAL_ARTIFACT="${AUDIT_DIR}/cross_signal_forward_shadow/buckets_${PRIOR_DAY}.json"
    if [ -f "$CROSS_SIGNAL_ARTIFACT" ]; then
        echo "${LOG_PREFIX} ✅ cross_signal buckets exist: ${PRIOR_DAY}"
    else
        echo "${LOG_PREFIX} ⚠️  Missing cross_signal buckets for ${PRIOR_DAY}; running backfill..."
        if /usr/bin/python3 "${REPO_ROOT}/tools/cross_signal_forward_logger.py" --as-of "$PRIOR_DAY" 2>&1 | grep -q "ERROR\|FATAL\|Traceback"; then
            echo "${LOG_PREFIX} ❌ cross_signal backfill FAILED for ${PRIOR_DAY}"
        else
            echo "${LOG_PREFIX} ✅ cross_signal backfill completed for ${PRIOR_DAY}"
        fi
    fi

    # production_qa_check — today's QA report (needs today's snapshot)
    PROD_QA_ARTIFACT="${REPO_ROOT}/artifacts/production_qa/${TODAY}_report.json"
    RANKINGS="${REPO_ROOT}/data/snapshots/${TODAY}/rankings.csv"
    if [ -f "$PROD_QA_ARTIFACT" ]; then
        echo "${LOG_PREFIX} ✅ production_qa report exists: ${TODAY}"
    elif [ ! -f "$RANKINGS" ]; then
        echo "${LOG_PREFIX} ⏳ production_qa deferred — no rankings.csv for ${TODAY} yet"
    else
        echo "${LOG_PREFIX} ⚠️  Missing production_qa for ${TODAY}; running backfill..."
        if /usr/bin/python3 "${REPO_ROOT}/tools/production_qa_check.py" \
                --as-of-date "${TODAY}" >> "${REPO_ROOT}/logs/production_qa.log" 2>&1; then
            echo "${LOG_PREFIX} ✅ production_qa completed for ${TODAY}"
        else
            echo "${LOG_PREFIX} ⚠️  production_qa exit non-zero for ${TODAY} (alerts or FAIL — see log)"
        fi
    fi

    # calibration_evidence + event_feedback_metrics — weekly Friday jobs
    # Find most recent Friday (or today if today is Friday)
    if [ "$(date +%u)" -eq 5 ]; then
        LAST_FRIDAY="${TODAY}"
    else
        LAST_FRIDAY=$(date -d "last friday" +%Y-%m-%d)
    fi

    CAL_ARTIFACT="${REPO_ROOT}/artifacts/calibration_evidence/${LAST_FRIDAY}_evidence.json"
    if [ -f "$CAL_ARTIFACT" ]; then
        echo "${LOG_PREFIX} ✅ calibration_evidence exists: ${LAST_FRIDAY}"
    else
        echo "${LOG_PREFIX} ⚠️  Missing calibration_evidence for ${LAST_FRIDAY}; running backfill..."
        if /usr/bin/python3 "${REPO_ROOT}/tools/build_calibration_evidence.py" \
                --as-of-date "${LAST_FRIDAY}" >> "${REPO_ROOT}/logs/calibration_evidence.log" 2>&1; then
            echo "${LOG_PREFIX} ✅ calibration_evidence completed for ${LAST_FRIDAY}"
        else
            echo "${LOG_PREFIX} ❌ calibration_evidence FAILED for ${LAST_FRIDAY}"
        fi
    fi

    EFM_ARTIFACT="${REPO_ROOT}/artifacts/event_feedback/metrics_${LAST_FRIDAY}.json"
    if [ -f "$EFM_ARTIFACT" ]; then
        echo "${LOG_PREFIX} ✅ event_feedback_metrics exists: ${LAST_FRIDAY}"
    else
        echo "${LOG_PREFIX} ⚠️  Missing event_feedback_metrics for ${LAST_FRIDAY}; running backfill..."
        if /usr/bin/python3 "${REPO_ROOT}/tools/build_event_feedback_metrics.py" \
                --as-of-date "${LAST_FRIDAY}" >> "${REPO_ROOT}/logs/event_feedback_metrics.log" 2>&1; then
            echo "${LOG_PREFIX} ✅ event_feedback_metrics completed for ${LAST_FRIDAY}"
        else
            echo "${LOG_PREFIX} ❌ event_feedback_metrics FAILED for ${LAST_FRIDAY}"
        fi
    fi

    echo "${LOG_PREFIX} Evening reliability check complete"

} | tee -a "$LOG_FILE"
