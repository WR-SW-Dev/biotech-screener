# Spec 051 — Pairwise Ranker v2 (Shadow Research)

**Status**: RESEARCH — shadow evaluation only, not production  
**Date**: 2026-04-03  
**Depends on**: Spec 050 (selector/ranker engine), Spec 049 (signal framework)  
**Replaces**: Nothing (additive research branch)

---

## Motivation

The current production ranker (Spec 050, `ranker_engine.py`) is a **bounded score-perturbation layer** that:

1. Only activates within catalyst-window names in top-60 by selector
2. Computes block scores from z-scored signals
3. Bounds the adjustment to ±15% of `selector_score`
4. Produces `final_score = selector_score + bounded_adjustment`

This architecture is **designed for stability and governance**, but has three structural limits on ranking discrimination:

- **Downstream of selector**: if selector score dominates, ranker can only nibble
- **Gated**: only fires in catalyst-window/top-bucket names (narrow sample)
- **Amplitude-capped**: cannot flip names even when ranking signal is strong

The question is whether a **pairwise ranking model** that directly learns relative preference within the selector-approved cohort can improve portfolio-level decisions.

## Goal

Build and evaluate a **pairwise Stage-2 ranker** that answers:

> "Given two names that already passed the selector and are in the same rebalance cohort, which one should outrank the other over the target holding horizon?"

## Non-goals

- Do NOT replace A4 selector
- Do NOT change production portfolio construction
- Do NOT re-open the research-vs-buy-list output contract
- Do NOT ship a monolithic end-to-end model across the whole universe

---

## Architecture

### Two-stage pipeline

```
Stage 1: Selector (A4) → eligible universe → top-K cohort
Stage 2: Pairwise Ranker v2 → final ordering within cohort
```

### Role separation

- **Selector** = "who deserves to be in the conversation"
- **Pairwise Ranker** = "who should outrank whom inside the conversation"

### Output contract

The pairwise model produces a **rank score** within the approved cohort.
Final portfolio order:

1. Selector defines the approved cohort (top-K by selector_score or actionable_rank)
2. Pairwise ranker orders names within that cohort
3. Portfolio takes top-30 by final order
4. Portfolio construction (EW) remains unchanged

All output is behind a config flag (`ranker_v2_mode`). Production is unaffected.

---

## Cohort Definitions

Three cohort variants evaluated:

| ID | Definition | Rationale |
|----|-----------|-----------|
| C1 | eligible + top-60 by actionable_rank | Broadest selector-approved set |
| C2 | eligible + top-60 by actionable_rank + catalyst_in_window | Matches current ranker activation |
| C3 | eligible + top-30 by actionable_rank + catalyst_in_window | Tightest, most relevant cohort |

---

## Feature Blocks

### Block 1: Institutional / Sponsorship Refinement
| Signal | Source | Direction |
|--------|--------|-----------|
| `coinvest_score_z` | 13F filings | Higher = better |
| `inst_delta_z` | Institutional flow | Higher = better |
| `coinvest_conviction` | Sponsor conviction | Higher = better |
| `coinvest_filing_age_days` | Filing recency | Lower = better |
| `sponsor_tier1_count` | Tier-1 sponsor count | Higher = better |
| `inst_delta_net` | Net institutional delta | Higher = better |

### Block 2: Clinical / Catalyst / Execution
| Signal | Source | Direction |
|--------|--------|-----------|
| `clinical_score_v2_z` | Clinical optionality | Higher = better |
| `clinical_quality_composite` | Quality composite | Higher = better |
| `endpoint_strength_score` | AACT endpoint quality | Higher = better |
| `design_quality_score` | Trial design quality | Higher = better |
| `binary_quality_score` | Binary event quality | Higher = better |
| `aact_execution_score` | AACT execution delta | Higher = better |
| `execution_momentum` | Execution trend | Higher = better |
| `catalyst_decay_w` | Catalyst proximity weight | Higher = better |
| `cat_priority` | Catalyst source priority | Lower = better |
| `catalyst_type_tier` | Event type tier (T1-T5) | Categorical |
| `catalyst_family` | REG/CLIN/SAFETY | Categorical |

### Block 3: Options / Event Pricing
| Signal | Source | Direction |
|--------|--------|-----------|
| `ovf_composite` | Options vol framework | Higher = better |
| `ovf11_score` | OVF v1.1 composite | Higher = better |
| `cheap_vol_score` | Cheap vol detection | Higher = better |
| `opt_rr_25d` | Risk reversal 25-delta | Higher = better |
| `opt_event_premium` | Event premium | Higher = better |
| `opt_term_slope` | Term structure slope | Higher = better |
| `opt_iv_regime` | IV regime label | Categorical |

