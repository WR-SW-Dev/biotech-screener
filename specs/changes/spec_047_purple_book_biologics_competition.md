# Change Spec: Purple Book Biologics Competition Layer

**Status**: DRAFT
**Author**: Claude / operator
**Date**: 2026-04-01
**Ruleset impact**: Phase 1-2 = NO; Phase 3 = candidate-only (requires promotion pipeline)

---

## Objective

Integrate FDA Purple Book data as a **slow-moving competitive landscape layer**
for commercial-stage biologics, providing biosimilar/interchangeability
screening, reference-product mapping, exclusivity context, and franchise erosion
risk assessment.

## Motivation

The DEM currently has no structured view of biologic competition. For commercial-
stage biologics, the key question is often "how protected is this franchise?"
rather than "will this read out?" Purple Book provides the authoritative FDA
registry of licensed biologics, biosimilars, interchangeables, and reference
product exclusivity — exactly the structural context needed for commercial
biologics risk assessment.

**Division of labor:**
- Purple Book = biologics competition / exclusivity context
- DealForma (Spec 046) = transaction / valuation context
- Herald + Grok + CRT = event flow and catalyst resolution

## Key Design Principles

1. **Commercial-stage focus** — most useful for approved biologics, not dev-stage
2. **Slow-moving priors** — monthly CSV download, not daily refresh
3. **Dashboard-first** — competition card before any model features
4. **Shadow-before-promote** — minimum 8 weeks shadow for any DEM overlay
5. **Biologics only** — not applicable to small-molecule competition

## PIT / Data Constraints

- [x] No lookahead — all fields use licensing date / approval date as PIT anchor
- [x] Data source: FDA Purple Book monthly CSV download (purplebooksearch.fda.gov)
- [x] Historical availability: Purple Book covers all currently licensed biologics;
      monthly snapshots available for recent years
- [x] Known gaps: exclusivity dates not always listed; biosimilar approval != market
      launch; CBER products (CGT) have limited biosimilar relevance

## Rollout Phases

### Phase 1: Dashboard Context (no model integration)

Add a **Biologic Competition** card to TickerDetail with:
- Is this a licensed biologic / reference product?
- Biosimilar count + names
- Interchangeable count + names
- Reference product exclusivity status
- Links to FDA labels

**Risk**: Zero. Read-only display, no ranking impact.

### Phase 2: Shadow Features (IC test required)

| Feature | Definition | Cadence |
|---------|-----------|---------|
| `is_fda_licensed_biologic` | Binary: company has >= 1 licensed biologic in Purple Book | Monthly |
| `is_reference_product` | Binary: product is a reference product (has biosimilar applicants) | Monthly |
| `biosimilar_count` | Count of licensed biosimilars for company's reference products | Monthly |
| `interchangeable_count` | Count of interchangeable biosimilars | Monthly |
| `has_biosimilar_competition` | Binary: any biosimilar licensed for reference product | Monthly |
| `has_interchangeable_competition` | Binary: any interchangeable licensed | Monthly |
| `reference_product_exclusivity_known` | Binary: exclusivity date is listed | Monthly |
| `reference_product_exclusivity_expired` | Binary: exclusivity has expired as of snapshot date | Monthly |
| `biologic_competition_pressure_score` | Composite: biosimilar_count + interchangeable_count + exclusivity_expired | Monthly |

### Phase 3: Bounded Overlay (only if Phase 2 evidence supports)

If `biologic_competition_pressure_score` shows IC:
- Integrate as commercial-archetype context in L4b
- Weight cap: 0.10 (very bounded — applies only to commercial biologics)
- Only applies to archetype=commercial with licensed biologics

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| Purple Book CSV | `production_data/purple_book.json` | list of product dicts |
| Universe tickers | `production_data/universe.json` | ticker list |
| Rankings snapshot | rankings.csv | standard DEM output |
| Company-to-product mapping | `production_data/purple_book_ticker_map.json` | ticker → product names |

### Purple Book Record Schema

