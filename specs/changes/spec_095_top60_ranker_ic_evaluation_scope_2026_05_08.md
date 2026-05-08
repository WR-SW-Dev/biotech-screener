# Spec 095 — Top-60 Ranker IC Evaluation Scope (2026-05-08)

**Status:** Evaluation methodology spec. No code changes to production ranker. No model changes.
**Priority:** 3
**Origin:** T5 ablation protocol Gate 7; T8 correction (2026-05-08). Recharacterized from "ic_decomposition.py bug" to "evaluation scope gap."
**Gates required:** None to define scope. Gate 4 (n≥30 HIT/MISS) + this spec's scope definition required before any formal ranker IC test runs.

**Hard constraints:**
- No changes to production ranker, selector, or scoring pipeline
- No changes to `ic_decomposition.py` in the scoring/production path
- Scope definition is a methodology document, not a production artifact
- Any new evaluation tooling is additive, not replacing existing tools

---

## 1. Problem Statement

`ic_decomposition.py` was designed to measure `coinvest_score_z` IC across all eligible tickers. That is its correct, designed purpose and it correctly implements that measurement. It is not broken.

However, the production ranker operates within a different population: the **top-60 selector cohort** (actionable_rank ≤ 60 at scoring time). Any IC test intended to evaluate ranker signal alternatives must use this subset, not the full eligible universe (~297 tickers). The two populations differ both in size and in the distribution of all features.

This spec defines the evaluation scope for all formal ranker IC tests so that Phase 2 and Phase 3 analyses use a consistent, correct methodology.

---

## 2. Evaluation Scope Definition

### 2a. Population
For any formal ranker IC test:
- **Include:** eligible tickers with actionable_rank ≤ 60 at the snapshot date
- **Exclude:** eligible tickers with actionable_rank > 60
- **Exclude:** ineligible tickers (eligible = 0 or null)

`actionable_rank` is the temporary pre-ranker rank assigned by selector_score within the eligible cohort. It is available in `rankings.csv` per snapshot.

### 2b. Signal column
For ranker IC tests:
- **Measure:** IC of the candidate signal (e.g., final_score, an alternative ranker feature, or selector_score) within the top-60 population
- **Do NOT use:** coinvest_score_z alone as the signal column for ranker IC measurement (that is a selector-level measurement; use ic_decomposition.py for that purpose)
- The signal must be the one the ranker would use, z-scored within the top-60 cohort as it is at scoring time

### 2c. Forward return
- `excess_return_5d` from `_forward_returns_panel.csv`
- Require `forward_complete = true`
- Measurement horizon: 5-day excess return (current standard)

### 2d. IC statistic
- Spearman rank correlation of signal vs excess_return_5d within the top-60 cohort
- Block bootstrap, NW-corrected t-statistic (minimum 5 lags; lag selection rule: L = floor(4 × (n/100)^(2/9)), minimum 5)
- Report: IC, NW-corrected t, n (top-60 observations), n_dates

### 2e. Regime caveat
- All April 2026 snapshots carry [REGIME_CAVEAT] regardless of methodology
- Report pre-selloff (before 04-21) and post-selloff (04-26 onward) separately

---

## 3. Relationship to Existing Tools

| Tool | Purpose | Population | Use for ranker IC? |
|------|---------|-----------|-------------------|
| `tools/ic_decomposition.py` | coinvest_score_z attribution | All eligible | No — selector-level signal, full universe |
| Phase 2 / Phase 3 ranker IC evaluation | Alternative signal IC within top-60 | Top-60 cohort only | Yes — must use this scope |
| Alt 10 descriptive (Spec 094) | Selector vs. ranker top-30 divergent comparison | Divergent tickers only | Descriptive only; no IC statistic |

---

## 4. Pre-Registration Requirement

Before running any formal ranker IC test in Phase 2 or Phase 3, a pre-registration note must be filed specifying:
1. The candidate signal column
2. The snapshot range to be tested
3. The IC computation method (confirming top-60 cohort scope and NW-corrected bootstrap)
4. The pre-specified hypothesis (directional or non-directional)

No post-hoc IC claims are valid without a pre-registration note.

---

## 5. Gate Dependency

This spec's scope definition must be confirmed (as a checklist item) in the Phase 2 evaluation plan before any formal IC test runs. Gate 7 ("IC evaluation scoped to top-60 cohort") is closed when this spec is accepted and the pre-registration requirement is documented.

Gate 7 does not require any code change. It requires that the evaluation methodology is agreed and documented before tests run.
