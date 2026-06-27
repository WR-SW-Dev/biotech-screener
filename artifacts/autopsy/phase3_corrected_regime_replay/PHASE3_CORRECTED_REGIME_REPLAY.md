# Phase 3 Corrected Regime Ranking Replay

> Classification: `PHASE3_CORRECTED_REGIME_RANKING_REPLAY_DIAGNOSTIC_NO_MODEL_CHANGE`
> Date: 2026-06-26
> Scope: Diagnostic only. No model, ranker, selector, or production change.

---

## Purpose

The YTD regime replay established that the Phase 3 inversion (May 18–Jun 9) occurred
while the regime detector was offline (FORCED_UNKNOWN from a stale market_snapshot).
PIT-safe reconstruction shows all 16 Phase 3 dates should have been classified as BEAR.

This memo answers the decision-relevant follow-on:

> **If the regime detector had classified Phase 3 as BEAR, would the production
> top-30 rankings have been different — and would those different rankings have
> performed better?**

---

## Method

1. Read canonical frozen rankings.csv for each Phase 3 date (read-only — no modification).
2. Re-run `ranker_v2.score_snapshot()` on the canonical rows using the production
   `ranker_v2_model.json` and `feature_set=minimal_v2`.
3. Compare the corrected top-30 (sorted by re-computed `ranker_v2_score`) against the
   original top-30 (sorted by `actionable_rank` from canonical CSV).
4. Report IC and excess return from the existing PIT backtest (forward returns are fixed).

**What was NOT done:** The production freeze was not bypassed. Canonical snapshots were
not modified. No model, ranker, or selector code was changed. Output goes only to
`artifacts/autopsy/phase3_corrected_regime_replay/`.

---

## Key Architectural Finding

The production ranker in v1.4+ runs in `pairwise_minimal` mode:

```
final_score = ranker_v2_score
actionable_rank = rank(final_score DESC)
```

`ranker_v2_model.json` uses exactly two features:

| Feature | Module | Weight | Regime-dependent? |
|---------|--------|-------:|:-----------------:|
| `coinvest_score_z` | 4 (institutional) | +0.020 | No |
| `financial_score` | 2 (financial health) | −0.053 | No |

Both features are computed in modules 2 and 4, before the regime detection layer runs.
Z-scoring is within-cohort on the same raw values — also regime-independent.

**Consequence:** correcting the regime label from UNKNOWN to BEAR leaves
`coinvest_score_z` and `financial_score` unchanged, which means `ranker_v2_score`
and therefore `final_score` and `actionable_rank` are all unchanged.

---

## Results

### Top-30 overlap

| Metric | Value |
|--------|------:|
| Dates checked | 16/16 |
| Dates with identical top-30 | **16/16** |
| Rank-order changes | **0** |

**Every Phase 3 date: identical top-30 under corrected BEAR regime.**

### Phase 3 backtest performance (unchanged)

| Metric | Value |
|--------|------:|
| Mean IC / snapshot (5d) | **−0.048** |
| Mean top-20 excess return / snapshot (5d) | **−0.018** |
| Dates with IC data | 16 |

Because rankings are identical, performance is unchanged — the same forward returns
apply to the same names in the same positions.

---

## Interpretation

The corrected BEAR regime would have produced the same names in the same ranks.
The Phase 3 negative IC is **not** an artifact of the regime detector being offline.

The same names were held during a genuine BEAR period (XBI underperforming SPY by
5–14% over 30 days), and those names underperformed. That is stock-selection
underperformance in a risk-off environment, not a regime-input artifact.

**What this means for the investability verdict:**

The prior gate framed the question as: *"If the regime detector had been working,
would Phase 3 have looked better?"* The answer is no — correct BEAR inputs would
have produced the same rankings and the same returns.

This closes the regime-input alternative explanation. The Phase 3 inversion was
not caused by the regime detector being offline. It was caused by the model's
selected names underperforming in a BEAR environment.

---

## What This Does Not Change

1. **The backtest numbers.** Phase 3 mean IC = −0.048. This is unchanged and correct.

2. **The investment verdict.** The model is not yet cleared for capital scaling.
   The minimum bar (mean IC > 0.04 sustained, 55%+ windows positive, 6+ months
   clean evidence) is not yet met.

3. **The model code.** No ranker, selector, sizing, or pipeline change was made.

4. **The interpretation of Phase 3.** It is still a genuine underperformance period,
   now with the alternative explanation (regime-input contamination) ruled out.

---

## Updated Gate Status

| Gate | Status |
|------|--------|
| `PHASE_3_INVERSION_EXPLANATION_REQUIRED_BEFORE_CAPITAL_SCALE` | Regime-input alternative ruled out. Phase 3 is genuine stock-selection underperformance in BEAR. |
| `PHASE3_CORRECTED_REGIME_RANKING_REPLAY_DIAGNOSTIC_NO_MODEL_CHANGE` | **COMPLETE** — 16/16 dates identical. No performance improvement from corrected regime. |

**Next question (separate gate):** Is the model's BEAR underperformance structural
(i.e., does it always underperform in BEAR regardless of inputs), or is there a
gating mechanism that could avoid BEAR periods? That is a regime-gating question,
not a ranking-accuracy question, and requires a separate diagnostic.

---

## Artifacts

| File | Description |
|------|-------------|
| `phase3_corrected_regime_replay.json` | Full per-date comparison output |
| `PHASE3_CORRECTED_REGIME_REPLAY.md` | This memo |
| `inputs/<date>/canonical_reference.json` | Reference pointers (canonical not copied) |
| `rankings/<date>/rankings_comparison.json` | Per-date top-30 comparison |
| `tools/phase3_corrected_regime_replay.py` | Replay tool |
| `tests/test_phase3_corrected_regime_replay.py` | 30 tests, all passing |

---

## Governance Verdict

```
Classification:    PHASE3_CORRECTED_REGIME_RANKING_REPLAY_DIAGNOSTIC_NO_MODEL_CHANGE
Model change:      NO
Ranker change:     NO
Selector change:   NO
Snapshot write:    NO (output to artifacts/autopsy/ only)
Production wiring: NO

Corrected regime:              BEAR (16/16 Phase 3 dates)
Top-30 change under BEAR:      NONE (16/16 identical)
Performance change under BEAR: NONE (same rankings → same returns)

Conclusion:
  Phase 3 negative IC (mean −0.048) is genuine stock-selection underperformance
  during a BEAR period, not a regime-input artifact.
  The regime-input alternative explanation is RULED OUT.
  The investability gate is NOT YET CLEARED (minimum bar not met).
```
