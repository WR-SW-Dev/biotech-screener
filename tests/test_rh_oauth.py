#!/usr/bin/env python3
"""Tests for the Robinhood MCP OAuth client.

Context, because it overturns the premise this work started from: connecting Robinhood
does **not** require driving a Claude Code session. The MCP endpoint answers an
unauthenticated request with a standard RFC 9728 challenge:

    WWW-Authenticate: Bearer resource_metadata="https://agent.robinhood.com/
                      .well-known/oauth-protected-resource/mcp/trading"

and its authorization-server metadata advertises PKCE (S256), Dynamic Client
Registration, and both authorization_code and refresh_token grants, with
``token_endpoint_auth_methods_supported: ["none"]`` — a public client. Claude Code is
simply an OAuth client implementing the MCP spec; any backend can be one too.

These tests pin the flow against a fake transport so they never touch the network.
"""

import json
import time

import pytest

from common.rh_oauth import (
    OAuthError,
    TokenSet,
    build_authorize_url,
    discover,
    exchange_code,
    new_pkce,
    refresh_tokens,
    register_client,
)

METADATA = {
    "authorization_endpoint": "https://robinhood.com/oauth",
    "token_endpoint": "https://api.robinhood.com/oauth2/token/",
    "registration_endpoint": "https://agent.robinhood.com/oauth/trading/register",
    "issuer": "https://agent.robinhood.com/mcp/trading",
    "code_challenge_methods_supported": ["S256"],
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "scopes_supported": ["internal"],
    "token_endpoint_auth_methods_supported": ["none"],
}

REDIRECT = "https://dash.example/connect/robinhood/callback"


class _Resp:
    def __init__(self, payload, status_code=200):
        self._p, self.status_code = payload, status_code
        self.text = json.dumps(payload) if isinstance(payload, dict) else str(payload)

    def json(self):
        return self._p


class _Transport:
    def __init__(self, gets=None, posts=None):
        self.gets, self.posts = list(gets or []), list(posts or [])
        self.get_calls, self.post_calls = [], []

    def get(self, url, *, timeout=None):
        self.get_calls.append(url)
        nxt = self.gets.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def post(self, url, *, json=None, data=None, headers=None, timeout=None):
        self.post_calls.append({"url": url, "json": json, "data": data})
        nxt = self.posts.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class TestDiscovery:
    def test_returns_the_endpoints(self):
        t = _Transport(gets=[_Resp(METADATA)])
        m = discover(transport=t)
        assert m.authorization_endpoint == "https://robinhood.com/oauth"
        assert m.token_endpoint == "https://api.robinhood.com/oauth2/token/"
        assert m.registration_endpoint.endswith("/oauth/trading/register")

    def test_supports_pkce_and_refresh(self):
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        assert m.supports_pkce is True
        assert m.supports_refresh is True

    def test_missing_pkce_support_is_refused(self):
        """Without PKCE a public client cannot protect the code exchange."""
        bad = dict(METADATA, code_challenge_methods_supported=["plain"])
        with pytest.raises(OAuthError, match="S256"):
            discover(transport=_Transport(gets=[_Resp(bad)]))

    def test_http_error_raises(self):
        with pytest.raises(OAuthError):
            discover(transport=_Transport(gets=[_Resp({"e": 1}, status_code=500)]))


class TestPKCE:
    def test_verifier_and_challenge_differ(self):
        v, c = new_pkce()
        assert v != c

    def test_verifier_length_is_within_spec(self):
        v, _ = new_pkce()
        assert 43 <= len(v) <= 128

    def test_challenge_is_deterministic_for_a_verifier(self):
        v, c1 = new_pkce()
        _, c2 = new_pkce(verifier=v)
        assert c1 == c2

    def test_each_call_is_unique(self):
        assert len({new_pkce()[0] for _ in range(20)}) == 20


class TestRegistration:
    def test_returns_client_id(self):
        t = _Transport(posts=[_Resp({"client_id": "abc123", "token_endpoint_auth_method": "none"})])
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        assert register_client(m, REDIRECT, transport=t) == "abc123"

    def test_redirect_uri_is_sent(self):
        t = _Transport(posts=[_Resp({"client_id": "abc"})])
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        register_client(m, REDIRECT, transport=t)
        assert t.post_calls[0]["json"]["redirect_uris"] == [REDIRECT]

    def test_missing_client_id_raises(self):
        t = _Transport(posts=[_Resp({"nope": 1})])
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        with pytest.raises(OAuthError):
            register_client(m, REDIRECT, transport=t)


