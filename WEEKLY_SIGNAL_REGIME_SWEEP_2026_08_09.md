# Weekly Signal Regime Sweep — 2026-08-09

**Dashboard:** 2026-08-07_dashboard.json | **Generated:** 2026-08-09

## Summary

**No signals at WARN/ALERT this week.** No comparator probes were run.

## Signal Status

| Signal | Health | Mean IC | Hit Rate | N Dates | Latest IC | Threshold |
|--------|--------|---------|----------|---------|-----------|-----------|
| score_rank_pct | HEALTHY | +0.0401 | 82.05% | 39 | +0.0354 | >0.03 = healthy |
| inst_delta_z | HEALTHY | +0.1280 | 100.0% | 27 | +0.0985 | >0.03 = healthy |

Dashboard `attention` field: **LOW**. Thresholds: healthy > 0.03, warn = 0.0, alert = -0.03.

## Interpretation

- **score_rank_pct**: HEALTHY, mean_ic=+0.0401, clear of the 0.03 threshold. Latest single-date IC +0.0354 (2026-07-09) is also above threshold — no negative-tail drift observed this cycle (contrast with the 2026-07-24 window, whose latest single-date IC had dipped to -0.0014). Hit rate 82.05% across 39 dates.
- **inst_delta_z**: HEALTHY, mean_ic=+0.1280, hit rate 100% across 27 dates, latest IC +0.0985 (2026-07-09). Still carries zero selector weight per the 2026-05-04 governance action (zeroed in v1.14.0); HEALTHY dashboard classification does not imply active selector influence.
- No load-bearing signal in the 2026-08-07 dashboard is at WARN or ALERT health. Per the sweep skill's trigger condition, no shared-regime comparator probes (`scripts/shared_regime_check.py`) were warranted this week.

## What This Does NOT Prove

- This sweep does NOT assess signals absent from the dashboard (`clinical_optionality_pct_dev`, `coinvest_score_z` are not present in the 2026-08-07 dashboard signals block, consistent with prior weeks — no visibility into whether these have insufficient data or were dropped from the build pipeline). Insufficient-data status for these two signals is UNKNOWN — flagged, not inferred.
- `inst_delta_z` carrying HEALTHY dashboard status does not imply it is active in the selector — it remains zero-weighted per the 2026-05-04 governance action.
- The latest available dashboard snapshot is 2026-08-07 (no fresher dashboard.json found as of this run, 2026-08-09; most recent per-date observation embedded in it is 2026-07-09 due to the 20-day forward-return horizon lag). This sweep is scoped to that snapshot.
- No production changes were made — this is a diagnose-only cron run per governance rule (no writes/commits/deploys without explicit operator authorization).

## Provenance

- Source: `artifacts/ic_dashboard/2026-08-07_dashboard.json`
- Methodology: `scripts/shared_regime_check.py` (not invoked — no triggers met)
- Artifact: none produced this week (no comparator probe run — no WARN/ALERT signals)
- Cron job: weekly-signal-regime-sweep (idempotency check per WEEKLY_SIGNAL_REGIME_SWEEP_*.md 5-day window; prior run 2026-07-28, 12 days elapsed — within cadence for a new run)
