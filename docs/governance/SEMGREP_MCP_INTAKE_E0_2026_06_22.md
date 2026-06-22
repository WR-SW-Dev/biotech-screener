# Semgrep MCP — Package E0 Intake Evaluation

**Date:** 2026-06-22  
**Evaluator:** operator  
**Phase:** E0 — evidence-only; no installation, no Hermes config edit, no cron  
**Decision gate:** go/no-go for E1 sandboxed trial  
**Next step (if GO):** E1 — manual stdio trial, sandboxed, non-registered

---

## 0. Critical disambiguation

Two distinct packages exist. **Only the canonical form is evaluated here.**

| Package | Form | Version | Status |
|---|---|---|---|
| `semgrep-mcp` on PyPI | `uvx semgrep-mcp` | 0.9.0 | **DEPRECATED** — only tool is `deprecation_notice` |
| `semgrep mcp` (built-in) | `semgrep mcp` (subcommand of `semgrep` binary) | `semgrep==1.167.0` | **CANONICAL** — 7 functional tools |

The deprecated package instructs callers to switch to the canonical form. Any E1 trial or Hermes registration must reference `semgrep==1.167.0`, not `uvx semgrep-mcp`.

---

## 1. Source identification

| Field | Value |
|---|---|
| **Binary** | `semgrep` (CLI) |
| **Version** | `1.167.0` |
| **MCP entrypoint** | `semgrep mcp` subcommand |
| **Source path (installed)** | `/home/arrenchulz/.local/share/uv/tools/semgrep/lib/python3.11/site-packages/semgrep/mcp/` |
| **Install command (pinned)** | `uv tool install semgrep==1.167.0` |
| **Repo** | `github.com/semgrep/semgrep` (OSS engine + MCP server) |
| **PyPI dist-info** | `semgrep-1.167.0.dist-info` |

The `semgrep/mcp/` directory contains 15 Python files: `server.py`, `semgrep.py`, `semgrep_context.py`, `models.py`, `hooks/{inject_secure_defaults,post_tool,settings,stop,supply_chain}.py`, `utilities/{token_verifier,tracing,utils}.py`.

---

## 2. License review

| Field | Value |
|---|---|
| **SPDX expression** | `LGPL-2.1-or-later` |
| **Source** | `semgrep-1.167.0.dist-info/METADATA` |
| **Rubric verdict** | **REVIEW** — copyleft; operator sign-off required |

LGPL-2.1 permits use as a library and execution of the tool without imposing copyleft on calling code, provided the semgrep binary is not statically linked into a proprietary artifact. For internal diagnostic use (eval/trial, not distribution), LGPL-2.1 is generally acceptable. **Operator must sign off before full admission.**

Note: the deprecated `semgrep-mcp` 0.9.0 package used MIT; the canonical `semgrep` package is LGPL-2.1-or-later throughout.

---

## 3. Tool list

All 7 tools confirmed via `tools/list` JSON-RPC at startup with `semgrep==1.167.0`:

| Tool | Description | Write-capable? | Network? | Auth required? | Expose in E1? |
|---|---|---|---|---|---|
| `get_supported_languages` | Returns list of languages Semgrep supports | No | No | No | **YES** |
| `semgrep_scan` | Runs Semgrep on provided code content; writes to `/tmp/semgrep_scan_*` (cleaned on exit) | Temp only | No | No | **YES** |
| `semgrep_scan_with_custom_rule` | Same as above but accepts a custom YAML rule string | Temp only | No | No | **YES** |
| `semgrep_rule_schema` | Fetches Semgrep rule YAML schema — calls `raw.githubusercontent.com` + `semgrep.dev` | No | **YES** (GET) | No | NO (remote fetch) |
| `get_abstract_syntax_tree` | Returns AST for provided code; writes temp file to `/tmp/` | Temp only | No | No | **DEFER** |
| `semgrep_findings` | Fetches findings from Semgrep AppSec Platform API | No | **YES** (GET+POST) | **YES** (`SEMGREP_APP_TOKEN`) | **NO** |
| `semgrep_scan_supply_chain` | Supply-chain scan of a workspace directory | Temp only | **YES** (auth call) | **YES** | **NO** |

**E1 proposed allowlist:** `get_supported_languages`, `semgrep_scan`, `semgrep_scan_with_custom_rule`

---

## 4. Per-tool disable env vars

The canonical server registers a `TOOL_DISABLE_ENV_VARS` dict (confirmed `server.py:1354`):

