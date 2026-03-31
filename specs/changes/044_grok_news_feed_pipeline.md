# Change Spec: Grok News Feed Pipeline for DEM/CRT

**Status**: DRAFT
**Author**: Claude / operator
**Date**: 2026-03-31
**Ruleset impact**: Phase 1 = NO (operator/dashboard only); Phase 2 = shadow features

---

## Objective

Build a typed, point-in-time Grok event feed that normalizes biotech news into
machine-readable records joinable to DEM snapshots and CRT resolutions. Uses xAI
x_search + web_search with structured outputs on Grok 4 family models.

## Design Principles

1. Structured records, not raw text
2. event_outcome separate from price_direction (AQST rule)
3. Exogenous events tagged, not scored (BIIB rule)
4. Informational updates suppressed before resolution logic (CRT tuning rule)
5. PIT-safe: only events known at query time

## Schema: dem_grok_news_feed.v1

See full JSON schema in Claude Chat session 2026-03-31. Key fields per event:
- ticker, event_time_utc, source_type, primary_source_kind
- event_category (mna/clinical/regulatory/financing/leadership/safety/legal/competitor/sector/other)
- severity (critical/high/medium/low)
- new_or_stale (new/follow_on/stale)
- event_outcome_guess, price_direction_guess (separate fields)
- exogenous_to_primary_catalyst (bool)
- informational_only (bool)
- confidence, needs_review, review_reason_codes

## Phase 1 Features (operator/dashboard)

- news_material_event_count_7d
- news_critical_event_flag_7d
- news_exogenous_event_flag_30d
- news_safety_signal_flag_90d
- competitor_negative_readout_count_30d

## Implementation

Existing: tools/biotech_event_alerts.py (xAI client, structured outputs, SQLite dedup)
Needed: richer schema, normalization layer, feature builder, CRT join rules

## Join Rules

1. Only clean events for calibration (not informational, not exogenous, not needs_review)
2. event_outcome != price_direction (keep separate)
3. Exogenous events excluded from RR/CRT scoring
4. Informational updates suppressed from calibration

---

## Implementation Log

### 2026-03-31 — Spec drafted
- Architecture defined in Claude Chat session
- Existing biotech_event_alerts.py covers ingest layer
- Phase 1 = operator features only, Phase 2 = shadow DEM features

---

*Template version: 1.0.0*
