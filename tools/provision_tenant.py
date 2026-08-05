#!/usr/bin/env python3
"""Add or update a tenant in the encrypted credential store.

This is the supported way to onboard a user to the multi-tenant dashboard. Before it
existed the only route was a hand-written Python snippet, which is how the first live
smoke test had to provision its test user.

**No secret is ever accepted on the command line.** Passwords, Robinhood bearer tokens
and Anthropic keys are prompted for via ``getpass``. Anything in ``argv`` is visible to
every local user through ``ps`` and ``/proc/<pid>/cmdline`` for the lifetime of the
process, and lands in shell history besides — the same reasoning that keeps the bearer
off ``tools/mcp_order_worker.py``'s argv.

That includes the Anthropic key: it is opted into with ``--with-anthropic-key`` (a flag,
no value) which triggers a prompt, rather than ``--anthropic-key <value>``.

Usage::

    python3 tools/provision_tenant.py --user scott --account 111111111
    python3 tools/provision_tenant.py --user scott --account 111111111 --with-anthropic-key
    python3 tools/provision_tenant.py --user scott --account 222222222 --update

Requires ``BIOTECH_CREDSTORE_KEY`` in the environment (generate one with
``python3 -c "from common.credstore import generate_key; print(generate_key().decode())"``
and keep it outside the repo — losing it makes every stored credential unrecoverable).

Python 3.10 compatible.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.credstore import CredentialNotFound, CredentialStore, CredentialStoreError  # noqa: E402
from common.tenancy import validate_user_id  # noqa: E402

ENV_CREDSTORE_PATH = "BIOTECH_CREDSTORE_PATH"


class ProvisionError(Exception):
    """Refusing to provision — bad input, or it would clobber something."""


def default_store_path() -> Path:
    override = os.environ.get(ENV_CREDSTORE_PATH, "").strip()
    if override:
        return Path(override)
    return REPO_ROOT / "credentials" / "tenants.db"


def provision(
    store: CredentialStore,
    user_id: str,
    account_number: str,
    *,
    password: str,
    bearer: str,
    anthropic_key: Optional[str] = None,
    update: bool = False,
) -> None:
    """Write one tenant's credentials and password into ``store``.

    Refuses rather than overwriting an existing tenant unless ``update`` is set, so a
    re-run cannot silently reset someone's password.
    """
    validate_user_id(user_id)
    if not account_number:
        raise ProvisionError("account_number is required")
    if not bearer:
        raise ProvisionError("robinhood bearer token is required")
    if not password:
        raise ProvisionError("password is required")

    existing = None
    try:
        existing = store.get(user_id)
    except CredentialNotFound:
        pass
    except CredentialStoreError as exc:
        raise ProvisionError("credential store unusable: " + str(exc)) from exc

    if existing is not None and not update:
        raise ProvisionError(
            "tenant " + repr(user_id) + " already exists; pass --update to change it "
            "(this refusal exists so a re-run cannot silently reset a password)"
        )

    # A brokerage account claimed by two tenants would make the trading guard's ownership
    # check meaningless — it can only prove "this tenant owns this account" if that
    # mapping is unique. Same invariant load_registry() enforces for the old registry.
    for other in store.list_user_ids():
        if other == user_id:
            continue
        try:
            if store.get(other).account_number == account_number:
                raise ProvisionError(
                    "account "
                    + repr(account_number)
                    + " is already claimed by tenant "
                    + repr(other)
                    + "; two tenants must not share a brokerage account"
                )
        except CredentialNotFound:  # pragma: no cover - race with concurrent removal
            continue

    store.put(
        user_id,
        account_number=account_number,
        robinhood_bearer=bearer,
        anthropic_api_key=anthropic_key or None,
    )
    store.set_password(user_id, password)


def _prompt_secret(label: str, *, confirm: bool = False) -> str:
    value = getpass.getpass(label + ": ")
    if not value:
        raise ProvisionError(label + " cannot be empty")
    if confirm:
        again = getpass.getpass(label + " (confirm): ")
        if value != again:
            raise ProvisionError(label + " entries did not match")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Add or update a tenant in the encrypted credential store.",
        epilog="Secrets are prompted for; none are accepted as arguments.",
    )
    p.add_argument("--user", required=True, help="tenant id (lowercase alnum, '_' and '-', 2-32 chars)")
    p.add_argument("--account", required=True, help="Robinhood account number for this tenant")
    # Deliberately a flag, not a value — see module docstring.
    p.add_argument(
        "--with-anthropic-key",
        action="store_true",
        help="also prompt for an Anthropic API key for this tenant",
    )
    p.add_argument("--update", action="store_true", help="allow overwriting an existing tenant")
    p.add_argument("--store", type=Path, default=None, help="credential store path")
    return p


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        validate_user_id(args.user)
    except Exception as exc:
        print("refused: " + str(exc), file=sys.stderr)
        return 2

    try:
        store = CredentialStore(args.store or default_store_path())
    except CredentialStoreError as exc:
        print("refused: " + str(exc), file=sys.stderr)
        return 2

    try:
        password = _prompt_secret("Dashboard password", confirm=True)
        bearer = _prompt_secret("Robinhood bearer token")
        anthropic = _prompt_secret("Anthropic API key") if args.with_anthropic_key else None
        provision(
            store,
            args.user,
            args.account,
            password=password,
            bearer=bearer,
            anthropic_key=anthropic,
            update=args.update,
        )
    except ProvisionError as exc:
        print("refused: " + str(exc), file=sys.stderr)
        return 3
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\naborted", file=sys.stderr)
        return 130

    action = "updated" if args.update else "provisioned"
    print(
        "tenant " + repr(args.user) + " " + action + " (account " + args.account + ", "
        "anthropic key " + ("set" if anthropic else "not set") + ")"
    )
    print("store: " + str(args.store or default_store_path()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
