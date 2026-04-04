# Spec 054 — Trial Execution / Timeline-Delta Signal Study

**Status**: COMPLETE — aact_execution_score SHADOW (incremental, year-unstable); static signals CLOSED
**Date**: 2026-04-04
**Predecessor**: Specs 049 (signal framework), 050 (selector-ranker), 051 (ranker v2), 053 (options — CLOSED)

## Motivation

The ranker ablation (Spec 051) shows the current edge is **institutional first, risk second**;
clinical-score-as-scored is **destructive** (−0.35pp ablation), and the full options study
(Spec 053) closed the options-as-alpha lane — none of 37 options signals beat B6.
Form 4 insider signals also failed to beat the incumbent selector.

The signal family that is **least explored and most orthogonal** to the institutional+risk
stack is **trial execution / timeline-change delta** from AACT/CT.gov data. This is
biotech-native, pre-event, and measures something fundamentally different from ownership
(coinvest), positioning (options), or insider activity.

## Hypothesis

Companies that demonstrate **on-time or accelerated trial execution** — as measured by
timeline adherence, update cadence, pipeline velocity, and enrollment momentum — have
better future stock returns than companies showing delays, silence, or pipeline contraction.

## Research Questions

1. Does trial execution quality predict future biotech returns?
2. Which execution dimensions carry signal: timeline adherence, update cadence, pipeline
   velocity, enrollment momentum, or results-posting discipline?
3. Best use: standalone selector, within-cohort ranker, or modifier/tiebreaker?
4. Is execution signal incremental to incumbent B6 (coinvest + inst_delta)?
5. Does signal strength depend on: phase, catalyst proximity, market cap, regime?

## Signal Design

### Track 1 — Static Execution Features (testable on full 71-month history)

These are computable from trial_records.json as-of any historical snapshot date.
No paired AACT snapshots needed.

| Signal | Definition | Direction |
|--------|-----------|-----------|
| `exec_pcd_overdue_ratio` | Fraction of active trials past estimated PCD | Lower = better |
| `exec_pcd_overdue_months_avg` | Mean months overdue across active overdue trials | Lower = better |
| `exec_update_recency_days` | Mean days since last_update_posted across active trials | Lower = better |
| `exec_update_silence_flag` | Any active trial >180d without update | 0 = better |
| `exec_pipeline_velocity` | (active + completed) / (active + completed + terminated + withdrawn) | Higher = better |
| `exec_termination_rate` | terminated / total started | Lower = better |
| `exec_late_stage_density` | fraction of active pipeline in Phase 2+ | Higher = better |
| `exec_results_posting_rate` | completed-with-results / completed | Higher = better |
| `exec_enrollment_scale_z` | Mean enrollment across active trials, z-scored per snapshot | Higher = better |
| `exec_active_trial_count` | Count of active/recruiting trials | Ambiguous (more ≠ better) |
| `exec_pipeline_breadth` | Number of unique indications under active development | Higher = better |
| `exec_phase_advancement_score` | Weighted sum: Ph3=3, Ph2=2, Ph1=1 across active trials | Higher = better |

### Track 2 — Delta Execution Features (2026 data only, accumulating forward)

Require paired AACT snapshots (currently 18 daily pairs, ~2-3 monthly overlaps).
Shadow accumulation — NOT testable as backtest yet.

| Signal | Definition | Direction |
|--------|-----------|-----------|
| `exec_delta_pcd_shift_days` | Net PCD shift across all trials (from build_aact_trial_deltas) | Negative = better |
| `exec_delta_n_accelerated` | Count of trials with PCD pulled forward | Higher = better |
| `exec_delta_n_delayed` | Count of trials with PCD pushed back | Lower = better |
| `exec_delta_enrollment_growth` | Net enrollment change | Higher = better |
| `exec_delta_status_upgrades` | Status transitions to active/completed | Higher = better |
| `exec_delta_status_downgrades` | Status transitions to terminated/withdrawn | Lower = better |
| `exec_delta_score` | Existing composite (execution_score from build_aact_trial_deltas) | Higher = better |

## PIT Safety Rules

1. Trial status, PCD, enrollment use `last_update_posted_date` as PIT boundary
2. Only trials with `last_update_posted_date < snapshot_date` are admissible
3. `primary_completion_date` with type=ESTIMATED is a forward projection — PIT-safe
   to use as "expected completion" because the estimate itself was posted before snapshot
4. Results-posting uses `results_first_posted_date` < snapshot_date
5. Forward returns from research panel (already PIT-safe)
6. No use of actual trial outcomes or resolution dates in pre-event signals

## Evaluation Plan

### Track A — Univariate Signal Cards (all 12 static signals)

For each signal:
- Coverage: % of eligible panel rows with non-null value
- Gate: above-median vs below-median excess return spread
- Selector: top-30 by signal vs top-30 by baseline rank → Δpp, t-stat
- Ranker: Spearman IC within top-30, RW vs EW
- Horizons: 20d, 63d

Acceptance bar: IC t-stat ≥ 1.6, coverage ≥ 40%, positive in ≥ 2/3 regimes.

### Track B — Selector & Ranker Bundle Tests

Selector bundles: B6 incumbent + execution signals at 10-25% weight
Ranker bundles: execution features within top-30

Compare to B6 (coinvest 65% + inst_delta 35%) on Δpp, t-stat, IR.

### Track C — Diagnostic Use Cases

- Near-catalyst tiebreaker: does execution quality improve selection within catalyst_days ≤ 30?
- Phase-gated utility: is execution signal stronger for Phase 2+ vs Phase 1?
- Single-asset risk interaction: does execution quality mitigate single-asset concentration risk?

### Track D — Robustness

- Year-by-year stability
- Regime slices (bear/neutral/bull)
- Market cap slices
- Catalyst proximity slices
- Correlation with incumbent signals (coinvest, inst_delta)

### Track E — Incrementality

- Partial IC: execution signal conditioned on coinvest+inst presence
- Fama-MacBeth-style: execution signal alpha after controlling for institutional

## Data Constraints

- **Static signals (Track 1)**: testable on all 71 monthly snapshots (2020-06 to 2026-04)
- **Delta signals (Track 2)**: only 18 AACT snapshot pairs (2026 only), ~2-3 monthly
  research panel overlaps. Shadow accumulation only; NOT credible for backtest.
- **Trial linkage**: 18,703 trials, ticker-mapped. ~3.8% of total AACT trials.
- **Coverage estimate**: ~70-80% of eligible panel rows should have static execution features

## Deliverables

1. `scripts/research/execution_delta_study.py` — full study script
2. `output/execution_delta_study/master_results.json` — structured results
3. `output/execution_delta_study/signal_ranking_table.md` — univariate ranking
4. `output/execution_delta_study/selector_bundle_comparison.md` — bundle comparison
5. `output/execution_delta_study/final_recommendation.md` — verdict memo
6. This spec updated with final status

## Decision Gate

- If any static execution signal has IC t-stat ≥ 1.6 AND is incremental to B6: → PROMOTE_CANDIDATE
- If signals help as ranker/tiebreaker but not selector: → SHADOW for overlay
- If nothing works: → CLOSE lane, document as exhausted (same as Spec 053)
