#!/bin/bash
# Run at 16:30 ET to diagnose ev_severity_score blank issue
# Output to artifacts/audit/ for review

set -e

LOG_DIR="artifacts/audit"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
LOG_FILE="$LOG_DIR/ev_severity_diagnostics_${TIMESTAMP}.txt"

{
    echo "ev_severity_score Diagnostic Run"
    echo "=================================="
    echo "Timestamp: $TIMESTAMP"
    echo ""

    echo "Step 1: Run production_qa_check for 2026-05-15 snapshot"
    echo "---"
    python tools/production_qa_check.py --as-of-date 2026-05-15 2>&1 || true
    echo ""

    echo "Step 2: Run detailed ev_severity_score diagnostic"
    echo "---"
    python tools/diagnose_ev_severity.py --date 2026-05-15 2>&1 || true
    echo ""

    echo "Step 3: Check run_screen.py logs (if available)"
    echo "---"
    if [ -f "logs/run_screen_2026-05-15.log" ]; then
        grep -i "severity\|enrichment\|ev_sev" logs/run_screen_2026-05-15.log | tail -20
    else
        echo "No log file found at logs/run_screen_2026-05-15.log"
    fi
    echo ""

    echo "Step 4: Sample rows from snapshot"
    echo "---"
    python3 - <<'PYTHON'
import csv
from pathlib import Path

p = Path("data/snapshots/2026-05-15/rankings.csv")
if p.exists():
    rows = list(csv.DictReader(p.open()))
    if rows:
        print(f"Snapshot has {len(rows)} rows")
        print(f"\nFirst 3 rows (selected fields):")
        cols_to_show = ["ticker", "ev_severity_score", "runway_severity_score", "severity_bucket", "financing_truth_gate"]
        existing_cols = [c for c in cols_to_show if c in rows[0]]

        for i, row in enumerate(rows[:3]):
            print(f"\nRow {i}:")
            for col in existing_cols:
                val = row.get(col, "<missing>")
                print(f"  {col}: {val}")
else:
    print(f"Snapshot not found: {p}")
PYTHON

} | tee "$LOG_FILE"

echo ""
echo "Diagnostics saved to: $LOG_FILE"
echo "Next step: Review diagnostics and apply patch from docs/EV_SEVERITY_PATCH_TEMPLATES.md"
