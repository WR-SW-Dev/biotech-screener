# HEARTBEAT.md — Shadow Monitor Agent

## Message routing

- **`HEARTBEAT`** — quick health check only (see checklist below). No memory write.
- **`DAILY`** — run the full daily workflow (AGENTS.md daily sequence), then write
  a triage briefing to `memory/YYYY-MM-DD.md`. This is the production cron message.

## Health checks

1. **Performance data exists**: `artifacts/live_shadow/performance.csv` has rows
2. **Today's monitor ran**: `artifacts/shadow_monitor/{date}_monitor.json` exists
3. **Freshness**: monitor artifact is from today (not stale)

## Status codes

- `HEALTHY` — monitor ran, data fresh
- `NO_MONITOR` — builder didn't run or failed
- `STALE` — latest monitor is >2 trading days old
- `NO_PERF_DATA` — performance.csv missing or empty
