# Spec 20: Surface-based Shadow Review Overlay for Hard-Catalyst Queue

**Status**: IMPLEMENTED (2026-03-15)
**Depends on**: Spec 16, Spec 17, Spec 19, historical IV features

## Objective

Productionize actual_implied_move_pctile and atm_iv_change_5d as shadow
review fields in the daily hard-catalyst queue. No decision-engine weight.
No ranking impact.

## New fields
- actual_implied_move_pctile: percentile of current implied move vs trailing 252 rows
- surface_move_extreme: high/med/low from percentile thresholds (0.80/0.60)
- atm_iv_change_5d: current ATM IV minus 5-trading-day lag
- iv_ramp_flag: rising/flat/falling from 0.05 threshold
- post_event_drift_risk: high/med/low combined flag
- surface_signal_quality: ok/partial/insufficient_history/missing_current_surface
- surface_validation_basis: retro_hard_filter (until April PIT validation)

## Queue priority boost (hard-only)

**Boosted (walk-forward validated):**
- surface_move_extreme=high: +2
- surface_move_extreme=med: +1

**Informational-only (walk-forward unstable):**
- atm_iv_change_5d / iv_ramp_flag: no priority boost
- Reason: walk-forward showed mean IC=0.008, sign flips in Sep-25 and Feb-26
- Will reconsider after April PIT-native validation

## Walk-forward results (2026-03-15, retro hard filter)
- actual_implied_move_pctile: STABLE (mean IC=0.202, 6/6 months positive)
- atm_iv_change_5d: UNSTABLE (mean IC=0.008, 5/7 months positive)

## Non-goals
- No decision engine changes
- No ranking weight
- No cheap_vol_score or skew promotion
