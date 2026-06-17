# OpenClaw all-agent code review notes

Use this reference when the task is broader than one agent: "review all OpenClaw agents", "agent code audit", "fleet code review", or similar.

## Session-derived review pattern

A full OpenClaw agent review should cover three layers, not just `agents/<name>/SOUL.md`:

1. **Contracts and scope**
   - `agents/AGENT_REGISTRY.json`
   - every agent's `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `HEARTBEAT.md`
   - crontab `run_agent_direct.py --agent ... --message ...` lines
   - generated reference docs if present (`docs/hermes_skills/references/agent-registry-reference.md`, `agent-scope-table.md`)

2. **Shared runtime/monitoring code**
   - `tools/run_agent_direct.py`
   - `tools/agent_heartbeat_checks.py`
   - `tools/run_post_snapshot_supervisor.py`
   - `tools/agent_supervisor_sentinel.py`
   - `agents/ops_supervisor/supervisor.py`

3. **Agent data-producing scripts**
   - scripts referenced from `TOOLS.md`
   - scripts named in heartbeat/supervisor checks
   - corresponding tests for the contract, not just existence tests

## High-value checks

### Direct LLM launcher limitations

Check whether `tools/run_agent_direct.py` is still a single SDK text call. If it calls `client.messages.create(...)` without tool definitions/tool loop/subprocess bridge, then an agent can only *narrate* commands; it cannot run the tools listed in `TOOLS.md`.

Also check whether `main()` exits nonzero on `result.status != success`. If it only prints `ERROR` and writes a log, cron treats auth/model/API failures as successful process exits.

### Registry schema vs live values

Compare `agents/AGENT_REGISTRY.json` enum values to entries actually used. If enum allows only `active|shadow|deprecated` but entries use `suppressed` or `retired`, heartbeat/accounting code may silently omit those agents unless it explicitly handles them.

### Terminal/final-layer monitors

Agents like `ops_supervisor` may be intentionally `active` and `supervised_by_orchestrator=false` because they are the last monitoring layer. Heartbeat verdict code must distinguish terminal-unsupervised from coverage gaps; otherwise the intended terminus forces RED.

### Generic AGENTS.md boilerplate in production agents

If a production agent still has generic workspace/social/heartbeat boilerplate (email/calendar/weather/social reactions, commit/push background work), and its `SOUL.md` defines a narrow data/ops boundary, flag it as prompt-scope drift. This is especially dangerous for suppressed placeholders.

### Tool docs vs executable scripts

For each `TOOLS.md` command:
- verify the script path exists;
- verify output filenames match implementation;
- verify heartbeat/supervisor checks look for the same filenames;
- verify at least contract-level tests exist for nontrivial producer scripts.

### Retry/done predicates

For supervisor/orchestrator tasks, compare comments to code: if a done predicate checks an intermediate artifact, later stages may never be retried after partial failure. Example pattern: "classification gets retried" but `_done()` returns true once dedupe exists, causing classify to skip forever.

## Suggested read-only validation

Run relevant tests serially without xdist before reporting regressions:

```bash
python3 -m pytest tests/test_openclaw_agents.py tests/test_agent_heartbeat_checks.py -q --override-ini='addopts=' -p no:xdist
```

If this fails on an inventory/classification test, report it as registry/test drift rather than assuming agent code is broken.
