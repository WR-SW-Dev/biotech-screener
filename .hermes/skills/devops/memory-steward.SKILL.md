---
name: memory-steward
triggers:
  - memory audit
  - session bloat
  - cache cleanup
  - stale sessions
  - task backlog cleanup
  - hermes memory pressure
  - openclaw session triage
description: >
  Audit-first, approval-gated memory steward for the OpenClaw/Hermes environment.
  Identifies resource pressure from stale sessions, task/issue backlog, caches,
  logs, and scratch artifacts. Read-only by default. Never deletes anything without
  explicit per-item approval. Delivers a 9-section audit report and stops.
---

# Memory Steward — OpenClaw/Hermes

## Purpose

Reduce resource pressure from stale sessions, task history, temporary caches,
and noncanonical memory — while preserving all project-critical knowledge.

Default mode: READ-ONLY AUDIT.

---

## What is never touched (forbidden list)

Regardless of what the user asks, NEVER delete, move, modify, pause, resume, or
clear any of the following:

- SYSTEM_STATE.md
- MEMORY.md
- specs/changes/
- docs/MODEL_DOCUMENTATION.md
- Any committed source file (check with git status before touching anything)
- production_data/ and any production snapshots
- .credentials.json
- auth-profiles.json
- Any active cron entry or job definition
- Active Hermes job roster
- Any audit/spec artifact from the current operating cycle
- Any file whose loss cannot be recovered from git

---

## Safe cleanup candidates (after explicit approval only)

