# Spec 080 — Catalyst Timing Ranker Ablation (2026-05-06)

**Status:** Spec only. No code changes. Defines the future ablation test that asks
whether `catalyst_decay_w` or a related timing signal should become the 3rd ranker
feature. Verdict target: RETEST_LATER — not an implementation ticket.

**Origin:** Investment Logic Audit (2026-05-06). The audit identified the live
2-feature ranker as timing-blind. Both a 300-day far-out catalyst and a 27-day PDUFA
enter the top-30 cohort on equal footing once the selector passes them. The selector
applies a near-term catalyst bucket (`binary_now` / `build_window`) as a threshold,
but the ranker makes no distinction between these within the passed cohort.

**Hard constraints:**
- No ranker retraining until evidence thresholds are met
- No selector / sizing / `coinvest_score_z` / `financial_score` changes
- False-catalyst gate (Spec 078 Lanes A+B) must ship first
- Post-PIT only: no pre-PIT backtests as evidence
- Post-13F cohort window only: no training on cohort-contaminated snapshots
- ≥30 resolved catalyst outcomes required before running ablation

---

## 1. Problem statement

The live 2-feature ranker uses `coinvest_score_z` (capped) and `financial_score`.
It was frozen at 2 features per `policy_alpha_freeze_2026_04_04.md` pending evidence
of incremental IC from any additional feature.

The investment logic audit's architectural gap: within the cohort that clears the
selector, catalyst timing varies enormously. A name with a 27-day PDUFA and a name
with a 300-day Phase 3 completion date receive identical ranker scores if their
`coinvest_score_z` and `financial_score` are equal. The selector's binary `catalyst_near`
flag collapses this timing variation to a binary threshold.

This creates two failure modes:
1. A near-term catalyst name gets ranked behind a far-out catalyst name with slightly
   better coinvest / financial scores
2. A far-out catalyst name that would not benefit from the near-term release-valve
   thesis consumes a top-30 slot while a higher-conviction near-term name sits at
   rank 31

The ablation test asks: does adding a catalyst timing decay weight improve ranker
IC in a post-PIT, post-13F, fair-sample setting?

---

## 2. Why it matters to the investment thesis

The thesis is coinvest quality + financial stress-upside + near-term catalyst
release valve. If the ranker cannot distinguish between near-term and far-out
catalysts within the selected cohort, the "release valve" component of the thesis
is partially blind in the ranking step.

However, this is a **testable** claim, not an obvious one. It is possible that:
- Within the selected cohort, catalyst timing is already adequately captured by the
  selector's `build_window` / `binary_now` gate, and the ranker's role is
  coinvest/financial tiebreaking within that gate
- Adding catalyst timing to the ranker creates implicit double-weighting with the
  selector's timing gate
- `catalyst_decay_w` is correlated with false-catalyst contamination (near-term
  false catalysts decay heavily and may dominate a timing signal)

The ablation test must resolve this empirically, not by assumption.

---

## 3. Production baseline

```
Feature 1: coinvest_score_z (capped)
Feature 2: financial_score

Source: production_data/ranker_v2_model.json
Ruleset: 2a3e79eb (v1.13.0)
```

The baseline IC and pairwise win-rate are established in
`artifacts/ranker/` and `signal_research_history.md`.

---

## 4. Proposed ablation variants

All variants use the same 2-feature baseline plus one candidate timing feature.
All are post-PIT only, post-13F cohort window only.

| Variant | Features | Notes |
|---|---|---|
| A0 (baseline) | coinvest_score_z, financial_score | Current production |
| A1 | coinvest_score_z, financial_score, catalyst_decay_w | Primary candidate |
| A2 | coinvest_score_z, financial_score, catalyst_score | Composite timing score |
| A3 | coinvest_score_z, financial_score, days_to_catalyst_norm | Raw day-count normalized |
| A4 | coinvest_score_z, financial_score, event_family_onehot | Event family controls (PDUFA vs DATA_READOUT vs other) |

`catalyst_decay_w` definition (to be confirmed against production code):
```
catalyst_decay_w = exp(-days_to_catalyst / decay_half_life)
where days_to_catalyst = max(0, next_catalyst_date - snapshot_date)
and decay_half_life is a hyperparameter to be specified in the test (suggest 60d, 90d, 120d)
```

