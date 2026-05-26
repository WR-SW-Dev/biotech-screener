---
name: governance-spec-enforcement
triggers:
  - "spec status audit"
  - "architecture freeze verification"
  - "promotion gate check"
  - "weekly governance audit"
description: >
  Verify architecture freeze, blocked specs, Checklist v2 enforcement,
  IC evidence hold, and promotion gates are correctly applied.
  Audit-only by default. Reports deviations and escalation recommendations.
---

# Governance Spec Enforcement — Weekly Audit

## Purpose

Verify that governance gates, architecture freeze, blocked specs, and promotion rules are correctly enforced across the codebase. All checks are read-only and report-only. No code changes made by this skill.

**Audit scope:**
- Architecture freeze status (active/lifted)
- Blocked specs (089, 100, 094, 072) — verify no implementation
- Checklist v2 promotion gate enforcement
- IC evidence hold (composite_score marked invalid)
- Model weight capping (governance overrides)
- Operational rules (no unilateral ranking changes)

**Schedule:** Weekly audit (Monday/Thursday post-h20d decision, or ad-hoc)

---

## 1. Architecture Freeze Status

### Expected State: LIFTED (as of 2026-05-26, h20d override authorization)

Architecture freeze was **LIFTED on 2026-05-26** via h20d override authorization (OPTION_B_OVERRIDE_2026_05_26). Selector, ranker, sizing, and core scoring changes now authorized (subject to governance gates).

**Verify freeze lift decision:**

```bash
# Check for h20d override authorization
ls -lh artifacts/audit/h20d_override_authorization_*.md 2>/dev/null | tail -1

# Verify freeze lift documented
grep -l "LIFTED\|freeze.*lift" artifacts/audit/h20d_override_authorization_*.md 2>/dev/null
```

**Checklist:**
- ☑ Original freeze initiated: 2026-04-19 (audit/attribution phase)
- ☑ Freeze reason: "Audit live A4 + 2-feat ranker; attribution only"
- ☑ **Current status: LIFTED (2026-05-26, h20d override)**
- ☑ Lift authorization: OPTION_B_OVERRIDE_2026_05_26 (55-manager registry override)
- ☑ Phase 2 Step 5: UNBLOCKED
- ☑ Spec 089: ACTIVATED (KG enforcement live)

**Stop condition:** If freeze status reverts to ACTIVE, escalation required (only operator can re-activate).

---

## 2. Spec Status (updated 2026-05-26, h20d override)

### Spec 089: ACTIVATED (was BLOCKED, now live)

| Spec | Status | Reason | Verification |
|------|--------|--------|---|
| **089** | ✅ **ACTIVATED** | h20d override (2026-05-26) — Phase 2 Step 5 LIVE | KG enforcement in preflight |
| **100** | BLOCKED | Deferred interpretation post-freeze | Smoke artifact only, read-only |
| **094** | BLOCKED | h20d decision + 13F refresh | No impl code |
| **072** | BLOCKED | h20d decision + 13F refresh | Diagnostic only |

**Spec 089 Verification (ACTIVATED):**

```bash
# Verify KG deployment live
ls -lh tools/build_hermes_knowledge_layer.py tools/query_knowledge_graph.py 2>/dev/null

# Check preflight activation
grep -n "spec_089_active\|Spec 089.*ACTIVE" tools/agent_preflight.py 2>/dev/null | head -3

# Verify h20d override authorization
ls -lh artifacts/audit/h20d_override_authorization_*.md 2>/dev/null

# Confirm Phase 2 Step 5 deployment
grep -l "Phase 2 Step 5.*LIVE\|KG.*deployment.*complete" \
  artifacts/audit/*.md 2>/dev/null | head -1
```

**Expected outcomes (Spec 089):**
- ✅ KG builder tools exist and are committed
- ✅ Preflight recognizes h20d override (spec_089_active flag set)
- ✅ h20d override authorization artifact present
- ✅ Phase 2 Step 5 deployment documented
- ✅ Weekly validation monitoring scheduled (starts 2026-05-31)

**Spec 100/094/072 Verification (still BLOCKED):**

```bash
# Verify no implementation of blocked specs
git log --oneline --grep="spec.100.*implement\|spec.094\|spec.072" 2>/dev/null | head -5
git diff origin/main -- ranker_v2_pairwise.py selector_engine.py \
  | grep -i "100\|094\|072" | head -5
```

**Expected outcomes (blocked specs):**
- ✅ No Spec 100 implementation (artifact only, read-only)
- ✅ No Spec 094 code
- ✅ No Spec 072 code
- ❌ Any implementation = FAILURE → escalate

**Escalation trigger:** If blocked specs (100/094/072) have implementation, halt deployment and escalate to governance.

---

## 3. Checklist v2 Promotion Gate

### Enforcement Rule: Mandatory Checklist v2 for all ranking/sizing changes

