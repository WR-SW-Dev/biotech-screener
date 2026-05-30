# HEARTBEAT.md — Company News Ingest Agent

## Schedule

- **Daily**: 3:00 PM ET weekdays (before production run at 4:30 PM)
- **Catch-up**: on boot, check for missed days

## Checklist

- [ ] Fetch all 341 tickers
- [ ] Report source health (failures, stale sources)
- [ ] Run classifier on new releases
- [ ] Update fetch_state.json
