# Weekly Signal Regime Sweep — 2026-07-09

**Dashboard:** 2026-07-09_dashboard.json | **Generated:** 2026-07-09
**Attention:** LOW

## Summary

**No signals at WARN/ALERT this week.** No comparator probes were run.

## Signal Status

| Signal | Health | Mean IC | Hit Rate | N Dates | Threshold |
|--------|--------|---------|----------|---------|-----------|
| score_rank_pct | HEALTHY | +0.0901 | 88.6% | 35 | >0.03 = healthy |
| inst_delta_z | HEALTHY | +0.0533 | 96.7% | 30 | >0.03 = healthy |

## Interpretation

- **score_rank_pct**: HEALTHY, mean_ic=+0.0901, well above the 0.03 threshold. Latest single-date IC (-0.0216, 2026-06-05) is negative but the rolling mean and hit rate (88.6%) remain strong — no WARN/ALERT trigger.
- **inst_delta_z**: HEALTHY, mean_ic=+0.0533, up from the WEAK reading (+0.0252) recorded on 2026-06-24. Hit rate is very strong at 96.7%. Continues to recover post-governance (zeroed in v1.14.0, 2026-05-04) — dashboard-level classification only, this signal still carries zero selector weight regardless of dashboard health label.
- **Dashboard attention = LOW**: No composite alert. No shared-regime probe warranted — both load-bearing signals are HEALTHY.

## What This Does NOT Prove

- This sweep does NOT assess signals absent from the dashboard (clinical_optionality_pct_dev, coinvest_score_z are not present in the 2026-07-09 dashboard signals block — consistent with prior weeks' absence; still no visibility into whether these have insufficient data or were dropped from the build pipeline).
- inst_delta_z carrying HEALTHY dashboard status does not imply it is active in the selector — it remains zero-weighted per the 2026-05-04 governance action.

## Provenance

- Source: `artifacts/ic_dashboard/2026-07-09_dashboard.json`
- Methodology: `scripts/shared_regime_check.py` (not invoked — no triggers met)
- Artifact: `artifacts/ic_dashboard/2026-07-09_shared_regime_check.json`
- Cron job: weekly-signal-regime-sweep (Thursday, idempotency check per WEEKLY_SIGNAL_REGIME_SWEEP_*.md 5-day window)
