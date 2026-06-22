# BIOTECH_MCP_REGISTRATION — 2026-06-22

Package C2: wire the already-built `tools/biotech_mcp_server.py` into Hermes
with the smallest possible blast radius.  This document records the registration
decision, what was changed, and the smoke-test evidence.

## What was registered

**Server name:** `biotech`  
**Config file:** `~/.hermes/config.yaml` (section `mcp_servers`)  
**Backup before edit:** `~/.hermes/config.yaml.bak.20260622_biotech_mcp_prereg`  
**Transport:** stdio — `python3 /mnt/c/Projects/biotech_screener/biotech-screener/tools/biotech_mcp_server.py`  
**Auth:** none (local, no network, no tokens)

## Safety constraints honored

| Constraint | How enforced |
|---|---|
| Local only | `command: python3`, absolute path to local script; no URL, no network MCP |
| Read-only | Only the 11 read-only tools from Package C exposed via `tools.include` |
| No write tools | No shell, no git, no file-write tools on this server — by construction |
| No cron | Zero cron changes; `weekly-skill-harvester` confirmed paused post-registration |
| No new profiles | Default profile only; no `platform_toolsets` expansion |
| No external MCPs | Only addition is the local biotech server |
| Explicit include | 11-tool allowlist in `tools.include` — surface stays auditable |

## Config change (verbatim excerpt)

```yaml
mcp_servers:
  # ... codegraph entry unchanged ...
  # biotech-mcp: read-only diagnostic view of the biotech screener model
  # Package C2 (2026-06-22) — local stdio, stdlib-only, no network, no writes
  biotech:
    command: python3
    args:
    - /mnt/c/Projects/biotech_screener/biotech-screener/tools/biotech_mcp_server.py
    timeout: 30
    connect_timeout: 15
    enabled: true
    tools:
      include:
      - list_snapshots
      - read_latest_snapshot_manifest
      - read_gate_verdicts
      - read_phase2_health
      - read_rankings_schema
      - read_event_ev_feature_coverage
      - read_forward_eval_ic_ledger
      - read_scientific_cartography_status
      - list_disease_map_artifacts
      - read_semgrep_findings
      - run_readonly_diagnostics
```

## Smoke-test results

**Test 1 — `hermes mcp test biotech`**
```
✓ Connected (140ms)
✓ Tools discovered: 11
  list_snapshots  read_latest_snapshot_manifest  read_gate_verdicts
  read_phase2_health  read_rankings_schema  read_event_ev_feature_coverage
  read_forward_eval_ic_ledger  read_scientific_cartography_status
  list_disease_map_artifacts  read_semgrep_findings  run_readonly_diagnostics
```

**Test 2 — `list_snapshots`**: returned `count: 3, latest: "2026-06-21"` ✓

**Test 3 — `read_phase2_health`**: responded correctly (artifact missing on
2026-06-21 — expected, one of the 3 missing artifacts noted in Package C
smoke test) ✓

**Test 4 — `read_semgrep_findings`**: `rule_count: 4`, `findings_persisted:
false`, `exists: true` ✓

**Test 5 — `run_readonly_diagnostics` safety flags**:
```
executes_scripts: false  ✓
mutates: false           ✓
network: false           ✓
latest_snapshot: 2026-06-21
summary: {artifacts_missing: 3, artifacts_present: 3, checks_total: 6}
```

**Test 6 — gateway health**: `{"status":"ok","platform":"hermes-agent"}` ✓

**Test 7 — weekly-skill-harvester**: `enabled: false`, `state: paused` ✓

**Test 8 — repo diff**: only pre-existing modifications (`.cursorrules`,
`CLAUDE.md`, `production_data/short_interest.json`) — no Package C file
changed ✓

## Open items (not blocking registration)

- 3 of 6 diagnostic checks in `run_readonly_diagnostics` show `exists: false`
  (snapshot_manifest, phase2_health, rankings_csv on 2026-06-21 stub snapshot).
  The 2026-06-18 snapshot is complete.  Investigate separately if needed.
- Hermes gateway restart required to load the new entry into live session
  tool-grant (gateway config reload or restart after next natural stop).

## Next step

Package D: `docs/governance/MCP_SERVER_INTAKE_RUBRIC.md` +
`.semgrep/mcp-supply-chain.yml`, then evaluate Semgrep MCP as the first
external MCP candidate.
