# TOOLS.md — Production QA

## 1. Snapshot completeness check

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
TODAY=$(date +%Y-%m-%d)
SNAP="data/snapshots/${TODAY}"
echo "=== Snapshot completeness ==="
ls -la "$SNAP/rankings.csv" "$SNAP/metadata.json" "$SNAP/run_manifest.json" 2>&1
ls "$SNAP/"*.json 2>/dev/null | wc -l
# Expected sidecars
for f in ees_v3_overlay.json conditional_model_overlay.json execution_capacity_overlay.json runway_severity_overlay.json; do
  [ -f "$SNAP/$f" ] && echo "OK: $f" || echo "MISSING: $f"
done
```

## 2. Production log scan

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
TODAY=$(date +%Y-%m-%d)
LOG="logs/daily_production_${TODAY}.log"
echo "=== Error scan ==="
grep -c "ERROR\|Traceback\|FAIL" "$LOG" 2>/dev/null || echo "No log found"
grep -i "ERROR\|Traceback" "$LOG" 2>/dev/null | tail -10
```

## 3. Lint gate (flake8)

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
flake8 run_screen.py event_ev/ decision_engine.py ranker_v2_pairwise.py --count --select=E,F --max-line-length=150 2>&1 | tail -10
```

## 4. Schema check (rankings.csv columns)

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
TODAY=$(date +%Y-%m-%d)
python3 -c "
import csv
with open('data/snapshots/${TODAY}/rankings.csv') as f:
    cols = csv.DictReader(f).fieldnames
required = ['ees_v3_score','ees_v3_gate','conditional_misprice_z','runway_severity_score',
            'financing_truth_gate','severity_bucket','execution_capacity_score','actionable_rank']
missing = [c for c in required if c not in cols]
print(f'Columns: {len(cols)} total')
if missing:
    print(f'MISSING: {missing}')
else:
    print('All required columns present')
"
```

## 5. EES v3 distribution health

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
TODAY=$(date +%Y-%m-%d)
python3 -c "
import csv, json
with open('data/snapshots/${TODAY}/rankings.csv') as f:
    rows = list(csv.DictReader(f))
mp = [float(r['conditional_misprice_score']) for r in rows if r.get('conditional_misprice_score') not in ('','None')]
n_ceil = sum(1 for v in mp if abs(v) >= 0.99)
n_uniq = len(set(round(v, 4) for v in mp))
print(f'misprice: n={len(mp)} unique={n_uniq} ceiling={n_ceil} ({n_ceil/len(mp)*100:.0f}%)')
if n_ceil > len(mp) * 0.20:
    print('WARN: >20% at ceiling — check priced_move_pct units')
else:
    print('OK: distribution healthy')
"
```

## 6. Runway severity sanity

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
TODAY=$(date +%Y-%m-%d)
python3 -c "
import csv
from collections import Counter
with open('data/snapshots/${TODAY}/rankings.csv') as f:
    rows = list(csv.DictReader(f))
buckets = Counter(r.get('severity_bucket','') for r in rows)
print(f'Runway severity: {dict(sorted(buckets.items()))}')
if len(buckets) <= 1:
    print('WARN: degenerate distribution (single bucket)')
else:
    print('OK: multiple severity buckets')
"
```

## 7. Broken reference check

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
echo "=== Agent SOUL.md path check ==="
for agent_dir in agents/*/; do
  if [ -f "${agent_dir}SOUL.md" ]; then
    grep -oE '`[^`]+\.(py|json|csv|sh)`' "${agent_dir}SOUL.md" | tr -d '`' | while read path; do
      [ -e "$path" ] || echo "BROKEN: ${agent_dir}SOUL.md → $path"
    done
  fi
done
```

## 8. Artifact freshness

| Artifact | Expected Path | Check |
|----------|--------------|-------|
| Ops digest | `artifacts/ops_digest/YYYY-MM-DD_digest.md` | Today's date |
| Readiness scorecard | `artifacts/readiness/scorecard_YYYY-MM-DD.md` | Today's date |
| Run manifest | `data/snapshots/YYYY-MM-DD/run_manifest.json` | Today's date |
| EES v3 sidecar | `data/snapshots/YYYY-MM-DD/ees_v3_overlay.json` | Today's date |

## 9. Gate failures from manifest

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
TODAY=$(date +%Y-%m-%d)
python3 -c "
import json
with open('data/snapshots/${TODAY}/run_manifest.json') as f:
    m = json.load(f)
gates = m.get('gates', [])
fails = [g for g in gates if g.get('status') == 'FAIL']
warns = [g for g in gates if g.get('status') == 'WARN']
print(f'Gates: {len(gates)} total, {len(fails)} FAIL, {len(warns)} WARN')
for g in fails:
    print(f'  FAIL: {g[\"name\"]} — {g.get(\"detail\",\"\")}')
for g in warns[:5]:
    print(f'  WARN: {g[\"name\"]} — {g.get(\"detail\",\"\")}')
"
```
