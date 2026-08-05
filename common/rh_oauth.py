"""OAuth 2.1 client for the Robinhood MCP endpoint.

**This replaces the assumption that connecting Robinhood needs a Claude Code session.**

The premise behind the original ask was that obtaining a bearer token is "inherently a
Claude Code MCP flow" — that a web backend would have to spawn and drive a Claude Code
session to complete OAuth on the user's behalf. Probing the endpoint shows otherwise.

An unauthenticated request returns a standard RFC 9728 challenge::

    HTTP/2 401
    www-authenticate: Bearer resource_metadata="https://agent.robinhood.com/
                      .well-known/oauth-protected-resource/mcp/trading"

and the authorization-server metadata advertises::

    authorization_endpoint            https://robinhood.com/oauth
    token_endpoint                    https://api.robinhood.com/oauth2/token/
    registration_endpoint             https://agent.robinhood.com/oauth/trading/register
    code_challenge_methods_supported  ["S256"]
    grant_types_supported             ["authorization_code", "refresh_token"]
    token_endpoint_auth_methods       ["none"]

That is a textbook OAuth 2.1 **public client** with PKCE and Dynamic Client Registration.
Claude Code is simply an OAuth client implementing the MCP authorization spec; there is
nothing proprietary to bridge. Dynamic registration was verified live against the real
endpoint: it accepts an arbitrary ``redirect_uri`` and issues a ``client_id`` with
``token_endpoint_auth_method: none``.

So the dashboard is its own OAuth client. No subprocess, no Claude Code dependency, no
session to drive — a redirect, a callback, and a token exchange.

One capability worth noting: the server supports ``refresh_token``. Today's design stores
a static bearer that silently goes stale when it expires; with refresh, a connection can
be kept alive instead.

Python 3.10 compatible.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

DISCOVERY_URL = "https://agent.robinhood.com/.well-known/oauth-authorization-server/mcp/trading"
RESOURCE = "https://agent.robinhood.com/mcp/trading"
DEFAULT_TIMEOUT = 30.0

#: Refresh this far before nominal expiry, so a request never races the boundary.
DEFAULT_SKEW_SECONDS = 120


class OAuthError(Exception):
    """Discovery, registration, or a token operation failed."""


@dataclass(frozen=True)
class AuthServerMetadata:
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str
    issuer: str
    scopes: "tuple[str, ...]"
    supports_pkce: bool
    supports_refresh: bool


@dataclass(frozen=True)
class TokenSet:
    """Tokens for one tenant. ``__repr__`` is overridden so they cannot be logged."""

    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[float]
    scope: str

    def __repr__(self) -> str:
        return "TokenSet(access_token=<redacted>, refresh_token=<redacted>, expires_at=" + str(self.expires_at) + ")"

    def is_expired(self, *, skew_seconds: float = DEFAULT_SKEW_SECONDS) -> bool:
        """True when the token should be refreshed.

        An unknown expiry counts as expired: assuming an unbounded lifetime would let a
        dead token sit in the store until a trade failed on it.
        """
        if self.expires_at is None:
            return True
        return time.time() + skew_seconds >= self.expires_at


class _HttpxTransport:
    """Injection seam so tests never touch the network."""

    def get(self, url, *, timeout=None):
        import httpx

        return httpx.get(url, timeout=timeout, follow_redirects=True)

    def post(self, url, *, json=None, data=None, headers=None, timeout=None):  # noqa: A002
        import httpx

        return httpx.post(url, json=json, data=data, headers=headers, timeout=timeout)


def _check(resp: Any, what: str) -> "dict[str, Any]":
    status = getattr(resp, "status_code", 200)
    try:
        payload = resp.json()
    except Exception as exc:
        raise OAuthError(what + " returned an undecodable body: " + str(exc)) from exc
    if not isinstance(payload, dict):
        raise OAuthError(what + " returned a non-object body")
    if status >= 400 or payload.get("error"):
        detail = payload.get("error_description") or payload.get("error") or str(status)
        raise OAuthError(what + " failed: " + str(detail))
    return payload


def discover(
    *, url: str = DISCOVERY_URL, transport: Any = None, timeout: float = DEFAULT_TIMEOUT
) -> AuthServerMetadata:
    """Fetch and validate the authorization-server metadata."""
    t = transport or _HttpxTransport()
    try:
        resp = t.get(url, timeout=timeout)
    except Exception as exc:
        raise OAuthError("could not reach OAuth discovery at " + url + ": " + str(exc)) from exc
    m = _check(resp, "OAuth discovery")

    methods = [str(x).upper() for x in (m.get("code_challenge_methods_supported") or [])]
    if "S256" not in methods:
        raise OAuthError(
            "authorization server does not advertise S256 PKCE; refusing to run a public-client "
            "flow without it (advertised: " + ", ".join(methods or ["none"]) + ")"
        )

    for field in ("authorization_endpoint", "token_endpoint"):
        if not m.get(field):
            raise OAuthError("authorization server metadata is missing " + field)

    grants = [str(x) for x in (m.get("grant_types_supported") or [])]
    return AuthServerMetadata(
        authorization_endpoint=str(m["authorization_endpoint"]),
        token_endpoint=str(m["token_endpoint"]),
        registration_endpoint=str(m.get("registration_endpoint") or ""),
        issuer=str(m.get("issuer") or ""),
        scopes=tuple(str(s) for s in (m.get("scopes_supported") or ())),
        supports_pkce=True,
        supports_refresh="refresh_token" in grants,
    )


def new_pkce(*, verifier: Optional[str] = None) -> "tuple[str, str]":
    """Return ``(verifier, challenge)`` for PKCE S256."""
    v = verifier or base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    return v, challenge


def register_client(
    meta: AuthServerMetadata,
    redirect_uri: str,
    *,
    client_name: str = "Wake Robin Biotech Dashboard",
    transport: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Dynamically register this deployment and return its ``client_id``.

    The id is not a secret (this is a public client) but it *is* bound to the exact
    ``redirect_uri`` registered here, so a deployment whose callback URL changes must
    register again.
    """
    if not meta.registration_endpoint:
        raise OAuthError("authorization server advertises no registration_endpoint")
    t = transport or _HttpxTransport()
    body = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    try:
        resp = t.post(meta.registration_endpoint, json=body, timeout=timeout)
    except Exception as exc:
        raise OAuthError("dynamic client registration failed: " + str(exc)) from exc
    payload = _check(resp, "dynamic client registration")
    client_id = payload.get("client_id")
    if not client_id:
        raise OAuthError("registration response carried no client_id")
    return str(client_id)


