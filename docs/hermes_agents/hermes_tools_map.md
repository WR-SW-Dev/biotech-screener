# Hermes Tools Map

Last updated: 2026-05-30

Canonical taxonomy for Hermes in this repo. **Hermes is not one thing** — it is four related surfaces plus a monitoring feed. Use this map before invoking tools so layers are not conflated.

> **Governance rule (non-negotiable):** Cursor MCP Hermes tools are **read-only** and must never mutate registry, cron, scoring, snapshots, skills, or governance artifacts. IDE convenience must not become a production-control surface.

## Surface overview

| Surface | Authority | Mutation risk | Primary entry |
|---------|-----------|---------------|---------------|
| **Cursor MCP** | IDE read interface | Read-only | `.cursor/mcp.json` → `mcp_server.hermes_server` |
| **Repo Python tools** | Deterministic ops in git | Builds artifacts, syncs docs | `tools/*.py` |
| **Lane A governance jobs** | Explicit `run_job.py` invocations | Town events + reads; no LLM | `agents/hermes-*/run_job.py` |
| **Skills + operator CLI** | Skill bodies + WSL runtime | Drift if `~/.hermes` stale | `docs/hermes_skills/`, `hermes -s …` |
| **Monitoring stack** | Ops signal producers | Writes heartbeat/supervisor artifacts | `tools/agent_heartbeat_checks.py`, etc. |

Related docs: [`operator_host_skills.md`](operator_host_skills.md) (skills sync + `~/.hermes`), [`agent_roster.md`](agent_roster.md) (fleet vs scheduler), [`HERMES_GATEWAY_SETUP.md`](../HERMES_GATEWAY_SETUP.md) (gateway model + WSL gate).

---

## 1. Cursor MCP tools

**Read-only.** Config: [`.cursor/mcp.json`](../../.cursor/mcp.json). Server:

```bash
python3 -m mcp_server.hermes_server
python3 -m mcp_server.hermes_server --health
```

Tests: [`tests/test_hermes_mcp_server.py`](../../tests/test_hermes_mcp_server.py).

| Tool | Purpose |
|------|---------|
| `fleet_context_snapshot` | One-call bootstrap: registry summary, knowledge artifact availability, fleet constraints |
| `agents_list` | List `agents/AGENT_REGISTRY.json` entries (optional `status`, `include_heartbeat`) |
| `agents_get` | One agent: registry row + bounded IDENTITY/SOUL/HEARTBEAT/TOOLS metadata |
| `skills_read` | Read **`agents/<name>/SOUL.md`** (agent behavior — not skill mirror files) |
| `knowledge_read` | Read built ops artifacts (table below) |

### `knowledge_read` artifacts

| `artifact` argument | Repo paths (first match wins) |
|---------------------|-------------------------------|
| `knowledge_layer`, `latest_state`, `state` | `artifacts/ops/knowledge_layer/latest_state.{json,md}` |
| `held_spec_ledger` | `artifacts/ops/held_spec_ledger/latest.{json,md}` |
| `contradiction_ledger` | `artifacts/ops/contradiction_ledger/latest.{md,json}` |
| `first_fire_ledger` | `artifacts/ops/first_fire_ledger/latest.{json,md}` |

If missing: run `python3 tools/build_hermes_knowledge_layer.py` on the operator host.

### Cursor bootstrap sequence

1. `fleet_context_snapshot()`
2. `knowledge_read(artifact="held_spec_ledger")`
3. `knowledge_read(artifact="contradiction_ledger")` when changing constrained areas
4. `agents_get(name="…")` + `skills_read(name="…")` before editing that agent

---

## 2. Repo Python tools

Deterministic scripts in `tools/`. These **can** write repo artifacts and docs; they are not MCP tools.

| Script | Role |
|--------|------|
| [`tools/build_hermes_knowledge_layer.py`](../../tools/build_hermes_knowledge_layer.py) | Spec 089 **Hermeslink** ops brain: git, crontab, registry, held specs, contradiction checks C1–C5 → `artifacts/ops/*` |
| [`tools/sync_hermes_skills.py`](../../tools/sync_hermes_skills.py) | `skills/` → `docs/hermes_skills/`; maintains `_meta.json` (`source_authority`) |
| [`tools/audit_hermes_skills.py`](../../tools/audit_hermes_skills.py) | Registry coverage, authority completeness, mirror drift vs `skills/` |
| [`tools/agent_preflight.py`](../../tools/agent_preflight.py) | Pre-dispatch governance report (used by `run_agent_direct.py`) |
| [`tools/notify_cron_missed.py`](../../tools/notify_cron_missed.py) | Town bridge: `cron_missed` events |
| [`tools/smoke_operator_delivery.py`](../../tools/smoke_operator_delivery.py) | Smoke-test Town email (`OPERATOR_DELIVERY_DRY_RUN`) |

