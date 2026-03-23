# HEARTBEAT.md — Ruleset Sentinel Agent

## Checklist

1. Check whether today's snapshot contains `drift_report.json`
2. Check whether `artifacts/ruleset_health_history.jsonl` exists
3. Check latest receipt in `artifacts/promotions/`
4. Read today's ruleset health sidecar if present
5. If status is OK/PASS and rollback is not recommended, reply `HEARTBEAT_OK`

## Surface only these cases

- `RULESET_WARN` — today's health status is WARN
- `ROLLBACK_RECOMMENDED` — consecutive WARN threshold reached
- `NO_RECEIPT` — health monitor is running without a promotion baseline
- `NO_DRIFT_REPORT` — daily production completed but drift artifact is missing

## Message format

When surfacing an issue, include:
- active ruleset id
- today's status
- consecutive WARN days
- exact rollback command if recommended
