# Spec 095 — Top-60 Evaluation-Scope Correction

**Status**: SPEC ONLY (evaluation correctness, no scoring change)  
**Date**: 2026-05-13  
**Priority**: 3 (blocks ranker IC interpretation)  
**Investment**: ~2–3 hours (documentation + tool audit)

---

## Problem Statement

Current ranker IC and forward-return tests may be computed **against the full 341-ticker universe**, conflating selector performance with ranker performance. If the ranker only operates on eligible/top-60 candidates (after gates), evaluating it against all 341 tickers mixes two signals and produces misleading IC.

Spec 095 defines the correct evaluation universe and corrects any IC measurement to ranker-only scope.

---

## Investment Logic

- IC and forward-return tests are only valid when measured in the universe where the signal operates
- Current confusion blocks interpretation of ranker improvements
- Correctness fix, not a retrain (no model change, only evaluation scope)
- Output: clean evaluation framework for future ranker audits

---

## Exact Evidence Needed

1. **Ranker operational universe**  
   - Confirm: does the ranker operate on all 341 tickers, or on eligible/top-60 only?
   - If top-60: what is the selection order (A4 selector → coinvest gate → top-60, or different)?

2. **Current IC measurement**  
   - Locate ranker IC / forward-return test code (likely in tools/ or notebooks/)
   - Document: is IC computed against full 341 tickers or subset?
   - Sample: what is the universe size when IC is computed?

3. **Correct evaluation scope**  
   - If ranker operates on top-60: IC should be computed on top-60 candidates only
   - If ranker operates on all 341: IC should be full-universe (current approach valid)
   - Define: eligible universe (before gates), gated universe (after coinvest), top-60 (post-ranker)

4. **Eligible universe definition**  
   - What are the hard gates? (false catalyst filter, liquidity minimum, runway minimum, dilution max, etc.)
   - How many names pass gates on average? (should be close to 60 if top-60 is post-gate)

5. **IC / forward-return measurement tool**  
   - Identify: which tool / script computes ranker IC?
   - Expected location: `tools/evaluate_ranker.py` or `common/ranking_eval.py` (guess)
   - Change scope: add parameter `universe="eligible"` or `universe="top60"`

---

## Data Constraints

- No new data required (pure scope definition)
- Use existing postmortem observations
- No model retrain or weight change

---

## Out-of-Scope

- ❌ Retrain ranker
- ❌ Change ranker weights or model
- ❌ Evaluate individual ranker features (Spec 099)
- ❌ Compare selector + ranker vs ranker-only (done in Spec 094)

---

## Tests / Analysis Commands

```bash
# Search for ranker evaluation code
find tools/ common/ -name "*ranker*" -o -name "*eval*" | grep -E "\.py$"
grep -r "ranker.*IC\|correlation\|forward_return" tools/ --include="*.py" | head -10

# Check postmortem universe
python3 << 'EOF'
import pandas as pd
pm = pd.read_csv('artifacts/postmortem/postmortem_observations.csv')
print(f"Postmortem rows: {len(pm)}")
print(f"Unique tickers: {pm['ticker'].nunique()}")
print(f"Unique dates: {pm['as_of_date'].nunique()}")
print(f"Forward_5d non-null: {pm['forward_5d'].notna().sum()}")
# Group by date to estimate top-60 size
by_date = pm.groupby('as_of_date').size()
print(f"Avg records per date: {by_date.mean():.0f} (expected ~30 if top-30 ranks)")
EOF

# Check eligibility filters
grep -A 10 "eligible\|gate\|filter" common/selection_logic.py
```

---

## Pass/Fail Criteria

**PASS:**
- ✅ Ranker operational universe clearly documented (all 341 or subset?)
- ✅ Current IC measurement scope identified (universe size at test time)
- ✅ Correct evaluation scope defined (eligible / gated / top-60)
- ✅ Hard gates listed (catalyst, liquidity, runway, dilution, etc.)
- ✅ Average gate-pass rate documented
- ✅ Evaluation tool updated (if needed) with universe parameter

**FAIL:**
- ❌ Ranker universe scope ambiguous
- ❌ Current IC test scope cannot be determined
- ❌ No evaluation tool found

---

## Expected Outcome

1. **Ranker operates on all 341**: Current full-universe IC is correct; no change needed
2. **Ranker operates on top-60**: Current IC is conflated; fix evaluation tool to measure IC within top-60 only
3. **Ambiguous**: Document as correctness debt; flag for Spec 098 (ranker audit)

---

## Rollback / No-Op Statement

Documentation + tool scope fix only. No production scoring change. If fix reveals current IC was inflated, it does not invalidate the ranker — it just means previous IC claims were universe-confounded. Proceed with Spec 094 (selector-only comparator) using corrected scope.

---

## Related Specs

- **Depends on:** Spec 094 (selector-only comparator; both use same evaluation scope)
- **Informs:** Specs 096–099 (all ranker improvement work uses corrected scope)
