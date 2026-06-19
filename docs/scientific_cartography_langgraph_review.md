# Scientific Cartography LangGraph Review Orchestrator

## Purpose

This document describes the LangGraph-based review orchestrator for Scientific Cartography diagnostic artifacts.

**Core Principle**: LangGraph sits **around** the biotech model as a workflow orchestration layer, not inside the scoring/ranking pipeline.

## What This Is

- Read-only diagnostic review workflow
- Artifact validation and governance scanning
- Deterministic disease selection for human review
- Stateful workflow with optional human approval gates

## What This Is NOT

- Alpha calculation
- Portfolio ranking or selection
- Risk scoring or sizing
- Production pipeline automation
- Deployment decision system

## Installation & Dependencies

LangGraph is optional. The deterministic node pipeline runs with or without it.

```bash
# Check if LangGraph is available
python3 -c "import langgraph; print('OK')"

# If needed, install separately (not in this task)
# pip install langgraph
```

## Command Examples

### Basic Usage

```bash
python3 tools/run_scientific_cartography_langgraph_review.py \
  --as-of-date 2026-06-18 \
  --artifact-dir artifacts/scientific_cartography/2026-06-18
```

### With Custom Output Directory

```bash
python3 tools/run_scientific_cartography_langgraph_review.py \
  --as-of-date 2026-06-18 \
  --artifact-dir artifacts/scientific_cartography/2026-06-18 \
  --review-dir /tmp/sc_review
```

### Test Mode (Auto-Approve)

```bash
python3 tools/run_scientific_cartography_langgraph_review.py \
  --as-of-date 2026-06-18 \
  --artifact-dir artifacts/scientific_cartography/2026-06-18 \
  --auto-approve-for-test
```

### Strict Mode

```bash
python3 tools/run_scientific_cartography_langgraph_review.py \
  --as-of-date 2026-06-18 \
  --artifact-dir artifacts/scientific_cartography/2026-06-18 \
  --strict
```

## Graph Nodes

The workflow is a linear pipeline of deterministic nodes:

1. **initialize_review** — Create review directory; set governance flags
2. **load_artifact_index** — Read disease_map_index.json; extract metadata
3. **validate_artifact_structure** — Check for required files in diseases/
4. **run_governance_scan** — Scan for forbidden terms (scoring/ranking language)
5. **select_review_diseases** — Choose representative diseases for human review
6. **build_review_summary** — Compile summary and decision
7. **optional_human_review_gate** — Non-interactive approval gate (test mode available)
8. **capture_human_decision** — Capture explicit human decision on review continuation (LG2)
9. **write_review_outputs** — Write JSON, Markdown, state files (with decision info if captured)
10. **finalize** — Return final state

## Governance Boundaries

All nodes enforce governance invariants:

```python
governance = {
    "read_only_diagnostic": True,
    "orchestration_layer_only": True,
    "production_model_change": False,
    "ranker_change": False,
    "selector_change": False,
    "sizing_change": False,
    "final_score_change": False,
    "alpha_promotion": False,
    "trading_or_portfolio_action": False,
}
```

These flags are immutable and part of the review output for audit.

## Outputs

The review generates three files in `<review_dir>/`:

### langgraph_review_summary.json

Structured summary suitable for parsing:

```json
{
  "artifact_type": "scientific_cartography_langgraph_review_summary",
  "generated_at": "2026-06-18T...",
  "governance": { ... },
  "as_of_date": "2026-06-18",
  "artifact_summary": {
    "disease_count": 3,
    "program_count": 12,
    ...
  },
  "selected_diseases_for_review": [ ... ],
  "governance_scan_passed": true,
  "decision": "HUMAN_REVIEW_REQUIRED",
  "next_steps": [ ... ]
}
```

### langgraph_review_summary.md

Human-readable review report:

```markdown
# Scientific Cartography LangGraph Review

## Governance
- read_only_diagnostic: true
- production_model_change: false
...

## Artifact Summary
- Diseases: 3
- Programs: 12
...

## Selected Diseases for Human Review
1. Acute Pain (MONDO:0000001) - 8 programs
2. ...

## Governance Scan
Status: PASS

## Decision
Recommended Decision: HUMAN_REVIEW_REQUIRED

## Next Steps
1. Review selected disease maps for quality...
2. ...
```

### langgraph_review_state.json

Full workflow state for debugging/audit:

```json
{
  "artifact_type": "scientific_cartography_langgraph_review_state",
  "generated_at": "...",
  "state": { ... all state fields ... }
}
```

## Governance Scan

The `run_governance_scan` node flags forbidden terms in disease artifact markdown:

**Forbidden terms**: score, alpha, rank, rating, buy, sell, recommend, conviction, weight, attractive, expected_return, portfolio action

**Allowed exceptions**: "not scoring", "not an investment recommendation"

Matches are flagged with context snippets in the review output.

**Pass criteria**: No forbidden terms found outside allowed disclaimer phrases.

## Disease Selection

The `select_review_diseases` node deterministically selects 3-5 disease maps:

1. Top disease by program count
2. Unknown disease (mondo_id = null) if available
3. Next largest diseases by program count (to fill to max_diseases)

Selection is deterministic (same input → same output) for reproducibility.

