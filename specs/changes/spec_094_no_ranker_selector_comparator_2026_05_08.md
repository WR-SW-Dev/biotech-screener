# Spec 094 — No-Ranker Selector_Score Comparator (Alt 10) (2026-05-08)

**Status:** Descriptive analysis spec. No code changes. No production changes. No significance claims.
**Priority:** 2
**Origin:** T6 alpha synthesis (2026-05-08). Alt 10 classified MEDIUM_POTENTIAL_SHADOW; only alternative with no blockers.
**Gates required:** None. Computable immediately from existing panel.

**Hard constraints:**
- No code changes
- No production ranker changes
- No significance claims — this is descriptive only
- Do not interpret sign-test results as promotion evidence
- [REGIME_CAVEAT] applies to all April 2026 snapshots (XBI selloff + cohort change)

---

## 1. Purpose

This analysis tests the null hypothesis: does the production ranker add positive marginal value over the A4 selector alone?

Given ρ(coinvest_score_z, final_score) = +0.882, the ranker is largely re-weighting the same signal already dominant in the selector. If the selector_score top-30 performs equivalently to the final_score top-30 on forward returns, the case for ranker complexity is weakened until a specific orthogonal mechanism (Alt 3, 4, or 6) clears formal evidence gates.

This is the framing test for the entire ranking alternatives research program. It must be run before any other alternative can be benchmarked against "beating production."

---

## 2. Methodology

### 2a. Data sources
- `data/snapshots/_forward_returns_panel.csv` — excess_return_5d per (ticker, snap_date)
- `data/snapshots/{date}/rankings.csv` — selector_score, final_score, actionable_rank, eligible per snapshot

### 2b. Snapshot selection
- Use all 17 post-PIT canonical snapshots (2026-04-17 through 2026-05-08)
- Mark April 21–25 snapshots [REGIME_CAVEAT] (XBI selloff; report separately from clean window)
- Require forward_complete = true for forward return inclusion

### 2c. Divergent-snapshot identification
For each snapshot, construct:
- **Selector top-30:** top 30 eligible tickers ranked by selector_score descending
- **Ranker top-30:** top 30 eligible tickers ranked by final_score descending (production)

A snapshot is **divergent** if the two sets differ. An **identical** snapshot (ranker causes no reordering among top-30) carries zero information for this comparison.

Report:
- Count of divergent snapshots (n_div) out of 17 total
- Count of identical snapshots (n_id)

### 2d. Return comparison (divergent snapshots only)
For each divergent snapshot, identify:
- **Selector-only tickers:** in selector_score top-30 but not in final_score top-30
- **Ranker-override tickers:** in final_score top-30 but not in selector_score top-30

Compute:
- `excess_return_5d` for each selector-only ticker
- `excess_return_5d` for each ranker-override ticker
- Median differential: median(selector-only returns) − median(ranker-override returns)

### 2e. Summary statistics
- Pooled sign-test: in how many divergent snapshots is median(selector-only) > median(ranker-override)?
- Median of per-snapshot differentials across all divergent snapshots
- Separate results for XBI-selloff window (04-21 to 04-25) vs. clean window

### 2f. What NOT to compute
- No p-values, no t-statistics, no IC claims
- No inference about what would happen if the ranker were removed
- No conclusion about whether to remove the ranker

---

## 3. Output Format

Produce a short memo at `artifacts/audit/alt10_selector_comparator_YYYY_MM_DD.md` containing:

1. Snapshot inventory table (date, divergent Y/N, n_selector_only, n_ranker_override)
2. Per-divergent-snapshot return differential (selector_only median − ranker_override median)
3. Pooled sign-test result (X of N_div snapshots, selector-only median > ranker-override)
4. Pooled median differential across all divergent snapshots
5. Explicit REGIME_CAVEAT section covering 04-21 to 04-25 results
6. Explicit "no significance claims" footer

---

## 4. Interpretation Framework

This analysis is **descriptive only**. It cannot support promotion or demotion of the ranker.

Possible outcomes and their meaning:

| Result | Meaning |
|--------|---------|
| Selector-only consistently outperforms | Ranker may be adding noise; not sufficient to remove (need n≥30 + formal IC) |
| Ranker-override consistently outperforms | Ranker adding value; positive signal, not proof |
| Mixed / near-zero differential | Ranker is approximately neutral; supports OBSERVE posture |
| Regime-driven (04-21 to 04-25 dominates) | Results confounded by XBI selloff; cannot interpret directionally |

For any action based on this analysis (including ranker removal), formal IC testing within the top-60 cohort with block bootstrap is required (Phase 2, Gate 4 + Gate 7).

---

## 5. Dependencies

None. This analysis can run immediately.

No code needs to be written or changed. The analysis is a read from existing files.
