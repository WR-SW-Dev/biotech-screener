# Semgrep MCP Post-Registration Audit
**Date:** 2026-06-23
**Verdict:** `PASS_SEMGREP_MCP_REGISTERED_WITH_GOVERNANCE_BOUNDARIES`

---

## 1. Registration Commit

| Field | Value |
|-------|-------|
| Commit hash | `934b53899` |
| Branch | `main` |
| Repo | `Warrenpoobear/biotech-screener` |
| Pushed | 2026-06-23 |

---

## 2. Configs Changed

### `.cursor/mcp.json` — tracked, committed
Registers Semgrep MCP for Cursor and Hermes sessions:
```json
"semgrep": {
  "command": "semgrep",
  "args": ["mcp", "--transport", "stdio", "--agent", "cursor"],
  "env": {
    "SEMGREP_MCP_DISABLE_TRACING": "true"
  }
}
```

### `.mcp.json` — local only, gitignored
Registers Semgrep MCP for Claude Code sessions:
```json
"semgrep": {
  "type": "stdio",
  "command": "semgrep",
  "args": ["mcp", "--transport", "stdio", "--agent", "claude"],
  "env": {
    "SEMGREP_MCP_DISABLE_TRACING": "true"
  }
}
```
Not committed because `.mcp.json` contains credentials for other servers (Morningstar, Robinhood) and is gitignored.

---

## 3. Telemetry Control

- **Env var:** `SEMGREP_MCP_DISABLE_TRACING=true`
- **Source:** `semgrep/mcp/utilities/tracing.py` line 199:
  `return os.environ.get("SEMGREP_MCP_DISABLE_TRACING", "").lower() == "true"`
- **Effect:** Disables OpenTelemetry/Datadog APM tracing and sets `MetricsState.OFF`
- **Verified:** Startup output reduced to `Starting Semgrep MCP server version v1.167.0` only — no Datadog trace IDs emitted
- **Note:** `SEMGREP_SEND_METRICS=off` was the wrong knob and did NOT suppress telemetry; `SEMGREP_MCP_DISABLE_TRACING=true` is the correct control

---

## 4. Roots/List Limitation

- `roots/list` is a server-to-client MCP request; Semgrep MCP uses it via `get_workspace_dir()` to discover the workspace root for file-path resolution
- `get_workspace_dir()` wraps `list_roots()` in a try/except that returns `""` on failure — graceful degradation, not a crash
- **Impact:** Workspace-relative path scanning may be limited if the client does not respond to `roots/list`
- **Not a blocker for:** Content-based scans (passing file content directly) and explicit-path governance scans
- **Operational posture:** All governance scanning against this repo is content-based or uses absolute paths; roots limitation is acceptable

---

## 5. LGPL Acknowledgment (Operator Sign-Off)

- **License:** Semgrep OSS CLI and `semgrep/mcp/utilities/` are licensed under GNU Lesser General Public License v2.1
- **Use case:** Internal dev-time governance tool; Semgrep binary called as-is from the host OS
- **Operator acknowledgment (2026-06-23):** Semgrep OSS CLI and MCP server are used as-is with no modification or redistribution of LGPL source code. LGPL permits this use without copyleft propagation.
- **Formal legal review:** Deferred; required only if Semgrep source is modified or bundled for distribution
- **Status:** `LGPL_SIGN_OFF_OPERATOR_ACKNOWLEDGED_2026_06_23`

---

## 6. Push Override Note

- The biotech screener pre-push hook (`INC-2026-06-20-AUTOPUSH` guard) blocked the initial push: non-interactive main push without a TTY was rejected
- `ALLOW_AGENT_PUSH=1` override was used after explicit operator approval ("yes")
- No production model files were changed: only `.cursor/mcp.json` (config) was modified
- Remote was 6 commits ahead; a `git pull --rebase` was performed before the final push
- This push is auditable and documented here per the guard's intent

---

## 7. Governance Boundaries

The following constraints govern all use of the Semgrep MCP server:

| Boundary | Status |
|----------|--------|
| Manual governance scanning only | ✅ Enforced |
| No autonomous/scheduled scans | ✅ No cron registration |
| No scheduler registration | ✅ Confirmed |
| No model/ranker/selector/sizing changes | ✅ Freeze active |
| No final_score/gate/snapshot changes | ✅ Freeze active |
| MCP config not further modified | ✅ Post-registration |
| No broad repo-wide scans via MCP | ✅ Policy |

**Permitted use:** Call Semgrep MCP tools interactively during sessions to scan specific files or code content against `.semgrep/` governance rules.

---

## 8. Blocker Resolution Summary

| Blocker | Resolution | Status |
|---------|-----------|--------|
| roots/list client handling | Graceful fallback confirmed; not a hard blocker for content scans | ✅ Closed |
| LGPL sign-off | Operator acknowledged 2026-06-23 | ✅ Closed |
| Startup fetch / telemetry | `SEMGREP_MCP_DISABLE_TRACING=true` verified | ✅ Closed |
| metrics-off bug | Same fix; `SEMGREP_SEND_METRICS=off` was wrong knob | ✅ Closed |

---

## Next Steps

- Semgrep MCP is live and ready for manual governance use
- No further MCP config changes planned
- Next work item: fresh PIT gap implementation branch or Sci-Cart Phase 12.1 review
- Semgrep CI integration (Step 2 of the durable 5-step sequence) remains deferred until GitHub Actions budget is restored
