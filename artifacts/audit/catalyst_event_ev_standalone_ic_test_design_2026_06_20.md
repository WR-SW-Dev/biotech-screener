# Catalyst / Event-EV Standalone IC Test — Design

**Date:** 2026-06-20  
**Status:** DESIGN COMPLETE — NO IMPLEMENTATION  
**Purpose:** Specify a read-only test of whether catalyst signal is *predictive* (not just orthogonal), runnable July 8 alongside the DEM IC remeasurement

---

## Status

```
CATALYST_EVENT_EV_STANDALONE_IC_TEST_DESIGN
DESIGN_ONLY
NO_IMPLEMENTATION
NO_MODEL_CHANGE
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED
```

---

## Motivation

Four prior audits converge on one Phase 3 question:

```
DEM fails IC likely because it re-ranks coinvest_score_z — the same institutional
axis that already selected the cohort (circular). The fix is a VALIDATED ORTHOGONAL
PREDICTIVE feature.

Catalyst audit found: catalyst IS orthogonal (+0.249 universe, -0.107 within cohort).
BUT orthogonality ≠ alpha: financial_score is also orthogonal (+0.086) and DEM still
fails IC. So catalyst's PREDICTIVE power (forward-return IC) must be measured before
any Phase 3 inclusion — using the same Spec 100 gate DEM is stuck on.
```

This design specifies that measurement. It is the gate that prevents Phase 3 from repeating the DEM mistake of shipping an unvalidated feature.

---

## Candidate Signals Assessed

| Signal | Coverage (eligible/cohort) | Testable? | Role |
|--------|---------------------------|-----------|------|
| **catalyst_score** | 207/207, 60/60 (all snapshots) | ✅ YES | **PRIMARY** candidate |
| **catalyst_decay_w** | 207/207, 60/60 (all snapshots) | ✅ YES | **SECONDARY** (timing-decayed variant) |
| **event_ev_score** | **0/207 — EMPTY in ALL snapshots** | ❌ NO | Blocked — needs backfill investigation |
| **event_ev_score_z** | **0/207 — EMPTY in ALL snapshots** | ❌ NO | Blocked — needs backfill investigation |

**Critical pre-finding:** `event_ev_score` and `event_ev_score_z` are systematically unpopulated across every snapshot checked (2026-04-15 through 2026-06-18). They are schema fields with no data. **They cannot be IC-tested until the upstream that should populate them is investigated and (if intended) backfilled.** This is itself a finding worth a separate diagnostic — an event-EV (expected-value) signal that is wired into the schema but never computed.

**Net testable set for July 8:** `catalyst_score` (primary), `catalyst_decay_w` (secondary).

---

## Existing Tooling Assessment

`tools/measure_final_score_ic_spec100.py` (read-only, created 2026-06-20):
- Computes Spearman IC + t-stat on a score field vs forward returns
- Scopes to cohort (actionable_rank ≤ 60); also has a full-universe composite branch
- Has `--start-date`, `--end-date`, `--snapshot-dir`, `--output-dir`, `--dry-run`, horizon support
- **Hardcodes the score field as `final_score`** (lines 214–222) — no `--score-field` parameter

**Gap:** The tool cannot currently test `catalyst_score` without one of:

```
Option A (minimal, preferred): Add a --score-field argument that defaults to
  "final_score" (preserving current behavior) and selects the column to correlate.
  ~5-line read-only change. REQUIRES SEPARATE APPROVAL before implementation.

Option B: A read-only sibling tool (measure_signal_ic.py) parameterized by score field
  and scope. More isolation; no risk to the existing DEM gate tool.
```

**This design does NOT implement either.** It specifies exactly what to build when approved.

---

## Test Design

### Signals under test

```
PRIMARY:   catalyst_score
SECONDARY: catalyst_decay_w
BASELINE:  coinvest_score_z, financial_score, final_score  (for relative interpretation)
```

Testing the existing features as baselines is essential: catalyst's IC is only meaningful **relative** to what the ranker already has. If coinvest_score_z and financial_score both show ~0 standalone IC and catalyst also shows ~0, the problem is universe-wide unpredictability, not a missing feature. If catalyst's IC is materially higher, it is a genuine Phase 3 candidate.

### Scope (two universes)

