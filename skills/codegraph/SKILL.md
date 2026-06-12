# Codegraph Repo Intelligence Skill

## Purpose

Use Codegraph as the first-pass structural map for biotech-screener code navigation, dependency tracing, and blast-radius review. Codegraph is a repo map, not a proof engine: use it to find symbols and call edges quickly, then confirm literals, cron boundaries, dynamic-dispatch gaps, and production-path claims with targeted file reads or text search.

## Activation

Use this skill when a task asks to:

- find where a function, class, constant, schema, or signal is defined
- trace callers/callees or production paths
- assess blast radius before edits
- compare duplicate definitions or schema drift risk
- validate codegraph setup in Cursor Cloud

Do not use this skill as sole evidence for file-path literals, shell/cron/subprocess boundaries, or final production-path proof.

---

## Operating Rule

```
Codegraph first, grep/read second, edit third.
```

For this repo, that means:

1. Use CodeGraph to find symbols and dependency edges.
2. Use direct file reads/grep to verify production-path details.
3. Only edit after blast-radius is understood.
4. Treat ranker/selector/scoring paths as **gated** even if CodeGraph reports small impact.

### Surface split

| Surface | Role |
| --- | --- |
| CodeGraph MCP | Cursor/Cloud structural navigation |
| CodeGraph CLI | Shell status/query/index/sync |
| Hermes MCP | Fleet + ledger context — **not** a code graph |
| Hermes agents | May use CLI + `common/codegraph_guard.py` — not raw MCP |
| Grep/read | Literals, cron, subprocess, dynamic dispatch |

CodeGraph is healthy and useful, but **bounded**. It is not authority for cron, runtime artifacts, or governance truth.

---

## Startup Check

From the repo root:

```bash
codegraph status
```

Healthy state:

- project path is the current workspace
- index statistics are present
- status says index is up to date

If missing or stale:

```bash
codegraph sync
# or, after branch switches / large changes:
codegraph index
```

Cursor Cloud agents install and maintain codegraph through `.cursor/environment.json`:

- Pin: `@colbymchenry/codegraph@0.9.9`
- Install to `$HOME/.local` (global npm may fail with EACCES on Cloud VMs)
- Then `pip install -r requirements.txt` and `codegraph sync` or `codegraph index`

Cursor MCP launches through `.cursor/mcp.json`:

```bash
codegraph serve --mcp --path ${workspaceFolder}
```

Plumbing baseline: `main` @ `67442e66`. Index ~1,733 files / ~51k nodes / ~115k edges. Re-run `codegraph sync` after large merges; re-run `sync_hermes_skills.py` when `skills/` changes.

**Hermes MCP** (`mcp_server/hermes_server.py`) is read-only fleet context only — it does **not** expose `codegraph_*` tools. Canonical Hermes surfaces (MCP vs gateway vs `run_agent_direct.py`): `docs/hermes_agents/hermes_tools_map.md`. Hermes cron agents that need structural maps use `common/codegraph_guard.py` locally, not Hermes MCP.

**Authority:** Operator WSL is authoritative for cron, `output/hedge_report/`, and knowledge-layer contradiction truth. Cloud builds may report `UNKNOWN_CLOUD_ENV` or first-fire gaps that are expected on VMs without operator crontab.

---

## MCP Tools (Cursor / Cloud Agent)

> **Tool names differ by context.** IDE sessions use **MCP** (`codegraph_search`, …). Shell use **CLI** (`codegraph query`, `codegraph callers`, …). Tables below use MCP names; CLI equivalents are noted inline.

### Main session (use directly)

| Tool | Use for |
| --- | --- |
| `codegraph_search` | Find symbols by name (`codegraph query`) |
| `codegraph_callers` | Upstream: what calls this function |
| `codegraph_callees` | Downstream: what this function calls |
| `codegraph_impact` | Blast radius before edits (`--depth 2` when editing) |
| `codegraph_node` | Single symbol signature + source (`source=true` before edits) |
| `codegraph_trace` | Path between two Python symbols (one call; bridges some dynamic hops) |
| `codegraph_files` | Indexed file tree under a path |
| `codegraph_status` | Index health |

### Sub-agent only (never in main session)

| Tool | Why |
| --- | --- |
| `codegraph_explore` | Returns large source blocks — fills context |
| `codegraph_context` | Builds broad context — same risk |

When the user asks “how does X work?” or “explain the Y system”:

- Spawn a sub-agent / background task for exploration
- Instruction: use `codegraph_explore` as the primary tool (or `codegraph_context` first, then one `codegraph_explore` for bodies)
- Main session stays lightweight: `codegraph_search` → `codegraph_node` → callers/callees only

For a **specific flow** (“how does X reach Y?”): start with `codegraph_trace` from→to, then **one** `codegraph_explore` at the break point — do not rebuild the path with search + repeated callers loops.

---

## Standard Preflight (before ANY code edit)

1. `codegraph_search` for the target symbol/concept
2. `codegraph_node` (with source) for the exact candidate
3. `codegraph_callers` and `codegraph_callees`
4. `codegraph_impact` with `--depth 2` if an edit is being considered
5. `grep` / `read` only to confirm dynamic hops, file paths, or string literals

**Do not edit files until this map is complete.**

Report before proceeding:

- production symbols vs test-only symbols
- ambiguous symbols (disambiguate by file path)
- dynamic-dispatch gaps
- file-path literals requiring grep/read
- classification: **safe** / **gated** / **blocked**

