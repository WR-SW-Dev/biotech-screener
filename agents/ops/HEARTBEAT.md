# HEARTBEAT.md — Ops Agent

**Retired 2026-07-17.** This checklist described steps for a live LLM agent
(`run_agent_direct.py --agent ops`), but that runner has no real
tool-execution capability — it was fabricating plausible-looking check
transcripts rather than actually performing them (including a false
"price_coverage=0.0%... Do not trade" claim while real price data was fresh).
The real, deterministic version of this checklist is `check_ops()` in
`tools/agent_heartbeat_checks.py`, which runs daily via the registry-mode
heartbeat cron and writes real results to `agents/ops/memory/YYYY-MM-DD.md`
(via `write_agent_daily_memory()`). Invoke that rather than re-running this
agent through `run_agent_direct.py` for routine checks. The checklist below is
retained for historical/design context only.

## Checklist (historical — see retirement note above)

On heartbeat, run this checklist. If everything is CLEAR, reply HEARTBEAT_OK.

1. Check if today's snapshot exists: `ls data/snapshots/$(date +%Y-%m-%d)/`
   - If missing and it's a weekday after 5:30 PM ET → flag as MISSED RUN
2. Read today's ops digest: `cat artifacts/ops_digest/$(date +%Y-%m-%d)_digest.md`
   - If attention != CLEAR → summarize action items
   - If the digest has a "Stability Plumbing" section with "PLUMBING SUSPECT" →
     flag as PLUMBING_INVESTIGATION and name the feature(s) that dropped coverage.
     Do NOT attribute to market regime until plumbing is ruled out.
3. Check gateway health: `openclaw gateway status`
   - If not running → flag

Only report issues. HEARTBEAT_OK means all three checks passed.
