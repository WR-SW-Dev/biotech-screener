# Hermes MCP Security Policy

Governs which MCP servers are active, what each may do, and how new servers
are admitted.

---

## Policy principles

1. **Explicit allowlist** — no MCP server is active by default; every server must be registered in `docs/ops/hermes_mcp_registry.md`
2. **Least privilege** — each server is granted only the tool categories it requires
3. **No production mutation** — MCP tools must not directly write to frozen production paths (ranker, selector, portfolio, snapshots)
4. **Operator-gated admission** — adding a new MCP server requires operator review and an entry in the registry
5. **Audit trail** — all MCP tool invocations by autonomous agents are logged; logs retained for 30 days

---

## Tool category classifications

| Category | Description | Default policy |
|---|---|---|
| **read-only-market** | Read market data, quotes, positions | Allowed for Tier 0+ agents |
| **write-trade** | Place, cancel, or modify orders | Tier 3+ agents only; human-in-loop required |
| **read-portfolio** | View portfolio, holdings, P&L | Allowed for Tier 0+ agents |
| **external-search** | Web search, document fetch | Allowed with logging |
| **repo-write** | Push to remote repositories | Forbidden for autonomous agents |
| **config-write** | Modify system configuration | Tier 4 only; operator-approved |
| **email-send** | Send emails or notifications | Restricted to Town bridge pattern |

---

## Active MCP servers

See `docs/ops/hermes_mcp_registry.md` for the authoritative list.

Currently active servers (summary):

| Server | Category | Autonomous use |
|---|---|---|
| `robinhood-trading` | read-portfolio, write-trade | Human-in-loop only for write-trade |
| `codegraph` | read-only-market (code intelligence) | Allowed |
| `claude_ai_Microsoft_365` | external-search, email-send | Read only for autonomous; email via Town bridge |

---

## Autonomous agent restrictions

Hermes cron jobs and subagents running without human in the loop must NOT:

- Place, cancel, or modify orders (`place_equity_order`, `cancel_equity_order`, etc.)
- Send emails or Slack messages outside the Town bridge
- Push to GitHub
- Modify `.env`, `.github/workflows/`, or crontab

**Exception:** `biotech-rebalance` and related portfolio skills may invoke
`place_equity_order` when the operator has explicitly launched the skill in an
interactive session (not via Hermes cron).

---

## Hardening for new MCP servers

Before registering any new MCP server:

1. Review all tools it exposes — document them in `hermes_mcp_registry.md`
2. Assign each tool to a category from the table above
3. Determine minimum tier required
4. Add admission entry with date and approver
5. If the server has write-trade or repo-write tools, require human-in-loop note in the registry

---

## Incident response

If an MCP tool executes an unauthorized write:

1. Immediately disable the MCP server (`hermes mcp disable <server-name>` or remove from config)
2. Revert any mutations (git revert, order cancel if applicable)
3. File an incident report in `governance_package_*/` following the INC format
4. Review audit logs at `logs/mcp_audit.log`
5. Require operator sign-off before re-enabling

---

## References

- MCP registry: `docs/ops/hermes_mcp_registry.md`
- Permission tiers: `docs/ops/hermes_permission_tiers.md`
- Incident precedent: INC-2026-06-20-AUTOPUSH (governance package)
- Town bridge (authorized email path): `docs/hermes_skills/town-operator-bridge.md`
