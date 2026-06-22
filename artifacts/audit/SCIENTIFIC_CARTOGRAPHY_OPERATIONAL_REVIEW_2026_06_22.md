# Scientific Cartography Phase 12.1 Operational Review
**Date:** 2026-06-22
**Verdict:** PASS_SCIENTIFIC_CARTOGRAPHY_OPERATIONAL_REVIEW_NO_MODEL_CHANGE

---

## Run Health

- Status: `success`, 0 errors, 0 warnings, 9/9 artifacts written
- Governance flags: all correct (`read_only_diagnostic=True`, everything else `False`)

---

## Counts vs Golden (2026-06-17) — Identical Across Every Metric

| Metric | Value |
|--------|-------|
| Programs | 71,284 |
| Clusters | 6,794 |
| Diseases | 6,760 |
| Phase breakdown | Unchanged |
| Mechanism coverage | Unchanged |

No regressions.

---

## Disease Map Quality

- **100% source_ref coverage** — all 6,760 diseases and 6,794 clusters have at least one NCT ID
- Disease names are readable and clinically meaningful (type 2 diabetes, lymphoma, breast cancer, NSCLC, etc.)
- Notable artifact: **"Healthy" (707 programs)** — CTGov control-arm trials, not a disease indication; flag for a future `control_arm_filter`

---

## Landscape Features

| Metric | Value | Notes |
|--------|-------|-------|
| Stage crowding | 54,209 / 71,284 (76.1%) | Healthy; 23.9% gap = 17,075 unknown-stage programs |
| Mechanism crowding | 53 / 71,284 (0.1%) | Known gap — MechanismNormalizer covers screener universe only |
| Mean white_space | 0.909 | Expected given CTGov fragmentation at exact cluster key granularity |

---

## Known Pre-Existing Gaps (Unchanged from Golden, All Documented)

| Gap | Status |
|-----|--------|
| `therapeutic_area = null` for all 6,760 diseases | Highest future UX value; needs MONDO-to-area lookup |
| Mechanism class: 99.9% unknown | Normalizer scope limited to screener universe |
| Public ticker linkage: 0/291 screener tickers | Enrichment path not wired |
| Confidence score: all 0.0 | Not yet implemented |

---

## Scoring Isolation Verification

`ranker_v2_score`, `final_score`, `selector_score`: not present in any artifact. No tracked file mutations.

**Governance status: CLEAN — READ_ONLY_DIAGNOSTIC confirmed.**
