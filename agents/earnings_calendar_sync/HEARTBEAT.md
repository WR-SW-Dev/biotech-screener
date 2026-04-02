# HEARTBEAT.md — Earnings Calendar Sync Agent

On heartbeat, run this checklist. If everything is CLEAR, reply HEARTBEAT_OK.

## Checklist

1. **ICS exists**: `artifacts/earnings_sync/biotech_earnings.ics` is present and >0 bytes
2. **ICS is fresh**: modified within the last 2 calendar days (weekday-aware)
3. **Event count**: ICS contains >0 VEVENT entries

## Schedule

- **Daily** on weekdays: fetch + regenerate ICS with 60-day lookahead

## Status codes

- `HEALTHY` — ICS exists, fresh, has events
- `STALE` — ICS exists but older than 2 trading days
- `MISSING` — ICS file not found
- `EMPTY` — ICS exists but contains 0 events
