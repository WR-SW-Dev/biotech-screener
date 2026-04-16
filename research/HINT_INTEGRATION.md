# HINT Integration Note

**Date:** 2026-04-16
**Status:** Research/benchmark component — NOT production-critical
**License:** Non-commercial research use only (HINT benchmark agreement)

## Architecture Position

```
Production stack (PIT-safe, live)          Research layer (offline, sandboxed)
─────────────────────────────────          ──────────────────────────────────
outcome_model.py (Layer 3)          ←──    hint_benchmark.py (calibration comparison)
clinical_score_z (Module 4)         ←──    hint_feature_extract.py (protocol features)
evidence_snapshot.py                ←──    hint_adapter.py (schema mapper)
                                           vendor/hint/ (cloned repo, data, models)
```

HINT sits entirely in the `research/` module. It does not import into or execute
within any production code path. Protocol features extracted from HINT data can
inform future `clinical_score_z` improvements, but only after passing Checklist v2.

## Schema Mapping: HINT/TOP → Internal Fields

| HINT field | Internal field | Notes |
|------------|---------------|-------|
| `nctid` | `ctgov_study_id` / `nct_id` | Exact match key |
| `drugs` | asset_name / drug_name_map | First entry = lead compound |
| `diseases` | indication | Lowercase normalized |
| `phase` | phase ("1", "2", "3") | Mapped from "phase 1" etc. |
| `criteria` | eligibility text → ProtocolFeatures | PIT-safe (posted pre-enrollment) |
| `label` | benchmark-only outcome label | NOT for live inference |
| `status` | event_status (completed/terminated) | Metadata only |
| `why_stop` | early-termination reason | Metadata only |
| `icdcodes` | ICD-10 codes → indication bucket | For subgroup analysis |
| `smiless` | molecular SMILES | Not used in v1 (no GNN) |
| `sponsor2approvalrate` | sponsor_track_record_hit_rate | External calibration reference |

## Benchmark Results (2026-04-16)

### All phases combined (n=17,614)

| Baseline | n | Brier ↓ | AUC ↑ |
|----------|---|---------|-------|
| HINT phase base rate | 17,614 | **0.2376** | 0.596 |
| Our PoS v3 (matched) | 1,610 | 0.2692 | 0.532 |
| Protocol feature proxy | 17,614 | 0.2560 | 0.514 |

### Per-phase

| Phase | HINT Brier | PoS v3 Brier | Winner | Action |
|-------|-----------|-------------|--------|--------|
| Phase 1 | 0.2437 | **0.2180** | **PoS v3** | Keep current priors |
| Phase 2 | **0.2499** | 0.3362 | **HINT** | Recalibrate Phase 2 prior |
| Phase 3 | 0.2193 | **0.2173** | Comparable | No change needed |

**Key finding:** Our Phase 2 prior (0.310 from Wong et al.) is miscalibrated vs
HINT's empirical 49.2%. The current prior implies ~31% success but HINT data shows
~49%. This is the main recalibration opportunity.

### Protocol Feature Statistics

- Biomarker-selected trials: 54.6% success vs 57.3% without (Δ=-2.7%)
- **Biomarker selection is NOT a positive PoS predictor in HINT data.** This
  contradicts the common assumption. The conditional model's biomarker-enrichment
  thesis should be re-examined in light of this evidence.

## Protocol Features Extracted

| Feature | Type | Description | PIT status |
|---------|------|-------------|-----------|
| `inclusion_criteria_count` | int | Bullet-point count in inclusion section | pre_catalyst_safe |
| `exclusion_criteria_count` | int | Bullet-point count in exclusion section | pre_catalyst_safe |
| `eligibility_text_length` | int | Character count of full criteria text | pre_catalyst_safe |
| `biomarker_selection_flag` | bool | HER2/EGFR/BRAF/KRAS/etc. detected | pre_catalyst_safe |
| `comparator_present_flag` | bool | Placebo/SOC/active control detected | pre_catalyst_safe |
| `randomization_flag` | bool | Randomization mentioned | pre_catalyst_safe |
| `blinding_flag` | bool | Double/single blind detected | pre_catalyst_safe |
| `multi_arm_flag` | bool | Multi-arm design detected | pre_catalyst_safe |
| `endpoint_specificity_proxy` | float [0,1] | Endpoint keyword density | pre_catalyst_safe |
| `protocol_complexity_score` | float [0,1] | Composite: criteria + length + biomarker + arms | pre_catalyst_safe |

## Recommendation

### Must do
- Use HINT Phase 2 base rate (49.2%) to recalibrate our Phase 2 prior (currently 31.0%)
- Use protocol feature extraction for `clinical_score_z` decomposition research
- Keep HINT as offline benchmark — run periodically to track PoS calibration drift

### Maybe later
- Add `hint_pos_calibrated` as a capped prior (weight ≤ 0.15) for Phase 2 only
- Use HINT sponsor approval rates as an external reference for `sponsor_track_record`
- Explore protocol complexity as a conditional modifier in outcome model

### Do not do
- Wire HINT's GNN model into live scoring (too complex, unclear incremental value)
- Import saved PyTorch models (transferability not validated)
- Use HINT labels in production training (benchmark-only, non-commercial license)
- Treat biomarker selection as a positive PoS modifier (HINT data refutes this)

## Files

| File | Purpose |
|------|---------|
| `research/__init__.py` | Package marker |
| `research/hint_adapter.py` | Schema mapper, data loader, NCT matcher |
| `research/hint_feature_extract.py` | Protocol feature extractor (no DL) |
| `research/hint_benchmark.py` | Offline benchmark script |
| `research/HINT_INTEGRATION.md` | This document |
| `vendor/hint/` | Cloned HINT repo (data + models, gitignored) |
| `artifacts/hint_benchmark.json` | Latest benchmark output |
