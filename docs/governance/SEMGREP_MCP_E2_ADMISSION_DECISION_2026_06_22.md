# Semgrep MCP — Package E2 Admission Decision

**Date:** 2026-06-22  
**Phase:** E2 — governance decision memo  
**Verdict:** `ADMIT_WITH_CONSTRAINTS_FOR_MANUAL_USE_ONLY`  
**Registration status:** `DO_NOT_REGISTER_IN_HERMES_YET`

---

## Evidence base

| Document | Status |
|---|---|
| `SEMGREP_MCP_INTAKE_E0_2026_06_22.md` | Complete — evidence dossier |
| `SEMGREP_MCP_E1_SANDBOX_TRIAL_2026_06_22.md` | Complete — sandbox trial PASS |

---

## E0 summary

- **Canonical package:** `semgrep mcp` built into `semgrep==1.167.0`. The `semgrep-mcp`
  PyPI 0.9.0 package is deprecated and exposes only a `deprecation_notice` tool; it is
  not the candidate.
- **License:** LGPL-2.1-or-later. Operator sign-off required before full admission.
  Internal non-distribution use is the expected pattern.
- **7 tools exposed** by the canonical server. Network-dependent tools (`semgrep_findings`,
  `semgrep_scan_supply_chain`, `semgrep_rule_schema`) are controllable via per-tool
  disable env vars; `get_abstract_syntax_tree` deferred.
- **inject_secure_defaults startup fetch:** at every fresh session the server fetches
  `raw.githubusercontent.com/tldrsec/awesome-secure-defaults/main/README.md` and caches
  the result to `/tmp/semgrep-mcp/claude-secure-defaults-cache.md` (24h TTL). There is no
  env var to suppress this in v1.167.0. If offline/air-gapped use is required the cache
  must be pre-seeded before starting the server.
- **Supply-chain scan:** 16 findings (all triaged — temp-only writes, core subprocess,
  outbound HTTP controlled by env vars).

## E1 summary

- **All 6 acceptance criteria met.**
- No repo writes; no `~/.hermes` writes; no cron/jobs changes; no external MCP registered.
- `semgrep_scan_with_custom_rule` on `tools/biotech_mcp_server.py` with
  `.semgrep/mcp-supply-chain.yml` → **0 findings** — matches the manually-run scan.
- `get_supported_languages` returned 50+ languages; no I/O.
- Process exited cleanly (exit code 0).
- **E1 also surfaced two blockers** (see §4).

---

## Admission constraints

### Allowed tools

| Tool | Notes |
|---|---|
| `get_supported_languages` | Pure logic, no I/O, no network |
| `semgrep_scan_with_custom_rule` | Local scan with inline YAML rule; writes to `/tmp/semgrep_scan_*` (auto-cleaned) |

### Excluded tools

| Tool | Reason |
|---|---|
| `semgrep_scan` | **Broken with metrics off:** raises `McpError` when `SEMGREP_SEND_METRICS=off` and `config=None` (no config parameter in its signature). Not usable in the constrained env. |
| `semgrep_findings` | Requires `SEMGREP_APP_TOKEN`; makes POST to `semgrep.dev` API |
| `semgrep_scan_supply_chain` | Requires auth; makes network calls |
| `semgrep_rule_schema` | Fetches from `raw.githubusercontent.com` + `semgrep.dev` |
| `get_abstract_syntax_tree` | Writes temp file; deferred pending further review |

### Operating requirements

| Requirement | Value |
|---|---|
| `SEMGREP_MCP_DISABLE_TRACING` | `true` |
| `SEMGREP_SEND_METRICS` | `off` |
| `SEMGREP_FINDINGS_DISABLED` | `true` |
| `SEMGREP_SCAN_SUPPLY_CHAIN_DISABLED` | `true` |
| `SEMGREP_RULE_SCHEMA_DISABLED` | `true` |
| `GET_ABSTRACT_SYNTAX_TREE_DISABLED` | `true` |
| `SEMGREP_APP_TOKEN` | Must NOT be set |
| Rule config | Local file only — never `auto`, never `p/` registry |
| Process scope | Manual stdio, session-scoped; kill after use |
| Cache pre-seed | Required for offline use (`/tmp/semgrep-mcp/claude-secure-defaults-cache.md`) |

---

## Blockers before Hermes registration

The following must be resolved before `semgrep mcp` can be added to
`~/.hermes/config.yaml`. Each is an independent gate; no ordering implied.

| # | Blocker | Owner | Status |
|---|---|---|---|
| B1 | **Hermes `roots/list` handling** — the server sends `roots/list` server-initiated requests during tool calls. A client that does not respond will crash (`anyio.ClosedResourceError`). Verify that Hermes' MCP client layer handles server-initiated requests correctly, or that a `roots` capability negotiation in the `initialize` handshake suppresses the request. | operator | OPEN |
| B2 | **LGPL-2.1-or-later sign-off** — LGPL-2.1 permits internal use without open-sourcing calling code, but requires explicit operator acknowledgement before the server is added to the production stack. | operator | OPEN |
| B3 | **inject_secure_defaults startup fetch policy** — decide whether the one-time background GET to `raw.githubusercontent.com` at session start is acceptable in production, or whether a permanent cache pre-seed strategy is required. The fetch is not suppressible via env var in v1.167.0. | operator | OPEN |
| B4 | **semgrep_scan usability** — decide whether to accept that `semgrep_scan` is non-functional in the constrained env (register with `tools.include` listing only the 2 approved tools), or wait for an upstream fix / version upgrade that adds a `config` parameter. | operator | OPEN |

---

## Decision

**`ADMIT_WITH_CONSTRAINTS_FOR_MANUAL_USE_ONLY`**

`semgrep mcp` may be used manually (stdio, session-scoped) under the operating
requirements above. The 2-tool constrained set (`get_supported_languages` +
`semgrep_scan_with_custom_rule`) is operationally useful for local rule validation and
biotech-mcp supply-chain checks.

**`DO_NOT_REGISTER_IN_HERMES_YET`**

Hermes registration is blocked on B1–B4 above. The external-MCP workstream is paused
after this memo; B1–B4 are standing open items for a future session.

---

## Change log entry (for MCP_SERVER_INTAKE_RUBRIC.md)

E2 complete: `ADMIT_WITH_CONSTRAINTS_FOR_MANUAL_USE_ONLY`; not registered in Hermes;
B1 (roots/list client handling), B2 (LGPL sign-off), B3 (startup fetch policy),
B4 (semgrep_scan usability) are open blockers for registration.

---

*Semgrep MCP external-MCP workstream paused after E2. Reopen when B1–B4 are resolved.*
