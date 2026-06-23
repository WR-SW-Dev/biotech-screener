# Scientific Cartography Map UX — Repo Audit

**Date**: 2026-06-23  
**Scope**: Read-only inventory of all map UX surfaces, dashboard rendering, static artifacts, disease-map views, and MCP/UI exposure.  
**Verdict**: `WARN_MAP_UX_FRAGMENTED_ARTIFACT_ONLY`

---

## 1. What Map UX Surfaces Already Exist?

### Static HTML Dashboard (LG4A) — EXISTS, NOT AUTO-SERVED
`scientific_cartography/dashboard_static/generator.py` + `templates.py`  
CLI: `tools/generate_scientific_cartography_dashboard.py`

Generates 6 static HTML pages from artifact JSON:
- `index.html` — overview of artifact run + governance status
- `review_runs.html` — LG1 review summary metadata
- `disease_maps.html` — list of diseases from `disease_map_index.json` (table, no visual map)
- `human_decisions.html` — LG2 audit trail
- `scheduled_review_health.html` — LG3 cron execution health
- `governance.html` — governance flags

Must be run manually. No running server. Output lands in user-specified `--output-dir`.

### Markdown Disease Maps — EXISTS
`disease_map_summary.md` in each artifact run directory.  
Content: per-disease tables (program count, cluster count, stage distribution, mechanism classes, tickers). Text/table format only; no visual layout.

### JSON Disease Maps — EXISTS (3 types)
- `disease_map_summary.json` — disease-level aggregated counts + mechanism/modality/ticker/stage lists
- `map_index.json` — top-level index with aggregate counts by disease + governance block
- `disease_map_index.json` (Phase 12/13c artifact path only) — per-disease metadata for the LG4A browser

### CSV Outputs — NONE
No CSV disease-map exports exist. `write_csv` is imported in `DiseaseMapArtifactExporter` but no CSV disease-map files are generated in current artifact runs.

### MCP Tool — EXISTS
`mcp_server/tools/cartography_tools.py` exposes `get_atlas_data(category: str)`.  
Categories: `overview`, `schemas`, `normalizers`, `diseases`, `programs`, `review`, `artifacts`.  
- `diseases` category returns `disease_map_summary.json` content + `map_index.json` counts + sample of first 10 diseases.  
- Read-only, returns JSON string. No spatial map data, no per-disease drill-down.

### Dashboard Generator Script — EXISTS
`tools/generate_scientific_cartography_dashboard.py` — manual CLI. Not wired to cron.

### Spatial / Visual Map (SVG, canvas, lane layout) — DOES NOT EXIST
No SVG, no HTML canvas, no D3, no React cartography component. No lane-by-mechanism, column-by-stage visual. The LG4A `disease_maps.html` page is an HTML table list, not a landscape map.

### React Frontend — EXISTS FOR SCREENER ONLY, NO CARTOGRAPHY
`frontend/dashboard/src/` is a live React/Vite/Tailwind app for the screener (rankings, options, catalysts, shadows, etc.). It has no Scientific Cartography tab or view. `frontend/prototype/` has reference-only mock components also scoped to the screener.

---

## 2. What Is Currently User-Facing vs Artifact-Only?

| Surface | Status |
|---|---|
| `disease_map_summary.json` | Artifact-only (file on disk) |
| `disease_map_summary.md` | Artifact-only (readable markdown) |
| `map_index.json` | Artifact-only |
| `disease_map_index.json` | Artifact-only |
| LG4A static HTML dashboard | User-facing after manual `generate_scientific_cartography_dashboard.py` run |
| MCP `get_atlas_data()` | User-facing via MCP/Hermes JSON query |
| React frontend | No cartography exposure |

Nothing is served live. All cartography UX requires either running a generator script or querying the MCP tool directly.

---

## 3. What Artifacts Are Generated Today?

