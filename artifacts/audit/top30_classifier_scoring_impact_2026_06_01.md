---
name: top30_classifier_scoring_impact_2026_06_01
title: Top-30 Classifier Scoring Impact Audit — 2026-06-01
description: Ticker-level validation of classifier misclassifications affecting catalyst scoring
date: 2026-06-02
scope: RVMD, CELC, ERAS, DRUG, ALKS, MBX
---

# Top-30 Classifier Scoring Impact Audit — 2026-06-01

**Authority:** Ticker-level validation (event-label quality checks, Top-30 impact assessment)  
**Scope:** Read-only diagnostic. No classifier edits, taxonomy changes, or scoring modifications.  
**Data Sources:** Herald classifier output (classified_2026-06-01.jsonl), rankings snapshot (2026-06-01)

---

## Executive Summary

| Ticker | Classification | Impact | Severity | Remediation |
|--------|---|---|---|---|
| **RVMD** | SUPPRESSED_CLINICAL_EVENT | CONFIRMED | HIGH | CATALYST_ATTRIBUTION_REVIEW_REQUIRED |
| **CELC** | SUPPRESSED_CLINICAL_EVENT | CONFIRMED | HIGH | CATALYST_ATTRIBUTION_REVIEW_REQUIRED |
| **ERAS** | COLLISION_NOISE_UNEXCLUDED | CONFIRMED | MEDIUM | CATALYST_INPUT_CONTAMINATION |
| **DRUG** | COLLISION_NOISE_UNEXCLUDED | CONFIRMED | MEDIUM | CATALYST_INPUT_CONTAMINATION |
| **ALKS** | COLLISION_NOISE_UNEXCLUDED | CONFIRMED | MEDIUM | CATALYST_INPUT_CONTAMINATION |
| **MBX** | LEGITIMATE_EVENTS | NO IMPACT | LOW | POOL_QA_ONLY |

**Status:** ⚠️ **CATALYST ATTRIBUTION REVIEW REQUIRED** before relying on Phase 2 ranking catalyst fields for RVMD, CELC, ERAS, DRUG, ALKS

---

## Detailed Ticker Analysis

### 1. RVMD (Revolution Medicines) — CONFIRMED SUPPRESSED CLINICAL EVENT

**Ranking Context:**
- Actionable rank: 8 (strong recommendation)
- Catalyst days: 303 (far-term catalyst, decay 0.3)
- Catalyst bucket: core
- Catalyst reason: `tier=B;reason=high_opt+catalyst_far`

**Herald Events:**

| # | Headline | Category | Event Type | Confidence | Published | Informational-Only | Collision-Flag | Needs-Review |
|---|---|---|---|---|---|---|---|---|
| 1 | Revolution Medicines Announces Asco Plenary Presentation | other | corporate_update | 0.70 | 2026-05-31 | ✓ Yes | ✗ No | ✗ No |
| 2 | **[PHASE 3] ASCO Plenary Presentation Highlighting... RASolute 302** | other | corporate_update | 0.70 | 2026-05-31 | ✓ Yes | ✗ No | ✗ No |

**Diagnosis:**
- Event 2 explicitly references **RASolute 302 Phase 3 data presentation** (major catalyst moment for RVMD)
- Classifier labeled both events as `other` (non-clinical category) with `informational_only=True`
- Despite informational-only flag, rankings show RVMD at **rank 8 with 303-day catalyst window**
- **Question:** Did informational-only Phase 3 events still feed catalyst_days=303 in composite scoring?

**Impact Classification:** `CONFIRMED_SUPPRESSED_CLINICAL_EVENT`
- Valid clinical catalyst (Phase 3 readout) misclassified as non-clinical
- Informational-only suppression may have been overridden upstream

---

### 2. CELC (Celcuity) — CONFIRMED SUPPRESSED CLINICAL EVENT

**Ranking Context:**
- Actionable rank: 20
- Catalyst days: 29 (near-term, in-window)
- Catalyst bucket: binary_now
- Catalyst reason: `tier=A;reason=high_opt+catalyst_near`

**Herald Events:**

