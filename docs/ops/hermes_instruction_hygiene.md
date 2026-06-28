# Hermes Instruction Hygiene

Rules for keeping `CLAUDE.md`, skills, and agent instruction files coherent
and free of stale, conflicting, or unauthorized guidance.

---

## The instruction stack (authority order)

```
1. CLAUDE.md                          — project-wide rules (highest authority)
2. .claude/agents/<name>.md           — subagent system prompts
3. docs/ops/*.md                      — ops policies (referenced by agents)
4. skills/*/SKILL.md                  — Cursor skill sources (synced to Hermes)
5. docs/hermes_skills/*.md            — Hermes runtime mirrors (generated)
6. ~/.hermes/skills/*/SKILL.md        — Hermes runtime copies
```

Higher authority always wins on conflict. No agent may override `CLAUDE.md` rules.

---

## CLAUDE.md hygiene rules

1. **Ruleset pin** — `Current: <hash>` in Active Ruleset section must match `run_screen.py` pin
2. **Freeze status** — Architecture Freeze Status block must be current; update when freeze lifts
3. **No backtest numbers** — `CLAUDE.md` must not contain backtest verdicts or quarantined output numbers (these belong in quarantine notes only)
4. **No stale agent references** — remove references to deprecated/merged agents from CLAUDE.md
5. **Changepoints** — major rule changes get a dated `## Change log` entry (one line + date)

**Forbidden in CLAUDE.md:**
- Direct model weights or scoring coefficients
- Pending spec content (use `artifacts/ops/held_spec_ledger/`)
- Environment-specific secrets or paths

---

## Skill source hygiene rules

### skills/*/SKILL.md (canonical source)

1. **Frontmatter required** — every `SKILL.md` must start with `---\nname: <mirror-stem>\n---`
2. **No live URIs** — retired endpoints (e.g. Town Correction Ledger URI) must be removed when retired
3. **No hardcoded dates** — use relative dates ("within 30 days") or parameter fields
4. **No production secrets** — API keys, passwords, tokens forbidden
5. **No ranker/selector internals** — skills must not describe frozen scoring coefficients

### Mirror hygiene (`docs/hermes_skills/*.md`)

1. Mirrors are **generated** — do not hand-edit unless the skill is `HERMES_AUTHORITATIVE`
2. Regenerate after editing source: `python3 tools/sync_hermes_skills.py`
3. Verify after sync: `python3 tools/hermes_skill_sync_audit.py --mode check`

---

## Agent instruction file hygiene (`.claude/agents/*.md`)

Each subagent file must have:

```yaml
---
name: <agent-slug>
description: <one-line description — used for agent selection>
tools: <comma-separated tool list>
model: <model-id>
---
```

Rules:
1. **Minimal tool list** — grant only the tools the agent needs; prefer `Read, Grep, Glob, Bash` for diagnostic agents
2. **Explicit scope** — first sentence of body must state what the agent does and what it does NOT do
3. **No production mutations** — diagnostic subagents must include a line: `Do not write to production paths, snapshots, ranker, selector, or portfolio.`
4. **Model pinning** — always specify model explicitly; do not rely on defaults
5. **Version comment** — add `## Last updated: YYYY-MM-DD` at end of file when making substantial changes

---

## Reference file hygiene (`skills/*/REFERENCE.md`)

Reference files are human-authored documentation, not instruction prompts. They may
contain richer prose. Same rules as SKILL.md apply for frontmatter and forbidden content.

---

## Stale content detection

Run the hermes-skill-sync-auditor subagent (`.claude/agents/hermes-skill-sync-auditor.md`)
to scan for common hygiene violations:

```
/hermes-skill-sync-auditor
```

Or manually audit:

```bash
# Check all skill sync drift
python3 tools/hermes_skill_sync_audit.py --mode audit

# Scan for retired Correction Ledger references
grep -r "Correction Ledger" skills/ docs/hermes_skills/ CLAUDE.md

# Find skills missing frontmatter
python3 -c "
from pathlib import Path
for p in Path('skills').rglob('SKILL.md'):
    t = p.read_text()
    if not t.startswith('---'):
        print('MISSING_FRONTMATTER:', p)
"
```

---

## Change control for instruction files

| Change type | Approval required |
|---|---|
| Add new skill source | None (operator can proceed) |
| Modify existing skill (ops/governance content) | Review via `biotech-governance-reviewer` subagent |
| Modify CLAUDE.md Active Ruleset | Explicit operator decision |
| Modify CLAUDE.md Freeze Status | Explicit operator decision |
| Add/modify subagent in `.claude/agents/` | Operator review; document in notes |
| Remove skill (retire) | Update `_meta.json`, delete mirror, update skill sync maps |

---

## References

- Sync tool: `tools/sync_hermes_skills.py`
- Audit tool: `tools/hermes_skill_sync_audit.py`
- Runbook: `docs/ops/hermes_skill_sync.md`
- Subagent spec: `docs/ops/hermes_subagent_policy.md`
