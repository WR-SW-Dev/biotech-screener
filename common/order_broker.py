"""Spawns one short-lived subprocess per order and returns its result.

See ``docs/design/MULTI_TENANCY_PR_PLAN.md`` §1. This is the caller's half of the
isolation boundary: the web process never holds a bearer token in a variable that
outlives a request, and never places an order itself.

Per request:

1. Resolve ``user_id`` from the signed session (done by the caller — never from a
   request parameter).
2. Read that tenant's credentials from the encrypted store.
3. Spawn ``tools/mcp_order_worker.py``, write the job to its **stdin**, close it.
4. Read one JSON result, wait for exit, return.

The token is written to a pipe, so it never appears in argv or the environment. The
child inherits a **scrubbed environment**: only the live-trading gate and the variables
Python needs to start. In particular the parent's ``BIOTECH_CREDSTORE_KEY`` is removed,
so a compromised worker cannot read *other* tenants' credentials — it holds exactly the
one token it was handed.

A timeout kills the child and raises. That is deliberately ambiguous — the order may or
may not have reached the broker — so the caller must treat a timeout as "unknown" and
reconcile against the account rather than retrying. Retrying a possibly-placed order is
how you buy a position twice.

Python 3.10 compatible.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from common.mcp_exec import ENV_LIVE_TRADING

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKER = REPO_ROOT / "tools" / "mcp_order_worker.py"

DEFAULT_SUBPROCESS_TIMEOUT = 60.0

#: Environment passed to the child. Nothing else is inherited — notably not the
#: credential-store key, and not anything a tenant could have influenced.
_ENV_ALLOWLIST = ("PATH", "PYTHONPATH", "PYTHONHOME", "LANG", "LC_ALL", "TZ", "SYSTEMROOT")


class OrderBrokerError(Exception):
    """The subprocess refused, failed, or could not be interpreted."""


class OrderOutcomeUnknown(OrderBrokerError):
    """The placement call failed after review succeeded — the order may have landed.

    Like :class:`OrderTimeout`, this must never be treated as a clean failure. Both block
    a basket from being released for retry.
    """


class OrderTimeout(OrderOutcomeUnknown):
    """The subprocess did not finish in time. Outcome is UNKNOWN — do not retry blindly."""


@dataclass(frozen=True)
class BrokerResult:
    ok: bool
    mode: str
    placed: bool
    order_id: Optional[str]
    payload: "dict[str, Any]"


def _child_env(*, live: bool) -> "dict[str, str]":
    env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
    # The gate is forwarded only when the caller actually asked for live placement, so a
    # review-only call cannot place even if the parent has the gate exported.
    if live and os.environ.get(ENV_LIVE_TRADING, "").strip() == "1":
        env[ENV_LIVE_TRADING] = "1"
    return env


def place_order_for_tenant(
    *,
    user_id: str,
    bearer: str,
    account_number: str,
    order: "dict[str, Any]",
    live: bool = False,
    dry_run: bool = False,
    timeout: float = DEFAULT_SUBPROCESS_TIMEOUT,
    worker: Path | None = None,
) -> BrokerResult:
    """Run one order through a short-lived subprocess and return its result.

    ``bearer`` is written to the child's stdin and is not retained here beyond the call.
    """
    if not bearer:
        raise OrderBrokerError("no bearer token for tenant " + repr(user_id))

    job = {
        "user_id": user_id,
        "bearer": bearer,
        "expect_account": account_number,
        "live": bool(live),
        "order": dict(order),
    }

    argv = [sys.executable, str(worker or WORKER)]
    if dry_run:
        argv.append("--dry-run")

    try:
        proc = subprocess.run(
            argv,
            input=json.dumps(job),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO_ROOT),
            env=_child_env(live=live),
        )
    except subprocess.TimeoutExpired as exc:
        raise OrderTimeout(
            "order subprocess for tenant "
            + repr(user_id)
            + " timed out after "
            + str(timeout)
            + "s — the order may or may not have been placed. "
            "Reconcile against the account before any retry."
        ) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip() or "(no detail)"
        try:
            parsed = json.loads(detail)
            detail = parsed.get("error", detail)
        except ValueError:
            pass
        if proc.returncode == 5:
            raise OrderOutcomeUnknown("order subprocess reported an ambiguous placement (exit 5): " + detail)
        raise OrderBrokerError("order subprocess refused (exit " + str(proc.returncode) + "): " + detail)

    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError as exc:
        raise OrderBrokerError("order subprocess emitted undecodable output: " + str(exc)) from exc

    return BrokerResult(
        ok=bool(payload.get("ok")),
        mode=str(payload.get("mode", "")),
        placed=bool(payload.get("placed")),
        order_id=payload.get("order_id"),
        payload=payload,
    )
