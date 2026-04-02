# Spec 045: Regime-Aware Stage-2 Pruner

**Status:** PHASE 1 LIVE (shadow)
**Author:** D. Schulz
**Date:** 2026-04-02
**Replaces:** Two-stage ranker architecture (was rank-weighting, now pruning)

## Goal

Promote the model from "DEM ranks 30 names" to "DEM selects 30 names, then a stage-2 pruner removes 10 names when the regime supports concentration."

Grounded in three findings:

1. DEM is a selector, not a within-top-30 ranker (top-30 IC ~0).
2. `inst_delta_z` pruning (Top-30 → EW Top-20) beats EW Top-30 by **+127pp net cumulative** over 76 months at 63d, IR 0.19 → 0.30.
3. Pruner is regime-dependent: adds lift in bull/neutral (+1.95 to +3.77pp), fails in bear (-0.56pp). Complementary to DEM's bear-market strength (IR 3.10).

## Non-goals

- Change DEM scoring
- Revive full Top-30 rank-weighting
- Use options surface-shape features for systematic reweighting
- Revive `total_volume_z` (failed PIT-native validation, IC = -0.10)

## Operating Thesis

**Base portfolio:** EW Top-30 (control and fallback).

**Stage-2 overlay:** In supportive regimes, prune Top-30 → Top-20.
- Initial signal: `inst_delta_z`
- First add-on: `aact_execution_score` (pending backfill + joint test)

## Regime Policy

| Regime | XBI 30d return | Recommendation | Evidence |
|--------|---------------|----------------|----------|
| Bear | < -2% | EW Top-30 | Pruner spread -0.56pp, IR -0.16 |
| Neutral | -2% to +2% | IDZ Top-20 | Pruner spread +1.95pp, IR 0.34 |
| Bull | > +2% | IDZ Top-20 | Pruner spread +3.77pp, IR 0.47 |

Risk override: CRITICAL risk level → EW Top-30 regardless of regime.

## Stage-2 Pruning Rule

### v1: IDZ-only (current)
1. DEM selects Top-30
2. Sort by `inst_delta_z` descending
3. Keep top 20
4. Equal-weight

### v2: Joint pruner (pending validation)
1. DEM selects Top-30
2. Compute: `pruner_score = 0.7 * z(inst_delta_z) + 0.3 * z(aact_execution_score)`
3. Keep top 20 by pruner_score
4. Equal-weight

Promotion: v2 only if it beats BOTH EW Top-30 AND v1 on all metrics.

## Daily Inputs

- `rankings.csv` with `inst_delta_z`, `aact_execution_score`
- Regime shadow / switching-policy recommendation
- Rebalance plan artifact
- Risk monitor artifact

## Daily Outputs

### Candidate books
- `ew_top30`
- `pruned_idz_top20`
- `pruned_joint_top20` (when available)

### Operational artifacts (all in production)
- `artifacts/regime_pruner/{date}_recommendation.json` — the daily call
- `artifacts/rebalance_plan/{date}_plan.json` — trade execution gate
- `artifacts/risk_monitor/{date}_risk.json` — risk/regime alerts
- `artifacts/post_promotion_monitor/{date}_monitor.json` — EW30 baseline tracking
- `artifacts/aact_deltas/aact_deltas_{date}.json` — trial execution signals
- `output/ranker_eval/` — backtest results

## Invariants

1. DEM remains unchanged (frozen selector)
2. Stage-2 acts only on the already selected Top-30
3. Stage-2 never rank-weights all 30
4. Bear regime → always EW Top-30
5. Missing `aact_execution_score` → fall back to IDZ-only
6. CRITICAL risk → block concentration even if regime allows it
7. Rebalance plan says SKIP → do not trade
8. Turnover < 5% → skip rebalance

## Validation Framework

### Portfolios
1. EW Top-30
2. EW Top-20 by `inst_delta_z`
3. EW Top-20 by `inst_delta_z + aact_execution_score`

### Required metrics
- 20d / 63d IC
- Cumulative spread (gross and net of costs)
- Hit rate
- Information ratio
- Top-vs-bottom spread
- Regime-sliced spread (bear / neutral / bull)

### Promotion rule
Joint pruner promotes only if it beats BOTH:
- EW Top-30
- IDZ-only Top-20

On ALL of: IC, spread, net of costs, top-vs-bottom spread.

## Rollout

### Phase 1: Live shadow ✅ DONE
- DEM Top-30 stays live baseline
- IDZ Top-20 runs in shadow
- Risk monitor, rebalance plan, regime recommendation — all in daily production
- 17 production steps, 25 agents, 30 cron jobs

### Phase 2: AACT backfill — IN PROGRESS
- 13/13 available AACT snapshots downloaded
- 11 delta pairs computed, 6+ dates injected into rankings
- Remaining: more daily downloads for denser coverage

### Phase 3: Joint-pruner evaluation — QUEUED
```bash
python3 scripts/research/pruner_backtest.py --include-aact
```
- Compare joint vs IDZ-only vs EW30
- Slice by regime
- Verify net-of-costs advantage

### Phase 4: Controlled promotion — GATED
- Promote only if joint pruner clears promotion rule
- Otherwise keep: EW Top-30 default, IDZ Top-20 as regime-gated overlay

## Key Evidence

### Pruner backtest (76 months)
| Strategy | 63d excess/mo | Cumulative | IR | Hit |
|----------|-------------|------------|-----|-----|
| EW Top-30 | +1.91pp | +138pp | 0.19 | 53% |
| **IDZ Top-20** | **+3.72pp** | **+268pp** | **0.30** | **58%** |
| Spread | +1.76pp net | +127pp net | | |

### Regime split (63d)
| Regime | N | Pruner spread | IR |
|--------|---|---------------|-----|
| Bear | 23 | -0.56pp | -0.16 |
| Neutral | 23 | +1.95pp | 0.34 |
| Bull | 26 | +3.77pp | 0.47 |

### Name attribution (74 periods, 20d)
- Hit rate: 51%
- Mean spread: +0.99pp/period
- Cumulative: +73.6pp

### Dead lanes
- `total_volume_z`: IC = -0.10 on PIT-native (109 obs). Look-ahead bias.
- Options surface ranker: IC negative at all horizons (50 months).
- Rank-weighting: inst_delta_z has real IC (+0.143, t=2.36) but RW doesn't monetize.

## Committee Narrative

> We stopped trying to fine-rank 30 names.
> We reframed the problem as selection-within-selection.
> A simple, explainable pruner already beats the baseline net of costs over 76 months.
> The pruner is regime-complementary: DEM carries bear, pruner adds lift in bull/neutral.
> We killed dead lanes quickly and are only testing one orthogonal add-on now.
