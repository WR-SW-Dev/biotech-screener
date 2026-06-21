# catalyst_decay_w Significance Validation

**Date:** 2026-06-20  
**Status:** COMPLETE  
**Classification:** CATALYST_DECAY_W_PROMISING_BUT_UNPROVEN

---

## Status

```
CATALYST_DECAY_W_SIGNIFICANCE_VALIDATION_COMPLETE
READ_ONLY
NO_MODEL_CHANGE
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED
```

---

## Bottom Line First

**catalyst_decay_w is robust IN-SAMPLE (Feb–May 2026) but does NOT replicate OUT-OF-SAMPLE (Oct 2025–Jan 2026).** Under the approved decision rule ("if it weakens materially or fails out-of-sample → promising but unproven"), this lands in **PROMISING_BUT_UNPROVEN**. A full Phase-3 design lane is **not yet justified** on this evidence alone. The in-sample strength is real but appears regime-dependent.

This is the result the validation was designed to catch — the sweep's exciting in-sample numbers do not survive an out-of-sample check.

---

## Method

Three deflation tests on the sweep's inflated t-stats, cohort segment (actionable_rank ≤ 60):

1. **Non-overlapping base dates** — greedily pick base dates ≥ horizon days apart so forward windows are independent (honest t).
2. **Circular block-bootstrap 95% CI** — block length = horizon-spaced; B=2000; tests whether mean IC's CI excludes 0.
3. **Out-of-sample window** — Oct 2025–Jan 2026 (28 snapshots, catalyst_decay_w populated), genuinely outside the Feb–May sweep.

Baselines: coinvest_score_z, financial_score, final_score.

---

## Results

### IN-SAMPLE (Feb–May 2026, 91 base snapshots)

```
Horizon   field              all_mean(t)   non-overlap(t,n)   block-boot 95% CI    verdict
T+10  catalyst_decay_w       +0.072(5.0)   +0.121(2.3, n=11)  [+0.019, +0.126]    ROBUST+
      coinvest_score_z       +0.023(1.5)   +0.009(0.2, n=11)  [-0.027, +0.079]    weak
      financial_score        +0.025(1.7)   +0.021(0.5, n=12)  [-0.021, +0.080]    weak
      final_score            -0.022       +0.003(0.0, n=6)    [-0.144, +0.067]    NEG
T+20  catalyst_decay_w       +0.086(6.1)   +0.090(3.3, n=6)   [+0.016, +0.159]    ROBUST+
      coinvest_score_z       +0.020(1.5)   +0.005(0.1, n=6)   [-0.041, +0.068]    flat
      financial_score        +0.025(1.6)   +0.028(0.4, n=6)   [-0.036, +0.103]    weak
      final_score            -0.068(-2.4) +0.026(0.2, n=3)    [-0.196, +0.063]    NEG
T+60  catalyst_decay_w       +0.096(4.5)   n<3                 [+0.096, +0.096]*   (no OOS test)
      final_score            -0.115(-2.9)  n<3                [-0.115,-0.115]*    NEG
```

**In-sample catalyst_decay_w survives both deflation tests at T+10 and T+20:** the non-overlapping independent-observation mean stays positive and significant (t+2.3, t+3.3), and the block-bootstrap 95% CI **excludes zero** ([+0.019,+0.126] and [+0.016,+0.159]). This is genuine in-sample robustness — not a t-stat artifact.

coinvest_score_z stays weak/flat within the cohort (CI includes 0) — circularity confirmed. final_score stays negative — DEM failure confirmed.

### OUT-OF-SAMPLE (Oct 2025–Jan 2026, 28 base snapshots)

```
Horizon   field              all_mean(t)   non-overlap(t,n)   block-boot 95% CI    verdict
T+10  catalyst_decay_w       +0.026(1.2)   +0.051(1.4, n=10)  [-0.018, +0.069]    weak (CI incl 0)
      coinvest_score_z       +0.018(0.6)   +0.016(0.3, n=10)  [-0.051, +0.082]    flat
      financial_score        -0.058(-2.5)  -0.047(-0.9, n=10) [-0.109, -0.012]    NEG (robust)
T+20  catalyst_decay_w       -0.005(-0.2)  +0.017(0.4, n=6)   [-0.057, +0.048]    NEG/flat
      coinvest_score_z       +0.028(1.1)   +0.051(0.7, n=6)   [-0.028, +0.091]    weak
      financial_score        -0.074(-3.3)  -0.051(-0.9, n=6)  [-0.132, -0.017]    NEG (robust)
T+60  catalyst_decay_w       +0.048(2.3)   n<3                 [-0.010, +0.105]    weak (CI incl 0)
      financial_score        -0.130(-6.0)  n<3                [-0.177, -0.066]    NEG (robust)
```

**Out-of-sample, catalyst_decay_w does NOT replicate:** weak at T+10 (CI includes 0), **negative at T+20**, weak at T+60 (CI includes 0). No horizon's CI excludes zero. The in-sample signal does not carry over to the earlier window.

---

## Interpretation

### catalyst_decay_w: promising but unproven

The in-sample robustness (CI excludes 0 at T+10/T+20, non-overlap significant) is real and not a t-stat artifact. But it **fails to replicate out-of-sample**. Two readings, both pointing to "unproven":

- **Overfitting / window-specific:** the Feb–May signal is partly an artifact of that period's catalyst calendar and market regime.
- **Regime dependence:** catalyst-timing predictiveness may genuinely vary by regime; Feb–May 2026 was favorable, Oct 2025–Jan 2026 was not.