class TestAuthorizeUrl:
    def _url(self, **over):
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        kw = dict(client_id="cid", redirect_uri=REDIRECT, challenge="chal", state="st")
        kw.update(over)
        return build_authorize_url(m, **kw)

    def test_points_at_the_authorization_endpoint(self):
        assert self._url().startswith("https://robinhood.com/oauth?")

    def test_carries_pkce_challenge_and_method(self):
        u = self._url()
        assert "code_challenge=chal" in u
        assert "code_challenge_method=S256" in u

    def test_carries_state(self):
        assert "state=st" in self._url()

    def test_no_client_secret_is_ever_included(self):
        assert "client_secret" not in self._url()

    def test_requests_the_advertised_scope(self):
        assert "scope=internal" in self._url()


class TestTokenExchange:
    def test_returns_a_tokenset(self):
        payload = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "internal"}
        t = _Transport(posts=[_Resp(payload)])
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        ts = exchange_code(m, client_id="cid", redirect_uri=REDIRECT, code="c", verifier="v", transport=t)
        assert isinstance(ts, TokenSet)
        assert ts.access_token == "at"
        assert ts.refresh_token == "rt"
        assert ts.expires_at > time.time()

    def test_sends_verifier_and_no_secret(self):
        t = _Transport(posts=[_Resp({"access_token": "at"})])
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        exchange_code(m, client_id="cid", redirect_uri=REDIRECT, code="c", verifier="v", transport=t)
        sent = t.post_calls[0]["data"]
        assert sent["code_verifier"] == "v"
        assert sent["grant_type"] == "authorization_code"
        assert "client_secret" not in sent

    def test_error_response_raises(self):
        t = _Transport(posts=[_Resp({"error": "invalid_grant"}, status_code=400)])
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        with pytest.raises(OAuthError, match="invalid_grant"):
            exchange_code(m, client_id="cid", redirect_uri=REDIRECT, code="c", verifier="v", transport=t)

    def test_missing_access_token_raises(self):
        t = _Transport(posts=[_Resp({"refresh_token": "rt"})])
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        with pytest.raises(OAuthError):
            exchange_code(m, client_id="cid", redirect_uri=REDIRECT, code="c", verifier="v", transport=t)


class TestRefresh:
    def test_returns_new_tokens(self):
        t = _Transport(posts=[_Resp({"access_token": "at2", "refresh_token": "rt2", "expires_in": 60})])
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        ts = refresh_tokens(m, client_id="cid", refresh_token="rt", transport=t)
        assert ts.access_token == "at2"
        assert t.post_calls[0]["data"]["grant_type"] == "refresh_token"

    def test_keeps_the_old_refresh_token_when_none_returned(self):
        """Some servers omit refresh_token on refresh; dropping it would end the session."""
        t = _Transport(posts=[_Resp({"access_token": "at2", "expires_in": 60})])
        m = discover(transport=_Transport(gets=[_Resp(METADATA)]))
        ts = refresh_tokens(m, client_id="cid", refresh_token="rt-original", transport=t)
        assert ts.refresh_token == "rt-original"


class TestTokenSet:
    def test_is_expired_respects_the_skew_window(self):
        ts = TokenSet(access_token="a", refresh_token=None, expires_at=time.time() + 30, scope="")
        assert ts.is_expired(skew_seconds=60) is True
        assert ts.is_expired(skew_seconds=5) is False

    def test_no_expiry_is_treated_as_expired(self):
        """Unknown lifetime must not be assumed valid indefinitely."""
        assert TokenSet(access_token="a", refresh_token=None, expires_at=None, scope="").is_expired() is True

    def test_repr_does_not_leak_tokens(self):
        ts = TokenSet(access_token="SECRET_AT", refresh_token="SECRET_RT", expires_at=None, scope="")
        assert "SECRET_AT" not in repr(ts)
        assert "SECRET_RT" not in repr(ts)
