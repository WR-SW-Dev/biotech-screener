# Scientific Cartography Phase 12.1 — Disease Map Operational Review

**Date:** 2026-06-23  
**Governance:** READ_ONLY_DIAGNOSTIC — no scoring, ranker, selector, or portfolio changes  
**Artifacts reviewed:** `artifacts/scientific_cartography/2026-06-22/` (pre-fix baseline)  
**Post-fix artifacts:** `artifacts/scientific_cartography/2026-06-23-postfix/` (fixed normalizer)  

---

## Summary

The 2026-06-22 artifacts were generated with a buggy disease normalizer that produced a **35.1% mis-normalization rate** and **zero ticker linkage**. A normalizer fix committed today (`697c0b83`) drops mis-normalization to **13.8%** and restores **97.9% ticker linkage** using the correct trial data input (`production_data/trial_records.json`). Three structural issues remain open: confidence scoring is structurally zero for all records, residual substring false positives at 13.8%, and therapeutic_area / mechanism_class are null throughout.

---

## Artifact Quality: Pre-Fix vs Post-Fix

| Metric | 2026-06-22 (pre-fix) | 2026-06-23 (post-fix) | Delta |
|---|---|---|---|
| Total program records | 71,284 | 73,075 | +1,791 |
| With ticker linkage | 0 (0%) | 71,589 (97.9%) | **+97.9pp** |
| Mis-normalization rate | 25,042 (35.1%) | 10,082 (13.8%) | **−21.3pp** |
| confidence == 0.0 | 71,284 (100%) | 73,075 (100%) | unchanged |
| therapeutic_area non-null | 0 (0%) | 0 (0%) | unchanged |
| mechanism_class non-null | 53 (0.07%) | — | — |

---

## Root Cause Analysis

### 1. Short-alias substring false positives (FIXED — `697c0b83`)

The disease normalizer indexed short MONDO synonyms directly into the lookup dictionary and then applied substring matching. Two short aliases caused cascading mis-mapping:

- **"RA"** (synonym for *rheumatoid arthritis*): any indication containing the substring "ra" matched — e.g., "Hepatitis Ch**ra**nic Viral" → *rheumatoid arthritis* (6,667 records in pre-fix)
- **"AD"** (synonym for *atopic dermatitis*): any indication containing "ad" matched — e.g., "B-cell **Ad**ult Acute Lymphoblastic Leukemia" → *atopic dermatitis* (5,668 records)

Fix: removed direct synonym indexing from the lookup table; synonyms are now matched only as exact-synonym strings (Priority 5). Substring matching (Priority 6) now skips any MONDO term shorter than 4 characters. Both false-positive disease targets drop to zero in post-fix artifacts.

### 2. Incorrect trial data input (FIXED in post-fix run)

The diagnostic wrapper was pointed at `production_data/ctgov_state/` which contains raw state snapshots but no `trials.json`. The correct input is `production_data/trial_records.json` (20,057 records, includes `ticker` field). This explains `ticker_count: 0` in all prior sci-cart artifacts. Post-fix run uses the correct file → 97.9% ticker linkage.

### 3. Confidence always zero (OPEN — design issue)

`ProgramRecord.confidence` is computed as:

```python
overall_confidence = min(
    asset_confidence,           # always 0.0 — asset alias resolver finds no match
    sponsor_public_factor,      # 1.0 or 0.7
    disease_confidence,         # 0.0–1.0 based on normalizer match
    stage_factor,               # 0.8 or 0.6
)
```

`asset_alias_resolver.resolve()` returns `None` for all interventions (intervention names from CT.gov are not in any asset alias dictionary). This propagates `asset_confidence = 0.0`, which collapses the `min()` to zero regardless of disease or sponsor quality.

**Effect:** Downstream filtering in `asset_indication_builder.py` (line 114: `if not program.disease_name or program.confidence < 0.5`) may suppress otherwise valid records. The map_index `ticker_count: 0` in prior runs was also a consequence of this — zero-confidence records were being excluded from ticker aggregation.

