#!/usr/bin/env bash
# Smoke test for the Wake Robin biotech screener.
# Run from the repo root: bash .claude/skills/run-biotech-screener/smoke.sh [DATE]
# DATE defaults to today (YYYY-MM-DD). No external network calls are made.

set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
DATE="${1:-$(date +%Y-%m-%d)}"

echo "=== Biotech Screener smoke — $DATE ==="

# 1. Input validation (dry-run)
echo ""
echo "--- 1/3  Input validation (dry-run) ---"
python3 "$REPO/run_screen.py" \
  --as-of-date "$DATE" \
  --data-dir "$REPO/production_data" \
  --dry-run 2>&1 | grep -E "Valid:|Required files|universe|financial|trial|market"

# 2. Snapshot gate summary from run_manifest.json
SNAP="$REPO/data/snapshots/$DATE/run_manifest.json"
echo ""
echo "--- 2/3  Snapshot gate summary ---"
if [ -f "$SNAP" ]; then
  python3 - "$SNAP" <<'PYEOF'
import json, sys
m = json.load(open(sys.argv[1]))
print(f"  overall_status : {m.get('overall_status','?')}")
print(f"  screen_exit_code: {m.get('screen_exit_code','?')}")
gates = m.get("gates", [])
fails  = [g for g in gates if g.get("status") == "FAIL"]
warns  = [g for g in gates if g.get("status") == "WARN"]
passes = [g for g in gates if g.get("status") == "PASS"]
print(f"  PASS={len(passes)}  WARN={len(warns)}  FAIL={len(fails)}")
for g in warns:
    print(f"    WARN  {g['name']}: {str(g.get('detail',''))[:80]}")
for g in fails:
    print(f"    FAIL  {g['name']}: {str(g.get('detail',''))[:80]}")
PYEOF
else
  echo "  No snapshot found for $DATE (not yet run or skipped)"
fi

# 3. Top-10 rankings
RANK="$REPO/data/snapshots/$DATE/rankings.csv"
echo ""
echo "--- 3/3  Top-10 rankings ---"
if [ -f "$RANK" ]; then
  python3 - "$RANK" <<'PYEOF'
import csv, sys
rows = sorted(
    [r for r in csv.DictReader(open(sys.argv[1])) if r.get("actionable_rank","").isdigit()],
    key=lambda r: int(r["actionable_rank"])
)[:10]
print(f"  {'Rank':>4}  {'Ticker':<6}  {'Sel Score':>9}  {'Final Score':>11}  {'Stage':<18}  Cat")
print("  " + "-"*62)
for r in rows:
    cat = "Y" if r.get("catalyst_in_window","0") == "1" else "-"
    print(f"  {r['actionable_rank']:>4}  {r['ticker']:<6}  {float(r['selector_score']):>9.4f}  {float(r['final_score']):>11.6f}  {r.get('development_stage','?'):<18}  {cat}")
PYEOF
else
  echo "  No rankings.csv found for $DATE"
fi

echo ""
echo "=== Done ==="