Every `tools/run_scientific_cartography_diagnostics.py` run writes to `artifacts/scientific_cartography/<as_of_date>[-suffix]/`:

| Artifact | Format | Level |
|---|---|---|
| `program_records.jsonl` | JSONL | Program/asset |
| `competitive_clusters.jsonl` | JSONL | Cluster |
| `landscape_features.jsonl` | JSONL | Cluster/disease feature |
| `cluster_coverage_report.json` | JSON | Summary |
| `landscape_feature_coverage_report.json` | JSON | Summary |
| `map_index.json` | JSON | Disease index |
| `disease_map_summary.json` | JSON | Disease level |
| `disease_map_summary.md` | Markdown | Disease level |
| `artifact_manifest.json` | JSON | Run manifest |
| `scientific_cartography_status.json` | JSON | Run status |

Phase 12 / 13c test runs additionally write:
- `disease_map_index.json` — richer per-disease index (DiseaseMapArtifactExporter)
- `disease_map_index.md`
- `diseases/` subdirectory (structure exists; currently empty in inspected runs)
- `scientific_cartography_manifest.json`

No HTML, SVG, or map-visualization artifacts are generated today.

---

## 4. Is There Any Interactive UI, or Only Static/Exported Artifacts?

Only static/exported artifacts. The LG4A HTML pages are static files (no JS interactivity, no fetch calls). No server is started. No React cartography view exists. No interactive map, tooltip, hover, or drill-down behavior.

---

## 5. Are Map Outputs Disease-Level, Asset-Level, Cluster-Level, or Index-Level?

All four levels exist in the artifact layer, but only disease-level and index-level are exposed in UX surfaces:

| Level | Artifact | UX Surface |
|---|---|---|
| Index (top) | `map_index.json` | MCP `get_atlas_data(diseases)` returns counts |
| Disease | `disease_map_summary.json/md` | LG4A disease_maps.html (table); MCP sample |
| Cluster | `competitive_clusters.jsonl` | No UX surface (file only, accessible via MCP `programs` category as line count) |
| Program/asset | `program_records.jsonl` | No UX surface |

No per-asset or per-company map view exists. No per-mechanism view.

---

## 6. Are There Tests for Dashboard/Map/Export Behavior?

Yes — solid coverage:

| Test File | Lines | What It Covers |
|---|---|---|
| `tests/scientific_cartography/test_lg4a_static_dashboard.py` | 279 | DashboardGenerator: all 6 pages, manifest, missing artifacts, governance flags |
| `tests/scientific_cartography/test_phase12_disease_map_artifacts.py` | 650 | DiseaseMapArtifactExporter: per-disease exports, slugs, index structure |
| `tests/test_mcp_cartography_tools.py` | ~200+ | MCP `get_atlas_data()` all categories |
| `tests/scientific_cartography/test_phase6_export_layer.py` | 287 | MapIndexExporter, DiseaseMapExporter, ArtifactManifestExporter |
| `tests/scientific_cartography/test_phase6_1_cli_export_artifacts.py` | 348 | CLI export tool integration |

---

## 7. What Are the Obvious UX Gaps?

### Critical data quality gap (blocks map usefulness)
- **Stage distribution: 100% unknown.** All 73,075 programs have stage=unknown in the postfix artifact. `stage_distribution` shows 0 in every named stage bucket (approved/filed/phase3/phase2/phase1/preclinical/discontinued). The R2 input-path fix is the active blocker here.
- **Mechanism normalization: 0.07% coverage.** 53 known / 73,022 unknown out of 73,075 programs. Only 3 diseases have ≥2 known mechanisms (lymphoma, type 2 diabetes mellitus, Metastatic Cancer). A lane-by-mechanism map would be nearly empty for most diseases.
- **Disease fragmentation: 9,865 diseases.** Most have 1-2 programs. An investor-readable map requires filtering to a specific disease or therapeutic area.

