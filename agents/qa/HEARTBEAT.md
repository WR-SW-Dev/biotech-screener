# HEARTBEAT.md — QA Agent

On heartbeat, keep this cheap.

## Checklist

1. Check whether today's snapshot exists:
   `data/snapshots/$(date +%Y-%m-%d)/`
2. If it exists, verify critical files are present:
   - `rankings.csv`
   - `metadata.json`
   - `phase2_health.json`
3. If a recent CI or local run log exists, look for:
   - contract test failures
   - output check failures
   - schema validation failures
4. If all clear, reply `HEARTBEAT_OK`

## Only surface issues

Surface only:
- CONTRACT_FAIL
- OUTPUT_MISSING
- SCHEMA_FAIL
- DATE_MISMATCH
- PIPELINE_CRASH_SUSPECTED