**Promotion requires:**
- Signal confidence: Checklist v2 all 5 gates PASS (signal card, FM incremental, bootstrap, BH FDR, LOSO)
- Evidence: Minimum 30+ resolved samples, year+ stability
- Governance: Demotion/removal path document (if applicable)

**Verification:**

```bash
# Check for any uncommitted ranking/sizing changes
git status --porcelain | grep -E "ranker|selector|sizing|weights" | head -10

# Check for any unreviewed scoring changes in commits (last 10)
git log --oneline -10 | while read commit msg; do
  git show $commit | grep -E "ranker.*weight|selector.*gate|sizing.*multiplier" && \
    echo "⚠ Found scoring change in: $commit"
done

# Verify Checklist v2 requirement is enforced in memory
grep -l "Checklist.*v2\|no.*promotions.*without\|alpha.*freeze" \
  ~/.claude/projects/*/memory/*policy*.md 2>/dev/null | head -2
```

**Expected outcomes:**
- ✅ No uncommitted ranking/sizing changes
- ✅ Any merged changes have Checklist v2 artifact
- ✅ Memory enforces promotion gate
- ✅ No ad-hoc weight changes without governance memo

**Failure indicators:**
- ❌ Ranking code changed without Checklist v2 memo
- ❌ Sizing multiplier changed without evidence
- ❌ Demotion without documented path
- ❌ Promotion without 5-element governance chain

**Escalation trigger:** If Checklist v2 gate is bypassed, revert change and escalate.

---

## 4. IC Evidence Hold — Composite_Score Invalidation

### Status: ENFORCED (Spec 095 audit found IC bug, Spec 100 corrected it)

**Background:**
- Spec 095 audit found IC backtest measured `composite_score`, not `final_score`
- Prior IC claims are INVALIDATED (pre-correction)
- Spec 100 fixed tooling to measure correct field (final_score)
- Composite_score IC marked INVALID in metadata

**Verification:**

```bash
# Check that composite_score IC is marked INVALID
grep -r "composite_score.*INVALID\|INVALIDATED" \
  artifacts/ production_data/ --include="*.json" --include="*.md" 2>/dev/null | head -5

# Verify Spec 100 corrected the IC field
grep -l "spec.100.*ic.*tooling\|final_score.*ic\|ic.*correction" \
  artifacts/*.md 2>/dev/null | head -2

# Check that no IC claims use pre-correction data
git log --oneline --grep="ic.*claim\|ic.*evidence\|ic.*promotion" 2>/dev/null \
  --since="2026-04-15" --until="2026-05-17" | head -5

# Verify memory holds governance memo
grep -l "governance.*ic.*evidence.*hold\|ic.*claims.*deferred" \
  ~/.claude/projects/*/memory/*.md 2>/dev/null | head -2
```

**Expected outcomes:**
- ✅ Composite_score IC marked INVALID in metadata
- ✅ Spec 100 IC tooling corrected final_score measurement
- ✅ No IC promotion claims using pre-correction evidence
- ✅ Memory enforces hold until post-freeze interpretation

**Failure indicators:**
- ❌ Old IC claims are still cited as current evidence
- ❌ Composite_score IC is NOT marked INVALID
- ❌ Spec 100 IC tooling change is not documented
- ❌ IC evidence hold is not enforced in decisions

**Escalation trigger:** If IC evidence is used despite hold, escalate to governance for decision override.

---

## 5. Model Weight Capping — Governance Override

### Active Override: coinvest_score_z CAPPED at 0.02

**Background:**
- Trained weight: 0.0613
- Governance cap: 0.02 (effective May 4, 2026)
- Rationale: Risk management during 13F cohort distortion window

**Verification:**

```bash
# Check deployed model weights
grep -A 5 "coinvest_score_z\|financial_score" \
  production_data/ranker_v2_model.json | head -10

# Expected output:
# "coinvest_score_z": 0.02,
# "financial_score": -0.05332,

# Verify provenance documents the governance override
grep -B 5 -A 5 "provenance\|governance.*override\|capped.*from" \
  production_data/ranker_v2_model.json | head -20

# Verify run_screen enforces capped weights
grep -A 3 "ranker_v2_score\|pairwise_minimal" run_screen.py | head -10
```

**Expected outputs:**
- ✅ coinvest_score_z = 0.02 (not 0.0613)
- ✅ Provenance block documents original 0.0613
- ✅ Provenance explains governance capping
- ✅ run_screen.py loads from production_data artifact

**Failure indicators:**
- ❌ Deployed weight ≠ 0.02 (cap not applied)
- ❌ Provenance block is missing
- ❌ run_screen loads old uncapped model
- ❌ No governance memo explaining override

**Escalation trigger:** If cap is removed without explicit h20d decision, revert immediately.

---

