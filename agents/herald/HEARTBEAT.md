# HEARTBEAT.md — Herald Agent

## Schedule

- **14:35 ET** weekdays: fetch all tickers + classify
- **08:00 ET** weekdays: overnight digest
- **15:00 ET** weekdays: midday digest
- **18:00 ET** weekdays: evening digest

## Checklist

- [ ] Fetch all universe tickers (341)
- [ ] Report source health (failures, stale sources)
- [ ] Run classifier on new releases
- [ ] Update fetch_state.json
- [ ] Send scheduled digests

## Health checks

1. **Herald data exists**: `data/press_releases/` has recent .jsonl files
   - If latest release file is >2 days old: STALE_SOURCE
2. **Today's digests sent**: check `artifacts/news_digest/` for today's files
   - If past 09:00 and no 08:00 digest: MISSED_MORNING
3. **Delivery log**: check for send failures

## Status codes

- `HEALTHY` -- fetches succeeding, digests sent on schedule
- `STALE_SOURCE` -- Herald data older than 2 days
- `MISSED_DIGEST` -- scheduled digest not sent
- `SEND_FAILURE` -- email delivery failed
- `FETCH_DEGRADED` -- >10% of tickers failing to fetch
