# HEARTBEAT.md — Production QA

## Checklist

1. Check today's snapshot exists and has rankings.csv:
   `ls data/snapshots/$(date +%Y-%m-%d)/rankings.csv`
   - If missing → `SNAPSHOT_MISSING`

2. Check run_manifest.json has no FAIL gates:
   `python3 -c "import json; m=json.load(open('data/snapshots/$(date +%Y-%m-%d)/run_manifest.json')); fails=[g for g in m.get('gates',[]) if g.get('status')=='FAIL']; print(len(fails))"`
   - If > 0 → `GATE_FAILURE`

3. Check today's production log for tracebacks:
   `grep -c 'Traceback' logs/daily_production_$(date +%Y-%m-%d).log`
   - If > 0 → `TRACEBACK_DETECTED`

4. Check EES v3 sidecar exists:
   `ls data/snapshots/$(date +%Y-%m-%d)/ees_v3_overlay.json`
   - If missing → `V3_SIDECAR_MISSING`

5. If all clear → `HEARTBEAT_OK`

## Only surface these cases

- `SNAPSHOT_MISSING` — production did not complete or was not promoted
- `GATE_FAILURE` — one or more hard gates failed in the production run
- `TRACEBACK_DETECTED` — unhandled exception in production log
- `V3_SIDECAR_MISSING` — EES v3 enrichment did not fire
- `LINT_REGRESSION` — new flake8 errors in production-critical files
