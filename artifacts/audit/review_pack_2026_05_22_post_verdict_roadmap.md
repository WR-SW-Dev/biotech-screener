# 2026-05-22 Review Verdict Roadmap — What Happens Next

**Status:** ROADMAP (execute after 2026-05-22 review verdicts are committed)  
**Purpose:** Define decision trees and next phases for each spec outcome

---

## Spec 072 Decision Tree

### Path A: All D7/D8/D9 PASS → Proceed to D1–D6 (Recommended)

**Timeline:** 2026-05-24 → 2026-05-27

**Actions:**
1. Commit verdict memo: `spec_072_d7_d8_d9_verdict_2026_05_22.md`
2. Begin D1–D6 diagnostics (see template: `spec_072_vnext_d1_d6_template_2026_05_14.md`)
   - D1: Composition Jaccard (5 min)
   - D2: Block delta confirmation (10 min)
   - D3: Forward-return comparison (T+5/T+20) (15 min)
   - D4: Stability metrics (10 min)
   - D5: Trap logic audit (10 min)
   - D6: Self-dominance check (15 min)
3. D1–D6 verdict: expected 2026-05-26 or 2026-05-27

**Next steps (if D1–D6 all pass):**
- Spec 072 candidate ready for **shadow phase** (not production; Checklist v2 pending)
- Prepare Checklist v2 battery (3–5 days)
- Expected timeline: Spec 072 shadow-ready by 2026-06-01

**Blockers (cannot promote to production):**
- Spec 094: Marginal value test (satisfied by D8) ✓
- Spec 095: IC scope correction (needs Spec 100) ⚠
- Spec 100: True ranker IC tooling (not yet built) ❌

---

### Path B: D7 FAILS (Not Orthogonal) → Evaluate BACKUP

**Symptom:** Candidate correlation with coinvest_score_z >= 0.40 OR residualized IC < 0.04

**Timeline:** 2026-05-22 → 2026-05-24

**Actions:**
1. Close PRIMARY candidate (clinical_score_v2_z)
2. Commit verdict: `spec_072_d7_d8_d9_verdict_2026_05_22.md` with "PRIMARY CLOSED; BACKUP UNDER EVALUATION"
3. Run D7/D8/D9 on BACKUP (endpoint_strength_score)
   - Same thresholds
   - Expected turnaround: 1 day (diagnostic is fast)
4. BACKUP verdict: 2026-05-23 or 2026-05-24

**Next steps:**
- If BACKUP D7/D8/D9 pass: proceed to D1–D6 on BACKUP (Path A equivalent)
- If BACKUP fails: proceed to Path C

---

### Path C: D8 FAILS (No Marginal Ordering Value) → Close Research

**Symptom:** T+5 IC < 0.06 OR T+20 IC < 0.04 within top-coinvest quintile

**Timeline:** 2026-05-22 (verdict same day)

**Actions:**
1. Close candidate (PRIMARY and BACKUP both failed)
2. Commit verdict: `spec_072_d7_d8_d9_verdict_2026_05_22.md` with "CLOSED: No marginal ordering value"
3. Document blocker: "Clinical_score_v2_z and endpoint_strength_score do not add ranking power within coinvest-eligible universe"

**Next steps:**
- Spec 072 candidate research PAUSED (not closed forever; can revisit with new candidates)
- Prepare memo on why frozen set failed (data quality? signal saturation? regime-dependent?)
- Escalate to operator: "Candidate research blocked; recommend alternative direction (Spec 098 catalyst timing? Spec 099 clinical orthogonality? New candidates?)"

---

### Path D: D9 FAILS (IC Confounded) → Close Research

**Symptom:** Residualized IC < threshold OR sign flips post-residualization

**Timeline:** 2026-05-22 (verdict same day)

**Actions:**
1. Close candidate
2. Commit verdict: `spec_072_d7_d8_d9_verdict_2026_05_22.md` with "CLOSED: IC confounded with coinvest"
3. Document findings: "Candidate IC exists but is entirely explained by coinvest_score_z correlation; no independent signal"

**Next steps:**
- Spec 072 candidate research PAUSED
- Consider alternative: improve selector (Spec 072 vNext gate refinement) rather than ranker

---

## Spec 091 Decision Tree

### Path A: CRT PASS (Cohort-Driven WARN) → Close with No Change

**Condition:** WARN streak coincides with cohort expansion (2026-04-25); clears post-13F-refresh (2026-05-15+)

**Timeline:** 2026-05-22 (verdict same day)

