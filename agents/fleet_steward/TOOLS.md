# TOOLS.md — Fleet Steward Agent

## Check today's pipeline output

```bash
ls data/snapshots/$(date +%Y-%m-%d)/rankings.csv 2>/dev/null && echo "OK" || echo "MISSING"
```

## Check agent artifact freshness

```bash
# All key artifacts at once
for f in \
  "artifacts/ops_digest/$(date +%Y-%m-%d)_digest.json" \
  "artifacts/ic_dashboard/$(date +%Y-%m-%d)_dashboard.json" \
  "artifacts/post_promotion_monitor/$(date +%Y-%m-%d)_monitor.json" \
  "output/ranker_eval/asymmetry_score_$(date +%Y-%m-%d).json" \
  "artifacts/earnings_sync/biotech_earnings.ics"; do
  if [ -f "$f" ]; then
    echo "OK  $f"
  else
    echo "MISS $f"
  fi
done
```

## Read ops digest attention

```bash
python3 -c "import json; d=json.load(open('artifacts/ops_digest/$(date +%Y-%m-%d)_digest.json')); print(d.get('attention','?'))"
```

## Read IC dashboard attention

```bash
python3 -c "import json; d=json.load(open('artifacts/ic_dashboard/$(date +%Y-%m-%d)_dashboard.json')); print(d.get('attention','?'))"
```

## Check post-promotion monitor day

```bash
python3 -c "import json; d=json.load(open('artifacts/post_promotion_monitor/$(date +%Y-%m-%d)_monitor.json')); print(f'Day {d[\"days_since_promotion\"]}/30, alerts={len(d.get(\"alerts\",[]))}')"
```

## Count CRT resolutions

```bash
find data/snapshots/resolutions -name "*.json" -not -name "calibration*" -not -name "manual*" -not -name "watchlist*" | wc -l
```

## Count snapshot_native hard events (for volume_z gate)

```bash
python3 -c "
import csv, os
n=0
for d in sorted(os.listdir('data/snapshots')):
    p=f'data/snapshots/{d}/rankings.csv'
    if not os.path.exists(p): continue
    with open(p) as f:
        for r in csv.DictReader(f):
            if r.get('is_hard_catalyst','0')=='1': n+=1
print(f'{n} snapshot_native hard events')
"
```

## Check gateway health

```bash
openclaw gateway status 2>&1 | head -5
```

## Discover agents (dynamic — picks up new agents automatically)

```bash
# Filesystem source of truth
for d in agents/*/SOUL.md; do
  agent=$(echo "$d" | sed 's|agents/||;s|/SOUL.md||')
  nick=$(grep -m1 "Name:" "agents/$agent/IDENTITY.md" 2>/dev/null | sed 's/.*: *//')
  echo "$agent ($nick)"
done
```

```bash
# OpenClaw registry (may lag filesystem)
openclaw agents list 2>&1 | grep "^-"
```

## Cadence

- Daily at 18:15 ET (after all other agents)
- Optional: manual heartbeat anytime for spot-check
