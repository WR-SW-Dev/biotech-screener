# Manager Registry Expansion Proposal — 2026-05-26

**Proposal Status:** FORMAL GOVERNANCE REVIEW (Option B formalization)  
**Proposed Change Date:** 2026-05-22 (retroactive authorization)  
**Decision Authority:** Operator approval required  
**Severity:** CRITICAL (affects h20d gate, Spec 089, freeze lift)

---

## Executive Summary

Seven biotech-specialist institutional managers with Q1 2026 13F filings were staged for addition to the elite_core registry in commit `51a79b523` (2026-05-22, currently in git stash as WIP). This proposal formalizes that expansion for operator review before committing to main.

**Proposed change:**
- elite_core: 42 → 49 managers (+7)
- total registry: 48 → 55 managers
- total elite AUM: $131.35B → $153.83B (+$22.48B, +17.1%)
- registry version: 2.5 → 3.2
- effective date: 2026-05-22 (Q1 2026 filing window)

**Governance requirement:** All 6 13F validation gates must pass on the 55-manager cohort before h20d decision can be finalized based on this registry.

---

## Part 1: Proposed Managers (7 Total)

All 7 managers have Q1 2026 13F form filings (filed 2026-05-14 to 2026-05-15).

### 1. Frazier Life Sciences Management

**CIK:** 0001892134  
**AUM (reportable in Q1 2026):** $3.89B  
**Style:** biotech_crossover  
**Q1 2026 Status:** Filed 2026-05-15  
**Holdings (13F):** 38  
**Source:** Staged in commit 51a79b523  

**Rationale for elite_core inclusion:**
- Frazier Healthcare is established crossover fund with significant biotech allocation
- $3.89B reportable in Q1 2026 13F indicates material biotech position
- Top Q1 2026 holdings (per proposal): MIRM, NAMS, ERAS, BBIO
- Fits crossover/VC-style biotech strategy alongside existing managers (RA Capital, Bain Capital LS, Venbio)

---

### 2. Siren LLC

**CIK:** 0002005245  
**AUM (reportable in Q1 2026):** $3.61B  
**Style:** concentrated_clinical_stage  
**Q1 2026 Status:** Filed 2026-05-14  
**Holdings (13F):** 100  
**Source:** Staged in commit 51a79b523  

**Rationale for elite_core inclusion:**
- Concentrated clinical-stage biotech focus aligns with screener's clinical signal infrastructure (Spec 057, Spec 072)
- 100 holdings in Q1 2026 13F indicates broad biotech universe coverage
- $3.61B reportable AUM suggests material institutional weight
- Top holdings (per proposal): SRRK, KYMR, BNT
- Complements existing clinical-signal users (Orbimed, Perceptive, Venbio)

---

### 3. TCG Crossover Management

**CIK:** 0001839948  
**AUM (reportable in Q1 2026):** $3.5B  
**Style:** biotech_crossover  
**Q1 2026 Status:** Filed 2026-05-15  
**Holdings (13F):** 49  
**Source:** Staged in commit 51a79b523  

**Rationale for elite_core inclusion:**
- Chen Yu-led crossover fund; science-driven approach to public + private life sciences
- $3.5B reportable in Q1 2026 13F
- 49 holdings shows selective but material biotech positions
- Crossover strategy fills gap between concentrated specialists (Siren, Orbimed) and broad generalists (Renaissance, D.E. Shaw)

---

### 4. Braidwell LP

**CIK:** 0001920938  
**AUM (reportable in Q1 2026):** $3.0B  
**Style:** biotech_long_short  
**Q1 2026 Status:** Filed 2026-05-15  
**Holdings (13F):** 88  
**Source:** Staged in commit 51a79b523  

**Rationale for elite_core inclusion:**
- Alex Karnal-led long/short across biotech, pharma, medtech, diagnostics
- $3.0B reportable, 88 holdings = broad cross-sector biotech expertise
- Long/short approach provides alternative hedging perspective vs. long-only managers
- Fills gap in long/short representation (existing: Avidity Partners, few others)

---

### 5. Integral Health Asset Management

**CIK:** 0001773206  
**AUM (reportable in Q1 2026):** $1.89B  
**Style:** healthcare_long_short  
**Q1 2026 Status:** Filed 2026-05-15  
**Holdings (13F):** 86  
**Source:** Staged in commit 51a79b523  

**Rationale for elite_core inclusion:**
- Jay Rao MD/JD; absolute-return healthcare L/S across pharma, biotech, medtech, healthcare services
- Medical credential + legal background suggests clinical judgment capability
- $1.89B reportable, 86 holdings across healthcare spectrum
- Long/short absolute-return approach adds risk-management perspective

---

### 6. Affinity Asset Advisors

**CIK:** 0001773195  
**AUM (reportable in Q1 2026):** $1.7B  
**Style:** biotech_long_short  
**Q1 2026 Status:** Filed 2026-05-14  
**Holdings (13F):** 95  
**Source:** Staged in commit 51a79b523  

