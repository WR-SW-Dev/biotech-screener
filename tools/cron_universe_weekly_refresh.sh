#!/bin/bash
# Weekly universe refresh — runs Monday 08:30 ET
# Four steps:
#   1. Coverage status refresh (dry-run, --finalize-collection so pending_coverage tickers
#      are not re-downgraded to pending_data_collection)
#   2. Fetch missing data for any pending_data_collection tickers (writes universe.json +
#      trial_records.json — the only step that modifies production_data/)
#   3. XBI/IBB ETF audit → proposed_universe_actions.csv (proposals only)
#   4. Universe maintenance LLM agent (read-only monitor, writes weekly memory)

set -euo pipefail

REPO=/mnt/c/Projects/biotech_screener/biotech-screener
DATE=$(date +%Y-%m-%d)
LOG="$REPO/logs/universe_weekly_refresh.log"

ts() { date -Iseconds; }

echo "[$(ts)] universe-weekly-refresh: START date=$DATE" >> "$LOG"

# Step 1: Coverage status refresh (dry-run with --finalize-collection)
# --finalize-collection: tickers with company+market covered but no CTGov trials are
# correctly kept as pending_coverage instead of being re-downgraded to pending_data_collection
echo "[$(ts)] Step 1: refresh_eligible_biotech_universe (dry-run, finalize-collection)" >> "$LOG"
cd "$REPO"
/usr/bin/python3 tools/refresh_eligible_biotech_universe.py \
    --as-of-date "$DATE" \
    --finalize-collection >> "$LOG" 2>&1 \
  && echo "[$(ts)] Step 1: OK" >> "$LOG" \
  || echo "[$(ts)] Step 1: FAIL (non-blocking)" >> "$LOG"

# Step 2: Fetch missing market/financial/trial data for pending stubs (applies changes)
echo "[$(ts)] Step 2: fetch_pending_biotech_data (apply)" >> "$LOG"
source .env 2>/dev/null || true
/usr/bin/python3 tools/fetch_pending_biotech_data.py \
    --as-of-date "$DATE" \
    --sleep-seconds 0.5 \
    --apply >> "$LOG" 2>&1 \
  && echo "[$(ts)] Step 2: OK" >> "$LOG" \
  || echo "[$(ts)] Step 2: FAIL (non-blocking)" >> "$LOG"

# Step 3: XBI/IBB audit — proposals only, no universe.json mutation
echo "[$(ts)] Step 3: audit_universe_against_xbi_ibb" >> "$LOG"
/usr/bin/python3 tools/audit_universe_against_xbi_ibb.py \
    --fetch-current-etf-holdings >> "$LOG" 2>&1 \
  && echo "[$(ts)] Step 3: OK" >> "$LOG" \
  || echo "[$(ts)] Step 3: FAIL (non-blocking)" >> "$LOG"

# Step 4: Universe maintenance LLM agent (read-only, writes weekly memory)
echo "[$(ts)] Step 4: universe_maintenance agent" >> "$LOG"
/usr/bin/python3 tools/run_agent_direct.py \
    --agent universe_maintenance \
    --message "WEEKLY date=$DATE" \
    --write-memory >> "$LOG" 2>&1 \
  && echo "[$(ts)] Step 4: OK" >> "$LOG" \
  || echo "[$(ts)] Step 4: FAIL (non-blocking)" >> "$LOG"

echo "[$(ts)] universe-weekly-refresh: END" >> "$LOG"
