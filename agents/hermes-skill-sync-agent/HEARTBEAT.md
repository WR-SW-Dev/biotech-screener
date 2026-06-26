# HEARTBEAT.md — Hermes Skill Sync Guard

## Schedule

Weekly Sunday 08:00 ET — Hermes cron job `hermes-skill-sync-guard`
(`no_agent`, script: `hermes_skill_sync_agent.sh`)

## Checklist

1. **Heartbeat current**: `artifacts/governance/hermes_skill_sync/latest_heartbeat.json`
   exists and `run_ts` is within 8 days.
   - If file missing → STALE (cron never fired)
   - If `run_ts` older than 10 days → MONITORING_FAIL

2. **Status field**: heartbeat `status` must be `OK` or `DRIFT_WARNING`
   - `DRIFT_CRITICAL` → MONITORING_FAIL: retired references in canonical skill sources
   - `ERROR` → MONITORING_FAIL: sync tool failed to load or run

3. **CRITICAL drift zero**: `n_critical == 0`
   - Any `n_critical > 0` → MONITORING_FAIL

4. **Sync cap respected** (only when `sync_ran == true`):
   - `sync_files_changed` must contain ≤ 3 entries
   - More than 3 → MONITORING_WARN (cap enforcement may have failed)

Reply `HEARTBEAT_OK` only when all checks clear.

## Status codes

- `HEARTBEAT_OK` — heartbeat current, `n_critical == 0`, no governance violations
- `STALE` — heartbeat file missing or `run_ts` older than 8 days
- `MONITORING_WARN` — `n_warning > 0` or sync cap anomaly
- `MONITORING_FAIL` — `DRIFT_CRITICAL` or `ERROR` status; heartbeat older than 10 days

## Cron registration

Do not use Linux crontab directly. Register via Hermes cron:

```bash
hermes cron add \
  --name "hermes-skill-sync-guard" \
  --schedule "0 8 * * 0" \
  --no-agent \
  --script hermes_skill_sync_agent.sh \
  --workdir /mnt/c/Projects/biotech_screener/biotech-screener
```

Hermes script entry point: `~/.hermes/scripts/hermes_skill_sync_agent.sh`
Repo wrapper: `scripts/run_hermes_skill_sync_agent.sh`
Audit tool: `tools/hermes_skill_sync_audit.py`
