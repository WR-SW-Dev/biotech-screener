# Spec 061 — Event EV Promotion Ladder

**Status**: IMPLEMENTING
**Author**: Claude / arrenchulz
**Date**: 2026-04-08
**Ruleset impact**: YES (opt-in, all stages default OFF)
**Depends on**: Spec 057 (Event EV Engine), Spec 060 (Daily EV Scoring)

---

## Objective

Define a staged, reversible promotion path for Event EV into production
decisions. Each stage is independently gated by ruleset configuration and
requires forward evidence before activation. The ladder ensures Event EV
earns its way into the decision stack incrementally rather than as a
single all-or-nothing promotion.

## Policy Constraint

**North Star Rule applies.** Event EV artifacts are backtest/research outputs.
Each promotion stage requires:
1. A governance review (human sign-off)
2. Minimum forward shadow evidence (configurable day threshold)
3. Coverage/confidence thresholds met by the EV engine itself

No stage auto-promotes. Each stage is an opt-in flag in `DecisionRuleset`.

## Promotion Stages

### Stage 1 — Tie-Breaker (lowest risk)

**What:** When two names have identical sort keys within the production
top-K cohort, use `downside_adjusted_ev` to break the tie. Names with
higher EV sort first.

**Why:** Zero impact when names have distinct sort keys (the common case).
Only fires on genuine ties, making this the narrowest possible integration.

**Config:**
- `event_ev_stage`: `"off"` | `"tiebreaker"` | `"rank_overlay"` | `"sizing_overlay"` | `"composite"` (default `"off"`)

**Behavior:**
- Appends `(-event_ev_score,)` as a late tiebreak position in the sort key tuple
- Only affects names that already share the same prefix sort key
- Requires `event_ev_score` to be present on the row (injected by run_screen.py from daily artifacts)
- Falls back to 0.0 when EV data is missing (no coverage → no effect)

**Gate:** `event_ev_stage` is `"tiebreaker"` or higher.

### Stage 2 — Bounded Rank Overlay (moderate risk)

**What:** Apply a small, capped EV-based adjustment to the sort anchor for
names within the top-60 selector cohort. Follows the same pattern as
`_build_sort_contributions()` — a new `SortContribution` named
`"event_ev"` with a configurable weight and clamp.

**Why:** Lets EV nudge borderline names in/out of the top-30 without
dominating the selector. Bounded by a per-name cap (default ±0.15 on the
anchor scale) so it cannot leapfrog distant ranks.

**Config:**
- `event_ev_rank_overlay_weight`: float (default 0.0, range [0.0, 1.0])
- `event_ev_rank_overlay_cap`: float (default 0.15, range [0.0, 1.0])
- `event_ev_min_analog_confidence`: str (default `"ok"`) — gate on analog_confidence

**Behavior:**
- Computes `delta = weight * clamp(ev_z, -cap, +cap)` where ev_z is
  the cross-sectional z-score of `downside_adjusted_ev`
- Positive EV → negative delta → sorts earlier (better)
- Only fires for names with `analog_confidence >= min_analog_confidence`
- Emitted as `SortContribution("event_ev", ...)`

**Gate:** `event_ev_stage` is `"rank_overlay"` or higher.

### Stage 3 — Sizing Overlay (higher risk)

**What:** Apply a multiplicative sizing tilt based on Event EV, following
the same pattern as `catalyst_tilt_mult` and `mom_state_tilt_mult`.
High-EV names get a modest weight increase; negative-EV names get a
modest decrease.

**Config:**
- `event_ev_sizing_tilt_mults`: tuple (default `(("high_ev", 1.0), ("mid_ev", 1.0), ("low_ev", 1.0), ("no_ev", 1.0))`)
- `event_ev_sizing_high_threshold`: float (default 3.0) — ds_adj_ev % above which → high_ev
- `event_ev_sizing_low_threshold`: float (default -1.0) — ds_adj_ev % below which → low_ev

**Behavior:**
- Classifies each name into high_ev / mid_ev / low_ev / no_ev based on
  thresholds on `downside_adjusted_ev`
- Multiplies `target_weight_pct` by the corresponding mult
- Renormalizes to 100% after applying tilts

**Gate:** `event_ev_stage` is `"sizing_overlay"` or higher.

### Stage 4 — Full Composite (highest risk, placeholder)

**What:** Replace the current selector anchor with an EV-weighted composite.
This is the final destination, NOT implemented yet. Reserved as a config
value to signal intent.

**Config:**
- `event_ev_stage = "composite"` — recognized but raises `NotImplementedError`

**Gate:** Requires its own promotion spec (not this one). This spec only
defines the config value; implementation is deferred.

## Promotion Ladder Gate Evaluator

New module: `event_ev/promotion_ladder.py`

Provides:
- `EventEVPromotionStage` enum: OFF, TIEBREAKER, RANK_OVERLAY, SIZING_OVERLAY, COMPOSITE
- `evaluate_ev_readiness(artifacts_dir, min_days)` → `{stage: ready/not_ready, evidence}`
- `load_event_ev_for_cohort(as_of_date, tickers)` → `{ticker: ev_score}` lookup

The evaluator is informational — it tells the operator which stages have
enough evidence to justify activation. It does NOT auto-promote.

## Integration Points

### decision_engine.py
- New `DecisionRuleset` fields (all default to off/no-op)
- `SORT_CONTRIB_KEYS` extended with `"event_ev"`
- `_build_sort_contributions()` gains a Stage 2 contribution
- `compute_actionable_sort_key()` gains a Stage 1 tiebreak position
- `compute_target_weights()` gains a Stage 3 sizing tilt

### run_screen.py
- Injects `event_ev_score` into decision_fields (from daily artifacts)
- Same pattern as selector_score/final_score injection

### DECISION_COLUMNS
- New columns: `event_ev_score`, `event_ev_bucket`, `event_ev_analog_confidence`

## Test Plan

1. Stage 1: two names with identical sort keys, EV breaks tie correctly
2. Stage 1: missing EV data falls back to 0.0
3. Stage 2: EV contribution clamped within cap
4. Stage 2: analog_confidence gate blocks low-confidence names
5. Stage 3: sizing tilt applies and renormalizes
6. Stage 3: no_ev names use 1.0 multiplier
7. Stage 4: "composite" raises NotImplementedError
8. All stages off: zero behavioral change (determinism preserved)
9. Ruleset JSON round-trip with new fields

## Risks

- **Coverage:** Not all top-30 names will have Event EV (requires dated catalyst in 0-180d window). Missing EV → no effect (safe).
- **Analog confidence:** Early EV scores may have sparse analogs. The `min_analog_confidence` gate prevents low-quality EV from influencing ranks.
- **Timing model non-stationarity:** Timing hazard is research-only; EV that depends on timing should be treated with caution.
- **Small N:** Forward evidence is accumulating. Do not promote beyond Stage 1 until 30+ trading days of forward data exist.
