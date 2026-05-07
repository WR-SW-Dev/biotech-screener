# HEARTBEAT.md — Shadow Monitor Agent

## Message routing

- **`HEARTBEAT`** — quick health check only (see checklist below). No memory write.
- **`DAILY`** — run the full daily workflow (AGENTS.md daily sequence), then write
  a triage briefing to `memory/YYYY-MM-DD.md`. **The cron entry for this was
  retired on 2026-05-06 (P1 #6 cadence reduction)** — the deterministic build
  (`tools/build_shadow_monitor.py` invoked by `run_daily_production.py`) writes
  `artifacts/shadow_monitor/{date}_monitor.{json,md}` daily, and the Tier 2
  heartbeat check (`agent_heartbeat_checks.py:check_shadow_monitor`) supervises
  it. The LLM `DAILY` path remains supported via manual invocation
  (`tools/run_agent_direct.py --agent shadow_monitor --message DAILY
  --write-memory`) but is no longer scheduled.

## Health checks

1. **Performance data exists**: `artifacts/live_shadow/performance.csv` has rows
2. **Today's monitor ran**: `artifacts/shadow_monitor/{date}_monitor.json` exists
3. **Freshness**: monitor artifact is from today (not stale)

## Status codes

- `HEALTHY` — monitor ran, data fresh
- `NO_MONITOR` — builder didn't run or failed
- `STALE` — latest monitor is >2 trading days old
- `NO_PERF_DATA` — performance.csv missing or empty
