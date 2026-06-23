# EES Forward Validation

**Date:** 2026-06-23  
**Reviewer:** Operator (Claude Sonnet 4.6 assistant)  
**Script:** `scripts/research/ees_forward_validation.py`  
**Validation report:** `artifacts/audit/ees_validation_report_2026-06-23.md`  
**PIT panel:** `artifacts/audit/gap_panel_method_a_2026-06-23.csv` (accepted, `PASS_PIT_GAP_PANEL_ACCEPTED_FOR_DIAGNOSTIC_RESEARCH`)  
**Status:** READ-ONLY DIAGNOSTIC — production model freeze ACTIVE

---

## 1. Scope and Question

**Question:** Do EES scores or EES-derived miscalibration labels have forward-return
information after using the accepted PIT diagnostic panel?

**Restricted scope:**
- Panel: top-30 actionable names on each gap-period snapshot date (2026-01-16 to 2026-05-07, 87 dates)
- All names already screened through the production model — this measures **within-selected-cohort** ranking, not raw predictive power from the full universe
- Horizons: 5d and 20d (Method A primary); 60d sensitivity only (Method B, labeled)
- EES scores are loaded PIT-safe from the same-date rankings.csv
- No live data fetch. No production file changes. No model promotion.

---

## 2. Data and Coverage

| Attribute | Count |
|-----------|-------|
| Panel rows | 2,610 |
| Gap dates | 87 (2026-01-16 to 2026-05-07) |
| Unique tickers | 118 |
| ATXS-excluded rows | 14 |
| Binary-event rows (\|1d return\| > 30%) | 3 |

**EES score availability:**

| Score | Rows with data | Coverage |
|-------|----------------|----------|
| ees_v2_score | 2,610 | 100.0% |
| ees_v3_score | 570 | 21.8% |
| base_rate_gap_score | 2,610 | 100.0% |
| ees_eligible (flag) | 2,142 | 82.1% |

**Key coverage note:** `ees_v3_score` is populated in only 21.8% of rows. Per-date Spearman
IC computation requires ≥5 valid pairs per date. The sparse v3 distribution means no date
reaches the minimum threshold; v3 IC cannot be computed on this panel. See §5 for the
v3 evaluation limitation.

---

## 3. Results — ees_v2_score (Primary)

### 3.1 Cross-sectional IC, full sample

Per-date Spearman rank correlation between ees_v2_score and XBI-excess return. ATXS
excluded after 2026-01-23. Dates with fewer than 5 valid pairs excluded.

| Horizon | Mean IC | Median IC | Hit Rate | t-stat | N dates |
|---------|---------|-----------|----------|--------|---------|
| 5d | **0.0725** | 0.0644 | **0.686** | **3.06** | 51 |
| 20d | **0.0605** | 0.0238 | 0.571 | **2.05** | 35 |

Interpretation: Both horizons cross t = 2. The 5d result (t = 3.06, hit rate 68.6%) is
the more reliable of the two given larger sample size (51 vs 35 dates).

An IC of 0.07 is modest in absolute terms — consistent with expectations for a rank
correlation across a pre-screened ~30-name cross-section. The IC measures ranking ability
within the selected cohort, not absolute return prediction.

### 3.2 Robustness — binary-event exclusion

With only 3 binary events in the panel, exclusion has negligible effect:

| Horizon | Mean IC (excl. binary) | t-stat | Change vs full |
|---------|----------------------|--------|----------------|
| 5d | 0.0732 | 3.09 | +0.1% |
| 20d | 0.0615 | 2.08 | +1.7% |

The v7 continuity-flag population (35,326 flags noted in PIT review) consists of
smaller return moves, not discrete binary events. The 3 filtered here (\|1d\| > 30%)
confirm the panel has minimal extreme-event contamination.

### 3.3 Quintile analysis (pooled)

Top quintile minus bottom quintile excess return (XBI-adjusted), pooled across all dates:

| Horizon | Top Quintile | Bottom Quintile | Spread | N |
|---------|-------------|-----------------|--------|---|
| 5d | +0.39% | −0.56% | **+0.95pp** | 1,691 |
| 20d | +1.54% | +0.32% | **+1.22pp** | 1,211 |

