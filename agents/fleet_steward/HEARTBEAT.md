# HEARTBEAT.md — Fleet Steward Agent

On heartbeat, produce a compact fleet health receipt.

## Checklist

### 0. Fleet discovery
- List all agents: `ls -d agents/*/SOUL.md | sed 's|agents/||;s|/SOUL.md||'`
- Compare to last known list in `memory/`
- If new agents found → report as NEW in receipt
- If agents removed → report as REMOVED

### 1. Production pipeline
- Check `data/snapshots/{today}/` exists and has rankings.csv
- Check `artifacts/ops_digest/{today}_digest.json` exists
- Read the digest attention level

### 2. Agent outputs (check freshness)

| Agent | Artifact to check | Stale if |
|-------|-------------------|----------|
| ops | `artifacts/ops_digest/{today}_digest.json` | missing after 17:30 |
| ic_health_monitor | `artifacts/ic_dashboard/{today}_dashboard.json` | missing after 17:45 |
| earnings_calendar_sync | `artifacts/earnings_sync/biotech_earnings.ics` | older than 2 days |
| post_promotion_monitor | `artifacts/post_promotion_monitor/{today}_monitor.json` | missing after 17:00 |
| asymmetry_score | `output/ranker_eval/asymmetry_score_{today}.json` | missing after 17:00 |
| crt_resolution_watcher | `output/catalyst_ev/crt_options_join.json` | older than 3 days |

### 3. Repeated issues
- Read last 3 days of `agents/fleet_steward/memory/` notes
- If the same issue appears 3+ times → escalate

### 4. Shadow/accumulation gates
- Post-promotion monitor: day N of 30
- Asymmetry score: N dates accumulated (need 20+ for backtest)
- total_volume_z: N snapshot_native observations (need 50+ for validation)

## Output format

```
FLEET RECEIPT — {date}
Pipeline: {OK/STALE/MISSING}
Digest: {attention level}

Agent Health:
  {agent}: {OK/STALE/ALARM} — {one-line detail}

Accumulation:
  Post-promo: day {N}/30
  Asymmetry: {N} dates
  volume_z: {N} snapshot_native obs

Issues (carried):
  {issue if any}

Verdict: {ALL_CLEAR / REVIEW / ACTION_REQUIRED}
```

## Status codes

- `ALL_CLEAR` — all agents fresh, no alarms, no carried issues
- `REVIEW` — at least one agent stale or at WARN
- `ACTION_REQUIRED` — pipeline missing, agent alarm, or 3+ day carried issue
