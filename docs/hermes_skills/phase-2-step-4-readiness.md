---
name: phase-2-step-4-readiness
triggers:
  - "13F quarantine cleared"
  - "KG pilot launch pending"
  - "Spec 089 implementation ready"
  - "governance approval needed"
description: >
  Pre-launch readiness verification for Phase 2 Step 4 (KG pilot / Spec 089).
  Validates prerequisites, governance approval, test plan, scope, and stop conditions
  before implementation launch. All actions read-only and approval-gated.
---

# Phase 2 Step 4 Readiness — KG Pilot Pre-Launch Verification

## Purpose

Verify all prerequisites, governance sign-offs, and implementation readiness before launching Spec 089 KG pilot (Phase 2 Step 4). Triggers after 13F quarantine lifts (expected May 21). All checks are read-only; final approval blocks implementation start.

**Launch window:** May 21–23 (pending governance approval post-clearance)

---

## Prerequisites Checklist

### 1. 13F Quarantine Status ✅

**Must be:** LIFTED (not extended or manual review)

```bash
# Verify quarantine is lifted
grep -l "CLEAR\|quarantine lifted\|Phase 2 Step 4 unlocks" \
  artifacts/13f_validation_*.md \
  artifacts/13f_quarantine_lift_evidence.txt 2>/dev/null | head -1

# Verify gate results: all PASS
grep -E "Gate [1-6].*PASS|Jaccard.*0\.[7-9]|Overall.*CLEAR" \
  artifacts/13f_validation_*.md 2>/dev/null
```

**Requirement:** All 6 gates PASS, Jaccard ≥ 0.70, verdict = CLEAR

**Stop condition:** If EXTENDED or MANUAL, do NOT proceed. Defer Phase 2 Step 4.

---

### 2. Phase 2 Step 3 Verification ✅

**Must be:** COMPLETE (evening watchdog + preflight integration both live)

```bash
# Verify Phase 2 Step 3 artifacts
ls -lh artifacts/*phase_2_step_3* 2>/dev/null | tail -3

# Verify watchdog is operational
grep -l "evening reliability audit\|COMPLETE" \
  artifacts/*phase_2_step_3* 2>/dev/null

# Verify preflight integration is live
git log --oneline -10 | grep -i "preflight\|phase.2.step.3"
```

**Requirement:** Both components must show completion status

**Checklist items:**
- ☐ Evening reliability watchdog deployed (May 15)
- ☐ Preflight integration wired (May 15, commits f29f53ed + c5da6870)
- ☐ 5/5 preflight tests PASS
- ☐ Phase 3b artifact exists and is committed

**Stop condition:** If either component is incomplete, Phase 2 Step 4 cannot launch.

---

### 3. Spec 089 Design Lock Status ✅

**Must be:** LOCKED (schema defined, implementation plan documented, no changes pending)

```bash
# Verify design lock commit
git log --oneline | grep -E "spec.089|KG.*schema|design.locked"

# Verify spec artifact exists
ls -lh specs/changes/spec_089*.md 2>/dev/null | head -3

# Verify implementation specs (4a–4e) are documented
grep -l "spec_089.*4a\|spec_089.*4b\|spec_089.*4c\|spec_089.*4d\|spec_089.*4e" \
  specs/changes/spec_089*.md 2>/dev/null | head -1
```

**Requirement:** Design locked on commit `3185d752` (May 15)

**Scope frozen:**
- 11 node types
- 15 edge types
- 5 contradiction rules
- Zero unresolved design issues

**Stop condition:** If design is not frozen or changes are pending, escalate before launch.

---

### 4. Governance Approval ⏳

**Status:** PENDING (awaits May 21-22 decision post-clearance)

**Approval chain:**
1. 13F validation verdict CLEAR (May 20)
2. Governance decision documented (May 21)
3. Spec 089 scope reviewed (May 21)
4. KG pilot risk assessment (May 21)
5. Signature recorded (May 21-22)

**Governance decision memo required:**
```markdown
# Spec 089 KG Pilot — Governance Approval

**13F Clearance Status:** CLEAR [date]
**Governing Risk Class:** Architecture exploration (read-only, no ranking changes)
**Scope:** 11 node types + 15 edge types + 5 contradiction rules
**Timeline:** May 21 start, May 23–24 completion, Phase 2 Step 5 validation gate
**Impact:** Zero production ranking changes; foundation for future governance automation
**Approval:** [Signature/Date]
**Reservations:** [None / specific items]
```

**Stop condition:** Without explicit approval memo, implementation cannot start.

---

## Test Plan Verification

### Automated Tests