**Actions:**
1. Commit verdict: `spec_091_evidence_bundle_2026_05_22.md` with "CRT PASS: WARN is cohort artifact"
2. Close Spec 091 with NO model changes (selector/ranker weights unchanged)
3. Document: "score_rank_pct WARN was expected during distortion window; self-heals post-13F-refresh"

**Next steps:**
- Spec 091 CLOSED
- Continue monitoring score_rank_pct IC post-13F-refresh; expect normalization within 1–2 weeks
- If ic_health WARN clears and score_rank_pct IC recovers by 2026-05-29: confirm closure

---

### Path B: CRT FAIL (True Degradation) → Multi-Horizon IC Test

**Condition:** WARN predates cohort expansion OR persists post-refresh

**Timeline:** 2026-05-22 → 2026-05-24

**Actions:**
1. Commit preliminary verdict: `spec_091_evidence_bundle_2026_05_22.md` with "CRT FAIL: True degradation signal; proceed to Multi-Horizon IC"
2. Run Multi-Horizon IC validation (T+5, T+20, T+60)
3. Verdict: 2026-05-24 or 2026-05-25

---

### Path B1: Multi-Horizon IC PASS → Proceed to PIT Audit

**Condition:** At least 2 horizons with IC >= +0.04 (t > 1.5)

**Timeline:** 2026-05-24 → 2026-05-25

**Actions:**
1. Run PIT Integrity Audit (data quality check)
2. If clean: candidate is promotion-eligible; prepare Checklist v2 (out of scope for now)
3. If issues: fix data/formula; re-run Multi-Horizon IC

---

### Path B2: Multi-Horizon IC FAIL → Retire Signal

**Condition:** No significant IC across any horizon

**Timeline:** 2026-05-24 (verdict same day)

**Actions:**
1. Commit verdict: "score_rank_pct shows no IC across T+5/T+20/T+60; true degradation confirmed; signal is anti-predictive or noise"
2. Retire signal from ic_health monitoring (or keep as diagnostic-only, non-actionable)
3. Close Spec 091 with decision: "No model action warranted; signal is degraded beyond recovery"

**Next steps:**
- Spec 091 CLOSED
- Continue observing whether signal recovers in future; escalate to operator if recovery observed

---

## Spec 096 Enforcement

**During and after review:**

### Enforcement Points

1. **Gate/Ranker Separation:** 
   - Confirm selector uses gates (exclude names)
   - Confirm ranker ranks survivors only
   - Confirm risk control is post-ranking
   - No composite construction during pending phase

2. **Marginal Value Gate:**
   - Spec 072 satisfies via D8 (within-quintile IC) ✓
   - Spec 091 requires Multi-Horizon IC if CRT fails ✓

3. **Blockers (Cannot Bypass):**
   - Spec 094: Marginal value proof → satisfied by D8 test ✓
   - Spec 095: Correct IC scope → still needs Spec 100 ⚠
   - Spec 100: Ranker IC tooling → not built; blocks all ranker promotions ❌

### Decision Gate

**BEFORE any production ranker change is authorized:**
- [ ] Spec 072: D7/D8/D9 all pass AND D1–D6 all pass (if applicable)
- [ ] Spec 091: CRT clears OR (Multi-Horizon passes AND PIT audit passes AND Checklist v2 ready)
- [ ] Spec 096: Gate/ranker separation confirmed; blockers acknowledged
- [ ] Spec 100: Ranker IC tooling implemented and tested (NEW REQUIREMENT)
- [ ] Spec 094: Marginal value test passed
- [ ] Spec 095: IC scope confirmed correct
- [ ] Checklist v2: Full battery passed (FM, bootstrap, FDR, LOSO, year stab, domain)

**If any gate fails:** No production ranker change. Document blocker and next steps.

---

## Phase Advancement: Shadow Lane Eligibility (Specs 098/099)

**Only evaluate AFTER 2026-05-22 review AND cohort window fully closed.**

### Spec 098 — Catalyst Timing Monitor

**Pre-requisites:**
- [ ] Cohort distortion cleared (inst_delta_z normalized)
- [ ] Forward-return window stable (no regime change post-cohort-clear)
- [ ] Spec 072 verdict known (if candidate advanced, does it interact with catalyst timing?)

**Next step:** Prepare diagnostic pack for catalyst_score_z (shadow-only measurement)

### Spec 099 — Clinical Orthogonality Audit

**Pre-requisites:**
- [ ] Spec 072 clinical_score_v2_z verdict known
- [ ] Cohort window closed
- [ ] Clinical quality data freshness confirmed (HINT benchmark, PubMed records)

