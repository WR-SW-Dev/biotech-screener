# Per-tenant credentials

Tenant secrets live in an **encrypted SQLite store**, not in files here.

```
credentials/
  tenants.db      # encrypted, mode 0600, gitignored — the real store
```

`common/credstore.py` owns it and `dashboard/auth.py` reads from it. Each tenant row
holds three values, all encrypted at rest with Fernet:

| Field | Purpose |
| --- | --- |
| `account_number` | the Robinhood account this tenant may trade |
| `robinhood_bearer` | that tenant's bearer token, handed to one subprocess per order |
| `anthropic_api_key` | optional, per-tenant |

Passwords are stored separately as `scrypt` hashes with per-record salts — never
recoverable, only verifiable.

## Adding a tenant

```bash
export BIOTECH_CREDSTORE_KEY="$(python3 -c 'from common.credstore import generate_key; print(generate_key().decode())')"
python3 tools/provision_tenant.py --user scott --account 111111111
```

The tool prompts for the password (with confirmation) and the Robinhood bearer token.
Add `--with-anthropic-key` to be prompted for an Anthropic key too, and `--update` to
change an existing tenant.

**No secret is accepted as a command-line argument.** Anything in `argv` is readable by
every local user via `ps` and `/proc/<pid>/cmdline`, and lands in shell history — the
same reason `tools/mcp_order_worker.py` takes its bearer on stdin only.

## The encryption key

`BIOTECH_CREDSTORE_KEY` must be present in the environment of anything that opens the
store. Keep it **outside the repo** — a secrets manager, or an operator-only file that is
not in a git working tree.

Losing it makes every stored credential unrecoverable; there is no recovery path, by
design. A missing key raises rather than falling back to plaintext.

## What this protects, and what it does not

Encryption at rest means a leaked backup, snapshot, or copied `tenants.db` is not a
leaked credential.

It does **not** defend against an attacker who already executes code as the serving user
— they can read the key out of the process environment. Within one OS account this is a
blast-radius control, not a proof of isolation. What it does buy, together with the
per-request subprocess in `common/order_broker.py`, is that a bug in the long-lived web
process cannot place an order with a token it never held.

## Superseded design

Earlier revisions used one `.env` file per tenant under `credentials/<user>/`, protected
by OS file permissions and one OS account per tenant. That design was **withdrawn** —
see `docs/design/MULTI_TENANCY_PR_PLAN.md` §1. Screening turned out to be deterministic
and shared, so the only moment tenant separation matters is the click on *Execute
trading for latest basket*, which needs a credential lookup rather than a standing
per-tenant process.

`common/tenancy.py` still exposes `credentials_file()` and `load_user_secrets()` for the
`_legacy` tenant, so the historical single-user layout keeps working unchanged. New
tenants should not use it.

`tenants.example.json` documents that withdrawn registry format and is kept only as a
reference for the `_legacy` path.
