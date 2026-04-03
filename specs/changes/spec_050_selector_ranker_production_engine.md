# Change Spec: Selector-Ranker Production Engine

**Status**: IN_PROGRESS
**Author**: system
**Date**: 2026-04-03
**Ruleset impact**: YES (new SelectorConfig + RankerConfig params, new sort anchor mode)

---

## Objective

Replace the current tier-based sort-key ordering with a two-stage selector-ranker
pipeline that uses validated signals (Spec 049) to produce a SelectorScore for
universe ranking and a bounded RankerAdjustment for catalyst-window names.
The PIT-corrected benchmark (Spec 048) collapsed historical alpha claims,
making an interpretable, forward-monitorable scoring architecture essential.

## PIT / Data Constraints

- [x] No lookahead — all inputs are already PIT-safe (Modules 1-5)
- [x] Cross-sectional z-scoring uses same-snapshot cohort only
- [x] Data sources: all existing SNAPSHOT_COLUMNS (no new data collection)
- [x] Historical availability: matches existing snapshot archive (76 months)
- [x] Known gaps: total_volume_z pending April 7 validation; options ~42% liquid chains

## Inputs

| Input | Source | Schema |
|-------|--------|--------|
| clinical_optionality_pct_dev | run_screen.py L4074 | float [0,1] |
| program_count | Module 4 | int >= 0 |
| program_diversification | Module 4 | float [0,1] |
| endpoint_strength_score | Module 4 | float [0,1] |
| single_asset_risk | Module 4 | str (yes/no) |
| readout_density_90 | Module 4 | float >= 0 |
| design_quality_score | Module 4 | float [0,1] |
| catalyst_days | DE overlay | int >= 0 |
| catalyst_bucket | DE overlay | str |
| catalyst_strength | DE overlay | str (NEAR/MID/FAR/MISSING) |
| catalyst_decay_w | DE overlay | float [0,1] |
| catalyst_family | run_screen.py | str (REGULATORY/CLINICAL/SAFETY) |
| cat_priority | run_screen.py | int 1-99 |
| binary_quality_score | run_screen.py | float [0,1] |
| severity | Module 3 | str (SEV1/SEV2/SEV3/NONE) |
| runway_bucket | DE overlay | str (critical/short/adequate) |
| financial_score | Module 3 | float |
| coinvest_score_z | run_screen.py | float (z-scored) |
| inst_delta_z | run_screen.py | float (z-scored) |
| coinvest_filing_age_days | DE overlay | int or blank |
| coinvest_recency_state | DE overlay | str (fresh/stale/blank) |
| de_beta_xbi_60d | DE input trace | float |
| de_vol_60d | DE input trace | float |
| de_drawdown | DE input trace | float |
| de_rsi_14d | DE input trace | float |
| actual_implied_move_pctile | Options | float [0,1] |
| opt_event_premium | Options | float |
| opt_term_slope | Options | float |
| opt_iv_regime | Options | str |
| ovf_composite | Options | float [0,1] |
| aact_execution_score | AACT | float |
| execution_momentum | Module 4 | float |

## Outputs

| Output | Destination | Schema |
|--------|-------------|--------|
| selector_score | rankings.csv | float [0,1] percentile |
| selector_rank_bucket | rankings.csv | str (top10/top30/top60/top120/below) |
| selector_clinical_block | rankings.csv | float |
| selector_catalyst_block | rankings.csv | float |
| selector_survivability_block | rankings.csv | float |
| selector_institutional_block | rankings.csv | float |
| selector_market_block | rankings.csv | float |
| ranker_active | rankings.csv | str (1/0) |
| ranker_adjustment | rankings.csv | float |
| final_score | rankings.csv | float |
| ranker_options_block | rankings.csv | float |
| ranker_inst_block | rankings.csv | float |
| ranker_aact_block | rankings.csv | float |

## Invariants

1. Deterministic: same input → same output across runs (Decimal arithmetic)
2. PIT-safe: z-scoring uses only same-snapshot cohort statistics
3. Backward-compatible: all 38 existing DECISION_COLUMNS preserved unchanged
4. Bounded ranker: |ranker_adjustment| <= max_adj * selector_score
5. Fail-closed: missing block inputs → penalized score, never crash
6. Selector percentiles sum to valid distribution across eligible cohort

## Failure Modes

| Scenario | Expected behavior |
|----------|-------------------|
| All signals missing for a block | Block score = 0.0, missingness penalty applied |
| Ranker gate not met | ranker_active=0, ranker_adjustment=0, final_score=selector_score |
| Zero eligible tickers | Empty result set, no z-scoring attempted |
| Single eligible ticker | Percentile = 0.5, no z-scoring (degenerate cohort) |
| Options data absent | Ranker gate fails, selector MarketStructure block penalized |

## Validation Plan

### Tests (write BEFORE implementation)
- [ ] `test_selector_deterministic` — same inputs → same outputs
- [ ] `test_selector_block_weights_sum` — weights sum to 1.0
- [ ] `test_selector_missing_signal_degradation` — graceful with missing data
- [ ] `test_selector_percentile_distribution` — scores in [0,1]
- [ ] `test_selector_golden_records` — known input/output pairs
- [ ] `test_ranker_gate_logic` — inactive when conditions not met
- [ ] `test_ranker_bounding` — adjustment within ±max_adj
- [ ] `test_ranker_deterministic` — same inputs → same outputs
- [ ] `test_ranker_golden_records` — known input/output pairs

### Evaluation
- [ ] Shadow comparison: selector_score anchor vs current anchor, top-30 overlap
- [ ] Use test_selector_bundles.py to evaluate block weight variants
- [ ] Forward monitor: track selector-ordered vs tier-ordered performance daily

### Integration
- [ ] Full test suite passes
- [ ] rankings.csv contains all new columns
- [ ] Dashboard renders without regression
- [ ] Backfill replay produces deterministic outputs

## Expected Effect Size

Structural improvement to scoring transparency and maintainability. Direct alpha
impact depends on block weight calibration via Spec 049 harness. The selector
subsumes the validated coinvest + inst_delta combo (B6 bundle: t=3.56, IR=0.43)
into a broader framework. Net-of-cost improvement is UNKNOWN until A/B shadow
evaluation completes.

## Non-Goals

- Replacing EW Top-30 construction (stays as baseline)
- Removing the existing tier system (preserved for backward compat)
- Tuning block weights (done separately via test_selector_bundles.py)
- Promoting selector_score as active anchor (shadow-first)
- Adding new data sources or signals

---

## Implementation Log

### 2026-04-03 — Initial implementation
- Files created: selector_engine.py, ranker_engine.py
- Files modified: decision_engine.py, run_screen.py
- Tests: test_selector_engine.py, test_ranker_engine.py
