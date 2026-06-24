# Scientific Cartography Map UX v0.3 — Visual QA
**Date:** 2026-06-23
**Status:** PASS
**Verdict:** `PASS_MAP_UX_V0_3_VISUAL_QA_LANDSCAPE_GRAMMAR_CONFIRMED`

---

## 1. Map Regeneration

Generated T2D map using real trial_records.json (20,057 trials) via scratchpad
ctgov_cache with mechanism alias pack v0.1 loaded automatically:

```
Output:
  HTML:     37,017 bytes
  SVG:      25,763 bytes (990×1076px)
  map.json: 179,297 bytes
```

---

## 2. Structural Checks — HTML Sections

| Section selector | Present | Notes |
|---|---|---|
| `.gov-banner` | ✅ | Contains "DIAGNOSTIC ONLY" |
| `.poster-header` | ✅ | Disease name + date |
| `.left-rail` | ✅ | Pipeline, Coverage, Caveats, Provenance sections |
| `.center-panel` | ✅ | Contains `.map-viewport` with embedded SVG |
| `.right-rail` | ✅ | Lane summaries |
| `.poster-footer` | ✅ | Governance + source |
| `.map-viewport` | ✅ | SVG rendered inline |

All 7 expected structural sections present.

---

## 3. Governance Language Check

| Required phrase | Present |
|---|---|
| "DIAGNOSTIC ONLY" | ✅ |
| "NOT AN INVESTMENT RECOMMENDATION" | ✅ |
| "Read-only" | ✅ |
| "No ranking" | ✅ |
| "frozen model" | ✅ |

| Forbidden phrase | Absent |
|---|---|
| "buy" / "sell" / "hold" | ✅ absent |
| "final_score" | ✅ absent |
| "sizing" / "ranker" | ✅ absent |
| External CDN references | ✅ absent |
| "alpha" (as in return claim) | ✅ absent |

---

## 4. SVG Structure Checks

**Dimensions:** 990×1076px (vs. 990×266px in v0.2b — correct, 11 lanes require taller canvas)

**Element counts:**
- `<rect>` elements: 159
- `<text>` elements: 111
- Lane labels in SVG: 11 (Insulin, Biguanide, GLP-1 receptor agonist,
  Sulfonylurea, PPAR agonist, SGLT2 inhibitor, DPP-4 inhibitor,
  SGLT2/SGLT1 inhibitor, Meglitinide, Alpha-glucosidase inhibitor,
  Unknown Mechanism)
- Column headers: 5 (phase1, phase2, phase3, approved, unknown)
- Total named labels: 16 ✅

---

## 5. map.json Schema Check

| Field | Value | Status |
|---|---|---|
| `metadata.generator_version` | `"v0.3"` | ✅ |
| `metadata.disease_name` | `"type 2 diabetes mellitus"` | ✅ |
| `metadata.as_of_date` | `"2026-06-23"` | ✅ |
| `summary.total_programs` | 335 | ✅ |
| `summary.mechanism_coverage_pct` | 23.0 | ✅ |
| `summary.mechanism_lane_count` | 11 | ✅ |
| `summary.stage_coverage_pct` | 74.0 | ✅ |
| `summary.ticker_coverage_pct` | 0.0 | ✅ (expected — no rankings.csv) |
| `lanes` array | 11 entries | ✅ |
| `columns` array | 5 entries | ✅ |
| `cells` dict | 11 keys | ✅ |
| `warnings` present | Yes | ✅ backward compat |
| `governance.read_only_diagnostic` | `true` | ✅ |

Schema is backward-compatible with v0.2 consumers.

---

## 6. Content-Level Observations

### 6a. GLP-1 RA · Approved — false positive (pre-existing)

The "Approved" column of the GLP-1 receptor agonist lane contains:

> asset_name: "standard of care (basal insulin or premixed insulin, excluding
> any GLP-1 receptor agonist-containing drugs)"
> company: Shanghai Zhongshan Hospital

This program matched because the asset_name contains the substring
"GLP-1 receptor agonist" (in the exclusion clause of a comparator arm
description). The substring matcher in `MechanismNormalizer.normalize()`
picks this up at lower confidence (0.7 from the asset_indication_builder
default, not from the alias pack).

