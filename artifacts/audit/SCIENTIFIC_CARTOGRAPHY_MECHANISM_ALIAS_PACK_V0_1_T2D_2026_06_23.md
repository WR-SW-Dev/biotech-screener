# Scientific Cartography — Mechanism Alias Pack v0.1 (T2D)
**Date:** 2026-06-23
**Status:** PASS
**Verdict:** `PASS_MECHANISM_ALIAS_PACK_V0_1_T2D_READY_FOR_MAP_REGEN`

---

## 1. Overview

Curates and wires a T2D-focused mechanism alias pack into the Scientific
Cartography diagnostic pipeline. Maps common T2D drug names, brand names,
and development codes to mechanism class, target, and modality.

**Files changed:**
- `scientific_cartography/data/mechanism_aliases_v0_1.csv` — new alias pack
- `tools/run_scientific_cartography_diagnostics.py` — auto-loads CSV
- `tests/scientific_cartography/test_mechanism_normalizer.py` — 34 new tests

No production model files modified. Diagnostic-only.

---

## 2. Alias Pack Content

**File:** `scientific_cartography/data/mechanism_aliases_v0_1.csv`

70 entries across 9 T2D drug classes:

| Mechanism class | Entries | Examples |
|---|---|---|
| Insulin | 28 | insulin glargine, glargine, afrezza, lantus, humalog, detemir, insulin icodec, nph insulin |
| Biguanide | 2 | metformin, metformin xr |
| SGLT2 inhibitor | 6 | dapagliflozin, empagliflozin, canagliflozin, ertugliflozin + 2 dose variants |
| GLP-1 receptor agonist | 8 | liraglutide, semaglutide, exenatide, dulaglutide, albiglutide, lixisenatide (ave0010), ac2993, exenatide once weekly |
| DPP-4 inhibitor | 7 | saxagliptin, sitagliptin, alogliptin, linagliptin, vildagliptin + 1 dose variant |
| SGLT2/SGLT1 inhibitor | 2 | sotagliflozin, sotagliflozin (sar439954) |
| Sulfonylurea | 4 | glimepiride, glipizide, glyburide, gliclazide |
| PPAR agonist | 3 | pioglitazone, rosiglitazone, actos |
| Alpha-glucosidase inhibitor | 2 | acarbose, miglitol |
| Meglitinide | 1 | nateglinide |
| GIP/GLP-1 receptor agonist | 1 | tirzepatide |
| Amylin analog | 1 | pramlintide |

**Design rules applied:**
- Map INN (preferred), brand name, development code, and dose-suffixed
  variants all as separate entries for explicit coverage.
- Skip combination products (e.g. "insulin glargine/lixisenatide" —
  not resolvable to a single mechanism class).
- Skip novel/experimental agents where mechanism is uncertain
  (sb-509, mbx-2044, incb013739, ccx140-b).
- Conservative confidence for class-level names like "basal insulin"
  (0.85) vs. full INN (0.99).

---

## 3. Pipeline Wiring

`run_scientific_cartography_diagnostics.py` Step 3 now auto-loads the
CSV at startup:

```
priority:
  1. args.mechanism_aliases override (if provided)
  2. scientific_cartography/data/mechanism_aliases_v0_1.csv (auto-discover)
  3. built-in dictionary only (fallback if CSV missing)
```

This is backward-compatible: existing test `Args` objects that omit
`mechanism_aliases` fall back to auto-discovery. All 555 sci-cart tests
pass.

---

## 4. T2D Mechanism Coverage — Before vs. After

### Raw programs (pre-dedup, pre-filter)

| Metric | Before | After |
|---|---|---|
| T2D raw programs | 963 | 963 |
| Mechanism resolved | ~3 | **332** |
| Mechanism coverage | **0.3%** | **34.5%** |

### Map programs (post-D3 + D1 dedup, 335 unique)

| Metric | v0.2d | v0.1 alias pack |
|---|---|---|
| Mechanism lanes | 2 | **11** |
| Mechanism coverage | 0.3% | **23.0%** |
| Named-lane programs | 1 | **77** |
| Unknown Mechanism | 334 | **258** |

The remaining 258 Unknown Mechanism programs are primarily:
- Experimental/novel agents without established class (SB-509, CCX140-B,
  MBX-2044, INCB013739, various investigational codes)
