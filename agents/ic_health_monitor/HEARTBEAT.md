# HEARTBEAT.md — IC Health Monitor Agent

On heartbeat, run this checklist. If everything is CLEAR, reply HEARTBEAT_OK.

## Checklist

1. **Dashboard exists**: `artifacts/ic_dashboard/{today}_dashboard.json` is present
   - If missing → STALE (dashboard not generated today)
2. **Read attention level**: check the `attention` field
   - HIGH or CRITICAL → flag immediately with signal details
   - MEDIUM → note and compare to prior
   - LOW → HEARTBEAT_OK
3. **Check each signal health**:
   - Any signal at ALERT → report: which signal, current IC, how many consecutive ALERT readings
   - Any signal newly degraded (was HEALTHY, now WARN) → flag as DEGRADING
   - Load-bearing signal (`clinical_optionality_pct_dev` or `inst_delta_z`) at WARN or worse → CRITICAL
4. **Trend check**: read `history.jsonl`, compute 5-reading rolling IC for each signal
   - If rolling IC is trending negative (3+ consecutive drops) → flag as TREND_DECAY

## Status codes

- `HEALTHY` — all signals HEALTHY or WEAK, no trends degrading
- `WATCH` — at least one signal at WARN, or one trend degrading
- `ALARM` — at least one signal at ALERT, or a load-bearing signal at WARN
- `STALE` — no dashboard for today
