# Ranker v2 Cohort Stability Audit — 2026-04-26

**Trigger:** ERAS dropped from `actionable_rank=16` (snapshot 2026-04-24) to
`actionable_rank=63` (snapshot 2026-04-25) overnight. Composite_score, tier_any,
and catalyst_days were essentially unchanged. Audit goal: identify whether this
is a real-signal change, a ranker pipeline bug, or expected boundary noise.

**Verdict:** **Expected boundary noise, not a regression.** ERAS sat on the
v2 cohort cutoff for a week and a 5% selector_score dip pushed it below the
60-name cut. Five other names experienced the same dislocation the same day.

## How v2 cohort selection works

```text
ranker_v2_pairwise.filter_cohort()
  cohort = top-60 by selector_score (descending)
         ∩ eligible == 1
         ∩ (catalyst_in_window OR catalyst_days ∈ [1, 120])
```

Pre-v2 `actionable_rank` is set in `run_screen.py:5089-5096` by sorting
`_eligible_for_selector` on `selector_score` descending. `filter_cohort` then
keeps the top 60. The remaining ~160 eligible names get
`final_score = selector_score × 0.0001` and sort below the cohort.

`cohort_top_n = 60` (`ranker_v2_pairwise.py:152`).

## ERAS day-over-day trajectory

| date | pre-v2 rank (selector) | selector_score | cohort cut@60 | ranker_v2_rank | actionable_rank |
|---|---:|---:|---:|---:|---:|
| 2026-04-20 | 49 | 0.7922 | 0.7446 | 17 | 17 |
| 2026-04-21 | 56 | 0.7534 | 0.7354 | 15 | 15 |
| 2026-04-22 | 60 | 0.7401 | 0.7401 (=ERAS) | 17 | 17 |
| 2026-04-23 | 56 | 0.7556 | 0.7378 | 17 | 17 |
| 2026-04-24 | 55 | 0.7578 | 0.7354 | 16 | 16 |
| **2026-04-25** | **63** | **0.7182** | **0.7318 (KNSA)** | **— (out)** | **63** |

Selector_score dropped 5.2% (0.7578 → 0.7182), enough to fall below the cut
sitting at 0.7318. Composite_score (0.0599), tier_any (A), catalyst_days (37),
and alpha_cohort_pct (0.557) were stable or improved — only the selector_score
moved. Once outside the cohort:
- `ranker_v2_score` blank
- `final_score = 0.7182 × 0.0001 ≈ 7.18e-5`
- AR=63 reflects 3rd position among non-cohort eligibles (BIIB at 61, XNCR at 62)

## Cohort churn — past two weeks

| date | cohort_n | left | joined | ERAS in cohort? |
|---|---:|---:|---:|---|
| 2026-04-13 | 60 | — | — | yes |
| 2026-04-14 | 60 | 2 | 2 | **out** |
| 2026-04-15 | 60 | **6** | **6** | back in |
| 2026-04-16 | 60 | 0 | 0 | yes |
| 2026-04-17 | 60 | 2 | 2 | yes |
| 2026-04-20 | 60 | 3 | 3 | yes |
| 2026-04-21 | 60 | 3 | 3 | yes |
| 2026-04-22 | 60 | 2 | 2 | yes |
| 2026-04-23 | 60 | 2 | 2 | yes |
| 2026-04-24 | 60 | 1 | 1 | yes |
| **2026-04-25** | **60** | **6** | **6** | **out** |

Typical churn: 0-3 names/day (0-5%). Two outliers at 10% churn — 04-15 and
04-25, suggesting periodic re-shuffles when multiple borderline names move
simultaneously. ERAS has now flapped in/out **three times in 13 days**.

## 2026-04-25 cohort delta

```text
Left  cohort: ABSI, BIIB, ERAS, SLN, TARS, XNCR
Joined cohort: KNSA, MBX, NRIX, PCVX, SNDX, ZYME
```

All six departures were borderline names (selector ranks 50-60 the day prior).
None had material composite_score, tier, or catalyst-day moves; all show <10%
selector_score dips that crossed the 0.73 cohort cut.

## Implications

1. **Reported `actionable_rank` is bistable for borderline names.** A name with
   selector_score within ~5% of the cut@60 boundary will routinely flip in/out
   of the cohort, producing AR moves of 40-50 positions despite no real signal
   change. ERAS is a textbook example.

2. **The cohort cutoff value is nearly stationary.** Cut@60 has been
   0.7318-0.7446 for the past 11 days. A name needs to be solidly above ~0.74
   to be cohort-stable.

3. **Top-30 (DEM) is unaffected.** All DEM positions had v2 scores well clear
   of the cut. The boundary churn lives at AR=50-65, not AR=1-30.

4. **No bug, no regression.** The pipeline is doing what it's designed to do.
   The `cohort_top_n=60` hard cut creates this boundary noise by construction.

## Suggested follow-ups (not implemented)

1. **Add `cohort_membership_streak` column.** Number of consecutive snapshots
   the name has been in/out of the v2 cohort. Makes flapping immediately
   visible in `rankings.csv` without snapshot-diff analysis.

2. **Soft-cohort hysteresis option.** Names within ~2-5% of the cut on either
   side could carry forward yesterday's cohort status to dampen flapping.
   Alpha-impact unknown; would need a Checklist v2 evaluation before promotion.

3. **Diagnostic alert** when cohort churn ≥10% in one snapshot (today's threshold).
   Two such events in 13 days warrants attention even if each is benign.

These are optional; none are required to fix today's observation.