**Must have:** Full test coverage for all 5 implementation specs (4a–4e)

```bash
# Verify test file exists and is comprehensive
ls -lh tests/test_spec_089*.py 2>/dev/null
wc -l tests/test_spec_089*.py 2>/dev/null

# Run tests to verify all pass
python -m pytest tests/test_spec_089*.py -v --tb=short
```

**Expected outcomes:**
- 60+ regression tests
- All test modules pass
- Coverage: node creation, edge routing, contradiction detection

**Specification breakdown:**

| Spec | Component | Tests | Prerequisite |
|------|-----------|-------|--------------|
| **4a** | Node type definitions | 15+ | Data structures |
| **4b** | Edge routing logic | 20+ | Pairwise link rules |
| **4c** | Contradiction detection | 15+ | Rule evaluation |
| **4d** | Governance visualization | 5+ | Report generation |
| **4e** | Phase 2 Step 5 gate | 5+ | Validation criteria |

**Stop condition:** If any spec has <test count or any test fails, fix before launch.

---

### Integration Tests

**Verification points:**

```bash
# Verify Phase 2 Step 5 gate definition (stop condition)
grep -A 10 "Phase 2 Step 5\|KG validation" \
  specs/changes/spec_089*.md | head -20

# Verify no unintended ranking/selector changes
git diff origin/main -- run_screen.py selector_engine.py ranker_v2_pairwise.py \
  | grep -v "^index\|^---\|^+++" | head -10
```

**Expected:** Zero ranking changes, KG is read-only exploratory layer.

**Stop condition:** If any unintended scoring changes are present, review design before launch.

---

## Scope Confirmation

### Functional Scope

**Must confirm all are in scope:**

- ☐ Node types: 11 (manager, ticker, institution, signal, position, cohort, conflict, ruling, decision, stage, outcome)
- ☐ Edge types: 15 (owns, holds, correlates, conflicts_with, rules, governs, gates, validates, refutes, enriches, informs, contradicts, refines, depends_on, evolves)
- ☐ Contradiction rules: 5 (manager conflict, ticker stage mismatch, signal coherence, gate precedence, outcome consistency)
- ☐ Visualization: Governance diagram (node count, edge count, rule violations)
- ☐ Phase 2 Step 5 gate: Validation framework (node/edge counts, rule pass/fail, coverage)

**User signal required:** "Scope confirmed" before proceeding.

### Out-of-Scope (explicitly NOT in Phase 2 Step 4)

- ❌ Production ranking changes
- ❌ Selector/ranker retraining
- ❌ Model weight updates
- ❌ Promotion decisions
- ❌ Live deployment beyond read-only metadata
- ❌ Spec 089 Phase 2 (beyond visualization + validation gate)

**Stop condition:** If scope creep is detected, escalate for governance review.

---

## Stop Conditions (Phase 2 Step 5 Gate)

**Phase 2 Step 4 implementation succeeds if:**

✅ All 5 specs (4a–4e) complete with tests passing
✅ KG schema is built and queryable
✅ Governance visualization runs without errors
✅ Contradiction detection fires on test cases
✅ Phase 2 Step 5 validation gate is defined

**Phase 2 Step 4 FAILS if:**

❌ Implementation is incomplete (any spec 4a–4e incomplete)
❌ Tests fail (any regression test fails)
❌ KG schema is malformed or unqueryable
❌ Governance visualization cannot generate report
❌ Contradiction rules do not evaluate correctly
❌ Phase 2 Step 5 gate conditions are not met

**Action upon failure:** Document root cause, escalate to governance, defer to post-h20d (May 26+).

---

## Launch Readiness Checklist

Before implementation starts (May 21-23):

```
PREREQUISITE GATES:
  ☐ 13F quarantine is CLEARED (not extended/manual)
  ☐ All 6 13F gates documented as PASS
  ☐ Phase 2 Step 3 is COMPLETE (watchdog + preflight)
  ☐ Spec 089 design is LOCKED (commit 3185d752 or later)
  ☐ No unresolved design issues

GOVERNANCE GATES:
  ☐ Approval memo is signed
  ☐ Scope confirmed (11 nodes + 15 edges + 5 rules)
  ☐ Risk assessment completed
  ☐ Timeline alignment confirmed (May 21 start, May 23–24 finish)

TEST GATES:
  ☐ Test file exists with 60+ tests
  ☐ All tests pass locally (pytest full run)
  ☐ Integration tests pass (no ranking changes, KG layer is read-only)

DEPLOYMENT GATES:
  ☐ Branch created from latest main
  ☐ Commits squashed or organized per spec
  ☐ CI check passes (no regressions)
  ☐ Phase 2 Step 5 gate definition is included

FINAL APPROVAL:
  ☐ User approves proceeding with implementation
  ☐ All stop conditions are satisfied
  ☐ Next gate is Phase 2 Step 5 (KG validation)
```

