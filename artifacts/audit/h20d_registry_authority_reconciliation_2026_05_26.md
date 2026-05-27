# h20d Registry Authority Reconciliation — 2026-05-26

**Status:** PROVISIONAL_NEEDS_RECONCILIATION  
**Issue Date:** 2026-05-26  
**Authority:** Governance / Operator Decision Required  
**Severity:** CRITICAL (affects freeze/Phase 2 Step 5 / Spec 089 decision)

---

## Executive Summary

The h20d decision memo (commit `7b3494e78`, finalized 2026-05-24) concludes with **Path B DEFERRED** based on a 55-manager institutional registry with Jaccard 0.364 (FAIL). However, verification reveals:

1. **48-manager registry is VALIDATED and CLEARED** on main (2026-05-19, Jaccard 0.875 ≥ 0.70 threshold PASS)
2. **55-manager registry used by h20d memo is NOT on main** — it exists only in git stash (commit `51a79b523`, marked WIP)
3. **h20d memo is committed to main** but its failing conclusion depends on stashed/uncommitted registry data
4. **No authorization record** for 7-manager expansion during active h20d gate evaluation window (2026-05-22 to 2026-05-26)

**Governance violation:** The h20d decision should not be treated as final until the operator reconciles which cohort controls the decision gate.

---

## Part 1: Registry State Evidence

### Validated 48-Manager Cohort (HEAD/main — Current)

**Validation run:** 2026-05-19 (post-bulk-filing)

```
elite_core:    42 managers
conditional:   6 managers
total:         48 managers

Registry version: 2.5
Last updated:     2026-04-25
Total elite AUM:  $131.35B
```

**Validation result:**
- Managers filed: 46/48 (95.8%)
- Jaccard similarity: **0.875** ✓ (threshold ≥0.70)
- Top-30 churn: 2 enter / 2 exit
- Verdict: **ALL 6 GATES PASS**
- Status: **QUARANTINE CLEARED**

**Commit ancestry:** ✓ Reachable from HEAD  
**Storage:** ✓ On origin/main (current HEAD)

---

### Unvalidated 55-Manager Cohort (Stash 51a79b523 — WIP)

**Expansion added:** 2026-05-22 (during active h20d evaluation)

```
elite_core:    49 managers (+7 new)
conditional:   6 managers
total:         55 managers

Registry version: 3.2
Last updated:     2026-05-22
Total elite AUM:  $153.83B (+$22.48B)
```

**7 managers added (no validation, no approval found):**
- Frazier Life Sciences Management ($3.89B, biotech_crossover)
- Siren LLC ($3.61B, concentrated_clinical_stage)
- TCG Crossover Management ($3.5B, biotech_crossover)
- Braidwell LP ($3.0B, biotech_long_short)
- Integral Health Asset Management ($1.89B, healthcare_long_short)
- Affinity Asset Advisors ($1.7B, biotech_long_short)
- Paradigm Biocapital Advisors ($4.89B, biotech_crossover)

**Commit status:** `51a79b523 (refs/stash)` — WIP, NOT on any branch  
**Ancestry:** ✗ NOT reachable from HEAD (exit code 1 on `merge-base --is-ancestor`)  
**Storage:** ✗ In git stash only (not committed to main)  
**Validation:** None — never validated against guard rails

---

### h20d Decision Memo (Commit 7b3494e78 — On main)

**Committed:** 2026-05-24 13:40:19 ET  
**Message:** "docs(governance): finalize h20d decision memo — Path B DEFERRED, Jaccard 0.364 not cleared"

**References in memo:**
- Manager registry size: 49/55 filed
- Jaccard similarity: **0.364** ✗ (well below threshold ≥0.70)
- Top-30 churn: 14 enter / 14 exit (much higher than 48-manager cohort)
- inst_delta_z mean abs delta: 1.090 (distortion elevated)
- Verdict: **Path B DEFERRED** (h20d not cleared)
- Status: Phase 2 Step 5 BLOCKED, Spec 089 ADVISORY ONLY, alpha freeze ACTIVE

**Commit ancestry:** ✓ Reachable from HEAD  
**Storage:** ✓ On origin/main (current HEAD)  
**Registry basis:** Uses 55-manager data (NOT on main)

