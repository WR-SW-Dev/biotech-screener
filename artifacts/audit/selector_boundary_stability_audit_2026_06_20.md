# Selector Boundary Stability Audit

**Date:** 2026-06-20  
**Status:** COMPLETE  
**Scope:** Read-only audit of selector cohort entry, rank-60 cutoff, and boundary churn

---

## Status

```
SELECTOR_BOUNDARY_STABILITY_AUDIT_COMPLETE
READ_ONLY
NO_SELECTOR_CHANGE
NO_RANKER_CHANGE
NO_MODEL_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED
```

---

## Scope

**Question:** Are the right ~60 names entering the DEM ranker cohort (actionable_rank ≤ 60), and is the rank-60 cutoff stable?

**Answer:** **STABLE_TOP30 + SOFT_NEARTIE_AT_RANK60_CUTOFF**

- ✅ Eligibility gate is clean and deterministic
- ✅ Top-30 selection is highly stable
- ✅ Catalyst quality near boundary is sound
- ⚠️ The rank-60 cohort cutoff sits in a near-tie band (~6 names churn per snapshot)
- ⚠️ Cohort entry is **65% institutionally-weighted** — same signal family DEM relies on

---

## Artifacts Inspected

| Artifact | Purpose | Status |
|----------|---------|--------|
| data/snapshots/{2026-06-01,06-08,06-15,06-18}/rankings.csv | Boundary churn | ✅ |
| selector_engine.py:348-472 (compute_selector_scores) | Selection logic | ✅ Read |
| run_screen.py:5542-5560 (A4_SELECTOR_CONFIG wiring) | Config + cutoff | ✅ Read |
| A4_SELECTOR_CONFIG block weights | Weighting | ✅ Inspected |

---

## Finding 1: selector_score Is Ordinal, Not Magnitude

`selector_score` is the **percentile rank** of the weighted block sum, not the raw signal magnitude (selector_engine.py:439, `pctiles = [r / max(n-1, 1) ...]`).

**Evidence:** selector_score spacing is perfectly uniform.

```
Consecutive deltas (top 15): all = 0.004854 ± 0.000000
0.004854 = 1 / 206 (n=207 eligible names)
Max = 1.000000, Min = 0.000000
```

**Implication:** Every adjacent pair of names differs by exactly one rank position (0.004854) in selector_score. "Near-tie at the boundary" is the default state by construction — selector_score carries no information about *how close* two names actually are. The real magnitude lives in the underlying weighted block score, which is collapsed to ordinal rank before the cohort cutoff.

---

## Finding 2: Cohort Entry Is 65% Institutionally-Weighted

Production selector block weights (A4_SELECTOR_CONFIG):

```
clinical          0%    (DISABLED in production)
catalyst          15%
survivability     10%
institutional     65%   ← DOMINANT
market_structure  10%
```

**Implication — concentration risk:**

The same institutional 13F signal family that drives **65% of cohort entry** is also one of the **two DEM ranker features** (coinvest_score_z). Institutional data therefore governs both:
1. **Who enters** the top-60 DEM cohort (65% of selector weight), and
2. **How they rank** within it (coinvest_score_z, weight +0.02 in ranker).

Cross-reference Phase 2c: 13F contamination is **monitored externally only, not enforced in the ranker**. The same applies to the selector. A 13F refresh-window contamination event would propagate through both cohort selection and ranking simultaneously, with no internal gate on either.

**This is the single most material finding of the audit.** It is a structural concentration, not a defect.

---

## Finding 3: The Rank-60 Cutoff Sits in a Near-Tie Band

Reconstructed weighted block scores (catalyst·0.15 + survivability·0.10 + institutional·0.65 + market·0.10) at the boundary, 2026-06-18:

```
pos ticker   raw_wtd   gap_to_next   bucket
 55 CRNX     0.5800    0.0004        top60
 56 CTNM     0.5796    0.0006        top60
 57 SNDX     0.5790    0.0016        top60
 58 SEPN     0.5774    0.0005        top60
 59 ARWR     0.5768    0.0017        top60
 60 PTCT     0.5752    0.0007        top60   <-- CUTOFF
 61 SLDB     0.5745    0.0029        top120
 62 ANNX     0.5716    0.0013        top120
 63 IDYA     0.5702    0.0010        top120
```

**Cutoff gap (rank 60 → 61): 0.00069**  
**Median gap (ranks 46–75): 0.00145**

