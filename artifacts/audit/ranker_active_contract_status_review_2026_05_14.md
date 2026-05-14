# ranker_active_contract.py — Status Review (2026-05-14)

**Status**: MERGE GAP CONFIRMED; PRIOR DECISION (2026-05-13) STANDS
**Mode**: read-only summary; no code changes
**Prior decision**: ranker_active_contract_disposition_decision_2026_05_13.md

---

## Summary

**File Status**: The module `common/ranker_active_contract.py` (21 drift tests) exists on an unmerged hygiene branch but is NOT on production main. No runtime enforcement is active.

**Prior Decision (2026-05-13)**: Accept manual enforcement. Update the 5 stale audit documents that claim it is live enforcement.

**This memo**: Confirms the decision is still valid; documents remaining action items.

---

## Evidence

### Branch Status

| Item | Finding |
|------|---------|
| **Branch name** | `hygiene/ranker-active-contract-2026-04-30` |
| **Commit** | `e7c0ee47` |
| **Module size** | 21 drift tests; ~150 lines |
| **Main branch status** | NOT merged; not imported; not called in any production path |
| **Risk to production** | NONE — absent enforcement is low-risk because (a) the ranker is frozen (Spec 086), (b) input fields are static (financial_score, coinvest_score_z), (c) drift would show up in production monitor dashboards |

### Files Claiming Live Enforcement (5 refs)

These audit documents reference `common/ranker_active_contract.py` as live enforcement:

1. **artifacts/audit/agent_fleet_investment_logic_audit_2026_05_06.md**
   - Claims: "(none directly; enforced via `common/ranker_active_contract.py`)"
   - Context: coinvest quality filter
   - Fix: Add note that enforcement is manual (visual inspection of commit diffs)

2. **artifacts/audit/ranking_alternatives_research_2026_05_08.md**
   - Claims: "`common/ranker_active_contract.py` referenced in 5 audit documents as enforcing 21 drift tests"
   - Context: flagged as URGENT missing module
   - Fix: Update to note branch exists but unapplied; manual enforcement accepted

3. **artifacts/audit/t1_ranker_anatomy_2026_05_08.md**
   - Claims: "The file `common/ranker_active_contract.py` is referenced in at least 5 audit documents...does not exist on disk"
   - Context: urgent finding
   - Fix: Acknowledge branch exists; note decision to defer merge pending freeze lift (Spec 086)

4. **artifacts/audit/t4_risk_analysis_2026_05_08.md**
   - Claims: "referenced in 5 audit documents as enforcing 21 drift tests on active ranker fields — does not exist on disk"
   - Context: risk item 12; medium severity
   - Fix: Update to: "Module on hygiene branch unapplied; manual enforcement via audit-memo diffs"

5. **artifacts/audit/held_spec_ledger_2026_05_11.md**
   - Claims: "confirmed absent from disk"
   - Context: actionable blocker
   - Fix: Mark RESOLVED (decision made 2026-05-13); note branch exists

---

## Prior Decision (2026-05-13)

From `ranker_active_contract_disposition_decision_2026_05_13.md`:

> **Option Selected**: DEFER MERGE; ACCEPT MANUAL ENFORCEMENT  
> **Rationale**:
> - The ranker is frozen (Spec 086 v1.14.0). No new fields are expected until a Spec-driven promotion (requires Checklist v2).
> - The 2 active fields (coinvest_score_z, financial_score) are static across snapshots.
> - Any unintended field drift would be caught by production monitor dashboards (IC decomposition, hit-rate drops).
> - Merging the module now is low-ROI; it would be consumed only by new specs (future).
> - Manual enforcement: commit-level audit diffs in memo form (current pattern).
>
> **Actions**:
> 1. Update the 5 stale audit documents
> 2. Update project memory: `biotech_ranker_active_contract_2026_04_30.md` (branch exists but unapplied)
> 3. Defer module merge until: (a) next ranker retrain is approved, OR (b) a field-contract change is needed

---

## Action Item Status

| Action | Owner | Status | Deadline |
|--------|-------|--------|----------|
| **1. Update 5 audit documents** | Operator/Claude | ⏳ PENDING | By 2026-05-17 |
| **2. Update project memory** | Operator/Claude | ⏳ PENDING | By 2026-05-17 |
| **3. Monitor for field drift** | ic_health_monitor agent | ✅ ACTIVE | Daily |
| **4. Defer module merge** | Operator | ✅ DEFERRED | Until Spec-driven promotion OR ranker retrain |

---

## Risk Assessment

| Scenario | Probability | Impact | Mitigation |
|----------|------------|--------|-----------|
| **Unintended field added to ranker** | LOW (frozen ranker) | MEDIUM (silent leakage) | Code review + commit-level audit |
| **Field name changed without notice** | VERY LOW (no dev activity) | HIGH (selector/ranker path breaks) | Production run would fail loudly; caught same-day |
| **Module merge creates integration drift** | LOW | MEDIUM | Defer until next ranker decision; test at merge time |

**Overall**: MEDIUM-risk gap, low-probability harm. Manual enforcement is adequate until the ranker is unfrozen.

---

## Governance Rule (Going Forward)

**When the ranker is unfrozen** (next Spec-driven promotion):

1. Merge `hygiene/ranker-active-contract-2026-04-30`
2. Wire active-contract enforcement into `run_screen.py` pre-ranker validation
3. Add to Checklist v2 as "active contract verified"
4. Document field list in MODEL_DOCUMENTATION.md

---

## Tracking

- **Prior Decision Memo**: artifacts/audit/ranker_active_contract_disposition_decision_2026_05_13.md
- **Branch**: `hygiene/ranker-active-contract-2026-04-30`
- **Project Memory**: biotech_ranker_active_contract_2026_04_30.md (status: branch exists, unapplied, manual enforcement accepted)
