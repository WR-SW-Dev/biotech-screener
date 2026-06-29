# IC Council — Recursive Improvement

Companion reference for `skills/biotech-ic-council/SKILL.md`. Load this when a review asks how the system should learn from failures, postmortems, repeated manual checks, or promotion-gate debates — i.e. when you are operating the recursive self-improvement loop, not just judging a single change.

This reference is the operational expansion of the skill's "Recursive self-improvement rule" and "Post-review LRN protocol" sections. It is read-only governance text: it tells the council how to capture and promote lessons, never how to mutate models or production autonomously.

## The loop in one line

A review is only complete when it has (a) reached a decision AND (b) emitted the learning that makes the same debate cheaper or unnecessary next time. Detection without encoding is a stalled loop.

```
review → Recursive Improvement Register (Section 7)
       → LRN entry in .learnings/LEARNINGS.md
       → [recurrence ≥ 3] → skill patch / Spec proposal
       → operator review → sync + audit → harvest_log → commit
```

## Three classes of improvement (and where each goes)

| Class | Examples | Destination |
|-------|----------|-------------|
| **safe process improvement** | new checklist item, sharper cross-examination probe, naming fix, runbook step, dashboard note | LRN now; eligible for an IC skill patch at recurrence ≥ 3 |
| **safe deterministic guardrail** | unit test, fixture, schema assertion, provenance check, null-coverage check, replay check | LRN now; propose the test/assertion as a normal PR (not a model change) |
| **model-affecting improvement** | feature/weight/threshold change, ranker/selector edit, event-EV math, gate or sizing change | LRN now, but NEVER auto-promote — route to a separate Spec + its own IC review |

The single most important boundary: a recursive improvement must never silently become a model change. If encoding the lesson would touch `final_score`, a selector, a ranker, a gate threshold, event-EV math, sizing, or snapshot-promotion semantics, it leaves the recursive loop and enters Spec governance.

## LRN capture (every review)

Write 1–3 LRN entries per review, following the format in the SKILL.md "Post-review LRN protocol". Key fields:

- **Pattern-Key** — `IC_<DOMAIN>_<description>`, snake_case, ≤6 words, from the namespace (`IC_CORP_ACTION_`, `IC_PIT_LEAK_`, `IC_CATALYST_`, `IC_EXPECTATION_`, `IC_BACKTEST_`, `IC_PRODUCTION_`, `IC_PORTFOLIO_`, `IC_PROCESS_`). Reuse the exact key when the same pattern recurs so the count is trackable.
- **Recurrence-Count** — increment when the Pattern-Key already exists; start at 1 otherwise. Judge recurrence in-session against existing LRN entries / memories (there is no separate ledger to consult — that was retired 2026-06-26 in the `self-improving` skill).
- **Promotion-lane** — `skill` (eligible to patch this skill), `spec` (model-affecting, needs a Spec), or `none` (one-off, log only).

Only `safe process improvement` and `safe deterministic guardrail` items become LRN entries with a `skill` lane. `model-affecting` items get `spec`. One-offs and context-specific notes get `none`.

## Promotion threshold

The canonical bar is **recurrence ≥ 3** — a 7-day rolling window for behavioral patterns, all-time for failure modes (matching the `failure-patterns` and `self-improving` skills). Below 3, the lesson stays an LRN entry and is allowed to recur; it is not encoded. A single sharp insight is logged, not promoted, unless the operator explicitly directs encoding.

A PENDING pattern that has cleared the threshold for more than one review cycle is a **stalled loop**, not a backlog item — surface it for operator decision rather than letting it sit.

## Promotion path (recurrence ≥ 3, lane = skill)

1. Propose a patch to `skills/biotech-ic-council/SKILL.md` — a new checklist item, a sharper probe, a domain anchor, or an example added to this file.
2. Generate drafts only: `SELFIMPROVE_GATES_MET=1 python3 tools/pattern_to_skillpatch.py --min-recurrence 3 --out artifacts/skill_patch_drafts`.
3. Operator reviews and hand-edits the SKILL.md (no autonomous skill mutation).
4. Sync and verify:
   ```bash
   python3 tools/sync_hermes_skills.py
   python3 tools/audit_hermes_skills.py
   ```
5. Append the promotion to `docs/hermes_skills/harvest_log.md` and commit.
6. Refresh the Town mirror of this skill so the loadable copy matches (the repo is canonical).

## Eligibility gate (skill patch vs Spec)

| Eligible for an IC skill patch | Ineligible — needs a Spec |
|-------------------------------|---------------------------|
| New cross-examination probe | Ranker / selector / weight changes |
| Sharper checklist item | Event-EV math or gate thresholds |
| New domain anchor or example | Production cron or sizing policy |
| Updated rubric severity | Forward-return / alpha threshold |
| PIT/provenance assertion template | Snapshot-promotion semantics |

## Learning from failures and postmortems

When a review re-derives a failure that is already cataloged, do not re-investigate from scratch:

- Check the `failure-patterns` catalog first (by category and keyword). If a match exists with a documented resolution, apply the known fix and increment recurrence rather than re-litigating.
- If the match is UNRESOLVED, add recurrence + any new diagnostic detail; do not declare it fixed.
- A failure mode at recurrence ≥ 3 with `promotion_status: PENDING` is a candidate for promoting its prevention rule into the relevant operational skill — surface it.

## Patch efficacy (close the loop on the loop)

A promoted patch is a hypothesis, not a fix, until verified. Record a 2-week post-merge efficacy check (per the harvest_log convention): did the pattern stop recurring after the patch landed? If efficacy can't be measured yet (e.g. telemetry not implemented), say so explicitly rather than assuming the patch worked.

## Restraint (does this lesson deserve to be encoded?)

Borrowed from `self-improving` Rule 10: insight is not the move. A captured lesson counts only when it changes a future decision or action — not when it is filed. Prefer fewer, sharper checklist items over an ever-growing rubric. Documentation of a recurring problem is not its resolution; if a pattern keeps recurring, escalate it toward a concrete fix or owner instead of re-logging it.
