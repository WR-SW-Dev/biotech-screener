# IC Decomposition Readout — 2026-05-08

## What changed

Tool only. No model changes.

`tools/ic_decomposition.py` was added as a read-only diagnostic that joins
the forward-returns panel with per-snapshot rankings to compute Spearman IC
of `coinvest_score_z` vs `excess_return_5d`. Architecture is frozen;
this is attribution/observability work only.

## Pooled result

| Metric | Value |
|---|---|
| Signal | `coinvest_score_z` |
| Forward target | `excess_return_5d` (h5d, XBI-excess) |
| Snap dates | 14 (2026-04-14 → 2026-04-30) |
| Obs per date | ~297 tickers |
| Pooled IC | -0.031 |
| Pooled t-stat | -1.99 |
| IC hit rate | 28.6% |

Serial correlation from overlapping 5-day windows reduces effective N
substantially below 14. t-stat is **indicative only**, not promotion-grade.

## Contamination note

The April 21–25 window coincides with the broader XBI selloff (tariff
volatility) and the 04-25 cohort change (4 new managers added to
`elite_core`). IC during this cluster reached -0.14 (t ≈ -2.4) at its
worst — driven by market regime, not structural signal inversion.

Dates 04-23 and 04-24 are labeled "clean" by snap date but their 5-day
forward windows extend into the 04-25 cohort change; they carry some
contamination from both the selloff and the regime shift.

## Post-cohort result

| Window | n_dates | mean_IC | hit_rate |
|---|---|---|---|
| Pre-cohort-change (clean) | 9 | -0.051 | 11.1% |
| Post-cohort-change (contaminated) | 5 | -0.008 | 60.0% |

Post-cohort mean IC = **-0.008** (flat). The contaminated window's IC is
*better* than the pre-cohort window, which argues against signal inversion
as the explanation. The pre-cohort negativity is driven by the April
selloff cluster, not a systematic coinvest failure.

## Decision

**OBSERVE.**

No weight changes. No demotion. No retrain. No selector/ranker/module
modifications. The score_rank_pct degradation pattern does not meet the
5-element governed path required for demotion (two-frame evidence +
comparator probe + Spec-style writeup + operator sign-off + receipt).

## Non-actions (explicit)

- No change to `coinvest_score_z` selector weight (currently 100%)
- No change to `financial_score` or ranker weights
- No `inst_delta_z` re-promotion (quarantined through ≥2026-05-15)
- No new signal promoted from this result
- `catalyst_quality` segment cannot be evaluated until ≥5 forward-complete
  snapshots from 2026-05-08 onward accumulate (earliest: ~2026-05-15)

## Next checkpoint

**h20d = 2026-05-26.** Per the interp framework (locked 2026-04-28):

> HL Jaccard >0.70 coherent / <0.40 weak; rolling 3d/5d medians;
> persistence > returns; no tuning before h20d AND post-13F refresh.

The 13F refresh (~2026-05-15) must also land and clear quarantine before
any IC conclusion is drawn. Both gates must clear before acting.

## Governance reference

- Alpha stack frozen: `policy_alpha_freeze_2026_04_04.md`
- Architecture frozen: `policy_freeze_architecture_2026_04_19.md`
- Demotion path: `policy_demotion_path_2026_05_06.md`
- Interp framework: `interp_framework_forward_shadows_2026_04_28.md`
- Checklist v2 required for any promotion: FM + bootstrap + FDR + LOSO + year stab