def build_authorize_url(
    meta: AuthServerMetadata,
    *,
    client_id: str,
    redirect_uri: str,
    challenge: str,
    state: str,
) -> str:
    """Build the URL the user's browser is sent to in order to consent."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if meta.scopes:
        params["scope"] = " ".join(meta.scopes)
    return meta.authorization_endpoint + "?" + urlencode(params)


def _token_request(
    meta: AuthServerMetadata, data: "dict[str, str]", *, transport: Any, timeout: float, what: str
) -> "dict[str, Any]":
    t = transport or _HttpxTransport()
    try:
        resp = t.post(
            meta.token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            timeout=timeout,
        )
    except Exception as exc:
        raise OAuthError(what + " failed: " + str(exc)) from exc
    return _check(resp, what)


def _to_tokenset(payload: "dict[str, Any]", *, fallback_refresh: Optional[str] = None) -> TokenSet:
    access = payload.get("access_token")
    if not access:
        raise OAuthError("token response carried no access_token")
    expires_in = payload.get("expires_in")
    expires_at = time.time() + float(expires_in) if isinstance(expires_in, (int, float)) else None
    return TokenSet(
        access_token=str(access),
        # Servers may omit refresh_token on a refresh; dropping it would silently end the
        # connection at the next expiry.
        refresh_token=str(payload.get("refresh_token") or fallback_refresh or "") or None,
        expires_at=expires_at,
        scope=str(payload.get("scope") or ""),
    )


def exchange_code(
    meta: AuthServerMetadata,
    *,
    client_id: str,
    redirect_uri: str,
    code: str,
    verifier: str,
    transport: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> TokenSet:
    """Exchange an authorization code for tokens. No client secret — public client."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    return _to_tokenset(_token_request(meta, data, transport=transport, timeout=timeout, what="token exchange"))


def refresh_tokens(
    meta: AuthServerMetadata,
    *,
    client_id: str,
    refresh_token: str,
    transport: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> TokenSet:
    """Trade a refresh token for a fresh access token."""
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
    payload = _token_request(meta, data, transport=transport, timeout=timeout, what="token refresh")
    return _to_tokenset(payload, fallback_refresh=refresh_token)
