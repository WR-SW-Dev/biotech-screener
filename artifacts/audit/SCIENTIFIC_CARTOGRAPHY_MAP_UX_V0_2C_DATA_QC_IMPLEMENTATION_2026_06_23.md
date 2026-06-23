# Scientific Cartography Map UX v0.2c — Data QC Implementation
**Date:** 2026-06-23
**Status:** PASS
**Verdict:** `PASS_MAP_UX_V0_2C_DATA_QC_READY_FOR_POSTER_LAYOUT`

---

## 1. Overview

Implements two data-QC layers in `tools/generate_scientific_cartography_map.py`
before building map layout:

- **D3 (non-drug filter):** Remove behavioral/lifestyle/device interventions
  that are not pharmaceutical programs.
- **D1 (asset deduplication):** Collapse to one record per
  `(asset_name, company_name)` at the highest-observed clinical stage.

These run in sequence: D3 first (removes noise), then D1 (collapses
duplicates). Neither modifies upstream `ProgramRecord` generation.

Version bumped to `v0.2c`.

---

## 2. D3: Non-Drug Filter

### Implementation

`_filter_non_drug_programs(programs)` checks each asset name (lowercase)
against:
- `_NON_DRUG_EXACT` (frozenset): 18 exact matches (e.g. "exercise",
  "diet", "placebo", "no treatment given", "watchful waiting",
  "lifestyle therapy")
- `_NON_DRUG_STARTSWITH` (tuple): 14 prefix patterns (e.g. "aerobic ",
  "tobacco cessation", "nutritional ", "comparison of eating",
  "behavioral intervention")

Returns `(kept_programs, meta)` where `meta` has `filtered_count` and
`examples` (first 5 filtered names).

### T2D Results

| Metric | v0.2b | v0.2c |
|---|---|---|
| Raw programs matched | 551 | 551 |
| D3 programs filtered | 0 | **14** |
| Post-D3 programs | 551 | 537 |

Examples filtered: "aerobic training, tobacco cessation and nutritional
advices", "tobacco cessation and nutritional advices", "Comparison of
eating windows intervention", "No treatment given", "Lifestyle therapy",
"Exercise", "Diet", "aerobic exercise + low-level laser therapy".

### Remaining D3 Gaps

The current filter did not catch these categories (present in approved
column of T2D map):

| Type | Examples | Count |
|---|---|---|
| Medical devices/wearables | Withings BPM Connect, Withings Body+, Hem-Col Capillary Blood Collection Device, MEMS (Medication Electronic Monitoring System) Cap | 4 |
| Clinical instruments | Questionnaire, Oral Glucose Tolerance Test, Comparison of different Blood Glucose Meters | 3 |
| Dosing regimen names | "0.5 units/kg daily insulin", "Basal Bolus", "Basal Plus", "NPH & regular insulin" | ~5 |

Total remaining non-drug pollution: ~12 of 362 programs (3.3%). These
appear spread across all stage columns; none dominates the top-5 visible
slots in any cell. The top-5 visible nodes in each column now show real
drugs: Saxagliptin, Metformin, Dapagliflozin, Glimepiride, Rosuvastatin
in the approved column.

**D3 expansion candidates for v0.2d or R6 pass:**
- Startswith "questionnaire", "oral glucose tolerance", "comparison of
  different blood glucose"
- Startswith "withings" (device brand)
- Exact: "ogtt", "basal bolus", "basal plus"

---

## 3. D1: Asset Deduplication

### Implementation

`_deduplicate_programs(programs)` groups by normalized
`(asset_name.lower(), company_name.lower())`. For each group:
- Selects record with highest stage rank (`_DEDUP_STAGE_RANK` dict:
  preclinical=0 → approved=7, None=-1)
- Merges `source_refs` from all trial records in group (unique, capped
  at 10)
- Adds `trial_count` field to the selected record

### T2D Results

| Metric | v0.2b | v0.2c |
|---|---|---|
| Post-D3 programs | 551 | 537 |
| After deduplication | 551 | **362** |
| Reduction | 0% | **32.5%** |

Stage distribution after dedup:

| Stage | v0.2b | v0.2c |
|---|---|---|
| phase3 | 150 | **86** |
| phase1 | 106 | **64** |
| unknown | 106 | **89** |
| phase2 | 103 | **62** |
| approved | 86 | **61** |

Phase3 dropped by 43% (150 → 86); approved dropped by 29% (86 → 61).
The reduction is concentrated in stage columns where well-known drugs
(Metformin, Dapagliflozin, Saxagliptin) appeared in many company trials.

### Deduplication Behavior