**Rationale for elite_core inclusion:**
- Pure biotech long/short strategy
- $1.7B reportable, 95 holdings = broad biotech selection
- Top Q1 2026 holdings (per proposal): XBI (ETF), APGE, INSM, ABVX, IBB (ETF)
- Broad holdings across market-cap spectrum

---

### 7. Paradigm Biocapital Advisors

**CIK:** 0001855655  
**AUM (reportable in Q1 2026):** $4.89B  
**Style:** biotech_crossover  
**Q1 2026 Status:** Filed 2026-05-15  
**Holdings (13F):** 35  
**Source:** Staged in commit 51a79b523  

**Rationale for elite_core inclusion:**
- Largest of 7 new managers by AUM ($4.89B reportable)
- Selective 35-holding approach (concentrated thesis-driven strategy)
- Top Q1 2026 holdings (per proposal): NUVL, RVMD, ACLX, GMAB, TARS
- High-conviction concentrated positioning fits elite_core profile

---

## Part 2: Registry Impact

### Current State (HEAD/main)

```
elite_core:    42 managers
conditional:   6 managers
total:         48 managers

version:       2.5
last_updated:  2026-04-25
total_aum_b:   $131.35B
```

### Proposed State (after expansion)

```
elite_core:    49 managers (+7 new)
conditional:   6 managers (unchanged)
total:         55 managers

version:       3.2
last_updated:  2026-05-22
total_aum_b:   $153.83B (+$22.48B, +17.1%)
```

### Coverage Impact

- New institutional AUM coverage: +$22.48B
- New Q1 2026 13F holdings: 491 positions (38+100+49+88+86+95+35)
- Expected ticker universe expansion: ~150–200 additional tickers with 13F support

---

## Part 3: Governance Risk Assessment

### Risk 1: Expansion During Active Decision Gate

**Fact:** 7 managers were staged for addition on 2026-05-22, while h20d gate evaluation was active (2026-05-22 to 2026-05-26).

**Impact:** 
- h20d decision memo (finalized 2026-05-24) used 55-manager cohort that was not yet authorized
- Memo references 49/55 filed, Jaccard 0.364 (FAIL), which differs significantly from pre-expansion validation (48 managers, Jaccard 0.875 PASS)
- This created a governance gap: the h20d conclusion depends on an expansion that was not formally approved

**Mitigation:** 
- This proposal formalizes the expansion retroactively
- 13F validation must be rerun on 55-manager cohort (all 6 gates)
- h20d decision memo must be regenerated after validation passes
- Freeze remains active until validation and regenerated h20d are complete

### Risk 2: Unvalidated Cohort State

**Fact:** The 55-manager registry was never subjected to 13F validation gate checks before being used in h20d decision.

**Impact:**
- h20d memo used Jaccard 0.364, Top-30 churn 14 enter / 14 exit, inst_delta_z 1.090
- These metrics were never validated against guard rails (completeness, freshness, producer quality, coverage, distortion, stability)
- Actual validation might fail on Top-30 stability or distortion metrics

**Mitigation:**
- Rerun full 13F validation suite on 55-manager cohort:
  - Gate 1: Filed count ≥34 (expect 49/55 = 89%)
  - Gate 2: Cohort Jaccard ≥0.70 (current: 0.364 — may still fail)
  - Gate 3: Producer freshness (cache advance from pre-refresh to post-refresh)
  - Gate 4: Position completeness (no stale Q4 positions in elite)
  - Gate 5: Top-30 stability (KS < 0.20 for coinvest_score_z; current churn: 14 enter / 14 exit)
  - Gate 6: Coverage drop < 10 percentage points
- Do not proceed with freeze lift until all 6 gates PASS on 55-manager cohort

### Risk 3: Strategic Legitimacy of Individual Managers

**Fact:** 7 managers appear in proposal with Q1 2026 filings, but their strategic fit was not documented at the time of addition.

**Impact:**
- If any manager is later found to be misaligned with institutional biotech focus, registry inclusion is questionable
- Institutional signal leakage risk if non-biotech specialists are added

**Mitigation:**
- Operator review of strategic fit for each manager (above rationale)
- Approval required before registry commit
- Annual audit of elite_core mandate adherence (recommend in future governance policy)

---

## Part 4: Validation Requirements (Before Freeze Lift)

### Step 1: Commit Registry Expansion to main

