# Phase 3 Conditional Roadmap
## Decision Tree for Time-Gated Governance Gates

**Created:** 2026-06-03  
**Status:** LOCKED (decision gates fixed)  
**Operator Authority:** user/operator

---

## Executive Summary

Phase 2 is in a **waiting state**: all governance work is time-gated (Path C / IC observable ~2026-06-17; shadow attribution validation ~2026-06-29). This roadmap defines the conditional paths that Phase 3 will take based on gate outcomes.

**No decision is made yet.** This is the decision framework for operator review when each gate arrives.

---

## Gate 1: Path C / IC Observability (~2026-06-17)

**Current State:** `IC_UNOBSERVABLE_EXPECTED` (cold-start, 2-day elapsed)

**Expected Resolution Date:** ~2026-06-17 (first 20-day forward-return horizons fill PIT cache)

### Condition A: IC Becomes Observable AND mean_ic ≥ 0.0200

**Verdict:** Path C valid; hypothesis confirmed.

**Phase 3 Outcome:**
- Close Path C window (governance override ends)
- Evaluate whether Phase 2 decision portfolio remains canonical or reverts to Phase 1b baseline
- **Next step:** Define governance post-freeze (Path A permanent gates design)

**Implementation Authority:** Operator review required; no automatic state change

**Timeline:** Decision required by ~2026-06-17

---

### Condition B: IC Becomes Observable AND mean_ic < 0.0200

**Verdict:** Path C failed; institutional signal insufficient.

**Phase 3 Outcome:**
- Revert portfolio to HOLD (close Phase 2)
- Activate Path A durable gates design (post-freeze, permanent replacement for Path C override)
- Investigate why forward-eval IC failed (signal quality, model drift, sampling error)

**Implementation Authority:** Automatic revert + escalation to operator for Path A design approval

**Timeline:** Immediate upon IC print; Path A design work begins

---

### Condition C: IC Remains Unobservable Beyond Extended Window (After ~2026-06-20)

**Verdict:** Cold-start failure; cannot evaluate Path C.

**Phase 3 Outcome:**
- **Do not silently extend.** Escalate operator review.
- Options:
  - Revert to HOLD pending PIT cache investigation
  - Extend once more with explicit justification
  - Activate emergency Path A (durable gates without IC validation)

**Implementation Authority:** Operator decision required; no automatic extension

**Timeline:** Escalation required if IC unobservable after 2026-06-20

---

## Gate 2: Shadow Attribution Validation (~2026-06-29)

**Current State:** 0 post-lock rebalance cycles; baseline established (pre-lock data through 2026-05-29)

**Expected Resolution Date:** ~2026-06-29 (after 2+ rebalance cycles post-lock)

### Condition A: Repeatable Pattern Confirmed (2+ Cycles)

**Pattern:** Bucket composition mismatch or catalyst-window drift persists across rebalance cycles.

**Verdict:** ERAS was not one-name noise; repeatable policy constraint issue.

**Phase 3 Outcome:**
- Escalate to policy review
- Investigate shadow portfolio policy constraints (why 0-30d overweighted, 91-180d underweighted)
- Propose policy correction for next governance cycle (post-freeze)
- **Impact on decision portfolio:** None immediate; Phase 2 decision remains locked

**Implementation Authority:** Policy review escalation; governance decision required

**Timeline:** Decision by ~2026-06-29

---

### Condition B: Pattern Unconfirmed / Insufficient Data

**Outcome:** ERAS exclusion appears idiosyncratic; bucket mismatch due to random allocation noise.

**Verdict:** Phase 1b hypothesis (one-name noise + random drift) remains valid.

**Phase 3 Outcome:**
- Continue observing shadow portfolio performance
- No policy change required
- Close Phase 2 shadow attribution validation task

**Implementation Authority:** Operator acknowledgment; routine close

**Timeline:** Decision by ~2026-06-29

---

### Condition C: Data Still Insufficient (< 2 Rebalance Cycles by 2026-06-29)

**Outcome:** Not enough rebalance windows to validate or refute hypothesis.

