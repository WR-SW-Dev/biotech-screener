#!/usr/bin/env python3
"""Per-request order subprocess. Runs one MCP call for one tenant, then exits.

See ``docs/design/MULTI_TENANCY_PR_PLAN.md`` §3 (PR 3).

This is the whole of the tenant isolation boundary at execution time. The web process
resolves ``user_id`` from the signed session, reads that tenant's bearer token from the
encrypted store, spawns this script, writes one job to its stdin, and reads one result
back. The process then exits and the token is gone.

**The credential arrives on stdin and nowhere else.**

* Not argv — ``ps``, ``/proc/<pid>/cmdline`` and most process listings expose it, to any
  local user, for the lifetime of the call.
* Not the environment — it is inherited by every child, and appears in ``/proc/<pid>/environ``.

There is deliberately no ``--bearer`` option. If one is ever added,
``tests/test_mcp_order_worker.py::test_worker_rejects_a_bearer_passed_on_the_command_line``
fails, which is the point.

Exit codes — every non-zero path means *nothing was placed*:

* ``0``  success (order placed in live mode, or reviewed in dry-run)
* ``2``  malformed or missing job on stdin
* ``3``  refused locally (bad order, account mismatch, live gate not satisfied)
* ``4``  the broker call failed

Usage (the caller is ``dashboard``, not a human)::

    echo '{"bearer": "...", "order": {...}}' | python3 tools/mcp_order_worker.py

Python 3.10 compatible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.mcp_exec import (  # noqa: E402
    DEFAULT_MCP_URL,
    DEFAULT_TIMEOUT,
    AccountMismatch,
    LiveTradingDisabled,
    MCPError,
    OrderRequest,
    execute_order,
)

EXIT_OK = 0
EXIT_BAD_JOB = 2
EXIT_REFUSED = 3
EXIT_BROKER_FAILED = 4


def _fail(code: int, message: str) -> int:
    """Emit a machine-readable refusal on stderr. Never includes the credential."""
    print(json.dumps({"ok": False, "error": message}), file=sys.stderr)
    return code


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one MCP brokerage call for one tenant. Job is read from stdin.",
    )
    # No --bearer. See module docstring.
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and review only; never place, regardless of the job's live flag.",
    )
    parser.add_argument("--url", default=DEFAULT_MCP_URL, help="MCP endpoint")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse exits 2 on unknown flags — e.g. someone adding --bearer.
        return EXIT_BAD_JOB

    raw = sys.stdin.read()
    if not raw.strip():
        return _fail(EXIT_BAD_JOB, "no job on stdin")
    try:
        job = json.loads(raw)
    except ValueError as exc:
        return _fail(EXIT_BAD_JOB, "job on stdin is not valid JSON: " + str(exc))
    if not isinstance(job, dict):
        return _fail(EXIT_BAD_JOB, "job must be a JSON object")

    bearer = job.get("bearer")
    if not bearer or not isinstance(bearer, str):
        return _fail(EXIT_BAD_JOB, "job carries no bearer token")

    order_spec = job.get("order")
    if not isinstance(order_spec, dict):
        return _fail(EXIT_BAD_JOB, "job carries no order object")

    try:
        order = OrderRequest(
            account_number=str(order_spec.get("account_number", "")),
            symbol=str(order_spec.get("symbol", "")),
            side=str(order_spec.get("side", "")),
            quantity=str(order_spec.get("quantity", "")),
            order_type=str(order_spec.get("order_type", "market")),
            time_in_force=str(order_spec.get("time_in_force", "gfd")),
            limit_price=order_spec.get("limit_price"),
        )
    except ValueError as exc:
        return _fail(EXIT_REFUSED, "invalid order: " + str(exc))

    live = bool(job.get("live", False)) and not args.dry_run

    # A job asking for live placement while the caller passed --dry-run is contradictory.
    # Refuse rather than silently downgrading: the caller is confused about what it wants,
    # and quietly not trading is as wrong as quietly trading.
    if bool(job.get("live", False)) and args.dry_run:
        return _fail(EXIT_REFUSED, "job requests live placement but --dry-run was passed")

    if job.get("expect_account") is not None and order.account_number != job["expect_account"]:
        return _fail(
            EXIT_REFUSED,
            "order targets account "
            + repr(order.account_number)
            + " but the caller expected "
            + repr(job["expect_account"]),
        )

    # --dry-run is offline: validate the order and the gates, touch no network. This is
    # what CI and the deploy smoke-check run, so it must not require a broker.
    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "DRY_RUN",
                    "placed": False,
                    "symbol": order.symbol.upper().strip(),
                    "side": order.side,
                    "quantity": str(order.quantity),
                    "account_number": order.account_number,
                    "order_id": None,
                    "review": {},
                    "raw": {},
                },
                sort_keys=True,
            )
        )
        return EXIT_OK

    # Bind the trading guard before the network call. In dry-run the guard is skipped:
    # nothing can be placed, and binding would pollute the audit log with non-attempts.
    if live:
        try:
            from common.tenancy import DEFAULT_MIN_KEEP_SNAPSHOTS, DEFAULT_RETENTION_DAYS, UserContext
            from common.trading_guard import bind_process_account

            bind_process_account(
                UserContext(
                    user_id=str(job.get("user_id") or "_legacy"),
                    account_number=order.account_number,
                    broker_server=str(job.get("broker_server") or "robinhood-trading"),
                    data_root=REPO_ROOT,
                    retention_days=DEFAULT_RETENTION_DAYS,
                    min_keep_snapshots=DEFAULT_MIN_KEEP_SNAPSHOTS,
                )
            )
        except Exception as exc:
            return _fail(EXIT_REFUSED, "trading guard refused to bind: " + str(exc))

    try:
        result = execute_order(
            order,
            bearer=bearer,
            live=live,
            expect_account=job.get("expect_account"),
            url=args.url,
            timeout=args.timeout,
        )
    except AccountMismatch as exc:
        return _fail(EXIT_REFUSED, str(exc))
    except LiveTradingDisabled as exc:
        return _fail(EXIT_REFUSED, str(exc))
    except MCPError as exc:
        return _fail(EXIT_BROKER_FAILED, str(exc))
    except Exception as exc:  # never let an unexpected error look like success
        return _fail(EXIT_BROKER_FAILED, "unexpected failure: " + str(exc))

    # --dry-run already returned above, so this is REVIEW_ONLY or LIVE.
    payload = result.as_dict()
    payload["ok"] = True
    print(json.dumps(payload, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
