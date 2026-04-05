# Scoring Logic Audit — 2026-04-05

## Architecture Map

```
Eligible Row
  → SELECTOR (5 blocks, percentile-normalized [0,1])
    → institutional (65%): coinvest_score_z 65% + inst_delta_z 35%
    → catalyst (15%): catalyst_decay_w 30% + binary_quality 25% + cat_priority 20% + ...
    → survivability (10%): financial_score 35% + severity 35% + runway 30%
    → market_structure (10%): vol 30% + beta 25% + drawdown 25% + rsi 20%
    → clinical (0%): ZEROED — 8 signals computed, none used
  → selector_score [0,1] (percentile rank)
  → RANKER V2 (pairwise logistic, top-60 cohort)
    → 5 features z-scored within cohort
    → coinvest_score_z (46.4% variance), financial_score (47.5%), binary_quality (5.4%)
    → inst_delta_z (0.2%), catalyst_decay_w (0.5%) — DEAD FEATURES
  → final_score
  → actionable_rank (sort by -final_score)
  → target_weight_pct (size_band * cost_mult * catalyst_tilt, normalized 100%)
  → top-30 portfolio subset
```

## What Matters

### Selector (dominates portfolio decisions)
| Block | Weight | Top-30 swaps if removed | Verdict |
|-------|--------|------------------------|---------|
| **institutional** | 65% | **23** | CRITICAL — removing it changes 77% of the book |
| catalyst | 15% | 2 | Modest contribution |
| survivability | 10% | 3 | Modest contribution |
| market_structure | 10% | 2 | Modest contribution |
| clinical | 0% | 0 | **DEAD** — zeroed in production, 8 signals still computed |

**Within institutional block:**
- coinvest_score_z (65% × 65% = 42% of total): size-residualized, filing-age decayed. DOMINANT.
- inst_delta_z (35% × 65% = 23% of total): quarterly delta, coverage-guarded. CONTRIBUTING.
- coinvest_recency_state (0%): DEAD in production.

### Ranker (marginal improvement over selector)
| Feature | Variance share | Top-30 swaps if dropped | Verdict |
|---------|---------------|------------------------|---------|
| **coinvest_score_z** | 46.4% | 8 | Active |
| **financial_score** | 47.5% | 7 | Active — "penalize financially safe names" |
| binary_quality_score | 5.4% | 2 | Marginal |
| inst_delta_z | 0.2% | 0 | **DEAD** — zero swaps, zero variance |
| catalyst_decay_w | 0.5% | 0 | **DEAD** — zero swaps, zero variance |

**Ranker value-add**: +0.21pp/mo over selector-only (t≈1.3), changes 9/30 names (70% overlap).
The ranker is effectively a 2-feature model: coinvest + financial_score. The other 3 features do nothing.

### Weight Logic
| Component | Effect | Active? |
|-----------|--------|---------|
| size_band | 28/30 are L (large) | **Nearly no-op** — all top names are L |
| catalyst_tilt | 0.9x-1.2x range | Active but modest (1.2x for 18/30 names) |
| cost_mult | 0.7x-1.0x range | Active (5 names penalized at 0.7x) |
| binary_sleeve_caps | cap=100% | DISABLED |
| construction_name_cap | cap=100% | DISABLED |
| construction_liquidity_cap | cap=100% | DISABLED |
| construction_cost_gate | gate=0 bps | DISABLED |
| less_binary_construction | mode=include | DISABLED |

Despite "EW Top-30" construction, actual weight dispersion is 6.4x (0.12% to 0.77%) from catalyst_tilt * cost_mult * size_band stacking.

## What Does Not Matter

### Dead fields (computed but unused in production sort)
1. **composite_rank** — legacy module 5 output, never affects actionable_rank
2. **composite_score** — stored but unused
3. **clinical_score_z_tier** — computed, `enable_clinical_sort_signal=false`
4. **options_quality_composite** — only 7/60 filled, unused in selector_score sort
5. **alpha_cohort_adjustment** — 0/60 filled, entirely dead
6. **ranker_options_block, ranker_aact_block** — clinical_50 ranker blocks, 0/60 filled (shadow only)
7. **coinvest_recency_state** — 0% weight in production selector

### Dead ranker features
8. **inst_delta_z in ranker** — 0.2% variance, 0 top-30 swaps. It's useful in the SELECTOR (23% of score) but dead in the RANKER.
9. **catalyst_decay_w in ranker** — 0.5% variance, 0 top-30 swaps. Also useful in selector catalyst block but dead in ranker.

### Dead construction controls
10. **binary_sleeve_caps, name_cap, liquidity_cap, cost_gate, less_binary** — all at disabled defaults. Code runs but never triggers.

### Clinical block
11. **8 clinical signals** computed (clinical_optionality_pct_dev, program_count, program_diversification, endpoint_strength_score, design_quality_score, readout_density_90, single_asset_risk, execution_momentum) — all zeroed by clinical=0% block weight. Computation is wasted.

## Critical Findings

### 1. The ranker is a 2-feature model masquerading as a 5-feature model
After z-scoring, coinvest_score_z and financial_score account for **93.9%** of ranker variance. The other 3 features produce zero top-30 changes. The ranker's 5-feature complexity is unjustified.