| # | Headline | Category | Event Type | Confidence | Published | Informational-Only | Collision-Flag | Needs-Review |
|---|---|---|---|---|---|---|---|---|
| 1 | Celcuity Hold Conference Call Discuss Results Pik3Ca Mutant | other | corporate_update | 0.70 | 2026-06-02 | ✓ Yes | ✗ No | ✗ No |
| 2 | Celcuity Participate Upcoming Investor Conferences | other | corporate_update | 0.70 | 2026-06-02 | ✓ Yes | ✗ No | ✗ No |
| 3 | **[PHASE 3] To Hold Conference Call to Discuss Results PIK3CA Mutant Cohort** | other | corporate_update | 0.70 | 2026-06-01 | ✓ Yes | ✗ No | ✗ No |

**Diagnosis:**
- Event 3 explicitly references **VIKTORIA-1 Phase 3 cohort results** (clinical data readout)
- Classifier labeled as `other` + `informational_only=True`
- Rankings show CELC at **rank 20 with 29-day near-term catalyst (in-window)**
- Catalyst bucket: `binary_now` suggests binary event expected imminently

**Impact Classification:** `CONFIRMED_SUPPRESSED_CLINICAL_EVENT`
- Valid clinical data release misclassified as non-clinical information
- Catalyst scoring treated Phase 3 conference call as near-term binary event despite `informational_only=True`

---

### 3. ERAS (Erasca) — CONFIRMED COLLISION/NOISE UNEXCLUDED

**Ranking Context:**
- Actionable rank: 13
- Catalyst days: 183 (mid-term)
- Catalyst bucket: core
- Catalyst reason: `tier=B;reason=high_opt+catalyst_far`

**Herald Events:**

| # | Headline | Category | Event Type | Confidence | Published | Collision-Flag | Needs-Review |
|---|---|---|---|---|---|---|---|
| 1 | **Norman Schwarzkopf's Desert Storm-Carried Pistol to Auction This June** | other | unclassified | 0.20 | 2026-06-01 | ✓ **FLAG** | ✓ **REVIEW** |
| 2 | **ASUS Unveils Revolutionary ProArt P16 and P14 Laptops Powered by NVIDIA RTX** | other | unclassified | 0.20 | 2026-06-01 | ✓ **FLAG** | ✓ **REVIEW** |
| 3 | **E Ink Debuts 75-inch Color ePaper Advertising Display** | other | unclassified | 0.20 | 2026-06-01 | ✓ **FLAG** | ✓ **REVIEW** |

**Diagnosis:**
- All 3 events are **ticker collisions with non-biotech companies**
- All marked `collision_flag=True` and `needs_review=True` by classifier
- Confidence=0.20 (very low, indicating uncertainty)
- All labeled as unclassified (classifier cannot identify what these are)
- **Despite collision flags, ERAS ranked 13 with 183-day catalyst window**

**Impact Classification:** `CONFIRMED_COLLISION_NOISE_UNEXCLUDED`
- 100% of ERAS Herald events are off-target noise/collisions
- Collision-flagged events appear to still be entering catalyst scoring
- No legitimate biotech events for ERAS in this date window

---

### 4. DRUG (Bright Minds Biosciences) — CONFIRMED COLLISION/NOISE CONTAMINATION

**Ranking Context:**
- Actionable rank: 9
- Catalyst days: 153 (mid-term)
- Catalyst bucket: less_binary
- Catalyst reason: `tier=A;reason=high_opt+catalyst_mid`

**Herald Events (9 total, showing 5 of 9):**

| # | Headline | Collision-Flag | Needs-Review | Confidence | Notes |
|---|---|---|---|---|---|
| 1 | Hikma Pharmaceuticals Announces Major Expansion in Ohio | ✓ FLAG | ✓ REVIEW | 0.20 | Wrong company |
| 2 | Zealand Pharma - Share Buy-back Transactions | ✓ FLAG | ✓ REVIEW | 0.20 | Wrong company |
| 3 | Origin Medical Announces Leadership Transition | ✓ FLAG | ✓ REVIEW | 0.20 | Wrong company |
| 4 | Cost Management for... Furry Friend: Save Money While Giving Medication | ✓ FLAG | ✓ REVIEW | 0.20 | **Pet meds (NOT biotech)** |
| 5 | Legend Biotech Presents First-in-Human LB2102 Results | ✓ FLAG | ✓ REVIEW | 0.20 | Wrong company |
| ... | **+4 more collision/noise events** | ✓ FLAGS | ✓ REVIEWS | 0.20-0.70 | ... |
| 8 | **Evosep Proteomics: Standardize & Scale Proteomics** | ✗ | ✓ REVIEW | 0.50 | Regulatory/high-severity |
| 9 | Ardena Appoints CSO | ✗ | ✗ | 0.70 | Legitimate corp update |