The gap separating the last in-cohort name (PTCT) from the first out-of-cohort name (SLDB) is **smaller than the typical gap in the region** (30th percentile). The cutoff lands in a tightly-packed cluster, not at a natural break. PTCT and SLDB are effectively interchangeable on a ~0.0007 weighted-score difference.

---

## Finding 4: Boundary Churn Is Real but Bounded

### Cohort entrants/exits per snapshot (top-60 by selector)

```
2026-06-01 → 2026-06-08: 54 stable, 6 in / 6 out
  in:  ANNX BCAX GLUE IDYA IMTX SLDB
  out: CRNX ERAS JBIO PTCT TENX VERA

2026-06-08 → 2026-06-15: 57 stable, 3 in / 3 out
  in:  CRNX ERAS PTCT      (CRNX, ERAS, PTCT re-enter after exiting)
  out: ANNX IMTX SLDB

2026-06-15 → 2026-06-18: 57 stable, 3 in / 3 out
  in:  JBIO TENX VERA      (JBIO, TENX, VERA re-enter)
  out: BCAX GLUE IDYA
```

### Oscillation across the rank-60 line (band ranks 50–70)

7 names cross the cohort line within the boundary band over 4 snapshots:

```
ticker  06-01  06-08  06-15  06-18   crosses-60
ANNX     66     59     64     62     YES
BCAX     67     58     57     68     YES
GLUE     64     60     60     65     YES
IDYA     62     55     59     63     YES
IMTX     65     57     61     64     YES
PTCT     60     63     58     60     YES
SLDB     63     56     62     61     YES
```

**Interpretation:** The bottom ~10 cohort slots are effectively a rotating pool of ~15–20 boundary names. Names flicker in and out on sub-0.001 weighted-score differences — the churn IS the near-tie band expressing itself, not new information arriving. The same names recur (PTCT, SLDB, ANNX, ERAS), confirming oscillation rather than genuine turnover.

---

## Finding 5: Eligibility Gate Is Clean and Deterministic

```
Universe rows (2026-06-18): 289
Eligible (eligible=1):       207 (72%)
Ineligible:                   82 (28%)

Ineligible reasons:
   76  deep_drawdown
    4  fundamental_red_flag
    2  fundamental_red_flag | deep_drawdown
```

**Verdict:** The eligibility gate is dominated by a single deterministic hard gate (`deep_drawdown`, 76 of 82 exclusions). Low ambiguity, no silent/unexplained exclusions, no missing-reason cases. This gate is **not** a source of boundary instability.

---

## Finding 6: Catalyst Quality Near Boundary Is Sound

```
top-60 cohort catalyst precision: DAY=54, MONTH=6
boundary band (50-70):            DAY=19, MONTH=1
top-60 with catalyst_in_window=1: 22/60 (37%)
top-60 with NO catalyst signal:   0/60
```

**Verdict:**
- Catalyst dates are mostly DAY-precision (no coarse HALF_YEAR/QUARTER leakage at the boundary).
- All 60 cohort names have a catalyst signal (no missing-data entrants).
- Only 37% are in a near-term catalyst window — the cohort is **not** over-dependent on imminent catalysts (consistent with institutional 65% weight). This is healthy: cohort entry is not gamed by catalyst-window timing artifacts.

---

## Churn Driver Attribution

| Driver | Boundary Impact | Evidence |
|--------|-----------------|----------|
| **Institutional block (65%)** | Dominant | Cohort entry tracks institutional signal; same family as DEM feature |
| **Near-tie ordinal cutoff** | Structural | Cutoff gap 0.0007 < median 0.0015; rank-60 in packed cluster |
| **Catalyst (15%)** | Minor | Precise dates; not timing-gamed |
| **Eligibility gate** | None | Deterministic deep_drawdown; clean |
| **Data quality** | None observed | No missing-signal entrants; no unexplained exclusions |

---

## Classification

```
SELECTOR_BOUNDARY_STABLE_TOP30
SOFT_NEARTIE_AT_RANK60_CUTOFF
INSTITUTIONAL_CONCENTRATION_IN_COHORT_ENTRY
```

**What is stable:**
- Eligibility gate (deterministic, clean)
- Top-30 selection (rock-solid; see Phase A top-5 stability)
- Catalyst quality (precise, complete)

**What is soft:**
- The rank-60 cohort cutoff is a near-tie boundary; ~6 names/snapshot rotate through the bottom cohort slots on sub-0.001 score differences.

**What is concentrated:**
- 65% of cohort entry weight is institutional — the same 13F family the DEM ranker relies on, with no internal contamination gate on either path.

---

## Materiality Assessment

