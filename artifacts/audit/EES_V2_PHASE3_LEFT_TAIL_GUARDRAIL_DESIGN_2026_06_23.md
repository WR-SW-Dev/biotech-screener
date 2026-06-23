# EES v2 Phase 3 Left-Tail Guardrail — Design Memo

**Date:** 2026-06-23  
**Status:** DESIGN_ONLY — NOT APPROVED FOR IMPLEMENTATION  
**Prerequisite commits:** `e80c3ff2` (validation), `c35fc1ba` (spec), `60876b11` (monitor),
`376d9e9d` (hardening), `fb52071f` (attribution)  
**Verdict:** `DESIGN_ONLY_LEFT_TAIL_GUARDRAIL_CANDIDATE_PENDING_SHADOW_CONFIRMATION`

---

## 1. Finding

### 1.1 The Signal Is Left-Tail Avoidance, Not Broad Alpha

The EES forward validation and attribution review chain establishes a specific,
bounded finding:

> **EES v2 Phase 3 signal = CT_PRIMARY_COMPLETION left-tail avoidance.**

EES v2 is not primarily selecting winners. It identifies Phase 3
CT_PRIMARY_COMPLETION names that should be avoided because they sit in the bad
left tail of the score distribution.

| Evidence | Result |
|----------|--------|
| Phase 3 5d IC | 0.174, t=4.97 (31 dates) |
| Phase 3 20d IC | 0.203, t=4.33 (15 dates) |
| Q1 low-score 5d return | **-3.47%** XBI-excess |
| Q1 low-score 20d return | **-6.80%** XBI-excess |
| Q2–Q5 5d return spread | < 1.0% — nearly indistinguishable |
| Q2–Q5 20d return spread | Scattered; no monotone pattern |
| CT_PRIMARY_COMPLETION IC t (5d) | 2.60 (31 dates) |
| All other Phase 3 event types | 1–2 valid IC dates — unevaluated |

The quintile shape is the key diagnostic: Q1 materially underperforms; Q2–Q5 are
compressed near zero with no clear ordering. This rules out EES as a symmetric
scorer. It is a one-tailed signal.

### 1.2 Applicable Cohort

| Dimension | In scope | Out of scope |
|-----------|----------|-------------|
| Phase | Phase 3 (lead_program_phase ≥ 3.0) | Phase 2 (IC=0.043, t=0.59 — no signal) |
| Event type | CT_PRIMARY_COMPLETION only | DATA_READOUT, CT_STUDY_COMPLETION, FDA_PDUFA_DATE (each ≤2 valid IC dates — unevaluable) |
| Score | | EES v3 — 21.8% coverage, 0 valid IC dates — unevaluable |
| Eligibility | EES-eligible names within Phase 3 (IC=0.158 t=3.88) | Non-eligible within Phase 3 (IC=-0.203 — adverse) |

**Non-applicable:** Phase 2, all non-CT_PRIMARY_COMPLETION Phase 3 events, and EES v3.
The guardrail concept does not transfer to those cohorts without separate evidence.

---

## 2. Candidate Future Model Uses

The following options are **future design candidates only**. None is approved. Each
requires a separate operator-approved implementation spec before any code is written.

### 2.1 Risk Warning (Informational)

**Mechanism:** Flag a Phase 3 CT_PRIMARY_COMPLETION name as a risk warning if its
`ees_v2_score` falls in the historical Q1 range (below threshold T). No automatic
change to rank, weight, or selection. A warning field is appended to diagnostic
artifacts for operator review.

