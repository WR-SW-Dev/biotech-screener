# HEARTBEAT.md — Postmortem Agent

## Checklist

1. Check if today's snapshot exists with rankings.csv
2. Check if price_history.csv has data through at least T-3
3. Check if any names in the latest snapshot have catalyst_days <= 0
4. If no resolutions pending → `HEARTBEAT_OK`

## Surface only these cases

- `RESOLUTION_PENDING` — N names have catalyst_days <= 0 but no postmortem yet
- `PRICE_DATA_GAP` — resolved names lack sufficient post-event price data
- `NO_SNAPSHOT` — today's snapshot missing