---

## Part 2: Timeline and Authority Gap

| Date | Event | Registry | Status | Authority |
|------|-------|----------|--------|-----------|
| 2026-05-19 | 13F validation gate run | 48 mgrs | Jaccard 0.875 ✓ PASS | Validated |
| 2026-05-22 | 7 managers added via WIP stash | → 55 mgrs | Unvalidated | **NO RECORD** |
| 2026-05-24 13:40 | h20d memo committed to main | Uses 55 mgrs | Jaccard 0.364 ✗ FAIL | Depends on stash |
| 2026-05-26 | h20d decision finalized | References 55 mgrs | DEFERRED | Provisional |

**Authority questions:**
1. Who authorized 7-manager expansion on 2026-05-22?
   - No spec found
   - No PR found
   - No approval memo found
   - Commit message: "WIP on fix/ops-ci-001-kg-lint-cleanup-2026-05-22" (does not justify registry expansion)

2. Why was expansion made during active h20d gate window (2026-05-22 to 2026-05-26)?
   - Timing suggests opportunistic addition during bulk filing window
   - Not a planned gate re-design documented in advance

3. Was 55-manager cohort validated before h20d decision?
   - NO — no validation gate run for 55-manager cohort
   - Only 48-manager cohort was validated (2026-05-19)

---

## Part 3: Governance Violation Summary

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Validated cohort decision? | ✅ YES | 48-manager cohort validated 2026-05-19, Jaccard 0.875 CLEARED |
| Unvalidated cohort used for h20d? | ✅ YES | 55-manager cohort (memo references 49/55 filed, Jaccard 0.364) never validated |
| Unvalidated cohort on main? | ❌ NO | Commit 51a79b523 is in stash only, not on any branch |
| h20d memo depends on stashed data? | ✅ YES | h20d memo uses 55-mgr Jaccard 0.364 which is only in stash |
| Authorization for expansion during gate? | ❌ NO | No spec, PR, approval, or formal decision found |
| Freeze lifted based on invalid data? | ❌ NO | Alpha freeze remains active (provisional) |

**Conclusion:** The h20d decision should not be treated as final. It was made on a registry state that:
1. Was not validated
2. Is not on the committed main branch
3. Was added without recorded authorization during an active decision gate
4. Supersedes the validated 48-manager cohort without formal reconciliation

---

## Part 4: Current Enforced Posture (Unchanged)

**Locks (remain in place until reconciliation):**
- ✓ Alpha freeze: ACTIVE
- ✓ Ranker freeze: ACTIVE  
- ✓ Selector freeze: ACTIVE
- ✓ Sizing freeze: ACTIVE
- ✓ Spec 089 KG enforcement: ADVISORY ONLY (no enforcement)
- ✓ Phase 2 Step 5 implementation: BLOCKED
- ✓ yfinance incident: ACTIVE (81+ hours, escalation at 2026-05-27 14:00 ET)

**No changes authorized.** Governance freeze remains active pending reconciliation.

---

## Part 5: Operator Decision Options

Choose exactly one:

### **Option A: Use Validated 48-Manager Cohort**

**Outcome:**
- 13F quarantine: **CLEARED** (Jaccard 0.875, validated 2026-05-19)
- h20d decision: **CLEARED** (condition-based gate satisfied)
- Phase 2 Step 5: **UNBLOCKED** (implement KG enforcement)
- Spec 089: **ACTIVATE ENFORCEMENT** (advisory → active)
- Alpha freeze: **LIFT** (ranker research unblocked)
- Rationale: Use only committed, validated data on main

**Risk:** Ignores 7 legitimate biotech specialists added during Q1 2026 filing season. They are filing their Q1 2026 13F forms (7/7 filed by 2026-05-15/18), so exclusion may be under-representing institutional biotech positioning.

**Authority required:** Operator approval to revert to 48-manager baseline and formally reject 55-manager expansion.

---

### **Option B: Formalize 55-Manager Expansion** ⭐ RECOMMENDED

**Sequence (no implementation without approval):**

