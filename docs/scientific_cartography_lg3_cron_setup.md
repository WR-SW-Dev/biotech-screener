# LG3 Scheduled Review — Cron Setup

## Overview

LG3 Mode B wrapper (`tools/run_scientific_cartography_scheduled_review.py`) enables daily automated review of Scientific Cartography artifacts.

**Status**: Approved and active (as of 2026-06-19)

## Prerequisites

- Python 3.12+
- Cron daemon running (on macOS, Linux, or WSL2)
- Repo root: `/mnt/c/Projects/biotech_screener/biotech-screener/` (adjust for your environment)

## Installation

### Step 1: Verify wrapper script

```bash
# Test the wrapper on the latest snapshot
python3 /mnt/c/Projects/biotech_screener/biotech-screener/tools/run_scientific_cartography_scheduled_review.py \
  --auto-run-latest

# Verify audit log was created
tail -f /mnt/c/Projects/biotech_screener/biotech-screener/artifacts/scientific_cartography/scheduled_review_cron.jsonl
```

### Step 2: Install cron entry

Edit your crontab:

```bash
crontab -e
```

Add the following line (adjust paths and time as needed):

```cron
# LG3 Scheduled Scientific Cartography review (daily at 08:05 AM ET)
5 8 * * * cd /mnt/c/Projects/biotech_screener/biotech-screener && python3 tools/run_scientific_cartography_scheduled_review.py --auto-run-latest >> /tmp/lg3_cron.log 2>&1
```

**Notes:**
- `5 8 * * *` = 08:05 AM every day
- Adjust time to your preference (cron uses local timezone)
- Logs output to `/tmp/lg3_cron.log` (optional; remove redirects if not needed)
- Set working directory explicitly for reliability

### Step 3: Verify cron entry

```bash
# List your cron entries
crontab -l | grep lg3_cron

# Verify it appears in the cron list
```

## Operation

### Automatic Execution

The wrapper runs daily on the specified schedule:
1. Auto-detects latest snapshot date
2. Invokes LG1 review orchestrator
3. Auto-approves with `decision_actor=scheduled-review-automation`
4. Logs execution to `artifacts/scientific_cartography/scheduled_review_cron.jsonl`
5. Returns exit code 0 (non-blocking)

### Manual Invocation

To run manually (useful for testing):

```bash
# Auto-detect latest snapshot
python3 tools/run_scientific_cartography_scheduled_review.py --auto-run-latest

# Specific snapshot date
python3 tools/run_scientific_cartography_scheduled_review.py --as-of-date 2026-06-19

# Without auto-approve (requires manual LG2 decision via CLI flags)
python3 tools/run_scientific_cartography_scheduled_review.py --auto-run-latest --no-auto-approve
```

### Monitoring

Check audit trail:

```bash
# Watch real-time
tail -f artifacts/scientific_cartography/scheduled_review_cron.jsonl

# Count successes vs failures
jq 'select(.outcome=="success")' artifacts/scientific_cartography/scheduled_review_cron.jsonl | wc -l
jq 'select(.outcome=="failure")' artifacts/scientific_cartography/scheduled_review_cron.jsonl | wc -l

# Check recent failures
jq 'select(.outcome=="failure")' artifacts/scientific_cartography/scheduled_review_cron.jsonl | tail -5
```

## Disable/Rollback

### Temporarily disable (comment out)

```bash
crontab -e
# Comment the cron line:
# 5 8 * * * cd /mnt/c/Projects/biotech_screener/biotech-screener && python3 tools/run_scientific_cartography_scheduled_review.py --auto-run-latest >> /tmp/lg3_cron.log 2>&1
```

### Permanently remove

```bash
crontab -e
# Delete the cron line entirely
```

### Emergency disable via environment variable

Add to your shell profile or set before cron runs:

```bash
export LG3_SCHEDULED_REVIEW_DISABLED=1
```

(Wrapper script can be updated to check this variable if needed.)

## Governance

All executions are logged with governance metadata:

```json
{
  "artifact_type": "scientific_cartography_lg3_scheduled_review_cron_execution",
  "executed_at_utc": "2026-06-19T08:05:00Z",
  "as_of_date": "2026-06-19",
  "outcome": "success",
  "duration_seconds": 45.2,
  "governance": {
    "read_only_diagnostic": true,
    "non_blocking": true,
    "automation_approval": false
  }
}
```

**Key guarantees:**
- Non-blocking: Failures never affect production pipeline
- Read-only: Only writes to `artifacts/scientific_cartography/`
- Diagnostic: No ranker/selector/sizing/final_score changes
- No automation_approval: Cron approval separate from production deployment

## Troubleshooting

### Cron not running

```bash
# Check if cron daemon is running
ps aux | grep cron

# On macOS
sudo launchctl list | grep cron

# On Linux/WSL2
sudo systemctl status cron
```

### Wrapper script fails

Check the audit log:

```bash
jq 'select(.outcome=="failure") | select(.error_message)' artifacts/scientific_cartography/scheduled_review_cron.jsonl
```

Common failures:
- Snapshot directory not found (check snapshot date generation)
- Python import error (check PYTHONPATH, repo root path in cron command)
- Timeout (snapshots taking >1 hour; increase timeout in wrapper)

### Manual testing

```bash
# Test with explicit date
python3 tools/run_scientific_cartography_scheduled_review.py --as-of-date 2026-06-19 --strict

# Check output in artifacts
ls -la artifacts/scientific_cartography/2026-06-19/review/
```

## First Review Period

Daily monitoring through 2026-07-03 (2 weeks) to verify:
- Cron executions completing on schedule
- Audit trail populated correctly
- Zero production pipeline impact
- No resource exhaustion

If any issues arise, disable cron and investigate.

---

**Status**: Operational  
**Approval date**: 2026-06-19  
**Review period**: 2026-06-19 to 2026-07-03
