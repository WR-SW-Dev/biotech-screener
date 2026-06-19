# Scientific Cartography LangGraph LG3 — Scheduled Review Design

## Status

```
LANGGRAPH_PHASE_LG3_SCHEDULED_REVIEW_DESIGN
DESIGN_ONLY
NO_RUNTIME_CRON
NO_PRODUCTION_HOOK
NO_AUTOMATION_APPROVAL
```

## Purpose

LG3 defines a design for **optional** scheduled review jobs that run the LangGraph review orchestrator (LG1) on Scientific Cartography diagnostic artifacts and capture human decision artifacts (LG2).

LG3 is intended for future operational convenience: allowing teams to schedule regular review job runs without manual intervention, while maintaining full governance boundaries and explicit approval gates.

**Current status**: Design only. No scheduling, cron, dashboard, or production integration is implemented or enabled.

## Non-Goals

- ✗ Production pipeline integration (no `run_daily_production.py` changes)
- ✗ Automated enforcement of LG2 decisions (LG2 approval never implies schedule enablement)
- ✗ Dashboard or UI (diagnostic artifacts only)
- ✗ Agent summarization or LLM-driven scheduling
- ✗ Ranker/selector/sizing/final_score changes
- ✗ Runtime cron installation or enablement
- ✗ Production hook wiring

## Current LG1/LG2 Baseline

**LG1** (commit 1b2c8095): Standalone review orchestrator.
- Deterministic nodes: initialize → load → validate → governance scan → disease selection → summary → review gate → capture decision → write outputs → finalize
- CLI: `tools/run_scientific_cartography_langgraph_review.py`
- Output: review artifacts (JSON, Markdown, state) + optional decision JSONL

**LG2** (commit bdb97db7): Human decision artifacts layer.
- Captures operator approval/rejection/hold decisions for review workflow continuation
- Append-only JSONL with full governance audit trail
- automation_approval immutably False
- CLI flags: --approve-review, --reject-review, --hold-review, --decision-reason, --decision-actor

**Key invariant**: LG2 approval is review-workflow-only. It does NOT authorize schedule enablement, production deployment, or automation.

## Design Principle

> LG2 approval approves review workflow continuation only.
> LG2 approval must never imply scheduled automation approval.
> LG3 schedule enablement requires a separate explicit operator action.

LG3 jobs may run on regular schedules, but only with:
1. Explicit schedule_enable flag or operator action (separate from LG2 approval)
2. Non-blocking failure behavior (failures never block production)
3. Read-only diagnostic outputs (review artifacts only)
4. Full audit trail (scheduled runs logged, reproducible)

## Workflow Overview

```
Operator Action (Optional Future)
    ↓
Schedule LG3 Review Job (Manual Trigger or Disabled-by-Default Cron)
    ↓
Run LG1 Review Orchestrator on as_of_date
    ↓
Generate Review Artifacts (JSON, Markdown, State)
    ↓
Optionally: Run LG2 Decision Capture (--approve-review / --reject-review / --hold-review)
    ↓
Append Decision to JSONL (if operator-provided flags)
    ↓
Store in artifacts/scientific_cartography/<as_of_date>/review/
    ↓
Log Success/Failure (non-blocking)
    ↓
Return to Production (LG3 failure never blocks anything)
```

## Mode A: Manual Scheduled-Review Runner

**Operator manually runs the existing LangGraph review CLI on a chosen artifact directory.**

Example command (no changes required to LG1/LG2):

```bash
python3 tools/run_scientific_cartography_langgraph_review.py \
  --as-of-date 2026-06-19 \
  --artifact-dir artifacts/scientific_cartography/2026-06-19 \
  --review-dir artifacts/scientific_cartography/2026-06-19/review \
  [--approve-review | --reject-review | --hold-review] \
  [--decision-reason "..."] \
  [--decision-actor "operator"]
```

**Status**: Already available via LG1 CLI. Operator may invoke manually whenever desired.

**Governance**: Relies entirely on operator discipline (no automated gating).

## Mode B: Disabled-by-Default Cron-Compatible Wrapper

**A future wrapper script may exist to simplify cron-style invocation, but cron must not be installed or enabled by default.**

Proposed future wrapper signature (not implemented):

```bash
tools/run_scientific_cartography_scheduled_review.py \
  --as-of-date <date> \
  --auto-run-latest \
  [--approve-review | --reject-review] \
  [--decision-reason "..."] \
  [--strict]
```

**Status**: Design only. No wrapper code exists yet.

**Enablement**: Any cron installation would require:
1. Explicit operator action (not auto-installed)
2. Separate schedule_enable flag (not inferred from LG2 approval)
3. Non-blocking failure behavior (failures logged, never block production)
4. Audit trail (cron runs logged to artifacts/scientific_cartography/scheduled_review_log.jsonl)

**Default state**: Disabled. Cron entry not created during normal deployment.

## Output Directory Convention

Scheduled review jobs write to:

```
artifacts/scientific_cartography/<as_of_date>/review/
```

Files generated (same as LG1):
- `langgraph_review_summary.json` — Structured review summary
- `langgraph_review_summary.md` — Human-readable report
- `langgraph_review_state.json` — Full workflow state (for debugging)
- `langgraph_human_decisions.jsonl` — Append-only decision artifact (if decision flags provided)

No other directories or artifacts are written.

