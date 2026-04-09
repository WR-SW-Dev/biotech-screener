# Spec 058 — Timing & Event Quality Infrastructure

**Status**: COMPLETE
**Author**: arrenchulz
**Date**: 2026-04-05
**Ruleset impact**: NO (all changes are diagnostic/dashboard/non-binding)

---

## Objective

Build compounding infrastructure for timing adaptation and event quality tracking.
Two pillars: (1) timing becomes family- and horizon-aware with calibration views,
(2) event quality gets source reliability tracking and a unified review packet.
All changes are dashboard-only / diagnostic / non-binding.

## PIT / Data Constraints

- [x] No lookahead — all data access satisfies PIT rules
- [x] Data source: production snapshots, calibration ledger, source_reliability.json, CRT
- [x] Historical availability: all existing production data
- [x] Known gaps: calibration ledger has limited resolved outcomes; CRT small (12 seeds)

## Architecture

### Timing Infrastructure (Items 1-5)

**1. Timing buckets** — classify each catalyst into explicit categories:
- Family: REGULATORY, CLINICAL, SAFETY
- Hardness: HARD, SOFT (from `is_hard_catalyst` + source quality)
- Horizon: NEAR (0-30d), MEDIUM (31-90d), FAR (91+d)

These buckets drive both probability assignment and dashboard display.

**2. Family-aware calibration ledger** — extend existing `calibration_ledger.jsonl`:
- Add fields: `horizon_bucket`, `hardness`, `source_provenance`
- Add calibration-by-slice view: family × horizon × hard/soft
- Trailing 90-day window for non-stationarity visibility

**3. Enhanced timing warnings** — structured warning labels:
- `SHORT_DATED_REVISION_RISK` — near-term + recent date pushout
- `LOW_CONFIDENCE_DATE` — precision MONTH+ or confidence < 0.50
- `STALE_EVENT_RECORD` — last AACT/CTgov update > 120d
- `FAMILY_MISSING` — empty catalyst_family after all carry steps
- `SOURCE_UNRELIABLE` — source action is DEMOTE or SUPPRESS
- Each warning includes top 1-2 dominant drivers and plain-text explanation

**4. catalyst_family hygiene**:
- Explicit `NO_CATALYST` sentinel for names truly lacking a catalyst
- Empty string → backfill from event_type mapping
- Post-carry validation: assert no empty family in top-60
- Stable family mapping for carried-forward events

**5. Cycle review packet** — unified per-cycle artifact:
- Timing calibration by family/horizon (if sufficient resolved outcomes)
- Top timing warnings with structured reasons
- Event-type distribution in the live book
- Source reliability summary table
- Written to `artifacts/review_packets/review_packet_YYYY-MM-DD.json`
- Integrated into daily production pipeline

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| rankings.csv | data/snapshots/{date}/ | per-ticker catalyst fields |
| calibration_ledger.jsonl | artifacts/timing_hazard/ | prediction+outcome records |
| source_reliability.json | production_data/ | source × confidence × family |
| timing_hazard_{date}.json | artifacts/timing_hazard/ | per-catalyst timing overlay |
| event_type_score | decision_engine.py | per-ticker float |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| Enhanced timing_hazard_{date}.json | artifacts/timing_hazard/ | adds bucket fields + warning labels |
| calibration_by_slice.json | artifacts/timing_hazard/ | family × horizon × hardness calibration |
| review_packet_{date}.json | artifacts/review_packets/ | unified cycle review |
| review_packet_{date}.md | artifacts/review_packets/ | human-readable summary |

## Invariants

1. No portfolio override — all changes are diagnostic/dashboard
2. Existing calibration ledger entries are never modified (append-only)
3. Timing probabilities use same OOS-validated methods (rolling base rate + near-term rules)
4. No new columns in rankings.csv or DECISION_COLUMNS
5. catalyst_family backfill uses only the existing CATALYST_FAMILY_MAP

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| Empty calibration ledger | Slice views show "insufficient data" |
| Missing source_reliability.json | Source warnings skipped, not hard-fail |
| No resolved outcomes for a slice | Report N=0, skip calibration metrics |
| catalyst_family still empty after backfill | Flag as FAMILY_MISSING warning |

## Validation Plan

### Tests
- [x] `test_timing_bucket_classification` — all 9 cells (3 families × 3 horizons)
- [x] `test_warning_label_assignment` — each label fires on correct conditions
- [x] `test_catalyst_family_backfill` — empty→mapped, NO_CATALYST for truly empty
- [x] `test_calibration_by_slice` — correct grouping, handles sparse slices
- [x] `test_review_packet_structure` — all required sections present
- [x] `test_review_packet_idempotent` — same input → same output

### Integration
- [x] Full suite passes (51/51 tests pass)
- [x] Daily production pipeline runs with new packet step (wired in run_daily_production.py)
- [x] Dashboard renders enhanced timing data (timing_by_ticker enrichment in app.py)

## Expected Effect Size

Structural improvement to operator information quality. No direct IC or alpha impact.
Timing adaptation will compound over months as calibration ledger accumulates.

## Non-Goals

- No new alpha signals or selector/ranker changes
- No Herald labeling work (separate manual effort)
- No changes to timing probability methods (rolling base rate stays as-is)
- No confusion dashboard (future spec — needs more labels first)
- No event_type_score changes (already Checklist v2 PASS)

---

## Implementation Log

### 2026-04-05 — Phase 1-4 build
- Files to modify: tools/compute_timing_hazard.py, common/hard_catalyst_carry.py, event_ledger.py
- Files to create: tools/build_review_packet.py, tests/test_timing_buckets.py, tests/test_review_packet.py

### 2026-04-05 — COMPLETE
- All 5 items implemented and tested (51/51 tests pass)
- Timing buckets: classify_horizon_bucket, classify_hardness, classify_family_bucket
- Calibration-by-slice: compute_calibration_by_slice + build_calibration_dashboard
- Enhanced warnings: 6 structured labels (SHORT_DATED_REVISION_RISK, LOW_CONFIDENCE_DATE, STALE_EVENT_RECORD, FAMILY_MISSING, SOURCE_UNRELIABLE, PCD_DELAYED/STATUS_DOWNGRADE)
- catalyst_family hygiene: backfill + NO_CATALYST sentinel (475-line test suite)
- Review packet: build_review_packet.py wired into daily production pipeline
- Dashboard integration: per-position timing_confidence + on_time_prob enrichment