```
SCOPE 1 — Within-cohort (actionable_rank ≤ 60):
  Answers the DIRECT Phase 3 question: "would catalyst help RE-RANK the cohort?"
  This is where a new ranker feature would operate.

SCOPE 2 — Full eligible universe (eligible=1, ~207):
  Answers "is catalyst predictive at all, pre-selection?"
  Guards against the circularity trap — catalyst measured on the full universe is not
  conditioned on the institutional selection that compresses the cohort.
```

Report both. Scope 2 is the cleaner test of raw predictive power; Scope 1 is the operational test.

### Horizons

```
T+5, T+10, T+20 (primary, matches Spec 100), T+60 (secondary)
```

**Timing-matching rationale:** catalyst_score includes far-dated catalysts (RVMD at 286 days). A T+20 forward return cannot capture a catalyst 286 days out, so a blended catalyst_score may show muted IC at short horizons. Therefore:

```
- Test all horizons; expect catalyst IC to rise with horizon IF predictive.
- T+60 is the most informative single horizon for catalyst realization.
- catalyst_decay_w (timing-weighted) may show stronger short-horizon IC than raw
  catalyst_score, because it already downweights far events.
```

### Timing-segmented sub-test (key design element)

Run catalyst_score IC separately on:

```
- catalyst_in_window = 1 subset (near-term catalysts) at T+5/T+10/T+20
- full set at T+60
```

A near-term catalyst's value should show up in near-term returns; a far catalyst's should not until its horizon. Segmenting avoids diluting a real near-term signal with far-dated noise. **If catalyst_in_window names show meaningful T+10/T+20 IC while the blended score does not, that is the actionable finding** — it would argue for a *windowed* catalyst feature, not a raw one.

### Method

```
- Spearman IC (rank correlation) between signal and forward return, per snapshot date
- Forward return = (close_price[t+h] − close_price[t]) / close_price[t]
- Aggregate: mean IC across snapshot dates, std, t-stat = mean / (std/√n_dates)
- Sign convention: higher catalyst_score → higher forward return ⇒ positive IC expected
- Minimum 10 snapshot-date observations per horizon for statistical validity
- Reuse the SAME PIT-safe forward-return logic as the DEM gate tool (no lookahead)
```

### Data window

```
PRIMARY (immediate, full statistical power):
  Historical rolling window 2026-02 through 2026-05 (Phase B showed 100+ pairs available)
  — can run as soon as tooling is approved; does not require waiting for July 8.

SECONDARY (real-time confirmation):
  2026-06-18 base date at T+20, observable 2026-07-08 — runs alongside DEM remeasurement.
```

**Note:** unlike DEM (which needs the July 8 forward data for its primary gate), the catalyst IC test can run on historical windows *immediately* once tooling is approved — there is no reason to wait for July 8 for the historical read. July 8 only adds the real-time confirmation point.

---

## Decision Thresholds

Apply the same Spec 100 gate as DEM, plus a relative-improvement test:

```
PER-SIGNAL GATE:
  catalyst_score mean IC ≥ 0.0200 at primary horizon (T+20 or best-matched horizon)
  with t-stat supporting significance and ≥10 observations.

RELATIVE TEST (the one that matters for Phase 3):
  catalyst_score IC must materially EXCEED the existing features' standalone IC.
  If coinvest_score_z ≈ financial_score ≈ catalyst ≈ 0, no feature is predictive
  → Phase 3 needs a different signal class entirely, not catalyst.
```

### Outcome classification

```
CATALYST_IC_PREDICTIVE_CANDIDATE:
  catalyst IC ≥ 0.0200 AND meaningfully > existing-feature IC
  → strong Phase 3 candidate; design windowed/decayed variant

CATALYST_IC_WEAK_NOT_WORTH_INCLUSION:
  catalyst IC < 0.0200 or ≈ existing features
  → catalyst is orthogonal but not predictive; do NOT add to ranker

CATALYST_IC_WINDOWED_ONLY:
  blended catalyst flat BUT catalyst_in_window subset IC ≥ 0.0200
  → consider a windowed catalyst feature, not raw catalyst_score

CATALYST_IC_UNOBSERVABLE:
  insufficient forward data / tooling gap
  → retry; do not infer
```

---

## July 8 Execution Plan

