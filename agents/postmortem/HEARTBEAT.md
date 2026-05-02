# HEARTBEAT.md — Postmortem Agent

## Snapshot guard

**FIRST**: Check if today's snapshot exists at `data/snapshots/YYYY-MM-DD/rankings.csv`.
If missing, reply `SNAPSHOT_MISSING` and STOP. Do not proceed with any further checks.

## Detection note (read before running)

`catalyst_days` resets to the *next* event the moment a date passes — so scanning
`catalyst_days <= 0` in the latest snapshot finds nothing and is **not** a valid
resolution check. Two reliable signals:

1. **Resolution records** dropped into `data/snapshots/resolutions/YYYY-MM/{TICKER}_{DATE}.json`
2. **`next_catalyst_date` advancing forward** across consecutive snapshots (the prior date is the resolved event)

The script `agents/postmortem/scripts/run_postmortem.py` implements both. Invoke it
rather than re-implementing detection in heartbeat output.

## Checklist

1. Check that today's snapshot exists with rankings.csv (else `SNAPSHOT_MISSING`)
2. Check `production_data/price_history.csv` is current through at least T-3
3. Run `python3 agents/postmortem/scripts/run_postmortem.py` and capture its output
4. Summarize: `written` count, `skipped` (T+3 pending) count, `gaps` count

## Surface only these cases

- `WROTE_N` — N new postmortems written this run
- `PRICE_DATA_GAP` — resolved names lack T+3 price data (will retry tomorrow)
- `SNAPSHOT_MISSING` — today's snapshot missing
- `HEARTBEAT_OK` — no new resolutions detected
