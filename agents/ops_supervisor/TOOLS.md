# TOOLS.md — Ops Supervisor Commands

## Daily supervisor run

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
python3 agents/ops_supervisor/supervisor.py --as-of 2026-04-28
```

## Force current hour (for testing)

```bash
python3 agents/ops_supervisor/supervisor.py --as-of 2026-04-28 --force-now-hour 22
```

## Read latest verdict

```bash
# Machine-readable
cat artifacts/ops_supervisor/YYYY-MM-DD_supervisor.json | head -100

# Human-readable markdown
cat artifacts/ops_supervisor/YYYY-MM-DD_supervisor.md | less

# Pretty JSON
python3 -m json.tool artifacts/ops_supervisor/YYYY-MM-DD_supervisor.json | less
```

## Check supervisor inputs

Required files must exist before supervisor runs:

```bash
# Heartbeat signals
cat artifacts/heartbeat/YYYY-MM-DD_anomalies.md

# Production digest
cat artifacts/ops_digest/YYYY-MM-DD_digest.json

# Rankings snapshot
head artifacts/ops_digest/YYYY-MM-DD_digest.md

# Run manifest
cat data/snapshots/YYYY-MM-DD/run_manifest.json | head -50

# Prior supervisor verdict
cat artifacts/ops_supervisor/$(date -d 'yesterday' +%Y-%m-%d)_supervisor.json | head -30
```

## Reading the verdict

Output artifacts:
- Machine-readable: `artifacts/ops_supervisor/{as_of_date}_supervisor.json`
- Human-readable: `artifacts/ops_supervisor/{as_of_date}_supervisor.md`

Key fields:
- `final_severity`: GREEN / YELLOW / ORANGE / RED
- `final_action`: no_action / watch / investigate / fix_now
- `anomalies`: Array of classified issues
  - Each anomaly has: id, raw_status, classification, supervisor_severity, reason
- `input_status`: Status of all upstream inputs (found / missing / malformed)

## Severity meanings

| Severity | Action |
|----------|--------|
| GREEN | No action. All agents healthy. |
| YELLOW | Watch only. Known/expected/carried issues. |
| ORANGE | Investigate. New anomaly or known issue persisting past expected resolution. |
| RED | Fix now. Production failure or required artifact missing after due time. |

## Exception table

The canonical source of known exceptions is embedded in `supervisor.py`:

- **`inst_delta_z_signal_alert`**: YELLOW until 2026-05-15
- **`calibration_evidence_stale`**: YELLOW until 2026-05-01, then ORANGE if persists
- **`phase2_fail_carried`**: YELLOW unless decision_diff materially worsens
- **`shadow_monitor_perf_alert`**: WARN treated as YELLOW
- **`massive_paused`**: SUPPRESS (license downgrade)
- **Retired agents**: SUPPRESS (`shadow_watch`, `company_news_ingest`)

## Cron schedule

```
20:30 ET  weekdays  → Run supervisor
20:40 ET  weekdays  → Run sentinel (verify supervisor ran)
```

## Red lines

- Never auto-fix anomalies
- Never restart agents
- Never modify the exception table at runtime
- Never mutate production data or artifacts
- Do not edit the supervisor script logic
