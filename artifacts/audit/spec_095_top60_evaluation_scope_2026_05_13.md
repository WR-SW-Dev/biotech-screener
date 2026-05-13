# Spec 095 Audit — Top-60 Evaluation-Scope Correction

**Date**: 2026-05-13  
**Status**: INVESTIGATION COMPLETE  
**Classification**: **CURRENT_TOOLS_CONFLATED** (IC backtest measures wrong ranking; must clarify scope)

---

## Executive Summary

**Critical Finding**: The IC backtest tool (`run_rank_ic_backtest.py`) measures IC for `composite_rank`/`composite_score`, **NOT the production ranker's `final_score`**. This is a fundamental scope mismatch:

- **Production ranking**: Uses `actionable_rank` (derived from `final_score` post-gating)
- **IC backtest**: Uses `composite_rank` (independent field, only 23% top-30 overlap)
- **Correlation**: Only 0.25 between composite_rank and actionable_rank (weak)
- **Top-30 overlap**: 7/30 names match between composite-rank and actionable-rank

**Result**: Any IC claims based on composite_score are measuring the wrong signal. Ranker IC is **currently unmeasured and unknown**.

---

## Problem Statement

Current IC evaluation tools are **measuring composite_score IC**, which is neither:
1. The selector's IC (selector_score is 0.30 correlated with composite_score)
2. The ranker's IC (final_score is 0.13 correlated with composite_score)

This creates ambiguity about what IC claims actually measure, and blocks proper interpretation of ranker value.

---

## Investigation

### 1. Ranker Operational Universe

**Production Flow**:
- **Stage 1: Selector** produces `selector_score` (percentile [0,1] on full ~341-ticker universe)
- **Stage 2: Ranker** takes top selector candidates (coinvest-gated, ~60 eligible)
- **Stage 3: Final Ranking** produces `actionable_rank` (top-30 post-gates)

**Ranker operates on**: Eligible universe (~60 names after coinvest/liquidity/runway gates)

### 2. Current IC Measurement Tool

**Tool**: `run_rank_ic_backtest.py` (line 1053)
- Reads: `composite_rank` and `composite_score`
- NOT `final_score` or `actionable_rank`
- NOT `selector_score`
- Filters to "investable universe" (tickers with valid forward returns)
- Re-ranks within investable set
- Computes IC on that filtered universe

### 3. Ranking Correlation Analysis

From 2026-05-13 snapshot (298 tickers, 218 eligible):

| Ranking Method | Rank Range | Description | Correlation w/ composite_rank |
|---|---|---|---|
| **composite_rank** (IC backtest) | 1-298 | Shadow decision output score | 1.0 (self) |
| **actionable_rank** (PRODUCTION) | 1-218 (eligible only) | Final production ranking | 0.25 |
| **selector_rank_bucket** | categorical | Selector output | (categorical) |
| **ranker_v2_rank** | depends | Pairwise ranker output | (not tested) |
| **final_score** | continuous | Selector + ranker adjustment | corr(final_score, composite_score) = 0.13 |

### 4. Top-30 Membership Test

**Question**: Do the top-30 by composite_rank match top-30 by actionable_rank?

| Ranking Method | Top-30 Names | Overlap with Composite Top-30 |
|---|---|---|
| composite_rank (IC backtest universe) | 30 unique | 100% (self) |
| actionable_rank (PRODUCTION) | 30 unique | 7/30 (23%) |

**Interpretation**: The two ranking methods select **completely different portfolios** (only 23% overlap).

### 5. What is composite_score?

**Finding**: `composite_score` is a **decision-engine or overlay quality metric**, not a ranking coefficient:

- Correlation with selector_score: 0.30 (weak, independent signal)
- Correlation with final_score: 0.13 (very weak, independent signal)
- Value range: [0.0, 1.0] (appears to be quality/confidence metric)
- Not derived from: selector output directly, not from final_score

**Hypothesis**: composite_score may be from:
1. Decision engine confidence/quality metric (defensive overlays, quality control)
2. Alternative ranker or overlay output (not the production ranker)
3. Historical scoring artifact from prior model version

**Data needed**: Grep decision_engine.py or defensive_overlay_adapter.py to confirm source.

---

## Current Evaluation Scope Problem

### IC Backtest Universe Conflation

The IC backtest (`run_rank_ic_backtest.py`) is measuring:
1. `composite_rank` IC on "investable universe" (tickers with forward-return data)
2. NOT `final_score` (production ranker) IC
3. NOT `selector_score` (selector-only) IC
4. NOT `actionable_rank` (production top-30) IC

