# Hermes Skill Sync Guard — Runbook

Agent: `hermes-skill-sync-agent`  
Cron job: `hermes-skill-sync-guard` (Hermes cron, Sun 08:00 ET)  
Registry: `agents/AGENT_REGISTRY.json` → `hermes-skill-sync-agent`

---

## Authority model

| Layer | Role |
|---|---|
| `skills/*/SKILL.md` | **Canonical source.** Edit here. |
| `docs/hermes_skills/*.md` | **Generated mirror.** Do not hand-edit; regenerate via sync tool. |
| `~/.hermes/skills/` | Hermes runtime copy. Copy from `docs/hermes_skills/` only when gateway reads runtime copies. |
| Town | **Observer and reviewer only.** No autonomous writeback to `skills/` or `docs/hermes_skills/`. |

> Mirror edits can be overwritten by the next sync run. All durable fixes belong in `skills/*/SKILL.md`.

---

## Files

| File | Purpose |
|---|---|
| `tools/hermes_skill_sync_audit.py` | 3-mode audit/check/sync tool |
| `tools/sync_hermes_skills.py` | Official mirror regeneration path |
| `scripts/run_hermes_skill_sync_agent.sh` | Hermes cron wrapper (lock + log + fail-closed) |
| `agents/hermes-skill-sync-agent/HEARTBEAT.md` | Heartbeat protocol |
| `artifacts/governance/hermes_skill_sync/latest_heartbeat.json` | Latest run status |
| `artifacts/governance/hermes_skill_sync/hermes_skill_sync_YYYY_MM_DD.md` | Per-run audit report |
| `docs/hermes_skills/_meta.json` | Skill registry (source of truth for sync maps) |

---

## Running manually

```bash
# Audit only (report; exit 1 on CRITICAL)
python3 tools/hermes_skill_sync_audit.py --mode audit

# Strict check (exit 1 on any CRITICAL or WARNING)
python3 tools/hermes_skill_sync_audit.py --mode check

# Audit + regenerate out-of-date mirrors (capped at 3 files)
python3 tools/hermes_skill_sync_audit.py --mode sync

# Dry-run sync (report what would change, write nothing)
python3 tools/hermes_skill_sync_audit.py --mode sync --dry-run

# Regenerate all mirrors unconditionally
python3 tools/sync_hermes_skills.py
```

---

## Interpreting drift items

| Drift class | Severity | Meaning | Fix |
|---|---|---|---|
| `RETIRED_CORRECTION_LEDGER` | **CRITICAL** | `skills/` source references retired Town Correction Ledger | Edit canonical source to remove reference |
| `RETIRED_CORRECTION_LEDGER_URI` | **CRITICAL** | `skills/` source has retired Correction Ledger URI | Same as above |
| `SOURCE_MISSING` | WARNING | Sync map entry has no source file | Create `skills/<key>/SKILL.md` or remove from `_meta.json` |
| `MIRROR_MISSING` | WARNING | Expected `docs/hermes_skills/` mirror absent | Run `sync_hermes_skills.py` |
| `FRONTMATTER_MISSING` | WARNING | Skill source has no YAML frontmatter | Add frontmatter block to `skills/<key>/SKILL.md` |
| `MIRROR_CONTENT_MISMATCH` | INFO | Source and mirror diverged | Run `sync_hermes_skills.py` |
| `ORPHANED_MIRROR` | INFO | Mirror file not tracked by any sync category | Add to `_meta.json` or delete |

**CRITICAL drift** (`DRIFT_CRITICAL`) blocks the agent and sends a `hermes_skill_sync_failed` FAIL event to Town.  
**WARNING drift** (`DRIFT_WARNING`) is non-blocking and sends a `hermes_skill_sync_drift` WARN event to Town.

---

## Handling a sync cap block

When `MIRROR_CONTENT_MISMATCH` count exceeds 3, `--mode sync` is suppressed:

```
Sync suppressed: N mismatched files exceeds cap of 3. Run sync_hermes_skills.py manually.
```

Run the full sync manually:

```bash
python3 tools/sync_hermes_skills.py
```

Then verify:

```bash
python3 tools/hermes_skill_sync_audit.py --mode check
```

---

## Cron registration

The wrapper is Hermes-managed, **not** a Linux crontab entry. Register once on the operator host:

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

---

## Disabling the cron

```bash
hermes cron pause hermes-skill-sync-guard
```

To re-enable:

```bash
hermes cron resume hermes-skill-sync-guard
```

---

## Heartbeat monitoring

`agent_heartbeat_checks.py` runs `check_hermes_skill_sync()` as part of the daily fleet receipt. Status mapping:

| Heartbeat status | CheckResult |
|---|---|
| File missing | `STALE` — agent has never run |
| `run_ts` > 10 days ago | `FAIL` — missed threshold |
| `run_ts` > 8 days ago | `WARN` — miss threshold approached |
| `status=DRIFT_CRITICAL` or `n_critical>0` | `FAIL` |
| `status=DRIFT_WARNING` or `n_warning>0` | `WARN` |
| `sync_files_changed>3` | `WARN` — sync cap breach |
| `status=OK` | `OK` |

---

## Forbidden files

The sync agent must never touch:

```
production_data/**
artifacts/generated/**
.env
.github/workflows/**
ranker/**
selector/**
portfolio/**
snapshots/**
data/snapshots*/**
```

Write authority is `observe_only` per `AGENT_REGISTRY.json`. The wrapper writes only to:
- `artifacts/governance/hermes_skill_sync/` (heartbeat + reports)
- `docs/hermes_skills/` (mirrors, capped at 3 files per sync run)
- `logs/hermes_skill_sync_agent.log`

---

## Town notification directionality

```
Hermes → Town: notify/report (hermes_skill_sync_drift, hermes_skill_sync_failed)
Town → Hermes: no autonomous writeback
```

When Town receives a `hermes_skill_sync_failed` email: investigate the CRITICAL drift items in the
dated report at `artifacts/governance/hermes_skill_sync/`. Fix in `skills/*/SKILL.md`, then run
`sync_hermes_skills.py` and verify with `hermes_skill_sync_audit.py --mode check`.
