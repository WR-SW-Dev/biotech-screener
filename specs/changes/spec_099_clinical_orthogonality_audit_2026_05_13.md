# Spec 099 — Clinical Design Quality Orthogonality Audit

**Status**: SPEC ONLY (orthogonality validation, no scoring change)  
**Date**: 2026-05-13  
**Priority**: 7 (blocks clinical promotion decision)  
**Investment**: ~3–5 hours (correlation analysis + PCA + conditional IC)

---

## Problem Statement

Clinical design quality (`clinical_design_quality_z`) is a **promising shadow signal** from Spec 057 (conditional IC +0.103, t=3.53 within top coinvest). However, promotion eligibility depends on **orthogonality proof**:

1. Is clinical quality independent of coinvest_score_z (quality filter)?
2. Does clinical retain predictive power after controlling for coinvest?
3. Is clinical uncorrelated with other alpha candidates (catalyst timing, event EV)?

Spec 099 validates orthogonality vs. coinvest and other signals before any consideration for selector/ranker inclusion.

---

## Investment Logic

- Clinical IC is conditional: measured within coinvest-eligible set, not marginal
- Coinvest is a **quality gate**, not an alpha signal; clinical must prove independence
- Orthogonality is a hard gate for promotion: collinear signals are redundant
- Shadow monitoring validates clinical utility without promotion risk
- Output: clear orthogonality verdict (independent/dependent/ambiguous) for Spec 100+ decisions

---

## Exact Evidence Needed

### 1. Coinvest Correlation Analysis

Document:
- `corr(clinical_design_quality_z, coinvest_score_z)` across all post-PIT snapshots
- Confidence interval / rolling correlation stability
- Partial correlation after controlling for catalyst_days, event_ev_p_hit

**Threshold for independence**: |corr| < 0.40 (rule-of-thumb; correlation >0.60 indicates redundancy risk)

### 2. Principal Component Analysis (PCA)

Compute PCA on normalized feature matrix: [coinvest_score_z, clinical_design_quality_z, catalyst_days, event_ev_p_hit, financial_score_z]

Document:
- Variance explained by PC1 / PC2 / PC3
- Loading weights (which features drive each component?)
- If PC1 > 80% variance: strong dominance (likely coinvest); clinical is secondary
- If PC1 < 60% variance: features are well-separated (orthogonal landscape)

### 3. Conditional IC (Clinical within Coinvest)

Reproduce Spec 057 conditional IC:
- Compute clinical_design_quality_z IC within top-30 coinvest-eligible only
- Report: IC, t-stat, sample size (must be ≥30)
- Compare to unconditional IC (clinical IC on full 341-ticker universe, if available)
- If unconditional IC < conditional IC: **collinearity signal** (clinical only works within coinvest context)

### 4. Stratified IC Analysis

Partition postmortems by coinvest_score_z quartile:
- Q1 (lowest coinvest): clinical IC in Q1
- Q2, Q3, Q4: clinical IC in each quartile
- If IC is **only** positive in Q1/Q2: clinical is "coinvest complements" (redundant)
- If IC is **stable** across quartiles: clinical is independent

### 5. Predictive Orthogonality

Join clinical_design_quality_z to postmortem observations by (ticker, as_of_date):
- Compute correlation(clinical, forward_5d) **controlling for coinvest_score_z** (partial correlation)
- If partial_corr(clinical, forward_5d | coinvest) ≈ 0: clinical adds no marginal information
- If partial_corr > 0.15: clinical retains independent predictive signal

---

## Data Constraints

- **Post-cohort-window dates only**: use snapshots from 2026-05-15+ (after 13F refresh, cohort stabilized)
- **PIT-safe universe**: top-30 or eligible post-gates only
- Use existing postmortem observations; no new data collection
- No backfill of historical clinical scores; forward-only analysis

---

## Out-of-Scope

- ❌ Promote clinical to selector or ranker
- ❌ Retrain clinical model
- ❌ Change clinical scoring logic
- ❌ Combine clinical with other signals (composite ranker)
- ❌ Remove clinical from shadow monitoring

---

## Tests / Analysis Commands

