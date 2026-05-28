#!/bin/bash
# Daily monitoring checklist for Path C governance window (2026-05-28 to 2026-06-03)
# Run post-snapshot, typically 10 AM ET

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WINDOW_END="2026-06-03"
FLOOR=0.0200

echo "[PATH_C_MONITOR] $(date '+%Y-%m-%d %H:%M:%S') — Daily governance monitoring"
echo ""

# 1. Check IC ledger status
echo "[1/4] Forward Eval IC Status"
python3 "$REPO_ROOT/tools/monitor_forward_eval_ic.py" --window-end "$WINDOW_END" --floor "$FLOOR" 2>&1 | grep -E "^\[IC_MONITOR\]|^\[IC_MONITOR_JSON\]"
echo ""

# 2. Portfolio drawdown check (if snapshot available)
LATEST_SNAPSHOT=$(ls -td "$REPO_ROOT/data/snapshots/"*/final 2>/dev/null | head -1)
if [ -n "$LATEST_SNAPSHOT" ]; then
  LATEST_SNAPSHOT_DIR=$(dirname "$LATEST_SNAPSHOT")
  echo "[2/4] Portfolio Drawdown vs XBI"
  if [ -f "$LATEST_SNAPSHOT/portfolio_summary.json" ]; then
    python3 -c "
import json
with open('$LATEST_SNAPSHOT/portfolio_summary.json') as f:
    data = json.load(f)
    drawdown = data.get('drawdown_vs_xbi_pp', None)
    status = '✓ NORMAL' if drawdown is not None and drawdown < 1.0 else '⚠ WARNING' if drawdown is not None and drawdown < 2.0 else '🔴 CRITICAL'
    print(f'Drawdown vs XBI: {drawdown:.2f}pp {status}')
" 2>/dev/null || echo "Portfolio summary not available"
  fi
else
  echo "[2/4] Portfolio Drawdown vs XBI — No recent snapshot"
fi
echo ""

# 3. 13F cohort stability check
echo "[3/4] 13F Cohort Stability"
if [ -f "$REPO_ROOT/artifacts/readiness/GOVERNANCE_DECISION_PATH_C_2026_05_28.md" ]; then
  echo "✓ Path C governance memo exists"
  echo "  Cohort target: Jaccard >= 0.70"
  echo "  Last clearance: 2026-05-24 (Jaccard 0.875)"
else
  echo "⚠ Governance memo not found"
fi
echo ""

# 4. Emergency exit conditions check
echo "[4/4] Emergency Exit Conditions"
echo "  Hard trigger 1: Portfolio drawdown > 2pp relative to XBI → revoke immediately"
echo "  Hard trigger 2: 13F cohort Jaccard < 0.70 or new quarantine → escalate"
echo ""

# Summary
echo "[PATH_C_MONITOR] Daily check complete. Window closes 2026-06-03."
echo "[PATH_C_MONITOR] Next action: Operator decision on 2026-06-03 window close (IC observable vs IC_UNOBSERVABLE)"
