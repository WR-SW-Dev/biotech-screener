# 13F Validation → Decision Tree

**Purpose:** Once 13F validation verdict is known (expected May 20–21), this tree determines which specs unlock and in what sequence.

**Key decision point:** Cohort Jaccard ≥0.70 + all 6 gates PASS = **CLEAR**

---

## Decision Tree: Root Node

```
IF 13F validation verdict = CLEAR:
  → Path A: Quarantine Lifts → Phase 2 Step 4 Unlocks
  
ELIF 13F validation verdict = EXTEND QUARANTINE:
  → Path B: Hold Position → No Model Changes
  
ELIF 13F validation verdict = MANUAL REVIEW:
  → Path C: Investigate → Defer until Resolved
```

---

## Path A: CLEAR — Quarantine Lifts

### Status Change
```text
13F Quarantine: ACTIVE → LIFTED
Architecture Freeze: PARTIAL LIFT (ranker frozen pending Spec 096)
h20d gate: CLEARS
Phase 2 Step 4: UNBLOCKS (KG pilot eligible)
```

### Immediate Actions (do in order)

#### Step 1: Confirm all gates + dependencies
```bash
# Verify 13F validation artifacts
ls -lh artifacts/13f_validation_*.md
cat artifacts/13f_validation_*.md | grep -E "Verdict|Jaccard|Gate"
```

**Checklist:**
- [ ] Jaccard ≥ 0.70
- [ ] All 6 gates PASS
- [ ] No critical failures reported
- [ ] Validation artifact exists + readable

**Stop condition:** If any gate FAILS, stop and route to Path B (EXTEND).

---

#### Step 2: Record closure + unlock decision
```bash
git log --oneline -1  # capture git HEAD
date +%Y-%m-%d > artifacts/13f_quarantine_lift_date.txt
```

**Commit:** `13F quarantine lifted; Jaccard=X.XX; all gates PASS`

**Memory update:** Create `13f_quarantine_lifted_[DATE].md` with:
- Jaccard value
- All 6 gate results
- Date of clearance
- Unlock decision timestamp

---

### Spec Work That Now Unlocks

#### **Spec 089 KG Pilot** (Phase 2 Step 4)
**Status:** Ready to launch (pending checklist)

**Pre-launch checklist:**
- [ ] Confirm 13F gates all PASS
- [ ] Confirm freeze lift approval (governance)
- [ ] Confirm KG scope: read-only / governance-audit only
- [ ] Confirm test plan: 11 node types + 15 edge types
- [ ] Confirm stop condition: Phase 2 Step 5 gate (KG validation)
- [ ] No PR blockers (check origin/main CI)
- [ ] Commit `3185d752` (design locked) available for reference

**Launch command:**
```bash
git checkout -b phase2-step4-kg-implementation
# Follow spec 089 implementation steps 1–5
```

**Timeline:** Start immediately post-approval; 13 hrs coding; completion May 23–24.

**Gating condition:** KG validation (Phase 2 Step 5) before advancing to Spec 100.

---

#### **Spec 100 IC Tooling Correction Battery** (post-KG validation)
**Status:** Ready to run (deferred until KG validates)

**Pre-run checklist:**
- [ ] Confirm KG Phase 2 Step 5 complete
- [ ] Confirm final_score IC scope (corrected per Spec 100)
- [ ] Confirm composite_score IC marked INVALIDATED in metadata
- [ ] Confirm smoke artifact generated (read-only)

**Scope:** Finalize IC tooling + generate corrected baseline.  
**Output:** Read-only smoke artifact (deferred interpretation post-freeze).

**Timeline:** May 24–25 (post-KG validation).

---

#### **Spec 094 Selector-Only Rerun** (around May 27)
**Status:** Eligible post-KG validation + h20d decision

**Trigger conditions:**
- [ ] KG Phase 2 Step 5 PASS
- [ ] h20d = 2026-05-26 (freeze decision known)
- [ ] Spec 100 IC baseline ready
- [ ] No open Phase 2 blockers

**Scope:** Run selector-only scorecard against full universe; compare to production.

**Timeline:** May 27–28 (post-h20d).

---

#### **Spec 072 vNext Diagnostic Review** (around May 27)
**Status:** Eligible post-KG validation

**Conditions:**
- [ ] KG Phase 2 Step 5 PASS
- [ ] Clinical quality IC data ready
- [ ] D7/D8/D9 orthogonality constraints confirmed (not leaked from coinvest)

**Scope:** Review vNext diagnostic results; assess conditional clinical IC +0.20 claim.

**Timeline:** May 27–28 (concurrent with Spec 094).

---

### Sequence (If CLEAR)

```
2026-05-20:  13F validation runs → verdict known
2026-05-21:  Quarantine lift decision
2026-05-21:  Phase 2 Step 4 (KG pilot) launch approved
2026-05-21:  Spec 089 implementation starts
2026-05-23:  Spec 089 Phase 2 Step 5 validation
2026-05-24:  Spec 100 IC battery (if Step 5 PASS)
2026-05-26:  h20d freeze decision
2026-05-27:  Spec 094 + Spec 072 concurrent review
2026-05-28:  Spec 072 diagnostic decision
2026-05-29:  IC dashboard (post-Spec 100 deferred interp)
```

---

## Path B: EXTEND QUARANTINE — Validation Failed

### Status Change
```text
13F Quarantine: ACTIVE → EXTENDED
Architecture Freeze: HELD (no changes)
h20d gate: DELAYED (re-assess post-fix)
Phase 2 Step 4: BLOCKED (no KG pilot)
```