### Do not conflate (KG vs Hermeslink)

| Tool | What it is |
|------|------------|
| `tools/build_knowledge_graph.py` | Governance **knowledge graph** (signals/rankings) — **not** Hermes MCP |
| `tools/query_knowledge_graph.py` | Query that graph — **not** Hermeslink |

Hermeslink skill: [`docs/hermes_skills/hermeslink-state-capture.md`](../hermes_skills/hermeslink-state-capture.md).

---

## 3. Lane A governance jobs

Four registry agents: `hermes-held-spec-ledger`, `hermes-first-fire-validator`, `hermes-ruleset-integrity`, `hermes-contradiction-detector`.

| Property | Value |
|----------|--------|
| Policy | `llm_policy: none` — no gateway LLM tokens |
| Cadence | `on_demand` |
| Heartbeat | **SKIP** (not daily freshness checks) |
| Invocation | Explicit only |

```bash
python3 tools/build_hermes_knowledge_layer.py   # artifacts first

python3 agents/hermes-held-spec-ledger/run_job.py
python3 agents/hermes-first-fire-validator/run_job.py
python3 agents/hermes-ruleset-integrity/run_job.py
python3 agents/hermes-contradiction-detector/run_job.py
```

Town delivery: [`common/operator_delivery.py`](../../common/operator_delivery.py) via `send_operator_event`. Default dry-run: `OPERATOR_DELIVERY_DRY_RUN=1` in `.env` until operator sign-off.

Bridge spec: [`docs/hermes_skills/town-operator-bridge.md`](../hermes_skills/town-operator-bridge.md).

---

## 4. Skills and operator CLI

Skill **docs** (procedures) are separate from agent **SOUL** files (behavior).

| Layer | Path |
|-------|------|
| Edit source | `skills/<dir>/SKILL.md`, `skills/<dir>/REFERENCE.md` |
| Hermes mirror | `docs/hermes_skills/*.md` |
| Index | `docs/hermes_skills/_meta.json` (`source_authority` per skill) |
| Optional WSL runtime | `~/.hermes/skills/`, `~/.hermes/skills/devops/` |

Operator CLI (WSL, outside git):

```bash
hermes -s screener-ops "status"
hermes -s codegraph "status"
```

**Rule:** edit `skills/` → `sync_hermes_skills.py` → `audit_hermes_skills.py` → commit → copy to `~/.hermes/` **only if** the gateway reads runtime copies.

Full runbook: [`operator_host_skills.md`](operator_host_skills.md).

Gateway model file and acceptance gate: [`HERMES_GATEWAY_SETUP.md`](../HERMES_GATEWAY_SETUP.md).

---

## 5. Hermes model routing (surface-specific)

**Do not assume one model for all “Hermes” paths.** Each surface has its own truth source.

| Layer | Truth source | Model / LLM? |
|-------|----------------|--------------|
| **Cursor MCP** | `mcp_server/hermes_server.py` | **No** — read-only; no inference |
| **Lane A `hermes-*` jobs** | `AGENT_REGISTRY.json` + `run_job.py` | **No** — `llm_policy: none` |
| **Hermes Gateway / CLI** | Operator WSL `~/.hermes/config.yaml` | **Yes** — **verify live on WSL** |
| **Fleet SOUL intent** | `agents/*/SOUL.md`, `screener-ops.md`, `hermes-context.mdc` | **`deepseek/deepseek-v4-flash:free`** (OpenRouter, 2026-05-20+) |
| **`run_agent_direct.py`** | `tools/run_agent_direct.py` | **Bypasses gateway** — defaults to **Together Llama** unless `--model` set |

### Implications

- **Cursor / Cloud Agent** cannot validate gateway model — no `~/.hermes/config.yaml` on typical cloud VMs.
- **SOUL.md** states fleet intent; **`run_agent_direct.py`** behavior is defined in repo code (Llama default today). Mismatch is documented, not hidden — fix via separate code PR only after WSL acceptance gate.
- Registry enum `direct_llama_on_anomaly` names the **direct-bypass** escalation path, not the Hermes Gateway default.

### Operator acceptance gate (after `git pull`)

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener   # operator WSL
git pull
python3 tools/build_hermes_knowledge_layer.py
python3 tools/audit_hermes_skills.py
python3 -c "
import yaml, pathlib
p = pathlib.Path.home() / '.hermes' / 'config.yaml'
if not p.exists():
    print('MISSING', p)
