# Spec 078 Lane A + Lane B — Diff Report (2026-05-06)

**Snapshot:** `data/snapshots/2026-05-06/rankings.csv`
**Generated:** 2026-05-06

---

## 1. Catalyst event count before / after

No catalyst event types changed. Both lanes have **zero current victims**.

| Metric | Before | After |
|--------|--------|-------|
| Rows with catalyst signal | 261 | 261 (unchanged) |
| binary_now / build_window count | 130 | 130 (unchanged) |
| Lane A (non-binary in binary_now/build_window) | 0 | 0 |
| Lane B (low-conf non-exempt in binary_now/build_window) | 0 | 0 |

---

## 2. catalyst_quality field distribution (new field — additive only)

| catalyst_quality | Count |
|----------------|-------|
| binary_alpha | 82 |
| registry_only | 179 |
| (no catalyst) | 38 |

`binary_alpha` = PDUFA_MANUAL, FDA_ADCOM_CALENDAR, SEC_8K_FILING, SEC_6K_FILING sources.
`registry_only` = CTGOV_CALENDAR, CTGOV_PCD_FAR sources.

---

## 3. Per-ticker delta

None. No ticker lost or gained catalyst credit from Lanes A or B.

---

## 4. Top-30 breakdown

All 30 top names have a legitimate catalyst source. No corporate_update or low_confidence 
entries in the top-30.

Top-30 catalyst_quality split:
- binary_alpha: 16 names (SEC_8K_FILING DATA_READOUT / FDA_PDUFA_DATE / SEC_6K_FILING)
- registry_only: 14 names (CTGOV_CALENDAR CT_PRIMARY_COMPLETION / DATA_READOUT / CT_STUDY_COMPLETION)

---

## 5. Spearman ρ before/after

**Not applicable** — no scoring changes. `catalyst_quality` is a new additive field with no 
weight in any score computation. actionable_rank is byte-identical to pre-implementation.

---

## 6. Negative controls (unaffected)

Verified: TSHA (PDUFA_MANUAL), AXSM (SEC_8K), CELC (SEC_8K), ABVX (SEC_6K) — all 
correctly classified as `binary_alpha`. Rankings unchanged.

---

## 7. Material-change check

Top-30 Jaccard: **1.00** (identical — no scoring changes).
Spearman ρ on `actionable_rank`: **1.00** (rankings byte-identical).

**PASS** — both thresholds (Jaccard ≥ 0.90, ρ ≥ 0.95) met.

---

## 8. What changed

- `run_screen.py`: Added `classify_catalyst_quality()` function + `_NON_BINARY_CATALYST_EVENT_TYPES` / `_CATALYST_QUALITY_EXEMPT_SOURCES` / `_CATALYST_QUALITY_CONF_THRESHOLD` constants. Added `catalyst_quality` field population in Catalyst calendar v2 loop.
- `module_3_catalyst.py`: Added Spec 078 Lane A guard in `convert_corporate_catalyst_to_v2()` — rejects non-binary corporate event types (EARNINGS_RELEASE, INVESTOR_DAY, PARTNERSHIP, MA_ACTIVITY, LICENSING_DEAL, CONFERENCE_PRESENTATION, CONFERENCE_LATE_BREAKER, CONFERENCE_ACCEPTED_ABSTRACT, IR_EVENT, PRESS_RELEASE_EVENT) with debug log. Zero current impact since none of these appear in current corporate catalysts files.
- `tests/test_catalyst_quality_gate.py`: 34 new tests covering Lane A classification, Lane B threshold, module_3 guard, and snapshot smoke tests.

---

## 9. Explicit statement

**No weight changes from this implementation.** Lane A and Lane B are defensive hygiene guards with zero current scoring impact. The `catalyst_quality` field is purely additive and diagnostic.
