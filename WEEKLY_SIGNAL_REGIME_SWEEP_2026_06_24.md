# Weekly Signal Regime Sweep — 2026-06-24

**Dashboard:** 2026-06-23_dashboard.json | **Generated:** 2026-06-24 ~22:00 UTC
**Attention:** LOW

## Summary

**No signals at WARN/ALERT this week.** No comparator probes were run.

## Signal Status

| Signal | Health | Mean IC | Hit Rate | N Dates | Threshold |
|--------|--------|---------|----------|---------|-----------|
| score_rank_pct | HEALTHY | +0.0432 | 54.3% | 35 | >0.03 = healthy |
| inst_delta_z | WEAK | +0.0252 | 83.9% | 31 | 0.00–0.03 = weak |

## Interpretation

- **score_rank_pct**: Recovered from the SPEC_REQUIRED streak (was Day 3 at mean_ic=−0.0119 on 2026-05-06). Now solidly HEALTHY at +0.0432, well above the 0.03 threshold. The recovery trajectory from mid-April negatives through May positives has persisted.
- **inst_delta_z**: WEAK — mean_ic=+0.0252 is below the 0.03 healthy threshold but above 0.00 warn threshold. Hit rate is strong at 83.9%. This is a monitor-grade finding, not action-grade. The signal was zeroed in v1.14.0 (2026-05-04) due to a two-frame ALERT at mean_ic=−0.097; its current WEAK reading in the dashboard reflects post-governance behavior where the signal still appears in the 60d window but carries zero weight in the selector.
- **Dashboard attention = LOW**: No composite alert. No shared-regime probe warranted.

## What This Does NOT Prove

- This sweep does NOT assess signals absent from the dashboard (clinical_optionality_pct_dev, coinvest_score_z are not present in the 2026-06-23 dashboard — they may have been dropped from the build pipeline or have insufficient data).
- WEAK on inst_delta_z is not a comparator-probe finding — it's a dashboard-level classification. No probe was run because the trigger threshold is WARN/ALERT, not WEAK.

## Provenance

- Source: `artifacts/ic_dashboard/2026-06-23_dashboard.json`
- Methodology: `scripts/shared_regime_check.py` (not invoked — no triggers met)
- Artifact: `artifacts/ic_dashboard/2026-06-24_shared_regime_check.json`
- Cron job: weekly-signal-regime-sweep (Sunday)