### Visual / UX gaps
- **No spatial map layout.** The LG4A `disease_maps.html` is an HTML table. No lane/column positioning, no node graph, no SVG.
- **No per-disease drill-down.** The Disease Maps page lists diseases; clicking a disease shows no detail page.
- **No mechanism-level or modality-level view.** No way to see "which diseases does mechanism X appear in."
- **No company pipeline view.** No per-ticker or per-company layout.
- **No asset-level nodes.** Individual program/asset names are not visible in any UX surface today.
- **No filtering or sorting in the static HTML.** No disease search, stage filter, or therapeutic-area grouping.
- **No cartography tab in React dashboard.** The live screener app at `frontend/dashboard/` has no Scientific Cartography exposure.

---

## 8. Safest Next UX Improvement Under the Freeze

**Generate a per-disease static HTML map page from existing artifacts — design and code spec only, no production wiring.**

Specifically: a standalone Python script (no server, no cron) that reads `disease_map_summary.json` and `competitive_clusters.jsonl` for one disease and writes `artifacts/scientific_cartography/map_ux/<disease_slug>/index.html`. The HTML contains:
- A stage-by-mechanism grid (gracefully handling the current all-unknown stage issue with a "stage data pending R2 fix" note)
- Asset/ticker node list per cluster
- Source-ref count and confidence encoding
- Governance header (READ_ONLY_DIAGNOSTIC)

This is safe because:
- It reads only from existing Sci-Cart artifact files (no production data sources)
- It writes only to a new `map_ux/` subdirectory within the existing artifact tree
- It does not touch ranker, selector, sizing, final_score, gates, snapshots, or portfolio
- It does not start a server
- It does not require the React app or any new dependencies

This is documented in detail in the companion design spec.

---

## Artifact Inventory (Current Run Paths)

```
artifacts/scientific_cartography/
├── 2026-06-23-postfix/       # most recent post-fix run
│   ├── program_records.jsonl      (73,075 programs)
│   ├── competitive_clusters.jsonl  (9,900 clusters)
│   ├── landscape_features.jsonl    (73,075 features)
│   ├── map_index.json              (9,865 diseases)
│   ├── disease_map_summary.json
│   ├── disease_map_summary.md
│   ├── cluster_coverage_report.json
│   ├── landscape_feature_coverage_report.json
│   ├── artifact_manifest.json
│   └── scientific_cartography_status.json
├── 2026-06-23-fixed/
├── 2026-06-23/
├── 2026-06-22/
├── 2026-06-17-{golden,fixed,mondo,with-real-data,withdata,}/
├── 2026-06-10-with-trials/
└── 2026-06-10/               # Phase 6 run (has diseases/ dir + manifest)
    ├── diseases/              (empty — DiseaseMapArtifactExporter not yet populated)
    └── scientific_cartography_manifest.json
artifacts/scientific_cartography_phase13c_test/
    ├── disease_map_index.json  (Phase 12/13 schema; diseases: 0 — empty test run)
    ├── disease_map_index.md
    └── scientific_cartography_manifest.json
```

---

## Summary

Scientific Cartography has a solid artifact-export layer (JSON + Markdown) and a working static HTML review dashboard (LG4A) focused on LG1/LG2/LG3 governance metadata. The "Disease Maps" page in LG4A is a list/table, not a visual landscape map. No spatial SVG or lane-layout map exists anywhere in the repo. The React screener frontend has no cartography exposure.

The most significant data quality blocker for a useful visual map is that stage data is 100% unknown and mechanism normalization covers only 0.07% of programs — both expected to improve post-R2 input-path fix. Prototyping the map UX now with graceful unknown-state handling is viable and safe.

---

**Verdict**: `WARN_MAP_UX_FRAGMENTED_ARTIFACT_ONLY`

The current map UX is artifact-only (JSON, Markdown, static HTML table). No visual landscape map exists. No production coupling found. Safe to prototype a static visual map under the current freeze.