**Root cause:** Pre-existing substring matching in the built-in mechanism_dict.
**Not introduced by:** alias pack v0.1 (which uses exact/alias match only)
**Not introduced by:** v0.3 (display layer only)
**Severity:** Low — one program out of 9 in the GLP-1 lane. The GLP-1 Approved
column shows 2 programs; the other is correctly identified (Exenatide,
University of Washington).
**Resolution path:** Asset-name normalization pass (filter comparator arm
descriptions before mechanism enrichment) — deferred to future work.

### 6b. Biguanide — multi-company Metformin (by design)

Metformin appears multiple times across Phase 2/3/Approved because
different companies (AstraZeneca, Sanofi, Gilead, Novartis, etc.) each
sponsor separate CT.gov trials with Metformin as the investigational arm.

D1 deduplication collapses `(canonical_asset_name, company_name)` pairs,
not just `(canonical_asset_name)`. Therefore Metformin/AstraZeneca and
Metformin/Sanofi are distinct entries. This is correct behavior: a real
analyst wants to know how many companies are running Metformin-arm trials.

**Not a data quality issue.** The high Biguanide count (11 programs) reflects
real trial activity, not data inflation.

### 6c. Insulin lane depth (32 programs)

Insulin lane is the most crowded (32 programs, dominated by Phase 3 and
Approved). The Phase 3 column shows 14 programs — many are Insulin Glargine
biosimilar trials from different manufacturers (Mylan, Eli Lilly, Sanofi)
and different formulation arms (HOE901, U300, etc.).

This reflects real historical trial depth in a mature standard-of-care class.
The grid communicates this correctly: Insulin row is visibly darker than
newer mechanism classes.

---

## 7. Analyst-Facing Landscape Assessment

**Map now answers these questions:**

| Question | Answerable | Evidence |
|---|---|---|
| Which mechanism classes are represented? | ✅ | 10 named lanes |
| Which classes have Phase 3/Approved density? | ✅ | Insulin, Biguanide, GLP-1 RA, Sulfonylurea all crowded in Phase 3+ |
| Which classes are earlier stage? | ✅ | No Phase 1/2 entries for Sulfonylurea, SGLT2i, DPP-4i |
| GLP-1 RA vs. SGLT2i stage distribution? | ✅ | GLP-1 RA spans P2–Approved; SGLT2i concentrated P3–Approved |
| What remains investigational (unknown)? | ✅ | 258 programs in Unknown Mechanism |
| Which companies appear per program? | ✅ (via hover tooltip) | In the rendered map |
| What tickers are active in each lane? | ❌ | 0% ticker linkage (expected) |

**The map functions as a landscape.** With 10 named mechanism classes and
23% mechanism coverage, an analyst can now orient to the T2D competitive
structure: Insulin and Biguanide as standard-of-care anchors; GLP-1 RA and
SGLT2i as the growth classes (Phase 3 → Approved); and a 258-program
investigational pool worth parsing in alias pack v0.2.

---

## 8. Warning CSS Class Note

The v0.3 fork agent renamed warning CSS classes:
- Old: `.warn-block`, `.warn-item` (v0.2b)
- New: `.warning-block`, `.warning-item` (v0.3)

Tests that checked for `warn-block` were updated in the v0.3 commit to
check for `warning-block`. The governance banner remains present and
visible. No functional regression.

---

## 9. Governance

- READ_ONLY_DIAGNOSTIC ✓
- No production model files modified ✓
- No ranker/selector/sizing/final_score changes ✓
- No forbidden sources read (ForbiddenSourceError guard active) ✓
- Freeze ACTIVE ✓
- Mechanism alias pack v0.1 loaded automatically (auto-discover path) ✓
- 573 tests passing at v0.3 commit `5e1eaf45` ✓

---

## 10. Next Steps

The T2D map is now a functional competitive landscape. Three natural
forward moves:

1. **Mechanism alias pack v0.2** — extend coverage from 23% to ~35%+ by
   adding insulin combination products, additional GLP-1 variant names,
   and GIP/GLP-1 dual agonists beyond tirzepatide. Low effort, high
   diagnostic value.

2. **Second disease prototype** — repeat the mechanism alias pass for a
   second oncology indication (e.g., NSCLC or HER2+ breast) to validate
   that the three-layer architecture generalizes beyond T2D metabolic drugs.

3. **Ticker linkage pass** — wire company_name → ticker matching so the
   map can show which cells contain public companies in the screener
   universe. Requires a controlled read of the company universe (not
   rankings.csv) and operator authorization.
