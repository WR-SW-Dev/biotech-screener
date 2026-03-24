#!/usr/bin/env bash
# =============================================================================
# April Validation Harness — run after BIIB/CELC/PVLA/TBPH outcomes
# =============================================================================
#
# Target events:
#   CELC, PVLA, TBPH  ~April 1  (SEC 8-K clinical data readouts)
#   BIIB               ~April 3  (FDA PDUFA)
#
# Prerequisites:
#   - Daily screen runs have accumulated snapshot_native hard-catalyst data
#   - price_history.csv is current through at least April 4
#   - event_move_table.json has been refreshed (auto-updates on screen runs)
#
# Usage:
#   bash scripts/research/run_april_validation.sh [--dry-run]
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")/../.."

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "[DRY RUN] Commands will be printed but not executed."
fi

TIMESTAMP=$(date +%Y%m%dT%H%M%S)
OUTPUT_ROOT="output/april_validation_${TIMESTAMP}"

echo "=== April Validation Harness ==="
echo "Output: ${OUTPUT_ROOT}"
echo ""

# --- Preflight checks ---
echo "--- Preflight ---"

# Check price history freshness
LATEST_PRICE_DATE=$(tail -1 production_data/price_history.csv 2>/dev/null | cut -d, -f2)
if [[ "${LATEST_PRICE_DATE}" == "date" ]]; then
    LATEST_PRICE_DATE="(only header row — file may be empty)"
fi
echo "Latest price date: ${LATEST_PRICE_DATE:-MISSING}"

# Check target tickers in latest snapshot
LATEST_SNAP=$(ls -d data/snapshots/2026-0[34]-[0-9][0-9] 2>/dev/null | sort | tail -1)
echo "Latest snapshot: ${LATEST_SNAP:-MISSING}"

if [[ -n "${LATEST_SNAP}" && -f "${LATEST_SNAP}/rankings.csv" ]]; then
    echo "Target tickers in latest snapshot:"
    head -1 "${LATEST_SNAP}/rankings.csv" | tr ',' '\n' | grep -n 'ticker\|catalyst_days\|is_hard' || true
    for T in BIIB CELC PVLA TBPH; do
        ROW=$(grep "^${T}," "${LATEST_SNAP}/rankings.csv" 2>/dev/null || grep ",${T}," "${LATEST_SNAP}/rankings.csv" 2>/dev/null || echo "NOT FOUND")
        echo "  ${T}: ${ROW:0:120}"
    done
fi

# Check required research data
for F in data/research/historical_iv_features.csv data/research/event_move_table.json; do
    if [[ -f "$F" ]]; then
        echo "  OK: $F ($(wc -l < "$F") lines)"
    else
        echo "  MISSING: $F — cannot proceed"
        exit 1
    fi
done

echo ""

# --- Step 1: Options signal pack (snapshot_native hard-catalyst) ---
echo "=== Step 1: Options Signal Pack (snapshot_native) ==="
CMD1="python3 scripts/research/eval_options_signal_pack.py \
  --snapshots-dir data/snapshots \
  --price-csv production_data/price_history.csv \
  --iv-features data/research/historical_iv_features.csv \
  --event-move-table data/research/event_move_table.json \
  --event-subset hard --hard-filter-mode snapshot_native \
  --max-catalyst-days 90 --horizons 5,21 --min-obs 10 --walkforward \
  --output-dir ${OUTPUT_ROOT}/options_signal_pack"

if $DRY_RUN; then
    echo "$CMD1"
else
    eval "$CMD1"
fi
echo ""

# --- Step 2: Surface alpha pack (snapshot_native) ---
echo "=== Step 2: Surface Alpha Pack (snapshot_native) ==="
CMD2="python3 scripts/research/eval_surface_alpha_pack.py \
  --snapshots-dir data/snapshots \
  --price-csv production_data/price_history.csv \
  --iv-features data/research/historical_iv_features.csv \
  --event-move-table data/research/event_move_table.json \
  --event-subset hard --hard-filter-mode snapshot_native \
  --max-catalyst-days 90 \
  --signals actual_implied_move_pctile,atm_iv_change_5d \
  --horizons 5,21 --min-obs 10 --walkforward monthly \
  --output-dir ${OUTPUT_ROOT}/surface_alpha_pack"

if $DRY_RUN; then
    echo "$CMD2"
else
    eval "$CMD2"
fi
echo ""

# --- Step 3: IV crush recalibration ---
echo "=== Step 3: IV Crush Calibration (snapshot_native) ==="
CMD3="python3 scripts/research/measure_iv_crush.py \
  --iv-features data/research/historical_iv_features.csv \
  --snapshots-dir data/snapshots \
  --price-csv production_data/price_history.csv \
  --event-subset hard --hard-filter-mode snapshot_native \
  --event-window 60 --pre-offsets 3,1 --post-offsets 1,3,5 --min-obs 5 \
  --output-dir ${OUTPUT_ROOT}/iv_crush"

if $DRY_RUN; then
    echo "$CMD3"
else
    eval "$CMD3"
fi
echo ""

# --- Summary ---
echo "=== Validation Complete ==="
echo "Results in: ${OUTPUT_ROOT}/"
echo ""
echo "Decision criteria:"
echo "  Step 1: total_volume_z IC must hold above 0.10"
echo "  Step 2: actual_implied_move_pctile IC must be positive in both walk-forward halves"
echo "  Step 3: REGULATORY crush T+3 must be < 1.0 (confirms post-event IV decay)"
echo ""
echo "If all three pass, proceed to promotion template:"
echo "  - w=0.05 in secondary-regulatory 31-90d"
echo "  - Sharpe >= 0.1"
echo "  - Top-60 overlap >= 0.90"
