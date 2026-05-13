# Spec 093 — Financial Score Sign-Direction Audit

**Status**: SPEC ONLY (descriptive research, no implementation)  
**Date**: 2026-05-13  
**Priority**: 1 (blocking ranker evaluation)  
**Investment**: ~2–4 hours (document review + feature inspection)

---

## Problem Statement

The production ranker includes `financial_score` with a **negative weight** (-0.0533 Family C cap). It is unclear whether this negative coefficient is:

1. **Intentional**: Stress-upside logic (penalizing "safe" names within quality-filtered candidates to favor volatility/optionality)
2. **Artifact**: Sign/label error in feature construction, normalization, or training config

Resolving this is a correctness prerequisite before any ranker retrain or evaluation.

---

## Investment Logic

- Ambiguity blocks confidence in ranker interpretation and any future retraining
- Spec 093 is **pure documentation + inspection**, no production changes
- Output informs Spec 094 (selector-only comparator) and future ranker audit
- Must complete before any ranker weight adjustment

---

## Exact Evidence Needed

1. **Feature construction**  
   - Read `common/financial_score.py` or equivalent
   - Document raw financial metrics: believed to represent runway / dilution / liquidity (concrete confirmation required)
   - Normalization: confirm stage×size cohort normalization scope
   - Note: is the metric directional as-is, or inverted?

2. **Normalization / rank-norm**  
   - Confirm whether financial_score is rank-normalized (Module 5, per memory)
   - If rank-norm: what is the reference universe? (all 341 tickers, or subset?)
   - Does higher raw metric → higher norm_score, or is it inverted?

3. **Training config / original rationale**  
   - Locate the training spec that produced `ranker_v2_model.json`
   - Document the intended thesis: does negative weight mean "penalize high financial_score" or "favor low financial_score"?
   - Compare against production_data/ranker_v2_model.json artifact (source of truth)

4. **Label / sign convention**  
   - Confirm that the ranker model weight is -0.0533 (not a typo for +0.0533)
   - If negative: is this "stress upside" (favor volatile/risky) or "prefer quality" (favor stable)?
   - Falsification: what would prove it is a sign error?

---

## Data Constraints

- No live data needed (pure config/artifact inspection)
- No forward returns needed (correctness-only audit)
- Source: `common/financial_score.py`, `production_data/ranker_v2_model.json`, training logs/spec

---

## Out-of-Scope

- ❌ Retrain ranker
- ❌ Change weights
- ❌ A/B test financial_score hypothesis
- ❌ Evaluate ranker performance (done in Spec 094)

---

## Tests / Analysis Commands

```bash
# Inspect ranker model artifact
python3 -c "
import json
with open('production_data/ranker_v2_model.json') as f:
    model = json.load(f)
    print('Ranker features:', model.get('features'))
    print('Coefficients:', model.get('coefficients'))
"

# Grep financial_score construction
grep -r "financial_score" common/ tools/ --include="*.py" | head -20

# Check rank-norm module
grep -A 5 "Module 5\|financial_score" common/scoring_model.py
```

---

## Pass/Fail Criteria

**PASS:**
- ✅ Feature construction documented (raw metric + direction)
- ✅ Normalization method confirmed (rank-norm, universe, direction)
- ✅ Training config/thesis documented with explicit sign statement
- ✅ Artifact weight confirmed as -0.0533 (or corrected if typo found)
- ✅ Falsification criteria stated (e.g., "sign error if X is true; intentional if Y is true")

**FAIL:**
- ❌ Feature construction ambiguous or unavailable
- ❌ No training config/rationale found
- ❌ Weight discrepancy unresolved

---

## Rollback / No-Op Statement

This spec is **read-only documentation**. No production changes. Rollback: delete spec document if findings are deemed wrong; no code revert needed. No-op outcome: if sign is confirmed intentional, proceed to Spec 094; if artifact is found, flag for Spec 098 (ranker correctness fix).

---

## Next Steps

1. Write Spec 093 audit document (this spec)
2. Inspect code + config, document findings
3. Escalate sign direction to ops/ML lead for confirmation
4. Pass: proceed to Spec 094 (selector-only comparator)
5. Fail: create Spec 098 (sign correction) before any other ranker work