```
SEMGREP_RULE_SCHEMA_DISABLED=true         → disables semgrep_rule_schema
GET_SUPPORTED_LANGUAGES_DISABLED=true     → disables get_supported_languages
SEMGREP_FINDINGS_DISABLED=true            → disables semgrep_findings
SEMGREP_SCAN_WITH_CUSTOM_RULE_DISABLED=true → disables semgrep_scan_with_custom_rule
SEMGREP_SCAN_DISABLED=true                → disables semgrep_scan
SEMGREP_SCAN_REMOTE_DISABLED=true         → disables semgrep_scan_remote (not in tools/list)
GET_ABSTRACT_SYNTAX_TREE_DISABLED=true    → disables get_abstract_syntax_tree
SEMGREP_SCAN_SUPPLY_CHAIN_DISABLED=true   → disables semgrep_scan_supply_chain
```

For E1, set `SEMGREP_FINDINGS_DISABLED=true SEMGREP_SCAN_SUPPLY_CHAIN_DISABLED=true SEMGREP_RULE_SCHEMA_DISABLED=true`.

---

## 5. Network and credential behavior

### 5.1 Telemetry / tracing

- **Default endpoint:** `https://telemetry.dev2.semgrep.dev/v1/traces` (OpenTelemetry OTLP)
- **Disable:** `SEMGREP_MCP_DISABLE_TRACING=true` (confirmed `utilities/tracing.py:199`)
- **Separate from binary metrics:** `SEMGREP_SEND_METRICS=off` disables semgrep CLI metrics; `SEMGREP_MCP_DISABLE_TRACING=true` disables MCP tracing spans. **Both must be set** for a fully offline trial.

### 5.2 Per-tool network activity

| Tool | Endpoint(s) | Verb | Trigger |
|---|---|---|---|
| `semgrep_findings` | `semgrep.dev/api/v1/findings` | GET+POST | explicit tool call; requires `SEMGREP_APP_TOKEN` |
| `semgrep_rule_schema` | `raw.githubusercontent.com/semgrep/semgrep-interfaces/.../rule_schema_v1.yaml`; `semgrep.dev/api/schema_url` | GET | explicit tool call |
| `inject_secure_defaults` hook | `raw.githubusercontent.com/tldrsec/awesome-secure-defaults/main/README.md` | GET | background at startup; result cached to `/tmp/semgrep-mcp/claude-secure-defaults-cache.md` |
| `stop` hook | None (temp file `/tmp/semgrep-mcp/edited-files.json`) | — | session end |
| `get_abstract_syntax_tree` | None (writes to `/tmp/`) | — | explicit tool call |
| `semgrep_scan`, `semgrep_scan_with_custom_rule` | None (subprocess + temp dir `/tmp/semgrep_scan_*`) | — | explicit tool call |
| `semgrep_scan_supply_chain` | May call `semgrep.dev` for supply-chain data | GET | explicit tool call |

**Startup network call (background):** `inject_secure_defaults` hook fetches from `raw.githubusercontent.com` at startup, caches to `/tmp/semgrep-mcp/`. This call occurs on every fresh session unless the cache is fresh. For an offline E1, this must be blocked or the cache pre-populated.

### 5.3 Credentials

- `SEMGREP_APP_TOKEN` — used by `semgrep_findings` and potentially `semgrep_scan_supply_chain`. Not required for the 3-tool E1 allowlist.
- No credentials read from `.env` files, git config, or OS keychain.

---

## 6. Semgrep supply-chain scan

**Scan command:**
```
SEMGREP_SEND_METRICS=off semgrep --config .semgrep/mcp-supply-chain.yml \
  /home/arrenchulz/.local/share/uv/tools/semgrep/lib/python3.11/site-packages/semgrep/mcp/
```

**Result:** 16 findings across 15 files (7 rules, 100% parse coverage)

| Rule | Count | Severity |
|---|---|---|
| `sc-mcp-tool-writes-filesystem` | 5 | ERROR |
| `sc-mcp-tool-spawns-subprocess` | 1 | ERROR |
| `sc-mcp-outbound-http` | 10 | WARNING |
| **Total** | **16** | — |

### Finding triage

**SC-W1 × 5 — filesystem writes**

