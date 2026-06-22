# Semgrep MCP — Package E1 Sandbox Trial

**Date:** 2026-06-22  
**Evaluator:** operator  
**Phase:** E1 — sandboxed manual stdio trial; NOT registered in Hermes  
**Predecessor:** Package E0 evaluation (`docs/governance/SEMGREP_MCP_INTAKE_E0_2026_06_22.md`)  
**Verdict:** **PASS** — all 3 acceptance criteria met  
**Next step:** E2 admission decision (separate operator decision; not automatic Hermes registration)

---

## Pre-trial state

| Check | Result |
|---|---|
| `weekly-skill-harvester` | `enabled=False  state=paused` ✓ |
| `/tmp/semgrep_scan_*` | (none) — no pre-existing temp dirs ✓ |
| `/tmp/semgrep-mcp/claude-secure-defaults-cache.md` | Pre-seeded at 14:27 (see §3) ✓ |
| Hermes config | Unchanged from Package C2 commit ✓ |
| Biotech repo git status | Only pre-existing unstaged `.cursorrules`/`CLAUDE.md`/`short_interest.json` ✓ |
| Network connections to semgrep.dev/github | (none before trial) ✓ |

---

## E1 environment

```bash
SEMGREP_MCP_DISABLE_TRACING=true
SEMGREP_SEND_METRICS=off
SEMGREP_FINDINGS_DISABLED=true
SEMGREP_SCAN_SUPPLY_CHAIN_DISABLED=true
SEMGREP_RULE_SCHEMA_DISABLED=true
GET_ABSTRACT_SYNTAX_TREE_DISABLED=true
# SEMGREP_APP_TOKEN — not set
```

---

## Startup network fetch — inject_secure_defaults hook

As documented in E0, the `inject_secure_defaults` hook fetches from
`raw.githubusercontent.com/tldrsec/awesome-secure-defaults/main/README.md` at startup,
caching to `/tmp/semgrep-mcp/claude-secure-defaults-cache.md`. There is no env var to
suppress this call in `semgrep==1.167.0`.

**Mitigation applied:** cache pre-seeded before trial start:

```bash
mkdir -p /tmp/semgrep-mcp
echo "# Secure Defaults Cache (pre-seeded for E1 trial — offline)" \
  > /tmp/semgrep-mcp/claude-secure-defaults-cache.md
```

**Confirmed:** the cache file mtime remained at the pre-seed timestamp (14:27) after the
trial — the server read the cache rather than re-fetching. No new outbound connections
to `raw.githubusercontent.com` observed during the trial.

**Recorded exception (E0 carry-forward):** The startup fetch is not suppressible via env
var. For any production use of this server, this one GET to `raw.githubusercontent.com`
must be accepted, or the cache must be pre-seeded on each fresh host/container.

---

## Deviation from E0 plan: semgrep_scan vs semgrep_scan_with_custom_rule

**E0 planned:** use `semgrep_scan` (path-based tool) for the scan acceptance test.

**Discovered in E1:** `semgrep_scan` does not accept a `config` parameter. It internally
calls `get_semgrep_scan_args(temp_dir, config=None)`. When `config is None` and
`SEMGREP_SEND_METRICS=off`, the server raises:

```
McpError: Cannot run scan with auto config when metrics are off.
Please allow metrics or run with a specific config.
```

**Resolution:** used `semgrep_scan_with_custom_rule` instead, which accepts the rule YAML
as a string. This tool passes the rule file as the config argument and bypasses the
metrics check.

**Impact on E1 allowlist:** `semgrep_scan` CANNOT be used with `SEMGREP_SEND_METRICS=off`
in its current form. For metrics-isolated use, the effective allowlist is:

- `get_supported_languages` ✓ (pure logic, no I/O)
- `semgrep_scan_with_custom_rule` ✓ (accepts rule YAML inline; metrics-compatible)
- ~~`semgrep_scan`~~ (path-based; errors with metrics off + no config; see above)

This deviation is documented. E2 should revise the Hermes `tools.include` allowlist
accordingly.

---

## Trial execution

**Method:** bidirectional Python stdio client wrapping `semgrep mcp`. The MCP server
sends `roots/list` server-initiated requests during tool calls; the client responds with
`{"roots":[]}` to avoid a race condition crash (seen in first run attempt with a
pipe-only approach).

**Tool call sequence:**
1. `initialize` (id=1) → `initialized` notification
2. `tools/list` (id=2)
3. `tools/call: get_supported_languages` (id=3)
4. `tools/call: semgrep_scan_with_custom_rule` (id=4)

**Target:** `tools/biotech_mcp_server.py`  
**Rule config:** `.semgrep/mcp-supply-chain.yml` (7 rules, passed as inline YAML string)

---

## Results

### Criterion 1 — tools/list returns exactly 3 tools

**PASS**

```json
{
  "tools": [
    "get_supported_languages",
    "semgrep_scan_with_custom_rule",
    "semgrep_scan"
  ]
}
```