**Does boundary softness matter for portfolio decisions?**

Limited. The names oscillating across rank 60 (PTCT, SLDB, ANNX, IDYA, IMTX, GLUE, BCAX) sit at the *bottom* of the DEM cohort. The DEM ranker re-ranks within the cohort, and portfolio actions concentrate in the top-30 (which Phase A confirmed is highly stable). Boundary churn mostly determines *which marginal names receive a DEM score at all* — not which names reach the portfolio.

**Does institutional concentration matter?**

Yes — this is the more material finding. If 13F data degrades (refresh-window contamination, stale filings, inflated conviction), the effect compounds across both cohort selection (65%) and ranking (coinvest_score_z). Phase 2c established this is monitored externally only. The selector audit confirms the exposure is larger than the ranker alone suggests.

---

## Confirmed Defects

**NONE.** Selector logic is correct:
- Percentile normalization is standard and intentional
- Block weighting is configured as designed (institutional-heavy by choice)
- Eligibility gate is deterministic and explainable
- No data-quality leakage at the boundary

The findings are **structural characteristics**, not bugs.

---

## Unconfirmed Risks

### Risk 1: Institutional Concentration Across Selection + Ranking (MEDIUM-HIGH)

Cohort entry (65%) and DEM ranking (coinvest_score_z) both lean on 13F. No internal contamination gate on either. External monitoring only (Phase 2c).

**Severity:** MEDIUM-HIGH (compounds during 13F refresh windows)

### Risk 2: Near-Tie Cutoff Sensitivity (LOW-MEDIUM)

The rank-60 cohort boundary is a coin-flip among near-tie names. Small data perturbations reshuffle the bottom cohort slots.

**Severity:** LOW-MEDIUM (limited portfolio impact; top-30 unaffected)

---

## Recommended Follow-Ups (No Implementation)

1. **Institutional concentration diagnostic** — quantify top-30 dependency on coinvest_score_z AND institutional selector block jointly. (Next audit: INSTITUTIONAL_SIGNAL_HEALTH_AND_OUTLIER_AUDIT, already in roadmap.)

2. **Boundary-band watch (design-only)** — consider a diagnostic flag for names within ±5 ranks of the rank-60 cutoff, marking them as "marginal cohort membership." Diagnostic only; no gating.

3. **Do NOT change selector weights or cutoff** based on this audit. The institutional-heavy weighting and rank-60 cutoff are design choices. Any change belongs in a separate, IC-evidence-backed design review — and DEM is currently blocked pending the July 8 IC gate.

---

## Governance Boundary

✅ **NO VIOLATIONS**

- ✅ Read-only inspection
- ✅ No selector code/weight changes
- ✅ No ranker changes
- ✅ No eligibility rule changes
- ✅ No production outputs modified
- ✅ No commits

---

## Files Modified

**None (production files).**

```bash
git status -sb
# nothing to commit (production); audit artifact untracked
```

---

## Summary

| Aspect | Finding | Verdict |
|--------|---------|---------|
| **selector_score nature** | Ordinal percentile rank (1/206 spacing) | Structural |
| **Cohort entry weighting** | Institutional 65%, clinical 0% | ⚠️ Concentration |
| **Rank-60 cutoff** | Near-tie band (gap 0.0007 < median 0.0015) | ⚠️ Soft |
| **Cohort churn** | ~6/snapshot; 7 names oscillate across line | ⚠️ Bounded |
| **Eligibility gate** | Deterministic deep_drawdown (76/82) | ✅ Clean |
| **Catalyst quality** | DAY-precise, complete, not timing-gamed | ✅ Sound |
| **Top-30 stability** | Rock-solid (Phase A) | ✅ Stable |
| **Defects** | None | ✅ |

**Classification:** `SELECTOR_BOUNDARY_STABLE_TOP30 + SOFT_NEARTIE_AT_RANK60_CUTOFF + INSTITUTIONAL_CONCENTRATION_IN_COHORT_ENTRY`

**Next recommended audit:** INSTITUTIONAL_SIGNAL_HEALTH_AND_OUTLIER_AUDIT (quantify the joint institutional dependency surfaced here).

---

## References

- **Phase 2c:** 13F contamination monitored externally only
- **Phase A:** Top-30 stability EXPLAINABLE_LOW_CHURN; top-5 identical across 17 days
- **Selector engine:** selector_engine.py:348-472 (percentile normalization, bucketing)
- **Config:** A4_SELECTOR_CONFIG (institutional 65%, clinical 0%, top_60_cutoff=60)

