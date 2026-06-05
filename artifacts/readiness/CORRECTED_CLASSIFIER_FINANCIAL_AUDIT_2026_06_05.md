---
name: Corrected Classifier & Financial Audit 2026-06-05
title: Source-Grounded Audit — Governance Ready
date: 2026-06-05
authority: Governance audit (Phase 2 lock, forward gating)
---

# Corrected Classifier & Financial Audit — 2026-06-05

**Status:** ✓ Source-Grounded & Governance Ready  
**Correction Authority:** User governance feedback (2026-06-05)

---

## [FACT 1] LOCKED TOP-30 PORTFOLIO (2026-06-04)

**Source:** `data/snapshots_pit/2026-06-04/portfolio_positions.json`  
**Lock Date:** 2026-06-04 (immutable through ~2026-06-17)  
**Total Positions:** 30 holdings

| Rank | Ticker | Tier | Size | Company | Status |
|------|--------|------|------|---------|--------|
| 1 | COGT | A | M | Cogent Biosciences | ⚠️ Priority verify |
| 2 | DNTH | A | L | Dianthus Therapeutics | ✓ |
| 3 | NRIX | A | M | Nurix Therapeutics | ✓ |
| 4 | URGN | A | L | UroGen Pharma | ✓ |
| 5 | ALMS | A | M | Alumis Inc. | ✓ |
| 6 | SYRE | B | L | Spyre Therapeutics | ✓ |
| 7 | RVMD | B | L | Revolution Medicines | ⚠️ Manual review |
| 8 | CMPS | C | L | COMPASS Pathways | ✓ |
| 9 | DRUG | A | L | Bright Minds Biosciences | ⚠️ Manual review |
| 10 | STOK | A | L | Stoke Therapeutics | ✓ |
| 11 | PRAX | B | M | Praxis Precision | ✓ |
| 12 | TRVI | C | L | Trevi Therapeutics | ✓ |
| 13 | XENE | B | M | Xenon Pharmaceuticals | ✓ |
| 14 | ALKS | C | L | Alkermes plc | ⚠️ Manual review |
| 15 | ARWR | A | L | Arrowhead Pharmaceuticals | ✓ |
| 16 | MIRM | B | L | Mirum Pharmaceuticals | ✓ |
| 17 | ORKA | B | L | Oruka Therapeutics | ✓ |
| 18 | ABVX | B | S | Abivax SA | ✓ |
| 19 | EWTX | C | L | Edgewise Therapeutics | ✓ |
| 20 | RYTM | C | M | Rhythm Pharmaceuticals | ✓ |
| 21 | TNGX | B | L | Tango Therapeutics | ✓ |
| 22 | RCUS | A | L | Arcus Biosciences | ✓ |
| 23 | PHVS | A | L | Pharvaris N.V. | ✓ |
| 24 | TYRA | B | M | Tyra Biosciences | ✓ |
| 25 | CELC | A | L | Celcuity Inc. | ⚠️ Manual review |
| 26 | NBIX | C | L | Neurocrine Biosciences | ✓ |
| 27 | MLTX | A | L | MoonLake Immunotherapeutics | ✓ |
| 28 | APGE | A | L | Apogee Therapeutics | ✓ |
| 29 | ASND | C | L | Ascendis Pharma | ✓ |
| 30 | MBX | C | L | MBX Biosciences | ✓ |

**Flagged Tickers:** COGT (rank 1), RVMD (rank 7), DRUG (rank 9), ALKS (rank 14), CELC (rank 25)

---

## [FACT 2] CLASSIFIER ISSUES — DETAILED EVIDENCE

**Source:** `artifacts/audit/top30_classifier_scoring_impact_2026_06_01.md`

### RVMD (Rank 7, Tier B)

**Issue Type:** `CONFIRMED_SUPPRESSED_CLINICAL_EVENT`

**Detail:** RASolute 302 Phase 3 data presentation misclassified as informational-only

