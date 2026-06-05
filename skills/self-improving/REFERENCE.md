# Self-Improving — Reference (biotech-screener)

Long-form templates and checklists. Entry point: `skills/self-improving/SKILL.md`.

---

## LRN entry template (`.learnings/LEARNINGS.md`)

```markdown
## [LRN-YYYYMMDD-XXX] short_snake_title

**Logged**: ISO-8601 timestamp
**Priority**: low | medium | high | critical
**Status**: pending | promoted | resolved | superseded
**Area**: tooling | ops | research | ci | hermes_ops | cloud_environment

### Summary
One sentence.

### Details
What happened, root cause, blast radius.

### Suggested Action
Concrete next step (skill patch, test, operator check).

### Metadata
- Source: session_id or tool name
- Related Files: paths
- Tags: comma-separated
- Pattern-Key: snake_case (for recurrence counting)
- Recurrence-Count: N
- Skill-Path: optional target skill dir (e.g. screener_ops, codegraph)
```

---

## Harvest log template (`docs/hermes_skills/harvest_log.md`)

```markdown
## YYYY-MM-DD (short title)

### Skill sources refreshed
- **skill-name** (`skills/<dir>/SKILL.md`): what changed
- Ran `sync_hermes_skills.py` — updated `mirror.md`

### Learnings promoted
- LRN-... → HOT `memory.md` | WARM `projects/biotech_screener.md`

### Governance
- Skills/docs only. No ranker, selector, sizing, or scoring changes.
```

---

## Session-end audit (5 minutes)

1. Any user correction? → `corrections.md` + consider `LEARNINGS.md`
2. Recurrence-Count ≥ 3 for same Pattern-Key? → promote tier
3. Operator workflow or tooling lesson? → candidate for `skills/*/SKILL.md`
4. If skill edited: `sync_hermes_skills.py` + `audit_hermes_skills.py`
5. If skill committed: append `harvest_log.md` section

---

## Skill-patch review checklist

Before merging a learning-driven skill PR:

- [ ] Change is **docs/skills only** OR separate code PR with tests
- [ ] No ranker/selector/sizing/final_score/decision_engine/KG production touch
- [ ] No cron or gateway config in repo (operator host only)
- [ ] Mirror drift audit clean
- [ ] LEARNINGS entry or harvest_log cites the pattern
- [ ] Stale mirror sections removed (no duplicate gates)

---

## Anti-patterns (do not automate)

- Promoting research signal findings into production weights without Spec + CRT+IC+PIT
- Writing hedge/cron truth into skills without WSL verification
- Expanding SKILL.md with full runbooks (use REFERENCE.md or Hermes-native docs)
- Inferring user preferences from silence
- Deleting `.learnings/` entries without operator confirmation

---

## Related skills

| Skill | Recursive role |
| --- | --- |
| `screener_ops` | Ops gates, knowledge layer, WSL authority |
| `codegraph` | Structural preflight, bounded proof |
| `openclaw-agent-optimize` | Context/skill bloat → compaction candidates |
| `memory_steward` | Tier demotion, archive (read-only default) |
| `selector_ranker` | Tier 3 preflight — learnings do not override BLOCKED |
