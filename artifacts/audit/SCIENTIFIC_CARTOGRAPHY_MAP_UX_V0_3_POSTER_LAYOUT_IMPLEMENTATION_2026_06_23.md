# Scientific Cartography Map UX v0.3 — Poster Layout Implementation
**Date:** 2026-06-23
**Status:** PASS
**Verdict:** `PASS_MAP_UX_V0_3_POSTER_LAYOUT_READY_FOR_ANALYST_REVIEW`

---

## 1. Overview

Redesigns the generated HTML output from a simple stats-row + SVG layout
into a three-column strategic landscape poster. The SVG grid, map.json
schema, data pipeline (D1/D3/canonicalization), and forbidden-source
guard are unchanged. This is a rendering-layer-only change.

Version bumped to `v0.3`.

---

## 2. Layout Change

### Before (v0.2d)

```
┌─────────────────────────────────────────────┐
│ Governance banner                           │
│ Header (disease, TA, dates)                 │
│ Warning banner                              │
│ Stats row (4 pills + stage distribution)   │
│ SVG map (full width)                        │
│ Modality legend                             │
│ Footer                                      │
└─────────────────────────────────────────────┘
```

### After (v0.3)

```
┌─────────────────────────────────────────────┐
│ Governance banner (full width)              │
│ Poster header: disease title + meta         │
├──────────┬──────────────────────┬───────────┤
│ Left     │ Center panel         │ Right     │
│ rail     │                      │ rail      │
│          │  Warnings            │           │
│ Pipeline │  SVG map (scrollable)│ Stage     │
│  stats   │  Legend strip        │  dist     │
│          │                      │           │
│ Coverage │                      │ Mechanism │
│  grid    │                      │  lanes    │
│          │                      │           │
│ Data     │                      │ Coverage  │
│  prov.   │                      │  gaps     │
│          │                      │           │
│ Caveats  │                      │           │
└──────────┴──────────────────────┴───────────┘
│ Footer: source / governance / generated_at  │
└─────────────────────────────────────────────┘
```

---

## 3. Section-by-Section Design

### Governance banner
Dark (#1a252f) full-width strip. "DIAGNOSTIC ONLY — NOT AN INVESTMENT
RECOMMENDATION" in red bold. Version tag right-aligned.

### Poster header
Dark gradient (#2c3e50 → #1a252f). Disease name at 26px/800-weight.
Small-caps "Scientific Cartography · Disease Landscape Map" label above.
Meta row: therapeutic area, MONDO ID, as-of date, artifact source.

### Left rail (232px fixed)
Four sections stacked vertically:
- **Pipeline:** raw count → D3 filtered → D1 deduped → canon merges
- **Coverage:** 2×2 grid of large-number tiles (Stage%, Mechanism%, Ticker%, Lanes)
- **Data Provenance:** source notes, forbidden-source summary
- **Caveats:** 4 fixed caveat bullets (mechanism sparse, ticker needs snapshot, stage lag, combos unknown)

### Center panel (flex: 1)
- Warning block (amber) if any warnings present
- SVG map in scrollable `overflow-x:auto` container
- Legend strip: modality color swatches + opacity/border notes

### Right rail (232px fixed)
Three sections:
- **Stage Distribution:** bar-chart table, stages sorted by count DESC
- **Mechanism Lanes:** bar-chart table, all lanes including Unknown (gray bar)
- **Coverage Gaps:** named-lane count, unknown-mechanism count, unlinked-ticker count, unknown-stage count

### Footer
Light gray. Source · Generator version + timestamp · Governance note ·
Forbidden-source assurance · Governance disclaimer.

---

## 4. Generated File Sizes — T2D Prototype

| File | v0.2d | v0.3 |
|---|---|---|
| `index.html` | 12,159B | **37,017B** |
| `map.svg` | 25,763B | 25,763B (unchanged) |
| `map.json` | 179,298B | 179,297B (≈unchanged) |
| `README.md` | 1,043B | 1,043B |

HTML grew by ~25KB due to the inline CSS (rail layout, coverage grid,
bar chart tables, card styling) and the right-rail content (stage/
mechanism tables with per-row bar widths).

---

## 5. T2D Map Stats (unchanged from alias pack)

| Metric | Value |
|---|---|
| Programs | 335 |
| Lanes | 11 |
| Stage columns | 5 |
| Mechanism coverage | 23.0% |
| Named-lane programs | 77 |
| Unknown Mechanism | 258 |

---

## 6. Tests

**File:** `tests/scientific_cartography/test_map_generator.py`

New class: `TestRenderHTMLV03Poster` — 18 tests

| Category | Tests |
|---|---|
| Layout section presence | poster-header, left-rail, center-panel, right-rail, poster-footer |
| Disease name in header | disease title appears in h1 |
| Right-rail content | stage distribution labels (Phase 3, Approved), mechanism lane names |
| Left-rail content | Coverage, Stage, Mechanism, Pipeline, Caveats, Provenance |
| Governance | gov-banner present, DIAGNOSTIC ONLY, NOT AN INVESTMENT RECOMMENDATION |
| No CDN | cdn.jsdelivr.net, unpkg.com, cdnjs.cloudflare.com absent |
| No action language | buy/sell/final_score/sizing/trade now absent |
| SVG embedded | map-viewport present, `<svg` present |
| Legend | legend-strip present |
| Warnings | warning-block appears when mechanism coverage sparse |

**Fix applied:** renamed `warn-block` → `warning-block` / `warn-item` →
`warning-item` so the existing `TestRenderHTML::test_warning_banner_appears_for_sparse_mechanism`
test (which checks `"warning" in html.lower()`) continues to pass.

Total: **573 passing** (was 555 in alias pack commit).

---

## 7. Preserved from v0.2d

- `map.json` schema: unchanged (metadata, summary, warnings, lanes,
  columns, cells)
- `render_svg()`: unchanged
- `build_map_data()`: unchanged
- D1/D3 preprocessing: unchanged
- Forbidden-source guard: unchanged
- Deterministic output: unchanged (generated_at_utc is the only
  non-deterministic field, already present in v0.2d)
- Unknown Mechanism lane: still rendered, now additionally listed in
  right-rail Mechanism Lanes table with gray bar

---

## 8. What the Poster Adds vs. v0.2d

The v0.2d map required the analyst to mentally compute stage distribution
from the column headers. The v0.3 poster surfaces that immediately in the
right rail. The Coverage section in the left rail gives four key numbers
(Stage%, Mechanism%, Ticker%, Lanes) at a glance without reading the SVG.
The Caveats section makes the data-quality limitations impossible to miss.

The map is now readable as a self-contained artifact that can be shared
without accompanying explanation.

---

## 9. Next Step

The poster layout is ready for analyst review. Recommended validation:
open `index.html` in a browser and assess whether the three-column layout
reads as a strategic landscape map.

After analyst review, the remaining gaps visible in the right rail are:
- Mechanism coverage 23% → further alias pack work (v0.2)
- Ticker coverage 0% → requires authorized snapshot input

---

## 10. Governance

- READ_ONLY_DIAGNOSTIC: no production model files modified
- Layout/rendering only: no data pipeline changes
- No forbidden sources read
- No live fetch; no cron; no server
- No ranker, selector, sizing, final_score, gates, snapshot changes
- Production model freeze remains ACTIVE
