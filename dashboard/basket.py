"""Basket assembly, CSRF, and execution idempotency for the approval flow.

See ``docs/design/MULTI_TENANCY_PR_PLAN.md`` §3 (PR 3b).

This sits between "user reviews the latest basket" and ``common.order_broker``. It owns
three properties that a review-then-click flow gets wrong by default:

**The approved basket is the executed basket.** Each basket carries a ``basket_id`` — a
digest over its date, membership, and sizing. The review page renders the id; the execute
request must send it back; the server rebuilds the basket from the current snapshot and
refuses if the id no longer matches. So if a new snapshot promotes overnight while the
review page is still open, the click fails loudly rather than silently trading a basket
nobody looked at.

**One click executes once.** The execution ledger is keyed on ``(user_id, basket_id)``.
A double-submitted form, a retried request, or an impatient second click is refused
rather than doubling the position.

**A state-changing POST cannot be driven cross-origin.** CSRF tokens are HMAC-bound to
the tenant, so a token minted for one user is useless for another. This is belt-and-braces
alongside ``SameSite=Strict`` on the session cookie.

Python 3.10 compatible.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Optional

from common.tenancy import validate_user_id

#: Keys never written to the execution ledger, whatever the caller passes.
_LEDGER_REDACT = frozenset({"bearer", "token", "authorization", "anthropic_api_key", "password"})


class BasketError(Exception):
    """Base for approval-flow refusals."""


class BasketMismatch(BasketError):
    """The approved basket is not the basket that would execute now."""


class BasketAlreadyExecuted(BasketError):
    """This tenant already executed this basket."""


class CSRFError(BasketError):
    """CSRF token missing, malformed, or not bound to this tenant."""


@dataclass(frozen=True)
class Basket:
    """A reviewable, executable set of positions."""

    as_of_date: str
    basket_id: str
    positions: "list[dict[str, Any]]" = field(default_factory=list)
    equity_usd: str = "0"

    def assert_matches(self, approved_basket_id: str) -> None:
        if not approved_basket_id or not hmac.compare_digest(self.basket_id, str(approved_basket_id)):
            raise BasketMismatch(
                "the basket under review is no longer current (approved "
                + repr(str(approved_basket_id)[:12])
                + ", current "
                + repr(self.basket_id[:12])
                + ") — re-review before executing"
            )

    def as_dict(self) -> "dict[str, Any]":
        return {
            "as_of_date": self.as_of_date,
            "basket_id": self.basket_id,
            "equity_usd": self.equity_usd,
            "positions": list(self.positions),
        }


def _rank_of(row: Mapping[str, Any]) -> Optional[int]:
    raw = str(row.get("actionable_rank", "")).strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def build_basket(
    as_of_date: str,
    rankings: Mapping[str, Mapping[str, Any]],
    *,
    top_n: int = 30,
    equity_usd: str = "0",
) -> Basket:
    """Assemble the equal-weight top-N basket from a snapshot's rankings.

    Rows without an ``actionable_rank`` are excluded — an unranked row is not a member of
    the cohort, and silently treating it as rank-0 would put an arbitrary name at the top.
    """
    ranked = []
    for row in rankings.values():
        rank = _rank_of(row)
        if rank is None:
            continue
        ranked.append((rank, row))
    ranked.sort(key=lambda pair: pair[0])
    ranked = ranked[: max(0, int(top_n))]

    try:
        equity = Decimal(str(equity_usd))
    except (InvalidOperation, ValueError):
        equity = Decimal("0")

    n = len(ranked)
    per = (equity / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN) if n else Decimal("0")

    positions = [
        {
            "ticker": str(row.get("ticker", "")).upper(),
            "rank": rank,
            "notional_usd": str(per),
            "final_score": str(row.get("final_score", "")),
        }
        for rank, row in ranked
    ]

    digest = hashlib.sha256()
    digest.update(as_of_date.encode())
    digest.update(str(equity).encode())
    for p in positions:
        digest.update(("|" + p["ticker"] + ":" + str(p["rank"]) + ":" + p["notional_usd"]).encode())

    return Basket(
        as_of_date=as_of_date,
        basket_id=digest.hexdigest()[:32],
        positions=positions,
        equity_usd=str(equity),
    )


# ---------------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------------


def _csrf_secret(explicit: bytes | str | None = None) -> bytes:
    raw = explicit if explicit is not None else os.environ.get("BIOTECH_SESSION_SECRET", "")
    if not raw:
        raise CSRFError("no session secret available to sign CSRF tokens")
    return raw.encode() if isinstance(raw, str) else raw


def issue_csrf(user_id: str, *, secret: bytes | str | None = None) -> str:
    """Mint a CSRF token bound to ``user_id``."""
    validate_user_id(user_id)
    return hmac.new(_csrf_secret(secret), ("csrf:" + user_id).encode(), hashlib.sha256).hexdigest()


def verify_csrf(token: Any, user_id: str, *, secret: bytes | str | None = None) -> None:
    """Raise unless ``token`` was minted for ``user_id``."""
    if not token or not isinstance(token, str):
        raise CSRFError("missing CSRF token")
    expected = issue_csrf(user_id, secret=secret)
    if not hmac.compare_digest(expected, token):
        raise CSRFError("CSRF token is not valid for this session")


# ---------------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------------


class ExecutionLedger:
    """Append-only record of executed baskets, keyed on ``(user_id, basket_id)``."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _executed_keys(self) -> "set[tuple[str, str]]":
        """Every ``(user_id, basket_id)`` seen.

        A malformed line is *not* skipped silently — it is counted as unreadable and the
        caller is refused, because "I could not tell whether this executed" must not be
        treated as "it did not execute".
        """
        keys: "set[tuple[str, str]]" = set()
        if not self.path.exists():
            return keys
        self._unreadable = 0
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    self._unreadable += 1
                    continue
                uid = rec.get("user_id")
                bid = rec.get("basket_id")
                if uid and bid:
                    keys.add((str(uid), str(bid)))
        return keys

    def assert_not_executed(self, user_id: str, basket_id: str) -> None:
        self._unreadable = 0
        keys = self._executed_keys()
        if (str(user_id), str(basket_id)) in keys:
            raise BasketAlreadyExecuted(
                "tenant " + repr(user_id) + " already executed basket " + repr(str(basket_id)[:12])
            )
        if getattr(self, "_unreadable", 0):
            raise BasketAlreadyExecuted(
                "execution ledger has "
                + str(self._unreadable)
                + " unreadable record(s); refusing to execute rather than risk a duplicate"
            )

    def record(self, user_id: str, basket_id: str, result: Mapping[str, Any]) -> None:
        safe = {k: v for k, v in dict(result).items() if k.lower() not in _LEDGER_REDACT}
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "user_id": str(user_id),
            "basket_id": str(basket_id),
            "result": safe,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
