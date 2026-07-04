# Spec: Alert-Layer Reflection + HITL Annotation (Ask David Pattern #2/#4)

**Status:** DRAFT — proposal for review (NOT authorized for production)
**Author:** Warrenpoobear (for Darren Schulz)
**Date:** July 4, 2026
**Repo:** `Warrenpoobear/biotech-screener` (branch: `main`)
**Governance class:** Additive, observe-only advisory fields on two existing agents. NO change to scoring/selector/ranker, no new supervisory layer, no `.py` scoring logic, no ruleset/manifest change.
**Pattern source:** JPMorgan Private Bank "Ask David" — reflection node (LLM-as-judge) + human-in-the-loop escalation.

---

## 1. Recommendation

Add Ask David's reflection + HITL discipline to the biotech screener as **two additive, observe-only advisory fields on agents that already exist** — NOT as new infrastructure and NOT inside the deterministic scoring path:

1. An optional `reflection_note` advisory field in the **`ops_supervisor`** output schema.
2. A per-entry **reasoning annotation** in **`review_queue_steward`**'s Step 5 report.

The screener already implements the Ask David architecture (supervisor + specialists + HITL + verifier). This spec enhances two existing nodes; it does not build a pattern.

## 2. Basis (verified from repo — July 4, 2026)

Confirmed by direct read of the repo:

- **The agent fleet already mirrors Ask David.** `agents/` contains 36 agents coordinated by `ops_supervisor` ("the LAST interpretive layer," one daily verdict). [`agents/ops_supervisor/SOUL.md`]
- **Supervisor/registry analog exists:** `agents/AGENT_REGISTRY.json` (26KB) + `agents/ops_supervisor/supervisor.py` (35KB) with an embedded, dated exception table. [confirmed]
- **HITL analog already exists:** `review_queue_steward` reads `data/snapshots/{date}/review_queue.csv`, buckets into `no_add_until_review` / `size_haircut` / `monitor_only`, builds a "must look now" list, and its closing rule is "present the queue as-is and let the human decide." [`agents/review_queue_steward/AGENTS.md`]
- **Reflection/verifier analog already exists:** `sentinel` verifies the supervisor itself ran (non-interpretive existence/freshness/schema check). [`ops_supervisor/SOUL.md` architecture block]
- **Both target agents are `observe_only`,** write only to their own `artifacts/` path, and never mutate production. [SOUL.md Boundaries; AGENTS.md Red lines]

## 3. HARD CONSTRAINT — no recursive supervision (verbatim red line)

`ops_supervisor/SOUL.md` states, per `feedback_no_recursive_supervision.md`:

> "this is the LAST interpretive layer. The sentinel above is non-interpretive... **Do not propose another layer above this one.**"

**Therefore an LLM reflection node MUST NOT be added as a new supervisory layer above `ops_supervisor`.** It may only be an advisory field *inside* the existing supervisor step, or an annotation *inside* an existing specialist. This spec is written to that constraint. Any implementation that introduces a new interpretive layer violates governance and is out of scope.

## 4. Scope

**In scope**
- Additive optional field `reflection_note` in the `ops_supervisor.v1` JSON schema (bump to `ops_supervisor.v1.1`, backward-compatible).
- A reasoning/`confidence_reason` string per "must look now" entry in `review_queue_steward` Step 5 report output.
- Both fields are advisory-only, human-consumed, never fed back into any severity/score/rank/action.

**Out of scope (DO NOT TOUCH)**
- Modules 1-5, Decision Engine, Selector (B6 `8887576e` v1.14.0), Ranker (`pairwise_minimal`), EW Top-30, `rankings.csv` scoring columns.
- Any `.py` scoring/ruleset/manifest file; `AGENT_REGISTRY.json` exception table at runtime.
- `final_severity` / `final_action` computation logic; queue action codes.
- Any new agent or supervisory layer.
- Determinism-protected scoring path (no non-deterministic/LLM call anywhere in Modules 1-5 -> selector -> ranker).

## 5. Design

### 5.1 Architecture position (unchanged fleet, two enhanced nodes)
```
agents (36 specialists)
  -> heartbeat monitor (tools/agent_heartbeat_checks.py)
  -> ops_supervisor          [ENHANCE: add advisory reflection_note field]
  -> sentinel                [unchanged: non-interpretive verifier]

review_queue_steward         [ENHANCE: add per-entry confidence_reason in Step 5 report]
```
No node is added above `ops_supervisor`. No node is inserted into the scoring path.

### 5.2 Enhancement A — `ops_supervisor` advisory `reflection_note`
- Add an OPTIONAL field to the `ops_supervisor.v1` schema (new `ops_supervisor.v1.1`):
  ```json
  "reflection_note": {
    "present": "bool",
    "note": "string | null",
    "basis": "which inputs the note is derived from",
    "advisory_only": true
  }
  ```