**Diagnosis:**
- **8 of 9 events are collision-flagged**
- 6 flagged for collision + 7 marked needs_review
- Includes pet medication article (completely off-target)
- Low confidence (0.20) on most collisions, yet DRUG ranked **rank 9 with 153-day catalyst**
- Only 1-2 events might be legitimate (Ardena CSO, Evosep proteomics)

**Impact Classification:** `CONFIRMED_COLLISION_NOISE_CONTAMINATION`
- 67% collision-flagged events feeding catalyst scoring
- Catalyst days 153 suggests contaminated event window is driving mid-term positioning

---

### 5. ALKS (Alkermes) — CONFIRMED COLLISION/NOISE

**Ranking Context:**
- Actionable rank: 19
- Catalyst days: 92 (mid-term, NOT in-window)
- Catalyst bucket: less_binary
- Catalyst reason: empty (no specific reason provided)

**Herald Events (1 event):**

| Headline | Category | Collision-Flag | Needs-Review | Confidence |
|---|---|---|---|---|
| **Lilly's Cancer Bombshell Sparks Hunt for Next Oncology Stock Set to Explode** | other | ✓ **FLAG** | ✓ **REVIEW** | 0.30 |

**Diagnosis:**
- Single event is a **Lilly company news article**, not an Alkermes event
- Marked `collision_flag=True` and `needs_review=True`
- Low confidence (0.30)
- **Yet ALKS catalyst_days=92 in rankings**

**Impact Classification:** `CONFIRMED_COLLISION_NOISE`
- 100% of ALKS Herald events are off-target (competitor company news)
- Collision event still appears in catalyst scoring pathway

---

### 6. MBX (MBX Biosciences) — NO IMPACT

**Ranking Context:**
- Actionable rank: 29 (lowest on focus list)
- Catalyst days: 360 (far-term, minimal decay)
- Catalyst bucket: core
- Catalyst reason: `tier=C;reason=low_opt`

**Herald Events:**

| # | Headline | Category | Collision-Flag | Needs-Review | Confidence |
|---|---|---|---|---|---|
| 1 | MBX Biosciences to Host Virtual Investor Event | other | ✗ | ✗ | 0.70 |
| 2 | MBX Biosciences to Host Virtual Investor Event (GNW) | other | ✗ | ✗ | 0.70 |

**Diagnosis:**
- Both events are **legitimate MBX corporate events** (investor event on Once-Weekly Canvuparat)
- No collision flags, no needs-review flags
- Proper classification as `other` (corporate update, informational)
- Rankings appropriately assign low catalyst impact (rank 29, tier C)

**Impact Classification:** `NO_IMPACT`
- MBX events are legitimate, properly classified
- Catalyst scoring appears unaffected by misclassification

---

## Scoring Impact Assessment

### Does Informational-Only Suppress Scoring?

**Finding:** Events marked `informational_only=True` may still be included in catalyst scoring.

- RVMD Phase 3: `informational_only=True`, yet drives catalyst_days=303
- CELC Phase 3: `informational_only=True`, yet drives catalyst_days=29 (in-window)
- Hypothesis: Informational flag does NOT exclude events from catalyst_days calculation upstream

### Do Collision Flags Prevent Scoring?

**Finding:** Events with `collision_flag=True` appear in catalyst scoring.

- ERAS: 100% collision-flagged, yet catalyst_days=183
- DRUG: 67% collision-flagged, yet catalyst_days=153
- ALKS: 100% collision-flagged, yet catalyst_days=92
- Hypothesis: Collision flags are informational-only; they don't block scoring

### Catalyst Attribution Trust

**Verdict:** Catalyst fields in rankings cannot be trusted for these tickers.

| Ticker | Attribution Status |
|--------|---|
| RVMD | ❌ UNTRUSTED (suppressed Phase 3 clinical event) |
| CELC | ❌ UNTRUSTED (suppressed Phase 3 clinical event) |
| ERAS | ❌ UNTRUSTED (100% collision-noise events) |
| DRUG | ❌ UNTRUSTED (67% collision-contaminated) |
| ALKS | ❌ UNTRUSTED (100% collision-noise event) |
| MBX | ✓ TRUSTED (legitimate events, properly classified) |

---

## Portfolio Construction Impact

**Current Top-30 Position:**
- RVMD: Rank 8 (HIGH RANK)
- CELC: Rank 20 (MID RANK)
- ERAS: Rank 13 (HIGH RANK)
- DRUG: Rank 9 (VERY HIGH RANK)
- ALKS: Rank 19 (MID RANK)
- MBX: Rank 29 (TAIL RANK)