**Pros:** Non-invasive. Adds information without changing model output. Easy to
validate (compare flagged names' realized returns over time). Shadow monitor directly
measures whether warnings correspond to future underperformance.

**Cons:** Does not act on the signal — requires operator intervention per flag.
Operationally costly if flags are frequent.

**Label:** FUTURE_DESIGN_ONLY — NOT APPROVED

---

### 2.2 Soft Penalty (Score Adjustment)

**Mechanism:** Apply a downward adjustment to `ees_v2_score` (or a derived
composite score) for Q1 names. Penalty magnitude is proportional to distance below
threshold T. Name remains selectable but ranks lower.

**Pros:** Preserves the continuous score signal. Blends cleanly with other score
components. Proportional — not a binary gate.

**Cons:** Requires defining a penalty function and magnitude — introduces a new
calibration parameter. Risk of double-counting if downstream ranker already responds
to ees_v2_score. In-distribution behavior untested.

**Label:** FUTURE_DESIGN_ONLY — NOT APPROVED

---

### 2.3 Hard Exclusion Gate

**Mechanism:** Names with Phase 3 + CT_PRIMARY_COMPLETION + ees_v2_score below
threshold T are excluded from the eligible universe for that snapshot. No weight, no
rank — not selectable.

**Pros:** Cleanest implementation of the "left-tail avoidance" finding. Hardest to
accidentally revert.

**Cons:** Binary gates have sharp edges — a name at T-ε is excluded; a name at T+ε
is not. Gate may be unstable if the score distribution compresses or shifts. Exclusion
gates interact with concentration limits (excluding a name can increase weight in
remaining names). Requires explicit sunset criteria (if shadow monitor invalidates).

**Label:** FUTURE_DESIGN_ONLY — NOT APPROVED

---

### 2.4 Reduced Sizing Cap

**Mechanism:** Retain the name in the eligible universe but apply a reduced maximum
weight cap for Q1 names. For example: if the standard cap is X%, apply 0.5×X% for
Phase 3 CT_PRIMARY_COMPLETION names below threshold T.

**Pros:** Partial risk brake rather than binary on/off. Preserves optionality —
if a Q1 name has strong rank on other dimensions, it can still appear in the
portfolio, just smaller.

**Cons:** Cap changes interact with the rebalancing constraint system. May require
changes to the sizing module, which is frozen. Does not eliminate exposure to Q1
underperformers — only reduces it. Harder to backtest in isolation.

**Label:** FUTURE_DESIGN_ONLY — NOT APPROVED

---

## 3. Proposed Conservative Trigger Definition

If any of the above candidates moves to implementation, the trigger must satisfy all
of the following conditions:

### 3.1 Phase Filter
- `lead_program_phase >= 3.0` (float comparison, not string matching)
- Evaluation uses the same `is_phase3()` logic as the shadow monitor

### 3.2 Event Type Filter
- `catalyst_event_type == "CT_PRIMARY_COMPLETION"` (exact match)
- No other event types qualify under this trigger

### 3.3 Score Threshold
- `ees_v2_score` must be non-null and pass the EES eligibility gate (`ees_eligible=True`)
- Score must fall below threshold T, defined as one of:
  - **Option A — Quintile boundary:** Score below the historical Q1/Q2 boundary from
    the PIT panel (~-0.019, where Q1 returns -3.47% vs Q2 returning +0.39% at 5d).
    Boundary must be re-estimated from the shadow monitor panel before deployment.
  - **Option B — Fixed floor:** Score below a fixed sentinel (e.g., -0.025) derived
    from the PIT Q1 score mean (-0.048) with margin. More stable against score
    compression but less responsive to distribution shifts.
  - Option selection requires a separate design decision and must not be made
    in this memo.

### 3.4 Timing Precision
- `anchor_date` must be non-null (a valid event date is resolvable)
- If event date is missing or more than 90 days stale, trigger does not fire

### 3.5 Scope Limit
- Trigger fires only on current-snapshot names, not retroactively on prior snapshots
- Does not apply to EES v3 scores (insufficient coverage, unevaluated)
- Does not apply to Phase 2 or non-CT_PRIMARY_COMPLETION Phase 3 names

---

## 4. Shadow Monitoring Requirement

**No model-use decision is authorized before the shadow monitor completes its
observation gates.**

The shadow monitor (`scripts/research/ees_v2_phase3_shadow_monitor.py`) has been
running since 2026-06-23. Gates:

| Gate | Threshold | Current status (2026-06-23) |
|------|-----------|----------------------------|
| Completed 5d observations | ≥ 20 | 0 — NOT_MET |
| Completed 20d observations | ≥ 20 | 0 — NOT_MET |

Until both gates are met: `OBSERVATION_WINDOW_INCOMPLETE_NO_INTERPRETATION`.

The shadow monitor tests whether the PIT panel signal is a real prospective signal
or a historical artifact. The PIT evidence is necessary but not sufficient for
deployment. The following questions must be answered from prospective data:

- Do Q1 names in the shadow ledger actually underperform over the next 5d and 20d?
- Is the prospective cross-sectional IC consistent with the PIT panel IC?
- Does the eligible gate continue to discriminate within Phase 3?
- Is the CT_PRIMARY_COMPLETION event type concentration stable in forward data?

**Minimum timeline for gates to be met:**
- 5d gate: ~4–5 trading weeks (20 trading days of Phase 3 CT_PC observations)
- 20d gate: ~4–6 calendar weeks (requires 20 snapshots where 20d return windows close)

Neither gate has a forced schedule — the shadow monitor accumulates observations
from actual daily snapshot runs. No interpretation is possible until both are met.

---

## 5. Failure Modes

### 5.1 Overfitting to the PIT Gap Panel

The PIT panel covers a specific date range (the EES forward validation panel spans
snapshots through 2026-06-23). The Q1 threshold (-0.019 quintile boundary) was
estimated from these dates. If the score distribution was unusual in that period,
the threshold will not generalize.

**Mitigation:** The shadow monitor uses prospective data. If the prospective IC is
materially lower than the PIT IC, the guardrail trigger is invalidated before
deployment.

### 5.2 Binary-Event Outliers

Some Phase 3 CT_PRIMARY_COMPLETION events may be binary in the colloquial sense
(one major catalyst drives the return regardless of base-rate pricing). A single
large-magnitude event in a small IC panel can bias the metric.

**Mitigation:** Per-date IC distributions show 25/31 positive dates, with no single
date contributing > 0.10 to the mean IC. The signal is distributed. However, if the
shadow monitor shows a handful of dates driving the prospective IC, this must be
flagged before deployment.

### 5.3 Event-Type Leakage

`catalyst_event_type = CT_PRIMARY_COMPLETION` is assigned from the EES
classification pipeline. If misclassifications are common (e.g., DATA_READOUT
events labeled as CT_PRIMARY_COMPLETION), the guardrail will fire on the wrong
events. Note that the broader classifier misclassification scan found systemic
quality issues (47.6% collision rate, 81.2% needs_review rate across 78 tickers,
as documented in `broader_classifier_misclassification_2026_06_01.md`).

**Mitigation:** Any implementation spec must include a classifier quality gate:
the trigger only fires if the event-type classification has confidence above a
minimum threshold, or if it passes a separate manual review step.

### 5.4 Phase Misclassification

Names with ambiguous or transitional phase assignments (e.g., Phase 2/3 trials,
or Phase 3-ready names that haven't been re-classified) may be incorrectly
included or excluded.

**Mitigation:** The trigger uses `is_phase3(value) → float >= 3.0`. Phase 2/3
names (lead_program_phase=2.5) are excluded. This is conservative — it may miss
some legitimate Phase 3 names but avoids over-broad application.

### 5.5 Score Compression Causing Unstable Thresholds

The EES v2 score distribution is highly compressed: Phase 3 median = -0.016,
Q75 = 0.00. Scores are tightly clustered near zero. Small changes to the score
model or base-rate data can shift the entire distribution, causing names that
were above threshold T to fall below it (or vice versa) with no change in their
fundamental risk profile.

**Mitigation:** Any threshold choice (Option A or B from §3.3) must be validated
against score distribution stability. Before deployment, the distribution of
ees_v2_score across rolling 6-month windows should be checked for stability.

---

## 6. Governance

| Control | Status |
|---------|--------|
| Production model freeze | ACTIVE — this memo changes nothing in the production model |
| Ranker changes | FROZEN — no changes |
| Selector changes | FROZEN — no changes |
| Sizing / final_score changes | FROZEN — no changes |
| Gate changes | FROZEN — no changes |
| Snapshot / portfolio changes | FROZEN — no changes |
| Freeze lift | Not authorized by this memo |
| Production integration | Not authorized by this memo |
| Code implementation | Not authorized by this memo |

**Authorization sequence for any future implementation:**

1. Shadow monitor observation gates must both be met (§4)
2. Operator reviews shadow monitor IC vs PIT panel IC
3. Operator commissions a separate implementation spec memo
4. Implementation spec memo must be operator-approved before code is written
5. Code must be operator-reviewed before any run
6. Run output must be operator-reviewed before any commit
7. Commit must be reviewed before merge
8. No merge to production model without explicit production-promotion instruction

Each step is independent and requires its own explicit authorization. This design
memo does not authorize steps 2–8.

---

## 7. Verdict

```
DESIGN_ONLY_LEFT_TAIL_GUARDRAIL_CANDIDATE_PENDING_SHADOW_CONFIRMATION
```

The EES v2 Phase 3 left-tail guardrail is a coherent candidate mechanism — the
finding is specific, the attribution is clear, and the scope is bounded. But it is
not yet deployable.

The next decision point is when the shadow monitor's 5d and 20d observation gates
are both met and the prospective IC can be compared to the PIT panel IC. If the
shadow confirms the finding (prospective IC in the same direction and order of
magnitude as PIT IC), the operator may commission an implementation spec.

Until then, **the cleanest future use of this signal, if confirmed, is a Phase 3
CT_PRIMARY_COMPLETION low-EES risk brake** — not a positive alpha selector.

---

*DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE | NO_MODEL_PROMOTION*
