# HEARTBEAT.md — Event Analyst Agent

## Message routing

- **`HEARTBEAT`** — quick health check only (see checklist below). No memory write.
- **`DAILY`** — run the full daily workflow (AGENTS.md daily sequence), then write
  a daily note to `memory/YYYY-MM-DD.md`. This is the production cron message.

## Health checks

1. **Postmortem data exists**: `artifacts/postmortem/` has at least one dated subdirectory
2. **Builder ran**: `artifacts/event_analyst/{date}_summary.json` exists for today
3. **Freshness**: summary is from the current week

## Status codes

- `HEALTHY` — postmortems exist, summary current
- `NO_DATA` — no postmortem records yet (expected until April catalysts resolve)
- `STALE` — summary is >5 trading days old
- `BUILDER_FAILED` — postmortems exist but summary missing
