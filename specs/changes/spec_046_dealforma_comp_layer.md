# Change Spec: DealForma Deal Comp & Dealability Layer

**Status**: DRAFT
**Author**: Claude / operator
**Date**: 2026-04-01
**Ruleset impact**: Phase 1-2 = NO; Phase 3 = candidate-only (requires promotion pipeline)

---

## Objective

Integrate DealForma biopharma deal data as a **slow-moving comp and prior layer**
for M&A probability estimation, valuation benchmarking, and operator-facing
dashboard context. This is a fundamental comp layer, not a fast tactical signal.

## Motivation

The DEM currently has no structured M&A comp data. Takeout probability, deal
structure precedent, and valuation benchmarks are invisible to the model and
operator dashboard. DealForma provides curated licensing, M&A, venture, and
asset deals with financial comps, filterable by stage, modality, indication,
target, and territory. The data is daily human-curated with export and (for
site-licensed customers) API access.

## Key Design Principles

1. **Slow-moving priors, not fast signals** — deal data updates monthly, not daily
2. **Comp-context first, model features second** — dashboard cards before shadow features
3. **Shadow-before-promote** — minimum 8 weeks of shadow IC before any DEM overlay
4. **Export-first** — start with manual CSV export; upgrade to API only if IC warrants subscription
5. **Bucket definition is critical** — therapeutic_area + phase + modality is the natural comp grouping

## PIT / Data Constraints

- [x] No lookahead — all deal comps use deal announcement date, not close date
- [x] Data source: DealForma export (CSV initially, API later if warranted)
- [ ] Historical availability: UNKNOWN — depends on DealForma export depth; platform
      claims comprehensive coverage of biopharma deals
- [x] Known gaps: incomplete deal terms (many deals have undisclosed financials),
      contingent value structures distort comparability, selection bias toward
      larger / disclosed deals

## Rollout Phases

### Phase 1: Dashboard Context (no model integration)

Add a **Deal Comps** card to TickerDetail with:
- Recent same-bucket deals (TA + phase + modality, 24 months)
- Median upfront / total deal value for same bucket
- Most active acquirers in that therapeutic area
- Licensing vs M&A split
- CVR/earnout prevalence
- Commercial-stage revenue multiple context (for approved assets)

**Risk**: Zero. Read-only display, no ranking impact.

### Phase 2: Shadow Features (IC test required before any use)

Build slow-moving features, refresh monthly, shadow alongside DEM:

| Feature | Definition | Cadence |
|---------|-----------|---------|
| `deal_activity_score_24m` | Recency-weighted count of deals in same TA+stage bucket (half-life 6mo) | Monthly |
| `mna_count_same_ta_stage_24m` | Raw count of M&A transactions for same TA+phase bucket, 24 months | Monthly |
| `licensing_heat_same_target_12m` | Count of licensing deals involving same biological target, 12 months | Monthly |
| `big_pharma_interest_flag` | Binary: any top-20 pharma acquirer active in same TA+modality, 12 months | Monthly |
| `commercial_comp_revenue_multiple` | Median EV/revenue for approved assets in same TA (from DealForma drug sales) | Quarterly |
| `dealability_prior_score` | Composite: deal_activity + mna_count + licensing_heat, z-scored | Monthly |

**IC threshold for promotion**: >0.03 at 60d, t>2.0, minimum 8 weeks of shadow.

### Phase 3: Bounded Overlay (only if Phase 2 evidence supports)

If `dealability_prior_score` clears IC bar:
- Integrate as L4b layer in decision engine (same pattern as inst_sort)
- Weight cap: 0.15 (lower than inst_sort 0.30 — deal data less timely)
- Only applies to eligible names (not gated/excluded)
- Buffer: same as current (30)
- Requires full promotion pipeline: candidate ruleset → replay → evidence packet

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| DealForma deal records | `production_data/dealforma_comps.json` | list of deal dicts (see schema below) |
| Universe tickers | `production_data/universe.json` | list of ticker strings |
| Rankings snapshot | `production_data/rankings_*.csv` | standard DEM output |
| Therapeutic area | rankings / `therapeutic_area` column | string |
| Lead program phase | rankings / `lead_program_phase` column | string |
| Modality | rankings / `modality` or derived | string |

### DealForma Record Schema

