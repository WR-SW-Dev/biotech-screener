# HEARTBEAT.md — Shadow Watch Agent

## Health checks

1. **Performance data exists**: `artifacts/live_shadow/performance.csv` has rows
2. **Today's monitor ran**: `artifacts/shadow_monitor/{date}_monitor.json` exists
3. **Policy compare ran**: `artifacts/policy_shadow/tier_weighted/history.jsonl` is fresh
4. **Freshness**: latest artifacts are from today (not stale)

## Status codes

- `HEALTHY` -- monitor and policy compare ran, data fresh
- `NO_MONITOR` -- shadow monitor builder didn't run or failed
- `NO_POLICY` -- policy compare missing or stale
- `STALE` -- latest artifacts are >2 trading days old
- `NO_PERF_DATA` -- performance.csv missing or empty
