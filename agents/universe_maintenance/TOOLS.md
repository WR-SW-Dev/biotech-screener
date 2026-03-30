# TOOLS.md — Universe Maintenance Agent

## Builder

```
python tools/build_universe_maintenance.py --as-of-date 2026-03-30
```

## Data sources (read-only)

- `production_data/universe.json` — current universe (354 tickers)
- `data/snapshots/{date}/rankings.csv` — latest rankings
- `production_data/price_history.csv` — price coverage
- `production_data/market_data.json` — market data coverage

## Output location

```
artifacts/universe_maintenance/
  {date}_report.json    — structured health report
  {date}_report.md      — human-readable summary
```