## 6. Operational Rules — No Unilateral Changes

### Rule 1: Selector changes require governance memo + Checklist v2

```bash
# Check for uncommitted selector changes
git status --porcelain | grep selector_engine

# Check git log for selector changes (last 30 commits)
git log --oneline -30 | grep -i "selector\|gate\|cohort" | while read commit msg; do
  git show --stat $commit | grep selector_engine.py && echo "⚠ $msg"
done
```

**Acceptable selector changes:**
- ☑ Bug fixes (with minimal test coverage)
- ☑ Performance optimization (no logic change)
- ☑ Documentation-only updates
- ❌ Gate threshold changes (requires governance)
- ❌ Eligibility criteria changes (requires Checklist v2)
- ❌ Cohort definition changes (requires 13F cycle)

---

### Rule 2: Ranker changes require Checklist v2 + architecture freeze lift

```bash
# Check for uncommitted ranker changes
git status --porcelain | grep ranker

# Check git log for ranker changes (last 30 commits)
git log --oneline -30 | grep -i "ranker\|feature\|model\|weight" | while read commit msg; do
  git show --stat $commit | grep ranker_v2 && echo "⚠ $msg"
done
```

**Freeze status:** ACTIVE (no changes authorized)

**To change ranker:**
1. Verify architecture freeze is LIFTED (requires h20d decision)
2. Prepare Checklist v2 (5-gate battery)
3. Obtain governance approval
4. Implement with full test coverage
5. Commit with evidence artifacts

---

### Rule 3: No model inference/scoring changes without governance approval

```bash
# Check for run_screen changes that affect scoring
git diff origin/main -- run_screen.py | grep -E "final_score|selector_score|ranker" | head -10

# Check for selector_engine.py z-scoring changes
git diff origin/main -- selector_engine.py | grep -E "z.score|stdev|normalize" | head -10

# Check for changes to production_data model loading
git diff origin/main -- . | grep -i "model.*load\|weights\|coefficients" | head -10
```

**Acceptable scoring changes:**
- ☑ Bug fixes (data type corrections, missing fields)
- ☑ PIT safety improvements (cache invalidation, date handling)
- ☑ Monitoring/diagnostic additions (no algorithmic change)
- ❌ Model weight changes (requires governance)
- ❌ Feature engineering changes (requires Checklist v2)
- ❌ Normalization method changes (requires governance audit)

---

## 7. H20D Decision Gate (May 26)

### Status: PENDING

H20D (hard decision date) is **May 26, 2026**. This is when freeze lift decision happens and Phase 2 Step 4 completion gates are evaluated.

**What happens on May 26:**
- 13F validation verdict is known (clear/extend)
- Phase 2 Step 5 (KG validation) verdict is known
- Forward shadows (inst_delta, cross_signal) are evaluated
- Governance makes freeze lift decision

**Verification (day-of h20d):**

```bash
# Verify 13F re-validation is complete
ls -lh artifacts/13f_validation_*.md 2>/dev/null | tail -1

# Verify Phase 2 Step 5 validation exists
ls -lh artifacts/phase_2_step_5_*.md 2>/dev/null | head -1

# Verify forward shadow artifacts are ready
ls -lh artifacts/forward_shadow_*.md 2>/dev/null | head -3

# Check memory for freeze lift decision
grep -l "freeze.*lift\|h20d.*decision\|freeze.*extended" \
  ~/.claude/projects/*/memory/*2026_05_26*.md 2>/dev/null
```

**Outcomes on h20d:**

**If CLEAR:**
- Architecture freeze LIFTS
- Specs 089/100/094/072 unlock (if not already completed)
- Checklist v2 promotion gate activates
- Model changes authorized (with evidence)

**If EXTEND:**
- Architecture freeze CONTINUES
- All specs remain BLOCKED
- No ranking/sizing changes authorized
- Re-validation window extends (to May 30+)

**If MANUAL:**
- Governance reviews ambiguous results
- Decides freeze lift on case-by-case basis
- Escalates to human decision-making

---

## 8. Weekly Audit Checklist

Run this audit on schedule (Monday/Thursday, or ad-hoc):

