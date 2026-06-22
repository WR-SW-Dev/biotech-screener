# Containment Branch — PR Readiness Check

**Date:** 2026-06-22  
**Branch:** `langgraph-review-artifact-dir-none-guard-2026-06-22`  
**Ahead of `main`:** 11 commits  
**Status:** READY FOR OPERATOR MANUAL PUSH/PR

---

## 1. Branch and ahead count

```
Branch: langgraph-review-artifact-dir-none-guard-2026-06-22
Ahead:  11 commits (0 behind)
```

## 2. Pre-push guard

```
$ echo "refs/heads/... <sha> refs/heads/main <sha>" | bash .git/hooks/pre-push origin ...
pre-push: BLOCKED — non-interactive push to 'main'.
  INC-2026-06-20-AUTOPUSH guard: this clone refuses automated/agent
  pushes to main. No TTY detected (cron/agent/CI context).
  To push deliberately and non-interactively: ALLOW_AGENT_PUSH=1 git push ...
```

Guard is live. Manual interactive push proceeds normally; agent push requires
`ALLOW_AGENT_PUSH=1`.

## 3. State checks

| Check | Result |
|---|---|
| `weekly-skill-harvester` | `enabled=False  state=paused` ✓ |
| Hermes gateway `:8642` | `{"status":"ok","platform":"hermes-agent"}` ✓ |
| `biotech-mcp` in Hermes | Registered, 11 tools, enabled ✓ |
| `semgrep` in `mcp_servers` | NOT registered (`mcp_servers` keys: `['codegraph','biotech']`) ✓ |
| OpenClaw `:19001` | `{"ok":true,"status":"live"}` — still live (dormant, retirement pending; see caveat §8) |

## 4. Tests

```
$ python3 -m pytest tests/test_biotech_mcp_server.py -q
25 passed in 5.15s
```

## 5. Semgrep supply-chain scan

```
$ SEMGREP_SEND_METRICS=off semgrep --config .semgrep/mcp-supply-chain.yml \
    tools/biotech_mcp_server.py
Findings: 0  Rules run: 7  Targets scanned: 1
```

## 6. Commit list (11 commits)

| Hash | Commit |
|---|---|
| `afced5d4` | Guard artifact_dir against None in LangGraph review node |
| `2d3f54ea` | docs(incident): INC-2026-06-20-AUTOPUSH closeout — harvester found+paused |
| `96ffea36` | docs(governance): Hermes/OpenClaw/LangGraph runtime boundary map (Package B) |
| `ded2d3b0` | feat(githooks): pre-push guard blocking non-interactive pushes to main |
| `9c2f4be2` | feat(mcp): read-only biotech-mcp diagnostic server (Package C) |
| `638d0227` | Package C1.5: reconcile biotech-mcp naming and documentation |
| `27233ec6` | docs(hermes): Package C2 — register biotech-mcp in Hermes, smoke tests pass |
| `bb66f847` | governance(mcp): Package D — MCP intake rubric + supply-chain Semgrep rules |
| `d270feb9` | governance(mcp): Package E0 — Semgrep MCP intake evaluation |
| `4a87187d` | governance(mcp): Package E1 — sandbox trial PASS |
| `1e954d07` | governance(mcp): Package E2 — Semgrep MCP admission decision |

## 7. Files changed (15 files, 2314 insertions, 1 deletion)

```
.semgrep/mcp-supply-chain.yml                                  +157
docs/governance/HERMES_OPENCLAW_LANGGRAPH_RUNTIME_BOUNDARY_...  +98
docs/governance/MCP_SERVER_INTAKE_RUBRIC.md                    +129
docs/governance/SEMGREP_MCP_E1_SANDBOX_TRIAL_2026_06_22.md    +262
docs/governance/SEMGREP_MCP_E2_ADMISSION_DECISION_2026_06_22.md +123
docs/governance/SEMGREP_MCP_INTAKE_E0_2026_06_22.md           +275
docs/hermes/BIOTECH_MCP_PATH_MAP_2026_06_22.md                  +67
docs/hermes/BIOTECH_MCP_REGISTRATION_2026_06_22.md             +106
docs/hermes/biotech_mcp.md                                       +95
docs/incidents/INC_2026_06_20_AUTOPUSH_CLOSEOUT_2026_06_22.md  +107
scientific_cartography/langgraph_review/nodes.py                  +1/-1
tests/test_biotech_mcp_server.py                               +210
tools/biotech_mcp_server.py                                    +617
tools/githooks/install-hooks.sh                                  +20
tools/githooks/pre-push                                          +47
```

All changes are additions except the one-line bug fix in `nodes.py`.
No test files deleted. No existing tool files modified.

## 8. Dirty / unrelated files (NOT part of branch)

| File | Status | Decision |
|---|---|---|
| `.cursorrules` | Modified (unstaged) | **Exclude** — session-local Cursor config, unrelated to this branch |
| `CLAUDE.md` | Modified (unstaged) | **Exclude** — session-local Claude Code instructions |
| `production_data/short_interest.json` | Modified (unstaged) | **Exclude** — data file, unrelated to this change set |