### Block 4: Risk / Tradability / Stability (controls)
| Signal | Source | Direction |
|--------|--------|-----------|
| `financial_score` | Survivability | Higher = better |
| `severity` | Severity flag | Categorical (lower = better) |
| `runway_bucket` | Cash runway | Categorical |
| `competitive_intensity_z` | Crowding penalty | Lower = better |
| `de_vol_60d` | 60d volatility | Lower = better |
| `de_beta_xbi_60d` | XBI beta | Lower = better |
| `de_drawdown` | Drawdown | Higher = better |
| `size_band` | Market cap band | Categorical |

### Feature sets

- **Minimal core**: coinvest_score_z, inst_delta_z, clinical_score_v2_z, catalyst_decay_w, binary_quality_score, financial_score
- **Expanded**: all signals from blocks 1-4
- **Ablation**: drop each block in turn to measure marginal contribution

---

## Label Design

For each rebalance date, within the in-cohort names:

### Pair generation
- Create all pairs `(i, j)` where `i ≠ j` within the cohort
- Label = 1 if name `i` outperforms `j` over holding horizon, else 0
- For N names in cohort: up to N*(N-1)/2 pairs per date

### Pair sampling
- If cohort > 40 names: random-sample up to 600 pairs per date
- Maintain class balance (target ~50% positive pairs)
- Recency weighting: exponential decay with half-life = 24 months

### Holding horizons
- **Primary**: `fwd_ret_63d` (1-month-equivalent, quarterly rebalance proxy)
- **Secondary**: `fwd_ret_20d` (monthly)
- **Robustness**: `fwd_excess_xbi_63d` (XBI-relative)

---

## Model Variants

### A. Current bounded-additive ranker (baseline)
Production ranker from `ranker_engine.py`. Scores computed on same cohort for apples-to-apples.

### B. Pointwise direct score model
Logistic regression predicting `fwd_ret_63d > 0` (positive absolute return).
Uses z-scored features within cohort. Produces a probability score used as rank.

### C. Pairwise logistic (primary candidate)
Bradley-Terry / pairwise logistic regression:
- Input: feature difference vector `x_i - x_j` for pair `(i, j)`
- Output: P(name i outranks name j)
- Training: logistic loss on pair labels
- Scoring: for each name, aggregate pairwise win probabilities vs all others → rank score

### D. (Optional) Tree-based pairwise
If C shows promise, extend with gradient-boosted pairwise ranking (LambdaMART-style).

---

## Evaluation Plan

### Ranker quality metrics
- Pairwise accuracy (within cohort)
- Spearman rank IC (rank score vs forward return)
- Top-decile / top-bucket spread inside cohort
- Cutoff-zone swap quality (ranks ~20–50)

### Portfolio impact metrics
- True PIT backtest of top-30 portfolio (EW)
- Monthly excess return vs XBI
- Net-of-cost return (65 bps/yr extra cost for RW)
- t-statistic
- Hit rate (% months positive excess)
- Turnover (monthly name changes)
- Roster overlap with current production top-30
- Roster stability (average overlap month-to-month)

### Robustness splits
- By year
- By market-cap bucket (L/M/S/XS)
- By catalyst family (REGULATORY/CLINICAL/SAFETY)
- With and without options feature block
- With and without institutional refinement block
- By regime (bull/bear/neutral)

---

## Acceptance Criteria

Do NOT recommend promotion unless Ranker v2:

1. Beats current A4 + clinical_50 stack on true PIT portfolio results
2. Improves cutoff-zone ordering quality
3. Does not materially worsen turnover / stability
4. Remains interpretable enough to explain name reorderings
5. Passes leakage and provenance checks

---

## Guardrails

- No leakage from future data (all features from snapshot date, labels from forward returns)
- Point-in-time feature generation (uses snapshots_pit_v2)
- Feature provenance logged per model version
- Exact cohort definition logged
- Financial/severity plumbing unchanged
- Research ranking and executable weight outputs remain separate

---

## Deliverables

1. **This spec** — `spec_051_pairwise_ranker_v2.md`
2. **Engine** — `ranker_v2_pairwise.py` (pair generation, models, scoring)
3. **Evaluation harness** — `scripts/research/evaluate_ranker_v2.py`
4. **Unit tests** — `tests/test_ranker_v2_pairwise.py`
5. **Research memo** — `output/signals/ranker_v2_research_memo.md`
6. **Artifacts** — `output/signals/ranker_v2_results.json`, ablation tables, roster comparisons
