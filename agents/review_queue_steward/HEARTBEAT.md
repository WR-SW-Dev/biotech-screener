# HEARTBEAT.md — Review Queue Steward

## Snapshot guard

**FIRST**: Check if today's snapshot exists at `data/snapshots/YYYY-MM-DD/rankings.csv`.
If missing, reply `SNAPSHOT_MISSING` and STOP. Do not proceed with any further checks.

## Checklist

1. Check if today's snapshot exists with review_queue.csv
2. Count total queue entries and "must look now" entries
3. If queue exists → report size and must-look count
4. If queue is empty → `HEARTBEAT_OK`
5. If no snapshot → `NO_QUEUE`

## Report format

```
QUEUE: {total} names ({must_look} must-look, {monitor} monitor)
  no_add_until_review: {n}
  size_haircut: {n}
  monitor_only: {n}
  NEW today: {n}
  ESCALATED today: {n}
```

If must_look == 0, reply `HEARTBEAT_OK — queue is {total} names, all monitor-level`.
