# HEARTBEAT.md — Options Watch Agent

## Checklist

1. Check if today's snapshot exists with rankings.csv
2. Check if options chain data exists for at least one A-tier name
3. If both present → `HEARTBEAT_OK`

## Surface only these cases

- `NO_SNAPSHOT` — today's snapshot missing
- `NO_OPTIONS_DATA` — no chain directories in today's snapshot
- `WATCH_STALE` — latest watch file is >2 trading days old
