# Full Signal IC Diagnostic Sweep

**Date:** 2026-06-20  
**Status:** COMPLETE  
**Headline:** catalyst_decay_w is a Phase-3 candidate; institutional circularity is now quantified

---

## Status

```
FULL_SIGNAL_IC_DIAGNOSTIC_SWEEP_COMPLETE
READ_ONLY
NO_MODEL_CHANGE
NO_RANKER_CHANGE
NO_SELECTOR_CHANGE
NO_PRODUCTION_OUTPUT_CHANGE
NOT_COMMITTED
```

---

## Supersedes Preliminary Result

The earlier single-window peek (April T+20: catalyst_score +0.0700) is **FROZEN AS PRELIMINARY / SUPERSEDED**. It was computed with (a) exact-date forward lookup and (b) forward snapshots truncated at the window end — both wrong. This sweep uses correct global forward loading (nearest snapshot on/after base+horizon, +7d tolerance) and replaces it.

---

## Method

- **Fields:** final_score, catalyst_score, catalyst_decay_w, coinvest_score_z, financial_score
- **Horizons:** T+5, T+10, T+20, T+60
- **Windows:** Feb / Mar / Apr / May 2026, plus combined Feb–May (91 base snapshots)
- **Segments:** cohort (actionable_rank ≤ 60), all_eligible (eligible=1), in_window (catalyst_in_window=1)
- **Forward returns:** nearest snapshot on/after base+horizon (≤+7d); missing → UNOBSERVABLE (never zero/NaN)
- **Stat:** per-base-date Spearman IC, aggregated to mean / std / t across base dates
- 189 snapshots loaded (2024-10-18 .. 2026-06-18)

---

## ⚠️ Three Caveats That Govern Interpretation

1. **t-stats are inflated by overlapping windows.** Consecutive daily base dates share almost all of their T+20/T+60 forward period, so observations are highly autocorrelated — they are NOT independent. A naive t≈6 over a 91-day window at T+20 corresponds to only ~4–5 independent periods; real significance is far lower. **Trust sign-consistency and relative ordering across windows more than the absolute t-values.**

2. **final_score is UNOBSERVABLE in Feb/Mar.** The pairwise_minimal ranker that emits final_score=ranker_v2_score is a recent deployment; historically final_score was unpopulated. final_score evidence rests on Apr/May only.

3. **catalyst_decay_w = 0 in the in_window segment** (all near-window names share the maxed decay weight → no variance → undefined IC). Expected, not a defect.

---

## Results — COHORT segment (actionable_rank ≤ 60, the operational Phase 3 question)

mean IC / t-stat per horizon (`*` = mean ≥ 0.0200):

```
                    T+5            T+10           T+20           T+60
Feb2026
  catalyst_score    +0.046 t+2.1*  +0.050 t+2.0*  +0.041 t+1.6*  -0.018 t-0.7
  catalyst_decay_w  +0.057 t+1.2*  +0.007 t+0.1   -0.060 t-1.6   -0.090 t-2.8   ← Feb counterexample
  coinvest_score_z  -0.009         -0.013         -0.046         +0.047 t+1.1*
  financial_score   +0.028 t+1.0*  +0.015         -0.016         +0.063 t+2.6*
  final_score       UNOBS          UNOBS          UNOBS          UNOBS
Mar2026
  catalyst_score    -0.004         -0.018         -0.030         -0.000
  catalyst_decay_w  +0.003         +0.026 t+1.4*  +0.029 t+1.4*  +0.099 t+5.6*
  coinvest_score_z  +0.023 t+0.7*  +0.055 t+1.6*  +0.085 t+4.5*  +0.076 t+5.2*
  financial_score   -0.012         -0.024         -0.020         -0.061
  final_score       UNOBS          UNOBS          UNOBS          UNOBS
Apr2026
  catalyst_score    +0.042 t+1.8*  +0.116 t+5.6*  +0.169 t+7.5*  +0.221 t+6.0*
  catalyst_decay_w  +0.046 t+2.5*  +0.078 t+4.2*  +0.137 t+11.2* +0.238 t+8.5*
  coinvest_score_z  +0.003         +0.044 t+2.4*  -0.015         -0.032
  financial_score   -0.014         +0.036 t+1.2*  +0.101 t+3.5*  +0.100 t+2.7*
  final_score       +0.054 t+1.9*  +0.035 t+1.2*  -0.095 t-2.6   -0.115 t-2.9   ← ranker output negative
May2026
  catalyst_score    +0.024 t+1.2*  +0.025 t+1.3*  +0.052 t+3.7*  UNOBS
  catalyst_decay_w  +0.087 t+4.3*  +0.167 t+6.6*  +0.189 t+9.1*  UNOBS
  coinvest_score_z  -0.021         -0.032         +0.009         UNOBS
  financial_score   +0.094 t+2.4*  +0.092 t+2.4*  +0.034 t+0.8*  UNOBS
  final_score       -0.082         -0.092         -0.034         UNOBS         ← ranker output negative

Feb–May COMBINED (91 base dates)
  catalyst_score    +0.026 t+2.2*  +0.044 t+3.6*  +0.058 t+4.5*  +0.047 t+2.4*
  catalyst_decay_w  +0.044 t+3.8*  +0.072 t+5.0*  +0.086 t+6.1*  +0.096 t+4.5*  ← strongest, all+
  coinvest_score_z  +0.002         +0.023 t+1.5*  +0.020 t+1.5   +0.039 t+2.7*  ← weak in cohort
  financial_score   +0.019         +0.025 t+1.7*  +0.025 t+1.6*  +0.020 t+1.3*
  final_score       -0.008         -0.022         -0.068 t-2.4   -0.115 t-2.9   ← ranker output negative
```

