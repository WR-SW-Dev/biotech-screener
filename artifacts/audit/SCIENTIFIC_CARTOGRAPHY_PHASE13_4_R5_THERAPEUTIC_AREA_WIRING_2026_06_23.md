# Scientific Cartography Phase 13.4 — R5 Therapeutic Area Wiring
**Date:** 2026-06-23
**Status:** PASS
**Verdict:** `PASS_R5_THERAPEUTIC_AREA_WIRED_DIAGNOSTIC_ONLY`

---

## 1. Problem Statement

`ProgramRecord.therapeutic_area` was hardcoded to `None` in
`AssetIndicationBuilder._create_program_from_trial()`:

```python
therapeutic_area=None,  # Will be computed later if needed
```

`DiseaseNormalizer.normalize()` already returns `therapeutic_area` in every
`DiseaseRecord` for MONDO-matched diseases. The normalizer had a curated
17-disease MONDO index spanning Oncology, Dermatology, Immunology,
Gastroenterology, Neurology, and Metabolic areas. The builder had access to
`disease_record.therapeutic_area` immediately after the `normalize()` call
but discarded it.

---

## 2. Fix Applied

**File:** `scientific_cartography/build/asset_indication_builder.py`

One-line change:

```python
# Before
therapeutic_area=None,  # Will be computed later if needed

# After
therapeutic_area=disease_record.therapeutic_area,
```

This propagates `therapeutic_area` when the disease normalizer resolves to a
MONDO entry with known therapeutic area. When the disease is unmapped
(`source="unmapped"`, `confidence=0.0`), `therapeutic_area` remains `None` —
the existing fallback behavior is preserved.

**File:** `tools/run_scientific_cartography_diagnostics.py`

Added a therapeutic_area coverage report block after program build, written
to `status["therapeutic_area_coverage"]`:

```json
{
  "total_programs": N,
  "with_therapeutic_area": K,
  "without_therapeutic_area": N-K,
  "coverage_pct": X.X,
  "top_areas": [["Oncology", n], ...]
}
```

---

## 3. Downstream Propagation

Because `CompetitiveClusterBuilder` already reads `first.therapeutic_area`
from the first member `ProgramRecord`, clusters automatically inherit the
populated value — no cluster builder changes required.

Similarly, `DiseaseMapExporter`, `MapIndexExporter`, and
`DiseaseMapArtifactExporter` already read `program.therapeutic_area` and
`cluster.therapeutic_area` — no exporter changes required.

The change is fully additive. No existing consumer is broken because all
downstream consumers already handle the field; they were simply receiving
`None` on every record.

---

## 4. Expected Coverage

The built-in MONDO index covers 17 curated diseases across 6 therapeutic
areas. The conservative phrase-matching in the normalizer extends this to
disease label variants (e.g., "moderate-to-severe atopic dermatitis" →
"Dermatology"). Diseases outside the index remain `None`.

Coverage will be low in absolute terms (the index is intentionally small and
manually curated), but every non-null value is ontology-backed with
confidence ≥ 0.80 — no guessing from ticker, company name, or free-text.

Expected top therapeutic areas from the biotech CT.gov universe:
- Oncology (largest; many cancer trial registrations)
- Neurology (Alzheimer's, Parkinson's, MS)
- Dermatology (atopic dermatitis, psoriasis)
- Immunology/Gastroenterology (RA, IBD)

---

## 5. Tests Added

**File:** `tests/scientific_cartography/test_asset_indication_builder.py`
**Class:** `TestTherapeuticAreaWiringR5` (6 new tests)

| Test | Behavior Verified |
|------|------------------|
| `test_mondo_mapped_disease_populates_therapeutic_area` | NSCLC → Oncology |
| `test_mondo_dermatology_disease_populates_therapeutic_area` | Atopic Dermatitis → Dermatology |
| `test_mondo_neurology_disease_populates_therapeutic_area` | Parkinson's → Neurology |
| `test_unknown_disease_leaves_therapeutic_area_none` | Unmapped disease → None |
| `test_therapeutic_area_survives_to_dict_roundtrip` | Field survives serialization |
| `test_therapeutic_area_propagates_to_cluster` | Cluster inherits from program |

---

## 6. Test Results

```
399 passed in 7.22s
```

All Phase 0–13 Sci-Cart tests pass. 6 new R5 tests pass.

---

## 7. Governance Constraints Preserved

- READ_ONLY_DIAGNOSTIC: no production model files modified
- No ranker, selector, sizing, final_score, gates, or snapshot changes
- No alpha claims; no trading/action language
- No live fetch or API calls
- No cron/scheduler
- Production model freeze remains ACTIVE

---

## 8. Scope Boundary

- No new ontology data added (MONDO index is unchanged)
- No inference from ticker, company name, asset name, or free-text indication
- No scoring integration
- No `therapeutic_area` added to `DiseaseRecord.from_dict()` (already present)
- No changes to disease normalizer confidence logic

---

## 9. Map UX Impact

With `therapeutic_area` now populated from MONDO, the disease map artifacts
(`map_index.json`, `disease_map_summary.json`) will carry non-null
therapeutic areas for MONDO-resolved records. This enables the planned
grouping/filtering UI (e.g., "show only Oncology clusters") without any
further schema changes — the field was already plumbed through every
exporter.

---

## 10. Next Steps

- R6: Mechanism coverage design memo (DESIGN_ONLY — no code)