### 2. financial_score plays a dual role that may be contradictory
In the **selector** (survivability block, 10%), higher financial_score is GOOD (improves survival).
In the **ranker** (weight -0.0371), higher financial_score is BAD (penalizes "safe" names).
This means financially strong names get a survivability bonus in the selector but then get penalized by the ranker — the two stages partially cancel.

### 3. coinvest_score_z appears THREE times
- Selector institutional block (42% of selector)
- Ranker feature (46.4% of ranker variance)
- Already size-residualized, filing-age decayed
Triple-counting the same signal adds complexity without diversification.

### 4. The "EW Top-30" construction is not actually equal-weight
28/30 names are size band L, but catalyst_tilt (0.9x-1.2x) and cost_mult (0.7x-1.0x) create 6.4x weight dispersion. If the intent is EW, these tilts should be disabled.

### 5. Clinical block computation is pure waste
8 signals are computed, z-scored, and aggregated for a block with 0% weight. This should be skipped.

### 6. 5 construction controls are dead code paths
All construction_risk_controls defaults are at 100%/0 — the early-exit condition always triggers. The code runs but never does anything.

## Simplification Opportunities

### Safe to remove (no decision impact)
1. **Skip clinical block computation** when weight=0 (save ~8 signal evaluations per ticker)
2. **Remove dead ranker features**: reduce to 2 features (coinvest_score_z + financial_score) or retrain
3. **Stop computing**: composite_rank, composite_score, clinical_score_z_tier, alpha_cohort_adjustment, options_quality_composite
4. **Remove coinvest_recency_state** from selector config (0% weight)

### Should consider (minor decision impact)
5. **Disable catalyst_tilt and size_band** if the intent is truly EW construction — or document that weights are intentionally non-equal
6. **Reduce ranker to 2 features** and retrain — eliminates 3 dead features, simplifies model, no decision loss
7. **Remove construction_risk_controls code path** or at least skip when all defaults are 100%

### Must not change
8. **Institutional block weights** (coinvest 65% + inst_delta 35%) — this is the empirically validated backbone
9. **Size residualization** of coinvest_score_z — corrects for mechanical market-cap correlation
10. **Filing-age decay** — prevents stale 13F data from dominating
11. **Percentile normalization** — ensures cross-sectional comparability
12. **Ranker top-60 cohort gate** — prevents noisy scores on low-data names

## Research vs Production Consistency

| Dimension | Status |
|-----------|--------|
| Selector config (A4) | ✓ Consistent — run_screen.py uses A4_SELECTOR_CONFIG |
| Ranker v2 model | ✓ Consistent — production_data/ranker_v2_model.json loaded |
| Z-scoring | ✓ Consistent — both training and scoring use cohort z-scoring |
| Sort anchor | ✓ Consistent — selector_score in production config |
| Research baseline | ⚠ Drifts — signal cards test against whatever was live at snapshot time |
| Snapshot fields | ⚠ Dead fields present in rankings.csv but unused in decisions |

## Verdict

### Should I trust the current scoring logic?
**Yes, conditionally.** The core signal (coinvest + inst_delta in the institutional block) is well-validated, size-residualized, and filing-age decayed. The selector percentile normalization is clean. The sort anchor correctly flattens tiers. The research evidence supports the current configuration.

### Is it overcomplicated?
**Yes.** The 5-feature ranker is effectively 2 features. The clinical block computes 8 signals for 0% weight. Five construction controls are dead. Multiple dead fields are computed and stored. The weight logic creates non-EW dispersion that may or may not be intentional.

### What single simplification would buy the most clarity?
**Reduce the ranker to 2 features (coinvest_score_z + financial_score) and retrain.** This removes 3 dead features, simplifies the model, and makes explicit what the ranker actually does: re-order the top-60 by re-weighting coinvest against financial health.

## Ranker Simplification Study Results (2026-04-05)

Walk-forward comparison (24-month rolling train, 45 test months, top-60 cohort):

| Config | Spread | Top excess | IC | IC t-stat |
|--------|--------|-----------|-----|-----------|
| 5-feature (production) | +1.66% | +0.83% | +0.128 | +2.66 |
| 3-feature (drop inst_delta, catalyst_decay) | +1.91% | +0.95% | +0.133 | +2.73 |
| **2-feature (coinvest + financial only)** | **+2.95%** | **+1.48%** | **+0.143** | **+2.98** |

The dead features weren't just useless — they added noise. The 2-feature ranker beats production on every metric. Top-30 overlap between 5-feature and 2-feature: 78%.

**Recommendation**: Retrain the production ranker with 2 features (coinvest_score_z + financial_score). This is a strict improvement, not a simplification trade-off.

### What must not be changed?
- Institutional block composition and weights
- coinvest_score_z size residualization
- Filing-age exponential decay
- Percentile-rank normalization
- sort_anchor = selector_score

## Plain English Answer

> **Which parts of the current scoring system are actually doing work?**
>
> Two things: **coinvest_score_z** and **financial_score**. Everything else is either a modest refinement (catalyst timing, market risk, inst_delta in the selector) or dead weight (clinical block, 3 ranker features, 5 construction controls, composite_rank, options_quality_composite).
>
> The institutional block IS the model. The ranker is a minor re-ordering that adds ~0.2pp/mo. The weight tilts create non-EW dispersion that contradicts the stated "EW Top-30" construction.
>
> The system is not broken — the core decision logic is sound. But about 40% of the scoring code does nothing in production.