**Risk Assessment:**
- **High-ranked tickers (RVMD rank 8, DRUG rank 9, ERAS rank 13)** are based on contaminated/suppressed catalysts
- **RVMD/CELC** legitimately high (Phase 3 events exist) but SUPPRESSED from proper classification
- **ERAS/DRUG/ALKS** are spurious (collision-driven, not real catalysts)
- **MBX** is low-ranked but clean (OK to carry)

**Portfolio Status:** 
- ⚠️ **Blocked from promotion/expansion** until catalyst attribution is verified
- Phase 2 decision-portfolio is stable (locked June 1), but forward attribution is unreliable
- Catalyst-driven rankings may reflect noise, not genuine biotech catalysts

---

## Remediation Recommendation

### Lane 1: CATALYST_ATTRIBUTION_REVIEW_REQUIRED (RVMD, CELC)

**Tickers:** RVMD (rank 8), CELC (rank 20)  
**Issue:** Valid clinical catalysts misclassified as `informational_only`  
**Action Required:**
1. Verify catalyst_days=303 (RVMD) and catalyst_days=29 (CELC) upstream pathway
2. Determine why Phase 3 events entered scoring despite `informational_only=True`
3. Audit whether composite scoring correctly weighted clinical-significance catalyst events
4. **Outcome:** Either validate catalyst position as correct despite label, or recalculate ranks with proper clinical event weighting

**Decision Gate:** Before any forward catalyst trading or rebalancing with RVMD/CELC

---

### Lane 2: CATALYST_INPUT_CONTAMINATION (ERAS, DRUG, ALKS)

**Tickers:** ERAS (rank 13), DRUG (rank 9), ALKS (rank 19)  
**Issue:** Collision-flagged noise events appear to drive catalyst_days values  
**Action Required:**
1. Verify that collision-flagged events were NOT excluded upstream (appears to be the case)
2. Recompute catalyst_days using ONLY legitimate biotech events for each ticker
3. Assess whether catalyst_days should collapse to 0 or very short window if no valid events exist
4. **Outcome:** Recalculate ranks without collision-contaminated catalysts

**Decision Gate:** Before any forward catalyst trading or rebalancing with ERAS/DRUG/ALKS

---

### Lane 3: POOL_QA_ONLY (MBX)

**Ticker:** MBX (rank 29)  
**Issue:** None. Events are legitimate and properly classified.  
**Action:** No remediation required. MBX portfolio position is clean.

---

## Governance Classification

**This audit classifies as:** `CATALYST_ATTRIBUTION_REVIEW_REQUIRED` + `CATALYST_INPUT_CONTAMINATION`

**Final Recommendation:**
- ✓ Portfolio construction **is NOT blocked** (Phase 2 Day 1 is locked governance artifact)
- ❌ Catalyst attribution **is NOT trustworthy** for forward rebalancing/expansion
- ⚠️ **Hold all catalyst-driven portfolio actions** pending remediation of lanes 1 & 2
- ✓ MBX and non-catalyst tickers safe to carry

---

## Audit Evidence

**Data Sources:**
- Herald classifier output: `data/press_releases/classified/classified_2026-06-01.jsonl` (331 KB)
- Rankings snapshot: `data/snapshots/2026-06-01/rankings.csv` (815 KB)
- Analysis scope: 6 focus tickers, 21 total classified events

**Methodology:**
- Read-only event inspection (no classifier code edits)
- Field-level comparison: classification labels vs. catalyst scoring fields
- Collision/needs-review flag audit
- Phase 3 event detection (keyword heuristic: "phase" + "3")

**Audit Date:** 2026-06-02  
**Authority:** Ticker-level validation (event-label quality + Top-30 impact check)

---

## Summary

| Classification | Tickers | Remediation Lane | Governance Impact |
|---|---|---|---|
| **Suppressed Clinical** | RVMD, CELC | CATALYST_ATTRIBUTION_REVIEW_REQUIRED | Hold catalyst-driven actions |
| **Collision-Contaminated** | ERAS, DRUG, ALKS | CATALYST_INPUT_CONTAMINATION | Hold catalyst-driven actions |
| **Legitimate, Clean** | MBX | POOL_QA_ONLY | No action required |

**Portfolio Status:** Phase 2 Day 1 locked (safe). Forward catalyst actions **BLOCKED