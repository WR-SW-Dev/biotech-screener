# Design Spec — PoS Divergence Study for Options Research

**Status**: IN PROGRESS
**Commit**: `a13f04f6` (initial implementation)
**Schema**: `pos_divergence_study.v1`

## Objective

Add a **research-only** market-implied probability-of-success study to the existing options-alpha harness. Test whether the spread between model-implied quality and market-implied event magnitude contains predictive information beyond catalyst timing.

## What Already Exists (as of 2026-03-14)

### Built
- `common/pos_divergence.py` — core computation: `implied_event_move`, `iv_premium_ratio`, `z_score_array`, `compute_pos_divergence_panel`
- `scripts/research/eval_pos_divergence.py` — full research harness: IC, incremental IC, binned comparison, portfolio slices, decision rule
- `tests/test_pos_divergence.py` — 18 tests for core module

### Initial Results (384 obs, 5 snapshots, 109 tickers)
- `pos_divergence_z` vs `signed_gap`: IC = **-0.193** (survives catalyst timing control)
- `pos_divergence_z` vs `abs_gap`: IC = **-0.267**
- `implied_event_move` vs `abs_gap`: IC = **+0.193**
- Classification: **alpha_candidate** (negative sign — contrarian)
- Incremental IC = raw IC (catalyst timing explains zero variance)

### Gaps vs This Spec
1. **Subgroup splits** (REGULATORY vs CLINICAL, IV regime) — not yet implemented
2. **abs_pos_divergence** as separate signal — not yet in test battery
3. **Model PoS estimator** — currently uses raw `composite_score`; spec suggests a bounded [0,1] proxy
4. **Market-implied PoS** — currently uses `implied_event_move = atm_iv * sqrt(T)`; spec suggests a bounded [0.05, 0.95] heuristic
5. **Integration into eval_options_alpha.py** as v2 schema — currently a separate script
6. **63d horizon** — insufficient data (need more snapshots)

## Scope

### In scope
- Extend `eval_pos_divergence.py` with subgroup splits and abs_pos_divergence
- Accumulate more snapshot data for 63d horizon coverage
- Compare directly against existing `opt_term_slope` / `opt_atm_iv` results

### Out of scope
- No live decision-engine scoring changes
- No changes to `options_quality_composite`
- No changes to candidate `73113d54`
- No use of PoS divergence in production ranking
- No term-structure validator or IV-crush sizing logic

## Definitions

### Model PoS (v1)
Cross-sectional z-score of `composite_score` from rankings.csv. This is a deterministic, point-in-time-safe proxy for the model's quality assessment.

### Market-implied PoS (v1)
`implied_event_move = opt_atm_iv * sqrt(catalyst_days / 365)` — the market's expected absolute move magnitude. Cross-sectionally z-scored.

### PoS Divergence
- `pos_divergence = model_signal_z - implied_move_z`
- Positive: model more bullish than market
- Negative: market pricing larger move than model quality suggests

## Evaluation Plan

### Return targets
Same as `eval_options_alpha.py`: `abs_gap`, `signed_gap`, `fwd_ret_{5,21,63}d`

### Tests
1. Raw Spearman IC for `pos_divergence_z`, `pos_divergence`, `implied_event_move`
2. Tercile binned comparisons
3. Top-K portfolio slice spread
4. Incremental IC controlling for `catalyst_decay_w`
5. Double-sort within catalyst timing terciles
6. Subgroup splits: `catalyst_family`, `opt_iv_regime` (TODO)

### Decision Rule
Inherited from existing harness:
- **alpha_candidate**: signed IC >= 0.05, survives timing control
- **risk_overlay_candidate**: abs IC >= 0.05, survives timing control
- **signal_present_but_not_incremental**: raw IC present, doesn't survive
- **abandon**: below thresholds

## Key Finding: Negative Sign

The initial study found **negative** IC for `pos_divergence_z` vs both `signed_gap` and `abs_gap`. This means:
- When the model is more optimistic than the market, events tend to disappoint
- The market is better calibrated than the model on near-catalyst names
- This is potentially a **risk overlay** (dampen overconfident model picks) or **contrarian alpha** (fade model-vs-market disagreement)

This finding needs validation with more data before any promotion decision.

## Next Steps

1. Accumulate snapshots until 63d horizon has >= 20 observations
2. Add subgroup splits (REGULATORY vs CLINICAL, IV regime)
3. Add `abs_pos_divergence` as separate signal to test battery
4. Compare head-to-head with `opt_term_slope` results
5. Re-evaluate decision classification with fuller dataset
6. If alpha_candidate persists: design promotion ladder
7. If risk_overlay only: integrate as a dampening signal in research

## Validation Criteria

Success is one of:
1. `pos_divergence` classified as `alpha_candidate` — design promotion path
2. `abs_pos_divergence` classified as `risk_overlay_candidate` — integrate as risk dampener
3. Clean `abandon` classification — avoid premature live integration

## Filename
`specs/changes/004_pos_divergence_options_study.md`