### Cohort read

- **final_score (the actual ranker output) has NEGATIVE IC at T+20/T+60** in every window where it is observable (Apr, May, combined). The deployed ranker is anti-predictive at longer horizons within its own cohort. Consistent with Phase B.
- **catalyst_decay_w is the strongest and most consistently positive cohort signal** — positive and significant at all horizons in the combined window, and in 3 of 4 individual windows (Mar, Apr, May). **Feb is a genuine counterexample** (negative at T+20/T+60).
- **catalyst_score (raw) is positive on net** (combined all+) but flips negative in Mar — the *decayed* variant is the more reliable form.
- **coinvest_score_z is weak within the cohort** (combined ≈ +0.02, mostly below the 0.0200 gate) — far weaker than its full-universe behavior below.

---

## Results — ALL_ELIGIBLE segment (raw predictiveness, pre-selection)

```
Feb–May COMBINED
  catalyst_score    +0.005         +0.004         -0.001         +0.023 t+3.2*
  catalyst_decay_w  +0.015         +0.022 t+2.4*  +0.023 t+3.2*  +0.035 t+4.8*
  coinvest_score_z  +0.017         +0.039 t+3.1*  +0.053 t+4.9*  +0.112 t+11.5* ← strong on full universe
  financial_score   -0.016         -0.017         -0.020         -0.004        ← anti-predictive
  final_score       -0.013         +0.003         +0.002         +0.023 t+6.0*
```

### All-eligible read

- **coinvest_score_z is the STRONGEST predictor on the full eligible universe** (T+20 +0.053, T+60 +0.112) — institutional conviction genuinely separates winners across the broad universe. Mar/Apr individually very strong.
- **financial_score is anti-predictive on the full universe** (consistently negative) — yet it carries a −0.0533 ranker weight, so it is effectively shorting a noisy/negative signal.

---

## 🔑 The Core Finding: Circularity, Quantified

Compare coinvest_score_z across segments (combined, T+20):

```
                          all_eligible    cohort
coinvest_score_z IC:        +0.053         +0.020     ← predictive power HALVES after selection
catalyst_decay_w IC:        +0.023         +0.086     ← signal STRENGTHENS within cohort
```

This is the institutional-circularity hypothesis confirmed numerically:

- **Institutional signal spends its predictive power on SELECTION.** On the full universe coinvest_score_z is strong (+0.053); within the already-institutionally-filtered cohort it collapses to +0.020. The cohort is pre-sorted on this axis, leaving little residual spread to re-rank on. Re-ranking the cohort with coinvest_score_z is near-circular — exactly why DEM's final_score IC fails.
- **catalyst_decay_w shows the opposite, complementary pattern:** weaker on the full universe (+0.023) but *stronger within the cohort* (+0.086, t+6.1). It carries signal precisely where institutional signal is exhausted and where the ranker actually operates.

This is the orthogonal-and-predictive-within-cohort property Phase 3 needs. It is the strongest evidence yet that the fix is not tuning institutional weight but adding a catalyst-timing axis to the *ranker*.

---

## Decision Framework Applied

