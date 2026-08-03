# Per-tenant credentials

One directory per tenant. **Nothing in here is ever committed** — see `.gitignore`.

```
credentials/
  alice/.env      # mode 0600, owned by alice's OS user
  bob/.env        # mode 0600, owned by bob's OS user
```

Each `.env` holds that user's own secrets, e.g.:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Setup

```bash
mkdir -p credentials/alice
chmod 700 credentials/alice
$EDITOR credentials/alice/.env
chmod 600 credentials/alice/.env
```

`common.tenancy.load_user_secrets()` refuses to read a file that is group- or
world-readable, and refuses before reading it — so a mis-permissioned secret is never
loaded at all.

## The limit you must understand

Within a **single OS account**, these permissions do not isolate tenants from each other:
same UID means same filesystem rights, so any process that account runs can read every
file here. `0600` only defends across OS users.

Real isolation therefore requires **one OS user (or container) per tenant**, with
`credentials/{user_id}/` owned by that user. The Python-side checks are defense-in-depth
and a correctness gate — they are not a security boundary on their own.

The same caveat applies to trading: see `docs/design/MULTI_TENANCY.md` §5. Robinhood
credentials are *not* stored here at all — they are OAuth tokens in the MCP client config
(`~/.claude.json`), so per-tenant trading isolation is a property of that config, one
Robinhood MCP server per OS user.
