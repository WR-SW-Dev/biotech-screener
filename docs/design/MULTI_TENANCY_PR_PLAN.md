# Multi-tenancy — rescoped PR plan (PRs 2–4)

**Status:** plan of record. Supersedes the staging described in `MULTI_TENANCY.md` §8.
**Operator decisions incorporated:** 2026-08-03.

---

## 1. What changed, and why it makes this smaller

The original design isolated tenants with **one OS account (or container) per tenant**,
because a long-running automated pipeline was assumed to act on a tenant's behalf.

That assumption is gone. The product is now:

> log in → see the latest blotter → generate a list on demand → review the basket →
> click **Execute trading for latest basket**.

Two consequences, and they remove most of the original difficulty:

**Screening is shared and needs no isolation.** The screen is deterministic — the same
inputs produce byte-identical outputs for every user (verified by running it directly,
with no agent and no Hermes involved). So it is a plain, shared, on-demand action against
a single copy of the market data. There is no per-tenant screening state to isolate,
because there is no per-tenant screening *output*.

**Isolation collapses to a single instant.** The only moment tenant separation matters is
the click on *Execute trading for latest basket*. That is not a long-running process to
sandbox; it is one request from a session that already knows who the user is.

A standing per-tenant container is therefore more infrastructure than the problem requires.
The replacement pattern, per request:

1. Backend resolves `user_id` from the **authenticated session** — never from a request
   parameter, body, header, or query string.
2. Backend reads that tenant's credentials from the **encrypted credential store**.
3. Credentials are materialised into a **short-lived subprocess scoped to exactly one MCP
   call**. The subprocess places/reviews the order and exits. Nothing persists past the
   request — no token in the parent process's memory, no environment mutation, no file.

This keeps the property the container gave us — one tenant's credentials are only ever
live inside a process that can touch one account — scoped to one click instead of a
standing process per tenant. No orchestration, no Hermes, no cron-uptime problem.

### What this does *not* claim

The subprocess is a **blast-radius** control, not a proof of non-interference. Within one
OS account, a sufficiently privileged local process can still read another tenant's data.
What the subprocess buys is that a bug in the long-lived web process cannot place an order
with a token it never held. `common/trading_guard.py` remains defence-in-depth on top.

---

## 2. Discovered gap: there is no live execution path

`tools/robinhood_execute_trades_v2_mcp.py` is a **stub simulator**. It emits fake order ids,
`--live-mcp` is explicitly *"not yet implemented (fails closed)"*, and real orders today are
placed only by a human-driven Claude session issuing `mcp__robinhood-trading__*` calls.

So "Execute trading for latest basket" cannot work by wiring a button to existing code —
the code it would call does not exist. Building it is now **in scope for PR 3**.

This is tractable because Robinhood MCP is an **HTTP endpoint authenticated by a Bearer
JWT** (`https://agent.robinhood.com/mcp/trading`, `Authorization: Bearer …`). A per-tenant
credential is therefore just a per-tenant token — no interactive OAuth, no browser profile,
no per-tenant client config to maintain. A subprocess holding one token can talk to exactly
one account.

---

## 3. Rescoped PRs

### PR 2 — Authentication + encrypted credential store *(this PR)*

The gate everything else depends on. Without a session there is no `user_id`, and without
`user_id` nothing downstream can be scoped.

- `common/credstore.py` — encrypted-at-rest SQLite store (Fernet/AES-128-CBC+HMAC via
  `cryptography`). Per-tenant attributes: `robinhood_bearer`, `anthropic_api_key`,
  `account_number`. Replaces the per-tenant `.env` files from PR 1; those remain readable
  for `_legacy` only, so the single-user layout keeps working.
- `dashboard/auth.py` — password login (`hashlib.scrypt`), HMAC-signed session cookie
  (stdlib — no new dependency), logout, idle + absolute expiry.
- `require_user()` FastAPI dependency returning a `UserContext` **derived solely from the
  signed session**. A `user_id` appearing in any request-controlled position is ignored,
  and a test asserts that.
- Per-tenant Anthropic keys live here (operator decision #3), same store, same encryption.

### PR 3 — Approval UI + the execution path

- Blotter / basket review screens; the basket is rendered from the shared snapshot.
- `POST /api/execute` — session-scoped, CSRF-protected, idempotent per basket.
- **New:** headless MCP order client (`common/mcp_exec.py` + `tools/mcp_order_worker.py`)
  that speaks the MCP HTTP protocol with an injected Bearer token. This is what the
  subprocess runs; it is the piece that does not exist today.
- Per-request subprocess broker: spawn → pass credential over a pipe (never argv, never
  env) → one call → exit. Non-zero exit or timeout fails closed.
- `trading_guard` binds inside the subprocess, so the latch covers exactly one account.

### PR 4 — Path migration + retention

- Migrate the ~1,894 hardcoded path references onto `common/paths.py`. Mechanical but
  large; done as its own PR so review is tractable and a bad rewrite is revertible.
- Snapshot retention: **180 days** (operator decision #4), floor of
  `DEFAULT_MIN_KEEP_SNAPSHOTS`.
- `artifacts/trading/isolation_audit.jsonl` currently appends forever with no retention.
  It is an audit trail, not routine data, so it is **compressed, never deleted**: entries
  older than **1 year** roll into `isolation_audit-YYYY.jsonl.gz`.

### Unchanged from operator decisions

- **Market data stays single-copy** (decision #2). Prices, 13F, catalysts, snapshots are
  shared. Only credentials, blotters, and execution records are per-tenant.

---

## 4. Sequencing for an end-to-end test

Scott cannot exercise the flow until PRs 2–4 are all merged: PR 2 gives him a login, PR 3
gives him something to click and something that actually executes, PR 4 stops the two
tenants writing over each other's paths. PR 3 is the only one touching real money and
should be the slowest to review.
