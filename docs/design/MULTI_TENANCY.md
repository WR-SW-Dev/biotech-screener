# Multi-Tenancy Design — biotech-screener

**Status:** DRAFT for review · **Branch:** `feat/multi-tenant-foundation` · **Base:** `226a5129`
**Author:** drafted 2026-07-31 · **Classification:** `NO_MODEL_CHANGE` (no selector/ranker/final_score edits)

Moving from one operator on one machine to several team members, each with their own
Robinhood account and Anthropic key.

---

## 0. Measured current state

Everything below was verified against `226a5129`, not assumed.

| Surface | Current state |
|---|---|
| Credential loading | **One** choke point: `common/repo_env.py::load_repo_dotenv()` (24 LOC) reads repo-root `.env` and calls `load_dotenv()` → mutates **process-wide `os.environ`** |
| `ANTHROPIC_API_KEY` readers | 2 Python files |
| Robinhood credentials | **Not in this repo.** OAuth tokens live in the MCP client config (`~/.claude.json`): `robinhood-trading` and `robinhood-scott`, *both* pointing at `https://agent.robinhood.com/mcp/trading`, distinguished **only** by which token is bound to the server name |
| Order placement in-repo | `tools/robinhood_execute_trades_v2_mcp.py` — the `review_equity_order` / `place_equity_order` MCP calls are **commented out**. It prints a plan and gates on a typed phrase; it does not place orders |
| Real order path | MCP tool calls issued by the Claude session via `~/.claude/skills/biotech-*` — 12 skills, 43 hardcoded references to account `802349084` |
| Approval gate | CLI only: exact phrase `EXECUTE APPROVED ORDERS` (`:50-60`), plus a `--skip-approval` bypass flag, plus `--account-number` defaulting to `802349084` |
| Dashboard | `dashboard/app.py` — FastAPI, 1564 LOC, ~40 endpoints, **zero authentication**. CORS is *not* wildcard: `["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000"]` |
| Second web app | `web/app.py` — 88 LOC, separate FastAPI app, CORS `localhost:8000`, exposes `POST /api/reload` |
| Hardcoded data paths | `production_data` 1070 refs / 513 files · `data/snapshots` 309 / 175 · `artifacts/` 482 / 212 · `data/caches` 33 / 18 — **~1,894 refs across ~900 files** |
| Existing parameterisation | Partial: `snapshots_dir` params in `common/wake_robin_context.py`, `common/watchlist_config.py`; `final_snapshots_dir` local in `run_daily_production.py` |
| Retention | Nothing deletes anything, anywhere |

Two corrections to the framing of this task, both load-bearing:

1. **CORS is already localhost-scoped, not wildcard.** The dashboard's real defect is the
   total absence of authentication, not its CORS policy.
2. **The in-repo executor cannot place orders.** So item 5 cannot be solved inside this
   repo alone — see §5, which is the most important section of this document.

---

## 1. Per-user credential resolution

**Decision.** Introduce `common/tenancy.py` with an immutable `UserContext`, and
`credentials/{user_id}/.env` (dir `0700`, file `0600`). Secrets are returned as a
scoped object — **never** loaded into `os.environ`.

```python
@dataclass(frozen=True)
class UserContext:
    user_id: str          # ^[a-z0-9][a-z0-9_-]{1,31}$
    account_number: str   # the ONE brokerage account this user may touch
    broker_server: str    # MCP server name, e.g. "robinhood-scott"
    data_root: Path       # tenant-scoped data root
    retention_days: int
```

`load_user_secrets(ctx) -> Mapping[str, str]` refuses, loudly, when:

- `user_id` fails the charset regex, or normalises outside `credentials/` (path traversal)
- the `.env` is group/world readable (`mode & 0o077`)
- the file owner UID ≠ the expected owner for that tenant
- a caller asks for a `user_id` other than the one bound to the current process

`load_repo_dotenv()` is kept as a deprecated shim for single-tenant CLI use, so the 500+
unmigrated call sites keep working during migration.

**Why not `os.environ`.** `os.environ` is process-global: once user A's key is in it, any
code in that process can read it, and any subprocess inherits it. A returned mapping keeps
the blast radius at the call site.

**Honest limit — read this before believing item 1 is "done".** Within a *single OS
account*, file permissions cannot stop user A's process from reading user B's `.env`:
same UID, same filesystem rights. `0600` only defends across OS users. Real isolation
therefore requires **one OS user (or container) per tenant**, with `credentials/{user_id}/`
owned by that OS user. The Python layer is defense-in-depth and a correctness check —
it is not a security boundary on its own. This must be stated in the deployment runbook,
or operators will assume a guarantee they do not have.

---

## 2. Hermes user-context plumbing

**Decision.** One identifier, `user_id`, threaded through every entry point, resolved
exactly once per process by `require_user_context()`.

