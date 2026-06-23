# Scientific Cartography Phase 13.3 — R3 Confidence Redesign
**Date:** 2026-06-23
**Status:** PASS
**Verdict:** `PASS_R3_CONFIDENCE_REDISTRIBUTION_DIAGNOSTIC_ONLY`

---

## 1. Problem Statement

Phase 13 diagnostics identified a structural confidence collapse in
`AssetIndicationBuilder._create_program_from_trial()`. CT.gov intervention
names (e.g., "RMC-6236", "MRTX-1719") are not present in the asset alias
dictionary. Prior to this fix, the builder called:

```python
overall_confidence = min(asset_confidence, sponsor_factor, disease_confidence, stage_factor)
```

When `AssetAliasResolver.resolve()` returned a fallback dict with
`confidence=0.0` and `resolution_status='unknown'`, `asset_confidence=0.0`
collapsed the `min()` to 0.0 for all 73,075 CT.gov-sourced records —
regardless of how well the disease or sponsor were resolved.

Root cause: `asset_alias_known` was tested as `asset_resolved is not None`,
but the resolver always returns a non-None dict (even for misses), so the
unresolved branch was never reached.

---

## 2. Fix Applied

**File:** `scientific_cartography/build/asset_indication_builder.py`

Changed `asset_alias_known` detection from `is not None` to a
`resolution_status` check:

```python
asset_alias_known = (
    asset_resolved is not None
    and asset_resolved.get("resolution_status") == "resolved"
)
```

When `asset_alias_known` is False:
- `asset_confidence` is excluded from the `min()` floor
- Confidence is capped at `_UNRESOLVED_CAP = 0.75`
- `"asset_alias_unresolved_confidence_capped"` appended to `confidence_warnings`

**File:** `scientific_cartography/schemas/program_schema.py`

Added `confidence_warnings: list[str]` field to `ProgramRecord`, wired into
`to_dict()` and `from_dict()`.

---

## 3. Expected Confidence Distribution (Post-Fix)

For a CT.gov-sourced record with known NSCLC and a public sponsor in Phase 3:
- `sponsor_factor = 1.0` (public + company_id resolved)
- `disease_confidence ≈ 0.95` (NSCLC is well-mapped)
- `stage_factor = 0.8` (Phase 3)
- `_UNRESOLVED_CAP = 0.75`
- `overall_confidence = min(1.0, 0.95, 0.8, 0.75) = 0.75`

Before fix: `min(0.0, 1.0, 0.95, 0.8) = 0.0`

Records with lower disease confidence (e.g., rare disease, unmapped subtype)
will remain low. The cap prevents zero-confidence inflation to near-1.0.

---

## 4. Tests Added

**File:** `tests/scientific_cartography/test_asset_indication_builder.py`
**Class:** `TestConfidenceRedesignR3` (8 new tests)

| Test | Behavior Verified |
|------|------------------|
| `test_known_disease_unresolved_asset_no_longer_zero` | Confidence > 0.0 for known disease + unresolved asset |
| `test_known_disease_unresolved_asset_capped_at_0_75` | Confidence <= 0.75 (unresolved cap enforced) |
| `test_unresolved_asset_emits_warning_flag` | Warning flag present in `confidence_warnings` |
| `test_low_disease_confidence_still_low` | Unknown disease keeps confidence < 0.5 |
| `test_unknown_disease_zero_confidence` | Unmapped disease keeps confidence < 0.5 |
| `test_warning_flag_present_in_serialized_dict` | Warning survives `to_dict()` |
| `test_roundtrip_confidence_warnings` | Roundtrip `to_dict()` → `from_dict()` preserves warnings |
| `test_no_spurious_warnings_when_disease_unknown` | Warning fires even when disease is also unresolved |

---

## 5. Test Results

```
393 passed in 7.16s
```

All Phase 0–13 Sci-Cart tests pass. 8 new R3 tests pass.

---

## 6. Governance Constraints Preserved

- READ_ONLY_DIAGNOSTIC: no production model files modified
- No ranker, selector, sizing, final_score, gates, or snapshot changes
- No alpha claims
- No live fetch or API calls
- Freeze remains ACTIVE

---

## 7. Scope Boundary

This fix affects confidence values computed during Sci-Cart diagnostic runs
only. It does not affect:
- Any production snapshot ranking or scoring
- The ranker, selector, or portfolio construction
- EES shadow monitor or attribution analysis

---

## 8. Next Steps

- R5: Wire `therapeutic_area` from MONDO mappings
- R6: Mechanism coverage design memo (DESIGN_ONLY — no code)
