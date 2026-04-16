# HEARTBEAT.md — Price Action Watch Agent

## Snapshot guard

If no snapshot exists for today at `data/snapshots/YYYY-MM-DD/`, report SNAPSHOT_MISSING and stop.

## Checklist

1. Load today's `rankings.csv` and `production_data/price_history.csv`
2. For the top-30 ranked names, check for big moves (>5% absolute daily return)
3. Flag any name with RVOL > 3x (volume vs 20-day avg) if available in market_data.json
4. Check if any top-30 name hit a new 90-day low
5. Summarize: count of big movers, direction, any overlap with catalyst dates
6. Write alert digest to `agents/price_action_watch/memory/` if any alerts found
