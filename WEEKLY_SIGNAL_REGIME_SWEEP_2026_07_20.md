# Weekly Signal Regime Sweep — 2026-07-20

**Dashboard:** 2026-07-17_dashboard.json | **Generated:** 2026-07-20
**Attention:** LOW

## Summary

**No signals at WARN/ALERT this week.** No comparator probes were run.

## Signal Status

| Signal | Health | Mean IC | Hit Rate | N Dates | Latest IC | Threshold |
|--------|--------|---------|----------|---------|-----------|-----------|
| score_rank_pct | HEALTHY | +0.0802 | 87.2% | 39 | +0.1233 | >0.03 = healthy |
| inst_delta_z | HEALTHY | +0.0680 | 100.0% | 27 | +0.2693 | >0.03 = healthy |

## Interpretation

- **score_rank_pct**: HEALTHY, mean_ic=+0.0802, well clear of the 0.03 healthy threshold. Rolling window shows a dip through early-mid June (single-date lows down to -0.1491 on 2026-06-08) but the series has recovered and the latest reading (+0.1233, 2026-06-17) is strong. Hit rate 87.2% — no WARN/ALERT trigger.
- **inst_delta_z**: HEALTHY, mean_ic=+0.0680, hit rate 100% across 27 dates, latest IC +0.2693 (2026-06-12) — trending up. Still carries zero selector weight per the 2026-05-04 governance action (zeroed in v1.14.0); dashboard HEALTHY classification does not imply active selector influence.
- **Dashboard attention = LOW**: No composite alert. Both load-bearing signals are HEALTHY — no shared-regime probe warranted this week.

## What This Does NOT Prove

- This sweep does NOT assess signals absent from the dashboard (`clinical_optionality_pct_dev`, `coinvest_score_z` are not present in the 2026-07-17 dashboard signals block, consistent with prior weeks — no visibility into whether these have insufficient data or were dropped from the build pipeline).
- `inst_delta_z` carrying HEALTHY dashboard status does not imply it is active in the selector — it remains zero-weighted per the 2026-05-04 governance action.
- The latest available dashboard snapshot is 2026-07-17 (no fresher dashboard.json found as of this run, 2026-07-20); this sweep is scoped to that snapshot.

## Provenance

- Source: `artifacts/ic_dashboard/2026-07-17_dashboard.json`
- Methodology: `scripts/shared_regime_check.py` (not invoked — no triggers met)
- Artifact: none produced this week (no comparator probe run — no WARN/ALERT signals)
- Cron job: weekly-signal-regime-sweep (idempotency check per WEEKLY_SIGNAL_REGIME_SWEEP_*.md 5-day window; prior run 2026-07-09, 11 days elapsed — within cadence for a new run)
