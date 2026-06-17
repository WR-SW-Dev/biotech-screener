# Agent Dry-Run Patterns — Operational Guide

**Purpose**: Document consistent dry-run invocation patterns across the Hermes fleet.  
**Audience**: Operators, QA engineers, testing automation.

---

## Pattern Overview

All agents support dry-run or preview modes via one of three patterns:

| Pattern | Type | Agents | Command |
|---|---|---|---|
| **CLI Flag** | `--dry-run` flag on agent invocation | Chat-mode, research | `--dry-run` |
| **Script Variant** | Separate `build_*.py` scripts or variants | Deterministic builders | `PREVIEW=1` env var or `--preview` flag |
| **Manual Review** | Manual script invocation (non-blocking) | Advisory agents | `tools/run_agent_direct.py --agent X` |

---

## By Agent Category

### Control Plane Agents (Fleet Director, QA)

#### fleet_steward
```bash
# Advisory-only mode (default)
python3 tools/run_agent_direct.py --agent fleet_steward

# No dry-run mode; output is observational by design.
```
**Output**: Fleet health summary (never mutates state)

---

#### sentinel
```bash
# Preview drift detection without promotion
python3 tools/run_agent_direct.py --agent sentinel --dry-run

# This will:
# - Load prior snapshot
# - Compare with current
# - Report drift metrics
# - NOT update cascade/alert thresholds
```
**Output**: Drift analysis (read-only)

---

#### production_qa, qa
```bash
# Dry-run QA checks
python3 tools/run_agent_direct.py --agent production_qa --dry-run

# Features checked but not flagged for escalation.
```
**Output**: Feature coverage report (advisory)

---

### Data Ingestion Agents (Data Lead)

#### herald
```bash
# Preview news classification without storage
PREVIEW=1 python3 tools/fetch_company_press_releases.py

# Or via agent interface (advisory-only):
python3 tools/run_agent_direct.py --agent herald
```
**Output**: Classified news digest (read-only; not written to disk)

---

#### ctgov_poller
```bash
# Preview new trials without caching
python3 tools/run_agent_direct.py --agent ctgov_poller --dry-run

# Or build script variant:
python3 scripts/ctgov_ingest.py --as-of 2026-06-17 --preview
```
**Output**: New trial count, stage transitions (not cached)

---

#### earnings_calendar_sync
```bash
# Preview calendar updates without disk write
PREVIEW=1 python3 tools/fetch_earnings_calendar.py

# Or agent interface:
python3 tools/run_agent_direct.py --agent earnings_calendar_sync --preview
```
**Output**: Calendar deltas (not synchronized)

---

### Signal Monitor Agents (Signal Lead)

#### price_action_watch, options_watch, catalyst_delta
```bash
# Preview alerts without artifact write
python3 tools/run_agent_direct.py --agent price_action_watch --dry-run

# Build scripts also support --preview:
python3 scripts/build_price_action_watch.py --as-of 2026-06-17 --preview
```
**Output**: Alert list (not written to `artifacts/`)

---

#### ic_health_monitor
```bash
# Preview IC trend without updating memory
python3 tools/run_agent_direct.py --agent ic_health_monitor --dry-run

# Output: IC metrics (not cached to memory/)
```

---

#### postmortem, event_analyst
```bash
# Preview postmortem analysis without recording
python3 tools/run_agent_direct.py --agent postmortem --dry-run

# Output: Analyzed events (not written to artifacts/)
```

---

### Research Agents (Research Lead)

#### calibration, calibration_evidence
```bash
# Preview evidence without artifact generation
python3 tools/run_agent_direct.py --agent calibration --dry-run

# Output: Evidence summary (not written to artifacts/calibration_evidence/)
```

---

#### crt_resolution_watcher
```bash
# Advisory-only; always non-mutating by default
python3 tools/run_agent_direct.py --agent crt_resolution_watcher

# For actual mutation (after review):
# Operator explicitly invokes rebuild scripts:
python3 scripts/research/build_crt_options_join.py --after-date 2026-06-17
```
**Output**: New resolutions (advisory; mutation requires explicit rebuild)