These three files are unstaged and must NOT be included in the PR commit. They do not
affect the branch diff against `main` and will not appear in the PR unless accidentally
staged.

## 9. Known caveats

| Caveat | Detail |
|---|---|
| **No CI ran** | GitHub Actions budget exhausted. Zero CI checks passed on any of the 11 commits. Local tests (25/25 pytest) and local Semgrep scan (0 findings) are the only automated validation. |
| **Semgrep MCP manual-only** | `semgrep mcp` is NOT in `~/.hermes/config.yaml`. The E2 decision (`ADMIT_WITH_CONSTRAINTS_FOR_MANUAL_USE_ONLY`) is the terminal state for this branch. Hermes registration is gated on 4 open blockers (B1–B4 in the E2 doc). |
| **OpenClaw still live** | `:19001` is responding. OpenClaw retirement/fencing is an open operator decision not addressed in this branch. |
| **Hermes 0.17.0 fix not validated end-to-end** | The GHSA-4pqm-j46f-795x WebSocket fix (fail-closed for empty peer) was applied manually to the Hermes fork. It is not covered by an automated test in this repo. |
| **biotech-mcp `/mnt/c/` path** | `tools/biotech_mcp_server.py` uses `/mnt/c/Projects/biotech_screener/biotech-screener` auto-detected as repo root. This path is WSL2-specific; adjust if deploying to a different host. |

---

## 10. PR description (draft)

See §11 below.

---

## 11. PR title and description

**Title:**
```
containment: INC-2026-06-20-AUTOPUSH response — pre-push guard, biotech-mcp, Semgrep governance
```

**Body:**

---

### Summary

Response to INC-2026-06-20-AUTOPUSH (weekly-skill-harvester autonomous push to `main`
via Hermes cron). This PR bundles the incident closeout, a pre-push guard to prevent
recurrence, a new read-only diagnostic MCP server for the biotech screener, and a
full governance gate for evaluating external MCP servers.

**Packages delivered (A → E):**

| Package | Commit | Description |
|---|---|---|
| Root fix | `afced5d4` | Guard `artifact_dir` against `None` in LangGraph review node (original bug that triggered the incident) |
| Incident closeout | `2d3f54ea` | INC-2026-06-20-AUTOPUSH post-mortem + harvester confirmed paused |
| B — boundary map | `96ffea36` | Hermes/OpenClaw/LangGraph runtime boundary map |
| C — pre-push guard | `ded2d3b0` | Non-interactive push to `main` blocked by pre-push hook |
| C (biotech-mcp) | `9c2f4be2` + `638d0227` + `27233ec6` | Read-only stdlib-only MCP server exposing 11 diagnostic views of the screener model; registered in Hermes with `tools.include` allowlist |
| D — intake rubric | `bb66f847` | 8-criterion gate for external MCP servers; 7 Semgrep supply-chain rules |
| E0/E1/E2 — Semgrep MCP | `d270feb9` + `4a87187d` + `1e954d07` | Full intake evaluation of `semgrep mcp` (canonical, not deprecated PyPI package); E1 sandbox trial PASS (0 findings on biotech-mcp); E2 decision: `ADMIT_WITH_CONSTRAINTS_FOR_MANUAL_USE_ONLY`, NOT registered in Hermes |

### Test plan

- [x] `python3 -m pytest tests/test_biotech_mcp_server.py` — 25/25 passed
- [x] `semgrep --config .semgrep/mcp-supply-chain.yml tools/biotech_mcp_server.py` — 0 findings
- [x] Pre-push guard blocks non-interactive push to `main` (dry-run verified)
- [x] `weekly-skill-harvester`: `enabled=False, state=paused` (pre- and post-branch)
- [x] `semgrep` NOT in `~/.hermes/mcp_servers`
- [x] Hermes gateway `:8642` healthy
- [ ] CI: **no Actions minutes — zero CI checks ran** (local validation only)

### Caveats

- **No CI.** GitHub Actions budget exhausted. All validation is local.
- **Semgrep MCP not registered in Hermes.** E2 terminal state: manual stdio only.
  4 blockers remain for full registration (roots/list client handling, LGPL sign-off,
  startup fetch policy, `semgrep_scan` metrics-off bug).
- **OpenClaw not addressed.** Still live at `:19001`. Retirement/fencing is a separate
  operator decision, not part of this PR.
- **WSL2 path dependency in biotech-mcp.** Auto-detects repo root from `__file__`;
  adjust if deploying outside WSL2.

---

## 12. Safe to push?

**YES — safe for operator manual interactive push.**

The pre-push guard will not block a human `git push` with a TTY. The branch is clean
(11 well-scoped commits, no unrelated staged changes), tests pass, and Semgrep scan is
clean. The operator should NOT include the three unstaged files (`.cursorrules`,
`CLAUDE.md`, `short_interest.json`) in any additional commit before pushing.

To push:
```bash
git push origin langgraph-review-artifact-dir-none-guard-2026-06-22
# then open PR on GitHub targeting main
```

Or non-interactively (override guard):
```bash
ALLOW_AGENT_PUSH=1 git push origin langgraph-review-artifact-dir-none-guard-2026-06-22
```