**Do NOT proceed unless all boxes are checked.**

---

## Timeline

```
May 20:  13F validation runs → verdict CLEAR or EXTEND
May 21:  Governance approval memo signed (if CLEAR)
May 21:  Phase 2 Step 4 launch decision (final approval)
May 21:  Spec 089 implementation starts (5 specs, 13 hrs coding)
May 23:  Spec 089 implementation complete
May 24:  Phase 2 Step 5 validation runs
May 25:  Validation verdict known
May 26:  h20d freeze decision (if Phase 2 Step 5 PASS)
```

**Delay triggers:**
- If 13F EXTENDS: defer Phase 2 Step 4 until re-validation clears
- If governance approval delayed: shift timeline to May 22+ start
- If Phase 2 Step 5 FAIL: escalate to post-h20d (May 26+)

---

## Reference Documents

- **Spec 089 Phase 1.5A design:** `specs/changes/spec_089_phase_1_5a_*.md`
- **Phase 2 Step 3 completion:** `artifacts/phase_2_step_3_*_complete_*.md`
- **13F decision tree:** `artifacts/13f_decision_tree_post_clearance_2026_05_19.md`
- **Governance override policy:** `docs/ops/hermes_openclaw_routing_policy.md`

---

## Approval Format

When governance approves, expect memo like:

```
═══════════════════════════════════════════════════════════════
GOVERNANCE APPROVAL — Spec 089 KG Pilot (Phase 2 Step 4)
═══════════════════════════════════════════════════════════════

✅ 13F Quarantine: CLEARED (Jaccard 0.XX, all gates PASS)
✅ Phase 2 Step 3: COMPLETE (watchdog + preflight ready)
✅ Design Lock: CONFIRMED (commit 3185d752, zero changes)
✅ Scope: APPROVED (11 nodes, 15 edges, 5 rules, read-only)
✅ Risk: ASSESSED (architecture exploration, no ranking impact)
✅ Timeline: CONFIRMED (May 21–24, Phase 2 Step 5 gate before phase freeze)

APPROVAL: [Signed] [Date] [Authority]

CONDITION: Launch only after all checks above are confirmed.
ESCALATION: Any blocker during implementation → governance review.

═══════════════════════════════════════════════════════════════
```

**This memo must be committed before implementation starts.**

---

## Decision Tree: Launch or Defer?

```
IF 13F quarantine = CLEAR:
  AND Phase 2 Step 3 = COMPLETE:
  AND Spec 089 design = LOCKED:
  AND governance approval = SIGNED:
  THEN → PROCEED with Phase 2 Step 4
        (May 21 start, May 23–24 completion)

ELSE:
  → DEFER Phase 2 Step 4 until condition is satisfied
    (escalate to governance for ETA)
```

**Decision required from:** User (with governance signature).

---

## Pitfalls

1. **Governance approval must be explicit memo, not casual verbal OK** — "Looks good" is not approval. Require signed memo with all fields filled.

2. **Phase 2 Step 3 completion must be artifact-verified, not assumed** — Check for actual completion memos, don't proceed on "it should be done."

3. **Design lock means zero new design discussion during impl** — Bugs/ambiguities discovered during coding must be escalated, not re-designed. Phase 1 is fixed.

4. **Test plan must run and pass locally before commit** — Don't assume tests work. Run full pytest suite. Any failure blocks launch.

5. **KG layer must stay read-only** — Do not add any scoring/ranking changes "just to explore." KG is metadata only. Verify in diffs.

6. **Phase 2 Step 5 gate conditions must be crystal clear** — Avoid "we'll figure out the validation criteria during implementation." Criteria must exist before Step 4 starts.

7. **h20d (May 26) freeze decision gate is downstream** — Phase 2 Step 4 launches May 21 but its output (KG validation) feeds into freeze decision May 26. Don't skip Step 5.

---

## Stop Conditions Summary

**HARD STOPS (do not proceed):**
- 13F quarantine is not CLEAR
- Phase 2 Step 3 is not COMPLETE
- Spec 089 design is not LOCKED
- Governance approval is not signed
- Test plan does not exist or tests do not pass

**SOFT STOPS (escalate for decision):**
- Timeline is compressed (need <2 weeks to May 26 freeze)
- Phase 2 Step 5 validation gate criteria are unclear
- Risk assessment raises production impact concerns

**Escalation:** Stop and wait for explicit user approval before proceeding.
