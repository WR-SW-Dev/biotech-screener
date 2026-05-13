# Spec 094 — Selector-Only Comparator

**Status**: SPEC ONLY (descriptive analysis, no implementation)  
**Date**: 2026-05-13  
**Priority**: 2 (foundational ranker value proof)  
**Investment**: ~4–6 hours (postmortem analysis, forward returns join)

---

## Problem Statement

Current production ranker operates on top 30 after A4 selector + coinvest gate. The question is: **does the ranker add marginal value over selector-only ordering?**

If selector-only (or selector + coinvest-binary) outperforms or matches the ranker on forward returns, drawdown, and churn, the ranker does not justify its complexity and no feature additions should proceed.

Spec 094 quantifies the baseline value before any ranker improvement work.

---

## Investment Logic

- Ranker complexity should earn its keep; this spec measures that
- Descriptive-only; no promotion or production change
- Prerequisite for Specs 095–099 (ranker improvement specs)
- Output: either validates current ranker or recommends simplification

---

## Exact Evidence Needed

1. **Rank comparison universe**  
   - Post-PIT snapshots only (2026-04-19 onwards, after PIT v2 audit closed)
   - Select 30–40 recent snapshots (e.g., 2026-05-13 back to ~2026-04-20)

2. **Selector-only ranking**  
   - Take final A4 selector scores (coinvest_score_z, financial_score_z)
   - Rank by coinvest_score_z only (no 2-feat pairwise ranker)
   - Alternative: rank by coinvest-binary gate + equal weight (tie-break by financial)

3. **Current ranker ranking**  
   - Take current final_score rank (A4 selector output through 2-feat ranker)
   - Ensure ruleset is `8887576e` (v1.14.0 active as of 2026-05-13)

4. **Comparison metrics**  
   - **Jaccard overlap** (top-30 intersection between selector-only and ranker, %)
   - **Rank churn** (average rank shift for names in both lists)
   - **Forward returns by rank cohort** (T+1, T+5, T+20 median returns for top-30 ranker vs top-30 selector-only)
   - **Drawdown** (post-recommendation max intraday draw)
   - **Hit rate** (% of top-30 recommendations with forward_5d ≥ 0)

5. **Postmortem joins**  
   - Use existing postmortem data (`artifacts/postmortem/`)
   - Join final_score rank and selector-only rank to each postmortem by (ticker, recommendation_date)
   - Compute forward returns and drawdown from market data cache

---

## Data Constraints

- **PIT-safe only**: use production_data price history and PIT snapshot financials
- **Forward labels**: use existing postmortem forward_5d, forward_20d columns
- **No yfinance**: use cached historical price data only
- **No backfill**: prospective analysis of 30–40 recent snapshots

---

## Out-of-Scope

- ❌ Retrain selector or ranker
- ❌ Change weights
- ❌ Evaluate individual ranker features (done in Spec 099 if needed)
- ❌ Full historical backtest (only post-PIT v2)

---

## Tests / Analysis Commands

```bash
# Extract recent snapshots (post-PIT)
ls data/snapshots/2026-05-* data/snapshots/2026-04-2* | sort | tail -30

# Load postmortem data
python3 << 'EOF'
import pandas as pd
pm = pd.read_csv('artifacts/postmortem/postmortem_observations.csv', parse_dates=['as_of_date'])
pm_recent = pm[pm['as_of_date'] >= '2026-04-20']
print(f"Recent postmortems: {len(pm_recent)}")
print(f"Columns: {list(pm.columns)}")
print(f"Forward_5d non-null: {pm_recent['forward_5d'].notna().sum()}")
EOF

# Compute Jaccard overlap
python3 << 'EOF'
import json
from pathlib import Path

# Example: load final ranks from two snapshots
# Compare top-30 ticker sets; compute Jaccard = intersection / union
snapshots = sorted(Path('data/snapshots').glob('2026-05-*'))[-10:]
for snap in snapshots:
    rankings = snap / 'rankings.csv'
    if rankings.exists():
        print(f"{snap.name}: {rankings.exists()}")
EOF
```

---

## Pass/Fail Criteria

**PASS:**
- ✅ Jaccard overlap computed for ≥20 snapshots (selector-only vs ranker top-30)
- ✅ Median forward_5d hit rates computed for both ranking methods
- ✅ Drawdown comparison done (post-recommendation max draw)
- ✅ Rank churn measured (average position shift)
- ✅ Clear statement: ranker outperforms selector-only (hit rate, returns, drawdown) or parity/underperform

**FAIL:**
- ❌ Insufficient postmortem data (<15 snapshots with forward labels)
- ❌ Ranker performance cannot be isolated from selector
- ❌ No forward returns available for comparison

---

## Expected Outcomes

1. **Ranker adds value**: Hit rate / median returns higher than selector-only → proceed with ranker improvement work (Specs 095–099)
2. **Parity**: No significant difference → recommend simplification to selector-only or coinvest-binary ordering
3. **Ranker underperforms**: Selector-only beats ranker → urgent review (Spec 098 correctness audit)

---

## Rollback / No-Op Statement

Descriptive analysis only. No production changes. Output informs prioritization of future ranker work. If analysis shows selector-only suffices, no code change needed; just document conclusion and close ranker improvement specs.

---

## Related Specs

- **Depends on:** Spec 093 (financial_score sign must be resolved first)
- **Unblocks:** Specs 095 (top-60 scope), 096 (gate/ranker separation), 099 (catalyst monitor)
