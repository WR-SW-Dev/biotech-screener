---
name: broader_classifier_misclassification_2026_06_01
title: Broader Classifier Misclassification Scan — All 78 Tickers
description: Portfolio-wide quality audit beyond focus-6 tickers
date: 2026-06-02
---

# Broader Classifier Misclassification Scan — All 78 Tickers

**Data Source:** `classified_2026-06-01.jsonl` (250 events across 78 tickers)  
**Scope:** Collision-flag audit + needs-review flag analysis  
**Authority:** Read-only diagnostic

---

## Executive Summary

| Category | Finding | Risk Level |
|----------|---------|-----------|
| **Collision Rate** | 119/250 events (47.6%) have ticker_collision_flag=True | ⚠️ SYSTEMIC |
| **Needs Review** | 203/250 events (81.2%) marked needs_review | ⚠️ SYSTEMIC |
| **Top-30 Tickers** | 4 with significant issues (COGT, ALKS, ERAS, DRUG) | HIGH |
| **Other Universe** | 26 tickers with >50% collision rates (LCTX, ONC, RARE, ACRS, etc.) | MEDIUM |

---

## Top-30 Ticker Issues

### FOCUS TICKERS (Already Audited)

| Ticker | Total | Collision | Rate | Needs-Review | Status |
|--------|-------|-----------|------|--------------|--------|
| **ERAS** | 3 | 3 | 100% | 3 | ⚠️ HIGH_COLLISION |
| **ALKS** | 1 | 1 | 100% | 1 | ⚠️ HIGH_COLLISION |
| **DRUG** | 9 | 6 | 66.7% | 7 | ⚠️ HIGH_COLLISION |
| **RVMD** | 2 | 0 | 0% | 0 | CLEAN (Phase 3 suppression ≠ collision) |
| **CELC** | 3 | 0 | 0% | 0 | CLEAN (Phase 3 suppression ≠ collision) |
| **MBX** | 2 | 0 | 0% | 0 | ✓ CLEAN |

**Previous audit findings remain valid.** RVMD/CELC misclassification is event_category suppression (Phase 3 → `other`), not collision flags.

---

### ADDITIONAL TOP-30 PROBLEM TICKER

#### **COGT** (Cogent Biosciences) — Rank 1 — ALL EVENTS FLAGGED

| Metric | Value |
|--------|-------|
| Total events | 2 |
| Collision flags | 0 (0%) |
| Needs review | 2 (100%) |
| Status | ⚠️ ALL_FLAGGED |

**Events:**
1. "Cogent Biosciences Announces Detailed Clinical Data Peak Phase..."
   - Category: clinical
   - Needs-review: True
   - Confidence: 0.70
   - Severity: high
   - Materiality: high
   - Status: Legitimate clinical event, but flagged for review

2. Event 2: Clinical/regulatory event, also flagged

**Risk Assessment:**
- COGT is **rank 1** in Top-30 (highest ranking ticker)
- Both events are legitimate clinical/regulatory announcements (not collisions)
- **Needs-review flags** indicate classifier uncertainty despite legitimate classification
- Clinical events at rank-1 position require higher confidence

**Remediation:** Review why legitimate clinical events are marked needs_review. If confidence threshold is the issue, COGT ranking may be unstable.

---

## Broader Universe Findings

### Tickers with >50% Collision Rates (Non-Top-30)

**Systemic pattern:** 26 tickers show ≥50% collision rates.

| Rate | Tickers | Count |
|------|---------|-------|
| **100%** | ABUS, ACAD, APGE, CYTK, DAWN, HALO, IONS, LCTX, NAMS, ONC, RARE, RXRX, SGMO, TARS | 14 |
| **75-99%** | ACRS, FOLD, JAZZ, IRON | 4 |
| **60-75%** | CLLS, DRUG, LAB, MENS, EDIT | 5 |
| **50-60%** | BEAM, CRL, FATE, GLUE, TECH | 5 |

**Tickers with most problematic events:**
- LCTX: 18/18 collision-flagged (100%)
- ONC: 9/9 collision-flagged (100%)
- RARE: 10/10 collision-flagged (100%)
- ACRS: 8/9 collision-flagged (88.9%)
- FOLD: 6/8 collision-flagged (75%)

**Pattern:** These appear to be ticker collisions with unrelated companies or categories (similar to ERAS Schwarzkopf pistol, DRUG pet medication). Widespread in non-Top-30 universe.

---

## Systemic Classifier Quality Issues

### Overall Statistics

