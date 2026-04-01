# Change Spec: Options Diagnostics Robustness Layer

**Status**: DRAFT
**Author**: Claude / operator
**Date**: 2026-04-01
**Ruleset impact**: Phase 1 = NO; Phase 3 = optional candidate only

---

## Objective

Make the options diagnostics lane robust to sparse chains, stale quotes, and
missingness by introducing explicit data-state fields, chain-quality gating,
degraded-mode fallback tiers, and alert confidence metadata.

This is a diagnostics-hardening project, not a new ranking axis.

## Key Design

1. Stop treating blanks as neutral — make missingness explicit
2. Gate by chain quality before emitting features
3. Use fallback feature tiers (full/reduced/absent)
4. Downgrade low-confidence alerts
5. Keep options operator-facing until the lane is cleaner

## New Fields

- `options_data_state`: full | partial | absent | stale
- `options_missing_reason`: no_chain | low_oi | stale_quote | bad_spread | parser_fail
- `options_chain_quality_score`: float 0-1
- `options_last_refresh_utc`: ISO-8601
- `options_tier_mode`: full | reduced | absent
- `alert_confidence`: float 0-1 (on watch rows)
- `trigger_mode`: history_based | abs_fallback | low_liquidity_fallback

## Rollout

1. Quality manifest + explicit missingness fields
2. Watch artifact hardening (alert confidence, trigger mode)
3. Dashboard visibility (coverage breakdown)
4. Shadow DEM features (only after artifact stability)

See full spec in Claude Chat session 2026-04-01 for invariants, failure modes,
validation plan, and formulas.

---

## Implementation Log

### 2026-04-01 — Draft spec
- Grounded in existing options lane (price_action_watch.v1, cohort models, surface signals)
- Phase 1 = artifact-only, operator-facing

---

*Template version: 1.0.0*
