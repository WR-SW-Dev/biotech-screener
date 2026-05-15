# Agent Preflight Checklist

**Version**: 1.0  
**Effective**: 2026-05-15  
**Scope**: Required for all LLM-initiated work on biotech-screener

---

## Purpose

Before any agent starts work (Hermes/OpenClaw session, run_agent_direct.py agent, or manual session), run the preflight checklist to:
1. Establish current operational state
2. Identify blocked specs and contradictions
3. State explicitly what work is allowed
4. Prevent drift, stale recommendations, and forbidden changes

This takes **~2 minutes** and prevents **80% of operational drift**.

---

## Canonical Checklist

Run these commands in order:

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

# 1. Git state
git status --short
git log --oneline -5

# 2. Latest snapshots
ls -td data/snapshots/*/ | head -3

# 3. Build/read knowledge layer (deterministic state compression)
python tools/build_hermes_knowledge_layer.py 2>/dev/null || echo "Knowledge layer not available; skip."

# 4. Read latest operational state
cat artifacts/ops/knowledge_layer/latest_state.md 2>/dev/null | head -80

# 5. Check for held specs (blocking work)
cat artifacts/ops/held_spec_ledger/latest.md 2>/dev/null || echo "No held specs."

# 6. Check for active contradictions
cat artifacts/ops/contradiction_ledger/latest.md 2>/dev/null || echo "No contradictions logged."
```

**If `build_hermes_knowledge_layer.py` does not exist yet**, use the fallback checklist below.

---

## Fallback Checklist (Until Knowledge Layer Tool Exists)

```bash
# 1. Git state
git status --short
git log --oneline -5

# 2. Latest snapshots
ls -td data/snapshots/*/ | head -3

# 3. Latest operational memo
ls -ltr artifacts/audit/operational_closure_* artifacts/audit/13f_cohort_status_* 2>/dev/null | tail -1

# 4. Check for active freeze/quarantine
grep -i "frozen\|quarantine\|blocked" artifacts/audit/operational_closure_* 2>/dev/null | head -5 || echo "No explicit freeze found."

# 5. Check for closed/deferred specs
ls -ltr artifacts/audit/*_closure_memo_* artifacts/audit/spec_*_defer_memo_* 2>/dev/null | tail -5
```

---

## Output Format

After running the checklist, the agent **must output** (in order):

```
## Preflight Report

**Current branch state**: [on main / on feature branch / dirty working tree]
**Latest snapshot**: [date + QA status]
**Git HEAD**: [commit hash + message]
**Blocked/frozen specs**: [list, or "none"]
**Contradictions**: [list, or "none"]
**Active quarantine/freeze**: [cohort quarantine status, architecture freeze status, etc.]
**Allowed next action**: [explicit statement of what work can start]
**Not allowed**: [explicit statement of what work is forbidden]
**If knowledge layer unavailable**: [explain fallback used]
```

**Example output**:

```
## Preflight Report

**Current branch state**: on main, clean
**Latest snapshot**: 2026-05-15, QA PASS (drift PASS, phase 2 OK)
**Git HEAD**: 3185d752 "Operational closure: 2026-05-15 snapshot QA + bookkeeping"

**Blocked/frozen specs**:
  - Spec 089 KG implementation (pending 13F cohort clearance)
  - Spec 100 (blocked by Spec 096 doctrine)
  - Ranker/selector/sizing work (frozen during cohort quarantine)

**Contradictions**: None detected

**Active quarantine/freeze**:
  - 13F Q1 2026 cohort quarantine: STILL ACTIVE (6/48 managers filed; distortion not cleared)
  - Architecture freeze: ACTIVE until post-h20d (2026-05-26)

**Allowed next action**:
  - Deploy diagnostics for evening cron reliability
  - Write governance docs (hermes_openclaw_routing_policy, token_budget_policy)
  - Audit forward shadow freshness
  - Monitor 13F filing ingest daily

**Not allowed**:
  - Any ranker/selector/sizing changes
  - Spec 089 KG implementation (deferred pending cohort clearance)
  - Spec 100 implementation (blocked by doctrine)
  - Broad crontab edits without approval

**If knowledge layer unavailable**: Used fallback checklist (grep + ls); knowledge layer not yet deployed.
```

---

## Integration with Agents

### For Hermes/OpenClaw Sessions

Add to initial system prompt or session setup:

```
Before you start work:
1. Run the agent preflight checklist (canonical version in docs/ops/agent_preflight_checklist.md).
2. Output the preflight report.
3. Do not proceed with work unless the report explicitly authorizes it.
```

### For `run_agent_direct.py` Agents

Call `tools/agent_preflight.py` (when available) at agent startup:

```python
from tools.agent_preflight import run_preflight
state = run_preflight()
if state["allowed_next_action"] is None:
    logger.warning("Preflight: no allowed work. Exiting.")
    sys.exit(0)
```

### For Manual Sessions

Include preflight checklist in Claude Code startup (can be part of memory, CLAUDE.md, or this doc itself).

---

## What Preflight Prevents

- **Stale recommendations**: "Start Spec 100" when Spec 100 is already blocked by doctrine
- **Contradictions**: Recommending work that contradicts an active freeze or contradiction
- **Unsynchronized state**: Agent unaware that Spec 089 is deferred pending cohort clearance
- **Forbidden changes**: Recommending ranker/selector/sizing changes during freeze
- **Artifact gaps**: Proposing work without understanding what artifacts are missing
- **Cron conflicts**: Suggesting cron changes that conflict with reliable production runs

---

## Maintenance

**Update preflight checklist when**:
- A new freeze or quarantine is declared
- A major spec is blocked or closed
- An artifact path changes (e.g., moved from `artifacts/audit/` to `artifacts/ops/`)
- Knowledge layer tool is deployed (switch from fallback to canonical)

**Review annually or after major architecture changes**.

---

## References

- [Hermes/OpenClaw routing policy](hermes_openclaw_routing_policy.md)
- [Token budget policy](token_budget_policy.md)
- [AGENT_REGISTRY.json](../../agents/AGENT_REGISTRY.json) — agent authority levels
- [tools/agent_preflight.py](../../tools/agent_preflight.py) — programmatic preflight (when deployed)