Either way, the evidence does not support committing a Phase-3 design lane yet.

### Out-of-sample caveats (why this is pseudo-OOS)

- The OOS window is **earlier** (look-back), not later — true forward OOS needs post-July-8 data.
- It is small (28 snapshots) and sparse (6-day median spacing), so non-overlap samples are tiny.
- T+60 non-overlap is uncomputable (n<3) in both windows — T+60 conclusions are weakest.

So "fails OOS" should be read as "does not replicate in a different, earlier regime," not as a definitive refutation. But the burden of proof is on the signal, and it has not met it.

### Circularity confirmed in both windows

coinvest_score_z is weak/flat within the cohort in BOTH in-sample and out-of-sample (CIs include 0). The institutional signal's within-cohort predictive weakness is not window-specific — it is a structural property. This part of the diagnosis holds.

### final_score (ranker output) negative in-sample

Confirmed negative at T+20/T+60 where observable. DEM blocker stands.

### Correction on financial_score's negative weight

Earlier audits flagged financial_score's −0.0533 ranker weight as "questionable" because its IC is negative. **That framing was incomplete.** financial_score has robustly NEGATIVE IC out-of-sample (T+20 −0.074, T+60 −0.130, CIs exclude 0). A *negative* ranker weight on a *negatively*-predictive feature is **directionally correct** — the ranker downweights high-financial_score names, which aligns with low-financial_score → higher return. So the negative weight is plausibly the right sign, not a defect. **This corrects the earlier "questionable weight" note.** (It does not rescue final_score's overall negative IC, but it removes financial_score's sign from the suspect list.)

---

## Decision Rule Applied

```
Approved rule:
  "If catalyst_decay_w remains positive after block-bootstrap / non-overlapping
   validation: Phase 3 design lane justified.
   If it weakens materially or fails out-of-sample: promising but unproven."

Result:
  - In-sample: passes (CI excludes 0, non-overlap significant) ✓
  - Out-of-sample: FAILS (CI includes 0 / negative) ✗

→ CATALYST_DECAY_W_PROMISING_BUT_UNPROVEN
→ Phase-3 design lane NOT yet justified.
→ No ranker implementation before July 8 operator review (unchanged).
```

---

## Recommended Next Step

1. **Do not open a catalyst Phase-3 implementation lane yet.** In-sample robustness is encouraging but out-of-sample failure is disqualifying for commitment.

2. **The decisive test is forward out-of-sample.** Add catalyst_decay_w (and coinvest_score_z, financial_score) to the **July 8 real-time confirmation run** via `--score-field`. Post-July-8 data is true forward OOS — if catalyst_decay_w is positive there AND on accumulating June+ data, the lane reopens. If it stays flat/negative forward, treat it as a Feb–May artifact.

3. **Keep the two durable diagnoses** (they survive validation):
   - Institutional signal is circular for within-cohort ranking (coinvest weak in cohort, both windows).
   - final_score is anti-predictive at longer horizons (DEM blocker confirmed).

4. **Retire the "financial_score weight is questionable" thread** — its negative weight is directionally consistent with its negative IC.

5. **Do NOT implement.** Diagnosis only. DEM remains blocked pending July 8.

---

## Reframed Phase-3 Picture

```
DEM is blocked by missing IC AND a diagnosed architecture issue:
  selection and within-cohort ranking overuse the same institutional axis (circular).

catalyst_decay_w looked like the orthogonal fix in-sample, but it does NOT
replicate out-of-sample. It is PROMISING_BUT_UNPROVEN, pending forward (post-July-8)
confirmation — not yet a justified Phase-3 lane.

No orthogonal signal has yet PROVEN out-of-sample predictive power within the cohort.
That remains the open Phase-3 question.
```

---

## Governance Boundary

✅ Read-only validation; no model/ranker/selector/production changes; no commits.

---

## Files Modified

**None (production).** Validation script in scratchpad (non-permanent, read-only). This audit added only `artifacts/audit/catalyst_decay_w_significance_validation_2026_06_20.md` (untracked).

---

## Summary

| Test | catalyst_decay_w | coinvest_score_z | financial_score | final_score |
|------|------------------|------------------|-----------------|-------------|
| **In-sample CI excludes 0?** | ✅ YES (T+10,T+20) | ❌ no | ❌ no | negative |
| **In-sample non-overlap sig?** | ✅ YES (t+2.3,+3.3) | ❌ no | ❌ no | negative |
| **Out-of-sample replicates?** | ❌ **NO** | ❌ no (weak) | robustly NEG | UNOBS |
| **Verdict** | PROMISING_BUT_UNPROVEN | circular (selection only) | neg IC (weight sign OK) | anti-predictive |

**Bottom line:** catalyst_decay_w's in-sample robustness does not survive out-of-sample. Promising, not proven. The forward test on post-July-8 data is decisive. The circularity diagnosis and DEM-failure confirmation both hold and are the durable takeaways.

---

## References

- **Full sweep:** catalyst_decay_w in-sample lead (this validation deflates it)
- **Institutional audit:** circularity hypothesis (confirmed here, both windows)
- **Phase B:** DEM final_score IC fails (confirmed negative)
- **Tooling:** tools/measure_final_score_ic_spec100.py --score-field; July 8 runbook
- **Scripts:** scratchpad/catalyst_decay_w_validation.py (read-only, non-permanent)
