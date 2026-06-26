# USER.md — EES v3 Veto Monitor

## What to do when Veto Watch alarms

**MONITORING_OK**: No action. Shadow evidence accumulating normally.

**MONITORING_OK_REQUIRES_OPERATOR_REVIEW**: Shadow gate is MET and cumulative 20d alpha
is strong (>+5%). This is not automatic promotion. Read the freeze-lift review memo at
`artifacts/readiness/EES_V3_FREEZE_LIFT_REVIEW_MEMO_2026_06_25.md` and initiate a review
if you are satisfied with the evidence.

**MONITORING_WARN**: Check warnings in the daily JSON card. Common causes:
- `n_vetoed == 0`: EES v3 scores may be missing from today's snapshot — check data pipeline.
- `veto_rate > 30%`: Unusually broad veto — check if universe composition changed.
- `no_options_coverage` dominant: Expected in low-coverage snapshots; monitor as coverage expands.
- `catalyst_too_far >= 3`: Check vetoed names for far-out catalyst timing; these are false-negative risk.

**MONITORING_FAIL**: Investigate immediately.
- If freeze appears lifted: halt any downstream changes; confirm with operator.
- If EES v3 appears in `final_score`: `git diff run_screen.py` — confirm no unauthorized edits.
- If production files changed: check `git log --oneline -5` and review last commit.

**DATA_UNAVAILABLE**: Today's snapshot may not have generated or `ees_v3_score` field is absent.
Check `data/snapshots/{today}/rankings.csv` and re-run production if needed.

**INSUFFICIENT_FORWARD_OBSERVATIONS**: Normal pre-gate state — shadow ledger has cards but not
enough settled 20d windows. No action; continue daily runs.

## Manual dry run

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python3 scripts/research/ees_v3_raw_veto_shadow_card.py --as-of-date 2026-06-25
```

## Cron activation

Cron is **not enabled**. To enable after operator review:
1. Operator confirms dry run artifacts are correct.
2. Operator explicitly approves scheduling.
3. Add to crontab after production snapshot (after ~17:30 ET).
4. Agent must remain read-only on activation.
