# Spec 20: Surface-based Shadow Review Overlay for Hard-Catalyst Queue

**Status**: IMPLEMENTING
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
- surface_signal_quality: ok/partial/insufficient_history/missing_current_surface

## Queue priority boost (hard-only)
- surface_move_extreme=high: +2
- surface_move_extreme=med: +1
- atm_iv_change_5d >= 0.10: +2
- 0.05 <= atm_iv_change_5d < 0.10: +1

## Non-goals
- No decision engine changes
- No ranking weight
- No cheap_vol_score or skew promotion
