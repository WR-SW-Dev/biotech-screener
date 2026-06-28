# Hermes Subagent Policy

Governs when and how Hermes agents may spawn subagents (fork, fresh agent,
or specialized agent types).

---

## Policy summary

| Agent type | Allowed use | Restrictions |
|---|---|---|
| Fork subagent | Research / investigation only | No implementation; no commits; no pushes |
| Fresh subagent | Read-only survey tasks | Explicit no-write/no-commit scope |
| Specialized (plan, explore) | Design and survey | No file writes |
| openclaw-monitor | Fleet health checks | Read-only; no agent restarts without operator approval |

---

## Strict prohibitions

Subagents spawned by Hermes jobs or Claude Code agents must **never**:

1. **Commit to any branch** — only the operator may commit
2. **Push to remote** — even with `ALLOW_AGENT_PUSH=1`; this requires operator confirmation
3. **Write to production paths** — ranker, selector, portfolio, snapshots, `.env`, `.github/workflows/`
4. **Launch further subagents** that themselves commit or push (no recursive delegation)
5. **Place orders** — no `place_equity_order` or similar write-trade tools

---

## Fork agent rules

Fork agents inherit full conversation context and run in background. Rules:

1. Use forks **only** for research where tool output would fill context unnecessarily
2. Fork prompt must include explicit `no-write/no-commit/no-push` constraint
3. Verify via `git log` after fork returns — check that no new commits appeared
4. If fork auto-committed: **immediately revert** and record in incident log

**Known risk:** Fork agents re-notify per child completion, creating multi-step
loops that have historically produced unauthorized commits. If a fork is used for
multi-step implementation: stop, revert, re-run as direct sequential calls instead.

---

## Scope constraint template

When spawning any read-only subagent, include this constraint in the prompt:

```
SCOPE CONSTRAINTS:
- Do not write, edit, or create any files
- Do not run git commit, git push, or git add
- Do not place any orders or call write-trade MCP tools
- Read-only investigation only
- Verify via 'git log' at end; if any new commits exist, report them immediately
```

---

## Delegation boundary

Claude Code (the operator-facing assistant) may delegate TO Hermes agents.
Hermes agents must NOT delegate BACK to Claude Code to perform implementation
steps. The authorization chain is:

```
Operator → Claude Code → [read-only investigation] → Hermes agent
                      ↗ (never this direction for implementation)
Hermes agent
```

Each step in markdown → design → script → run → commit → push → PR requires
its own explicit operator instruction. "Proceed" after one step does not
authorize the next.

---

## Subagent authorization record

Active subagents registered in `.claude/agents/`:

| File | Purpose | Write authority |
|---|---|---|
| `hermes-operator.md` | Hermes job inspection | Read-only |
| `biotech-governance-reviewer.md` | Pre-commit freeze audit | Read-only |
| `memory-steward.md` | Memory file management | Writes to `~/.claude/projects/` only |
| `hermes-source-integrity-auditor.md` | Source/mirror integrity audit | Read-only |
| `hermes-skill-sync-auditor.md` | Skill sync drift detection | Read-only |

---

## References

- Fork agent runaway incident: memory `feedback_fork_agent_runaway_2026_06_24.md`
- Subagent tool list: `.claude/agents/*.md` (tools: field)
- Permission tiers: `docs/ops/hermes_permission_tiers.md`
- Instruction hygiene: `docs/ops/hermes_instruction_hygiene.md`
