#!/usr/bin/env bash
# run_total_volume_validation.sh — Full validation sequence for total_volume_z signal.
#
# Prerequisites:
#   - price_history.csv current through at least T+5 after target events
#   - Daily snapshots accumulated with is_hard_catalyst column (Mar 15+)
#
# Usage:
#   bash scripts/research/run_total_volume_validation.sh [--dry-run]
#
# Gate criteria (from April validation plan):
#   1. IC >= 0.10 on snapshot_native hard events
#   2. Walk-forward IC positive in both halves
#   3. total_volume_z top/bottom tercile + continuous both tested
#   4. Interaction with rr_25d_canonical

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

TIMESTAMP=$(date +%Y%m%dT%H%M%S)
OUT_BASE="output/total_volume_validation_${TIMESTAMP}"
PRICE_CSV="production_data/price_history.csv"
SNAPSHOTS="data/snapshots"
IV_FEATURES="data/research/historical_iv_features.csv"
EVENT_TABLE="data/research/event_move_table.json"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

# --- Preflight checks ---
echo "=== PREFLIGHT ==="

# Check price_history freshness
LATEST_PRICE_DATE=$(tail -1 "$PRICE_CSV" | cut -d',' -f1)
echo "Price history through: $LATEST_PRICE_DATE"

# Count snapshot_native hard-catalyst data points
HARD_SNAPSHOTS=$(python3 -c "
import csv, glob, sys
n = 0
for f in sorted(glob.glob('${SNAPSHOTS}/2026-*/rankings.csv')):
    if '__pre' in f: continue
    with open(f) as fh:
        reader = csv.DictReader(fh)
        if 'is_hard_catalyst' not in (reader.fieldnames or []):
            continue
        for row in reader:
            if str(row.get('is_hard_catalyst', '0')).strip() == '1':
                n += 1
print(n)
")
echo "Hard-catalyst rows (snapshot_native): $HARD_SNAPSHOTS"

if [[ "$HARD_SNAPSHOTS" -lt 50 ]]; then
    echo "WARNING: Only $HARD_SNAPSHOTS hard-catalyst rows. Signal pack needs --min-obs 10 minimum."
fi

# Check required files exist
for f in "$PRICE_CSV" "$IV_FEATURES" "$EVENT_TABLE"; do
    if [[ ! -f "$f" ]]; then
        echo "FATAL: Missing $f"
        exit 1
    fi
done

# Check T+5 coverage for target tickers
echo ""
echo "Target event resolution check:"
python3 -c "
import csv
from datetime import datetime, timedelta

targets = {
    'CELC': '2026-03-25',  # 8-K filed
    'PVLA': '2026-03-31',  # 8-K filed
    'TBPH': '2026-03-30',  # 8-K filed
}

prices = {}
with open('${PRICE_CSV}') as f:
    reader = csv.DictReader(f)
    for row in reader:
        t = row.get('ticker') or row.get('symbol')
        if t in targets:
            prices.setdefault(t, []).append(row.get('date'))

for ticker, event_date in targets.items():
    ed = datetime.strptime(event_date, '%Y-%m-%d')
    t5 = ed + timedelta(days=7)  # ~5 trading days
    ticker_dates = sorted(prices.get(ticker, []))
    latest = ticker_dates[-1] if ticker_dates else 'NONE'
    has_t5 = latest >= t5.strftime('%Y-%m-%d') if ticker_dates else False
    status = 'OK' if has_t5 else 'WAITING (need through ' + t5.strftime('%Y-%m-%d') + ')'
    print(f'  {ticker}: event={event_date}, price_through={latest}, T+5: {status}')
"

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "=== DRY RUN — would run the following steps ==="
    echo "1. Signal pack (snapshot_native, focus=total_volume_z)"
    echo "2. Surface alpha pack (snapshot_native)"
    echo "3. IV crush recalibration (snapshot_native)"
    echo "4. Verdict extraction"
    echo "Output dir: $OUT_BASE/"
    exit 0
fi

mkdir -p "$OUT_BASE"

# --- Step 1: Signal pack — total_volume_z focus ---
echo ""
echo "=== STEP 1: Options Signal Pack (snapshot_native) ==="
python3 scripts/research/eval_options_signal_pack.py \
    --snapshots-dir "$SNAPSHOTS" \
    --price-csv "$PRICE_CSV" \
    --iv-features "$IV_FEATURES" \
    --event-move-table "$EVENT_TABLE" \
    --event-subset hard \
    --hard-filter-mode snapshot_native \
    --max-catalyst-days 90 \
    --horizons 5,21 \
    --min-obs 10 \
    --walkforward \
    --focus-signal total_volume_z \
    --output-dir "$OUT_BASE/signal_pack" \
    2>&1 | tee "$OUT_BASE/signal_pack.log"

STEP1_EXIT=${PIPESTATUS[0]}
echo "Step 1 exit code: $STEP1_EXIT"

# --- Step 2: Surface alpha pack ---
echo ""
echo "=== STEP 2: Surface Alpha Pack (snapshot_native) ==="
python3 scripts/research/eval_surface_alpha_pack.py \
    --snapshots-dir "$SNAPSHOTS" \
    --price-csv "$PRICE_CSV" \
    --iv-features "$IV_FEATURES" \
    --event-move-table "$EVENT_TABLE" \
    --event-subset hard \
    --hard-filter-mode snapshot_native \
    --max-catalyst-days 90 \
    --signals actual_implied_move_pctile,atm_iv_change_5d \
    --horizons 5,21 \
    --min-obs 10 \
    --walkforward monthly \
    --output-dir "$OUT_BASE/surface_alpha" \
    2>&1 | tee "$OUT_BASE/surface_alpha.log"

STEP2_EXIT=${PIPESTATUS[0]}
echo "Step 2 exit code: $STEP2_EXIT"

# --- Step 3: IV crush recalibration ---
echo ""
echo "=== STEP 3: IV Crush Recalibration (snapshot_native) ==="
python3 scripts/research/measure_iv_crush.py \
    --iv-features "$IV_FEATURES" \
    --snapshots-dir "$SNAPSHOTS" \
    --price-csv "$PRICE_CSV" \
    --event-subset hard \
    --hard-filter-mode snapshot_native \
    --event-window 60 \
    --pre-offsets 3,1 \
    --post-offsets 1,3,5 \
    --min-obs 5 \
    --output-dir "$OUT_BASE/iv_crush" \
    2>&1 | tee "$OUT_BASE/iv_crush.log"

STEP3_EXIT=${PIPESTATUS[0]}
echo "Step 3 exit code: $STEP3_EXIT"

# --- Step 4: Extract verdict ---
echo ""
echo "=== VERDICT EXTRACTION ==="
python3 -c "
import json, glob, sys
from pathlib import Path

out = Path('${OUT_BASE}')
verdict = {'timestamp': '${TIMESTAMP}', 'steps': {}}

# Signal pack — look for total_volume_z IC
sp_files = list((out / 'signal_pack').glob('*.json'))
if sp_files:
    for f in sp_files:
        try:
            d = json.loads(f.read_text())
            verdict['steps']['signal_pack'] = {
                'file': str(f.name),
                'n_outcomes': d.get('n_outcomes') or d.get('n_obs'),
            }
            # Extract IC for total_volume_z if present
            for k, v in d.items():
                if 'total_volume' in str(k).lower() and isinstance(v, dict):
                    verdict['steps']['signal_pack']['total_volume_z'] = v
            break
        except Exception:
            continue

# Surface alpha
sa_files = list((out / 'surface_alpha').glob('*.json'))
if sa_files:
    verdict['steps']['surface_alpha'] = {'file': str(sa_files[0].name)}

# IV crush
ic_files = list((out / 'iv_crush').glob('*.json'))
if ic_files:
    verdict['steps']['iv_crush'] = {'file': str(ic_files[0].name)}

verdict['exit_codes'] = {
    'signal_pack': ${STEP1_EXIT},
    'surface_alpha': ${STEP2_EXIT},
    'iv_crush': ${STEP3_EXIT},
}
verdict['all_passed'] = all(v == 0 for v in verdict['exit_codes'].values())

(out / 'verdict.json').write_text(json.dumps(verdict, indent=2, default=str))
print(json.dumps(verdict, indent=2, default=str))
"

echo ""
echo "=== DONE ==="
echo "Results: $OUT_BASE/"
echo ""
echo "Next steps (manual):"
echo "  1. Check verdict.json for total_volume_z IC at 5d and 21d horizons"
echo "  2. IC >= 0.10 at 5d or 21d? → PASS gate 1"
echo "  3. Walk-forward IC positive both halves? → PASS gate 2"
echo "  4. If both pass: wire as bounded modifier to secondary-regulatory 31-90d, w=0.05"
echo "  5. If either fails: DEFER until BIIB PDUFA (May 24) adds more hard outcomes"
