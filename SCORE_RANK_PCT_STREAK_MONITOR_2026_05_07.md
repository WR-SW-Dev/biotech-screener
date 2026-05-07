# score_rank_pct Streak Monitor — Governance Note
**Date**: 2026-05-07
**Author**: Hermes ops session

## Context

`score_rank_pct` WARN streak reached Day 3 on 2026-05-06:

| Day | Date | mean_ic | hit_rate | Verdict |
|-----|------|---------|----------|---------|
| 1 | 2026-05-04 | ≤ 0.0 | < 50% | WARN |
| 2 | 2026-05-05 | −0.0098 | 34.2% | WARN |
| 3 | 2026-05-06 | −0.0119 | 28.95% | WARN — ESCALATION |

WARN threshold: `mean_ic <= 0.0 AND hit_rate < 50%` (rolling 60-day, 20d horizon).
IC time series shows consistent negatives from mid-February onward; structural
degradation pattern, not a recent perturbation (n_dates=38, latest_ic=−0.0361
on 2026-04-08).

Governance cron `3d500ffb6032` (one-shot, Wed 22:00 ET) confirmed escalation
on 2026-05-06 22:04 ET. Output: `~/.hermes/cron/output/3d500ffb6032/2026-05-06_22-04-46.md`.

## Escalation Status

**SPEC_REQUIRED** — no model changes to `score_rank_pct` or any component
driving it may proceed until a Spec-style writeup (CRT+IC+PIT+Checklist v2)
is completed and logged under the governance framework.

## Monitoring

Hermes cron `4a96ad05405c` (`score-rank-pct-streak-monitor`) created 2026-05-07.
Schedule: 22:00 ET Mon–Fri, recurring forever.
Delivers to local (CLI). Reports streak status each trading day:
- STREAK BROKEN → Spec investigation can proceed with recovery data
- WARN Day N → SPEC_REQUIRED still active

The original one-shot cron (`3d500ffb6032`) is no longer in the Hermes scheduler.
The recurring cron above replaces it.

## Governance Rule

Score_rank_pct weight reduction requires CRT+IC+PIT+Checklist v2.
Do NOT suggest weight changes without that writeup.
