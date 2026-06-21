# Agent Workflow Hardening

This repo treats agent workflow controls as governance infrastructure. These rules do not authorize scoring, selector, ranker, sizing, or production deployment changes.

## Session Preflight

Before edits, an agent must establish:

- CodeGraph status is current.
- Governance tier is classified.
- Production/scoring boundary is stated.
- Affected symbols are identified.
- Affected tests are identified.
- PIT timestamp source is confirmed.
- Shell health check can return an exit status.

Run:

```bash
python tools/agent_preflight.py --json
```

For local verification, run:

```bash
python scripts/verify_agent_workflow.py
```

The verifier stops early if shell health is not `ok`.

CI also runs the dedicated `agent-workflow` workflow for changes to agent workflow controls, dependency files, and LangGraph review tests.

## Approval States

Do not collapse approval concepts. Track them separately:

- Human reviewed: a person inspected the output.
- Workflow continuation approved: the next review or diagnostic step may run.
- Production deployment approved: production state may change.
- Automation allowed: a scheduled or automated process may act.

Automation may not imply human review. Workflow continuation may not imply production deployment.

## CI Lanes

- Tier 1 docs/utilities: lint, unit tests, `tools/check_agent_workflow.py`.
- Tier 2 research plumbing: Tier 1 plus determinism checks and focused fixture tests.
- Tier 3 production/evidence surfaces: Tier 2 plus PIT/leakage/regression battery and mandatory Claude Code review.
- Tier 4 governance/research judgment: memo/spec first; implementation only after explicit instruction.

## Dependency Hygiene

Runtime dependency changes must update:

- `requirements.txt`
- `requirements.lock`
- `pyproject.toml` when package installs need the dependency

CI should fail when pinned runtime requirements are missing from the lock file.
This is intentional: after changing `requirements.txt`, regenerate `requirements.lock` with `pip-compile --generate-hashes --output-file=requirements.lock requirements.txt`.

`tools/check_agent_workflow.py` also checks third-party imports in deterministic workflow paths against `requirements.txt` and `pyproject.toml`.

## Determinism

Review and diagnostic artifacts should derive timestamps from `as_of_date` when rerun byte stability matters. Avoid `datetime.now()` and `datetime.utcnow()` in deterministic workflow paths.

## Scheduled Jobs

Scheduled diagnostics may fail open only when the behavior is explicitly documented and a structured failure artifact is written. Scheduled jobs must not auto-approve human review states by default.

## Review Default

Review agents are read-only by default. Implementation agents patch only after review findings are accepted or the user explicitly asks for fixes.

## Changed-File Tier Labels

Use PR labels that match the highest required tier:

- `tier-1`
- `tier-2`
- `tier-3`
- `tier-4`

To classify paths locally:

```bash
python tools/check_agent_workflow.py --changed-file selector_engine.py --changed-file docs/AGENT_WORKFLOW_HARDENING.md
```

## Optional Extended Scans

Use these before broader workflow changes:

```bash
python tools/check_agent_workflow.py --check-network-tests
python tools/check_agent_workflow.py --check-stale-artifact-refs
```

Network-looking tests should be marked `@pytest.mark.network` unless all network calls are mocked. Hard-coded dated artifact paths should be avoided outside fixtures and archival docs.

## Artifact Schemas

Agent review and scheduled diagnostic artifacts are registered in `docs/agent_artifact_schemas.json`. New review artifacts should be added there with required governance fields before they are produced by automation.