Expected set: `{get_supported_languages, semgrep_scan, semgrep_scan_with_custom_rule}` — match ✓.
Note: `semgrep_scan` is in the list but cannot be invoked with `SEMGREP_SEND_METRICS=off`
(see deviation above).

---

### Criterion 2 — get_supported_languages returns successfully

**PASS**

Server response (trimmed):

```
supported languages are: apex, bash, c, c#, c++, cairo, circom, clojure, cpp, csharp,
dart, docker, dockerfile, elixir, ex, fga, generic, go, golang, gosu, hack, hcl, html,
java, javascript, js, json, jsonnet, julia, kotlin, kt, lisp, lua, move_on_aptos,
move_on_sui, none, ocaml, openfga, php, powershell, promql, proto, proto3, protobuf,
py, python, python2, python3, ql, r, regex, ruby, rust, scala, ...
```

Deterministic, no I/O, no network. ✓

---

### Criterion 3 — semgrep_scan_with_custom_rule returns 0 findings on biotech_mcp_server.py

**PASS**

```json
{
  "isError": false,
  "results": [],
  "errors": []
}
```

Zero findings on 7 supply-chain rules — matches the manually-run scan from Package D. ✓

Server log: `semgrep_scan_with_custom_rule succeeded`

---

### Criterion 4 — No files written to repo, ~/.hermes, or cron/jobs

**PASS**

| Location | State | Verdict |
|---|---|---|
| `/tmp/semgrep_scan_*` | (none) — temp dir created and cleaned by `finally: shutil.rmtree` | ✓ clean |
| `/tmp/semgrep-mcp/claude-secure-defaults-cache.md` | Unchanged (pre-seeded content, mtime=14:27) | ✓ no re-write |
| `/tmp/semgrep-mcp/edited-files.json` | Not created — stop.py hook did not activate | ✓ clean |
| `~/.hermes/config.yaml` | Unchanged — `semgrep` not in mcp_servers | ✓ |
| `~/.hermes/cron/jobs.json` | Unchanged — `weekly-skill-harvester` still `enabled=False, state=paused` | ✓ |
| Biotech repo working tree | Only pre-existing unstaged files | ✓ |

---

### Criterion 5 — No external MCP registered

**PASS** — trial used manual stdio; no config edited.

---

### Criterion 6 — Process exits cleanly

**PASS** — server exit code 0; no exception in server stderr tail.

Server stderr tail:
```
get_supported_languages succeeded
Somehow, no roots found
Somehow, no roots found
Findings elicitation is not enabled, skipping.
semgrep_scan_with_custom_rule succeeded
```

"Somehow, no roots found" is a harmless log line emitted when `roots/list` returns an
empty list (our client responded with `{"roots":[]}`). The server continued to function
correctly.

---

## Network observation

| Phase | Observation |
|---|---|
| Pre-trial | Existing connections: `hermes` pid 426443, `claude` pids 392178/415046 — none to semgrep.dev |
| During trial | No new connections to semgrep.dev, raw.githubusercontent.com, or telemetry.dev2.semgrep.dev observed via `ss -tnp` |
| Post-trial | Same baseline connections; no new entries |

**Note:** Network observation is best-effort via `ss -tnp` snapshots. It does not prove
no packets were sent (the cache pre-seed may have prevented the only expected background
call). For higher assurance, a future trial could use a network namespace or eBPF trace.

---

## Summary

| Criterion | Status |
|---|---|
| 1. tools/list = exactly 3 tools | ✓ PASS |
| 2. get_supported_languages works | ✓ PASS |
| 3. semgrep_scan_with_custom_rule → 0 findings | ✓ PASS |
| 4. No writes outside /tmp/ | ✓ PASS |
| 5. No external MCP registered | ✓ PASS |
| 6. Process exits cleanly | ✓ PASS |
| **Overall** | **✓ PASS** |

---

## Key findings for E2 admission decision

1. **semgrep_scan not usable with metrics off.** The path-based scan tool errors when
   `SEMGREP_SEND_METRICS=off` and no config is provided. The effective E1 toolset is 2
   tools: `get_supported_languages` + `semgrep_scan_with_custom_rule`.

2. **inject_secure_defaults startup fetch is not suppressible.** Must be accepted or
   cache pre-seeded. This is a one-time background GET to `raw.githubusercontent.com`
   per session (24h cache TTL). It makes no calls if the cache is fresh.

3. **roots/list must be handled by any client.** The server sends `roots/list`
   server-initiated requests during tool invocations. A client that doesn't respond will
   cause a crash (`anyio.ClosedResourceError`). Hermes MCP client handling for this
   should be verified before production registration.

4. **License: LGPL-2.1-or-later.** Operator sign-off pending. Internal non-distribution
   use is the intended pattern; LGPL does not require open-sourcing calling code.

5. **E1 goal met:** `semgrep_scan_with_custom_rule` can scan `tools/biotech_mcp_server.py`
   with `.semgrep/mcp-supply-chain.yml` rules, returning 0 findings, with zero writes to
   the repo and predictable output. The "add it to the agent stack" path remains gated on
   a separate E2 admission decision.

---

*E1 complete. E2 proceeds as a separate operator decision; not automatic.*