### Actions (in order)

#### Step 1: Isolate Failed Gates
```bash
cat artifacts/13f_validation_*.md | grep -E "FAIL|ERROR"
# Identify which of 6 gates failed
```

**Expected failures (examples):**
- Gate 2 (Freshness): Cache not advanced → re-run post-snapshot
- Gate 4 (Completeness): Stale positions detected → manager data gap
- Gate 5 (Stability): KS-stat > threshold → score distribution drift
- Gate 6 (Coverage): Coverage drop ≥10pp → signal loss detected

---

#### Step 2: Root Cause Analysis
For **each failed gate**, document:
1. Which managers/tickers triggered failure
2. Is it data/cache issue or modeling issue?
3. Can it be remedied by re-baseline or fix?

**Examples:**

| Failed Gate | Possible Cause | Remedy |
|-------------|----------------|--------|
| Gate 2 (Freshness) | Cache not refreshed on time | Wait for next snapshot; re-run validation |
| Gate 4 (Completeness) | Manager X missing Q1 filing | Re-run when X files OR exclude X from validation |
| Gate 5 (Stability) | inst_delta_z distribution shifted | Check manager composition; assess if cohort impact |
| Gate 6 (Coverage) | Coverage dropped 12pp | Identify lost signals; triage by stage/sector |

---

#### Step 3: Extend Window or Remediate
**Option 1: Data/Cache Issue (can re-run)**
```text
If failure = "cache not advanced" or "manager not yet filed":
  → Set re-validation date = next snapshot + 3 days
  → Rerun validation with post-date = [future date]
  → Quarantine extends until revalidation CLEAR
```

**Option 2: Modeling Issue (requires fix)**
```text
If failure = "distribution drift" or "coverage loss":
  → Isolation step: document which tickers/managers caused
  → Assess: is it cohort artifact or signal degradation?
  → Decision: extend quarantine OR waive gate if isolated to X managers
  → Document decision in 13f_failure_memo.md
```

**Option 3: Manual Review Needed**
```text
If unclear which gates pass/fail or results ambiguous:
  → Schedule 1:1 review with governance
  → Summarize ambiguous gates
  → Determine whether to extend window or remediate
```

---

#### Step 4: Announce Extension
```bash
# Create memo
touch artifacts/13f_quarantine_extended_memo_[DATE].md
# Content:
# - Which gates failed
# - Root cause(s)
# - Revalidation trigger (date / condition)
# - Expected remediation timeline
```

---

### Specs That Remain BLOCKED

```text
BLOCKED until quarantine clears:
  ✗ Spec 089 KG pilot
  ✗ Spec 100 IC battery
  ✗ Spec 094 selector-only rerun
  ✗ Spec 072 vNext diagnostic
  ✗ All selector/ranker/sizing changes
  ✗ Architecture freeze lift
  ✗ h20d model decisions

MONITOR ONLY:
  ✓ Phase 2 Step 3 watchdog (continues)
  ✓ 13F filing progress (continues)
  ✓ Forward shadows (inst_delta, cross_signal)
  ✓ Diagnostic-only specs (Spec 068, 092, etc.)
```

---

### Revalidation Timeline (If Remedied)

```
+3 days after fix:  Next production snapshot
+2 days after snap: Revalidation runs
+1 day after rerun: Verdict known
        → If CLEAR: proceed to Path A
        → If still failed: escalate to Path C
```

---

## Path C: MANUAL REVIEW — Ambiguous Verdict

### Status
```text
13F Quarantine: HELD (pending review)
Architecture Freeze: HELD
Phase 2 Step 4: BLOCKED pending manual decision
```

### Actions

#### Step 1: Summarize Ambiguous Checks
```markdown
**Ambiguous Gate: [Gate name]**
- Result: [unclear/borderline/mixed]
- Data: [conflicting signals OR missing data]
- Example: [gate 5 — KS-stat = 0.25 (threshold 0.30, borderline)]
```

#### Step 2: Review Options
1. **Waive gate:** If failure isolated to non-essential managers/tickers
2. **Extend validation window:** Re-baseline at future date
3. **Remediate:** Fix specific data/modeling issue
4. **Escalate:** Governance review + human decision

#### Step 3: Governance Sign-Off
Obtain sign-off on chosen remediation path + timeline.

---

## Summary Table

| Outcome | Quarantine | Phase 2 Step 4 | Specs Unblock | Next Gate | Timeline |
|---------|-----------|----------------|---------------|-----------|----------|
| **CLEAR** | LIFTS | UNBLOCKS | 089, 100, 094, 072 | KG validation (Phase 2 Step 5) | 5/21–5/28 |
| **EXTEND** | EXTENDS | BLOCKED | None | Revalidation | +3–7 days |
| **MANUAL** | HELD | BLOCKED | TBD | Governance review | +1–3 days |

---

## Key Stop Conditions

**Do NOT proceed to next phase if:**
- [ ] 13F validation verdict is not CLEAR
- [ ] Cohort Jaccard < 0.70
- [ ] Any of 6 gates FAIL (unless explicitly waived)
- [ ] Governance approval not recorded
- [ ] Phase 2 Step 3 or earlier blockers still open

**DO proceed only if:**
- [ ] All 6 gates PASS
- [ ] Jaccard ≥ 0.70
- [ ] Memo/artifact filed and committed
- [ ] Governance decision logged
- [ ] No Phase 2 pre-requisites blocked

---

**Document version:** 2026-05-19 (pre-verdict draft)  
**Prepared for:** Hermes / Town agent coordination  
**Next update:** When 13F validation completes
