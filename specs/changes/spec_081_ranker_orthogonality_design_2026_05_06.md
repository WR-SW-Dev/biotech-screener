# Spec 081 — Ranker Orthogonality / Ranker Role Clarification (2026-05-06)

**Status:** Architecture clarification spec. No code changes. No retrain. Defines
what the ranker is supposed to do after selector filtering, and scopes a future
ablation battery that tests the orthogonality hypothesis. Verdict target: design
alignment + future ablation gate.

**Origin:** Investment Logic Audit (2026-05-06). The audit flagged that the system
selects heavily on `coinvest_score_z` and then ranks again with capped `coinvest_score_z`.
The cap reduces double-counting but the architectural question remains: should the
ranker use signals that are orthogonal to the selector, or should it amplify the
same signal that passed the selection gate?

**Hard constraints:**
- No ranker retraining from this spec
- No selector / sizing weight changes
- No feature additions without Checklist v2 evidence
- No EES / clinical / Polymarket features — those lanes are closed
- This is a design document and ablation spec, not an implementation ticket

---

## 1. Problem statement

### 1a. Current design

**Selector:** passes names with high `coinvest_score_z` (primary), `financial_score`
(secondary), and `inst_delta_z` (pruner). The selector is the dominant filter:
92.7% of selector variance is explained by `coinvest_score_z` alone.

**Ranker:** pairwise 2-feature model:
- Feature 1: `coinvest_score_z` (capped at +0.02 / -0.0533 per Family C fit)
- Feature 2: `financial_score` (rank-norm of Module 5 output)

The cap on `coinvest_score_z` in the ranker was introduced precisely to reduce
double-weighting with the selector. But the cap is a practical mitigation, not a
principled resolution of the architectural question.

### 1b. The circularity concern

A name that passes the selector on high `coinvest_score_z` then gets ranked higher
by the ranker partly because of the same `coinvest_score_z`. Even with a cap:

- A name at `coinvest_score_z = +2.0` passes the selector AND gets a capped ranker
  boost from coinvest
- A name at `coinvest_score_z = +0.8` that barely passes the selector gets a
  smaller ranker boost from the same signal

The ranker's coinvest term re-sorts the passed cohort by the same dimension the
selector used to admit them. This is not wrong by definition — it may be the right
design if coinvest quality is the primary return predictor at every stage. But it
means the ranker is currently amplifying one signal rather than adding orthogonal
information.

### 1c. The architectural question

What is the ranker supposed to do, given that the selector has already filtered on
coinvest quality?

Five candidate answers, each implying a different ranker design:

---

## 2. Candidate ranker roles

### Role 1: Amplify coinvest quality (current design)
**Hypothesis:** Within the coinvest-selected cohort, higher coinvest quality still
predicts better returns. The selector is a binary gate; the ranker captures the
continuous gradient within the passed group.

**Current evidence:** Ranker IC = +0.106 (coinvest_score_z in ranker). This is
consistent with Role 1. But it does not distinguish Role 1 from "coinvest is simply
the strongest available signal at every level of granularity."

**Testable prediction:** After selector filtering, coinvest_score_z should still
be the best single-feature ranker predictor. ρ(coinvest_score_z, returns within
cohort) > ρ(any other feature, returns within cohort).

### Role 2: Rank by financial stress / upside (partial current design)
**Hypothesis:** Within the coinvest-selected cohort, the ranker should primarily
sort by who has the most financial optionality (high stress = upside on HIT, low
burn = surviving to catalyst). `financial_score` captures this.

**Current evidence:** `financial_score` is Feature 2 with -0.0533 weight in ranker.
The negative weight is counterintuitive at first glance — higher `financial_score`
(rank-norm) maps to a lower ranker score. This is consistent with `financial_score`
being a penalizer of "safe" names (established revenue, low stress) rather than a
promoter of distressed upside. Verify this interpretation before adding features.

**Testable prediction:** ρ(financial_score, returns within cohort) < 0, meaning
financially-stressed names outperform safer ones within the selected cohort.

### Role 3: Rank by catalyst timing (currently absent)
**Hypothesis:** After coinvest selection, the ranker's primary job should be to
prioritize names whose release valve is nearest in time. A 27-day PDUFA should
rank above a 300-day Phase 3 completion with identical coinvest/financial scores.

**Current evidence:** Not tested post-PIT. Spec 080 defines this test.

**Testable prediction:** `catalyst_decay_w` (or `days_to_catalyst_norm`) has
IC > 0 within the selected cohort. (Spec 080 result will resolve this.)

### Role 4: Rank by expectation gap (closed lane)
**Hypothesis:** The ranker should find names where market expectations are most
miscalibrated vs intrinsic probability. EES v3 attempted this and failed due to
pmv-dominance. `base_rate_gap_score` is anti-predictive.

**Current status:** CLOSED. Cannot extract expectation error from expectation alone.
Requires external inputs (IV-vs-realized history, cross-sectional dispersion,
microstructure flow). Do not revive until those inputs are available.

