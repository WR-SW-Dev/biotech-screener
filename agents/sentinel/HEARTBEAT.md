# HEARTBEAT.md — Ruleset Sentinel Agent

**Retired 2026-07-17.** This checklist described steps for a live LLM agent
(`run_agent_direct.py --agent sentinel`), but that runner has no real
tool-execution capability — it was fabricating plausible-looking check
transcripts rather than actually performing them. The real, deterministic
version of this checklist is `check_sentinel()` in
`tools/agent_heartbeat_checks.py`, which runs daily via the registry-mode
heartbeat cron and writes real results to `agents/sentinel/memory/YYYY-MM-DD.md`
(via `write_agent_daily_memory()`). Invoke that rather than re-running this
agent through `run_agent_direct.py` for routine checks. The checklist below is
retained for historical/design context only.

## Checklist (historical — see retirement note above)

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