**Not a normalizer bug.** This is a design choice where asset resolution gates overall confidence. The asset alias database (if it exists) is either empty or not wired. Fixing this requires either: (a) populating the asset alias resolver, or (b) decoupling asset confidence from the overall confidence floor.

### 4. Residual mis-normalization at 13.8% (OPEN)

After the fix, the top remaining false-positive targets are:

| Mapped-to disease | Records | Example indication |
|---|---|---|
| lymphoma | 4,116 | "Transformed CLL to Diffuse Large B-Cell Lymphoma", "Grade 1 Follicular Lymphoma" |
| breast cancer | 1,604 | "Stage IIA Breast Cancer AJCC v6", "HR+ Breast Cancer" |
| non-small cell lung cancer | 1,193 | "EGFR-mutated NSCLC", "Non-small Cell Lung Cancer Stage III" |
| colorectal cancer | 739 | "Stage III Colon Cancer" |
| melanoma | 619 | "Advanced Melanoma", "Stage IIIB Uveal Melanoma" |

**Character of remaining mismatches:** These are plausibly correct normalizations (e.g., "Stage IIA Breast Cancer" → *breast cancer*) or legitimate substring matches where a specific subtype maps to the parent MONDO term. They are not obviously wrong in the way "viral" → *rheumatoid arthritis* was. A manual sample review is needed to distinguish true positives from false positives.

### 5. Null therapeutic_area throughout (OPEN)

`asset_indication_builder.py` hardcodes `therapeutic_area=None`. MONDO records carry `therapeutic_area` in their ontology; it was not wired into `DiseaseRecord` propagation or `ProgramRecord` construction. This is a known gap, not a regression.

---

## Disease Map Quality Spot-Check (Post-Fix)

Sample from `artifacts/scientific_cartography/2026-06-23-postfix/`:

**Correct normalizations (expected):**
- "Obesity" → `MONDO:0004994` *obesity*
- "Small Cell Lung Cancer" → `MONDO:0005235` *small cell lung cancer*
- "Atopic Dermatitis" → `MONDO:0004980` *atopic dermatitis* ✅ (correct via exact match)

**Previously broken, now correct:**
- "Prader-Willi Syndrome" → unmapped (was *atopic dermatitis* via "AD" alias) ✅
- "Hepatitis Chronic Viral" → unmapped (was *rheumatoid arthritis* via "RA" alias) ✅
- "Vasomotor Symptoms Associated With Menopause" → unmapped (was *multiple sclerosis*) ✅

---

## Recommendations

| # | Issue | Severity | Action | Phase |
|---|---|---|---|---|
| R1 | Adopt 2026-06-23-postfix artifacts as working baseline | High | Rename/promote after operator review | Now |
| R2 | Fix ctgov_cache input path in cron/scheduled runs | High | Point to `production_data/trial_records.json` | Now |
| R3 | Decouple asset_confidence from overall confidence floor | Medium | Allow disease+sponsor confidence when asset unresolved | Phase 13 |
| R4 | Manual sample of residual 13.8% mis-normalizations | Medium | 50-record review; classify true vs false positive | Phase 13 |
| R5 | Wire therapeutic_area from MONDO into DiseaseRecord | Low | Propagate `therapeutic_area` from ontology build | Phase 13 |
| R6 | Mechanism normalizer coverage | Low | 99.9% unknown; separate workstream | Phase 13+ |

---

## What Is NOT Changing

- No ranker, selector, sizing, final_score, or portfolio changes
- No Sci-Cart fields wired into any scoring system
- No production snapshot modifications
- All Sci-Cart outputs remain `READ_ONLY_DIAGNOSTIC`

---

## Verdict

**Phase 12.1 operational review COMPLETE.**  
The 2026-06-22 baseline was severely degraded by two short-alias bugs now fixed. The post-fix 2026-06-23 artifacts represent a substantive improvement and are suitable as the new working baseline pending operator review of R1–R2. Three structural gaps (confidence, residual normalization, therapeutic_area) are documented and deferred to Phase 13.
