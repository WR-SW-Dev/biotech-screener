# HEARTBEAT.md — Biotech News Digest Agent

On heartbeat, check digest pipeline health.

## Checklist

1. **Herald data exists**: `data/press_releases/` has recent .jsonl files
   - If latest release file is >2 days old → STALE_SOURCE
2. **Today's digests sent**: check `artifacts/news_digest/` for today's files
   - Expected: up to 3 per day (08:00, 15:00, 18:00)
   - If it's past 09:00 and no 08:00 digest → MISSED_MORNING
3. **Delivery log**: check for send failures in delivery log

## Schedule

- **08:00 ET** weekdays: overnight + pre-market digest
- **15:00 ET** weekdays: midday digest
- **18:00 ET** weekdays: end-of-day digest

## Status codes

- `HEALTHY` — digests sent on schedule, Herald data fresh
- `STALE_SOURCE` — Herald data older than 2 days
- `MISSED_DIGEST` — scheduled digest not sent
- `SEND_FAILURE` — email delivery failed
