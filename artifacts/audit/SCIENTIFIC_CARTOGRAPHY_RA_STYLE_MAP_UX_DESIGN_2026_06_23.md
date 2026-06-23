# Scientific Cartography Map UX v0.2 — Design Spec

**Date**: 2026-06-23  
**Status**: `DESIGN_ONLY_RA_STYLE_MAP_UX_READY_FOR_STATIC_PROTOTYPE`  
**Version**: v0.2a (design spec only)  
**Governance**: READ_ONLY_DIAGNOSTIC | NO_PRODUCTION_WIRING | NO_SCORING | NO_FREEZE_LIFT

---

## 1. Product Goal

Scientific Cartography Map UX v0.2 builds **strategic landscape maps for investment research** — original maps (not copies of RA Capital's visual design or branding) that serve the same functional purpose: organizing biotech programs by disease, mechanism, modality, and clinical stage to help identify competitive crowding, white space, stage maturity, and strategic positioning.

An RA-style map reads in 5–10 minutes and tells an investor:
- Which mechanisms are crowded in a disease area
- Where the late-stage assets are and who owns them
- Where stage gaps or mechanism gaps represent white space
- Which public companies are most exposed to the disease area

This is an internal research tool. It is diagnostic-only. It makes no investment recommendations, no portfolio actions, and no scoring changes.

### What "RA-style" means for this system

Not a copy of TechAtlas. The functional pattern:
```
Disease / indication map
→ organized by mechanism, modality, stage, asset/company
→ highlights crowding, white space, stage maturity, strategic gaps
→ readable by an investor in 5–10 minutes
```

### Known data quality constraints (2026-06-23)

The current artifact layer has two significant limitations that affect map quality:

1. **Stage data is 100% unknown.** All stage_distribution buckets show 0 in the current postfix artifact. The R2 input-path fix is the active blocker. Maps must gracefully handle this with a `[stage data pending R2 fix]` label and fall back to program-count-only layout.

2. **Mechanism normalization covers ~0.07% of programs.** 53 of 73,075 programs have a known mechanism. Only 3 diseases have ≥2 known mechanisms. Map lanes that depend on mechanism must gracefully degrade to "mechanism: unknown" with a diagnostic note.

These do not prevent prototyping. The design handles both as explicit unknown states with visible labels, so maps remain honest and useful even with sparse data.

---

## 2. Map Types

### 2.1 Disease Landscape Map (v0.2b prototype)

**Question answered**: "In this disease, who is doing what, how advanced are they, and where is the field crowded vs. sparse?"

```
Rows / lanes    = mechanism class or target (e.g., JAK inhibitor, PD-1 inhibitor, GLP-1 agonist)
                  → one row per mechanism; "unknown mechanism" grouped at bottom
Columns         = clinical stage (approved → phase 3 → phase 2 → phase 1 → preclinical → unknown)
Nodes           = programs/assets
Node label      = asset_name + ticker (if public)
Node style      = encodes modality, confidence, source_refs count
```

**Primary data sources**: `disease_map_summary.json`, `competitive_clusters.jsonl`, `program_records.jsonl`

### 2.2 Mechanism / Modality Landscape Map (v0.2c)

**Question answered**: "Across which diseases is this mechanism being developed, and how far along is it?"

```
Rows / lanes    = disease area or therapeutic area grouping
Columns         = clinical stage
Nodes           = programs/assets using this mechanism
Node label      = asset_name + ticker
```

**Primary data sources**: `map_index.json`, `program_records.jsonl`

### 2.3 Company Pipeline Map (v0.2d)

**Question answered**: "What does this company's pipeline look like across diseases and stages, and where do they have concentration or whitespace?"

```
Rows / lanes    = disease area
Columns         = clinical stage
Nodes           = programs for this ticker
Node label      = asset_name + indication
```

**Primary data sources**: `program_records.jsonl` filtered by ticker

---

## 3. Data Model

### Inputs from Existing Sci-Cart Artifacts

All inputs are read from existing artifact files. No new data sources. No production pipeline reads.

| Artifact | Path | Used For |
|---|---|---|
| `disease_map_summary.json` | `artifacts/scientific_cartography/<date>/` | Disease-level overview, mechanism/modality lists, tickers |
| `map_index.json` | same | Disease index, counts, governance check |
| `competitive_clusters.jsonl` | same | Cluster membership, stage distribution per cluster |
| `program_records.jsonl` | same | Per-asset data: disease, mechanism, modality, stage, ticker, confidence, source_refs |
| `landscape_features.jsonl` | same | Crowding scores, white-space proxy scores |
| `artifact_manifest.json` | same | Governance validation before rendering |

### Required Fields Per Node (ProgramRecord)

| Field | Source | Notes |
|---|---|---|
| `disease_name` | program_records | Primary lane assignment |
| `disease_id` / `mondo_id` | program_records | Stable ID for deduplication |
| `company` / `ticker` | program_records | Node label; public companies get ticker badge |
| `asset_name` | program_records | Node label |
| `mechanism_class` | program_records | Row/lane key; "unknown" handled explicitly |
| `target` | program_records | Secondary lane refinement |
| `modality` | program_records | Node visual encoding (shape or color class) |
| `clinical_stage` | program_records | Column key; "unknown" handled explicitly |
| `source_refs` | program_records | Node size / confidence signal |
| `confidence` | program_records | Node opacity or border weight |
| `cluster_id` | competitive_clusters | Cluster grouping |

### Crowding / White-Space Fields (from LandscapeFeatureRecord)

| Field | Use |
|---|---|
| `mechanism_crowding_score` | Highlight crowded mechanism lanes in orange/red |
| `stage_crowding_score` | Highlight crowded stage columns |
| `white_space_score` | Highlight lane/column cells with low program density in blue |

---

## 4. Visual Grammar

### Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DISEASE: Type 2 Diabetes Mellitus  │  as_of: 2026-06-23  │  READ_ONLY_DIAG │
├──────────────┬────────────┬─────────┬─────────┬──────────┬──────────────────┤
│  Mechanism   │  Approved  │ Phase 3 │ Phase 2 │ Phase 1  │  Preclinical     │
├──────────────┼────────────┼─────────┼─────────┼──────────┼──────────────────┤
│ GLP-1 agonst │  ●AMGN     │ ●REGN   │ ●ABSI   │          │                  │
├──────────────┼────────────┼─────────┼─────────┼──────────┼──────────────────┤
│ TNF inhibitor│            │ ●BIIB   │         │ ●AMRX    │                  │
├──────────────┼────────────┼─────────┼─────────┼──────────┼──────────────────┤
│ Unknown mech │            │         │         │          │  (N programs)    │
└──────────────┴────────────┴─────────┴─────────┴──────────┴──────────────────┘
```

### Node Encoding

| Dimension | Encoding | Values |
|---|---|---|
| Modality | Node shape class | `circle` = small molecule, `square` = mAb, `diamond` = gene therapy, `hexagon` = cell therapy, `dot` = unknown |
| Confidence | Node opacity | High confidence = solid; Low confidence = 70% opacity |
| Source refs count | Node border weight | ≥3 refs = bold border; 1–2 = normal; 0 = dashed |
| Crowding | Cell background | Normal = white; Crowded = light orange; Very crowded = orange |
| White space | Cell background | Low density = light blue |
| Public ticker | Ticker badge | Bold all-caps label when ticker available |

### Node Label Format

```
[asset_name]
[TICKER]
```

Example: `semaglutide / AMGN`

When asset_name is unknown: `[unknown program] / TICKER`

### Unknown State Labels

When data is missing, show explicit diagnostic labels rather than empty cells:

- Stage = unknown → column labeled `[unknown stage — pending R2 fix]`
- Mechanism = unknown → lane labeled `[unknown mechanism]` at bottom of grid
- No source_refs → node labeled with `(unverified)` in smaller font

### Sidecards / Tooltips

Each node in HTML renders a tooltip or expandable sidecard showing:
- disease_name + mondo_id
- mechanism_class + target
- modality
- clinical_stage
- source_refs list (truncated at 5)
- confidence score
- cluster_id
- diagnostic note if any field is unknown

---

## 5. Static-First Implementation

**No server. No React app. No cron. No production wiring.**

Generation pipeline:
1. Python script reads artifact JSON/JSONL files for a specific disease slug and date
2. Builds in-memory data model (nodes, lanes, columns, crowding)
3. Renders to inline HTML + inline SVG (no external CDN, no JS framework)
4. Writes static output files to `artifacts/scientific_cartography/map_ux/<disease_slug>/`

All CSS and JS is inlined. Output is a self-contained HTML file openable with `file://` in any browser.

Governance check at generation time:
- Read `artifact_manifest.json` and verify `read_only_diagnostic: true`
- Abort with error if any forbidden data source is detected (rankings.csv, production_data, selector, sizing, final_score)
- Embed governance header in generated HTML

---

## 6. First Prototype

### Disease Selection

**Recommended prototype disease: `type 2 diabetes mellitus`**

Rationale from audit findings:
- 1,046 programs (manageable — not overwhelming like lymphoma's 5,495)
- 2 known mechanism classes: `GLP-1 receptor agonist`, `TNF inhibitor`
- 2 known modalities: `monoclonal antibody`, `small molecule`
- 53 public tickers (names investors recognize: AMGN, AZN, REGN, SNY, VRTX, etc.)
- 3 competitive clusters
- 513 source references
- Low normalization ambiguity (both mechanisms are well-defined)

**Fallback**: `lymphoma` (5,495 programs, 89 tickers, 2 mechanisms) — more content but will require pagination or filtering to be readable.

### Output File Structure

```
artifacts/scientific_cartography/map_ux/
└── type-2-diabetes-mellitus/
    ├── index.html      ← self-contained HTML map (inline CSS + JS)
    ├── map.svg         ← standalone SVG for embedding in reports
    ├── map.json        ← structured map data (nodes, lanes, columns, metadata)
    └── README.md       ← governance note + how to regenerate
```

### map.json Schema

```json
{
  "disease_name": "type 2 diabetes mellitus",
  "disease_slug": "type-2-diabetes-mellitus",
  "as_of_date": "2026-06-23",
  "artifact_source": "artifacts/scientific_cartography/2026-06-23-postfix",
  "governance": { "read_only_diagnostic": true, ... },
  "lanes": [
    {
      "mechanism_class": "GLP-1 receptor agonist",
      "crowding_score": null,
      "nodes": [
        {
          "asset_name": "...",
          "ticker": "AMGN",
          "modality": "monoclonal antibody",
          "clinical_stage": "unknown",
          "confidence": 0.8,
          "source_refs_count": 3,
          "cluster_id": "..."
        }
      ]
    }
  ],
  "stage_columns": ["approved", "phase3", "phase2", "phase1", "preclinical", "unknown"],
  "warnings": ["stage_data_all_unknown_pending_r2_fix"],
  "generated_at_utc": "..."
}
```

---

## 7. UX Acceptance Criteria

A reader of the generated map must be able to identify, in under 10 minutes:

- [ ] Top crowded mechanisms in the disease (or explicit "mechanism data sparse" note)
- [ ] Stage distribution across programs (or explicit "stage data pending R2 fix" note)
- [ ] Major public companies/tickers with exposure to the disease
- [ ] Which clusters exist and what mechanisms they contain
- [ ] White-space candidates (mechanism+stage cells with low/no programs)
- [ ] Low-confidence areas (programs with few source refs, shown as dashed/faded nodes)
- [ ] Clear governance header: READ_ONLY_DIAGNOSTIC, no investment recommendation

Additional requirements:
- Map is deterministic: same input artifacts → same output
- Map is reproducible: can be regenerated with the same CLI command
- Source refs are preserved: each node links to source_refs count; sidecard shows list
- Unknown states are labeled explicitly, never silently omitted
- No ranking, no scoring, no position sizing, no investment recommendation anywhere in the output

---

## 8. Governance

| Constraint | Status |
|---|---|
| Diagnostic-only | Enforced: no scoring, no model output, no recommendation |
| No ranker/selector/sizing/final_score changes | Enforced: map reads only Sci-Cart artifacts |
| No gates/snapshots/portfolio changes | Enforced: no pipeline writes |
| No investment/trading recommendations | Enforced: governance header in every output file |
| No model promotion | N/A: no model involved |
| No freeze lift | Production model freeze remains ACTIVE throughout |
| No server | Enforced: static file output only |
| No production hook | Enforced: not wired to orchestrator |
| No cron | Enforced: manual CLI only |

Forbidden data sources (same as LG4A governance check):
```python
FORBIDDEN_DATA_SOURCES = {
    "rankings.csv", "portfolio_positions.csv", "screen_output.json",
    "production_data", "selector", "sizing", "final_score"
}
```

---

## 9. Implementation Sequence

### v0.2a — Design spec only (THIS DOCUMENT)
- Audit findings reviewed
- Map types, data model, visual grammar, and governance defined
- Prototype disease selected (type 2 diabetes mellitus)
- No code written

### v0.2b — Static HTML/SVG prototype for one disease
Deliverables:
- `tools/generate_scientific_cartography_map.py` — CLI script
  - Args: `--disease <slug>`, `--artifact-dir <path>`, `--output-dir <path>`
  - Reads: `disease_map_summary.json`, `competitive_clusters.jsonl`, `program_records.jsonl`, `artifact_manifest.json`
  - Writes: `index.html`, `map.svg`, `map.json`, `README.md`
- Test: `tests/scientific_cartography/test_map_generator.py`
- One disease only (type 2 diabetes mellitus)
- Full unknown-state handling for stage/mechanism gaps
- Governance header + forbidden-source check

### v0.2c — Mechanism landscape map
- Add `--map-type mechanism` flag to same CLI
- Rows = disease areas, cols = stage
- Filter by mechanism class argument

### v0.2d — Company pipeline map
- Add `--map-type company` and `--ticker <TICKER>` args
- Rows = disease areas, cols = stage
- Filtered to one ticker's programs

---

## 10. Verdict

`DESIGN_ONLY_RA_STYLE_MAP_UX_READY_FOR_STATIC_PROTOTYPE`

The design is complete. The data model is confirmed against existing artifacts. The prototype disease (type 2 diabetes mellitus) has been verified as the best coverage candidate in the current artifact layer. Unknown-state handling for stage and mechanism data gaps is specified. No code has been written or modified.

Next step when authorized: implement v0.2b (static HTML/SVG prototype for type 2 diabetes mellitus).