```json
{
  "deal_id": "string",
  "deal_type": "M&A | licensing | asset_purchase | venture | IPO | follow_on | spin_out | academic",
  "announcement_date": "YYYY-MM-DD",
  "close_date": "YYYY-MM-DD | null",
  "acquirer": "string",
  "target": "string",
  "target_ticker": "string | null",
  "therapeutic_area": "string",
  "indication": "string | null",
  "modality": "string | null",
  "stage": "preclinical | phase_1 | phase_2 | phase_3 | approved | commercial",
  "biological_target": "string | null",
  "territory": "string | null",
  "upfront_value_mm": "float | null",
  "total_value_mm": "float | null",
  "contingent_value_mm": "float | null",
  "has_cvr": "bool",
  "has_earnout": "bool",
  "revenue_multiple": "float | null",
  "source_url": "string | null"
}
```

## Outputs

### Phase 1 (dashboard only)

| Output | Destination | Schema |
|--------|-------------|--------|
| Deal comp card data | `/api/deal_comps/{ticker}` | JSON: recent_deals, median_upfront, median_total, top_acquirers, licensing_mna_split, cvr_prevalence |

### Phase 2 (shadow features)

| Output | Destination | Schema |
|--------|-------------|--------|
| `deal_activity_score_24m` | shadow artifact | float, z-scored |
| `mna_count_same_ta_stage_24m` | shadow artifact | int >= 0 |
| `licensing_heat_same_target_12m` | shadow artifact | int >= 0 |
| `big_pharma_interest_flag` | shadow artifact | 0/1 |
| `commercial_comp_revenue_multiple` | shadow artifact | float / null |
| `dealability_prior_score` | shadow artifact | float, z-scored |

### Phase 3 (overlay — conditional)

| Output | Destination | Schema |
|--------|-------------|--------|
| `dealability_overlay_z` | rankings.csv | float, bounded z |
| Sort contribution | rankings.csv / `sc_dealability` | float |

## Invariants

1. **PIT-safe**: all deal comps use announcement_date, not close_date. No future
   deals leak into historical features.
2. **Deterministic**: same deal export + same universe → identical features.
3. **Bounded**: all z-scores clipped to [-3.0, 3.0]. Binary flags are 0/1.
   Revenue multiples clipped to reasonable range [0, 100x].
4. **Fail-closed on missing data**: ticker with no comp matches gets neutral
   (z=0) features, not optimistic inference.
5. **No direct ranking impact in Phase 1-2**: dashboard-only and shadow-only.
   Any DEM integration requires Phase 3 promotion.
6. **Monthly cadence only**: features must not be refreshed more frequently than
   monthly. Deal data is slow-moving by nature.
7. **Export-first**: no API dependency until IC evidence justifies subscription.
8. **Rollback-safe**: Phase 3 overlay is fully removable via candidate ruleset
   or feature disable.

## Bucket Definition

The natural comp grouping for deal matching:

**Primary bucket**: `therapeutic_area + stage`
- Example: "Oncology + Phase 2", "Rare Disease + Approved"

**Secondary refinement** (when primary bucket has >= 10 deals):
- Add `modality` (small molecule, antibody, gene therapy, etc.)
- Add `biological_target` (for licensing heat)

**Fallback** (when primary bucket has < 5 deals):
- Widen to `therapeutic_area` only (drop stage filter)
- If still < 3 deals, mark `dealability_prior_score` as null/neutral

Bucket sparsity is the primary risk. Track `n_comps_in_bucket` alongside every
feature to surface confidence.

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| No DealForma export available | Phase 1-2 emit nothing; no ranking impact |
| Ticker's TA+stage bucket has 0 deals | All features neutral (z=0); dashboard shows "No comps" |
| Bucket has < 5 deals | Features computed but flagged low-confidence; dashboard shows count |
| Deal terms undisclosed (upfront=null) | Count-based features unaffected; value-based features skip record |
| Stale export (> 60 days old) | WARN gate in production; features still computed but flagged stale |
| DealForma schema change | Ingest script validates required fields; hard fail on missing |
| API unavailable (Phase 3+) | Fall back to most recent CSV export; WARN in manifest |

## Validation Plan

### Tests (write BEFORE implementation)

Phase 1:
- [ ] `test_deal_comp_bucket_matching` — correct TA+stage grouping
- [ ] `test_deal_comp_empty_bucket_neutral` — no deals → neutral output
- [ ] `test_deal_comp_median_calculation` — correct median with nulls excluded
- [ ] `test_deal_comp_pit_safety` — deals after snapshot date excluded
- [ ] `test_deal_comp_dashboard_endpoint_schema` — API returns valid JSON

