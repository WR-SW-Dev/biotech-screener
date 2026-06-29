# IC Council — Review Rubric

Companion reference for `skills/biotech-ic-council/SKILL.md`. Defines the strict severity levels, merge gates, blocker classification, and recursive-improvement gates the council applies. Load this when you need to assign a severity, decide whether something blocks a merge, or judge whether a finding has cleared its promotion gate.

This rubric is read-only governance text. It never authorizes a merge, a production change, or a model change by itself — it only standardizes how the council labels findings so the operator's decision is consistent across reviews.

## Severity levels

Assign exactly one severity per finding. When in doubt, escalate one level rather than down-rank.

| Severity | Meaning | Council effect |
|----------|---------|----------------|
| **BLOCKER** | Would cause wrong production output, PIT leakage, a false alpha claim, or an irreversible/unsafe action if merged. | Forces `reject / revert` or `hold pending validation`. Never compatible with `merge / approve`. |
| **HIGH** | Real correctness or governance risk that is contained or conditional (e.g. wrong only in an unobserved regime, or behind a flag). | Forces at most `merge only as research-only` or `merge only as plumbing / no-alpha-claim` until resolved. |
| **MEDIUM** | Inconsistency, missing test, or undocumented assumption that should be fixed but does not invalidate the change. | Compatible with merge if a required follow-up check is recorded. |
| **LOW** | Style, naming, or documentation nit. | Informational; never blocks. |
| **UNOBSERVED** | Evidence required to judge is missing. NOT a pass. | Treat as HIGH for any alpha/PIT/production dimension until evidence is supplied. Never infer the missing evidence. |

`UNOBSERVED` is the rubric's single most important discipline: the council must mark missing evidence as missing, never assume it favorable. A decision-matrix row may only be `pass` when positive evidence exists.

## Decision-matrix status mapping

The Section 6 decision matrix uses `pass | watch | fail | unobserved`. Map severities to status:

- Any **BLOCKER** on a dimension → that dimension is `fail`.
- **HIGH** → `fail` if it directly undermines the dimension, else `watch`.
- **MEDIUM** → `watch`.
- **LOW** → `pass` (note the nit in rationale).
- Missing evidence → `unobserved` (never `pass`).

## Merge gates

The Final IC Recommendation (Section 8) is constrained by the matrix:

| Final recommendation | Allowed only when |
|----------------------|-------------------|
| **merge / approve** | No BLOCKER and no `fail` row; all alpha/PIT/production dimensions are `pass`; rollback path stated. |
| **merge only as research-only** | Diagnostic value is real but a production dimension is `watch`/`unobserved`; no BLOCKER. Output must not feed production sort keys. |
| **merge only as plumbing / no-alpha-claim** | Improves coverage/observability/expectation estimation only; carries no forward-return or alpha claim; no BLOCKER. |
| **hold pending validation** | A HIGH or UNOBSERVED dimension blocks confidence and the missing evidence is obtainable. |
| **reject / revert** | Any BLOCKER, or the change is outside mandate (leaky, trading-adjacent, or silently model-affecting). |
| **no consensus** | Seats reach irreducible disagreement; escalate to operator with the open question stated in one line. |

Hard rule: **CI is never assumed green.** If CI status is unobserved or red, no recommendation above `hold pending validation` may be issued for a production-path change. State the CI basis explicitly.

## Blocker classification

A finding is a BLOCKER if any of the following is true:

- It introduces **PIT leakage** (a forward return or future-dated source enters a feature, or a generated artifact feeds an input hash unintentionally).
- It makes a **forward-return / IC / hit-rate / alpha claim** unsupported by out-of-sample or forward evidence.
- It silently alters `final_score`, a selector, a ranker, a gate threshold, event-EV math, or sizing/portfolio policy without a separate model-change review.
- It accepts a biotech price series without checking splits, reverse splits, spinouts, M&A, delistings, or special distributions.
- It accepts a catalyst claim without source-date / effective-date discipline.
- It breaks deterministic replay or removes a rollback path on a production change.
- It would take an irreversible or trading-adjacent action from council output alone.

Anything trading-adjacent, credential-touching, or cron-mutating that lacks an explicit blast-radius + rollback discussion is at minimum HIGH and usually BLOCKER.

## Recursive-improvement gates

A finding only earns a place in the Section 7 register (and a downstream LRN entry) when it is supported by evidence or a clearly repeated risk — never speculation.

Promotion of a recurring pattern into the skill body or a companion reference is gated on **recurrence ≥ 3** (the canonical threshold: 7-day rolling window for behavioral patterns, all-time for failure modes). Below that threshold the lesson is logged as an LRN entry and left to recur; it is not encoded.

Eligibility for an IC *skill* patch (vs. requiring a separate Spec) follows the table in the SKILL.md "What may become an IC skill patch" section: process/checklist/rubric/anchor/template edits are eligible; anything touching ranker/selector/weights, event-EV math, gate or alpha thresholds, cron, sizing, or snapshot-promotion semantics requires a Spec, not a skill patch.
