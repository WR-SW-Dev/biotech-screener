"""Headless MCP client for brokerage order placement.

See ``docs/design/MULTI_TENANCY_PR_PLAN.md`` §3 (PR 3).

**This is the first module in the repository that can place a real order.** Until now
``tools/robinhood_execute_trades_v2_mcp.py`` was a stub simulator that emitted fake order
ids and failed closed on ``--live-mcp``; real orders were placed only by a human-driven
Claude session issuing ``mcp__robinhood-trading__*`` calls. That is what this replaces,
so that a click in the dashboard has something to call.

Robinhood's MCP surface is an HTTP JSON-RPC endpoint authenticated by a bearer token
(``Authorization: Bearer …``). A per-tenant credential is therefore just a per-tenant
token: there is no interactive OAuth step, no browser profile, and no per-tenant client
config to maintain. One process holding one token can reach exactly one account.

Two gates guard live placement, and **both** are required:

1. ``live=True`` passed explicitly by the caller, and
2. ``BIOTECH_LIVE_TRADING=1`` in the environment.

Neither alone is sufficient. The argument alone would let a code path that looks harmless
in review start trading; the environment variable alone would turn every review into a
placement the moment an operator exported it for one run. Default is review-only.

Errors never retry. A timeout, a transport failure, a JSON-RPC error, or a tool-level
``isError`` all raise — there is no path where an ambiguous outcome results in a second
placement attempt, because a duplicated order is worse than a failed one.

Python 3.10 compatible.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

ENV_LIVE_TRADING = "BIOTECH_LIVE_TRADING"

DEFAULT_MCP_URL = "https://agent.robinhood.com/mcp/trading"
DEFAULT_TIMEOUT = 30.0

_VALID_SIDES = frozenset({"buy", "sell"})
_VALID_ORDER_TYPES = frozenset({"market", "limit"})


class MCPError(Exception):
    """The MCP call failed, or returned something we will not act on."""


class LiveTradingDisabled(Exception):
    """Live placement was requested without both gates set."""


class AccountMismatch(Exception):
    """The order's account does not match the account the caller expected."""


class UnprovenAccountError(Exception):
    """No expected account was supplied, so ownership cannot be proven.

    Mirrors ``trading_guard.UnprovenAccountError``: a missing account is refused rather
    than treated as "no check requested". See ``execute_order``.
    """


@dataclass(frozen=True)
class OrderRequest:
    """One equity order. Validated at construction so a malformed order cannot travel."""

    account_number: str
    symbol: str
    side: str
    quantity: str
    order_type: str = "market"
    time_in_force: str = "gfd"
    limit_price: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.account_number:
            raise ValueError("account_number is required")
        if not self.symbol or not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.side not in _VALID_SIDES:
            raise ValueError("side must be one of " + ", ".join(sorted(_VALID_SIDES)) + ", got " + repr(self.side))
        if self.order_type not in _VALID_ORDER_TYPES:
            raise ValueError("order_type must be one of " + ", ".join(sorted(_VALID_ORDER_TYPES)))
        try:
            qty = Decimal(str(self.quantity))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("quantity is not a number: " + repr(self.quantity)) from exc
        if qty <= 0:
            raise ValueError("quantity must be positive, got " + repr(self.quantity))
        if self.order_type == "limit" and not self.limit_price:
            raise ValueError("limit orders require limit_price")

    def as_arguments(self) -> "dict[str, Any]":
        args: "dict[str, Any]" = {
            "account_number": self.account_number,
            "symbol": self.symbol.upper().strip(),
            "side": self.side,
            "quantity": str(self.quantity),
            "type": self.order_type,
            "time_in_force": self.time_in_force,
        }
        if self.limit_price:
            args["limit_price"] = str(self.limit_price)
        return args


@dataclass
class OrderResult:
    """Outcome of one execute_order call. Deliberately carries no credential."""

    mode: str
    placed: bool
    symbol: str
    side: str
    quantity: str
    account_number: str
    review: Mapping[str, Any] = field(default_factory=dict)
    order_id: Optional[str] = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> "dict[str, Any]":
        return {
            "mode": self.mode,
            "placed": self.placed,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "account_number": self.account_number,
            "order_id": self.order_id,
            "review": dict(self.review),
            "raw": dict(self.raw),
        }


class _HttpxTransport:
    """Thin adapter so tests can inject a fake without patching httpx globally."""

    def post(self, url, *, json=None, headers=None, timeout=None):  # noqa: A002
        import httpx

        return httpx.post(url, json=json, headers=headers, timeout=timeout)