Phase 2:
- [ ] `test_deal_activity_score_recency_weighting` — half-life 6mo applied correctly
- [ ] `test_mna_count_filter_type` — only M&A deals counted
- [ ] `test_licensing_heat_target_match` — biological target matching works
- [ ] `test_big_pharma_flag_top20` — only top-20 pharma triggers flag
- [ ] `test_dealability_composite_zscore` — z-scored within universe
- [ ] `test_dealability_deterministic` — same inputs → identical output
- [ ] `test_dealability_bounded` — z-scores clipped to [-3, 3]
- [ ] `test_dealability_sparse_bucket_neutral` — < 5 deals → neutral

Phase 3 (conditional):
- [ ] `test_dealability_overlay_bounded` — overlay weight capped at 0.15
- [ ] `test_dealability_overlay_rollback` — feature toggle disables cleanly
- [ ] `test_dealability_replay_bars` — primary +0.20pp, guardrail -0.05pp

### Evaluation (if signal/ranking change — Phase 3 only)

- [ ] Signal evidence packet on candidate rerank vs active baseline
- [ ] Horizons: 20d / 63d / 84d
- [ ] Coverage >= 50% (bucketed features populated for majority of universe)
- [ ] IC > 0.03 at 60d, t > 2.0
- [ ] Primary bar: +0.20pp at longest evaluated horizon
- [ ] Guardrail: no worse than -0.05pp on any evaluated horizon
- [ ] Minimum 8 weeks of shadow data

### Integration

- [ ] Full suite passes
- [ ] No pre-commit hook failures
- [ ] Artifact schema version stamped
- [ ] Candidate ruleset rollback-safe
- [ ] Monthly refresh cron documented

## Expected Effect Size

**Phase 1** (dashboard): No IC impact. Operator productivity improvement.

**Phase 2** (shadow features): UNKNOWN — needs evaluation. Hypothesis:
`dealability_prior_score` may show low-positive IC (0.02-0.05) at 60d+ horizons
for dev-stage names in active deal sectors. Effect likely strongest in rare
disease and oncology where M&A activity is concentrated.

**Phase 3** (overlay): Conditional. If IC > 0.03, bounded overlay with w=0.15
would contribute modest sort tilt. Expected portfolio-level impact: small
(deal data is slow, universe is mid-cap biotech where not all names are
acquisition targets).

Best case: defensible M&A probability prior that improves dev-name ordering in
active deal sectors. Worst case: intuitive but redundant with existing
optionality signal, yielding < 0.03 IC.

## Non-Goals

- Does not build a real-time M&A prediction model
- Does not use stock price to infer deal probability
- Does not replace DEM sort anchor or tiering logic
- Does not require DealForma API subscription in Phase 1-2
- Does not become a hard eligibility gate
- Does not replace milestone optionality (Spec 041) — complementary, not competing
- Does not model deal terms or contingent structures (Phase 1-2 uses counts, not values)
- Does not bypass promotion / rollback governance
- Does not refresh more frequently than monthly

## Data Integration Path

```
DealForma export (CSV)
  → scripts/ingest_dealforma.py        (parse, validate, normalize)
  → production_data/dealforma_comps.json  (monthly refresh, PIT-stamped)
  → common/dealforma_features.py        (feature builder)
  → dashboard/app.py /api/deal_comps    (Phase 1: dashboard endpoint)
  → tools/run_daily_production.py Step 5n  (Phase 2: shadow features)
  → decision_engine.py L4b              (Phase 3: bounded overlay, conditional)
```

## Top-20 Pharma List (for `big_pharma_interest_flag`)

Maintain in `production_data/big_pharma_acquirers.json`:
Pfizer, Merck, J&J, Roche, Novartis, AbbVie, AstraZeneca, Lilly, BMS,
Sanofi, GSK, Amgen, Gilead, Regeneron, Vertex, Biogen, Takeda, Bayer,
Novo Nordisk, Daiichi Sankyo.

Update annually or when top-20 by biopharma revenue changes.

---

## Implementation Log

### 2026-04-01 — Draft spec
- Files modified: `specs/changes/spec_046_dealforma_comp_layer.md`
- Tests added: 0
- Commit: pending

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