### Impact gating

- If `codegraph_impact` returns **> 10 direct consumers**: mark **GATED** — operator approval required
- If impact touches **selector, ranker, sizing, final_score, decision_engine, production KG, snapshot writer/schema**: mark **BLOCKED** — stop and report (architecture freeze applies)

### Pre-edit source check

- Use `codegraph_node` with `source=true` for the function body only
- Read the full file only when surrounding context is required (e.g. `run_screen.py` is 4000+ lines)

### Affected tests (pre-commit)

```bash
git diff --name-only | codegraph affected --stdin --quiet
```

If output is non-empty, run those tests before committing.

---

## Standard Workflow (symbol lookup)

1. Search: `codegraph_search("save_validation_snapshot")` / CLI `codegraph query "save_validation_snapshot"`
2. Disambiguate common names by file/path before conclusions
3. Direction: `codegraph_callers` / `codegraph_callees`
4. Before edits: `codegraph_impact("SNAPSHOT_COLUMNS", depth=2)`
5. Confirm non-static edges (paths, cron, subprocess) with grep/read

### Practical CLI examples

```bash
codegraph status
codegraph sync                    # small changes
codegraph query "save_validation_snapshot"
codegraph callers save_validation_snapshot
codegraph impact save_validation_snapshot --depth 2
```

Full reindex only after a major merge or branch switch:

```bash
codegraph index
codegraph status
```

---

## Biotech-Specific Patterns

### Snapshot / rankings path

Known split:

- Live: `run_screen.py -> save_validation_snapshot() -> _write_snapshot()`
- Bundle/backfill: `scripts/run_screen_from_bundle.py -> main() -> run_batch() -> run_screen_for_date() -> _write_snapshot()`

Always clarify which path is in scope and confirm `"rankings.csv"` or other output path literals outside codegraph.

### Signal input tracing

Use callers/callees on the composer; `codegraph_node` for parameter signatures; trace upstream callers that construct `z_*` inputs. Fields: `clinical_score`, `final_score`, `financial_score`, expectation-layer. Separate production callers from tests.

### Governance boundary (before any change)

Classify whether the change touches: selector, ranker, sizing, final_score, decision_engine, production KG, snapshot writer/schema.

- If yes: **GATED** — stop and report
- If no: explain why it is plumbing / test / docs only

### Drift-risk checks

For duplicate constants or schema lists: `codegraph_search` + `codegraph_impact`, then inspect the authoritative definition.

Known example:

- `SNAPSHOT_COLUMNS` in `run_screen_columns.py`
- duplicate list in `scripts/run_screen_from_bundle.py`

Guardrail: `tests/test_contract_output_schemas.py` contract 6 (bundle vs live column parity).

### Blast-radius review (before accepting a patch)

On each changed function: `codegraph_impact` + callers + callees.

Report: direct callers/callees, production vs test consumers, affected artifacts, classification **safe / gated / blocked**.

---

## Reindexing (WSL / manual sync)

Git hooks are intentionally declined (WSL `/mnt/` path). Reindex explicitly:

- After small changes (< 10 files): `codegraph sync`
- After merges / branch switches / generated code: `codegraph index`
- Before serious dependency tracing: verify with `codegraph status`

---

## Limits and Required Fallbacks

| Area | Codegraph use | Required fallback |
| --- | --- | --- |
| Symbol definitions | `query`, `codegraph_search` | file read when editing |
| Call direction | `callers`, `callees` | inspect dynamic dispatch at break point |
| Flow paths | `codegraph_trace` | `codegraph_node` + grep/read; do not infer missing edges |
| File names / strings | candidate symbol location only | targeted grep/read |
| Cron / shell / subprocess | orienting only | crontab / script boundary on operator host |
| Common names | search candidates | file-qualified disambiguation |

If `codegraph_trace` reports dynamic dispatch: **STOP**, report the break point, inspect manually.

Codegraph proof is **partial** unless: symbol is file-disambiguated, dynamic breaks inspected, path literals confirmed, cron/shell verified, production vs test separated.

---

## Output Checklist

When reporting codegraph findings, include:

- production symbols
- test-only symbols
- ambiguous symbols
- dynamic-dispatch gaps
- file-path literals needing confirmation
- safe / gated / blocked classification
- recommended next action

---

## Recursive improvement

When a session fixes a repeatable CodeGraph mistake (MCP vs CLI, stale pin, preflight skip, dynamic-dispatch gap):

1. Log in `.learnings/LEARNINGS.md` with `Pattern-Key` and `Skill-Path: codegraph`
2. After 3x recurrence, promote to `.learnings/memory.md` or patch this skill
3. `sync_hermes_skills.py` + `audit_hermes_skills.py` + `harvest_log.md` entry

Meta loop: `skills/self-improving/SKILL.md`

## References

| Resource | Path |
| --- | --- |
| Cursor rule (preflight + gating) | `.cursor/rules/codegraph.mdc` |
| Operator runbook | `docs/CODEGRAPH_RUNBOOK.md` |
| Hermes guard (cron agents) | `common/codegraph_guard.py` |
| Hermes skill mirror | `docs/hermes_skills/codegraph.md` (sync via `tools/sync_hermes_skills.py --only codegraph`) |
| Self-improvement loop | `skills/self-improving/SKILL.md` |