else:
    d = yaml.safe_load(p.read_text())
    m = d.get('model', {})
    print('model.default:', m.get('default'))
    print('model.provider:', m.get('provider'))
    for fb in d.get('fallback_providers', [])[:3]:
        print('fallback:', fb.get('provider'), fb.get('model'))
"
```

**Healthy (2026-05-20+ intent):** OpenRouter primary; `deepseek/deepseek-v4-flash:free` default/active.  
**Stale:** Claude Sonnet primary with Llama as the only working route — update host config; see [`HERMES_GATEWAY_SETUP.md`](../HERMES_GATEWAY_SETUP.md).

---

## 6. Monitoring stack

Produces ops signals consumed by the knowledge layer and heartbeat. **Not** Hermes MCP tools.

```
tools/agent_heartbeat_checks.py
    → agents/ops_supervisor/supervisor.py
    → tools/run_post_snapshot_supervisor.py
    → tools/agent_supervisor_sentinel.py
```

Also feeds: `artifacts/heartbeat/`, `artifacts/ops_supervisor/`, fleet receipts under `agents/fleet_steward/memory/`.

---

## 7. Standard operator sequences

### Skills hygiene

```bash
python3 tools/sync_hermes_skills.py
python3 tools/audit_hermes_skills.py
```

Expected: 31 Hermes `.md` files, 31 registered in `_meta.json`, no mirror drift.

### Knowledge layer (operator WSL — crontab checks authoritative)

```bash
python3 tools/build_hermes_knowledge_layer.py
python3 agents/hermes-contradiction-detector/run_job.py
```

Cloud VMs without `crontab` may emit `UNKNOWN_CLOUD_ENV` for C1/C3 — not hard failures on the operator host.

### Before LLM agent dispatch

```bash
python3 tools/agent_preflight.py --agent <name> --json
python3 tools/run_agent_direct.py --agent <name> --message "…"   # blocked agents/jobs rejected
```

### After `git pull` on WSL

```bash
git pull origin main
python3 tools/sync_hermes_skills.py && python3 tools/audit_hermes_skills.py
python3 tools/build_hermes_knowledge_layer.py
# Optional: refresh ~/.hermes/skills/ from docs/hermes_skills/ (see operator_host_skills.md)
```

---

## Do not conflate

| Mistake | Truth |
|---------|--------|
| `skills_read` loads Hermes skill docs | It reads **`agents/<name>/SOUL.md`** only |
| Hermes skills live under `agents/` | Skill mirrors live under **`docs/hermes_skills/`** |
| `docs/hermes_skills/` equals `~/.hermes/skills/` | Runtime copies are **optional** and can be stale |
| Hermes MCP mutates production | MCP is **read-only**; use repo tools/jobs for writes |
| One model for all Hermes | **Surface-specific** — see §5; gateway ≠ MCP ≠ `run_agent_direct.py` |
| SOUL DeepSeek = cron uses DeepSeek | Cron via `run_agent_direct.py` defaults to **Llama** until a separate code change |
| `HERMES_GATEWAY_SETUP.md` is live config | **Illustrative**; `~/.hermes/config.yaml` on WSL is truth |
| `build_knowledge_graph.py` is Hermeslink | That is the **governance KG** — use `build_hermes_knowledge_layer.py` |
| Lane A jobs run on heartbeat | Heartbeat **SKIP**s them; run `run_job.py` explicitly |
| Monitoring scripts are Hermes tools | They **feed** ops state; they are not MCP `hermes_*` tools |
| Registry alone defines behavior | **SOUL.md** and runtime scripts override registry for execution |

---

## Quick reference

| I need to… | Use |
|------------|-----|
| Bootstrap in Cursor | MCP `fleet_context_snapshot` |
| Read held specs / contradictions | MCP `knowledge_read` or build knowledge layer first |
| Change a skill procedure | `skills/` → sync → audit |
| Run governance after build | `agents/hermes-*/run_job.py` |
| Check fleet agent behavior | `agents_get` + `skills_read` (SOUL) |
| Avoid split-brain with Hermes CLI | [`operator_host_skills.md`](operator_host_skills.md) |
| Hermes gateway model on WSL | §5 + [`HERMES_GATEWAY_SETUP.md`](../HERMES_GATEWAY_SETUP.md) acceptance gate |
| Direct cron LLM (no gateway) | `run_agent_direct.py` — Together Llama default (documented drift vs SOUL) |