## Failure Behavior

**Scheduled review failure is non-blocking.**

- Failure must never block daily production, rankings, portfolio output, screening, or trading
- Failure writes diagnostic error artifacts only (no model state, no production data)
- Error logged to: `artifacts/scientific_cartography/<as_of_date>/review/error_log.jsonl`
- Operator notified (log entry, optional alert, no stopping production)
- Production continues normally

Example error artifact:

```json
{
  "artifact_type": "scientific_cartography_lg3_scheduled_review_error",
  "scheduled_run_at_utc": "2026-06-19T08:05:00Z",
  "as_of_date": "2026-06-19",
  "error_code": "MISSING_ARTIFACT_INDEX",
  "error_message": "disease_map_index.json not found in artifacts/scientific_cartography/2026-06-19/",
  "trace": "...",
  "governance": {
    "read_only_diagnostic": true,
    "review_workflow_only": true,
    "production_model_change": false,
    ...
  }
}
```

## Retention Policy

Review artifacts are point-in-time diagnostic outputs and may be retained indefinitely (storage permitting) or pruned per operator policy.

**Default retention**: Keep all. Operator may define pruning rules (e.g., delete reviews older than 90 days) without governance impact.

**Governance requirement**: Deletion must not affect production pipeline or audit trail (review artifacts are ephemeral; LG2 decisions are durable if needed for audit).

## LG2 Decision Artifact Interaction

LG3 scheduled jobs may optionally invoke LG2 decision capture:

```bash
python3 tools/run_scientific_cartography_langgraph_review.py \
  --as-of-date 2026-06-19 \
  --artifact-dir artifacts/scientific_cartography/2026-06-19 \
  --approve-review \
  --decision-actor "scheduled-review-automation" \
  --decision-reason "Automated approval pending operator review"
```

**Critical rule**: LG2 approval in a scheduled context does NOT imply:
- Production deployment
- Automation approval
- Ranker/selector/sizing changes
- Portfolio action
- Trading authorization

It only approves review workflow continuation (same as manual LG2 usage).

**Audit trail**: Scheduled LG2 decisions are marked with decision_actor="scheduled-review-automation" (or similar) to distinguish from manual operator decisions.

## Schedule Enablement Guardrail

**Cron enablement requires explicit operator action, separate from LG2 approval.**

Proposed future gatekeeping:

1. **Config file approach**: `config/lg3_scheduled_review_enabled.txt` (must exist and be non-empty for cron to run)
   ```
   # cron only runs if this file exists with a non-empty, non-comment line
   2026-06-19T10:30:00Z  # enabled at this time
   ```

2. **Environment variable approach**: `LG3_SCHEDULED_REVIEW_ENABLED=1` (cron entry checks this)

3. **Explicit flag approach**: Cron entry includes `--enable-scheduling` (fails with error if missing)

**Operator action to enable**: 
```bash
# Option 1: Create enable file
echo "2026-06-19T10:30:00Z" > config/lg3_scheduled_review_enabled.txt

# Option 2: Set environment variable
export LG3_SCHEDULED_REVIEW_ENABLED=1

# Option 3: Install cron entry with explicit flag
```

**Operator action to disable**:
```bash
# Option 1: Remove enable file
rm config/lg3_scheduled_review_enabled.txt

# Option 2: Unset environment variable
unset LG3_SCHEDULED_REVIEW_ENABLED

# Option 3: Comment out cron entry
```

## Rollback / Disable Procedure

If scheduled review jobs cause issues:

**Immediate disable** (within current run):
```bash
# Kill running job
pkill -f "run_scientific_cartography_scheduled_review"

# Or: Remove enable file
rm config/lg3_scheduled_review_enabled.txt
```

**Cron disable** (prevent future runs):
```bash
# Comment out cron entry in crontab
crontab -e  # and remove or comment the scheduled-review line

# Or: Delete enable file
rm config/lg3_scheduled_review_enabled.txt
```

**Restore operation**:
```bash
# Production pipeline is unaffected (scheduled review is non-blocking)
# Resume scheduled jobs by re-creating enable file or re-adding cron entry
echo "2026-06-19T10:30:00Z" > config/lg3_scheduled_review_enabled.txt
```

## Acceptance Criteria

LG3 design is complete when:

- ✓ Design document exists (this file)
- ✓ Governance decision artifact exists
- ✓ No code changes
- ✓ No cron installed
- ✓ No production pipeline changes
- ✓ No ranker/selector/sizing/final_score changes
- ✓ LG2 approval remains separate from schedule enablement
- ✓ Failure behavior is non-blocking
- ✓ Output directory convention specified
- ✓ Retention policy defined
- ✓ Rollback procedure documented

## Explicitly Deferred

The following are **not** part of LG3 design and require separate approval:

- ✗ Cron installation and enablement
- ✗ Dashboard or UI integration
- ✗ Agent summarization (Hermes skills, LLM-driven scheduling)
- ✗ Production pipeline integration (`run_daily_production.py` changes)
- ✗ Ranker/selector/sizing/final_score integration
- ✗ Automated portfolio action or trading decisions
- ✗ Model state mutations or production data writes
- ✗ GitHub Actions or CI/CD integration for scheduled reviews

All of the above require explicit separate operator approval and must maintain the same governance boundaries as LG2.

---

**Document Status**: Design complete. Ready for governance decision and operator review.