---

## 5. Evaluation protocol

### 5a. Data requirements (non-negotiable)

- Post-PIT only: snapshot dates ≥ 2026-04-13
- Post-13F cohort window: snapshot dates ≥ 2026-05-15 (after Q1 2026 13F refresh)
- Minimum resolved catalyst outcomes: ≥30 HIT/MISS post-PIT with known resolution dates
- False-catalyst gate applied: Spec 078 Lanes A+B must be in production before
  training data is assembled (removes false-catalyst rows from the training set)
- Sample construction: pairwise ranking (consistent with current ranker methodology —
  ordinal, no rank-weighting per `policy_alpha_freeze_2026_04_04.md`)

### 5b. Evaluation metrics

Primary:
- Pairwise IC (Spearman ρ between ranker score and subsequent return)
- NW-corrected t-statistic (at least 5 lags given weekly observation frequency)
- Bootstrap 95% CI on pairwise IC (≥1000 draws)

Secondary:
- Top-30 overlap with production baseline (Jaccard)
- Top-5 / Top-10 precision vs XBI returns
- FDR-corrected p-value across all variants (family-wise error correction for 4 tests)

### 5c. Promotion threshold (not current goal — for future reference)

Any variant that clears all of the following may be considered for promotion via
Checklist v2:
- NW-corrected t ≥ 2.0 (marginal: 1.65)
- Bootstrap CI excludes 0 at 90% confidence
- FDR-corrected p < 0.05 (Benjamini-Hochberg across variants)
- LOSO (leave-one-snapshot-out) IC > 0 in ≥ 70% of folds
- Year-stability: IC positive in both of the available calendar years

---

## 6. Pre-conditions (all must be satisfied before running ablation)

| Pre-condition | Status |
|---|---|
| Spec 078 Lane A (CORPORATE_UPDATE veto) shipped | Not yet |
| Spec 078 Lane B (calendar_confidence threshold) shipped | Not yet |
| Post-13F cohort window closed (~2026-05-15) | Not yet |
| n(resolved catalyst outcomes post-PIT) ≥ 30 | ~7 today |
| Ranker policy freeze review scheduled | Per alpha freeze policy |

**None of the ablation tests should run until all pre-conditions are met.**
The false-catalyst gate is especially critical: training a ranker on false-catalyst
rows will spuriously strengthen or weaken timing signals depending on the contamination
direction.

---

## 7. Expected timeline

| Milestone | Estimated date |
|---|---|
| Spec 078 Lanes A+B shipped | ~2026-05-20 (after post-13F window) |
| Post-13F cohort window closed | ~2026-05-15 |
| n(resolved outcomes) ≥ 30 | ~2026-06-15 |
| Ablation data assembly | ~2026-06-20 |
| Ablation runs complete | ~2026-06-25 |
| Verdict memo | ~2026-06-30 |

---

## 8. Verdict target

**RETEST_LATER.** This is not a current implementation ticket. No code changes,
no ranker retraining, no feature additions until all pre-conditions are met and
the ablation IC clears the promotion threshold. The spec exists to ensure the test
is run correctly when evidence accumulates, not run prematurely.

---

## 9. What is explicitly out of scope

- Any ranker retraining before pre-conditions are met
- Adding catalyst timing to the selector (that is a separate alpha-lane decision)
- Rank-weighted pairwise loss functions (rejected per alpha freeze policy: ordinal only)
- EES / expectation-error features (closed lane per ees_v3 structural failure memo)
- Clinical quality features in the ranker (closed lane per clinical verdict 2026-05-04)
- Coinvest / financial / inst_delta weight changes
- Timing signal derived from false-catalyst rows (must be filtered first)

---

## 10. Dependencies

| Dependency | Status |
|---|---|
| Spec 078 (false-catalyst gate) | Required pre-condition |
| Spec 071 Lane 2 (CTGOV classifier) | Required for clean training data |
| Policy alpha freeze (2026-04-04) | Governs promotion path |
| Post-13F quarantine (~2026-05-15) | Required for clean cohort |
| n ≥ 30 resolved outcomes | ~2026-06-15 |
