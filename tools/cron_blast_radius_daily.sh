#!/usr/bin/env bash
# cron_blast_radius_daily.sh — Daily blast-radius diff vs prior trading day.
#
# Compares today's data/snapshots/{today}/rankings.csv against the most
# recent prior weekday snapshot, writes a markdown report to
# artifacts/blast_radius/{today}.md, and emits a single-line summary
# (top-N churn count, max |Δrank|, dirty-ticker %) to the log.
#
# Designed to run AFTER production_qa_check.py (18:55 ET).
#
# Cron schedule (installed alongside this script):
#   15 19 * * 1-5  (7:15 PM ET weekdays)

set -euo pipefail

REPO_ROOT="/mnt/c/Projects/biotech_screener/biotech-screener"
PYTHON="/usr/bin/python3"
LOG_DIR="${REPO_ROOT}/logs"
ARTIFACT_DIR="${REPO_ROOT}/artifacts/blast_radius"
SNAPSHOT_DIR="${REPO_ROOT}/data/snapshots"
DATA_EXTRAS_LOG="${LOG_DIR}/data_extras.log"

cd "$REPO_ROOT"
mkdir -p "$LOG_DIR" "$ARTIFACT_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] blast-radius: $*"
}

TODAY=$(date +%Y-%m-%d)
TODAY_SNAP="${SNAPSHOT_DIR}/${TODAY}/rankings.csv"

if [ ! -f "$TODAY_SNAP" ]; then
    log "SKIP: no snapshot for ${TODAY} (production may not have run yet)"
    exit 0
fi

# Find most recent prior weekday snapshot (look back up to 7 days)
PRIOR_DATE=""
for i in 1 2 3 4 5 6 7; do
    CAND_DATE=$(date -d "${TODAY} -${i} days" +%Y-%m-%d 2>/dev/null || continue)
    CAND_DOW=$(date -d "${CAND_DATE}" +%u 2>/dev/null || continue)
    [ "${CAND_DOW}" -gt 5 ] && continue   # skip Sat/Sun
    if [ -f "${SNAPSHOT_DIR}/${CAND_DATE}/rankings.csv" ]; then
        PRIOR_DATE="${CAND_DATE}"
        break
    fi
done

if [ -z "$PRIOR_DATE" ]; then
    log "SKIP: no prior weekday snapshot found in last 7 days"
    exit 0
fi

PRIOR_SNAP="${SNAPSHOT_DIR}/${PRIOR_DATE}/rankings.csv"
REPORT="${ARTIFACT_DIR}/${TODAY}.md"

log "diff: ${PRIOR_DATE} → ${TODAY}"

# Run the diff, capturing stdout for inline summary
DIFF_OUTPUT=$($PYTHON tools/diff_rankings_blast_radius.py \
    --before "$PRIOR_SNAP" \
    --after  "$TODAY_SNAP" \
    --report "$REPORT" 2>&1) || {
    log "FAIL: diff tool exited non-zero"
    echo "$DIFF_OUTPUT" | tail -20
    exit 1
}

# Extract the headline metrics from the diff output for the log
ENTERED=$(echo "$DIFF_OUTPUT" | grep -oE 'entered \([0-9]+\)' | head -1 || echo "entered (?)")
LEFT=$(echo "$DIFF_OUTPUT" | grep -oE 'left    \([0-9]+\)' | head -1 || echo "left (?)")
DIRTY_PCT=$(echo "$DIFF_OUTPUT" | grep -oE 'Tickers with any field change: [0-9]+/[0-9]+ \([0-9.]+%\)' | head -1 || echo "dirty %: ?")
MAX_SHIFT=$(echo "$DIFF_OUTPUT" | grep -oE 'max \|Δrank\|=[0-9.]+' | head -1 || echo "max |Δrank|: ?")

log "summary: top-30 ${ENTERED} / ${LEFT} | ${DIRTY_PCT} | ${MAX_SHIFT}"

# Flag any column where >30% of universe shifted (potential anomaly)
# The diff tool prints lines like "  319  col_name  mean|Δ|=..." — extract counts.
TOTAL_TICKERS=$(echo "$DIFF_OUTPUT" | grep -oE 'shared: [0-9]+' | head -1 | grep -oE '[0-9]+' || echo "0")
if [ "$TOTAL_TICKERS" -gt 0 ]; then
    THRESHOLD=$(( TOTAL_TICKERS * 30 / 100 ))
    HIGH_BLAST=$(echo "$DIFF_OUTPUT" | awk -v t="$THRESHOLD" '
        /^Top columns by tickers-changed:/ { in_section=1; next }
        /^[A-Z]/ { in_section=0 }
        in_section && NF >= 2 {
            n=$1
            col=$2
            if (n+0 > t) print "  " n "  " col
        }')
    if [ -n "$HIGH_BLAST" ]; then
        log "HIGH-BLAST columns (>${THRESHOLD}/${TOTAL_TICKERS} = 30% of universe shifted):"
        echo "$HIGH_BLAST" | while read -r line; do log "  $line"; done
    fi
fi

# Tail data_extras.log for today's stages — confirm the new fetchers ran clean
if [ -f "$DATA_EXTRAS_LOG" ]; then
    TODAY_STAGES=$(grep "^\[${TODAY}" "$DATA_EXTRAS_LOG" | grep -E "(form4|short interest|PIT financials|Purple Book) (done|TIMED OUT|failed)" || true)
    if [ -n "$TODAY_STAGES" ]; then
        log "data_extras stages today:"
        echo "$TODAY_STAGES" | while read -r line; do log "  $line"; done
    else
        log "data_extras log: no stage lines for ${TODAY} (fetchers may not have fired)"
    fi
fi

log "report: ${REPORT}"