| File | Line | Code | Triage |
|---|---|---|---|
| `hooks/inject_secure_defaults.py` | 88 | `CACHE_FILE.write_text(content)` | **ACCEPT** — writes to `/tmp/semgrep-mcp/claude-secure-defaults-cache.md`; no repo writes |
| `hooks/stop.py` | 86 | `with open(CACHE_FILE, "w")` | **ACCEPT** — writes to `/tmp/semgrep-mcp/edited-files.json`; no repo writes |
| `server.py` | 271 | `with open(temp_file_path, "w") as f:` | **ACCEPT** — creates `/tmp/semgrep_scan_*/`; cleaned in `finally` block via `shutil.rmtree` |
| `server.py` | 811 | `with open(rule_file_path, "w") as f:` | **ACCEPT** — writes rule YAML to `/tmp/semgrep_scan_*/`; cleaned in `finally` |
| `server.py` | 874 | `with open(temp_file_path, "w") as f:` | **ACCEPT** — writes code file to `/tmp/semgrep_scan_*/`; cleaned in `finally` |

All 5 filesystem writes are bounded to `/tmp/semgrep-mcp/` or `/tmp/semgrep_scan_*/`. No writes to the repo, artifacts directory, or credentials. Cleanup is present.

**SC-W2 × 1 — subprocess**

| File | Line | Code | Triage |
|---|---|---|---|
| `semgrep.py` | 105 | `process = subprocess.run(await create_args(args), ...)` | **ACCEPT (with note)** — this IS the core function: spawning the `semgrep` CLI. The subprocess is the semgrep binary itself (found via PATH lookup in `find_semgrep_info()`). Args are constructed from an allowlist (`["scan", "--json", "--experimental", ...]`), not from user-supplied shell strings. No shell=True, no command injection surface. |

**SC-N1 × 10 — outbound HTTP**

| File | Lines | Destination | Trigger | Triage |
|---|---|---|---|---|
| `server.py` | 526–532 | `semgrep.dev/api/schema_url` + `raw.githubusercontent.com` | `semgrep_rule_schema` tool call | **CONTROL** — disable `SEMGREP_RULE_SCHEMA_DISABLED=true` in E1 |
| `server.py` | 588 | `semgrep.dev` (findings auth check) | `semgrep_findings` startup or tool call | **CONTROL** — disable `SEMGREP_FINDINGS_DISABLED=true` in E1 |
| `server.py` | 737 | `semgrep.dev` (findings POST) | `semgrep_findings` tool call | **CONTROL** — disabled with above |
| `server.py` | 1319 | `raw.githubusercontent.com/semgrep/semgrep-interfaces/...` | `get_abstract_syntax_tree` tool call | **DEFER** — disable `GET_ABSTRACT_SYNTAX_TREE_DISABLED=true` in E1 |
| `server.py` | 1334 | `semgrep.dev/c/r/{rule_id}` | resource handler (not a tool) | **ACCEPT** — resource URL, not auto-triggered; only fires on explicit resource fetch |
| `utilities/utils.py` | 174, 247, 342, 386 | `semgrep.dev` (OAuth, deployment, org info) | auth flows when `SEMGREP_APP_TOKEN` present | **ACCEPT** — only fires if token is set; E1 will not set token |

---

## 7. Constrained-mode assessment

### E1 env var set

```bash
SEMGREP_MCP_DISABLE_TRACING=true
SEMGREP_SEND_METRICS=off
SEMGREP_FINDINGS_DISABLED=true
SEMGREP_SCAN_SUPPLY_CHAIN_DISABLED=true
SEMGREP_RULE_SCHEMA_DISABLED=true
GET_ABSTRACT_SYNTAX_TREE_DISABLED=true
# Do NOT set SEMGREP_APP_TOKEN
```

With this set:
- Tracing to `telemetry.dev2.semgrep.dev` → **disabled**
- `semgrep_findings` (auth + POST) → **disabled**
- `semgrep_scan_supply_chain` (auth) → **disabled**
- `semgrep_rule_schema` (remote fetch) → **disabled**
- `get_abstract_syntax_tree` (deferred) → **disabled**
- Active tools: `get_supported_languages`, `semgrep_scan`, `semgrep_scan_with_custom_rule`

### Remaining network exposure

- `inject_secure_defaults` hook (background, at startup): fetches `raw.githubusercontent.com/tldrsec/awesome-secure-defaults/main/README.md` to `/tmp/semgrep-mcp/`. **This call occurs regardless of tool disable vars.** For offline E1: pre-create the cache file or accept the one-time fetch. This is not suppressible via env var in the canonical 1.167.0 source.

### Rule config for E1

- Do **not** use `auto` config — it requires semgrep.dev connectivity and would fail or produce unexpected results.
- Use `--config <absolute-path>` pointing to a local `.semgrep/` rule file.
- For scan-biotech-mcp trial: `--config /mnt/c/Projects/biotech_screener/biotech-screener/.semgrep/mcp-supply-chain.yml`