| Entry point | How `user_id` arrives |
|---|---|
| CLI tools | `--user <id>`, else `BIOTECH_USER_ID`, else fail (no default in multi-tenant mode) |
| Cron wrappers (`tools/cron_*.sh`) | `$1` = user id; wrapper exports `BIOTECH_USER_ID` and re-execs under that tenant. One crontab line **per user per job** |
| `tools/run_agent_direct.py` | `--user` propagated into the agent invocation record |
| `scripts/webhook_receiver.py` | authenticated principal → `user_id` map; unmapped → `403`, never a default tenant |
| MCP tool calls | `account_number` and `broker_server` always taken from `ctx`, never a literal |

**Fail closed.** If `user_id` is absent in multi-tenant mode, the process exits non-zero
rather than falling back to a default. A silent default is how cross-tenant writes happen.

Cron cost is real: N users × ~30 jobs. Mitigate with a `tools/cron_fanout.sh <job>` that
iterates the tenant registry — but note this serialises tenants and lengthens the run, and
the current WSL cron window is already saturated (all slots ≥19:00 are dead; usable band
is ~17:00–18:50). **Multi-tenant cron needs the uptime problem fixed first.**

---

## 3. Per-user data namespacing

**Decision.** `common/paths.py` exposing a `UserPaths` resolver; layout:

```
tenants/{user_id}/data/snapshots/{date}/
tenants/{user_id}/production_data/
tenants/{user_id}/data/caches/
tenants/{user_id}/artifacts/
```

**This cannot be a mechanical rewrite.** 1,894 literal references across ~900 files, in a
repo whose CI is currently red on three jobs, with a daily production run against the same
tree. A big-bang `sed` would be the single riskiest change in this project's history.

Staged migration:

1. Land `UserPaths` + a `LEGACY_TENANT` that resolves to today's paths verbatim, so
   behaviour is bit-identical for the existing operator.
2. Migrate the **write** paths first (`run_daily_production.py` promotion, snapshot
   writers) — writes are what collide; reads only go stale.
3. Migrate read paths per-module behind tests.
4. Add a CI guard that fails on **newly added** hardcoded literals (baseline the existing
   1,894 as grandfathered, block regressions).

**Shared, non-tenant data must stay shared.** Price history, CT.gov/AACT pulls, and 13F
data are market facts, not user data. Duplicating them per tenant would multiply a ~550 MB
tree by N and break PIT provenance (two tenants would hold divergent "truth" for the same
date). Design: `shared/` stays single-copy and read-only to tenants; only *derived,
per-user* outputs get namespaced.

---

## 4. Retention / cleanup

**Decision.** `tools/prune_user_data.py --user <id> [--apply]`, dry-run by default,
scheduled inside the live cron band. Age-based with a count floor
(`retention_days`, `min_keep_snapshots`).

**Hard denylist — never pruned, at any age:**

| Path | Reason |
|---|---|
| `data/caches/massive_options/` | PIT options data is **not re-fetchable**. Deleting it is unrecoverable |
| `artifacts/forward_validation/` | `captures.jsonl` is the mandate's immutable evidence of record (SM-20260629-001) |
| any snapshot date referenced by `captures.jsonl` | pruning it would orphan a capture and destroy the audit trail |
| `data/snapshots/*__pre_*` quarantine dirs | retained deliberately for provenance audits |

The denylist is enforced in code with a test per entry, not by convention. A retention job
that can delete evidence is worse than no retention job.

---

## 5. Trading isolation — the safety-critical boundary

**The honest architecture.** Orders are not placed by this repo. They are placed by MCP
tool calls from a Claude session, against whichever OAuth token is bound to a named MCP
server. Both server names currently point at the *same URL*; identity is *only* the token.
Therefore:

> **A repo-side guard cannot prevent cross-account trading. It can only refuse to
> *ask* for it.** The boundary that actually holds is one OS user (or container) per
> tenant, each with its own MCP client config containing exactly one Robinhood server.

Anything short of that leaves a session technically able to call another tenant's server.
This is the single most important conclusion in this document, and it is a deployment
requirement, not code.

**Defense in depth, in code:**

1. **Registry binding.** `tenants.json` (root-owned, `0644`, not tenant-writable) maps
   `user_id → exactly one account_number + one broker_server`. Many-to-one is rejected at
   load; two users sharing an account number is a hard config error.
2. **`assert_account_owned(ctx, account_number)`** — called at every order construction
   site. Mismatch raises `AccountIsolationError`, never a warning.
3. **Process monogamy.** A module-level latch records the first account number seen; a
   second distinct value aborts the process. This is the race-condition defense: a
   long-lived worker that somehow rebinds context cannot place a second account's order.
4. **No defaults.** Delete `--account-number`'s `802349084` default and the
   `--skip-approval` flag. A default account number in a multi-tenant executor is a loaded
   gun; `--skip-approval` removes the only human gate that exists today.
5. **Order-time re-verification.** Before submit, re-read the account number from `ctx`
   and compare against the blotter's recorded account; refuse on drift.
6. **Append-only audit.** Every attempt (accepted *and* refused) logged with
   `user_id`, `account_number`, blotter hash, decision.

