# Self-Improving Skill

Structured learning capture with tiered storage and promotion rules.
Source: clawhub.ai/ivangdavila/self-improving

## When to Use

- User corrects you or points out mistakes
- You complete significant work and want to evaluate the outcome
- You notice something in your own output that could be better
- Knowledge should compound over time without manual maintenance

## Memory Architecture

Storage lives in `.learnings/` (adapted from `~/self-improving/` to fit repo structure):

| Tier | File | Limit | Purpose |
|------|------|-------|---------|
| HOT | `memory.md` | ≤100 lines | Always loaded, most critical patterns |
| WARM | `projects/{name}.md` | ≤200 lines each | Per-project learnings |
| WARM | `domains/{name}.md` | ≤200 lines each | Domain-specific patterns |
| COLD | `archive/` | Unlimited | Decayed patterns |
| LOG | `corrections.md` | Last 50 | Raw correction log |

## Learning Signals

### Log immediately
- **Corrections**: "No, that's not right...", "Actually, it should be...", "You're wrong about...", "I prefer X, not Y", "Stop doing X"
- **Preferences**: "I like when you...", "Always do X for me", "Never do Y"

### Track and promote after 3x
- **Patterns**: Recurring mistakes, recurring successes, recurring workarounds

### Ignore
- One-time instructions
- Context-specific guidance
- Hypotheticals

## Self-Reflection Framework

After completing significant work:
1. Did it meet expectations?
2. What could be better?
3. Is this a pattern?

Log format:
```
CONTEXT: [task type]
REFLECTION: [what I noticed]
LESSON: [what to do differently]
```

## Core Rules

### Rule 1 — Learning
Log explicit corrections and self-identified improvements. Never infer from silence. Confirm patterns after 3 identical lessons.

### Rule 2 — Tiered Storage
- **HOT** (≤100 lines): Critical patterns, active preferences
- **WARM** (≤200 lines each): Per-project, per-domain
- **COLD** (unlimited): Archived, decayed

### Rule 3 — Promotion / Demotion
- 3x in 7 days → promote to HOT
- Unused 30 days → demote to WARM
- Unused 90 days → move to archive

### Rule 4 — Namespace Isolation
- Projects in `projects/{name}.md`
- Global patterns in HOT `memory.md`
- Domain patterns in `domains/{name}.md`

### Rule 5 — Conflict Resolution
Most specific wins: project > domain > global. Most recent wins at same level.

### Rule 6 — Compaction
Merge similar corrections. Archive unused patterns. Never delete without asking.

### Rule 7 — Transparency
Cite sources: "Using X (from projects/foo.md:12)". Weekly digests. Full export on demand.

### Rule 8 — Security
Never store credentials, health data, or third-party information.

### Rule 9 — Graceful Degradation
Load `memory.md` first. Load namespaces on demand. Communicate what's unavailable.

## Scope

**ONLY**: Learns from corrections and self-reflection; stores preferences locally; reads memory files.

**NEVER**: Accesses calendar/email/contacts; makes network requests; reads outside project directory; infers from silence; deletes memory blindly.

## Integration with Existing .learnings/

This skill complements the `self-improvement` skill (pskoett):
- `self-improvement` provides logging format (LRN/ERR/FEAT entries) + hooks
- `self-improving` provides tiered storage + promotion/demotion rules
- Both write to `.learnings/` directory
- Promotion targets: CLAUDE.md, memory files, SOUL.md