- OpenClaw/Hermes sessions older than a user-specified threshold
- Failed or abandoned task records
- Temporary scratch files (tmp/, scratch/, *.tmp, *.bak)
- Old run logs beyond retention window
- Duplicate generated artifacts
- Cache directories that can be regenerated (__pycache__, .cache/, etc.)
- Obsolete untracked tool outputs (tools/*.json scratch files, etc.)

---

## Audit steps (run all, read-only)

### 1. Hermes job roster and recent run health

```bash
hermes jobs list 2>/dev/null || echo "hermes CLI not available"
```

### 2. OpenClaw agent/session status

```bash
openclaw status 2>/dev/null || echo "openclaw not available"
openclaw sessions list 2>/dev/null | head -50
openclaw tasks list 2>/dev/null | head -50
```

### 3. Disk usage on likely bloat locations

```bash
du -sh ~/.hermes/ 2>/dev/null
du -sh ~/.hermes/sessions/ 2>/dev/null
du -sh ~/.hermes/logs/ 2>/dev/null
du -sh ~/.hermes/cache/ 2>/dev/null
du -sh ~/.hermes/history/ 2>/dev/null
du -sh ~/.openclaw/ 2>/dev/null
du -sh ~/.openclaw/sessions/ 2>/dev/null
du -sh ~/.openclaw/logs/ 2>/dev/null
du -sh ~/.openclaw/agents/ 2>/dev/null
```

### 4. Large log files

```bash
find ~/.hermes/ -name "*.log" -size +1M 2>/dev/null | xargs ls -lh 2>/dev/null | sort -k5 -rh | head -20
find ~/.openclaw/ -name "*.log" -size +1M 2>/dev/null | xargs ls -lh 2>/dev/null | sort -k5 -rh | head -20
find /mnt/c/Projects/biotech_screener/biotech-screener -name "*.log" -size +1M 2>/dev/null | xargs ls -lh 2>/dev/null | sort -k5 -rh | head -20
```

### 5. Old log files (>7 days)

```bash
find ~/.hermes/ -name "*.log" -mtime +7 2>/dev/null | head -30
find ~/.openclaw/ -name "*.log" -mtime +7 2>/dev/null | head -30
```

### 6. Stale sessions by age

```bash
ls -lt ~/.hermes/sessions/ 2>/dev/null | head -30
ls -lt ~/.openclaw/sessions/ 2>/dev/null | head -30
# Check oldest sessions
ls -ltr ~/.hermes/sessions/ 2>/dev/null | head -20
ls -ltr ~/.openclaw/sessions/ 2>/dev/null | head -20
```

### 7. Temporary and scratch files in project

```bash
find /mnt/c/Projects/biotech_screener/biotech-screener -name "*.tmp" 2>/dev/null
find /mnt/c/Projects/biotech_screener/biotech-screener -name "*.bak" 2>/dev/null
find /mnt/c/Projects/biotech_screener/biotech-screener -name "__pycache__" -type d 2>/dev/null | head -20
find /mnt/c/Projects/biotech_screener/biotech-screener/tools -name "*.json" -not -path "*/node_modules/*" 2>/dev/null | xargs ls -lh 2>/dev/null
find /mnt/c/Projects/biotech_screener/biotech-screener -maxdepth 3 -name "scratch*" -o -name "tmp*" -o -name "test_output*" 2>/dev/null | head -20
```

### 8. Cache directories

```bash
find /mnt/c/Projects/biotech_screener/biotech-screener -name ".cache" -type d 2>/dev/null
find /mnt/c/Projects/biotech_screener/biotech-screener -name "*.pyc" 2>/dev/null | wc -l
du -sh /mnt/c/Projects/biotech_screener/biotech-screener/artifacts/ 2>/dev/null
ls -lt /mnt/c/Projects/biotech_screener/biotech-screener/artifacts/ 2>/dev/null | head -20
```

### 9. Hermes job history files

```bash
find ~/.hermes/ -name "*.jsonl" -o -name "*.json" 2>/dev/null | xargs ls -lh 2>/dev/null | sort -k5 -rh | head -20
```

---

## Required audit deliverable (9 sections)

After running all audit commands, produce this report in full:

---
MEMORY STEWARD AUDIT REPORT
Generated: <timestamp>
---

### 1. Current Memory/Session/Task Status
- Hermes: job count, last run dates, any failed jobs
- OpenClaw: agent count, active sessions, memory-core status
- Token pressure indicators where visible

### 2. Largest Resource Consumers
- Directories by disk size (top 10)
- Largest individual files

### 3. Stale Sessions by Age
- Session ID | Age | Last activity | Token count (if available)
- Flag any session older than 7 days

### 4. Stale Tasks/Issues
- Failed tasks with no resolution
- Abandoned tasks (no activity > 3 days)
- Issue count vs. active count

### 5. Safe Cleanup Candidates
Table: Path/ID | Type | Size/Count | Age | Why Safe

### 6. Unsafe Cleanup Candidates
Table: Path/ID | Type | Why Unsafe (what would be lost)

### 7. Exact Proposed Commands
One command per target. No broad wildcards.
Example:
  rm -rf ~/.hermes/sessions/abc123   # session from 2026-04-01, 0 tokens, abandoned

### 8. Estimated Risk Per Candidate
NONE / LOW / MEDIUM / HIGH with brief rationale

### 9. Rollback / Backup Plan
- What to back up before each action
- How to recover if something goes wrong
- Prefer: mv to archive location over rm

---
DECISION OPTIONS
  AUDIT_ONLY           — no action taken, report only
  CLEAN_SAFE_CACHES    — delete only regenerable cache dirs listed above
  CLEAN_STALE_SESSIONS — archive/remove only the specific stale sessions listed
  CLEAN_STALE_TASKS    — clear only specific failed/abandoned tasks listed
  FULL_APPROVAL_REQUIRED — approve each item individually
---

STOP HERE. Do not execute any cleanup until user explicitly says proceed.

---

## Execution rules (when approved)

- Back up before deleting: cp -r <target> <target>.bak_<date> or tar archive
- Prefer mv to an ~/archive/ location over rm
- Never rm -rf without first listing exact targets
- Print the exact target list before executing
- Execute one category at a time, confirm after each
- If anything is ambiguous, skip it and flag for manual review
