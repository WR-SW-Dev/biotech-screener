# HEARTBEAT.md — CRT Resolution Watcher Agent

On heartbeat, run this checklist. If everything is CLEAR, reply HEARTBEAT_OK.

## Checklist

1. **Count resolutions**: `ls data/snapshots/resolutions/*/` and count total .json files
   - Compare to last known count in memory
   - If new files → report: ticker, date, outcome for each new resolution
2. **Join table freshness**: check `output/catalyst_ev/crt_options_join.json` modification time
   - If older than latest resolution → STALE_JOIN
   - Rebuild: `python scripts/research/build_crt_options_join.py`
3. **Event move table freshness**: check `data/research/event_move_table.json`
   - If older than latest resolution → STALE_EMT
   - Rebuild: `python scripts/research/rebuild_event_move_table.py`
4. **Hit rate check**: from the join table, compute hit rate by catalyst type
   - Report if any catalyst type has < 3 observations (confidence too low)

## Status codes

- `HEALTHY` — join table and EMT current, no new unprocessed resolutions
- `NEW_RESOLUTIONS` — new resolution(s) found, join/EMT need rebuild
- `STALE_JOIN` — join table older than latest resolution
- `STALE_EMT` — event move table older than latest resolution