1. **Commit the 55-manager registry addition**
   - Move commit `51a79b523` from stash to main
   - Or create new commit formalizing the 7-manager addition
   - Commit message: "feat(13f): add 7 Q1 2026 biotech specialists to elite manager registry; formal expansion authorized [OPERATOR_APPROVAL_ID]"

2. **Rerun 13F validation from scratch**
   - Use the committed 55-manager registry
   - Run: `tools/check_13f_cohort_quarantine.py --pre-date 2026-05-15 --post-date 2026-05-26 --registry-version 3.2`
   - Check all 6 validation gates (completeness, freshness, stability, coverage, distortion, top-30 churn)
   - If gates pass: quarantine cleared
   - If gates fail: document failure reason and defer h20d

3. **Regenerate h20d decision memo**
   - If validation passes: rerun h20d evaluation on validated 55-manager cohort
   - If Jaccard ≥ 0.70: h20d clears, freeze lifts
   - If Jaccard < 0.70: h20d defers, freeze remains active

**Outcome (if validation + h20d both pass):**
- 13F quarantine: **CLEARED** (55-mgr validated cohort)
- h20d decision: **CLEARED** (condition-based gates satisfied)
- Phase 2 Step 5: **UNBLOCKED**
- Spec 089: **ACTIVATE ENFORCEMENT**
- Alpha freeze: **LIFT**

**Risk:** If validation gates fail on 55-manager cohort, h20d remains deferred longer. The 7 new managers introduce 14 entering / 14 leaving top-30 churn, which may fail the Top-30 stability gate.

**Authority required:** Operator approval + formal documentation of why 7 managers are strategically legitimate additions to the elite core during active decision gate.

---

### **Option C: Keep h20d Deferred Pending Reconciliation**

**Outcome:**
- 13F quarantine: **UNRESOLVED** (48-mgr cleared but 55-mgr unvalidated)
- h20d decision: **DEFERRED** (waiting for formal cohort decision)
- Phase 2 Step 5: **BLOCKED** (no implementation)
- Spec 089: **ADVISORY ONLY** (no enforcement activation)
- Alpha freeze: **ACTIVE** (remains locked)
- yfinance recovery: Continue monitoring

**Timeline:** Delay further h20d/Phase 2 work until operator resolves cohort authority.

**Authority required:** None — maintains status quo until operator chooses A or B.

---

## Part 6: Recommended Path Forward

**Governance recommendation: Option B** (if 7 managers are strategically legitimate)

**Rationale:**
1. All 7 managers have legitimate Q1 2026 13F filings (source of truth)
2. They collectively represent +$22.48B institutional AUM in biotech/healthcare
3. Adding them during bulk filing window suggests intentional coverage expansion for Q1 2026
4. Proper authorization and validation will establish governance precedent for future registry changes

**If Option B is chosen, sequence is:**
1. Operator approves 55-manager expansion and provides authorization ID
2. Commit the registry expansion to main with formal message
3. Rerun 13F validation on 55-manager cohort (all 6 gates)
4. If validation passes: regenerate h20d decision on validated cohort
5. If h20d passes: lift freeze, unblock Phase 2 Step 5, activate Spec 089

**If Option A is chosen:**
1. Operator rejects 55-manager expansion
2. Revert registry to 48-manager baseline on main
3. Mark h20d decision as CLEARED on validated 48-manager cohort
4. Lift freeze, unblock Phase 2 Step 5, activate Spec 089

---

## Related Documentation

- **13F Validation Evidence:** `artifacts/13f_validation_verdict_2026_05_19.md` (48-mgr cohort, all gates PASS)
- **h20d Decision Memo:** `artifacts/audit/h20d_decision_memo_2026_05_26.md` (uses 55-mgr data, not finalized)
- **Git commits:**
  - `7b3494e78` — h20d memo (on main, uses 55-mgr data)
  - `51a79b523` — 55-mgr registry (in stash, not on main)

---

**Status:** Awaiting operator decision (A / B / C)  
**Governance state:** PROVISIONAL_NEEDS_RECONCILIATION  
**Freeze:** ACTIVE (all restrictions remain until reconciliation)  
**Next action:** Operator selects reconciliation path and provides authorization