Both spreads are directionally consistent with positive IC. The 20d spread (top +1.54% vs
bottom +0.32%) is notable: both quintiles are in positive territory but the top quintile
outperforms by 122bps over 20 trading days. This likely reflects the Phase 3 concentration
discussed in §4.

### 3.4 EES-eligible subset

Restricting to the 2,142 rows where `ees_eligible = True`:

| Horizon | Mean IC | t-stat |
|---------|---------|--------|
| 5d | 0.0554 | 2.04 |
| 20d | 0.0129 | 0.38 |

Compared with the full-sample IC (5d: 0.073, 20d: 0.061), the eligible subset shows:
- **5d** signal weakens modestly but remains significant (t = 2.04)
- **20d** signal largely disappears (t = 0.38)

The eligible-subset weakening at 20d is unexpected and suggests that EES v2 score carries
some information even for names the gate classifies as non-eligible — possibly because the
eligibility gate and the continuous score capture partially different information.

---

## 4. Cohort Breakdown — Phase 3 Concentration

This is the principal finding of this validation.

### 4.1 Phase breakdown

| Phase | N rows | ees_v2 5d IC | 5d t | ees_v2 20d IC | 20d t |
|-------|--------|-------------|------|--------------|-------|
| Phase 3 | 1,421 | **0.1738** | **4.97** | **0.2025** | **4.33** |
| Phase 2 | 429 | 0.0434 | 0.59 | 0.0629 | 0.62 |
| Phase 1 | 70 | — | — | — | — |

Phase 3 names (54% of the panel) drive virtually all of the full-sample IC signal.
Phase 3 IC of 0.17–0.20 with t ≈ 4–5 across 15–31 dates is a strong diagnostic
finding for a pre-screened cohort.

Phase 2 IC (0.04–0.06, t < 1) is statistically indistinguishable from zero.

### 4.2 Catalyst family breakdown

| Family | N rows | ees_v2 5d IC | 5d t | N dates |
|--------|--------|-------------|------|---------|
| CLINICAL | 1,378 | 0.1089 | 2.14 | 20 |
| REGULATORY | 138 | −0.2667 | −1.32 | 3 |

REGULATORY has only 3 valid IC dates — too few to interpret. The negative IC is not
reliable at this sample size.

CLINICAL (IC = 0.109, t = 2.14, 20 dates) is consistent with the Phase 3 finding —
most Phase 3 events in this cohort are clinical readouts.

### 4.3 Interpretation of Phase 3 concentration

EES v2 measures whether a catalyst event appears underpriced or overpriced relative to
historical base rates. The finding that this signal is concentrated in Phase 3 names is
theoretically coherent: Phase 3 readouts are more analyzable using historical success
rates (defined endpoints, established comparators, FDA prior decisions), giving the base
rate calculation more anchoring power. Phase 2 events are more heterogeneous in design
and interpretation, making the base rate comparison less stable.

This does **not** imply Phase 3 EES should be promoted into the model. It is a finding
warranting a design session, not an implementation decision.

---

## 5. EES v3 — Evaluation Limitation

`ees_v3_score` is populated in only 570 of 2,610 rows (21.8%). At that coverage level,
no gap-period snapshot date has ≥5 valid pairs, making per-date Spearman IC computation
impossible. The v3 score cannot be evaluated on this panel.

Possible causes:
- v3 has a stricter eligibility gate (`ees_v3_gate`, `ees_v3_misprice_available`)
- v3 was introduced later in the gap period with lower retrospective backfill
- v3 scope may be narrower than v2

To evaluate v3, a denser coverage period would be required, or a separate validation
using only dates/tickers where v3 is populated (accepting that those dates are not
a random sample from the gap period).

---

## 6. base_rate_gap_score — No Independent 5d Signal

| Horizon | Mean IC | t-stat | Notes |
|---------|---------|--------|-------|
| 5d | 0.0059 | 0.22 | Noise |
| 20d | 0.0374 | 1.36 | Marginal |

