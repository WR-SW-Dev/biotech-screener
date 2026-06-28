# Hermes Cron Policy

Governs registration, operation, and decommission of Hermes-managed cron jobs.

---

## Two cron systems (do not confuse)

| System | Config | Managed by |
|---|---|---|
| **Linux crontab** | `/var/spool/cron/...` or `crontab -e` | Operator; installed via `tools/install_agent_fleet_crontab.sh` |
| **Hermes cron** | Hermes internal scheduler | `hermes cron create/pause/resume/list` |

Hermes cron jobs are registered once on the operator host. They survive reboots
via Hermes's own persistence. Do not add them to Linux crontab.

---

## Hermes cron registration

```bash
# Create a Hermes cron job
hermes cron create "<cron-expr>" \
  --name "<job-name>" \
  --no-agent \
  --script <script-name>.sh \
  --workdir /mnt/c/Projects/biotech_screener/biotech-screener

# List all jobs
hermes cron list

# Pause (safe; does not delete job state)
hermes cron pause <job-name>

# Resume
hermes cron resume <job-name>

# Remove permanently
hermes cron delete <job-name>
```

**Note:** `hermes cron run <job-name>` and `hermes cron tick <job-name>` re-enable
paused jobs as a side effect. Do not use them on paused jobs.

---

## Authorization requirements

| Action | Authorization |
|---|---|
| Register new Hermes cron | Operator approval + `AGENT_REGISTRY.json` entry with `cron_enabled: true` |
| Pause Hermes cron | Operator-initiated only (not autonomous agents) |
| Resume Hermes cron | Operator-initiated only |
| Delete Hermes cron | Operator approval; update registry |
| Register Linux crontab entry | Edit `tools/install_agent_fleet_crontab.sh`; operator runs install |

---

## Registry requirement

Every Hermes cron job must have a corresponding entry in `AGENT_REGISTRY.json`:

```json
"<agent-id>": {
  "cron_enabled": true,
  "notes": "Hermes cron job ID: <job-id>"
}
```

If the job has no agent directory (uses `--no-agent`), add a Hermes-managed
entry comment block in `tools/install_agent_fleet_crontab.sh`:

```bash
# --- Hermes-managed cron (NOT Linux crontab — register once on host) ---
# <Description>: <schedule>
#   hermes cron create "<expr>" --name "<name>" --no-agent --script <script>.sh \
#     --workdir ${REPO_ROOT}
```

---

## Script requirements

Hermes cron wrapper scripts must:
1. Use a file lock to prevent overlapping runs
2. Log to `logs/<job-name>.log`
3. Write `artifacts/governance/<agent-id>/latest_heartbeat.json` after each run
4. Exit non-zero on CRITICAL failures
5. Respect the forbidden path list (see `docs/ops/hermes_permission_tiers.md`)

---

## Active Hermes cron jobs

| Job name | Schedule | Agent ID | Script |
|---|---|---|---|
| `hermes-skill-sync-guard` | Sun 08:00 ET | `hermes-skill-sync-agent` | `run_hermes_skill_sync_agent.sh` |

---

## Allowed Hermes cron behaviors

| Behavior | Allowed |
|---|---|
| Write own artifacts | Yes |
| Send Town notification | Yes (via `send_operator_event()`) |
| Commit to git | No — forbidden for autonomous cron |
| Push to remote | No — forbidden |
| Call write-trade MCP tools | No — forbidden |
| Spawn subagents that commit | No — forbidden |
| Modify frozen paths | No — forbidden |

---

## Decommission procedure

1. `hermes cron pause <job-name>` (keep paused for 1 week to confirm no dependencies)
2. `hermes cron delete <job-name>` after confirmation
3. Update `AGENT_REGISTRY.json`: `cron_enabled: false`
4. Remove job ID from `notes`
5. Update this file's Active Hermes cron jobs table

---

## References

- Skill sync guard example: `docs/ops/hermes_skill_sync.md` → Cron registration
- Registry: `agents/AGENT_REGISTRY.json`
- Town bridge: `docs/hermes_skills/town-operator-bridge.md`
- Scheduler incidents: memory `hermes_scheduler_paused_job_safety_2026_06_22.md`
