# HEARTBEAT.md — CTgov Poller Agent

## Checklist

1. Check if today's ctgov cache exists: `cache/ctgov/trial_records_YYYY-MM-DD.json`
2. Compare record count against yesterday's cache — flag if delta > 500 or < -100
3. Check `cache/cache_refresh_YYYY-MM-DD.json` for refresh diagnostics
4. If cache is missing for today, report STALE with last available date
5. Write summary to `agents/ctgov_poller/memory/` if any material changes detected
