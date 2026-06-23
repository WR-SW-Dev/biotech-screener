# OpenClaw State Reconciliation — 2026-06-23

## Contradiction Being Resolved

Governance docs label OpenClaw `FENCED — LEGACY_READ_ONLY_DORMANT`. Fleet health
monitor (2026-06-23) reported "OpenClaw :19001 Operational (compensating)."
This memo resolves the contradiction.

---

## Process State

```
PIDs:   9950, 9957 (both launched 14:48 from pts/0 — interactive terminal session)
Ports:  52379 (LISTEN, all interfaces), 3000 (LISTEN), 52379↔127.0.0.1 (ESTABLISHED loopback)
Port 19001: NOT BOUND (ss -tlnp confirms nothing on 19001)
Socket: ~/.openclaw/exec-approvals.sock — ABSENT (no Unix socket file)
Systemd unit: NONE
```

**Fleet health monitor finding was inaccurate.** Port 19001 is not bound. The two
openclaw processes running in pts/0 are the Hermes desktop TUI (started
interactively), not a gateway server. The fleet monitor likely checked for process
existence and conflated it with the historical :19001 gateway label.

---

## Exec-Approvals Audit

Current allowlist (`*` agent, 13 entries):

| Pattern | Type |
|---|---|
| `/usr/bin/python3` | read-only interpreter (scoped calls only) |
| `/usr/bin/ls` | read-only |
| `/usr/bin/cat` | read-only |
| `/usr/bin/head` | read-only |
| `/usr/bin/tail` | read-only |
| `/usr/bin/grep` | read-only |
| `/usr/bin/find` | read-only |
| `/usr/bin/wc` | read-only |
| `/usr/bin/date` | read-only |
| `/usr/bin/stat` | read-only |
| `/usr/bin/diff` | read-only |
| `/usr/bin/sort` | read-only |
| `/usr/bin/jq` | read-only |

Per-agent overrides: `bioshort_watch` has `/usr/bin/test` (read-only check command
only). All other named agents have empty allowlists.

Pre-fence backup (`exec-approvals.json.bak.20260622_fence`) had 21 entries — fence
operation on 2026-06-22 reduced to 13. Reduction is correct.

**Checks:**
- `**` wildcard: ABSENT ✓
- `bash` / `sh` / `zsh`: ABSENT ✓
- `git`: ABSENT ✓
- `/mnt/c/**` write wildcard: ABSENT ✓
- Write paths of any kind: ABSENT ✓

---

## Production Caller Audit

**Active cron:** Zero non-comment crontab entries invoke `openclaw` or
`run_openclaw.sh`. Two comment-only lines reference OpenClaw (staggered agent
schedule header, one-shot 2026-04-28).

**`tools/agent_heartbeat_checks.py`:** Defines `OPENCLAW = REPO_ROOT / "tools" /
"run_openclaw.sh"` on line 33, but no active call site found (`send_to_openclaw`,
`invoke_openclaw`, `subprocess.*OPENCLAW` — all absent). The variable is declared
but unused in current production paths.

**`tools/run_openclaw.sh`:** Exists as a Node v22 PATH-fixing wrapper that calls
`openclaw "$@"`. Callable if explicitly invoked, but no current caller.

**Hermes project:** References to "openclaw" in `release.py` and `delegate_tool.py`
are contributor attribution strings and design-doc comments, not runtime calls.

**Biotech screener:** `sync_hermes_skills.py` maps legacy skill names (documentation
only). No runtime executor path.

---

## Verdict

**`WARN_OPENCLAW_GATEWAY_LIVE_BUT_READ_ONLY_FENCED`**

The process is running (interactive terminal, TUI mode) but:
- Port 19001 is **not bound**
- Exec-approvals are fully read-only fenced
- No production or cron caller
- No Unix socket present

The "operational" label from the fleet monitor was a false positive based on process
existence, not gateway availability.

---

## Residual Live Surface

| Surface | State |
|---|---|
| openclaw process (pts/0) | Running, interactive TUI only |
| Port 52379 | Bound (OpenClaw internal port, loopback connection only) |
| Port 3000 | Bound (dev server, standard OpenClaw port) |
| `tools/run_openclaw.sh` | Callable wrapper — no active caller |
| `agent_heartbeat_checks.py` OPENCLAW var | Declared, unused |

---

## Recommended Action

1. **Update governance label** from `FENCED — LEGACY_READ_ONLY_DORMANT` to
   `FENCED — LEGACY_READ_ONLY_INTERACTIVE_TUI_ONLY` to accurately reflect that the
   process runs interactively but has no gateway, no cron, and read-only exec fence.

2. **No process termination needed.** The running process is the desktop TUI in an
   interactive session (pts/0). It poses no autonomous executor risk with the current
   exec-approvals fence.

3. **Remove or stub `OPENCLAW` variable in `agent_heartbeat_checks.py`** to
   eliminate the latent callable path. Low priority — it's currently unreachable.

4. **Fleet health monitor should be corrected** to check port binding, not process
   existence, when reporting OpenClaw gateway status.

---

## Self-Improvement Staging Gate

**BLOCKED — operator call required.**

`ALL_AGENTS_CLOSED` gate interpretation: OpenClaw is running (interactive TUI) with
a read-only exec fence and no production path. Whether this counts as "closed"
depends on operator intent for the gate. The process is not an autonomous executor,
but it is not terminated. Operator should explicitly confirm whether interactive TUI
presence satisfies or blocks the `ALL_AGENTS_CLOSED` gate before full apply.

Dry-run only (`pattern_to_skillpatch.py --dry-run`) remains safe regardless.

---

## Governance

`OPENCLAW_STATE_RECONCILIATION_DIAGNOSTIC_ONLY`  
No production files modified. No processes stopped. No self-improvement applied.
