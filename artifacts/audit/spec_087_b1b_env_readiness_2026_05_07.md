# Spec 087 B1b — Env-Readiness Finding (2026-05-07)

**Phase**: B1b prerequisite #1
**Mode**: read-only; no commits, installs, secrets printed, or production reruns
**Predecessor**: B1a shipped at `ae702bf2`; manual producer run completed at 09:30 EDT logged "MASSIVE_API_KEY is not set" warnings

## Bottom line

**B1b env prerequisite is CLEARED.** All three required keys are now present in `.env`. Both env-loading paths in use (`source .env` and the wrapper's python-dotenv-style parser) load them identically. The 09:30 producer warnings reflect a pre-09:44 state; `.env` was updated by the operator at 09:44:03 EDT, **after** that run completed.

## Evidence

### Key presence (lengths only — values never printed)

| Key | Status | Length |
|---|---|---|
| `MASSIVE_API_KEY` | set | 32 |
| `MASSIVE_S3_ACCESS_KEY_ID` | set | 36 |
| `MASSIVE_S3_SECRET_ACCESS_KEY` | set | 32 |

Both env-loading paths verified:
- **`source .env 2>/dev/null`** (used by the manual producer command and by the proposed B1b cron line): loads all 3 keys with the lengths above.
- **Python-dotenv-style parser** (used by `tools/cron_daily_production.sh:91–103`): loads all 3 keys with identical lengths.

### Timeline confirms the 09:30 warnings are stale

| Event | Time (EDT) | Source |
|---|---|---|
| Manual producer run completed | 2026-05-07 09:30 | `output/hedge_report/hedge_report_2026-05-07.json` mtime |
| Producer log "MASSIVE_API_KEY is not set" | 2026-05-07 09:30 | `bh65ta8qx` task output |
| `.env` modified to add the keys | 2026-05-07 09:44:03 | `stat .env` Modify time |

The 09:30 producer warnings were a snapshot of pre-09:44 env state. They are no longer reproducible.

## Operator decision-rule mapping

> If keys are present and loaded: B1b env prerequisite passes.

**This branch fires.** B1b env prerequisite passes. Cron line as currently drafted in the spec (uses `source .env 2>/dev/null`) is sufficient.

## Validation gap (worth a Phase B1b in-flight check)

We have **not** yet observed a producer run actually using these keys against live endpoints. Confirmation requires a producer run executed after 09:44:03 EDT. Two options to close this:

1. **Validate during B1b cron's first-fire** — install the cron and watch the first Friday's `logs/biotech_hedge_report.log` for "Options source: massive (auto: tastytrade unavailable; massive selected)" instead of "realized_vol". If Massive selection works, S3 day aggs should also load successfully (same credentials envelope).
2. **One additional manual run pre-cron** — re-run the same approved command from 09:30 EDT against today's portfolio CSV. Would confirm live keys work but mutates `output/hedge_report/` again. **NOT requesting this** — see decision below.

**Recommendation**: validate during B1b's first scheduled run. The risk of installing the cron and finding live endpoints fail is small — both endpoints would fall back to `realized_vol_proxy` / BS pricing, the same degraded path the morning run already produced cleanly. Worst case is one Friday with degraded-pricing output, which is recoverable.

## Three sub-checks completed

### 1. Env-readiness — PASS

Both keys present, both loading paths work.

### 2. `data/snapshots/resolutions/watchlist_current.json` disposition — leave uncommitted

The diff is unambiguously normal daily-production wrapper output:

- `as_of_date`: 2026-05-05 → 2026-05-07 (rolled forward 2 days)
- `n_watchlist`: 7 → 10 (3 more upcoming catalysts)
- `n_resolved_today`: 1 → 7 (more catalysts resolved today)
- `n_existing`: 119 → 120
- Watchlist entries refreshed with current names and dates

This file is tracked in git but is rewritten on each daily-production run. Not in scope for any Spec 087 commit. **Per operator's rule: leave uncommitted.** The next operator-driven commit (or scheduled artifact-tracking job) will pick it up.

### 3. Alerts commits sanity — PASS all three criteria

Commits inspected: `0e9851c2` (`common/alerts.py` + 23 tests) and `5a9fdb8b` (3 hook points wired).

| Criterion | Result | Evidence |
|---|---|---|
| No Telegram token hardcoded | ✅ PASS | regex `\d{8,10}:[A-Za-z0-9_-]{35}` (Telegram bot-token shape) returns no matches in `common/alerts.py`; token resolved via `os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()` |
| Missing env doesn't crash production | ✅ PASS | `send_operator_alert` returns `False` (does not raise) when `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` is unset (verified in `tests/test_operator_alerts.py`: `test_missing_token_returns_false`, `test_missing_chat_id_returns_false`); each hook site wraps the call in `try/except Exception → logger.debug("Operator alert skipped: %s", ...)` |
| Alert failures don't turn PASS/WARN into FAIL | ✅ PASS | hook points fire **after** gate-result accumulation in `run_daily()` and as a side-effect in `run_screen.py`; alert call site uses its own `try/except`; no path mutates `gate_results` or `screen_proc.returncode` based on alert outcome |

Alert hook in `run_screen.py:12424–12442` fires only on the STALE branch of B0; with B1b's producer restored and weekly cron firing, freshness flips to FRESH and the alert won't fire. Well-scoped.

## What stays held

- B1b cron install (waiting on operator decision after this memo)
- `bioshort_watch` LLM reactivation
- B2 dashboard envelope
- 087C alpha shadow research
- Manual `run_screen.py` invocation
- `output/hedge_report/` mutation (no further runs without explicit approval)

## Recommended next decision

B1b env prerequisite #1 is cleared. Watchlist disposition #2 is settled (leave uncommitted). Alerts commits do not block B1b.

You may now choose:

1. **Approve B1b cron install** with the cron line drafted in the spec (uses `source .env`, dedicated `logs/biotech_hedge_report.log`); validate during first Friday fire.
2. **Hold B1b further** and run one validation producer run first (mutates `output/hedge_report/` again — would write `hedge_report_2026-05-07.json` with mtime > 09:44 to confirm live Massive integration).
3. **Switch the cron line** to use the wrapper's robust python-dotenv-style parser instead of `source .env`. Functionally equivalent today (both produce identical lengths) but more defensive against future `.env` values containing shell-special characters.

My read: option 1 is fine; option 3 is a marginal improvement worth bundling later if any other env brittleness surfaces.

---

_Generated 2026-05-07 as Spec 087 B1b read-only env-readiness finding. No code, cron, or artifact changes made beyond writing this memo._