```json
{
  "bla_number": "string",
  "product_name_proprietary": "string",
  "product_name_nonproprietary": "string",
  "applicant": "string",
  "licensing_date": "YYYY-MM-DD",
  "product_category": "string",
  "is_biosimilar": false,
  "is_interchangeable": false,
  "reference_product_bla": "string | null",
  "reference_product_name": "string | null",
  "exclusivity_expiry_date": "YYYY-MM-DD | null",
  "marketing_status": "string | null"
}
```

## Outputs

### Phase 1 (dashboard only)

| Output | Destination | Schema |
|--------|-------------|--------|
| Competition card data | `/api/purple_book/{ticker}` | JSON: products, biosimilar_count, interchangeable_count, exclusivity |

### Phase 2 (shadow features)

| Output | Destination | Schema |
|--------|-------------|--------|
| Shadow feature set | shadow artifact | dict per ticker with all Phase 2 fields |

## Invariants

1. **PIT-safe**: all fields use licensing_date; no future approvals leak
2. **Deterministic**: same Purple Book CSV + same universe → identical output
3. **Bounded**: counts are non-negative; binary flags are 0/1; composite clipped [-3, 3]
4. **Fail-closed**: ticker with no Purple Book match gets neutral features
5. **No ranking impact Phase 1-2**: dashboard and shadow only
6. **Monthly cadence only**: no more frequent than monthly refresh
7. **Biologics only**: features are meaningless for small-molecule-only companies

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| No Purple Book CSV downloaded | Phase 1-2 emit nothing; dashboard shows "No data" |
| Ticker not in product mapping | Neutral features; dashboard shows "No biologic products found" |
| Exclusivity date missing | `reference_product_exclusivity_known` = 0; no expiry flag |
| CSV schema change | Ingest validates required columns; hard fail on missing |
| Stale data (> 90 days old) | WARN gate; features still computed but flagged |

## Validation Plan

### Tests
- [ ] `test_purple_book_ingest_parsing` — CSV → JSON normalization
- [ ] `test_purple_book_biosimilar_count` — correct count by reference product
- [ ] `test_purple_book_interchangeable_count` — correct interchangeable filtering
- [ ] `test_purple_book_exclusivity_pit_safe` — future dates excluded
- [ ] `test_purple_book_ticker_mapping` — company name → ticker resolution
- [ ] `test_purple_book_empty_match_neutral` — no match → neutral output
- [ ] `test_purple_book_dashboard_schema` — API returns valid JSON
- [ ] `test_purple_book_deterministic` — same inputs → identical output
- [ ] `test_competition_pressure_score_bounded` — z-score clipped [-3, 3]

## Expected Effect Size

**Phase 1**: No IC impact. Operator context for commercial biologics review.

**Phase 2**: UNKNOWN. Hypothesis: `biologic_competition_pressure_score` may show
weak negative IC for commercial biologics (more competition → lower returns).
Effect is narrow — only ~15-20% of universe are commercial biologics.

## Non-Goals

- Does not cover small-molecule competition (use other sources)
- Does not predict biosimilar approval timing
- Does not model biosimilar market share erosion curves
- Does not replace DealForma for M&A/licensing context
- Does not bypass promotion governance

## Data Integration Path

```
FDA Purple Book CSV (monthly download from purplebooksearch.fda.gov)
  → scripts/ingest_purple_book.py          (parse, normalize, map to tickers)
  → production_data/purple_book.json       (monthly refresh, PIT-stamped)
  → production_data/purple_book_ticker_map.json  (company → ticker mapping)
  → common/purple_book_features.py         (feature builder)
  → dashboard/app.py /api/purple_book      (Phase 1: dashboard endpoint)
  → tools/run_daily_production.py          (Phase 2: shadow features, conditional)
```

---

## Implementation Log

### 2026-04-01 — Draft spec
- Files modified: `specs/changes/spec_047_purple_book_biologics_competition.md`
- Tests added: 0
- Commit: pending

---

*Template version: 1.0.0 — see specs/SYSTEM_SPEC.md for system invariants*
