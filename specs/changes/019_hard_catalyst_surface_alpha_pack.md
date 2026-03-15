# Spec 19: Hard-Catalyst Surface Alpha Pack

**Status**: IMPLEMENTING
**Owner**: research / options lane
**Priority**: P1
**Depends on**: Spec 10, Spec 16, Spec 17, Massive chain analytics, historical IV surface/features

## Objective

Single hard-catalyst-only options backtest evaluating 6 surface signals against 4 targets using the standard research decision framework.

## Signals
1. cheap_vol_score
2. opt_rr_25d
3. opt_put_call_skew
4. actual_implied_move_pctile
5. rr_25d_change_5d
6. atm_iv_change_5d

## Targets
- signed_gap, abs_gap, fwd_ret_5d, fwd_ret_21d

## Controls
- catalyst_decay_w, composite_score

## Filters
- is_hard_catalyst == 1 (default)
- catalyst_days <= 180 (default), optional <= 90

## Decision Rule
- ALPHA_CANDIDATE: |IC| >= 0.05 vs signed_gap or fwd_ret_21d, survives both controls
- RISK_OVERLAY_CANDIDATE: |IC| >= 0.05 vs abs_gap, survives timing control
- SIGNAL_PRESENT_BUT_NOT_INCREMENTAL: raw IC exists but disappears after controls
- ABANDON: fails both raw and incremental thresholds
