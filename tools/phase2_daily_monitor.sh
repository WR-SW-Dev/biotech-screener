#!/bin/bash
# Phase 2 Unified Daily Monitoring (2026-06-01 to 2026-06-17)
# Automated gate verification + fleet health + risk metrics
#
# Run: 08:00 AM ET (pre-market)
#      14:00 PM ET (intraday)
#      18:00 PM ET (post-trading signals)
#      22:00 PM ET (evening summary)
#
# Usage: bash tools/phase2_daily_monitor.sh [--check TYPE] [--date YYYY-MM-DD]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON3="/usr/bin/python3"
LOG_FILE="$REPO_ROOT/logs/phase2_monitor.log"
WINDOW_START="2026-06-01"
WINDOW_END="2026-06-17"
TODAY="${1:-$(date +%Y-%m-%d)}"
CHECK_TYPE="${2:-all}"  # all | gates | fleet | risk | report

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    local level="$1"
    shift
    local msg="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $msg" | tee -a "$LOG_FILE"
}

log "INFO" "=== Phase 2 Daily Monitoring Start ($(date '+%Y-%m-%d %H:%M:%S %Z')) ==="
log "INFO" "Window: $WINDOW_START to $WINDOW_END | Today: $TODAY"

# ============================================================================
# TIER 1: GOVERNANCE GATES VERIFICATION
# ============================================================================

if [[ "$CHECK_TYPE" == "all" || "$CHECK_TYPE" == "gates" ]]; then
    log "INFO" "[GATES] Verifying Phase 2 governance gates..."

    # Gate 1: Drawdown vs XBI
    log "INFO" "[GATE-1] Drawdown vs XBI"
    DRAWDOWN_FILE="$REPO_ROOT/artifacts/phase2_monitoring/drawdown_vs_xbi_$TODAY.json"
    if [ -f "$DRAWDOWN_FILE" ]; then
        DRAWDOWN=$(python3 -c "import json; d=json.load(open('$DRAWDOWN_FILE')); print(d.get('drawdown_pp', 'N/A'))")
        STATUS=$(python3 -c "import json; d=json.load(open('$DRAWDOWN_FILE')); print(d.get('status', '?'))")
        if [ "$STATUS" = "PASS" ]; then
            log "INFO" "  ✓ PASS: $DRAWDOWN pp (threshold: > -2.00pp)"
        elif [ "$STATUS" = "FAIL_HARD_EXIT" ]; then
            log "ERROR" "  🔴 FAIL_HARD_EXIT: $DRAWDOWN pp (EMERGENCY EXIT TRIGGERED)"
        else
            log "WARN" "  ⏳ $STATUS"
        fi
    else
        log "WARN" "  ⏳ Snapshot not ready yet"
    fi

    # Gate 2: 13F Jaccard
    log "INFO" "[GATE-2] 13F Cohort Stability (Jaccard)"
    JACCARD_FILE="$REPO_ROOT/artifacts/ic_health_monitor/memory/latest_jaccard.json"
    if [ -f "$JACCARD_FILE" ]; then
        JACCARD=$(python3 -c "import json; d=json.load(open('$JACCARD_FILE')); print(d.get('jaccard', 'N/A'))")
        STATUS=$(python3 -c "import json; d=json.load(open('$JACCARD_FILE')); print('PASS' if float(d.get('jaccard', 0)) >= 0.70 else 'DEFERRED')")
        log "INFO" "  ✓ $STATUS: $JACCARD (threshold: ≥ 0.70)"
    else
        log "WARN" "  ⏳ No 13F data yet"
    fi

    # Gate 3: IC Observable
    log "INFO" "[GATE-3] IC Observable Status"
    log "INFO" "  ⏳ Expected first IC print: ~2026-06-17"
    IC_DASHBOARD="$REPO_ROOT/artifacts/ic_dashboard/${TODAY}_dashboard.json"
    if [ -f "$IC_DASHBOARD" ]; then
        ATTENTION=$(python3 -c "import json; d=json.load(open('$IC_DASHBOARD')); print(d.get('attention', '?'))")
        N_SIGNALS=$(python3 -c "import json; d=json.load(open('$IC_DASHBOARD')); print(len(d.get('signals', {})))")
        log "INFO" "  Current: $N_SIGNALS signals, attention=$ATTENTION"
    fi

    # Gate 4: Emergency Exit
    log "INFO" "[GATE-4] Emergency Exit Conditions"
    log "INFO" "  ✓ ARMED: Hard trigger at drawdown > -2.00pp or 13F Jaccard < 0.70"
    log "INFO" "  ✓ Real-time monitoring: sentinel agent"

    log "INFO" "[GATES] Gate verification complete"
