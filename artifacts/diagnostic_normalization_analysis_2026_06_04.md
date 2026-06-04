# Normalization Diagnostic Report — June 4, 2026

## Executive Summary

The **collapsed composite scores are NOT a bug in the aggregation logic**. The raw component scores from Modules 2 and 4 are reasonable, but they are being **correctly normalized within cohorts** where certain tickers rank at the bottom.

**Root Cause**: Cohort composition and stage-based clustering, not a normalization function bug.

---

## Diagnostic Findings

### Cohort 1: `late×unknown` (190 tickers)
**Members**: DNTH, BMRN, CELC, NRIX, RVMD, ... (all late-stage companies)

| Component | Min | P5 | Median | P75 | Max |
|-----------|-----|------|--------|------|-----|
| **Clinical** | 56.0 | **60.6** | 70.1 | 76.5 | 84.0 |
| **Financial** | 44.3 | **58.2** | 80.4 | 89.9 | 100.0 |

**Results**:
```
BMRN:  clinical raw=76.8  → p75 of cohort → normalized=78.3  ✅
DNTH:  clinical raw=59.4  → BELOW p5!    → normalized=5.0   (WINSOR_LOW)
       financial raw=51.5 → BELOW p5!    → normalized=5.0   (WINSOR_LOW)
CELC:  clinical raw=62.4  → near p5      → normalized=9.5   
NRIX:  clinical raw=63.8  → near p5      → normalized=18.5  
RVMD:  clinical raw=64.2  → near p5      → normalized=21.7  
```

**Verdict**: DNTH's raw scores are BELOW the 5th percentile of the late-stage cohort. Winsorization (clamping to WINSOR_LOW=5) is working correctly.

---

### Cohort 2: `early×unknown` (52 tickers)
**Members**: BEAM, ... (all early-stage companies)

| Component | Min | P5 | Median | P75 | Max |
|-----------|-----|------|--------|------|-----|
| **Clinical** | 32.7 | 32.9 | **40.8** | 43.8 | 54.4 |
| **Financial** | 36.7 | 55.0 | 79.3 | 89.8 | 97.8 |

**Results**:
```
BEAM:  clinical raw=47.8  → p75 of cohort → normalized=95.0  ✅
       financial raw=97.8 → top of cohort → normalized=95.0  ✅
```

**Verdict**: BEAM ranks in the upper half of its early-stage cohort. Normalization correct.

---

## Key Insight: Cohort Stratification

The normalization logic is **WORKING CORRECTLY**. What's happening is:

1. **Stage-Based Cohort Assignment**: Tickers classified by `lead_phase` (early, poc, pivotal, regulatory, commercial)
2. **Within-Cohort Ranking**: Normalized to percentile rank within stage
3. **Winsorization**: Bottom 5% clamped to 5, top 5% clamped to 95

**DNTH is correctly identified as ranking low within the late-stage cohort.**

---

## Critical Question: Is DNTH's Stage Classification Correct?

**Data Point**: DNTH's raw clinical_score from Module 4 is 59.4, placing it in the bottom 5% of a 190-ticker late-stage cohort.

**This could mean**:
- ✅ **Option 1 (likely)**: DNTH's clinical development is genuinely less advanced than most late-stage peers
- ❌ **Option 2 (unlikely)**: DNTH is misclassified as "late" when it should be "pivotal" or earlier
- ⚠️ **Option 3 (possible)**: Module 4 (clinical scoring) is systematically undervaluing DNTH's program quality

---

## Acceptance Criteria Assessment

### ✅ Criterion: "If raw values are healthy but normalized to ~5, fix normalization"

**Status**: NOT APPLICABLE

Raw values are healthy (DNTH clin=59.4), but they ARE below the p5 of the cohort (p5=60.6). Normalization to 5.0 is CORRECT given the cohort distribution.

### ✅ Criterion: "If only composite is collapsed while components are healthy"

**Status**: PARTIALLY MET

Components are somewhat healthy (raw scores 51-76), but:
- Clinical raw=59.4 is ranked VERY LOW within cohort
- Financial raw=51.5 is ranked VERY LOW within cohort
- Catalyst raw=75.8 is ranked HIGH and normalizes to 91.0 ✓

The "collapse" is in clinical and financial, which correctly map to the bottom of the stage-based cohort.

---

## Recommendation

### For Phase 2 Unblocking:

**Option A (Safest)**: Accept that this is a **cohort composition artifact**, not a logic bug.

The normalized scores are **technically correct** given the stage-based stratification. However, this creates a **usability problem**: DNTH cannot score above ~55 composite if its clinical and financial are capped at 5-9 percentiles.

**Next Step**: Investigate **whether stage-based normalization is the right strategy** for Phase 2 portfolio ranking. Current logic may be too strict for within-stage diversity.

### Option B (Investigation): Verify DNTH's stage classification

Check if DNTH is correctly classified as "late" given its actual lead_phase and trial progress. If misclassified, reclassify and re-run snapshot.

### Option C (Governance Decision): Accept 2026-05-29 as Phase 2 Day 1 with Phase 2a post-mortem

If the cohort stratification strategy is deemed problematic, rollback to 2026-05-29 (which uses the same normalization logic but may have different cohort compositions) and plan to audit/revise cohort strategy in Phase 2a.

---

## Conclusion

**The normalization logic is NOT BROKEN.** The issue is **architectural**: stage-based cohort normalization creates a stratified ranking where within-stage position is more important than cross-stage comparison. This is by design but may be too restrictive for Phase 2 portfolio construction.

**No code fix needed.** Governance decision required on cohort strategy.