```
FREEZE STATUS:
  ☐ Architecture freeze is ACTIVE (not lifted prematurely)
  ☐ No selector changes without governance memo
  ☐ No ranker changes without Checklist v2
  ☐ No scoring logic changes without approval

BLOCKED SPECS (4):
  ☐ Spec 089: no implementation branch/PR
  ☐ Spec 100: artifact exists, read-only, no code changes
  ☐ Spec 094: no selector-only code
  ☐ Spec 072: no vNext scoring code

PROMOTION GATE:
  ☐ Checklist v2 enforced in memory
  ☐ No ranking changes without 5-element chain
  ☐ No sizing changes without evidence
  ☐ All demotion decisions documented

IC EVIDENCE:
  ☐ composite_score marked INVALID
  ☐ Spec 100 IC tooling is live
  ☐ No pre-correction IC claims in current evidence
  ☐ governance_ic_evidence_hold memo is active

MODEL WEIGHTS:
  ☐ coinvest_score_z = 0.02 (capped)
  ☐ Provenance documents 0.0613 → 0.02
  ☐ run_screen loads from production_data
  ☐ No uncapped weight deployments

OPERATIONAL RULES:
  ☐ No unilateral ranking changes
  ☐ No unilateral selector changes
  ☐ No scoring inference changes
  ☐ All code changes have governance context

H20D READINESS:
  ☐ 13F re-validation artifacts ready (May 26)
  ☐ Phase 2 Step 5 validation ready (May 26)
  ☐ Forward shadow artifacts ready (May 26)
  ☐ Governance decision memo template ready (May 26)
```

**Do NOT proceed if any box fails.**

---

## 9. Escalation Paths

### Path 1: Freeze Lift Before h20d

**Scenario:** Architecture freeze is marked LIFTED before May 26

**Investigation:**
1. Find the decision memo (search memory for "freeze lift")
2. Verify it has h20d signature (date = May 26)
3. Verify governance approval is documented
4. Confirm Phase 2 Step 5 passed (if applicable)

**If memo is missing or premature:**
- **Action:** Escalate to governance immediately
- **Do NOT merge** any ranking/sizing changes
- **Revert** to ACTIVE freeze state if changes landed

---

### Path 2: IC Evidence Hold is Bypassed

**Scenario:** IC claim is made using composite_score or pre-correction data

**Investigation:**
1. Find the claim (git log / memory)
2. Verify it uses pre-Spec 100 data
3. Check if governance approved override

**If no override memo exists:**
- **Action:** Escalate to governance immediately
- **Do NOT promote** on invalid evidence
- **Withdraw** the claim from any presentations/decisions

---

### Path 3: Blocked Spec Has Implementation

**Scenario:** Spec 089/100/094/072 has code branch or PR

**Investigation:**
1. Find the branch/PR
2. Check when it was created (should be after quarantine lift, not before)
3. Verify governance approval exists

**If created prematurely (before quarantine lift):**
- **Action:** Halt development immediately
- **Escalate** to governance for decision
- **Do NOT merge** without explicit approval

---

### Path 4: Checklist v2 is Bypassed

**Scenario:** Ranking/sizing change lands without Checklist v2 evidence

**Investigation:**
1. Find the commit
2. Search for corresponding Checklist v2 artifact
3. Verify 5-element chain (two-frame evidence, comparator probe, writeup, sign-off, receipt)

**If Checklist v2 is missing:**
- **Action:** Halt deployment immediately
- **Revert** the change (or request explicit governance override)
- **Escalate** to governance with evidence request

---

## Reference Documents

- **Architecture freeze policy:** `policy_freeze_architecture_2026_04_19.md` (memory)
- **Checklist v2 gate:** `policy_alpha_freeze_2026_04_04.md` (memory)
- **IC evidence hold:** `governance_ic_evidence_hold_2026_05_13.md` (memory)
- **h20d timeline:** `2026_05_22_ranker_review_framing.md` (memory)
- **Model weights:** `production_data/ranker_v2_model.json` (provenance block)
- **Blocked spec status:** `13f_decision_tree_post_clearance_2026_05_19.md`

---

## Audit Output Format

Upon completion, deliver this summary:

```
═══════════════════════════════════════════════════════════════
GOVERNANCE ENFORCEMENT AUDIT
Generated: [date/time]
═══════════════════════════════════════════════════════════════

1. FREEZE STATUS
   ✅ / ⚠ / ❌ [status]
   Details: [summary]

2. BLOCKED SPECS (4)
   Spec 089: ✅ / ⚠ / ❌
   Spec 100: ✅ / ⚠ / ❌
   Spec 094: ✅ / ⚠ / ❌
   Spec 072: ✅ / ⚠ / ❌

3. PROMOTION GATE
   ✅ / ⚠ / ❌ Checklist v2 enforced

4. IC EVIDENCE
   ✅ / ⚠ / ❌ Composite_score INVALID

5. MODEL WEIGHTS
   ✅ / ⚠ / ❌ coinvest_score_z = 0.02

6. OPERATIONAL RULES
   ✅ / ⚠ / ❌ [summary of compliance]

7. H20D READINESS
   ✅ / ⚠ / ❌ [May 26 prep status]

8. ESCALATIONS
   [List any failures above; none = "No escalations"]

9. NEXT AUDIT
   [Scheduled date or trigger]

═══════════════════════════════════════════════════════════════
```

**Status key:**
- ✅ = All checks pass, no action needed
- ⚠ = Warning (manual review recommended)
- ❌ = Failure (escalate immediately)
