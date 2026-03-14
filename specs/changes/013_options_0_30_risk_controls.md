# Spec 13: 0-30d Options Risk Controls

**Status**: MODULE BUILT, AWAITING CONSTRUCTION WIRING

## What Exists

- `common/options_risk_controls.py` — `compute_0_30_risk_controls()` + `compute_rv_30d()`
- `tests/test_options_risk_controls.py` — 13 tests

## Three Controls

### Control 1: Crowding Penalty
- Fires when `options_volume_ratio > 2.0` AND `near_term_volume_share > 0.60` AND `catalyst_days <= 20`
- Cap multiplier: ×0.75
- **DORMANT** until crowding panel (`build_precatalyst_options_panel.py`) is populated with Massive data

### Control 2: Event Premium Complacency
- Fires when `IV/RV < 1.15` AND `catalyst_days <= 20` AND `catalyst_family = REGULATORY`
- Action: `review_required` (human check, not automatic cap)
- Uses `compute_rv_30d()` from price_history.csv

### Control 3: Gap Risk Sizing Cap
- Fires when `|pos_divergence| > 1.0` AND `catalyst_days <= 14` AND options fresh
- Cap multiplier: ×0.75

All controls suppressed when `options_data_freshness.all_fresh = False`.

## Review Queue Integration (pending)

```
complacency_flag = True → manual_review_required (options_complacency_near_pdufa)
crowding_flag = True → size_haircut (options_crowding_near_event)
```

## Next Steps

1. Wire into `_allocate_sub_bucket_quality()` in `tools/live_shadow_portfolio.py` for binary_0_30 bucket
2. Add review queue action rules for complacency and crowding flags
3. Compute rv_30d from price_history.csv in the construction path
