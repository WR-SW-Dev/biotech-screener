# TOOLS.md — Catalyst Delta Agent

## Data sources (read-only)

### Event artifacts (per snapshot)
- `data/snapshots/{date}/catalyst_source_mix.json` — source counts by type
- `data/snapshots/{date}/catalyst_shadow_metrics.json` — shadow catalyst metrics
- `data/snapshots/{date}/rankings.csv` — ticker, tier, rank, catalyst_days, is_hard, catalyst_family, catalyst_event_type, catalyst_source
- `data/snapshots/{date}/phase2_run_delta_details.json` — entrants, exits, top catalysts

### Cache state
- `cache/ctgov/trial_records_{date}.json` — PIT-filtered CTGov cache
- `data/caches/sec_8k/` — SEC 8-K event cache
- `production_data/pdufa_dates.json` — manual PDUFA calendar (15 entries)

### Model context
- `artifacts/live_shadow/positions/{date}.json` — shadow portfolio
- `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv` — trade plan
- `artifacts/catalyst_delta/{prior_date}_delta.json` — prior delta (for carried-over detection)

## Output location

```
artifacts/catalyst_delta/
  {date}_delta.json    — structured delta with codes
  {date}_delta.md      — human-readable summary
```

## Production builder

The core delta logic is now implemented in `tools/build_catalyst_delta.py`:

```bash
python tools/build_catalyst_delta.py --as-of-date 2026-03-27
```

This runs automatically in the daily production pipeline (step 5i.6).
The agent's role is to interpret the builder's output, not duplicate its logic.

## Environment

- WSL2 Ubuntu, Python 3.12
- All reads are file-based — no API calls needed
- Schedule: once daily after production pipeline completes (step 5i.6)