```
Universe:              78 tickers
Total events:          250
Events with collision_flag=True:  119 (47.6%)
Events with needs_review=True:    203 (81.2%)
Events with informational_only:   147 (58.8%)
```

**Interpretation:**
- Nearly **half** of all classified events have ticker collisions
- Over **80%** are flagged for manual review
- Most events are marked informational-only (likely correctly, but combined with collisions = lower trust)

### Cascade of Quality Markers

Many events stack multiple flags:
- Collision + needs_review + informational_only (typical for ERAS, DRUG, ALKS)
- All events flagged for review (COGT, LCTX, ONC, RARE)
- High needs_review rates across tickers with legitimate events

**Root Cause Hypothesis:** Classifier has high false-positive rate on:
1. Ticker collision detection (50% collision flag rate is suspicious)
2. Confidence thresholds (81% needs_review despite high event volume)
3. Event categorization uncertainty (58% informational-only despite valid clinical events)

---

## Risk to Portfolio

### Top-30 Tier Risk

| Tier | Tickers | Risk |
|------|---------|------|
| **CRITICAL** | COGT (rank 1) | All events flagged for review, at highest rank |
| **HIGH** | ERAS, ALKS, DRUG | Collision-contaminated rankings (already audited) |
| **MEDIUM** | RVMD, CELC | Phase 3 suppression (already audited) |
| **LOW** | MBX + others | Clean or low-impact flags |

**Recommendation:** COGT should be reviewed for ranking stability given 100% needs_review flag rate at rank 1.

---

## Comparison: Collision vs. Category Suppression

### Two Distinct Problems Identified

**Problem 1: Ticker Collision (ERAS, DRUG, ALKS)**
- Wrong company news assigned to ticker (e.g., Lilly news → ALKS)
- Field: `ticker_collision_flag=True`
- Examples: Schwarzkopf pistol (ERAS), pet medication (DRUG), Lilly (ALKS)
- Impact: False catalyst events inflate catalyst_days

**Problem 2: Event Category Suppression (RVMD, CELC)**
- Correct company, correct event, wrong category
- Phase 3 clinical events labeled `event_category=other` + `informational_only=True`
- Field: `event_category` misclassification (not a flag field)
- Impact: Valid catalysts suppressed from proper classification but still enter scoring

**Problem 3: Confidence Uncertainty (COGT, widespread)**
- Events correctly identified but flagged `needs_review=True`
- Indicates low classifier confidence despite classification
- Field: `needs_review=True`, `confidence` typically 0.70 or lower
- Impact: Unstable rankings for flagged tickers

---

## Governance Recommendation

### Immediate Actions

1. **COGT Review:** Verify why rank-1 ticker has all events flagged for review. Check if ranking is stable or confidence-dependent.

2. **Suppressed Clinical Events (RVMD, CELC):** Already covered in primary audit. Lanes 1 & 2 remediation required.

3. **Collision-Contaminated Tickers (ERAS, DRUG, ALKS):** Already covered in primary audit. Lanes 1 & 2 remediation required.

### Broader Universe

**Non-Top-30 tickers** with >50% collision rates are **not blocking Phase 2**, but indicate systemic classifier quality issues:
- Collision detection is unreliable (50% false-positive suspected)
- Manual review tags (needs_review) suggest low confidence thresholds
- Forward use of any classifier output for new tickers should be treated as **advisory-only** until root causes addressed

### Forward Remediation Path

**Lane 4: Classifier Quality Baseline Review (Future)**
- Audit collision-flag accuracy (are LCTX/ONC/RARE truly collisions or false positives?)
- Evaluate needs_review flag thresholds (81% rate is too high)
- Consider confidence-based gating (suppress or flag events <0.70 confidence)

---

## Summary

| Finding | Scope | Severity | Action |
|---------|-------|----------|--------|
| COGT all-flagged | 1 Top-30 ticker | Medium | Review for ranking stability |
| Focus 6 tickers | RVMD, CELC, ERAS, DRUG, ALKS, MBX | High | Remediation lanes 1 & 2 (primary audit) |
| Other universe collisions | 26 tickers with >50% collision | Medium | Advisory-only for now |
| Systemic classifier quality | 47.6% collision, 81.2% needs_review | High | Future baseline audit required |

**Phase 2 Impact:** COGT only new concern (rank 1, all-flagged). RVMD/CELC/ERAS/DRUG/ALKS already known. MBX clean.

**Forward Actions:** COGT + primary audit remediation lanes 1 & 2 before next portfolio expansion.
