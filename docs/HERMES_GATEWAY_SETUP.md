# Hermes Gateway & LLM Model Routing

**Last updated**: 2026-06-16  
**Status**: Operator-host config is live source of truth (not this file alone)

---

## Hermes Agent v0.16.0 update check (operator WSL only)

Public release metadata shows **Hermes Agent v0.16.0 / v2026.6.5**
("The Surface Release") published on 2026-06-06 with release date
2026-06-05. This Cloud checkout has no `hermes` CLI or
`~/.hermes/hermes-agent`, so the live installed version must be checked on
operator WSL.

Run on operator WSL:

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener

# Identify current install and version.
command -v hermes
hermes version || hermes --version

# Non-mutating update preflight.
hermes update --check
```

Before applying v0.16.0, preserve the live operator config and state:

```bash
backup_dir="$HOME/hermes-backup-$(date +%F-%H%M%S)"
mkdir -p "$backup_dir"
cp -a "$HOME/.hermes/config.yaml" "$backup_dir/config.yaml"
cp -a "$HOME/.hermes/skills" "$backup_dir/skills"
sha256sum "$HOME/.hermes/config.yaml" > "$backup_dir/config.yaml.sha256"
```

Then update only after the backup exists:

```bash
hermes update
hermes version || hermes --version
hermes config check
hermes doctor
hermes gateway status
```

**v0.16.0 caution:** a reported 0.16.0 issue can rewrite
`$HERMES_HOME/config.yaml` on the first config persistence after upgrade and
drop hand-curated `custom_providers` / comments. After the first post-update
launch or dashboard/config write, compare the config against the backup:

```bash
sha256sum "$HOME/.hermes/config.yaml"
diff -u "$backup_dir/config.yaml" "$HOME/.hermes/config.yaml" | sed -n '1,160p'
```

If the config expands to defaults or loses provider blocks, restore the backup
and re-run `hermes config migrate` manually before restarting gateway.

---

## Stale-doc notice (read first)

This file **replaced** the 2026-05-13 version that described:

1. Primary: OpenRouter **Claude Sonnet 4.6** (out of credits)  
2. Fallback: **Together Llama 3.3 70B**  
3. Backup: **Nous Trinity**

That predates the **2026-05-20+** fleet intent documented in `docs/hermes_skills/screener-ops.md`, `agents/*/SOUL.md`, and `.cursor/rules/hermes-context.mdc`:

- **Fleet SOUL intent**: `deepseek/deepseek-v4-flash:free` via **OpenRouter**
- **Gateway fix**: OpenRouter primary confirmed **2026-05-25** on operator WSL (session notes)

**Live routing** is always **`~/.hermes/config.yaml` on operator WSL**. Re-verify after every `git pull` that touches Hermes docs (acceptance gate below).

---

## Hermes model routing is surface-specific

Do not assume one model applies to all “Hermes” paths.

| Layer | Truth source | Model / LLM? |
|-------|----------------|--------------|
| **Hermes MCP** (Cursor) | Repo: `mcp_server/hermes_server.py` | **No model** — read-only registry, SOUL, knowledge artifacts |
| **Lane A Hermes jobs** | Registry + `agents/hermes-*/run_job.py` | **No model** — `llm_policy: none`, deterministic |
| **Hermes Gateway / CLI** | Operator WSL `~/.hermes/config.yaml` | **Yes** — verify live on WSL |
| **Fleet SOUL intent** | `agents/*/SOUL.md`, `screener-ops.md`, `hermes-context.mdc` | **`deepseek/deepseek-v4-flash:free`** (OpenRouter) |
| **`run_agent_direct.py`** | Repo: `tools/run_agent_direct.py` | **Bypasses Hermes Gateway**; defaults to **Together Llama** unless `--model` overrides |

Canonical taxonomy: [`docs/hermes_agents/hermes_tools_map.md`](hermes_agents/hermes_tools_map.md) (§ Hermes model routing).

**Defer code changes** to `run_agent_direct.py` until WSL confirms desired live gateway routing. A separate PR may add OpenRouter/DeepSeek to the direct-bypass path so cron matches SOUL intent — that is a **behavior change**, not documentation.

---

## Operator acceptance gate (after doc merge)

Run on **operator WSL** only:

```bash
cd /mnt/c/Projects/biotech_screener/biotech-screener
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

**Expected healthy state** (2026-05-20+ intent):

- `model.provider`: **openrouter** (or equivalent primary)
- `model.default`: **`deepseek/deepseek-v4-flash:free`** active or default
- No forced **Claude-only / Together-only** legacy primary without operator approval

If output still shows Claude Sonnet primary with Llama as the only working route, update `~/.hermes/config.yaml` on WSL — do not infer from this repo doc alone.

Optional smoke:

```bash
hermes gateway status
hermes chat -q "Reply with only the model id you are using." -Q
```

---

## Configuration file (operator WSL)

**Location**: `~/.hermes/config.yaml` (not in git)

**Illustrative** shape (keys vary by Hermes Agent version — verify on host):

```yaml
model:
  default: deepseek/deepseek-v4-flash:free   # fleet intent 2026-05-20+
  provider: openrouter
  base_url: https://openrouter.ai/api/v1

providers:
  together:
    base_url: https://api.together.xyz/v1
    api_key: <set on host>                   # systemd may need embedded key
    default_model: meta-llama/Llama-3.3-70B-Instruct-Turbo

fallback_providers:
  - provider: together
    model: meta-llama/Llama-3.3-70B-Instruct-Turbo
    base_url: https://api.together.xyz/v1
  # Optional backup providers (e.g. nous) — operator-defined
```

**Historical reference** (2026-05-13, superseded): primary `anthropic/claude-sonnet-4.6` on OpenRouter with Together Llama fallback when OpenRouter returned HTTP 402.

### Bash environment

`TOGETHER_API_KEY` and OpenRouter credentials belong in operator env (`~/.bashrc` and/or embedded in `config.yaml` for `hermes-gateway.service`). Systemd user units do not load bashrc unless configured.

---

## Gateway service

| Property | Typical value |
|----------|----------------|
| Process | Hermes Agent (version on host: `hermes gateway status`) |
| Service | `hermes-gateway.service` (systemd user) |
| Port | 8642 |
| OpenClaw | May delegate LLM inference through Hermes — separate from MCP |

### Commands

```bash
hermes gateway status
hermes gateway restart    # after config.yaml edits
journalctl --user-unit hermes-gateway -f
```

### Interactive chat

```bash
hermes chat
hermes chat -q "your query"
hermes chat -q "query" -Q    # response only
```

Cascade behavior (when fallbacks are configured) may log provider switches — inspect gateway logs; do not assume 2026-05-13 “402 → Llama” is still the steady state.

---

## Direct-bypass path (repo, not gateway)

Scheduled or cron invocations that call **`tools/run_agent_direct.py`** do **not** read `~/.hermes/config.yaml`.

| Property | Value |
|----------|--------|
| Default model | `meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| Provider | Together AI (`TOGETHER_API_KEY`) |
| Routing | `llama` in model name → Together; else → Anthropic SDK |
| Registry name | `direct_llama_on_anomaly` (historical label) |

See [`docs/ops/hermes_openclaw_routing_policy.md`](ops/hermes_openclaw_routing_policy.md) and [`docs/ops/token_budget_policy.md`](ops/token_budget_policy.md) (Tier 1 still documents Llama for this path).

---

## Known operator issues (retained)

### Together API HTTP 401 from gateway

**Cause**: API key only in bashrc; systemd service cannot resolve `$TOGETHER_API_KEY`.

**Fix**: Embed key in `~/.hermes/config.yaml` fallback sections and/or `hermes auth add together …`; `hermes gateway restart`.

### Compression model context mismatch

Gateway may warn when auxiliary compression model context is smaller than main model threshold. Adjust `auxiliary.compression` or `compression.threshold` in `config.yaml` per Hermes Agent docs.

---

## Governance

- **Hermes MCP** (IDE): read-only — never schedules models  
- **Lane A** `hermes-*` jobs: no LLM tokens  
- **Gateway / CLI**: operator-controlled model policy on WSL  
- **OpenClaw**: see [`docs/hermes_agents/hermes_tools_map.md`](hermes_agents/hermes_tools_map.md) OpenClaw section when present on `main`  
- No ranker/selector/scoring changes via gateway config

---

## Related

| Doc | Topic |
|-----|--------|
| [`docs/hermes_agents/hermes_tools_map.md`](hermes_agents/hermes_tools_map.md) | Full Hermes surface taxonomy + model table |
| [`docs/hermes_skills/screener-ops.md`](hermes_skills/screener-ops.md) | Fleet model migration 2026-05-20 |
| [`.cursor/rules/hermes-context.mdc`](../.cursor/rules/hermes-context.mdc) | Cursor bootstrap fleet model note |
| [`docs/ops/hermes_openclaw_routing_policy.md`](ops/hermes_openclaw_routing_policy.md) | Lanes A/B/C |
| [`tools/run_agent_direct.py`](../tools/run_agent_direct.py) | Direct API bypass (Llama default) |

---

## Sequencing (recommended)

1. **Docs-only PR** (this file + tools map) — clarify surfaces; no code  
2. **WSL verification** — acceptance gate above  
3. **Optional code PR** — OpenRouter/DeepSeek in `run_agent_direct.py` only if cron/direct path must match SOUL intent
