# Spec 033: Graveyard / Survivorship Dataset and Signal

**Status:** IN PROGRESS — Phase A (infrastructure)
**Date:** 2026-03-29
**Lane:** Spec-driven, production-affecting data + signal work
**Type:** New signal-source + validation infrastructure
**Priority:** Highest-ROI signal-source work after current baseline operation

## Objective

Build a deterministic, PIT-safe graveyard / survivorship dataset that captures
failed, abandoned, acquired, or de-prioritized biotech programs and companies.

## Phases

- **Phase A**: Infrastructure only — catalog builder, rollup, tests
- **Phase B**: Research evidence — ablation, IC, calibration impact
- **Phase C**: Bounded candidate — only after governance

## Key data sources

1. clinical_history_catalog (PIT-safe warehouse, 18,689 trials)
2. clinical_outcome_labels_v2 (labeled outcomes)
3. CTgov lifecycle states (TERMINATED, WITHDRAWN, completed-no-results)
4. SEC / company event sources (8-K, multi-form)
5. Manual curation layer (data/graveyard/)

## Schema: graveyard_catalog.v1

One record per company-program event:
- graveyard_id, ticker, company_name, program_key
- event_type, event_subtype, event_date, data_available_as_of
- pit_safe, source_type, source_ref, confidence
- phase_at_failure, status_before_event, failure_reason_class
- lead_asset, was_in_live_universe

## PIT rules

- data_available_as_of <= as_of_date (non-negotiable)
- CTgov status changes available on posted/updated date
- SEC events on filing date + repo PIT policy
- Manual curation requires explicit timestamp + source

## Confidence levels

- HIGH: explicit TERMINATED/WITHDRAWN, explicit discontinuation, delisting
- MEDIUM: completed-no-results + corroborating silence, indirect discontinuation
- LOW: ambiguous inactivity only (research-only, exclude from production)

## Files

- scripts/research/build_graveyard_catalog.py
- scripts/research/build_graveyard_rollup.py
- data/graveyard/graveyard_catalog.json
- data/graveyard/graveyard_company_rollup.json
- tests/test_build_graveyard_catalog.py
- tests/test_graveyard_pit.py
