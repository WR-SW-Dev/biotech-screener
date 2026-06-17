# Bulk Fleet Indexing — Parallel Subagent Recipe
First used: 2026-05-04. Use when scope table, registry, or session history are stale
and need a full refresh in one shot.

## When to use
- First triage of a session after a long gap (skill tables may be days/phases behind)
- After adding/deprecating agents (SOUL.md sweep needed)
- After registry edits (path mismatch check needed)
- Want to surface failure patterns from past sessions not yet in skills

## 3-subagent parallel delegation pattern

```python
mcp_delegate_task(tasks=[
    {
        "goal": "Read every SOUL.md in agents/ and extract: agent_id | scope_summary | work_trigger | key_prohibitions. Flag agents with ambiguous scope or missing prohibitions.",
        "toolsets": ["terminal", "file"],
        "context": "Repo at /mnt/c/Projects/biotech_screener/biotech-screener. Read-only."
    },
    {
        "goal": "Search past Hermes sessions for confirmed failure patterns NOT yet in the three debugger skills (cron-scheduler-debug, agent-scope-audit, session-routing-debug). Return: pattern_name | session_summary | diagnostic_chain | resolution.",
        "toolsets": ["session_search"]
    },
    {
        "goal": "Read AGENT_REGISTRY.json and produce: full reference table (agent_id | cadence | artifact_paths | memory_path | status) + path mismatch list (declared paths that don't exist on disk).",
        "toolsets": ["terminal", "file"],
        "context": "Repo at /mnt/c/Projects/biotech_screener/biotech-screener. Read-only."
    }
])
```

## Output routing
- SOUL.md sweep output → update `references/agent-scope-table.md` in this skill
- Session search output → new patterns go into the appropriate debugger skill
- Registry audit output → update `references/agent-registry-reference.md` in this skill

## Confirmed results (2026-05-04 run)
- 30 SOUL.md files read, 10 scope ambiguity gaps identified
- 10 new confirmed failure patterns extracted from session history
- 30-agent registry table built, 7 path mismatches found (4 hard, 3 behavioral)
- Total subagent runtime: ~9 minutes parallel

## Cadence
Run when scope/registry reference files are >2 weeks old, or after any batch of
agent additions/retirements.