**Next step:** Run orthogonality tests on clinical_design_quality vs coinvest_score_z

---

## Expected Outcomes by 2026-05-29

### Scenario 1: Spec 072 D7/D8/D9 All Pass (Most Optimistic)

```
2026-05-22: D7/D8/D9 verdict = PASS
2026-05-24/25: D1–D6 diagnostics
2026-05-27: D1–D6 verdict (expected to PASS)
2026-05-29: Checklist v2 readiness assessment

OUTCOME: Spec 072 candidate eligible for shadow phase (pending Spec 100 IC tooling)
NEXT: Prepare shadow implementation plan; wait for Spec 100 tooling
```

### Scenario 2: Spec 072 D8 Fails; Spec 091 CRT Passes

```
2026-05-22: D7/D8/D9 = FAIL (no marginal ordering value)
2026-05-22: Spec 091 CRT = PASS (WARN is cohort artifact)

OUTCOME: Spec 072 research PAUSED; Spec 091 CLOSED
NEXT: Evaluate alternative ranker research directions (shadow lanes? new candidates?)
```

### Scenario 3: Spec 091 Multi-Horizon Fails

```
2026-05-22: Spec 091 CRT = FAIL (true degradation)
2026-05-24: Multi-Horizon IC = FAIL (no IC across horizons)

OUTCOME: Spec 091 CLOSED; score_rank_pct retired
NEXT: No model action; continue monitoring for recovery
```

---

## Escalation Triggers

**If any of these occur, escalate to operator immediately:**

1. **Both PRIMARY and BACKUP fail D7/D8/D9:**
   - Indicates frozen candidate set may not have viable ranker candidates
   - Escalate: "Recommend pivoting to alternative ranker research direction or new candidate set"

2. **Spec 091 Multi-Horizon shows real IC but data is corrupted:**
   - Indicates formula/data issue, not signal quality issue
   - Escalate: "Production data quality issue detected; recommend engineering review"

3. **Cohort distortion does NOT clear post-13F-refresh:**
   - Indicates 13F ingest itself may be broken
   - Escalate: "13F ingest pipeline may be non-functional; investigate upstream"

4. **Forward-return test shows divergence > 2pp vs coinvest-only ranking:**
   - Indicates ranker may be introducing systematic error
   - Escalate: "Ranker logic may be broken; recommend architecture review before shadow phase"

---

## Timeline Summary

```
2026-05-22: Pre-gates + review day (4 hours)
           → Verdicts for Spec 072 D7/D8/D9, Spec 091 CRT, Spec 096 confirmation

2026-05-23/24: Follow-up diagnostics (if needed)
             → D1–D6 (if Spec 072 D7/D8/D9 pass)
             → BACKUP evaluation (if PRIMARY fails)
             → Multi-Horizon IC (if Spec 091 CRT fails)

2026-05-27: Expected verdict on D1–D6 (if running)

2026-05-29: Final review of all outcomes
           → Confirmed verdicts
           → Next phase decision (shadow lanes? Checklist v2? Alternative direction?)

2026-06-01+: Execution phase (shadow implementation, Checklist v2 battery, etc.)
```

---

## Success Metrics for Post-Review

**Spec 072:**
- Clear verdict (D7/D8/D9 result) documented ✓
- If pass: D1–D6 plan clear ✓
- If fail: blocker identified ✓

**Spec 091:**
- CRT verdict clear (cohort-driven or true degradation) ✓
- If multi-horizon needed: test plan ready ✓
- If closed: rationale documented ✓

**Spec 096:**
- Gate/ranker separation confirmed ✓
- Blockers (Specs 094/095/100) acknowledged ✓
- No unauthorized production changes made ✓

**Forward-Return Test:**
- Baseline comparison shows ranker integrity ✓
- Data sufficiency assessed ✓

**Overall:**
- All verdicts committed to git ✓
- Next phase scoped and dated ✓
- Escalation triggers identified ✓
- No production changes made ✓

---

## References

- Spec 072 D7/D8/D9 prep: `artifacts/audit/spec_072_vnext_ranker_review_prep_2026_05_14.md`
- Spec 072 D1–D6 template: `artifacts/audit/spec_072_vnext_d1_d6_template_2026_05_14.md`
- Spec 091 evidence bundle: `artifacts/audit/score_rank_pct_evidence_bundle_template_2026_05_14.md`
- Ranker research landscape: `memory/ranker_research_landscape_2026_05_14.md`
- Spec 096 doctrine: Gate/ranker separation governance
