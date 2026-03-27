# TOOLS.md — Event Analyst Agent

## Production builder

```bash
python tools/build_event_analyst.py --as-of-date 2026-04-15
python tools/build_event_analyst.py --as-of-date 2026-04-15 --lookback 90
```

## Data sources (read-only)

### Primary
- `artifacts/postmortem/{date}/{ticker}.json` — structured postmortem records (schema: postmortem.v1)

### Context (for enrichment, not primary analysis)
- `data/snapshots/{date}/metadata.json` — ruleset provenance
- `artifacts/live_shadow/positions/{date}.json` — shadow membership
- `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv` — trade plan membership
- `artifacts/readiness/scorecard_{date}.json` — readiness verdict

## Output

```
artifacts/event_analyst/
  {date}_summary.json     — structured aggregate (schema: event_analyst.v1)
  {date}_summary.md       — human-readable summary
```

## Slice dimensions

| Dimension | Field | Question |
|-----------|-------|----------|
| catalyst_family | pre_event.catalyst_family | Which families produce the best outcomes? |
| tier_dev | pre_event.tier_dev | Does tier assignment predict resolution quality? |
| in_shadow | pre_event.in_shadow | Does shadow membership correlate with better returns? |
| in_trade_plan | pre_event.in_trade_plan | Do trade-plan names outperform? |
| is_hard_catalyst | pre_event.is_hard_catalyst | Do hard catalysts produce cleaner signals? |

## Cadence

- **Daily**: run after postmortem agent, only when new postmortems exist
- **Weekly**: primary artifact for human review (Friday or Monday)
- Currently: NO_DATA until April catalyst resolutions produce postmortems
