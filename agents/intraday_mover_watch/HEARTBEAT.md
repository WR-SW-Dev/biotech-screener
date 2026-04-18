# HEARTBEAT.md — Intraday Mover Watch Agent

## Cadence (target — not yet wired)

OpenClaw cron registration is **deferred until credentials + tier are confirmed**. Target schedule (US Eastern):

| Window | Cron (UTC) | Description |
|---|---|---|
| Open | `35,50 9 * * 1-5` | 09:35 and 09:50 ET around the open |
| Core | `5,20,35,50 10-15 * * 1-5` | every 15 min, 10:00–15:50 ET |
| Close digest | `15 16 * * 1-5` | 16:15 ET end-of-day digest |

Default poll cadence is 15 minutes; configurable via `BIOTECH_INTRADAY_POLL_MINUTES`.

## Liveness checks

The agent is healthy when, on the most recent market weekday:

- At least one `*_poll.json` artifact exists with `status=OK` and `provider=live`
- Watchlist size is within `[1, WATCHLIST_MAX]`
- XBI quote is present in at least 90% of polls (missing XBI degrades to abs-only classification)
- `{date}_digest.json` exists by 16:30 ET

Degraded states (expected, not failures):

- `status=NO_DATA` + `provider=no_credentials` — no key configured; resolve by setting `APCA_API_KEY_ID` + `APCA_API_SECRET_KEY`
- `status=NO_DATA` + `provider=dry_run` — Polygon/Massive key present but `BIOTECH_INTRADAY_REALTIME_TIER=1` not set (only relevant if the optional paid-upgrade path is selected)
- `status=NO_DATA` + `provider=dev_fallback` — yfinance fallback active; local dev only, not acceptable for production

## Failure handling

- Quote provider error: single artifact with `status=NO_DATA`, one WARN per trading day, no retries beyond the two built into the client.
- Herald artifacts missing: mover alerts still emit; `news_status=UNKNOWN_SOURCE_STATE`.
- Grok artifacts missing: no enrichment; core watcher never fails on this.
- SMTP unavailable: artifacts written; email send skipped with a single WARN line.
- Market closed: polls produce `status=OK` with `market_status=closed` and `n_triggered=0`; digest still runs at 16:15 ET.

## OpenClaw delivery contract

One-line verdict, 2–5 bullets, one artifact pointer. Verdict classes: `OK`, `WARN`, `ACTION REQUIRED`, `NO DATA`, `FAIL`.
