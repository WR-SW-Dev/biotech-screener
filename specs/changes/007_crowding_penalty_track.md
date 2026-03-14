# Spec 7: Crowding Penalty Track

**Status**: HARNESS BUILT, AWAITING DATA
**Schema**: `crowding_penalty_study.v1`

## What Exists

- `scripts/research/build_precatalyst_options_panel.py` (500 lines) — event extraction + Massive options feature builder
- `scripts/research/crowding_orthogonality_analysis.py` (704 lines) — full IC analysis with partial IC, temporal stability, subgroup splits (uses scipy/numpy)
- `scripts/research/eval_crowding_penalty.py` (NEW) — decision-rule wrapper with crowding_z composite, same alpha/overlay/abandon framework
- `tests/test_crowding_penalty.py` — 11 tests for decision logic and crowding_z computation
- `data/research/precatalyst_options_panel.csv` — 816 events (6 dates, 160 tickers) but **options features empty** (Massive API not yet warmed)

## Blocking Issue

The panel has catalyst events extracted from archives but no options volume/breadth/concentration data. The `build_precatalyst_options_panel.py` fetches this from Massive day aggregates (S3 flat files), which requires:
- `MASSIVE_S3_ACCESS_KEY_ID` + `MASSIVE_S3_SECRET_ACCESS_KEY` environment variables
- Running: `python scripts/research/build_precatalyst_options_panel.py --warm-options`

## Crowding Metrics

```
crowding_z = z(pre_event_volume_mean) + z(pre_event_volume_surge)
```

Individual features tested: `pre_event_volume_mean`, `chain_breadth`, `pre_event_put_call_ratio`, `pre_event_transactions_mean`, `pre_event_volume_surge`, `pre_event_volume_trend`, `pre_event_contract_count_mean`

## Decision Rule

- **negative_alpha_candidate**: crowding_z has negative signed IC >= 0.05 that survives composite_score control
- **risk_overlay_candidate**: |crowding_z| IC >= 0.05, survives control
- **signal_present_but_not_incremental**: raw IC present but wiped by quality control
- **abandon**: below thresholds

## Next Steps

1. Warm Massive options cache for panel dates
2. Re-run `build_precatalyst_options_panel.py` to populate features
3. Run `eval_crowding_penalty.py` with populated panel
4. Compare results with existing `crowding_orthogonality_analysis.py` output