```
PRECONDITION (one-time, requires approval):
  Approve Option A (add --score-field to existing tool) OR Option B (sibling tool).
  Until then, this test cannot run. NO TOOL CHANGE IS MADE BY THIS DESIGN.

STEP 1 (can run immediately after tooling approval — does NOT need July 8):
  Run historical IC (2026-02 → 2026-05) for:
    catalyst_score, catalyst_decay_w, coinvest_score_z, financial_score
    × scopes {cohort, full-universe} × horizons {T+5,T+10,T+20,T+60}
    + catalyst_in_window-segmented sub-test
  This gives full-statistical-power answer on catalyst predictiveness now.

STEP 2 (July 8, alongside DEM remeasurement):
  Run real-time confirmation on 2026-06-18 base date, T+20, when forward data exists.

STEP 3:
  Classify per outcomes above. Archive to artifacts/audit/.
  Feed result into Phase 3 design decision (which orthogonal signal, if any, is predictive).

HARD RULE:
  This test informs Phase 3 design. It does NOT authorize adding catalyst to the ranker.
  Inclusion requires operator approval + the same governance gates as any DEM change.
```

---

## What This Design Does NOT Do

```
❌ Does not create or modify any tool
❌ Does not run any new IC computation
❌ Does not change catalyst policy, weights, buckets, or formulas
❌ Does not change the ranker, selector, or final_score
❌ Does not authorize Phase 3 feature inclusion
✅ Creates only this local design artifact
```

---

## Open Items Surfaced

1. **event_ev_score is empty everywhere** — a schema field for an event expected-value signal that is never populated. Worth a separate diagnostic: is the upstream broken, deferred, or intentionally disabled? If event-EV is meant to be a return-calibrated signal, it could be a stronger Phase 3 candidate than catalyst_score — but only if populated. **Recommend a short read-only "event_ev population" diagnostic before relying on it.**

2. **catalyst_score blends timing** — far-dated catalysts dilute short-horizon IC. The windowed/decayed variants (catalyst_in_window subset, catalyst_decay_w) are the more promising forms and are built into this test plan.

---

## Recommended Next Step

```
PAUSE before implementation (per directive).

When ready to proceed, the decision point is:
  - Approve tooling Option A or B (read-only IC measurement extension), THEN
  - Run STEP 1 historical IC immediately (no need to wait for July 8), THEN
  - Confirm at July 8 (STEP 2).

Optionally first: a 1-snapshot read-only "event_ev population" diagnostic to decide
whether event_ev_score is worth resurrecting as a candidate.
```

---

## Governance Boundary

✅ **NO VIOLATIONS**

- ✅ Design-only; no tool created or modified
- ✅ No IC computation run (only read-only coverage inspection of existing fields)
- ✅ No catalyst/selector/ranker/model changes
- ✅ No production outputs modified
- ✅ No commits

---

## Files Modified

**None (production files).**

This design added only: `artifacts/audit/catalyst_event_ev_standalone_ic_test_design_2026_06_20.md` (untracked).

---

## Summary

| Element | Decision |
|---------|----------|
| **Primary candidate** | catalyst_score (full coverage) |
| **Secondary candidate** | catalyst_decay_w (timing-decayed) |
| **Blocked candidate** | event_ev_score/_z (empty in all snapshots) |
| **Tooling** | Existing tool hardcodes final_score; needs --score-field (Option A) or sibling (Option B) — NOT built |
| **Scopes** | Within-cohort (≤60) + full eligible universe (207) |
| **Horizons** | T+5/T+10/T+20/T+60 + in-window segmentation |
| **Baselines** | coinvest_score_z, financial_score (relative test) |
| **Gate** | IC ≥ 0.0200 AND > existing-feature IC |
| **Timing** | Historical window runs immediately on approval; July 8 confirms |
| **Authorization** | Test informs Phase 3; does NOT authorize inclusion |

**Bottom line:** The test is fully specified and ready to execute the moment read-only IC tooling is approved. catalyst_score and catalyst_decay_w are the testable candidates; event_ev_score is blocked (empty). The relative test (catalyst IC vs existing-feature IC) is the decisive Phase 3 input.

---

## References

- **Catalyst audit:** catalyst orthogonal (+0.249 / −0.107) but flat as current discriminator
- **Institutional audit:** institutional circularity; need orthogonal predictive feature
- **Phase B:** DEM IC fails; orthogonal financial_score insufficient (orthogonality ≠ alpha)
- **July 8 runbook:** docs/dem_ranker_july8_ic_remeasurement_runbook.md (this test runs alongside)
- **Existing tool:** tools/measure_final_score_ic_spec100.py (hardcodes final_score)