class MCPClient:
    """Minimal MCP JSON-RPC client: enough to call one tool, and nothing more."""

    def __init__(
        self,
        url: str = DEFAULT_MCP_URL,
        *,
        bearer: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Any = None,
    ) -> None:
        if not bearer:
            raise MCPError("no bearer token; refusing to construct an unauthenticated client")
        self.url = url
        self.timeout = timeout
        self._bearer = bearer
        self._transport = transport or _HttpxTransport()
        self._id = 0

    def __repr__(self) -> str:  # pragma: no cover - trivial, but must not leak
        return "MCPClient(url=" + repr(self.url) + ", bearer=<redacted>)"

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> "dict[str, Any]":
        """Invoke one MCP tool and return its decoded payload."""
        self._id += 1
        body = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": "tools/call",
            "params": {"name": name, "arguments": dict(arguments)},
        }
        headers = {
            "Authorization": "Bearer " + self._bearer,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        try:
            resp = self._transport.post(self.url, json=body, headers=headers, timeout=self.timeout)
        except Exception as exc:  # transport-level: connection, DNS, timeout
            raise MCPError("MCP transport failure calling " + name + ": " + str(exc)) from exc

        status = getattr(resp, "status_code", 200)
        if status >= 400:
            raise MCPError("MCP call " + name + " returned HTTP " + str(status) + ": " + str(getattr(resp, "text", "")))

        try:
            payload = resp.json()
        except Exception as exc:
            raise MCPError("MCP call " + name + " returned undecodable body: " + str(exc)) from exc

        if isinstance(payload, dict) and payload.get("error"):
            err = payload["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise MCPError("MCP call " + name + " failed: " + msg)

        result = payload.get("result") if isinstance(payload, dict) else None
        if result is None:
            raise MCPError("MCP call " + name + " returned no result")

        if isinstance(result, dict) and result.get("isError"):
            raise MCPError("MCP tool " + name + " reported an error: " + _text_of(result))

        return _decode_content(result)


def _text_of(result: Mapping[str, Any]) -> str:
    parts = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return " ".join(parts).strip() or json.dumps(dict(result))


def _decode_content(result: Any) -> "dict[str, Any]":
    """MCP tool results carry their payload as text content; decode JSON when present."""
    if not isinstance(result, dict):
        return {"value": result}
    text = _text_of(result)
    if text:
        try:
            decoded = json.loads(text)
            if isinstance(decoded, dict):
                return decoded
            return {"value": decoded}
        except (ValueError, TypeError):
            return {"text": text}
    return dict(result)


def live_trading_enabled() -> bool:
    """True only when the environment gate is explicitly set to 1."""
    return os.environ.get(ENV_LIVE_TRADING, "").strip() == "1"


def execute_order(
    order: OrderRequest,
    *,
    bearer: str,
    expect_account: Optional[str],
    live: bool = False,
    url: str = DEFAULT_MCP_URL,
    timeout: float = DEFAULT_TIMEOUT,
    transport: Any = None,
) -> OrderResult:
    """Review an order, and place it only when both live gates are satisfied.

    ``expect_account`` is **required** and must be non-empty. It was previously optional,
    which meant a caller that simply omitted it got no cross-tenant verification at all —
    the ownership check silently skipped rather than refusing. The one sanctioned caller
    (``order_broker.place_order_for_tenant``) always passes it, but that made the safety
    property depend on every future caller happening to behave. ``trading_guard`` already
    refuses an unproven account rather than skipping; this primitive now holds that bar too.

    Order of operations is deliberate: every refusal that can be decided locally happens
    *before* any network call, so a misconfigured caller never touches the broker at all.
    """
    if not expect_account:
        raise UnprovenAccountError(
            "expect_account is required and must be non-empty; refusing to place an order "
            "for account " + repr(order.account_number) + " with no ownership check"
        )

    if order.account_number != expect_account:
        raise AccountMismatch(
            "order targets account "
            + repr(order.account_number)
            + " but the caller expected "
            + repr(expect_account)
            + " — refusing before any network call"
        )

    if live and not live_trading_enabled():
        raise LiveTradingDisabled(
            "live placement requested but " + ENV_LIVE_TRADING + " is not set to 1. "
            "Both the live argument and the environment gate are required."
        )

    client = MCPClient(url, bearer=bearer, timeout=timeout, transport=transport)

    # Review always runs. A failed review raises, so placement is unreachable.
    review = client.call_tool("review_equity_order", order.as_arguments())

    if not (live and live_trading_enabled()):
        return OrderResult(
            mode="REVIEW_ONLY",
            placed=False,
            symbol=order.symbol,
            side=order.side,
            quantity=str(order.quantity),
            account_number=order.account_number,
            review=review,
        )

    placed = client.call_tool("place_equity_order", order.as_arguments())
    order_id = placed.get("id") or placed.get("order_id")
    return OrderResult(
        mode="LIVE",
        placed=True,
        symbol=order.symbol,
        side=order.side,
        quantity=str(order.quantity),
        account_number=order.account_number,
        review=review,
        order_id=str(order_id) if order_id else None,
        raw=placed,
    )