```
catalyst_decay_w:
  Repeatable cohort IC ≥ 0.0200 across horizons/windows? — YES in combined (all horizons,
  t inflated but sign-consistent) and 3 of 4 windows; Feb is a counterexample.
  → CATALYST_SIGNAL_PHASE3_CANDIDATE (decayed variant specifically)

catalyst_score (raw):
  Positive on net but sign-flips by window (Mar negative); blends far-dated events.
  → CATALYST_SIGNAL_PROMISING_BUT_UNPROVEN

coinvest_score_z:
  Strong on full universe, weak within cohort (circularity).
  → predictive for SELECTION, not for within-cohort RANKING.

financial_score:
  Flat-to-negative across segments; anti-predictive on full universe.
  → CATALYST_SIGNAL_NOT_SUPPORTED (as a ranking signal; current −0.0533 weight is questionable)

final_score (ranker output):
  Negative IC at T+20/T+60 where observable.
  → confirms DEM blocker; ranker is anti-predictive at longer horizons in-cohort
```

**Overall classification:** `CATALYST_SIGNAL_PHASE3_CANDIDATE` (driven by catalyst_decay_w), with the decisive supporting insight that institutional signal is circular within the cohort.

---

## What This Does and Does Not Authorize

```
✅ Establishes catalyst_decay_w as a Phase-3 ranker-feature CANDIDATE worth formal design
✅ Quantifies why DEM fails IC (institutional circularity within cohort)
✅ Flags financial_score's negative full-universe IC as a separate concern

❌ Does NOT authorize adding catalyst_decay_w to the ranker
❌ Does NOT authorize changing/removing financial_score
❌ Does NOT change weights, formulas, gates, or any production output
❌ A positive sweep is NOT a passing IC gate — overlapping-window t-stats are inflated;
   Feb counterexample exists; this must be confirmed with proper non-overlapping /
   block-bootstrap significance before any Phase-3 commitment.
```

---

## Recommended Next Step

1. **Treat catalyst_decay_w as the lead Phase-3 candidate** — but require a proper significance test before any commitment: non-overlapping base dates (or block-bootstrap) to deflate the autocorrelated t-stats, plus an out-of-sample window (Jun + the post-July-8 data) for confirmation.

2. **Re-examine financial_score's −0.0533 ranker weight separately** — it is anti-predictive on the full universe and only marginally positive within cohort. This is a distinct finding worth its own note.

3. **Do NOT implement.** This sweep informs the Phase 3 design conversation; it does not authorize a ranker change. DEM remains blocked pending July 8.

4. **July 8:** add catalyst_decay_w to the real-time confirmation run alongside the DEM remeasurement (using the `--score-field` tool, now available).

---

## Governance Boundary

✅ Read-only sweep; no model/ranker/selector/production changes; no commits.

---

## Files Modified

**None (production files).** Sweep script lives in scratchpad (not a permanent tool). This audit added only `artifacts/audit/full_signal_ic_diagnostic_sweep_2026_06_20.md` (untracked).

---

## Summary

| Signal | Full-universe IC | Within-cohort IC | Phase-3 verdict |
|--------|------------------|------------------|-----------------|
| **catalyst_decay_w** | weak (+0.023) | **strong (+0.086, 3/4 windows)** | ✅ CANDIDATE |
| catalyst_score | ~0 | positive but window-inconsistent | PROMISING_BUT_UNPROVEN |
| coinvest_score_z | **strong (+0.053)** | weak (+0.020) | selection signal, circular for ranking |
| financial_score | negative | marginal | NOT_SUPPORTED (weight questionable) |
| final_score (output) | n/a | **negative at T+20/T+60** | confirms DEM blocker |

**Bottom line:** catalyst_decay_w carries predictive signal *exactly where the ranker operates and where institutional signal is exhausted* — the orthogonal-and-predictive property Phase 3 needs. This is a candidate, not a conclusion: overlapping-window t-stats are inflated and Feb is a counterexample. Confirm with block-bootstrap + out-of-sample before any Phase-3 commitment.

---

## References

- **Catalyst audit:** catalyst orthogonal to institutional (+0.249 / −0.107)
- **Institutional audit:** institutional circularity hypothesis (now quantified here)
- **Phase B:** DEM final_score IC fails — confirmed (negative at T+20/T+60)
- **Tooling:** tools/measure_final_score_ic_spec100.py --score-field (this session)
- **Sweep script:** scratchpad/full_signal_ic_sweep.py (read-only, non-permanent)
