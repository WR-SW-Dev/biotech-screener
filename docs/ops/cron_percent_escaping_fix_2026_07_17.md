# Linux crontab `%`-escaping bug — fixed 2026-07-17

## Symptom

`tools/build_event_feedback.py` (17:45 M-F) and `tools/build_policy_shadow_compare.py`
(18:05 M-F) produced no new log output or artifacts for days, with no error visible
anywhere. `tools/production_qa_check.py` (17:35 M-F) and
`tools/build_event_feedback_metrics.py` (14:30 Fri) had the same latent defect.

## Root cause

Each affected crontab line embedded `$(date +%Y-%m-%d)` with an **unescaped `%`**.
In crontab syntax, an unescaped `%` is converted to a newline, and cron truncates
the executed command at the first `%` — passing everything after it (including
the `>> log 2>&1` redirect) as stdin instead of command text. The truncated
command is a shell syntax error (unclosed `$(...)`); the resulting stderr goes to
cron's default mail delivery, which is silently discarded because no MTA is
installed on the operator host:

```
CRON[...]: (arrenchulz) CMD (cd .../biotech-screener && /usr/bin/python3 tools/build_event_feedback.py --as-of-date $(date +)
CRON[...]: (CRON) info (No MTA installed, discarding output)
```

Net effect: the python scripts never actually ran. A manual run of the same
command (with `%` typed normally in an interactive shell, where it needs no
escaping) always succeeded, which is what made this look environmental rather
than a crontab syntax bug.

## Fix

Escaped `%` as `\%` in the four affected lines (`$(date +%Y-%m-%d)` →
`$(date +\%Y-\%m-\%d)`), matching the pattern already used correctly by other
entries in the same crontab (`build_rank_change_monitor.py`,
`build_universe_maintenance.py`, etc.). Applied directly via `crontab` on the
operator host (not tracked by this repo's install scripts — see caveat below);
backup of the prior crontab was taken before editing.

## Related fix same day

The LG3 scientific-cartography scheduled review (`5 8 * * *`,
`tools/run_scientific_cartography_scheduled_review.py --auto-run-latest`) logged
to `/tmp/lg3_cron.log`, which doesn't survive WSL restarts. Redirected to
`logs/lg3_scheduled_review.log` for persistence. This job's stale
`as_of_date=2026-06-23` is expected, separate behavior — no new dated snapshot
has existed under `artifacts/scientific_cartography/` since Phases 3-13C
concluded; the job is read-only/diagnostic/non-blocking by design and correctly
finds nothing newer.

## Caveat — crontab is not version-controlled

The live Linux crontab on the operator host is not fully represented by
`tools/install_agent_fleet_crontab.sh` (that script is a partial, already-stale
reference — several production jobs, including all four fixed here, are not
listed in it). This doc records the fix for posterity; it does not by itself
prevent the same class of bug in future manually-added crontab lines. Any new
entry using `$(date +...)` must escape every `%` as `\%`.