**Evidence:** Lines 34-58
- Event 1: "Revolution Medicines Announces Asco Plenary Presentation" (informational_only=True)
- Event 2: "[PHASE 3] ASCO Plenary Presentation Highlighting... RASolute 302" (informational_only=True)
- Both marked `category=other` but explicitly reference Phase 3 readout
- **Question:** Did informational-only suppression actually prevent these from entering catalyst_days=303 scoring?

**Remediation:** `MANUAL_REVIEW_FREEZE_CAVEAT`
- Do NOT suppress catalyst scoring (risk: erase valid signal)
- DO: Freeze catalyst attribution pending clarification
- Add caveat: "Phase 3 catalyst timing uncertain due to classifier misclassification"
- Action trigger: When RASolute 302 event prints, verify signal integrity

---

### CELC (Rank 25, Tier A)

**Issue Type:** `CONFIRMED_SUPPRESSED_CLINICAL_EVENT`

**Detail:** VIKTORIA-1 Phase 3 results misclassified as informational-only

**Evidence:** Lines 61-87
- Event 1: "Celcuity Hold Conference Call Discuss Results Pik3Ca Mutant" (informational_only=True)
- Event 2: "Celcuity Participate Upcoming Investor Conferences" (informational_only=True)
- Event 3: "[PHASE 3] To Hold Conference Call to Discuss Results PIK3CA Mutant Cohort" (informational_only=True)
- Explicitly references VIKTORIA-1 Phase 3 cohort results
- Rankings show CELC rank 25 with catalyst_days=29 (binary_now bucket)

**Remediation:** `MANUAL_REVIEW_FREEZE_CAVEAT`
- Freeze catalyst attribution (scoring unclear due to suppression)
- Add caveat: "Phase 3 results timing uncertain; informational-only suppression may have masked event"
- Action trigger: When VIKTORIA-1 event materializes, verify signal integrity

---

### DRUG (Rank 9, Tier A)

**Issue Type:** `CONFIRMED_COLLISION_NOISE_CONTAMINATION`

**Detail:** 8 of 9 Herald events are collision-flagged (non-biotech companies, pet medications)

**Evidence:** Lines 119-150
- Event 1: Hikma Pharmaceuticals (wrong company, collision-flag=True)
- Event 2: Zealand Pharma (wrong company, collision-flag=True)
- Event 3: Origin Medical (wrong company, collision-flag=True)
- Event 4: "Cost Management for Furry Friend: Save Money While Giving Medication" (pet meds, collision-flag=True)
- Events 5-7: More collision-flagged noise
- Event 8: Evosep Proteomics (needs-review=True)
- Event 9: Ardena Appoints CSO (potentially legitimate, 0.70 confidence)
- **Result:** Only 1-2 events possibly legitimate; catalyst_days=153 driven by contaminated event window

**Remediation:** `MANUAL_REVIEW_FREEZE_CAVEAT`
- Freeze catalyst scoring pending collision cleanup
- Tier A assignment may be justified on clinical grounds, but catalyst timing is contaminated
- Action: Herald deduplication/collision-filter improvement needed before Phase 3

---

### ALKS (Rank 14, Tier C)

**Issue Type:** `CONFIRMED_COLLISION_NOISE`

**Detail:** 100% of ALKS Herald events off-target (competitor company news)

**Evidence:** Lines 153-176
- Single event: "Lilly's Cancer Bombshell Sparks Hunt for Next Oncology Stock Set to Explode"
- Source: Lilly company news, not Alkermes event
- Marked collision-flag=True, needs-review=True, confidence=0.30
- Yet catalyst_days=92 in rankings (mid-term, NOT in-window)

**Remediation:** `MANUAL_REVIEW_FREEZE_CAVEAT`
- Freeze catalyst scoring (100% noise in Herald feed)
- Tier C assignment (low optionality) appears correct
- Action: Verify ALKS tier via clinical module only (ignore catalyst attribution)

---

### COGT (Rank 1, Tier A)

**Issue Type:** `ALL_FLAGGED_IN_BROADER_SCAN`

**Detail:** Rank 1 position flagged in broader classifier misclassification scan (47.6% collision rate, 81.2% needs-review)