base_rate_gap_score has no measurable 5d predictive content independently. The marginal
20d reading (t = 1.36) does not clear any significance threshold but the directional
consistency with ees_v2 is noted. The 20d quintile spread for base_rate_gap_score
(top +1.54% vs bottom −0.33%, spread = +1.87pp) is the widest of the three scores,
which is inconsistent with the near-zero IC — likely driven by outlier composition in
the quintile buckets rather than a genuine ranking effect.

---

## 7. Method B 60d Sensitivity

**Label: SENSITIVITY_ONLY_NOT_PRIMARY_EVIDENCE** — single May 7 archive basis;
16 dates computed vs 20-date threshold (sub-threshold per PIT review §3).

| Score | Mean IC (60d) | t-stat | N dates |
|-------|-------------|--------|---------|
| ees_v2_score | 0.1454 | 2.95 | 16 |
| ees_v3_score | N/A | — | 0 |
| base_rate_gap_score | 0.0850 | 1.94 | 16 |

These numbers are directionally consistent with the primary results and suggest the
ees_v2 signal may persist at 60d. Because the data is sub-threshold and sensitivity-
labeled, no 60d conclusion is drawn. This reading is quarantined orientation.

---

## 8. Governance Checks

| Check | Status |
|-------|--------|
| Production model freeze | ACTIVE — no ranker/selector/sizing/final_score/gate/snapshot changes |
| No live data fetch | PASS |
| No API calls | PASS |
| No production file imports | PASS |
| EES scores loaded PIT-safe (same-date rankings.csv) | PASS |
| ATXS exclusion applied after 2026-01-23 | PASS |
| Method B labeled throughout | PASS (all 60d rows carry sensitivity label) |
| No trading or position language | PASS |
| No alpha claim | PASS |
| No freeze-lift conclusion | PASS |
| No model promotion language | PASS |

---

## 9. Verdict

```
PASS_EES_DIAGNOSTIC_PREDICTIVE_SIGNAL_OBSERVED
```

**Summary:**

EES v2 has a statistically significant forward-return IC in this diagnostic panel:
5d IC = 0.073 (t = 3.06), 20d IC = 0.061 (t = 2.05). The signal is not uniformly
distributed — it is concentrated in Phase 3 names (5d IC = 0.174, t = 4.97; 20d IC =
0.203, t = 4.33). Phase 2 has no measurable signal.

**What this finding is:**
- Evidence that within the Phase 3 sub-cohort of the top-30 screener, higher EES v2
  scores at snapshot time correlate positively with subsequent 5d and 20d XBI-excess
  returns, over the 2026-01-16 to 2026-05-07 gap period.
- A diagnostic result on a pre-screened cohort in a single time window.

**What this finding is not:**
- Validation of EES v2 as a standalone alpha factor.
- Evidence that EES is predictive in general or across all biotech names.
- A basis for model promotion, weight changes, or any portfolio action.
- Applicable to Phase 2 names (signal not present).

**Scope limitations:**
- Single gap period (Jan–May 2026): one macroeconomic and event-density environment
- Pre-screened cohort: all 30 names are already model-selected; IC is within-cohort
- Phase 3 dominates (54% of rows): full-sample IC is Phase 3 driven
- EES v3 unevaluable at this panel's coverage
- base_rate_gap_score provides no independent 5d signal

**Operator decision gate:**  
The Phase 3 concentration finding (t ≈ 5) is strong enough to warrant a design-level
investigation of whether EES v2 Phase 3 weighting could be incorporated into the model
in a future unfreeze window. That is a **design session question**, not an implementation
action. The freeze remains ACTIVE. No model changes are implied by this memo.

---

## 10. Output Files (Quarantined — Not Committed)

| File | Rows | Status |
|------|------|--------|
| `artifacts/audit/ees_validation_panel_2026-06-23.csv` | 2,610 | Joined panel, gitignored |
| `artifacts/audit/ees_validation_report_2026-06-23.md` | — | Machine-readable stats |

Both CSV files are gitignored. This memo and the validation report markdown are the
only committed artifacts from this run.

---

*Generated from `scripts/research/ees_forward_validation.py` — DIAGNOSTIC_ONLY |
NO_PRODUCTION_CHANGES | FREEZE_ACTIVE*