---

### Portfolio Risk Agents (Risk Lead)

#### shadow_monitor
```bash
# Preview shadow portfolio comparison without disk update
python3 tools/run_agent_direct.py --agent shadow_monitor --dry-run

# Build script variant:
PREVIEW=1 python3 tools/build_shadow_monitor.py --as-of 2026-06-17
```
**Output**: Performance comparison (not written to artifacts/)

---

### Governance Agents (Governance Lead)

#### hermes-* agents
```bash
# Governance agents are read-only by design (no dry-run needed)
python3 agents/hermes-first-fire-validator/run_job.py

# Outputs are advisory; no mutations performed.
```
**Output**: Validation reports (observational)

---

### Chat-Mode Agents (Manual Invocation)

#### review_queue_steward
```bash
# Chat-mode invocation (always non-destructive)
python3 tools/run_agent_direct.py --agent review_queue_steward

# Dry-run:
python3 tools/run_agent_direct.py --agent review_queue_steward --dry-run
```
**Output**: Triage decisions (not recorded to disk)

---

## Common Patterns Across Agents

### Advisory Mode (Default)
Most agents default to advisory mode, which:
- **Reads** from production data
- **Computes** summaries, metrics, alerts
- **Writes** to memory/ only (if at all)
- **Never** mutates artifacts, rankings, or state

**Invocation**:
```bash
python3 tools/run_agent_direct.py --agent <agent_name>
```

### Dry-Run / Preview Mode
For agents that can write artifacts, preview mode:
- **Reads** from production data
- **Computes** summaries, alerts
- **Skips** disk writes (or writes to temp dir)
- **Reports** what would be written

**Invocation**:
```bash
python3 tools/run_agent_direct.py --agent <agent_name> --dry-run
# OR
PREVIEW=1 python3 scripts/build_<agent_name>.py ...
# OR
python3 scripts/build_<agent_name>.py --preview
```

### Manual Build (Research/Mutation)
For agents that require explicit approval:
- **Call the underlying build script directly**
- **Operator reviews output**
- **Operator invokes with `--confirm` flag if satisfied**

**Examples**:
```bash
# Advisory run
python3 scripts/research/build_crt_options_join.py --as-of 2026-06-17

# Then, if operator approves:
python3 scripts/research/build_crt_options_join.py --as-of 2026-06-17 --confirm
```

---

## Testing Checklist

When onboarding a new operator, use this checklist:

- [ ] Run `--dry-run` on 3 advisory agents (e.g., fleet_steward, ic_health_monitor, review_queue_steward)
- [ ] Verify `--dry-run` output is sensible (not empty, no errors)
- [ ] Run `PREVIEW=1` on 2 build agents (e.g., herald, shadow_monitor)
- [ ] Verify artifacts dir is NOT modified (check mtime)
- [ ] Run 1 governance agent (e.g., hermes-ruleset-integrity)
- [ ] Verify output is advisory (no mutations)

---

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| `--dry-run` flag not recognized | Agent type (chat vs. deterministic) | Use `PREVIEW=1` env var instead, or check `SOUL.md` |
| Output is empty | Data dependencies | Verify input artifacts exist (e.g., Lane B outputs) |
| Script fails on `--dry-run` | Env var not passed correctly | Use `PREVIEW=1 python3 script.py` (space, no `=`) |
| Artifacts modified despite `--dry-run` | Bug in agent script | File issue; agent should skip writes in preview mode |

---

## References

- **Fleet architecture**: `docs/AGENT_FLEET_ARCHITECTURE_INDEX.md`
- **Lane B signal monitors**: `docs/SIGNAL_MONITOR_AGENT_MAP.md`
- **Data ingestion pipeline**: `docs/DATA_INGESTION_AGENT_MAP.md`
- **Control plane**: `docs/CONTROL_PLANE_AGENT_MAP.md`

---

**Last updated**: 2026-06-17  
**Maintainer**: Hermes Agent Optimization Audit