**Skills are the other half.** The 12 `biotech-*` skills with 43 hardcoded `802349084`
references must not be cloned per user — a drifting duplicate of `biotech-hard-exit` is a
liquidation aimed at the wrong account. They should read `account_number` from the tenant
registry. That work lives outside this repo (`~/.claude/skills/`) and needs its own change.

---

## 6. Dashboard authentication

**Decision.** Session-cookie auth in front of `dashboard/app.py`, identity tied to §1.

- User registry with **argon2id** password hashes (never plaintext, never sha256)
- Signed, `HttpOnly`, `SameSite=Lax`, `Secure`-when-TLS session cookies; server-side
  session store with absolute + idle expiry
- A `current_user` FastAPI dependency applied via router-level dependency so **new
  endpoints are protected by default** — an opt-in decorator would eventually be forgotten
  on one of ~40 handlers
- **Every** data endpoint resolves its `UserContext` from the session, never from a path or
  query parameter. `/api/positions/{date}` must not grow a `{user_id}`; if a tenant id ever
  appears in a URL it becomes an IDOR the moment one check is missed
- CORS: drop cross-origin entirely and serve the UI same-origin. If a separate dev origin is
  needed, keep the explicit allowlist and set `allow_credentials=True` — never `*` with
  credentials (the browser rejects it, and it signals the wrong intent)
- Rate-limit login; constant-time compare; generic failure message

**Also:** `dashboard/app.py:9` documents `uvicorn dashboard.app:app --reload`. Auto-reload
must be **off** — it watches the filesystem, re-executes on change, and has no place in a
process holding session keys and trading context. The runbook will specify no `--reload`.

`web/app.py`'s `POST /api/reload` needs the same treatment: authenticated and non-mutating,
or removed.

---

## 7. Trade approval in the UI

**Decision.** Replace the typed phrase with an authenticated review-and-approve screen.
Human-in-the-loop is preserved — it moves, it does not weaken.

```
GET  /approvals                      → pending blotters for the session's tenant only
GET  /api/approvals/{blotter_id}     → line items, est. cost, target vs current weight
POST /api/approvals/{blotter_id}/approve
POST /api/approvals/{blotter_id}/reject
```

Required properties:

- **Re-authentication** at approval time (password or TOTP), not just a live session —
  approving trades should not ride on a cookie someone left open
- **Blotter content hash** shown to the user and submitted back with the approval; if the
  blotter changed after rendering, refuse. This is the TOCTOU defense
- **Idempotency key** per approval so a double-click or retry cannot double-submit
- Tenant scoping: a blotter whose `user_id` ≠ session user is `404`, not `403` (no
  cross-tenant existence disclosure)
- The audit record keeps *who* approved, *what hash*, and *when* — the phrase-typing flow
  records none of this today, so this is a net improvement in auditability
- Approval grants execution of **that** blotter only; no standing approval

---

## 8. Localhost-only until 6 and 7 land

**Decision.** Bind `127.0.0.1` explicitly, and add a startup refusal: if the bind host is
not loopback and `MULTI_TENANT_AUTH_READY` is not set, the app exits with a clear message.
A comment saying "don't expose this" is not a control; a process that refuses to start is.

No reverse proxy, no port forward, no Tailscale `serve`/`funnel` until §6 and §7 are merged
and reviewed. Worth noting: the Mac studio is already on the tailnet tagged
`tag:appserver` — exposing an unauthenticated dashboard there would publish every tenant's
positions to anything the ACL admits.

---

## Staging

| PR | Contents | Risk |
|---|---|---|
| **1 (this branch)** | §1 `tenancy.py`, §2 resolution helper, §3 `paths.py` + `LEGACY_TENANT` shim, §5 guard + registry, §4 pruner (dry-run default), tests | Low — additive; no existing call site changes behaviour |
| 2 | §6 dashboard auth + §8 bind refusal | Medium |
| 3 | §7 approval UI, retire CLI phrase + `--skip-approval` | Medium — touches execution |
| 4 | §3 write-path migration, then read paths, module by module | High — do last, behind tests |
| 5 | Skills registry-driven (separate repo, `~/.claude/skills/`) | High |

PR 1 is deliberately additive: it introduces the primitives and proves them with tests
without moving any existing behaviour, so it can be reviewed on its merits rather than as a
1,894-site refactor.

## Open questions for review

1. **One OS user per tenant — confirmed acceptable?** §1 and §5 both depend on it. If all
   tenants must share one OS account, then credential and trading isolation are advisory
   only, and that limitation needs to be written into the user-facing terms.
2. **Shared vs per-tenant market data** (§3) — confirming price history / AACT / 13F stay
   single-copy.
3. **Does each tenant need their own Anthropic key**, or does one org key with per-user
   attribution suffice? The latter is much simpler and avoids N key rotations.
4. **Retention window** default — proposing 180 days with `min_keep_snapshots=60`.
5. **CI is red on `main`** (`tests`, `replay-regression`, `container`) independent of this
   work. This PR's own tests pass; the branch cannot turn CI green.