Dedup is by `(asset_name, company_name)` — same drug, different company
remains as separate programs. This is intentional: landscape maps should
distinguish AstraZeneca's Dapagliflozin from other sponsors' dapagliflozin
programs.

### Remaining D1 Gaps

**Insulin name fragmentation:** Multiple spelling/capitalization variants
of the same drug are treated as separate programs because `asset_name`
differs:
- "insulin glargine", "Insulin glargine", "Insulin Glargine", "Glargine",
  "glargine via insulin pen", "Insulin Glargine 300 U/mL"

These would require a name-normalization step (e.g. lowercase + brand
name → INN) before the dedup key is applied. Deferred to a future pass.

---

## 4. Summary Statistics

```
Pipeline:  551 raw → D3 (-14) → 537 → D1 dedup → 362 unique programs
Version:   v0.2c (bumped from v0.2b)
```

| Coverage metric | v0.2b | v0.2c |
|---|---|---|
| Stage coverage | 80.8% | 75.4% |
| Mechanism coverage | 0.2% | 0.3% |
| Ticker linkage | 0.0% | 0.0% |

Stage coverage dropped slightly (80.8% → 75.4%) because after dedup, the
unknown-stage programs are not proportionally removed as heavily as the
staged ones (unknown-stage trials tend to be observational and multi-drug,
so the same asset appears in unknown stage from one trial and a real stage
from another — dedup picks the real stage, which is correct, but the
unknown pool is more diverse and compresses less).

This is correct behavior: 75.4% stage coverage is more honest than 80.8%
because many of the duplicated high-stage records inflated that number.

---

## 5. Tests

**File:** `tests/scientific_cartography/test_map_generator.py`

| New class | Tests | Coverage |
|---|---|---|
| `TestNonDrugFilter` | 12 | Exercise/diet/aerobic/tobacco/no-treatment filtered; Metformin/Dapagliflozin pass; case-insensitive; filtered_count; examples |
| `TestDeduplication` | 8 | highest-stage wins; different assets not merged; approved > phase3; trial_count; source_refs merged; unknown < phase1; different companies not merged; ticker preserved |
| `TestGenerateMapV02c` | 5 | non-drug filtered from output; duplicates deduped; highest stage in map.json columns; non-drug warning emitted; preprocessing counts in summary |

Total: 501 passing (was 476).

---

## 6. New map.json Fields

`summary` now includes:
```json
{
  "raw_program_count": 551,
  "non_drug_filtered_count": 14,
  "deduped_program_count": 362,
  "total_programs": 362
}
```

`warnings` now includes when non-drug programs were filtered:
```
"14 non-pharmaceutical programs filtered (e.g. "aerobic training...", ...)."
```

Each node in `cells` now has `trial_count` (how many CT.gov records
collapsed into this deduplicated program).

---

## 7. What Improved in the T2D Map

Before v0.2c, the top-5 visible nodes in the phase3 Unknown Mechanism
column were:
- "Human Insulin Inhalation Powder", "injected insulin", "Evolocumab",
  "Saxagliptin", "Saxagliptin" (duplicate)

After v0.2c, the top-5 are:
- "Human Insulin Inhalation Powder", "injected insulin", "Evolocumab",
  "Glyburide", "exenatide" (no duplicates; more diverse names)

Before v0.2c, "+145 more" overflow in phase3 (150 programs).
After v0.2c, "+81 more" overflow (86 programs). Each overflow hides ~35%
fewer programs.

Before v0.2c, phase2 had "ALN-4324 / CCX140-B / CCX140-B / pioglitazone
/ CCX140-B" as top-5 (CCX140-B ×3).
After v0.2c, phase2 has diverse distinct programs.

---

## 8. Remaining Work for Poster Layout

v0.2c establishes clean enough node content for the poster layout pass.
Before starting the poster layout:

1. **D3 expansion (optional pre-pass):** Add patterns for questionnaires,
   devices, OGTT, BG meters, dosing regimen names. ~12 programs still
   pollute approved column.

2. **R6 mechanism aliases (separate, content work):** Still 0.3% coverage;
   the Unknown Mechanism lane is still dominant. Poster layout with a
   single data row looks like a table. R6 must precede any meaningful
   landscape feel.

3. **Poster layout pass:** Left rail (inventory stats) + center (mechanism
   × stage grid) + right cards (stage/mechanism/confidence/source
   summaries). The node content is now clean enough to judge the layout
   correctly.

---

## 9. Governance

- READ_ONLY_DIAGNOSTIC: no production model files modified
- No ranker, selector, sizing, final_score, gates, snapshot changes
- No forbidden sources read (ticker linkage 0% confirmed)
- No live fetch; no cron; no server
- Production model freeze remains ACTIVE
- D3/D1 are generator-only; upstream ProgramRecord generation unchanged