**Any claims** like "ranker IC = X" based on this tool are **wrong** because:
- The tool doesn't measure the ranker
- The tool measures a different ranking entirely
- The two rankings have 77% portfolio churn (top-30 overlap only 23%)

### Correct Evaluation Scopes (For Future)

| Entity | Should Measure | Current Tool Status |
|--------|---|---|
| **Selector-only IC** | selector_score IC on full ~341-ticker universe | NOT MEASURED |
| **Ranker-only IC** | final_score IC on eligible/top-60 universe | NOT MEASURED |
| **Ranker marginal IC** | (ranker-added names forward returns) - (selector-removed names forward returns) | NOT MEASURED (Spec 094 partially addressed) |
| **Composite score IC** | composite_score IC on investable universe | CURRENTLY MEASURED (misidentified as ranker IC) |

---

## Existing IC Output Status

**Question**: Are there any published IC claims based on composite_score?

**Answer**: Unknown, but likely yes if `run_rank_ic_backtest.py` has been run. Check:
- `output/rank_ic_backtest.json` (if exists)
- Any reports citing "ranker IC"
- Documentation/CLAUDE.md referencing IC values

**Action**: Any IC values >0 should be re-classified as **"composite_score IC"**, not "ranker IC".

---

## Recommendations

### Immediate (Spec 095)

1. **Clarify composite_score source**: Grep decision_engine.py, defensive_overlay_adapter.py, module_5_scoring_v3.py
2. **Deprecate composite_rank IC claims**: Mark any existing IC output as measuring "composite_score", not "ranker"
3. **Document correct scopes** in evaluation framework:
   - Selector-only IC = selector_score rank correlation on full universe
   - Ranker IC = final_score rank correlation on eligible universe
   - Ranker marginal = (ranker top-30 returns) - (selector-only top-30 returns)

### Future (Post-Spec 095)

4. **Build correct IC tools**:
   - Tool for selector-only IC (full universe)
   - Tool for ranker IC (eligible universe, top-60 scope)
   - Tool for ranker marginal value (Spec 094 approach)

5. **Do NOT re-run IC backtest** until `composite_rank` issue is resolved

6. **Prefer Spec 094 approach** (forward-return membership analysis) over IC backtest until correct scopes are defined

---

## Classification: CURRENT_TOOLS_CONFLATED

**Reasoning**:
- ✓ IC backtest tool **exists** and runs
- ✗ IC backtest tool measures **wrong ranking** (composite, not ranker)
- ✗ IC claims are **misattributed** (composite IC labeled as ranker IC)
- ✓ Correct scopes **can be defined** once composite_score source is clarified
- ⚠️ Ranker IC is **currently unmeasured and unknown**

---

## Files Inspected

| File | Purpose | Finding |
|------|---------|---------|
| `run_rank_ic_backtest.py:1053` | IC measurement | Uses composite_rank, not final_score |
| `data/snapshots/2026-05-13/rankings.csv` | Current ranking | composite_rank (0.25 corr w/ actionable_rank) |
| `ranker_engine.py:201` | Ranker definition | final_score = selector_score + ranker_adjustment |
| `selector_engine.py:206` | Selector definition | selector_score = percentile normalized |

---

## Next Steps

1. **Confirm composite_score source**: Search codebase for where composite_rank is computed
2. **If composite = quality metric**: Mark IC backtest as "quality-signal IC", not "ranker IC"; defer to future correct-scope IC measurement
3. **If composite = old ranker version**: Deprecate entirely; rebuild IC tools
4. **Spec 095 resolution**: Document approved scopes for all future IC/return tests (selector-only, ranker, marginal)

---

## Appendix: Scope Framework (Proposed)

For future evaluation tools, clarify which universe each test answers:

```
Full Universe (341 tickers)
  └─ Selector-only IC test
     ├─ Input: selector_score rank
     ├─ Universe: all 341
     ├─ Measure: Spearman(selector_rank, forward_return)
     
Eligible Universe (~60 tickers)
  └─ Ranker IC test (proposed)
     ├─ Input: final_score rank
     ├─ Universe: eligible only
     ├─ Measure: Spearman(final_rank, forward_return)
     
Top-30 Actionable
  └─ Ranker marginal test (Spec 094)
     ├─ Input: top-30 by selector vs top-30 by ranker
     ├─ Universe: actionable names
     ├─ Measure: (ranker-added forward_return) - (ranker-removed forward_return)
```

Test scopes must NOT conflate selector and ranker.