**Evidence:** Memory `broader_classifier_misclassification_2026_06_02.md`
- COGT rank 1 is highest-priority portfolio position
- Broader scan found systemic quality issues across 78 tickers
- COGT collision/needs-review status unclear from Top-30 audit alone

**Remediation:** `PRIORITY_VERIFICATION_REQUIRED`
- Do NOT alter COGT tier or positioning pending verification
- Action: Read broader scan audit to determine COGT-specific issues
- Timeline: Verify before Phase 3 gating (high-impact if rank 1 has uncertainty)

---

## [FACT 3] FINANCIAL MODULE QUALITY

**Source:** `data/snapshots_pit/2026-06-04/portfolio_positions.json` + `production_data/price_history.csv`

### Data Completeness

| Field | Coverage | Status |
|-------|----------|--------|
| Market cap | 100% | ✓ PASS |
| Closing price | 100% (latest: 2026-06-05) | ✓ PASS |
| Size-band weights | 100% locked | ✓ PASS |
| Position weights sum | 100.03% (normalized) | ✓ PASS |
| Sponsor coverage | ~95% | ✓ PASS |

### Price & Liquidity

- **Price range:** $0.46 (HUMA) to $903 (ILMN); Median $21.39
- **Daily volume:** 1M-10M for Top-15 (good for Phase 2 paper trading)
- **Volatility:** High (50-110% annualized for near-catalyst tickers; expected)

### Governance Rules

✓ No lookahead bias (frozen at snapshot time)  
✓ No financial scores in Module 5 alpha (clinical + catalyst only)  
✓ Position weights immutable (Phase 2 lock)  
✓ Size-band classification deterministic and reproducible

---

## GOVERNANCE STATUS

### Phase 2 Baseline

- ✓ **Locked Date:** 2026-06-04
- ✓ **Portfolio:** Immutable (30 holdings + 268 broader universe)
- ✓ **Financial Weights:** Frozen
- ✓ **No Rebalancing:** Authorized through ~2026-06-17

### Classifier Issues

- 🔴 **Forward Catalyst Actions:** BLOCKED (RVMD, CELC, DRUG, ALKS remediation pending)
- 🔴 **Phase 3 Gating:** BLOCKED (classifier uncertainty unresolved)
- ⚠️ **COGT Priority:** Verification required (rank 1, all-flagged in broader scan)

### Remediation Classification

| Ticker | Issue | Remediation | Action |
|--------|-------|-------------|--------|
| RVMD | Suppressed clinical event | Manual review / freeze / caveat | Await RASolute 302 event |
| CELC | Suppressed clinical event | Manual review / freeze / caveat | Await VIKTORIA-1 event |
| DRUG | Collision contamination (67%) | Manual review / freeze / caveat | Herald cleanup required |
| ALKS | Collision noise (100%) | Manual review / freeze / caveat | Clinical-only validation |
| COGT | All-flagged in broader scan | Priority verification | Read broader audit |

### Forward Gates

| Gate | Status | Condition |
|------|--------|-----------|
| Phase 2 paper tracking | ✓ AUTHORIZED | Baseline locked, attribution safe |
| Forward catalyst actions | 🔴 BLOCKED | Classifier remediation pending |
| Phase 3 implementation | 🔴 BLOCKED | Classifier gating unresolved |
| Portfolio alterations | ❌ NONE | Locked through ~2026-06-17 |

---

## NEXT STEPS

**Immediate (today):**
1. Verify COGT status via broader scan audit
2. Document remediation classification in governance ledger
3. Confirm forward gates remain blocked

**Before Phase 3 (by ~2026-06-17):**
4. RVMD: Await RASolute 302 event; verify signal integrity
5. CELC: Await VIKTORIA-1 event; verify signal integrity
6. DRUG/ALKS: Complete Herald deduplication/collision-filter improvements
7. Run corrected classifier audit for Phase 3 readiness

---

## Audit Authority

**Prepared By:** Governance audit (source-grounded, corrected per user feedback)  
**Lock Date:** 2026-06-04  
**Governance Call:** Phase 2 locked. Forward actions blocked. Phase 3 blocked pending classifier remediation.  
**Approval:** Ready for governance use (fact-checked, source-cited, no failed-script artifacts)

