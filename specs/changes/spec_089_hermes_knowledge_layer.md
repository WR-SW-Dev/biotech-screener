# Spec 089 — Hermes Knowledge Layer

**Status:** PHASE 0 COMPLETE / PHASE 1 IN PROGRESS
**Author:** Hermes ops session 2026-05-07
**First commit:** TBD

---

## Objective

Build a repo-native knowledge layer for Hermes that continuously answers:

1. What is the current operational state?
2. What changed since the last good state?
3. What is held, blocked, or awaiting first-fire validation?
4. What contradictions exist across specs, audit memos, cron, and registry?
5. What is the next allowed operator action?
6. What is explicitly not allowed?

This becomes the system "ops brain" but NOT a source of production truth.
Production truth remains in deterministic artifacts, code, cron, and receipts.

---

## Design — Four Layers

### Layer 1 — Capture (read-only)

Sources:
- specs/changes/*.md
- artifacts/audit/*.md
- artifacts/ops/**/*.md
- agents/AGENT_REGISTRY.json
- agents/*/SOUL.md (where present)
- docs/MODEL_DOCUMENTATION.md
- git log --oneline -N
- git status --porcelain
- crontab -l
- key production artifacts:
    data/snapshots/<date>/
    artifacts/bioshort_watch/latest_status.json
    output/hedge_report/BIOSHORT_VERDICT.json
    artifacts/catalyst_delta/
    ruleset/manifest artifacts

Note: logs are secondary. B0/B0.1 investigation showed child-process stdout
can be captured and discarded; filesystem artifacts are more reliable.

### Layer 2 — Normalize

artifacts/ops/knowledge_layer/
  latest_state.json
  latest_state.md

artifacts/ops/held_spec_ledger/
  latest.json
  latest.md
  YYYY-MM-DD.md

artifacts/ops/first_fire_ledger/
  latest.json
  latest.md

artifacts/ops/contradiction_ledger/
  latest.md

artifacts/ops/operator_brief/
  daily/YYYY-MM-DD.md
  weekly/YYYY-MM-DD.md

### Layer 3 — Reason

- held branch drift
- stale artifact drift
- contradiction detection
- first-fire validation
- scheduled job missed-run detection
- uncommitted held-file detection
- registry vs cron mismatch
- spec vs implementation mismatch
- "next allowed action" extraction

### Layer 4 — Return

Daily:
- 5-minute operational brief
- blockers, fresh failures, held branches, first-fire checks due today

Weekly:
- synthesis of open branches, contradictions, stale specs,
  research opportunities, decisions awaiting operator

---

## Jobs (target state, Phases 2-3)

| Job | Cadence | Purpose |
|-----|---------|---------|
| hermes-knowledge-indexer | daily after production + manual | build latest_state.json |
| hermes-held-spec-ledger | Mon 08:45 ET + daily while specs open | prevent branch contamination |
| hermes-first-fire-validator | one-shot after new cron first run | validate new scheduled jobs |
| hermes-contradiction-detector | daily lightweight, weekly deep | catch conflicts |
| hermes-daily-operator-brief | weekday morning | rank-order the day |
| hermes-weekly-synthesis | Mon or Sun | strategic synthesis |

Phase 2 start order: hermes-held-spec-ledger, hermes-first-fire-validator first.

---

## Data Model

### latest_state.json schema

```json
{
  "as_of_date": "YYYY-MM-DD",
  "git": {
    "head": "sha",
    "branch": "main",
    "uncommitted": []
  },
  "cron": {
    "active_jobs": [],
    "suppressed_jobs": []
  },
  "specs": [],
  "held_items": [],
  "first_fire_items": [],
  "warnings": []
}
```

### held_spec_ledger/latest.json schema

```json
{
  "as_of_date": "YYYY-MM-DD",
  "items": [
    {
      "id": "spec_087_b1b",
      "title": "Bioshort weekly producer first-fire",
      "status": "AWAITING_FIRST_FIRE",
      "last_evidence": "crontab installed, one active producer cron",
      "blocker": "Friday 2026-05-08 18:00 EDT first-fire not yet observed",
      "next_allowed_action": "read first-fire validation outputs",
      "not_allowed": [],
      "requires_operator_approval": true,
      "related_artifacts": []
    }
  ]
}
```

### first_fire_ledger/latest.json schema

```json
{
  "jobs": [
    {
      "job": "biotech_hedge_report",
      "cron": "0 18 * * 5",
      "expected_first_fire": "2026-05-08T18:00:00-04:00",
      "expected_artifacts": [
        "output/hedge_report/hedge_report_2026-05-08.json"
      ],
      "status": "PENDING"
    }
  ]
}
```

---

## Implementation Phases

### Phase 0 — Document only (DONE)

Created:
- specs/changes/spec_089_hermes_knowledge_layer.md
- artifacts/ops/knowledge_layer/README.md

No cron. No code. No job scheduling.

### Phase 1 — Ledger generator (IN PROGRESS)

Build: tools/build_hermes_knowledge_layer.py

Outputs:
- artifacts/ops/knowledge_layer/latest_state.json
- artifacts/ops/knowledge_layer/latest_state.md
- artifacts/ops/first_fire_ledger/latest.json
- artifacts/ops/first_fire_ledger/latest.md

Read-only. No scheduler changes.

Acceptance criteria:
- detects Spec 087 B1b as AWAITING_FIRST_FIRE
- detects Spec 088 Phase B as HELD
- detects watchlist_current.json as uncommitted/held
- does not touch git-tracked production files

### Phase 2 — Hermes job wiring

Start with:
1. hermes-held-spec-ledger
2. hermes-first-fire-validator

### Phase 3 — Daily/weekly synthesis

Add daily and weekly operator briefs.
Telegram only hard failures (missing snapshot, missed first-fire, absent artifact,
ruleset mismatch, cron job did not fire). No routine brief via Telegram.

### Phase 4 — Deeper research memory (later)

- signal history synthesis
- alpha research queue
- bioshort time-series research readiness
- catalyst_delta artifact-filter research state

---

## Guardrails (always active)

MAY:
- read repo state
- write ledger artifacts
- produce briefs
- flag contradictions
- recommend next actions

MAY NOT:
- change scoring
- change selector/ranker/EV/sizing
- change cron without explicit approval
- reactivate agents
- commit held files
- infer approval from stale notes
- treat LLM synthesis as alpha evidence

---

## Prompt Templates (for Phase 2 Hermes jobs)

### Knowledge Indexer

```
You are Hermes Knowledge Indexer.
Read repo state, recent commits, specs, audit memos, agent registry, and crontab.
Produce a normalized state ledger.
Rules:
- Do not modify code.
- Do not modify cron.
- Do not infer approval.
- Preserve explicit HELD / NOT APPROVED states.
- Mark uncertainty as NEEDS_OPERATOR_DECISION.
- Prefer artifact/file-system evidence over logs when logs are known lossy.
```

### Held-Spec Ledger

```
You are Hermes Held-Spec Ledger.
Find every open, held, blocked, or awaiting-validation branch.
For each, report: status, last evidence, blocker, next allowed action,
explicitly not allowed, related artifacts, related cron/jobs,
whether operator approval is required.
Never stage or commit held files.
Never merge held branches into unrelated work.
```

### Contradiction Detector

```
You are Hermes Contradiction Detector.
Compare specs, audit memos, cron, registry, docs, and recent commits.
Find conflicts between: declared state and actual state, held/not-approved
actions and committed changes, date/cadence claims and cron expressions,
artifact freshness claims and file dates, registry status and supervisor status.
Classify: HARD_CONTRADICTION, POSSIBLE_DRIFT, HISTORICAL_REFERENCE, OK.
Recommend one operator decision if needed.
```

### Daily Operator Brief

```
You are Hermes Daily Operator Brief.
Produce a short operator-facing brief:
1. Blockers
2. Fresh WARN/FAIL items
3. Portfolio/catalyst watch items
4. Signal health changes
5. Fleet/cron health
6. Held specs and next allowed actions
7. One recommended operator decision
Do not summarize everything. Surface only what changes action.
```