- The note is a narrative sanity-check on the day's already-computed verdict (e.g., "final_severity=GREEN but 3 Tier-A names newly entered no_add_until_review this week — worth a human glance"). It reads the SAME inputs the supervisor already loads (heartbeat anomalies, ops_digest, rankings.csv, prior supervisor JSON).
- **It never alters `final_severity` or `final_action`.** If the note generator is unavailable, `present=false`, `note=null` — the supervisor verdict is unaffected (fail-open on the advisory, fail-closed unchanged on the verdict).

### 5.3 Enhancement B — `review_queue_steward` per-entry reasoning
- In Step 5 (Report), the "Must Look Now" table gains one column: `confidence_reason` — a short human-readable *why this name is borderline* (e.g., "coinvest_z high but financial_score SEV1 and catalyst in 9d").
- Derived ONLY from fields already in `review_queue.csv` + the name's existing governance flags. Adds no new data and changes no bucket assignment.
- Respects the agent's existing red lines: no `.py` edits, no action-code changes, no name removal.

### 5.4 Fail-closed / fidelity guardrails
- Advisory fields are additive; absence must not break any downstream consumer (schema bump is backward-compatible; `reflection_note` optional).
- No advisory field may restate a number not present in the agent's existing inputs (no fabrication).
- Neither field is readable by any scoring/selector/ranker code — enforce with a placement assertion (advisory fields live only in `artifacts/`, never in `data/snapshots/*/rankings.csv`).
- The reflection note must NOT be positioned as a supervisory layer (Section 3); it is a field on the existing verdict object.

## 6. Rollout (governance-safe)

1. **Shadow (Phase 0):** Generate both advisory fields for the next N daily runs, written to a *side artifact* (`artifacts/ops_supervisor/{date}_reflection_shadow.json`), NOT into the live schema. Operator reviews for usefulness + zero false reassurance.
2. **Validation gate:** Darren confirms (a) notes add signal, (b) no note ever contradicts or softens a RED/ORANGE verdict, (c) no fabricated figures. One clean week required.
3. **Promote (Phase 1):** Only on explicit written approval — fold `reflection_note` into `ops_supervisor.v1.1` and the column into `review_queue_steward` Step 5. Additive schema bump; no consumer migration required.
4. Do NOT generalize to other agents or into scoring without a separate spec.

## 7. Acceptance criteria
- `reflection_note` is optional; existing `ops_supervisor.v1` consumers keep working with it absent.
- Advisory fields never appear in `rankings.csv` or any scoring input (placement assertion passes).
- No case where a reflection note lowers/contradicts `final_severity` (verified over Phase 0 window).
- `review_queue_steward` bucket assignments and action codes are byte-identical with vs. without the annotation (annotation is display-only).
- No `.py` scoring/ruleset/manifest file modified; no new agent or layer added.
- One clean Phase 0 week reviewed and approved by Darren.

## 8. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Reflection note creates false reassurance on a bad day | Guardrail: note may annotate but never soften a verdict; Phase 0 explicitly tests this |
| Scope creep into a new supervisory layer | Section 3 hard constraint; acceptance criterion forbids new layer |
| Advisory field leaks into scoring path | Placement assertion: advisory fields only in `artifacts/`, never `rankings.csv` |
| Non-determinism introduced into pipeline | LLM call is confined to the observe-only agent layer, never Modules 1-5/selector/ranker |
| Hallucinated figures in annotation | No-new-facts guardrail; derive only from existing inputs |

## 9. What this is NOT
- Not an integration with any JPMorgan system — "Ask David" is JPM-internal, no API. This ports a *pattern*.
- Not a new agent, and explicitly NOT a new supervisory layer (violates the no-recursive-supervision red line).
- Not a scoring/selector/ranker/model change; nothing touches `8887576e` v1.14.0.
- Not authorized until Phase 0 shadow + explicit operator approval.

## 10. Exact repo references (authoritative)
- `agents/ops_supervisor/SOUL.md` — supervisor identity, `ops_supervisor.v1` JSON schema, boundaries, no-recursive-supervision constraint.
- `agents/ops_supervisor/supervisor.py` — embedded exception table (do not modify at runtime).
- `agents/review_queue_steward/AGENTS.md` — daily sequence, "must look now" logic (Step 4), report format (Step 5), red lines.
- `agents/AGENT_REGISTRY.json` — fleet registry (read-only reference).
- `agents/sentinel/` — non-interpretive verifier (unchanged; do not duplicate its role).

## 11. Related specs (each separate, each gated)
- **Pattern #1 (personalization node)** — AI Digest routine (see `pattern-1-personalization-node-ai-digest.md`).
- **Pattern #3 (two-level planning-node routing)** — Hermes orchestration; architecture-level, observe/spec only.
- Companion note: for the screener, Pattern #2 is delivery/alert-layer ONLY (this spec). It is scoped OUT of the deterministic model per the July 4 investigation.