```bash
# Correlation matrix: clinical vs. all alpha candidates
python3 << 'EOF'
import pandas as pd
import numpy as np
from scipy.stats import spearmanr, pearsonr

snap = pd.read_csv('data/snapshots/2026-05-13/rankings.csv')
pm = pd.read_csv('artifacts/postmortem/postmortem_observations.csv')

# Merge snapshot signals to postmortem
merged = pm.merge(
    snap[['ticker', 'coinvest_score_z', 'clinical_design_quality_z', 'catalyst_days', 'financial_score_z']],
    on='ticker',
    how='left'
)

# Correlation matrix
features = ['coinvest_score_z', 'clinical_design_quality_z', 'catalyst_days', 'financial_score_z']
corr_matrix = merged[features].corr(method='spearman')
print("Correlation Matrix (Spearman):")
print(corr_matrix)

# Partial correlation: clinical vs forward_5d, controlling for coinvest
from scipy.stats import linregress

# Residuals: clinical ~ coinvest
res_clinical = linregress(merged['coinvest_score_z'], merged['clinical_design_quality_z'])
clinical_resid = merged['clinical_design_quality_z'] - (res_clinical.slope * merged['coinvest_score_z'] + res_clinical.intercept)

# Residuals: forward_5d ~ coinvest
res_fwd = linregress(merged['coinvest_score_z'], merged['forward_5d'])
fwd_resid = merged['forward_5d'] - (res_fwd.slope * merged['coinvest_score_z'] + res_fwd.intercept)

# Partial correlation
partial_corr = np.corrcoef(clinical_resid.dropna(), fwd_resid[clinical_resid.notna()])[0, 1]
print(f"\nPartial Corr(clinical, forward_5d | coinvest): {partial_corr:.3f}")

# Conditional IC (clinical within top-30 coinvest)
top_30_coinvest = merged.nlargest(30, 'coinvest_score_z')
if not top_30_coinvest.empty and top_30_coinvest['clinical_design_quality_z'].notna().sum() > 0:
    conditional_ic, _ = spearmanr(top_30_coinvest['clinical_design_quality_z'], top_30_coinvest['forward_5d'])
    print(f"\nConditional IC (clinical within top-30 coinvest): {conditional_ic:.3f}")
EOF

# PCA analysis
python3 << 'EOF'
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

snap = pd.read_csv('data/snapshots/2026-05-13/rankings.csv')
pm = pd.read_csv('artifacts/postmortem/postmortem_observations.csv')

merged = pm.merge(
    snap[['ticker', 'coinvest_score_z', 'clinical_design_quality_z', 'catalyst_days', 'financial_score_z']],
    on='ticker',
    how='left'
)

# PCA
features = ['coinvest_score_z', 'clinical_design_quality_z', 'catalyst_days', 'financial_score_z']
X = merged[features].dropna()
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
pca = PCA()
pca.fit(X_scaled)

print("PCA Explained Variance Ratio:")
for i, var in enumerate(pca.explained_variance_ratio_[:3]):
    print(f"PC{i+1}: {var*100:.1f}%")

print("\nPCA Loadings (first 3 components):")
loadings = pd.DataFrame(
    pca.components_[:3].T,
    columns=['PC1', 'PC2', 'PC3'],
    index=features
)
print(loadings)
EOF

# Stratified IC by coinvest quartile
python3 << 'EOF'
import pandas as pd
from scipy.stats import spearmanr

snap = pd.read_csv('data/snapshots/2026-05-13/rankings.csv')
pm = pd.read_csv('artifacts/postmortem/postmortem_observations.csv')

merged = pm.merge(
    snap[['ticker', 'coinvest_score_z', 'clinical_design_quality_z']],
    on='ticker',
    how='left'
).dropna(subset=['coinvest_score_z', 'clinical_design_quality_z', 'forward_5d'])

# Quartiles
merged['coinvest_quartile'] = pd.qcut(merged['coinvest_score_z'], q=4, labels=['Q1', 'Q2', 'Q3', 'Q4'])

print("Clinical IC by Coinvest Quartile:")
for q in ['Q1', 'Q2', 'Q3', 'Q4']:
    subset = merged[merged['coinvest_quartile'] == q]
    if len(subset) > 5:
        ic, _ = spearmanr(subset['clinical_design_quality_z'], subset['forward_5d'])
        print(f"{q} (n={len(subset)}): IC={ic:.3f}")
EOF
```

---

## Pass/Fail Criteria

**PASS:**
- ✅ Correlation with coinvest documented (|corr| and CI)
- ✅ PCA computed; clinical not dominated by PC1 (variance >30% in PC2+)
- ✅ Partial correlation(clinical, forward_5d | coinvest) computed (magnitude documented)
- ✅ Conditional IC measured within top-30 coinvest (n ≥ 10)
- ✅ Stratified IC by coinvest quartile shown (at least 3 quartiles with n ≥ 5)
- ✅ Clear orthogonality verdict: independent / dependent / ambiguous

**FAIL:**
- ❌ Correlation with coinvest > 0.60 (redundancy risk)
- ❌ PC1 explains >80% variance (features not well-separated)
- ❌ Partial correlation ≈ 0 (no independent predictive signal)
- ❌ Clinical IC only positive in Q1 (coinvest-dependent)
- ❌ Insufficient samples (n < 5 in any quartile)

---

## Expected Outcomes

1. **Clinical is orthogonal** (|corr| < 0.40, PCA separation clear, partial_corr > 0.15): eligible for Spec 100+ evaluation pathway
2. **Clinical is collinear** (|corr| > 0.60, PC1 dominance, partial_corr ≈ 0): redundant with coinvest; defer promotion indefinitely
3. **Ambiguous** (mixed signals): document conditions and recommend additional analysis before decision

---

## Rollback / No-Op Statement

Audit documentation only. No production changes. If analysis reveals clinical is collinear with coinvest (|corr| > 0.60), conclude that coinvest gate is sufficient and clinical adds no independent utility. No-op outcome: clinical remains shadow diagnostic only; no promotion pathway.

---

## Related Specs

- **Depends on:** Specs 094–098 (ranker baseline, evaluation scope, gate/ranker separation, event-EV/catalyst monitoring)
- **Enables:** Spec 100+ (conditional clinical ranker design, if orthogonality passes)
- **Related to:** Spec 057 (clinical conditional IC baseline), Spec 072 (Screener vNext uses clinical as candidate ranker feature)

---

## Timeline

- **2026-05-15+**: Post-cohort-window snapshots available (13F refresh)
- **2026-05-20**: Orthogonality analysis complete
- **2026-05-22**: Verdict ready (independent/dependent/ambiguous)
- **2026-06+**: If orthogonality passes, proceed with Spec 100+ (conditional clinical ranker design)
