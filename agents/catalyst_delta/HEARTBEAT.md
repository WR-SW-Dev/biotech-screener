# HEARTBEAT.md — Catalyst Delta Agent

## Snapshot guard

**FIRST**: Check if today's snapshot exists at `data/snapshots/YYYY-MM-DD/rankings.csv`.
If missing, reply `SNAPSHOT_MISSING` and STOP. Do not proceed with any further checks.

## Checklist

1. Check if today's snapshot exists: `ls data/snapshots/$(date +%Y-%m-%d)/`
2. Check if prior delta exists: `ls artifacts/catalyst_delta/` (most recent)
3. If both present → `HEARTBEAT_OK`

## Surface only these cases

- `NO_SNAPSHOT` — today's snapshot missing (pre-production or failed run)
- `NO_PRIOR_DELTA` — no prior delta to compare against (first run)
- `DELTA_STALE` — latest delta is >2 trading days old