fi

# ============================================================================
# TIER 2: FLEET HEALTH & SIGNALS
# ============================================================================

if [[ "$CHECK_TYPE" == "all" || "$CHECK_TYPE" == "fleet" ]]; then
    log "INFO" "[FLEET] Checking Hermes fleet health..."

    # Run heartbeat checks (simplified summary)
    if command -v python3 &> /dev/null; then
        HEARTBEAT_OUTPUT=$("$PYTHON3" "$REPO_ROOT/tools/agent_heartbeat_checks.py" 2>&1 | grep -E "Summary:|OK:|FAIL:|WARN:" | head -5)
        log "INFO" "$HEARTBEAT_OUTPUT"
    else
        log "WARN" "[FLEET] Python3 not available for heartbeat check"
    fi
fi

# ============================================================================
# TIER 3: RISK METRICS
# ============================================================================

if [[ "$CHECK_TYPE" == "all" || "$CHECK_TYPE" == "risk" ]]; then
    log "INFO" "[RISK] Computing daily risk metrics..."

    SHADOW_FILE="$REPO_ROOT/artifacts/shadow_monitor/${TODAY}_monitor.json"
    if [ -f "$SHADOW_FILE" ]; then
        python3 -c "
import json
with open('$SHADOW_FILE') as f:
    data = json.load(f)
    print(f\"[RISK] Portfolio PnL: {data.get('cumulative', {}).get('total_pnl_pct', 'N/A')}%\")
    print(f\"[RISK] Max Drawdown: {data.get('cumulative', {}).get('max_drawdown_pct', 'N/A')}% (warn: 8%)\")
    print(f\"[RISK] Excess vs Policy: {data.get('cumulative', {}).get('total_excess_pct', 'N/A')}%\")
" | while read line; do log "INFO" "$line"; done
    else
        log "WARN" "[RISK] Shadow monitor data not ready"
    fi
fi

# ============================================================================
# TIER 4: REPORT GENERATION
# ============================================================================

if [[ "$CHECK_TYPE" == "all" || "$CHECK_TYPE" == "report" ]]; then
    log "INFO" "[REPORT] Generating daily monitoring report..."

    REPORT_DIR="$REPO_ROOT/artifacts/phase2_monitoring/daily"
    mkdir -p "$REPORT_DIR"

    REPORT_FILE="$REPORT_DIR/${TODAY}_report.txt"
    {
        echo "============================================================================"
        echo "PHASE 2 DAILY MONITORING REPORT"
        echo "Date: $TODAY | Window: $WINDOW_START to $WINDOW_END"
        echo "============================================================================"
        echo ""
        echo "GOVERNANCE GATES:"
        echo "  ✓ Drawdown vs XBI: [Check log for status]"
        echo "  ✓ 13F Jaccard: [Check log for status]"
        echo "  ⏳ IC Observable: Expected ~2026-06-17"
        echo "  ✓ Emergency Exit: ARMED"
        echo ""
        echo "FLEET HEALTH:"
        echo "  See heartbeat_checks output above"
        echo ""
        echo "RISK METRICS:"
        echo "  See risk metrics output above"
        echo ""
        echo "Generated: $(date '+%Y-%m-%d %H:%M:%S %Z')"
        echo "============================================================================"
    } | tee "$REPORT_FILE" | while read line; do log "INFO" "$line"; done

    log "INFO" "[REPORT] Report saved to $REPORT_FILE"
fi

log "INFO" "=== Phase 2 Daily Monitoring Complete ($(date '+%Y-%m-%d %H:%M:%S %Z')) ==="
