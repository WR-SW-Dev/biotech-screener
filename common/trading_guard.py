"""Hard guard against placing an order into the wrong tenant's brokerage account.

See ``docs/design/MULTI_TENANCY.md`` §5.

**Read this before trusting this module.** Orders are not placed by this repository. They
are placed by MCP tool calls from a Claude session against whichever OAuth token is bound
to a named MCP server, and today two server names point at the *same* URL — identity is
only the token. So this module cannot *prevent* a cross-account order; it can only refuse
to construct or submit one from code that consults it. The boundary that actually holds is
one OS user (or container) per tenant, each with exactly one Robinhood server in its MCP
client config. Treat this as defense-in-depth, and never as the reason cross-account
trading is impossible.

What it does provide, cheaply and deterministically:

* ownership assertion against the root-owned tenant registry
* a process-lifetime latch, so a long-lived worker cannot rebind to a second account
* an append-only audit record of every attempt, accepted or refused
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from common.tenancy import UserContext

_LOCK = threading.Lock()
_bound_user_id: Optional[str] = None
_bound_account: Optional[str] = None

ENV_AUDIT_PATH = "BIOTECH_TRADING_AUDIT_LOG"


class TradingIsolationError(Exception):
    """Base class for trading-boundary violations. Never catch this to continue."""


class AccountIsolationError(TradingIsolationError):
    """An order was constructed for an account the acting tenant does not own."""


class ProcessAccountRebindError(TradingIsolationError):
    """A second, different brokerage account was seen in one process lifetime."""


class UnprovenAccountError(TradingIsolationError):
    """The context carries no account number, so ownership cannot be proven."""


def _audit_path() -> Path:
    override = os.environ.get(ENV_AUDIT_PATH, "").strip()
    if override:
        return Path(override)
    from common.tenancy import REPO_ROOT

    return REPO_ROOT / "artifacts" / "trading" / "isolation_audit.jsonl"


def _audit(event: str, *, user_id: str, account_number: str, detail: str = "") -> None:
    """Append one audit record. Never raises — an audit failure must not mask a refusal."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "user_id": user_id,
        "account_number": account_number,
        "pid": os.getpid(),
        "detail": detail,
    }
    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


def bind_process_account(ctx: UserContext) -> None:
    """Latch this process to one tenant + account. Idempotent for the same pair.

    Called once at entry-point startup. A second distinct account aborts, which is the
    race-condition defense: even if a context object were swapped mid-run, the latch has
    already recorded which account this process is allowed to touch.
    """
    global _bound_user_id, _bound_account

    if not ctx.account_number:
        raise UnprovenAccountError(
            "tenant " + repr(ctx.user_id) + " has no account_number; refusing to bind a "
            "trading process to an unproven account"
        )

    with _LOCK:
        if _bound_account is None:
            _bound_user_id = ctx.user_id
            _bound_account = ctx.account_number
            _audit("process_bound", user_id=ctx.user_id, account_number=ctx.account_number)
            return
        if _bound_account != ctx.account_number or _bound_user_id != ctx.user_id:
            _audit(
                "rebind_refused",
                user_id=ctx.user_id,
                account_number=ctx.account_number,
                detail="already bound to " + str(_bound_user_id) + "/" + str(_bound_account),
            )
            raise ProcessAccountRebindError(
                "process is already bound to tenant "
                + repr(_bound_user_id)
                + " account "
                + repr(_bound_account)
                + "; refusing to rebind to tenant "
                + repr(ctx.user_id)
                + " account "
                + repr(ctx.account_number)
            )


def assert_account_owned(ctx: UserContext, account_number: str) -> None:
    """Refuse unless ``account_number`` is exactly the account ``ctx`` owns.

    Call at every order-construction and order-submission site. Raises rather than warns:
    a warning in this position would be logged and ignored.
    """
    if not ctx.account_number:
        _audit(
            "refused_unproven",
            user_id=ctx.user_id,
            account_number=str(account_number),
            detail="context has empty account_number",
        )
        raise UnprovenAccountError(
            "tenant " + repr(ctx.user_id) + " has no bound account_number; cannot prove "
            "ownership of " + repr(account_number)
        )

    if not account_number or str(account_number) != ctx.account_number:
        _audit(
            "refused_mismatch",
            user_id=ctx.user_id,
            account_number=str(account_number),
            detail="tenant owns " + ctx.account_number,
        )
        raise AccountIsolationError(
            "tenant "
            + repr(ctx.user_id)
            + " owns account "
            + repr(ctx.account_number)
            + " but an order was constructed for account "
            + repr(account_number)
            + "; refusing"
        )

    # Ownership holds. Also enforce the process latch so the first order in a process
    # fixes the account for its whole lifetime.
    bind_process_account(ctx)
    _audit("allowed", user_id=ctx.user_id, account_number=ctx.account_number)


def verify_blotter_account(ctx: UserContext, blotter: dict) -> str:
    """Re-verify a blotter's recorded account against ``ctx`` immediately before submit.

    Guards the window between blotter construction and submission (design §5.5): if the
    file changed, or was written for another tenant, refuse.
    """
    recorded = ""
    meta = blotter.get("metadata")
    if isinstance(meta, dict):
        recorded = str(meta.get("account_number") or meta.get("account") or "").strip()
    if not recorded:
        raise AccountIsolationError(
            "blotter has no metadata.account_number; refusing to submit an order whose "
            "target account cannot be verified"
        )
    assert_account_owned(ctx, recorded)
    return recorded


def bound_account() -> Optional[str]:
    """The account this process is latched to, if any. For diagnostics and tests."""
    return _bound_account


def reset_for_testing() -> None:
    """Clear the process latch. **Tests only** — never call from production code."""
    global _bound_user_id, _bound_account
    with _LOCK:
        _bound_user_id = None
        _bound_account = None