**Verdict:** Extend observation window to ~2026-07-15 (3 cycles minimum).

**Phase 3 Outcome:**
- Continue Phase 2 shadow validation task into July
- No Phase 3 action pending additional data

**Implementation Authority:** Automatic extension; no escalation required

**Timeline:** Re-evaluate ~2026-07-15

---

## Combined Gate Outcomes & Phase 3 Scenarios

### Scenario 1: Path C PASS + Shadow Pattern UNCONFIRMED (Most Likely)

**Phase 3 Work:**
- Close Path C (validated via IC)
- Continue shadow observation (no policy action)
- Define Path A durable gates design
- Resume normal governance cycle post-freeze

**Timeline:** Phase 3 begins ~2026-06-17; path A design starts immediately

---

### Scenario 2: Path C FAIL + Any Shadow Outcome

**Phase 3 Work:**
- Revert to HOLD immediately
- Investigate forward-eval IC failure
- Activate Path A emergency gates (durable fallback)
- Post-freeze: design permanent gates framework

**Timeline:** Automatic revert; escalation immediately upon IC print

---

### Scenario 3: Path C UNOBSERVABLE + Shadow Pattern CONFIRMED

**Phase 3 Work:**
- Escalate Path C cold-start failure (operator review)
- Escalate shadow policy mismatch (operator review)
- Two independent governance failures; may require coordinated remediation

**Timeline:** Escalation by ~2026-06-20 and ~2026-06-29 respectively

---

### Scenario 4: Path C PASS + Shadow Pattern CONFIRMED

**Phase 3 Work:**
- Close Path C (validated)
- Escalate shadow policy mismatch (governance review)
- Path A design defines how to incorporate shadow feedback into permanent gates

**Timeline:** Path C closes ~2026-06-17; shadow escalation ~2026-06-29; Path A design ongoing

---

## Hard Constraints (All Scenarios)

**Cannot proceed to next governance cycle until:**
1. ✓ Path C decision is made (pass/fail/escalate)
2. ✓ Shadow attribution validation is complete (2+ cycles or explicit data insufficiency)
3. ✓ All hard-exit conditions are reviewed (Jaccard, drawdown, concentration)

**No automatic state changes:**
- Silent extension is prohibited
- Operator decision required at each gate
- Escalation required if conditions become ambiguous

**Frozen scope applies through all scenarios:**
- No ranker/selector/scoring changes unless explicitly authorized post-freeze
- No portfolio construction changes unless explicitly authorized
- Phase 1b safety primitives remain operational (non-blocking observability only)

---

## Implementation Checklist

### By ~2026-06-17 (Path C Gate)

- [ ] Operator receives IC observability alert
- [ ] mean_ic value is confirmed
- [ ] Operator selects Scenario 1, 2, 3, or 4
- [ ] Decision is logged in governance ledger
- [ ] Phase 3 work begins (path-specific)

### By ~2026-06-29 (Shadow Attribution Gate)

- [ ] Operator receives shadow rebalance cycle count
- [ ] Validation matrix is updated with new data
- [ ] Operator confirms pattern is repeatable, insufficient, or confirmed
- [ ] Decision is logged in governance ledger
- [ ] If escalation: policy review initiated

### Post-Decision (Phase 3 Execution)

- [ ] Path A design work starts (if Path C fails or gate unclear)
- [ ] Policy review escalation starts (if shadow pattern confirmed)
- [ ] Freeze end-of-life planning begins (Path A readiness target)

---

## Related Documents

- `PATH_C_WINDOW_CLOSE_DECISION_2026_06_03.md` — Current Path C decision memo
- `PATH_C_DECISION_LOG_2026_06_03.md` — Current operator decision (EXTEND to ~2026-06-17)
- `shadow_portfolio_attribution_2026_06_02.md` — Phase 1b hypothesis document (pending validation)
- `forward_eval_ic_baseline.json` — IC observability baseline

---

**This roadmap is locked. Operator approval required to deviate.**

**Next: Phase 3 conditional paths are defined. Awaiting ~2026-06-17 (Path C / IC gate).**
