# Scientific Cartography Map UX v0.2b — Static Prototype Implementation
**Date:** 2026-06-23
**Status:** PASS
**Verdict:** `PASS_MAP_UX_V0_2B_STATIC_PROTOTYPE_DIAGNOSTIC_ONLY`

---

## 1. Overview

Implements a static RA-style disease landscape map generator for the
Scientific Cartography diagnostic layer. Reads only Sci-Cart artifacts.
No server, no CDN, no production scoring sources.

Generates four files per disease:
- `index.html` — self-contained HTML, openable with `file://`
- `map.svg` — standalone SVG (embeddable)
- `map.json` — structured lane/column/node data
- `README.md` — brief description

---

## 2. Artifact Baseline Refresh

Re-ran Sci-Cart diagnostics after Phase 13.7 stage alias fix (`40a621f2`),
using `production_data/trial_records.json` (20,057 records) with no snapshot
(no `rankings.csv` — forbidden source for this UX layer):

```
Output: artifacts/scientific_cartography/2026-06-23-stagefix/
Trials loaded: 20,057
Programs built: 73,075
```

---

## 3. Prototype — Type 2 Diabetes Mellitus

Disease query: `type 2 diabetes mellitus`

### Programs

| Metric | Value |
|---|---|
| Total programs matched | 551 |
| Stage coverage | 80.8% |
| Mechanism coverage | 0.2% (1 program, sparse — expected) |
| Ticker coverage | 0.0% (no snapshot — expected) |
| Therapeutic area | Metabolic (from R5 MONDO wiring) |
| MONDO IDs | MONDO:0005148 |

### Stage Distribution

| Stage | Programs | % |
|---|---|---|
| phase3 | 150 | 27.2% |
| unknown | 106 | 19.2% |
| phase1 | 106 | 19.2% |
| phase2 | 103 | 18.7% |
| approved | 86 | 15.6% |

### Map Layout

- **Columns (stage axis):** phase1, phase2, phase3, approved, unknown — 5 columns
- **Lanes (mechanism axis):** GLP-1 receptor agonist (1 program), Unknown Mechanism (550 programs) — 2 lanes

The "Unknown Mechanism" lane is visually dominant and correctly reflects
~99.8% unknown mechanism coverage for this disease. This is honest sparse-data
treatment per R6 design spec.

### Generated File Sizes

| File | Size |
|---|---|
| `map.json` | 284,170 bytes |
| `index.html` | 11,838 bytes |
| `map.svg` | 8,036 bytes |
| `README.md` | 1,046 bytes |

---

## 4. Generator Design

**Tool:** `tools/generate_scientific_cartography_map.py`

### Forbidden-source guard

Checks all input paths against banned patterns before any I/O:
- `rankings.csv`, `portfolio_positions.csv`, `screen_output.json`
- `selector`, `sizing`, `final_score`

Raises `ForbiddenSourceError` immediately if any match.

### Layout engine

- **Rows (lanes):** mechanism_class groups, sorted by program count DESC.
  `Unknown Mechanism` always last.
- **Columns:** active stage buckets in canonical order
  (preclinical → phase1 → phase1/2 → phase2 → phase2b → phase3 → filed → approved → unknown).
  Only shows columns with ≥1 program.
- **Cells:** programs sorted by confidence DESC; max 5 visible, "+N more" label.

### SVG encoding

- **Color:** modality (blue=small molecule, orange=mAb, green=cell therapy,
  purple=gene therapy, red=RNA, teal=protein/enzyme, gray=unknown)
- **Opacity:** 0.30 + 0.70 × confidence (R3 wiring visible in rendering)
- **Border:** solid/thick = has ticker; thin = unlinked sponsor
- **Unknown mechanism lane:** highlighted amber background

### Governance

- `map.json` includes `governance.read_only_diagnostic=true` and disclaimer
- HTML governance banner at top
- Generator aborts on any forbidden-source path
- No external CDN references; self-contained

---

## 5. Tests

**File:** `tests/scientific_cartography/test_map_generator.py`
**Count:** 38 tests

| Class | Tests | Coverage |
|---|---|---|
| `TestForbiddenSourceGuard` | 8 | All 6 patterns + allowed paths + generate_map abort |
| `TestDiseaseFilter` | 3 | Exact match, substring match, no-match raises |
| `TestBuildMapData` | 13 | Lane order, stage order, unknown lanes, metadata, coverage stats, warnings, determinism, therapeutic_area |
| `TestRenderSVG` | 5 | SVG produced, unknown lanes/columns present, overflow label, no action language |
| `TestRenderHTML` | 5 | Governance header, no action language, therapeutic_area, warning banner, no external CDN |
| `TestGenerateMap` | 4 | 4 files created, map.json schema, SVG not empty, result dict shape |

---

## 6. Full Test Suite

```
476 passed in 7.63s
```

All Phase 0–13 Sci-Cart + 38 new map generator tests pass.

---

## 7. Governance

- READ_ONLY_DIAGNOSTIC: no production model files modified
- `rankings.csv` never read (forbidden source guard enforced)
- No ranker, selector, sizing, final_score, gates, snapshot changes
- No alpha claims; no trading/action language in any generated output
- No cron/scheduler; no server; no live data
- Generated map output excluded from git by `artifacts/*` rule
- Production model freeze remains ACTIVE

---

## 8. Known Limitations

1. **Mechanism coverage 0.2%:** All T2D programs except 1 fall into Unknown
   Mechanism lane. Correct behavior per R6 design. Improves after R6
   implementation (alias CSV curation).

2. **Ticker coverage 0%:** No snapshot loaded — expected. Provide
   `rankings.csv` snapshot to restore ticker linkage (will require
   explicit operator authorization since it's a currently-forbidden source).

3. **Map.json large (284KB):** Contains full node data for all 551 programs.
   Future optimization: paginated or summary-only map.json with detail on demand.

4. **SVG not interactive:** v0.2b is static. Hover/click interactions deferred
   to a future version using inline JavaScript (still no CDN).

---

## 9. Next Steps

- R6 mechanism alias CSV curation — fills Unknown Mechanism lane
- Ticker linkage restoration with explicit snapshot source authorization
- Add second disease prototype (e.g., atopic dermatitis, NSCLC) for
  comparison
- Investigate interactive enhancements (hover tooltips, filter by TA) as
  inline JS without CDN
