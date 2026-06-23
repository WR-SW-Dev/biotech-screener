# Scientific Cartography Map UX v0.2d — Display QC Implementation
**Date:** 2026-06-23
**Status:** PASS
**Verdict:** `PASS_MAP_UX_V0_2D_DISPLAY_QC_READY_FOR_MECHANISM_ALIAS_PACK`

---

## 1. Overview

Extends `tools/generate_scientific_cartography_map.py` to v0.2d with two
display-QC improvements:

- **D3 expansion:** 23 additional non-drug patterns added to catch medical
  devices, clinical instruments, dosing regimen names, and questionnaires
  that remained in v0.2c.
- **Asset-name canonicalization:** Strips "insulin " prefix and
  route/dose suffixes before the deduplication key, collapsing variants
  like "saxagliptin 5 mg" and "dapagliflozin 10 mg" into their INN
  parent.

Neither change modifies upstream ProgramRecord generation. Generator/
display-layer only.

Version bumped to `v0.2d`.

---

## 2. D3 Expansion

### New Patterns Added

**`_NON_DRUG_EXACT` additions (6):**
`"ogtt"`, `"oral glucose tolerance test"`, `"mems cap"`,
`"basal bolus"`, `"basal plus"` — dosing regimens and clinical
instruments that appeared in the v0.2c approved column.

**`_NON_DRUG_STARTSWITH` additions (9):**
`"withings"` (device brand), `"hem-col"`, `"mems ("`,
`"questionnaire"`, `"blood glucose meter"`,
`"comparison of different blood glucose"`,
`"glucose meter"`, `"oral glucose tolerance"` — wearables, BG meters,
and patient questionnaires.

**`_DOSE_ONLY_RE` (new):** Matches names that are pure dosing descriptions
(e.g. "0.5 units/kg daily insulin", "10 units insulin") — pattern
`r"^\d+(\.\d+)?\s+units?"`.

### T2D Impact

| Metric | v0.2c | v0.2d |
|---|---|---|
| D3 programs filtered | 14 | **37** |
| Post-D3 programs | 537 | **514** |

The 23 additional filtered items were concentrated in the approved column
(Withings BPM Connect, Withings Body+, Hem-Col, MEMS Cap, OGTT,
Questionnaire, BG Meter variants, Basal Bolus, Basal Plus). The approved
column now shows pharmaceutical programs only.

---

## 3. Asset-Name Canonicalization

### Implementation

`_canonical_asset_name(name)` produces a lowercase key for deduplication:

1. **Strip "insulin " prefix** — "insulin glargine" → "glargine",
   "insulin lispro" → "lispro" (only when `len(remainder) > 0`)
2. **Strip route/form suffixes** — " via insulin pen", " via pen",
   " injection", " oral tablet", " oral tablets"
3. **Strip dose suffix** — `_ASSET_DOSE_SUFFIX_RE` removes trailing
   ` 5 mg`, ` 10 mg/ml`, ` 300 U/mL`, etc.

### Merge-Count Tracking

The generator now correctly tracks groups where multiple DISTINCT
raw-lowercase names map to the same canonical key. Two names that differ
only in capitalization ("Metformin" vs "metformin") are the same
raw-lowercase key and are not counted as canonicalization merges — they
were already collapsed by v0.2c lowercasing. A canonicalization merge
requires a genuine spelling/form difference in the raw name.

### T2D Impact

| Metric | v0.2c | v0.2d |
|---|---|---|
| Canonicalization merge groups | 0 | **9** |
| Post-D1 unique programs | 362 | **335** |

9 groups merged by canonicalization:

- `saxagliptin / saxagliptin 5 mg` → "saxagliptin"
- `dapagliflozin / dapagliflozin 10 mg / dapagliflozin 5 mg` → "dapagliflozin"
- Additional insulin/dose-suffix variants

---

## 4. Full Pipeline Comparison

| Stage | v0.2b | v0.2c | v0.2d |
|---|---|---|---|
| Raw programs matched | 551 | 551 | 551 |
| D3 filtered | 0 | 14 | **37** |
| Post-D3 | 551 | 537 | **514** |
| Post-D1 (unique programs) | 551 | 362 | **335** |

Stage distribution after v0.2d:

| Stage | v0.2c | v0.2d |
|---|---|---|
| unknown | 89 | **87** |
| phase3 | 86 | **82** |
| phase2 | 62 | **61** |
| phase1 | 64 | **57** |
| approved | 61 | **48** |

The approved column dropped from 61 to 48 (-13 programs, -21%) — this
is the expected result of removing BG meters, devices, dosing regimen
names, and questionnaires that were polluting the approved column.
Approved now contains pharmaceutical drug programs only.

---

## 5. New `map.json` Fields

`summary` now includes:
```json
{
  "canonicalization_merge_count": 9
}
```

`warnings` now includes when canonicalization merges occurred:
```
"9 asset-name variant groups merged by canonicalization
 (e.g. saxagliptin / saxagliptin 5 mg; dapagliflozin / dapagliflozin 10 mg
 / dapagliflozin 5 mg)."
```

---

## 6. Tests

**File:** `tests/scientific_cartography/test_map_generator.py`

| New class | Tests | Coverage |
|---|---|---|
| `TestNonDrugFilterV02d` | 12 | questionnaire, withings, mems cap, ogtt, blood glucose meter, dose regimen (0.5 units/kg), hem-col, basal bolus; Metformin and Dapagliflozin pass |
| `TestAssetCanonicalization` | 13 | insulin prefix strip, dose suffix strip, glargine variants deduplicate to 1, combination product stays distinct; _canonical_asset_name unit tests |
| `TestGenerateMapV02d` | 3 | canon_merge_count ≥ 1 in summary; device + behavioral removed from output; deterministic output across two runs |

Total: **529 passing** (was 501 in v0.2c).

---

## 7. Remaining Display-QC Issues

| Issue | Status |
|---|---|
| Mechanism coverage 0.3% | Unchanged — requires mechanism alias pack |
| Ticker linkage 0% | Unchanged — requires authorized snapshot input |
| Confidence opacity range degenerate | Unchanged — will improve after ticker linkage |

No remaining obvious non-drug pollutants in the approved column after
v0.2d. The 48 approved-column programs are all pharmaceutical.

---

## 8. Next Step: Mechanism Alias Pack v0.1

With display QC complete (D3 expansion + D1 canonicalization), the node
set is clean. The single highest-leverage remaining fix is the mechanism
alias pack for T2D:

**Minimum viable alias pack for T2D (6 classes):**
1. SGLT2 inhibitor — dapagliflozin, canagliflozin, empagliflozin,
   ertugliflozin
2. DPP-4 inhibitor — saxagliptin, sitagliptin, alogliptin,
   linagliptin, vildagliptin
3. GLP-1 receptor agonist — semaglutide, liraglutide, dulaglutide,
   exenatide, albiglutide (extends existing single entry)
4. Biguanide — metformin
5. Insulin — glargine, detemir, degludec, lispro, aspart, glulisine,
   regular insulin, NPH
6. PPAR agonist / thiazolidinedione — pioglitazone, rosiglitazone

Expected outcome: mechanism coverage 0.3% → ~40–50%; 6+ lanes populated;
Unknown Mechanism row shrinks from dominant to minority.

---

## 9. Governance

- READ_ONLY_DIAGNOSTIC: no production model files modified
- No ranker, selector, sizing, final_score, gates, snapshot changes
- No forbidden sources read (ticker linkage 0% confirmed)
- No live fetch; no cron; no server
- Generator/display-layer only; upstream ProgramRecord generation unchanged
- Production model freeze remains ACTIVE
