# Weekly Signal Regime Sweep — 2026-07-28

**Dashboard:** 2026-07-24_dashboard.json | **Generated:** 2026-07-28

## Summary

**No signals at WARN/ALERT this week.** No comparator probes were run.

## Signal Status

| Signal | Health | Mean IC | Hit Rate | N Dates | Latest IC | Threshold |
|--------|--------|---------|----------|---------|-----------|-----------|
| score_rank_pct | HEALTHY | +0.0775 | 84.6% | 39 | -0.0014 | >0.03 = healthy |
| inst_delta_z | HEALTHY | +0.0930 | 100.0% | 27 | +0.1349 | >0.03 = healthy |

Dashboard `attention` field: **LOW**. Thresholds: healthy > 0.03, warn = 0.0, alert = -0.03.

## Interpretation

- **score_rank_pct**: HEALTHY, mean_ic=+0.0775, clear of the 0.03 threshold. Latest single-date IC (-0.0014, 2026-06-25) sits in negative/WARN-band territory, but this is one observation inside a rolling window whose mean remains strongly positive and hit rate is 84.6% — no sustained WARN/ALERT trigger at the aggregate level, consistent with the same late-May/early-June dip already noted in the prior (2026-07-20) sweep having partially reasserted itself at the tail of the window. Flagging for awareness, not action: latest_ic alone would sit below the WARN threshold (0.0) if it persists next week.
- **inst_delta_z**: HEALTHY, mean_ic=+0.0930, hit rate 100% across 27 dates, latest IC +0.1349 (2026-06-25). Still carries zero selector weight per the 2026-05-04 governance action (zeroed in v1.14.0); HEALTHY dashboard classification does not imply active selector influence.
- No load-bearing signal in the 2026-07-24 dashboard is at WARN or ALERT health. Per the sweep skill's trigger condition, no shared-regime comparator probes were warranted this week.

## What This Does NOT Prove

- This sweep does NOT assess signals absent from the dashboard (`clinical_optionality_pct_dev`, `coinvest_score_z` are not present in the 2026-07-24 dashboard signals block, consistent with prior weeks — no visibility into whether these have insufficient data or were dropped from the build pipeline).
- `inst_delta_z` carrying HEALTHY dashboard status does not imply it is active in the selector — it remains zero-weighted per the 2026-05-04 governance action.
- The latest available dashboard snapshot is 2026-07-24 (no fresher dashboard.json found as of this run, 2026-07-28); this sweep is scoped to that snapshot.
- score_rank_pct's negative latest single-date IC is noted but not diagnosed — a single-date dip does not meet the WARN/ALERT trigger threshold used by this skill (which gates on the dashboard's aggregated `health` field, not the single latest observation).

## Provenance

- Source: `artifacts/ic_dashboard/2026-07-24_dashboard.json`
- Methodology: `scripts/shared_regime_check.py` (not invoked — no triggers met)
- Artifact: none produced this week (no comparator probe run — no WARN/ALERT signals)
- Cron job: weekly-signal-regime-sweep (idempotency check per WEEKLY_SIGNAL_REGIME_SWEEP_*.md 5-day window; prior run 2026-07-20, 8 days elapsed — within cadence for a new run)