**Precondition:** Operator approves this proposal  
**Command:**
```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
git add production_data/manager_registry.json
git commit -m "feat(13f): add 7 Q1 2026 biotech specialists to elite manager registry [OPTION_B_FORMAL_EXPANSION]

Added:
- Frazier Life Sciences Management (CIK 0001892134, $3.89B)
- Siren LLC (CIK 0002005245, $3.61B)
- TCG Crossover Management (CIK 0001839948, $3.5B)
- Braidwell LP (CIK 0001920938, $3.0B)
- Integral Health Asset Management (CIK 0001773206, $1.89B)
- Affinity Asset Advisors (CIK 0001773195, $1.7B)
- Paradigm Biocapital Advisors (CIK 0001855655, $4.89B)

Registry impact:
- elite_core: 42 -> 49 managers
- total: 48 -> 55 managers
- AUM: $131.35B -> $153.83B (+17.1%)

Validation: All 6 13F gates must pass before h20d decision finalization.
Approval ID: OPTION_B_FORMAL_EXPANSION [DATE] [OPERATOR_NAME]"
```

### Step 2: Rerun 13F Validation

**Precondition:** Registry commit merged to main  
**Command:**
```bash
python3 tools/check_13f_cohort_quarantine.py \
  --pre-date 2026-05-15 \
  --post-date 2026-05-26 \
  --output artifacts/13f_validation_verdict_55manager_cohort_2026_05_26.md
```

**Expected output:** Document all 6 validation gates + pass/fail for each

**Gate pass requirements:**
- Gate 1 (filed count): ≥34 managers → expect 49/55 ✓
- Gate 2 (Jaccard): ≥0.70 → current 0.364 ✗ (may fail; this is the critical gate)
- Gate 3 (producer freshness): cache advanced → expect PASS ✓
- Gate 4 (position completeness): no stale Q4 → expect PASS ✓
- Gate 5 (Top-30 stability): KS < 0.20 (coinvest) → current 14 enter / 14 exit ✗ (may fail)
- Gate 6 (coverage): drop < 10pp → expect PASS ✓

**If any gate fails:** Document failure, mark 13F quarantine as NOT CLEARED, h20d remains DEFERRED

**If all gates pass:** Proceed to Step 3

### Step 3: Regenerate h20d Decision Memo

**Precondition:** All 6 validation gates PASS on 55-manager cohort  
**Action:** Regenerate h20d decision memo using validated 55-manager registry
**Output:** New memo at `artifacts/audit/h20d_decision_memo_55manager_validated_2026_05_26.md`

**Decision options:**
- If h20d gates all pass on validated cohort: **Path A — PROCEED** (freeze lift, Spec 089 activate)
- If h20d gates fail on validated cohort: **Path B — DEFER** (freeze remains active)

---

## Part 5: Approval Requirements

**This proposal requires approval before any registry changes.**

**Approval decision:**

```
OPERATOR APPROVAL FOR OPTION B (Manager Registry Expansion)

Manager List: Approved ☐  Rejected ☐  Conditional ☐

Strategic Rationale Review:
- Frazier Life Sciences (biotech crossover): Approved ☐
- Siren LLC (clinical stage concentrated): Approved ☐
- TCG Crossover (science-driven public/private): Approved ☐
- Braidwell LP (long/short multi-sector): Approved ☐
- Integral Health (medical/legal expertise): Approved ☐
- Affinity Asset (biotech long/short): Approved ☐
- Paradigm Biocapital (concentrated thesis): Approved ☐

All seven managers strategically legitimate for elite_core:  Yes ☐  No ☐

Authorization to proceed with:
1. Commit registry expansion to main: Approved ☐
2. Rerun 13F validation on 55-manager cohort: Approved ☐
3. Regenerate h20d decision if validation passes: Approved ☐

Approval ID: ________________
Operator Name: ________________
Date: ________________
```

---

## Part 6: Timeline and Next Steps

**If approved:**

| Date | Action | Owner |
|------|--------|-------|
| 2026-05-26 | Operator approval for Option B | OPERATOR |
| 2026-05-27 | Commit registry expansion to main | ENGINEER |
| 2026-05-27 | Rerun 13F validation on 55-manager cohort | ENGINEER |
| 2026-05-27 to 2026-05-28 | Await validation results | MONITOR |
| 2026-05-28 (if all gates PASS) | Regenerate h20d memo | ENGINEER |
| 2026-05-28 (if h20d passes) | **Lift freeze, activate Spec 089** | OPERATOR |

**If validation gates FAIL:**
- 13F quarantine: NOT CLEARED
- h20d: remains DEFERRED
- Freeze: REMAINS ACTIVE
- Next decision: Revert expansion or investigate failing gates

---

## Related Documentation

- **H20d Registry Authority Reconciliation:** `artifacts/audit/h20d_registry_authority_reconciliation_2026_05_26.md`
- **Current H20d Decision Memo (provisional):** `artifacts/audit/h20d_decision_memo_2026_05_26.md` (uses 55-mgr data pending validation)
- **13F Validation (48-manager cohort):** `artifacts/13f_validation_verdict_2026_05_19.md` (PASS, Jaccard 0.875)
- **Staged Registry Addition:** Git stash commit `51a79b523` (55-manager registry, not on main)

---

**Status:** Awaiting operator approval  
**Decision required:** Approve Option B expansion (yes/no/conditional)  
**No registry changes until approved.**
