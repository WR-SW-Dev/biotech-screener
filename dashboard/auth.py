"""Session authentication for the operator dashboard.

See ``docs/design/MULTI_TENANCY_PR_PLAN.md`` §3 (PR 2).

**The one rule.** The acting tenant is derived from the signed session cookie and from
nothing else. No query parameter, path parameter, header, form field or JSON body may
influence which tenant a request acts as. Every downstream control — credential lookup,
the trading guard's account latch, per-tenant paths — assumes this, so if it ever stops
being true they all silently become bypassable by editing a URL.
``tests/test_dashboard_auth.py::TestUserIdCannotComeFromTheRequest`` is the barrier.

Session tokens are ``base64url(payload).hexdigest(HMAC-SHA256)``. Stdlib only — the repo
does not ship ``itsdangerous`` and this is not enough code to justify adding it.

Tokens are *stateless*: there is no server-side session table, so a token stays valid
until it expires. That is an accepted trade for PR 2 (single operator host, short
``max_age``); if per-session revocation is ever needed, add a revocation table keyed on
the ``jti`` field, which is already minted and carried for that purpose.

Python 3.10 compatible.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import secrets
import time
from hashlib import sha256
from typing import Any, Optional

from common.credstore import CredentialNotFound, CredentialStore, CredentialStoreError
from common.tenancy import DEFAULT_MIN_KEEP_SNAPSHOTS, DEFAULT_RETENTION_DAYS, UserContext, validate_user_id

SESSION_COOKIE = "biotech_session"
# The value below is an environment-variable *name* used for an os.environ lookup, not a
# secret. detect-secrets' keyword heuristic matches on "SECRET =" alone.
ENV_SESSION_SECRET = "BIOTECH_SESSION_SECRET"  # pragma: allowlist secret

#: Absolute session lifetime. Deliberately short: this session can authorise a live trade.
DEFAULT_MAX_AGE = 12 * 3600


class AuthError(Exception):
    """Request is not authenticated, or the session is not usable."""


class SessionExpired(AuthError):
    """Session signature is valid but the token is past its lifetime."""


def _secret(explicit: bytes | str | None = None) -> bytes:
    raw = explicit if explicit is not None else os.environ.get(ENV_SESSION_SECRET, "")
    if not raw:
        raise AuthError(
            "no session secret: set " + ENV_SESSION_SECRET + " (32+ random bytes). "
            "Refusing to sign sessions with a default value."
        )
    return raw.encode() if isinstance(raw, str) else raw


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_session(
    user_id: str,
    *,
    secret: bytes | str | None = None,
    issued_at: float | None = None,
    max_age: int = DEFAULT_MAX_AGE,
) -> str:
    """Mint a signed session token for ``user_id``."""
    validate_user_id(user_id)
    payload = {
        "sub": user_id,
        "iat": int(issued_at if issued_at is not None else time.time()),
        "exp": int((issued_at if issued_at is not None else time.time()) + max_age),
        "jti": secrets.token_hex(8),
    }
    body = _b64e(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    sig = hmac.new(_secret(secret), body.encode(), sha256).hexdigest()
    return body + "." + sig


def read_session(
    token: str,
    *,
    secret: bytes | str | None = None,
    max_age: int | None = None,
    now: float | None = None,
) -> str:
    """Verify ``token`` and return the tenant id, or raise.

    Signature is checked before the payload is parsed, so malformed input from an
    unauthenticated caller never reaches the JSON decoder.
    """
    if not token or token.count(".") != 1:
        raise AuthError("malformed session token")
    body, sig = token.rsplit(".", 1)
    if not body or not sig:
        raise AuthError("malformed session token")

    expected = hmac.new(_secret(secret), body.encode(), sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise AuthError("session signature does not verify")

    try:
        payload: Any = json.loads(_b64d(body))
    except (ValueError, binascii.Error) as exc:
        raise AuthError("session payload is not decodable: " + str(exc)) from exc
    if not isinstance(payload, dict):
        raise AuthError("session payload is not an object")

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise AuthError("session payload carries no subject")

    ts = now if now is not None else time.time()
    exp = payload.get("exp")
    if max_age is not None:
        iat = payload.get("iat")
        if not isinstance(iat, (int, float)):
            raise AuthError("session payload carries no issued-at")
        if ts - iat > max_age:
            raise SessionExpired("session older than max_age")
    elif isinstance(exp, (int, float)) and ts > exp:
        raise SessionExpired("session expired")

    try:
        validate_user_id(sub)
    except Exception as exc:
        raise AuthError("session subject is not a valid tenant id") from exc
    return sub


def sign_payload(payload: str, *, secret: bytes | str, issued_at: float | None = None) -> str:
    """Sign an arbitrary short-lived string. Same envelope as a session, no user-id rules.

    ``issue_session`` validates its subject as a tenant id, so it cannot carry packed
    values like the OAuth ``state|verifier`` pair. This is the generic form.
    """
    body = _b64e(
        json.dumps(
            {"p": payload, "iat": int(issued_at if issued_at is not None else time.time())},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    return body + "." + hmac.new(_secret(secret), body.encode(), sha256).hexdigest()


def verify_payload(token: str, *, secret: bytes | str, max_age: int, now: float | None = None) -> str:
    """Verify and unpack a :func:`sign_payload` token, or raise."""
    if not token or token.count(".") != 1:
        raise AuthError("malformed signed payload")
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(hmac.new(_secret(secret), body.encode(), sha256).hexdigest(), sig):
        raise AuthError("signed payload does not verify")
    try:
        data = json.loads(_b64d(body))
    except (ValueError, binascii.Error) as exc:
        raise AuthError("signed payload is not decodable") from exc
    if not isinstance(data, dict) or not isinstance(data.get("p"), str):
        raise AuthError("signed payload is malformed")
    iat = data.get("iat")
    if not isinstance(iat, (int, float)):
        raise AuthError("signed payload carries no issued-at")
    if (now if now is not None else time.time()) - iat > max_age:
        raise SessionExpired("signed payload is older than max_age")
    return data["p"]


def _cookie_from(request: Any) -> Optional[str]:
    cookies = getattr(request, "cookies", None) or {}
    try:
        return cookies.get(SESSION_COOKIE)
    except AttributeError:  # pragma: no cover - defensive
        return None


def resolve_session_user(
    request: Any,
    *,
    store: CredentialStore,
    secret: bytes | str | None = None,
    max_age: int | None = None,
    repo_root=None,
) -> UserContext:
    """Return the ``UserContext`` for the authenticated session on ``request``.

    Note what this function does not do: it never reads ``request.query_params``,
    ``request.path_params``, ``request.headers`` or any body. The only input taken from
    the request is the signed cookie.
    """
    token = _cookie_from(request)
    if not token:
        raise AuthError("no session cookie; request is unauthenticated")

    user_id = read_session(token, secret=secret, max_age=max_age)

    try:
        creds = store.get(user_id)
    except CredentialNotFound as exc:
        # Valid signature for a tenant that no longer exists — e.g. offboarded while a
        # cookie was still live. Fail closed rather than resolving a hollow context.
        raise AuthError("session tenant " + repr(user_id) + " has no credentials") from exc
    except CredentialStoreError as exc:
        raise AuthError("credential store unusable for tenant " + repr(user_id)) from exc

    from common import paths as _paths

    ctx = UserContext(
        user_id=user_id,
        account_number=creds.account_number,
        broker_server="robinhood-" + user_id,
        data_root=_paths._default_repo_root() if repo_root is None else repo_root,
        retention_days=DEFAULT_RETENTION_DAYS,
        min_keep_snapshots=DEFAULT_MIN_KEEP_SNAPSHOTS,
    )
    return ctx


def login(store: CredentialStore, user_id: str, password: str, *, secret: bytes | str | None = None) -> str:
    """Verify a password and mint a session. Raises ``AuthError`` on any failure.

    The failure message is deliberately identical for unknown-tenant and wrong-password
    so the form cannot be used to enumerate accounts.
    """
    if not store.verify_password(user_id, password):
        raise AuthError("invalid credentials")
    return issue_session(user_id, secret=secret)