### Temp file scope

All temp writes are to `/tmp/semgrep_scan_*` (via `tempfile.mkdtemp(prefix="semgrep_scan_")`), cleaned in `finally`. Verified from `server.py:261–193` (the `create_temp_files_from_code_content` function with `shutil.rmtree` in except block). No writes to the biotech-screener repo, artifacts, or `~/.hermes/`.

---

## 8. Rubric evaluation

| # | Criterion | Status | Notes |
|---|---|---|---|
| 1 | Source pinned | **PASS** | `semgrep==1.167.0`; install via `uv tool install semgrep==1.167.0` |
| 2 | License reviewed | **REVIEW** | LGPL-2.1-or-later; internal non-distribution use acceptable; **operator sign-off required** before full admission |
| 3 | Tool list enumerated | **PASS** | 7 tools listed; 3 proposed for E1 allowlist |
| 4 | Write tools disabled | **CONDITIONAL PASS** | No repo writes; temp-only writes acceptable; `semgrep_findings` + `semgrep_scan_supply_chain` + `semgrep_rule_schema` + `get_abstract_syntax_tree` must be disabled via env vars in E1 |
| 5 | Network/cred behavior | **DOCUMENTED** | Full table above; startup background fetch (`inject_secure_defaults`) not suppressible; E1 env set disables auth-dependent calls |
| 6 | Semgrep scan | **TRIAGED** | 16 findings: 5× SC-W1 (temp-only, ACCEPT), 1× SC-W2 (core subprocess, ACCEPT), 10× SC-N1 (CONTROL/ACCEPT per table) |
| 7 | Local dry-run | **DEFERRED** | E0 is evidence-only; E1 will execute dry-run and record output |
| 8 | Governance memo | **PASS** | This document committed; `MCP_SERVER_INTAKE_RUBRIC.md` candidate table updated in same commit |

---

## 9. E1 go/no-go recommendation

**Decision: GO for E1 sandboxed trial**

### Rationale

All 3 scan-capable tools (`get_supported_languages`, `semgrep_scan`, `semgrep_scan_with_custom_rule`) are:
- Local-only: no outbound HTTP
- Temp-bounded: write only to `/tmp/semgrep_scan_*`, cleaned on exit
- No auth: no `SEMGREP_APP_TOKEN` required
- Subprocess-bounded: spawns only the `semgrep` binary with a fixed arg list

The 4 network-dependent tools are suppressible via env vars. The LGPL-2.1 license permits internal use. The supply-chain scan findings are all individually triaged and acceptable under conditions.

### E1 acceptance criteria

> "Can Semgrep MCP scan a fixture repo and `tools/biotech_mcp_server.py` with zero writes to the repo and predictable output?"

E1 passes if:
1. `tools/list` returns exactly 3 tools after applying the disable env vars above
2. `get_supported_languages` returns a deterministic list without network calls
3. `semgrep_scan` against `tools/biotech_mcp_server.py` with `.semgrep/mcp-supply-chain.yml` returns 0 findings (matching the manually-run scan result)
4. No files written outside `/tmp/` (verify with `inotifywait` or `strace -e write` on the trial)
5. No outbound connections made during the trial (verify with `ss -tnp` snapshot before/after, or network namespace)

### E1 constraints (non-negotiable)

- **NOT** registered in `~/.hermes/config.yaml`
- **NOT** added to any Hermes job or cron
- Run manually via `semgrep mcp` stdio with the env vars above
- Local rule config file only (no `auto`, no `p/` registry)
- Session scoped: kill the process after each trial; do not leave daemon running

### E1 non-goal (explicit)

> "Add Semgrep MCP to the agent stack" — this is NOT the E1 goal.

Full Hermes registration (Package F, if it occurs) requires: E1 passing, operator LGPL sign-off, and a separate governance commit following the rubric.

---

## 10. Open items before Hermes admission (Package F, not yet authorized)

| Item | Status |
|---|---|
| LGPL-2.1 operator sign-off | **PENDING** |
| `inject_secure_defaults` startup fetch — suppression strategy | **OPEN** (no env var; accept or pre-seed cache) |
| E1 dry-run output recorded | **DEFERRED** — requires E1 execution |
| Hermes `tools.include` allowlist config drafted | **DEFERRED** — post E1 |

---

*Package E0 complete. E1 proceeds as a sandboxed manual stdio trial; no Hermes config changes authorized.*
