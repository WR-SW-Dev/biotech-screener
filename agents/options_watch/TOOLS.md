# TOOLS.md — Options Watch Agent

## Data sources (read-only)

### Rankings & model context
- `data/snapshots/{date}/rankings.csv` — tier, rank, catalyst_days, is_hard
- `data/snapshots/{date}/review_queue.csv` — hard-catalyst review queue
- `artifacts/live_shadow/positions/{date}.json` — shadow portfolio
- `artifacts/live_shadow/trade_plan/{date}/trade_plan.csv` — trade plan

### Options surface
- `data/snapshots/{date}/chains/{ticker}/` — per-ticker options chain snapshots
- `data/research/historical_iv_features.csv` — 254K rows, historical IV/volume
- `data/research/live_options_timeseries.csv` — live options time series

### Reference
- `production_data/decision_rulesets/manifest.json` — shadow candidate IDs
- `artifacts/options_watch/{prior_date}_watch.json` — prior watch (for deltas)

## Output location

```
artifacts/options_watch/
  {date}_watch.json    — structured flags with model context
  {date}_watch.md      — human-readable summary (one line per flag)
```

## Environment

- WSL2 Ubuntu, Python 3.12
- All reads are file-based
- Schedule: once daily after production packet completes
