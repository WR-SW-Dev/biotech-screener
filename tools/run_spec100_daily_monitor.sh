#!/usr/bin/env bash
# Spec 100 daily horizon monitor — run each day until July 8 primary gate.
#
# Purpose: track final_score IC trajectory across T+5..T+20 as forward snapshots
# accumulate. All output is MONITOR_ONLY / NOT_PRIMARY_GATE. July 8 T+20 is the gate.
#
# Usage:
#   bash tools/run_spec100_daily_monitor.sh              # uses today's date
#   bash tools/run_spec100_daily_monitor.sh 2026-07-01   # explicit end date
#
# Output: artifacts/spec100/ (memo files committed; csv/json gitignored)

set -euo pipefail
cd "$(dirname "$0")/.."

END_DATE="${1:-$(date +%Y-%m-%d)}"
BASE_DATE="2026-06-18"
OUTPUT_DIR="artifacts/spec100"
mkdir -p "$OUTPUT_DIR"

echo "=== Spec 100 Daily Monitor: base=$BASE_DATE end=$END_DATE ==="
echo "    Status: MONITOR_ONLY / NOT_PRIMARY_GATE / NOT_PROMOTION_EVIDENCE"
echo ""

# Run all five fields at all available horizons
for FLD in final_score catalyst_decay_w catalyst_score coinvest_score_z financial_score; do
    echo "--- $FLD ---"
    python3 tools/measure_final_score_ic_spec100.py \
        --score-field "$FLD" \
        --start-date "$BASE_DATE" \
        --end-date "$END_DATE" \
        --horizons 5 10 15 20 \
        --forward-date-mode nearest_later \
        --forward-tolerance-days 5 \
        --output-dir "$OUTPUT_DIR" \
        2>&1 | grep -E "T\+[0-9]+.*IC=|mean=|>= 0.0200|SUMMARY"
    echo ""
done

echo "=== Done. Primary gate: 2026-07-08 (T+20 from $BASE_DATE) ==="
echo "    Run July 8 runbook: docs/dem_ranker_july8_ic_remeasurement_runbook.md"
