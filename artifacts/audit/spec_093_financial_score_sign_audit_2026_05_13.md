# Spec 093 Audit — Financial Score Sign Direction

**Date**: 2026-05-13  
**Status**: INSPECTION COMPLETE  
**Classification**: **INTENTIONAL_STRESS_UPSIDE**

---

## Executive Summary

The production ranker's negative weight on `financial_score` (-0.0533) is **intentional stress-upside logic**, not a sign or label artifact. The model systematically **penalizes financially safe names** to favor those with higher catalytic/binary upside potential through financial distress leverage.

---

## Evidence Table

| Aspect | Finding | Source |
|--------|---------|--------|
| **Exact Coefficient** | -0.05332037006884376 (deployed -0.0533) | `production_data/ranker_v2_model.json:7` |
| **Feature Name** | `financial_score` | Artifact line 13 |
| **Model Type** | Pairwise logistic (Bradley-Terry) | Artifact line 4 |
| **Training Basis** | `minimal_v2` (2-feature), trained on 12,400 pairs | Artifact lines 20, 31 |
| **Deployment Context** | Family C live pilot; coinvest capped +0.02, financial_score unchanged | Artifact lines 34-40 |

---

## Raw Financial Score Components

### Construction (Module 2 v2)
Financial score is a **composite of three sub-scores**:

```
financial_score = 50% × runway_score
                + 30% × dilution_score
                + 20% × liquidity_score
```

**Source**: `module_2_financial_v2.py:1142-1146`

### Sub-score Directionality

| Component | Raw Input | Mapping | Direction | Meaning |
|-----------|-----------|---------|-----------|---------|
| **runway_score** | Cash runway in months | Piecewise-linear (0mo→5, 6mo→40, 12mo→70, 18mo→90, 24+mo→100) | Higher = Better | More months until cash burn = healthier |
| **dilution_score** | Cash-to-market-cap ratio | Sigmoid centered at 15%, clamped [0,100] | Higher = Better | More cash relative to market = less dilution risk |
| **liquidity_score** | Dollar ADV (60%) + market cap (40%) | Stepped buckets, rescaled [10,100] | Higher = Better | Higher volume + larger cap = better tradability |

**Source**: `module_2_financial_v2.py:630-860`

### Composite Direction
**All three sub-components have the same direction**: higher = stronger balance sheet / more survivable.

Therefore: **Higher composite financial_score = Better financial health** (more runway, less dilution risk, better liquidity).

---

## Normalization (Module 5 v3)

Financial score in the ranker's input vector is **rank-normalized within stage×size cohort**:

- **Method**: Winsorized percentile rank normalization
- **Cohort**: Stage × market-cap band (e.g., "Phase 2, $200M-$500M")
- **Direction Preservation**: Rank normalization sorts by value; higher raw scores → higher normalized scores
- **Output Scale**: [0, 100] percentile within cohort

**Source**: `module_5_scoring_v3.py:2173` (fin_norm = rank-normalized within cohort), `module_5_scoring_v3.py:1471-1490` (normalization function)

**Key Point**: Normalization preserves direction. A financially strong name in a weak cohort still gets a high normalized score; a weak name in a strong cohort gets a low score.

---

## Training Intent & Explicit Rationale

### Official Documentation

From `docs/MODEL_DOCUMENTATION.md`:

> "financial_score (deployed weight **−0.0533**, unchanged from trained): **penalizes financially safe names — those with less catalytic upside**. Negative weight is correct and informative. Persists across all cohort widths, both bull and bear regimes."

### Interpretation

1. **Intentional sign**: The negative weight is explicitly described as "correct and informative."
2. **Stress-upside logic**: Financially "safe" names (high financial_score) are less attractive because they have **lower binary upside**. Financially stressed names (low financial_score) have more upside due to leverage and binary outcomes.
3. **Persistence**: The negative weight survives across cohort widths and market regimes, indicating model fit, not data artifact.
4. **Training basis**: Model trained on 12,400 pairwise comparisons; negative weight emerged from Bradley-Terry pairwise preference learning.

### Supporting Evidence

From `CLAUDE.md`:
> "financial_score is a true negative penalty (NW-t=−3.41)"

The t-statistic of -3.41 indicates strong statistical significance of the negative relationship to forward returns within the pairwise ranking context.

---

## Falsification Criteria

### What Would Support SIGN_OR_LABEL_ARTIFACT:
- ❌ The weight flipped unexpectedly between training and deployment
- ❌ Documentation contradicts the sign (not observed — docs affirm intentionality)
- ❌ The weight becomes zero or flips positive in ablations (not tested yet)
- ❌ Evidence of a label inversion bug (e.g., financial_score = 100 when cash=0) in Module 2 → not observed; all mappings are monotonic

### What Supports INTENTIONAL_STRESS_UPSIDE:
- ✅ Official documentation explicitly states negative weight is "correct and informative"
- ✅ Negative weight persists across cohort widths and regimes (2026-04-05 deployment notes)
- ✅ Negative sign emerges from trained Bradley-Terry model (not manually constrained)
- ✅ Module 2 financial_score construction is transparent and directionally correct (higher = better)
- ✅ Rank normalization preserves direction
- ✅ Conceptually sound: biotech upside is often inversely related to balance sheet strength (leveraged optionality of distressed names)

---

## Classification

**INTENTIONAL_STRESS_UPSIDE**

The negative weight on financial_score is a deliberate modeling choice to favor financially stressed names within the coinvest-filtered cohort. The stress-upside thesis is:

1. **Financially strong** names (high runway, low dilution) = lower binary optionality
2. **Financially stressed** names (low runway, high dilution risk) = higher binary optionality due to leverage
3. Within a quality-filtered universe (coinvest ≥ positive sponsor involvement), the ranker trades survivability for catalytic upside

---

## Recommended Next Steps

1. **Spec 094 (Selector-Only Comparator)**: Now that financial_score directionality is confirmed intentional, proceed with baseline measurement of whether the ranker adds marginal value over selector-only ordering.

2. **No code changes**: The negative sign is correct. Do not treat as a bug.

3. **Interpretation guidance**: Any forward-return analysis involving financial_score must note that **lower financial_score (more stressed) is preferred by the ranker**, and interpret accordingly.

4. **Future refinement**: If future Checklist v2 work needs to audit ranker fit, the negative financial_score weight is one of the few ordinal ranker features with clear conceptual justification. Test whether stress-upside thesis holds prospectively.

---

## Files Inspected

| File | Lines | Purpose |
|------|-------|---------|
| `production_data/ranker_v2_model.json` | 1-43 | Live deployed artifact; coefficients, provenance |
| `module_2_financial_v2.py` | 1142-1206 | Financial_score construction; sub-component weights |
| `module_2_financial_v2.py` | 630-650 | Runway scoring (0-100 range) |
| `module_2_financial_v2.py` | 767-860 | Dilution scoring (0-100 range) |
| `module_2_financial_v2.py` | 933-990 | Liquidity scoring (0-100 range) |
| `module_5_scoring_v3.py` | 2173 | Rank normalization call |
| `module_5_scoring_v3.py` | 1471-1490 | Rank normalization implementation |
| `docs/MODEL_DOCUMENTATION.md` | (grep context) | Official deployed model documentation |
| `CLAUDE.md` | (grep context) | Internal model identity notes |
| `specs/changes/spec_051_pairwise_ranker_v2.md` | 1-150 | Original ranker research spec |

---

## Conclusion

Proceed to Spec 094 with confidence that financial_score directionality is sound and intentional.