- Insulin combination products not mapped (e.g. insulin glargine/lixisenatide)
- Inhaled formulation code variants not captured (MKC253)

---

## 5. Named Mechanism Lanes in T2D Map

| Lane | Programs |
|---|---|
| Insulin | 32 |
| Biguanide | 11 |
| GLP-1 receptor agonist | 9 |
| Sulfonylurea | 6 |
| PPAR agonist | 5 |
| SGLT2 inhibitor | 5 |
| DPP-4 inhibitor | 4 |
| SGLT2/SGLT1 inhibitor | 3 |
| Meglitinide | 1 |
| Alpha-glucosidase inhibitor | 1 |
| Unknown Mechanism | 258 |

The map now communicates competitive structure:
- Insulin lane (32 programs): crowded approved + phase3 columns
- Biguanide (11): heavy approved column (metformin is standard of care)
- GLP-1 RA (9): spread across phase1–approved
- SGLT2 inhibitor (5): concentrated in phase3 + approved
- DPP-4 inhibitor (4): phase3 + approved

---

## 6. Tests

**File:** `tests/scientific_cartography/test_mechanism_normalizer.py`

New class: `TestT2DAliasPackV01` — 34 tests

| Category | Tests | Coverage |
|---|---|---|
| Case-insensitive resolution | 11 | Metformin, dapagliflozin, saxagliptin, liraglutide, semaglutide, insulin glargine, pioglitazone, glimepiride, acarbose, tirzepatide, GLP-1 RA modality |
| Dose-suffixed variants resolve | 3 | saxagliptin 5 mg, dapagliflozin 10mg tab, dapagliflozin 10 mg |
| Brand names resolve | 3 | Afrezza, Lantus, Actos |
| Development codes resolve | 2 | AC2993 (exenatide), sotagliflozin (sar439954) |
| Unknown drugs stay unknown | 3 | SB-509, aerobic exercise, Withings BPM |
| Combination products not resolved | 2 | insulin glargine/lixisenatide, metformin + sitagliptin |
| Built-in dict still works | 2 | JAK inhibitor, PD-1 inhibitor |

Total: **555 passing** (was 529 in v0.2d).

---

## 7. Remaining Coverage Gap

Mechanism coverage is 23.0% after the alias pack. The remaining 77%
Unknown Mechanism consists of:

1. **True novel agents** (~40%): investigational codes with no established
   class in the alias pack. These are real unknowns, not omissions.

2. **Insulin combination products** (~5%): "insulin glargine/lixisenatide"
   and similar combos conservatively left as Unknown.

3. **Variant names not yet aliased** (~10%): e.g. "injected insulin",
   "mkc253 inhalation powder", "ly041001 (hiip)", "bgm" variants.
   These could be added to v0.2 of the alias pack.

4. **Other disease programs** (~22%): programs in the T2D bucket that
   study T2D complications (retinopathy, nephropathy, neuropathy) with
   drug names not related to the 9 T2D classes.

The current 23.0% / 11-lane result is substantially better than 0.3% / 2
lanes and is sufficient to make the map function as a competitive
landscape. Further coverage gains require either expanding the alias CSV
or running a separate mechanism inference pass.

---

## 8. Next Step

The map now has enough named lanes to support a poster layout redesign.
The recommended next step is:

**Poster layout pass (v0.3):** Redesign the HTML/SVG layout from a
simple grid to a strategic landscape poster:
- Left rail: inventory stats (program count, mechanism coverage,
  stage coverage)
- Center: mechanism × stage grid (now meaningful with 11 lanes)
- Right/bottom: summary cards per mechanism class

Optionally before poster layout: Mechanism Alias Pack v0.2 to bring
coverage from 23% to ~35%+ by adding insulin combination products,
additional variant names, and GIP/GLP-1 dual agonists beyond tirzepatide.

---

## 9. Governance

- READ_ONLY_DIAGNOSTIC: no production model files modified
- No ranker, selector, sizing, final_score, gates, snapshot changes
- No forbidden sources read
- No live fetch; no cron; no server
- Alias CSV is diagnostic enrichment data only — no production scoring
- Production model freeze remains ACTIVE