## Decision Types

The workflow recommends one of three decisions:

- **HUMAN_REVIEW_REQUIRED** — Artifacts are valid; human review recommended before Phase 13B/13C decisions
- **BLOCKED_MISSING_ARTIFACTS** — Required index file missing; cannot proceed
- **BLOCKED_GOVERNANCE_SCAN** — Forbidden terms detected; artifacts must be corrected

## Test Mode

Use `--auto-approve-for-test` for testing:

```bash
python3 tools/run_scientific_cartography_langgraph_review.py \
  --as-of-date 2026-06-18 \
  --artifact-dir artifacts/scientific_cartography/2026-06-18 \
  --auto-approve-for-test
```

This sets `human_decision = "AUTO_APPROVED_FOR_TEST_ONLY"` but does **not** approve deployment or production changes.

## Strict Mode

Use `--strict` to exit with nonzero status on governance failures:

```bash
python3 tools/run_scientific_cartography_langgraph_review.py \
  --as-of-date 2026-06-18 \
  --artifact-dir artifacts/scientific_cartography/2026-06-18 \
  --strict
```

This is useful for CI/CD gates: fail the build if review cannot proceed.

## Troubleshooting

### "disease_map_index.json not found"

The index file is required. Ensure Scientific Cartography artifact generation completed:

```bash
ls -la artifacts/scientific_cartography/2026-06-18/disease_map_index.json
```

### "Governance scan failed"

Check the `langgraph_review_summary.json` for `forbidden_terms_found`:

```bash
grep forbidden_terms artifacts/scientific_cartography/2026-06-18/review/langgraph_review_summary.json
```

Edit the offending disease artifact markdown to remove the term or add an allowed disclaimer phrase.

### LangGraph dependency error

The workflow can run with or without LangGraph. If it complains about a missing import, ensure you have LangGraph installed:

```bash
pip install langgraph
```

If LangGraph is not available, the CLI automatically falls back to running deterministic nodes without the graph wrapper.

## LG2 — Human Decision Artifacts

LG2 extends LG1 with explicit human decision capture for the review workflow.

### Decision States

```text
APPROVED_FOR_REVIEW_CONTINUATION — Human approves workflow continuation
REJECTED_WITH_REASON — Human rejects workflow continuation
HOLD_PENDING_MORE_REVIEW — Human requests more review before deciding
NO_DECISION_RECORDED — No explicit decision made (default)
```

### CLI Examples

Approve workflow continuation:
```bash
python3 tools/run_scientific_cartography_langgraph_review.py \
  --as-of-date 2026-06-18 \
  --artifact-dir artifacts/scientific_cartography/2026-06-18 \
  --approve-review \
  --decision-actor darren \
  --decision-reason "Reviewed selected disease maps; continue workflow."
```

Reject workflow continuation:
```bash
python3 tools/run_scientific_cartography_langgraph_review.py \
  --as-of-date 2026-06-18 \
  --artifact-dir artifacts/scientific_cartography/2026-06-18 \
  --reject-review \
  --decision-actor darren \
  --decision-reason "Source refs insufficient for continuation."
```

### Append-Only Decision Artifact

Decisions are appended to:
```
artifacts/scientific_cartography/<as_of_date>/review/langgraph_human_decisions.jsonl
```

Each line is a JSON record with decision state, actor, reason, timestamp, and governance block. Multiple decisions create multiple lines (audit history).

### Critical Governance Rule

**automation_approval is ALWAYS false in LG2.**

This approves only review workflow continuation, **NOT** production deployment, automation, portfolio actions, or any biotech model changes.

## LG3 — Scheduled Review Design

LG3 is currently **design-only**. No runtime cron, scheduling, or production hooks are enabled.

See `docs/scientific_cartography_lg3_scheduled_review_design.md` for full design.

**Key rule**: LG2 decision artifacts approve review continuation only and do not authorize schedule enablement. Any future scheduled review jobs would require separate operator action (config flag, environment variable, or cron installation).

**Status**: Design complete, implementation deferred pending operator decision.

## Known Limitations

1. **Mechanism/target sparse by design** — The normalizer is conservative; sparse coverage is expected, not a failure.
2. **Disease selection limited to first ~10 disease dirs** — Prevents timeout on massive artifact sets.
3. **LG2 is non-interactive** — CLI flags only; no real-time prompts (future: LG3 with scheduled review jobs).

## Next Phases

- **LG2** — Human-in-the-loop interactive approval gates
- **LG3** — Optional non-blocking scheduled review job
- **LG4** — Dashboard / static browser integration
- **LG5** — Hermes/agent summarization nodes

## Architecture Principle

```
biotech model = deterministic production engine (unchanged)
LangGraph = orchestration shell for diagnostics/review (this)
Hermes agents = optional specialist helpers for summarization

Do not blur these boundaries. LangGraph must not influence:
- ranker
- selector
- sizing
- final_score
- portfolio decisions
- trading actions
```

## Governance Statement

This workflow operates **entirely outside** the production scoring and ranking pipeline.

All outputs are read-only diagnostic artifacts. No deployment decisions are made without explicit human approval and explicit code changes.

The `governance` block is immutable and auditable, ensuring traceability of review execution.
