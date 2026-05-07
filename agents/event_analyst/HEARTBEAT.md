# HEARTBEAT.md — Event Analyst Agent

## Message routing

- **`HEARTBEAT`** — quick health check only (see checklist below). No memory write.
- **`DAILY`** — run the full workflow (AGENTS.md daily sequence) and write a
  dated note to `memory/YYYY-MM-DD.md`. **Production cron now fires this only
  on Fridays at 18:55 ET (P1 #4 cadence reduction, 2026-05-06).** The message
  string is preserved as `"DAILY"` for back-compat with the agent prompt; the
  scheduling is weekly.
- Manual invocation path preserved: `tools/run_agent_direct.py --agent event_analyst`
  and `tools/build_event_analyst.py --as-of-date YYYY-MM-DD`.

## Health checks (post-2026-05-06 cadence: weekly Friday)

1. **Postmortem data exists**: `artifacts/postmortem/` has at least one dated subdirectory
2. **Builder ran**: `artifacts/event_analyst/{date}_summary.json` exists for the most
   recent Friday on or before today (was: "exists for today" under the prior daily
   cadence — no longer accurate)
3. **Freshness**: summary is from the current or prior week

## Status codes

- `HEALTHY` — postmortems exist, summary current
- `NO_DATA` — no postmortem records yet (expected until April catalysts resolve)
- `STALE` — summary is >5 trading days old
- `BUILDER_FAILED` — postmortems exist but summary missing
