# TOOLS.md — Postmortem Agent

## Data sources (read-only)

### Pre-event state
- `data/snapshots/{date}/rankings.csv` — rank, tier, catalyst_days, is_hard, family
- `data/snapshots/{date}/metadata.json` — ruleset_id, engine_version
- `artifacts/live_shadow/positions/{date}.json` — shadow portfolio membership
- `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv` — trade plan membership
- `artifacts/readiness/scorecard_{date}.json` — readiness verdict

### Post-event outcome
- `production_data/price_history.csv` — daily close prices (for return computation)
- `data/research/event_move_table.json` — historical abs_gap if available

### Reference
- `artifacts/postmortem/` — existing postmortems (avoid duplicates)
- `data/snapshots/` — directory listing to find pre-event snapshot date

## Output location

```
artifacts/postmortem/
  {date}/
    {ticker}.json    — structured postmortem record
    {ticker}.md      — human-readable summary
```

## Postmortem JSON schema

```json
{
  "schema": "postmortem.v1",
  "ticker": "CELC",
  "event_date": "2026-04-01",
  "captured_at": "2026-04-04T...",
  "pre_event": {
    "snapshot_date": "2026-03-31",
    "actionable_rank": 7,
    "tier_dev": "A",
    "catalyst_days": 1,
    "catalyst_family": "CLINICAL",
    "is_hard_catalyst": true,
    "in_shadow": true,
    "in_trade_plan": false,
    "readiness_verdict": "REVIEW",
    "ruleset_id": "9f1f4587"
  },
  "outcome": {
    "return_t1": 0.12,
    "return_t3": 0.08,
    "return_t5": 0.05,
    "excess_vs_xbi_t1": 0.11,
    "excess_vs_xbi_t3": 0.07,
    "abs_gap": 0.15
  }
}
```

## Environment

- WSL2 Ubuntu, Python 3.12
- Schedule: daily after market close, only for newly resolved catalysts
