# MCP Server Intake Rubric

**Version:** 1.0 (2026-06-22)  
**Status:** ACTIVE — applies to all external MCP server candidates  
**Scope:** Any MCP server not already present in `~/.hermes/config.yaml` as of 2026-06-22  
**Exemption:** `biotech` (local, stdlib-only) is already admitted via Package C2

---

## Background

During INC-2026-06-20-AUTOPUSH, an autonomous Hermes skill push to `main` was
traced to the `command_allowlist` shell-execution bypass in Hermes'
`approvals.cron_mode: deny`. Adding an external MCP server is a capability
expansion that deserves at least as much scrutiny as a Hermes cron job — an MCP
server runs as a subprocess with full filesystem and network access unless
explicitly constrained. This rubric is the gate.

---

## The 8 Acceptance Criteria

Each incoming MCP server must satisfy all 8 before it is added to any
`mcp_servers` block.

| # | Criterion | What "satisfied" means |
|---|---|---|
| **1** | **Source pinned** | Entry point is pinned to a specific commit hash or release tag in the config or this doc. Floating `@latest` / unpinned branch is a FAIL. |
| **2** | **License reviewed** | SPDX identifier confirmed. Permissive (MIT/Apache-2/BSD) = green. Copyleft or unknown = operator review required. |
| **3** | **Tool list enumerated** | All tools the server exposes are listed by name here, with a one-line description of what each does. No "catch-all" accepts. |
| **4** | **Write-capable tools disabled** | Any tool that writes files, commits, pushes, calls external APIs with mutation verbs (POST/PUT/DELETE), or sends messages must be either absent from the server or blocked via `tools.exclude` or `tools.include` (allowlist preferred). |
| **5** | **Network/credential behavior documented** | Does the server make outbound HTTP calls? Does it require API keys? Are keys scoped (read-only tokens preferred)? Document what it phones home to and when. |
| **6** | **Semgrep scan clean or triaged** | Run `.semgrep/mcp-supply-chain.yml` against the server source. All findings either (a) produce zero hits, or (b) each hit is individually triaged with a suppression comment or an operator-signed waiver below. |
| **7** | **Local dry-run in sandbox** | Manually launch the server with `BIOTECH_MCP_REPO` or equivalent override, call `tools/list`, call one safe read tool, confirm output is bounded and expected. Record results here. |
| **8** | **Governance memo committed** | This doc is updated with the server's entry below and committed to the branch before the config edit. The config edit must happen in a separate commit that references this doc. |

---

## Evaluation Template

Copy the block below when evaluating a new candidate.

```markdown
### Candidate: <name>

**Date evaluated:** YYYY-MM-DD  
**Evaluator:** <operator>  
**Source:** <repo URL> @ commit <sha> / tag <tag>  
**Install command:** <e.g. `uvx mcp-server-foo` or `python3 server.py`>  
**License:** <SPDX or "unknown">

#### Criteria

| # | Criterion | Status | Notes |
|---|---|---|---|
| 1 | Source pinned | PASS / FAIL | |
| 2 | License reviewed | PASS / FAIL / REVIEW | |
| 3 | Tool list enumerated | PASS / FAIL | see below |
| 4 | Write tools disabled | PASS / FAIL | |
| 5 | Network/cred behavior | PASS / FAIL | |
| 6 | Semgrep scan | PASS / FINDINGS | |
| 7 | Local dry-run | PASS / FAIL | |
| 8 | Governance memo | PASS | updated this doc |

**Overall:** ADMIT / REJECT / DEFER

#### Tool list (criterion 3)

| Tool | Description | Write-capable? | Expose? |
|---|---|---|---|
| `tool_name` | what it does | No | Yes |

#### Network behavior (criterion 5)

...

#### Semgrep findings (criterion 6)

Zero findings / see triage below.

#### Dry-run output (criterion 7)

```
$ hermes mcp test <name>
```

#### Waivers (if any)

...
```

---

## Admitted servers

| Server | Admitted | Source | Criteria | Doc |
|---|---|---|---|---|
| `biotech` | 2026-06-22 | local (`tools/biotech_mcp_server.py`) | all 8 (local exemption) | `docs/hermes/BIOTECH_MCP_REGISTRATION_2026_06_22.md` |

---

## Candidate queue

| Server | Status | Notes |
|---|---|---|
| `semgrep mcp` (canonical) | E1 PASS — awaiting E2 admission decision | `semgrep==1.167.0`; effective 2-tool allowlist (see E1); LGPL sign-off pending; E0: `SEMGREP_MCP_INTAKE_E0_2026_06_22.md`; E1: `SEMGREP_MCP_E1_SANDBOX_TRIAL_2026_06_22.md` |

---

## Evaluation: semgrep mcp (Package E0 — COMPLETE)

See `docs/governance/SEMGREP_MCP_INTAKE_E0_2026_06_22.md` for the full evidence dossier.

**Summary:** 16 supply-chain findings (all triaged), 7 tools (3 safe for E1), LGPL-2.1-or-later (operator
sign-off pending). Rubric verdict: **ADMIT\_FOR\_E1\_TRIAL** with env-var constraints.

**Note:** `semgrep-mcp` PyPI 0.9.0 is deprecated (only exposes `deprecation_notice` tool). The
evaluated package is the `semgrep mcp` subcommand built into `semgrep==1.167.0`.

---

## Change log

| Date | Change |
|---|---|
| 2026-06-22 | v1.0 created; `biotech` admitted as Package C2 local exemption; `semgrep-mcp` queued as Package E |
| 2026-06-22 | E0 complete: `semgrep mcp` (1.167.0) evaluated — ADMIT\_FOR\_E1\_TRIAL; LGPL sign-off pending |
| 2026-06-22 | E1 PASS: sandbox trial confirmed 0 findings on biotech-mcp, clean temp writes; effective allowlist = 2 tools; awaiting E2 |