### Role 5: Rank by risk-adjusted event EV (future candidate)
**Hypothesis:** The ranker should prefer names where `event_ev_p_hit` × expected
return on HIT (scaled by position size and stop) exceeds a threshold.

**Current status:** `event_ev_p_hit` is too sparse (n=7 post-PIT). The calibration
review (Spec 079) must run first. Even if calibrated, adding EV to the ranker
requires Checklist v2. This role is a long-horizon candidate (earliest: ~2026-Q4).

---

## 3. Orthogonality hypothesis

The orthogonality hypothesis states: **the ranker should add information orthogonal
to the selector so that the combined selector + ranker pipeline captures a broader
set of predictors than either alone.**

Under this hypothesis, the ranker should NOT re-sort on `coinvest_score_z` at all,
because:
1. The selector already used coinvest as its primary dimension
2. Any remaining coinvest gradient within the passed cohort is small (selection
   restricts range) and noisy
3. A ranker built on orthogonal signals would add a second independent return predictor

**Counter-argument:** If `coinvest_score_z` has monotonic return-predictive power
within the selected cohort (not just for selection), then restricting the ranker to
orthogonal signals means throwing away the strongest available predictor within the
cohort. The cap-not-eliminate approach is the practical resolution of this tension.

**Resolution path:** Test both. Run a ranker ablation where Feature 1 is replaced by
a signal orthogonal to `coinvest_score_z` (e.g., `catalyst_decay_w` alone, or
`financial_score` alone without the coinvest term). If orthogonal rankers produce IC ≥
current 2-feature ranker IC, the orthogonality hypothesis is supported.

---

## 4. Proposed ablation battery (future, not current)

This battery should run only after:
- Spec 078 (false-catalyst gate) is in production
- Post-13F cohort window is closed (~2026-05-15)
- n(resolved outcomes post-PIT) ≥ 30

| Variant | Features | Tests role |
|---|---|---|
| B0 | coinvest_score_z (capped), financial_score | Baseline (current) |
| B1 | financial_score only | Role 2 alone |
| B2 | catalyst_decay_w only | Role 3 alone (requires Spec 080 pre-conditions) |
| B3 | financial_score, catalyst_decay_w | Roles 2+3, fully orthogonal to selector |
| B4 | coinvest_score_z (capped), catalyst_decay_w | Baseline + Role 3 |
| B5 | coinvest_score_z (capped), financial_score, catalyst_decay_w | Full 3-feature |

The key comparison is B0 vs B3: does the orthogonal ranker (no coinvest term)
match or beat the current design?

Evaluation protocol: identical to Spec 080 §5b (pairwise IC, NW-corrected t,
bootstrap CI, FDR correction across variants).

---

## 5. Design decisions required (no code until resolved)

The following questions must be answered before any ranker retrain:

1. **What does `financial_score` actually penalize?** The negative weight is
   consistent with penalizing safe/profitable names, but this should be verified
   against the Module 5 rank-norm construction. Read `docs/MODEL_DOCUMENTATION.md`
   and confirm the directionality before treating it as "upside" vs "safety."

2. **Is the coinvest cap empirically derived or arbitrary?** The +0.02 / -0.0533
   cap came from Family C fit. Verify whether this cap was fit to minimize
   double-weighting or to maximize IC. Document the derivation.

3. **Does ranker IC hold within the selector-passed cohort specifically?** Current
   ranker IC measurements use the full universe. IC within the selected cohort
   (coinvest-filtered) may be lower. Measure and document this separately.

4. **Is there a return-predictive gradient within the coinvest cohort?** Plot
   returns vs coinvest_score_z restricted to names that were in the top-30/60 on
   a given snapshot. If the gradient is flat or weak, Role 1 is not supported.

---

## 6. What is explicitly out of scope

- Any ranker retrain before the ablation battery runs and clears evidence thresholds
- EES / expectation-error features (closed)
- Clinical quality features (closed per 2026-05-04 verdict)
- Options features in the ranker
- Rank-weighted pairwise loss (rejected per alpha freeze policy)
- Selector changes — this spec is about the ranker only
- Sizing changes based on ranker redesign

---

## 7. Verdict target

**Architecture clarification + future ablation battery.** This spec does not trigger
any code changes. It documents the design question, the candidate roles, and the
ablation battery that will test them. The ablation should run as part of the
post-Spec-078, post-13F, post-n≥30 review window — the same window as Spec 080.

The two specs (080 and 081) can share the same ablation run: Spec 080 tests timing
as a 3rd feature, Spec 081 tests orthogonal role decomposition. Run them together
in one evidence session, not two separate cycles.

---

## 8. Dependencies

| Dependency | Status |
|---|---|
| Spec 078 (false-catalyst gate) | Required for clean training data |
| Spec 080 (catalyst timing ablation) | Companion spec — run together |
| Post-13F window (~2026-05-15) | Required |
| n ≥ 30 resolved outcomes | ~2026-06-15 |
| Design questions (§5) resolved | Prerequisite for writing ablation code |
