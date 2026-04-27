# Spec 066 — Ranker v2 Cohort Hysteresis (2026-04-26)

**Status:** Spec only. **No production code changes from this document.**
**Author:** drafted 2026-04-26 following `artifacts/ranker_v2_cohort_audit_2026-04-26.md`.
**Constraint:** alpha-stack is frozen per `policy_alpha_freeze_2026_04_04.md`. Promotion of any code change here requires a Checklist v2 evaluation.

## 0. Why this spec exists

The 2026-04-26 cohort audit found ERAS dropped from `actionable_rank=16` to `63` overnight on 2026-04-25 — driven by a 5.2% selector_score dip that crossed the `cohort_top_n=60` cut. Five other names dislocated the same day; ERAS has flapped in/out of the v2 cohort three times in 13 days. The hard cut at 60 produces structural in/out flapping for any name with selector_score within ~5% of the cut value (currently ~0.73).

This spec proposes a **soft-cohort hysteresis** that would carry forward yesterday's cohort status for borderline names, dampening the flapping. It is **not approved for code yet** — it would alter which names get a v2 score, which is an alpha-affecting change subject to the alpha freeze.

## 1. Proposed change (NOT to be implemented from this spec)

Replace the strict top-60 cut with a hysteresis band:

```
if rank_by_selector <= 60:
    in_cohort = True                              # unconditional admit
elif rank_by_selector <= 60 + N_buffer AND was_in_cohort_yesterday:
    in_cohort = True                              # carry forward
else:
    in_cohort = False
```

Or equivalently in selector_score space:

```
admit_threshold = cut_score_at_position_60        # current behavior
keep_threshold  = admit_threshold * (1 - hysteresis_pct)   # 2-5%
```

A name above `admit_threshold` joins. A name above `keep_threshold` *and* in the cohort yesterday stays. A name below `keep_threshold` always drops.

Default proposal: `hysteresis_pct = 3%`, `N_buffer = 6` (10% buffer on a 60-name cohort). Both knobs configurable via `RankerV2Config`.

## 2. What this spec is NOT

- It is **not** a behind-flag deployment. Even shadow-only flag wiring would change `rankings.csv` columns or sidecar artifacts in ways the alpha-freeze policy treats as material; per `policy_freeze_architecture_2026_04_19.md` we are studying *live* behavior, not adding new behavior.
- It is **not** a Checklist v2 evaluation. This document only defines the experiment that a future evaluation must run.
- It does **not** modify `cohort_top_n=60`. The hard top-60 admit boundary is preserved; hysteresis only governs the *exit* condition.

## 3. Pre-promotion requirements (Checklist v2)

Before any code change implementing this spec:

1. **FM ratio (Forward Monitor)** — score the proposed cohort on the same forward-return panel used for the current ranker. Must beat the strict-cut baseline by ≥1 standardized unit on net-of-cost forward return.
2. **Bootstrap** — block-bootstrap (≥1000 reps) the FM gap; the lower 5%ile must remain positive.
3. **FDR** — pre-register the test as one comparison; no peeking across hysteresis_pct values.
4. **LOSO** — leave-one-snapshot-out cross-validation across the available shadow window; the gap must be stable across folds.
5. **Year stability** — pre-2025 vs 2025-26 splits must each show non-negative gaps.

The five gates match the standard set from `policy_alpha_freeze_2026_04_04.md`. None can be skipped.

## 4. Counter-evidence to address explicitly

Hysteresis has known failure modes that the evaluation must rule out:

- **Stickiness on declining names.** A name dropping out of the cohort due to a real signal deterioration (not boundary noise) gets one extra day of inclusion. If those names have negative forward returns, hysteresis is alpha-negative.
- **Asymmetric churn.** If declines into the cohort are rarer than declines out, hysteresis preferentially keeps weaker names. Check via per-direction streak analysis on shadow data.
- **Cohort-rank distortion.** Names entering via hysteresis are by definition below the strict cut; their v2 score will tend to sort them at the cohort tail (positions 55-60). DEM (top-30) should be unaffected unless v2 rank-ordering drifts materially.

## 5. Design knobs

| Knob | Default proposal | Alternative |
|---|---|---|
| `hysteresis_pct` | 3% | 2%, 5% — sweep in evaluation |
| `N_buffer` (selector-rank space) | 6 names | 10 names |
| Apply to: enter only / exit only / both | exit only | both |
| Tie-break when `was_in_yesterday` is undefined (first run) | strict cut | — |

Recommend evaluating **exit-only** because the original goal is to dampen flap-out, not to admit fresh names below the cut.

## 6. Evaluation experiment design

1. Take the most recent N=90 snapshots (or however many are available with v2 scores populated).
2. For each snapshot, compute three cohorts:
   - **A (strict)**: current production rule — top-60 by selector.
   - **B (hysteresis-3%-exit)**: the proposed rule.
   - **C (hysteresis-5%-exit)**: a wider variant.
3. For each cohort, score forward returns at 5d / 21d / 63d horizons.
4. Run all five Checklist v2 gates on (B - A) and (C - A) gaps.
5. Decide promotion only if **at least one variant clears all five gates**.

Any variant that clears all five may be promoted to a behind-flag shadow under a follow-up spec; this spec does not authorize the flag wiring itself.

## 7. Out-of-scope

- Modifying `cohort_top_n` itself.
- Changing the selector_score formula or the v2 model weights.
- Soft cohort rules based on signals other than yesterday's membership (e.g. catalyst proximity, tier_any). These are separate hypotheses.

## 8. Decision log

- 2026-04-26: spec drafted following ERAS audit. **Not approved for code**. Promotion requires Checklist v2 + this evaluation pre-registered before running.
