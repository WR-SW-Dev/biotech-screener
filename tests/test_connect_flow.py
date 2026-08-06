#!/usr/bin/env python3
"""Tests for the self-service connect flow (Robinhood OAuth + Anthropic key).

Network is never touched: BIOTECH_RH_CLIENT_ID short-circuits dynamic registration, and
discovery is patched. What is under test is the dashboard's half of the flow — the CSRF
and state guards, and that a pending connection belongs to whoever started it.
"""

import importlib
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402

from common.credstore import CredentialStore, generate_key  # noqa: E402
from common.mcp_exec import MCPError, MultipleAccountsFound  # noqa: E402
from common.rh_oauth import AuthServerMetadata, TokenSet  # noqa: E402

META = AuthServerMetadata(
    authorization_endpoint="https://robinhood.com/oauth",
    token_endpoint="https://api.robinhood.com/oauth2/token/",
    registration_endpoint="https://agent.robinhood.com/oauth/trading/register",
    issuer="https://agent.robinhood.com/mcp/trading",
    scopes=("internal",),
    supports_pkce=True,
    supports_refresh=True,
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    key = generate_key()
    monkeypatch.setenv("BIOTECH_CREDSTORE_KEY", key.decode())
    monkeypatch.setenv("BIOTECH_CREDSTORE_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("BIOTECH_SESSION_SECRET", "connect-test-secret")
    monkeypatch.setenv("BIOTECH_MULTI_TENANT", "1")
    monkeypatch.setenv("BIOTECH_COOKIE_INSECURE", "1")
    monkeypatch.setenv("BIOTECH_RH_CLIENT_ID", "test-client")
    monkeypatch.setenv("BIOTECH_PUBLIC_BASE_URL", "http://testserver")

    # Both tenants start unbound, which is what a self-signed-up user actually looks like:
    # a password and nothing else. The account number arrives from the OAuth callback.
    store = CredentialStore(tmp_path / "c.db", key=key)
    for uid, pw in (("scott", "pw-scott"), ("darren", "pw-darren")):
        store.ensure_tenant(uid)
        store.set_password(uid, pw)

    import dashboard.app as app_module

    importlib.reload(app_module)
    app_module._credstore_singleton = None
    monkeypatch.setattr(app_module, "discover", lambda **kw: META)
    return app_module, store


def _client(app_module, user="scott", pw="pw-scott"):
    c = TestClient(app_module.app, raise_server_exceptions=False)
    c.post("/login", data={"user_id": user, "password": pw})
    return c


class TestConnectPage:
    def test_requires_authentication(self, env):
        app_module, _ = env
        c = TestClient(app_module.app, raise_server_exceptions=False)
        assert c.get("/connect", follow_redirects=False).status_code == 302

    def test_shows_both_as_unconnected_initially(self, env):
        app_module, _ = env
        body = _client(app_module).get("/connect").text
        assert body.count("Not connected") == 2

    def test_reflects_a_stored_anthropic_key(self, env):
        app_module, store = env
        store.set_anthropic_key("scott", "sk-ant-abc")
        assert "Not connected" in _client(app_module).get("/connect").text
        assert _client(app_module).get("/connect").text.count("Not connected") == 1


class TestAnthropicKey:
    def _csrf(self, user="scott"):
        from dashboard.basket import issue_csrf

        return issue_csrf(user)

    def test_valid_key_is_stored(self, env):
        app_module, store = env
        r = _client(app_module).post(
            "/connect/anthropic",
            data={"csrf_token": self._csrf(), "anthropic_key": "sk-ant-good"},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/connect?connected=anthropic"
        assert store.get("scott").anthropic_api_key == "sk-ant-good"  # pragma: allowlist secret

    def test_wrong_shape_is_refused(self, env):
        app_module, store = env
        r = _client(app_module).post(
            "/connect/anthropic",
            data={"csrf_token": self._csrf(), "anthropic_key": "not-a-key"},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/connect?error=keyshape"
        assert store.get("scott").anthropic_api_key is None

    def test_bad_csrf_is_refused(self, env):
        app_module, store = env
        r = _client(app_module).post(
            "/connect/anthropic",
            data={"csrf_token": "forged", "anthropic_key": "sk-ant-x"},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/connect?error=csrf"
        assert store.get("scott").anthropic_api_key is None

    def test_another_tenants_csrf_token_is_refused(self, env):
        app_module, store = env
        r = _client(app_module).post(
            "/connect/anthropic",
            data={"csrf_token": self._csrf("darren"), "anthropic_key": "sk-ant-x"},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/connect?error=csrf"
        assert store.get("scott").anthropic_api_key is None


class TestRobinhoodAuthorizeRedirect:
    def _start(self, app_module, **kw):
        c = _client(app_module, **kw)
        r = c.get("/connect/robinhood/start", follow_redirects=False)
        return c, r, parse_qs(urlparse(r.headers.get("location", "")).query)

    def test_redirects_to_the_authorization_endpoint(self, env):
        app_module, _ = env
        _, r, _ = self._start(app_module)
        assert r.status_code == 302
        assert r.headers["location"].startswith("https://robinhood.com/oauth?")

    def test_uses_pkce_s256(self, env):
        app_module, _ = env
        _, _, q = self._start(app_module)
        assert q["code_challenge_method"] == ["S256"]
        assert q["code_challenge"][0]

    def test_never_sends_a_client_secret(self, env):
        app_module, _ = env
        _, _, q = self._start(app_module)
        assert "client_secret" not in q

    def test_state_cookie_is_httponly(self, env):
        app_module, _ = env
        _, r, _ = self._start(app_module)
        assert "httponly" in r.headers.get("set-cookie", "").lower()


class TestRobinhoodCallbackGuards:
    def _start(self, app_module, user="scott", pw="pw-scott"):
        c = _client(app_module, user, pw)
        r = c.get("/connect/robinhood/start", follow_redirects=False)
        return c, parse_qs(urlparse(r.headers["location"]).query)["state"][0]

    def test_mismatched_state_is_refused(self, env):
        app_module, _ = env
        c, _ = self._start(app_module)
        r = c.get("/connect/robinhood/callback?code=x&state=FORGED", follow_redirects=False)
        assert r.headers["location"] == "/connect?error=state"

    def test_missing_code_is_refused(self, env):
        app_module, _ = env
        c, st = self._start(app_module)
        r = c.get("/connect/robinhood/callback?state=" + st, follow_redirects=False)
        assert r.headers["location"] == "/connect?error=nocode"

    def test_user_denial_is_reported(self, env):
        app_module, _ = env
        c, _ = self._start(app_module)
        r = c.get("/connect/robinhood/callback?error=access_denied", follow_redirects=False)
        assert r.headers["location"] == "/connect?error=denied"

    def test_callback_without_a_pending_state_is_refused(self, env):
        app_module, _ = env
        c = _client(app_module)
        r = c.get("/connect/robinhood/callback?code=x&state=whatever", follow_redirects=False)
        assert r.headers["location"] == "/connect?error=expired"

    def test_unauthenticated_callback_never_stores_anything(self, env):
        app_module, store = env
        c = TestClient(app_module.app, raise_server_exceptions=False)
        r = c.get("/connect/robinhood/callback?code=x&state=y", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/login"
        assert store.get("scott").robinhood_bearer == ""


def _complete_callback(
    app_module, monkeypatch, *, user="scott", pw="pw-scott", access="new-access", account="111111111"
):
    """Drive start -> callback with the network halves stubbed. Returns the response."""
    monkeypatch.setattr(
        app_module,
        "exchange_code",
        lambda meta, **kw: TokenSet(access_token=access, refresh_token="new-refresh", expires_at=9e9, scope="internal"),
    )
    if not isinstance(account, BaseException):
        monkeypatch.setattr(app_module, "fetch_account_number", lambda **kw: account)
    else:
        monkeypatch.setattr(app_module, "fetch_account_number", _raiser(account))
    c = _client(app_module, user, pw)
    st = parse_qs(urlparse(c.get("/connect/robinhood/start", follow_redirects=False).headers["location"]).query)[
        "state"
    ][0]
    return c.get("/connect/robinhood/callback?code=abc&state=" + st, follow_redirects=False)


def _raiser(exc):
    def _raise(**kw):
        raise exc

    return _raise


class TestSuccessfulExchange:
    def test_tokens_are_stored_for_the_signed_in_tenant(self, env, monkeypatch):
        app_module, store = env
        r = _complete_callback(app_module, monkeypatch)
        assert r.headers["location"] == "/connect?connected=robinhood"
        assert store.get("scott").robinhood_bearer == "new-access"
        refresh, expires = store.get_robinhood_tokens("scott")
        assert refresh == "new-refresh"
        assert expires == 9e9

    def test_the_other_tenant_is_untouched(self, env, monkeypatch):
        app_module, store = env
        _complete_callback(app_module, monkeypatch, account="333333333")
        assert store.get("darren").robinhood_bearer == ""


class TestAccountNumberIsBoundOnConnect:
    """Without this the tenant connects successfully and then cannot trade, silently.

    execute_order() raises UnprovenAccountError on an empty expected account, so a token
    with no account number behind it is a connection that refuses every order — including
    a review — at the click that was supposed to trade.
    """

    def test_account_number_comes_from_the_broker(self, env, monkeypatch):
        app_module, store = env
        _complete_callback(app_module, monkeypatch, account="802349084")
        assert store.get("scott").account_number == "802349084"

    def test_account_number_is_fetched_with_the_new_token(self, env, monkeypatch):
        """It must be the token just granted, not some ambient credential."""
        app_module, _ = env
        seen = {}
        monkeypatch.setattr(
            app_module,
            "exchange_code",
            lambda meta, **kw: TokenSet(access_token="fresh", refresh_token="r", expires_at=9e9, scope=""),
        )

        def _capture(*, bearer, **kw):
            seen["bearer"] = bearer
            return "111111111"

        monkeypatch.setattr(app_module, "fetch_account_number", _capture)
        c = _client(app_module)
        st = parse_qs(urlparse(c.get("/connect/robinhood/start", follow_redirects=False).headers["location"]).query)[
            "state"
        ][0]
        c.get("/connect/robinhood/callback?code=abc&state=" + st, follow_redirects=False)
        assert seen["bearer"] == "fresh"

    def test_a_tenant_cannot_claim_another_tenants_account(self, env, monkeypatch):
        app_module, store = env
        store.set_account_number("darren", "222222222")
        r = _complete_callback(app_module, monkeypatch, account="222222222")
        assert r.headers["location"] == "/connect?error=acctclaimed"
        assert store.get("scott").account_number == ""

    def test_a_refused_claim_stores_no_token_either(self, env, monkeypatch):
        """Fail closed and leave no partial state: no token for an unusable account."""
        app_module, store = env
        store.set_account_number("darren", "222222222")
        _complete_callback(app_module, monkeypatch, account="222222222")
        assert store.get("scott").robinhood_bearer == ""

    def test_ambiguous_account_is_refused_not_guessed(self, env, monkeypatch):
        app_module, store = env
        r = _complete_callback(app_module, monkeypatch, account=MultipleAccountsFound(["1", "2"]))
        assert r.headers["location"] == "/connect?error=multiaccount"
        assert store.get("scott").account_number == ""
        assert store.get("scott").robinhood_bearer == ""

    def test_discovery_failure_stores_nothing(self, env, monkeypatch):
        app_module, store = env
        r = _complete_callback(app_module, monkeypatch, account=MCPError("upstream is down"))
        assert r.headers["location"] == "/connect?error=account"
        assert store.get("scott").account_number == ""
        assert store.get("scott").robinhood_bearer == ""

    def test_reconnecting_the_same_account_still_works(self, env, monkeypatch):
        app_module, store = env
        _complete_callback(app_module, monkeypatch, account="111111111")
        r = _complete_callback(app_module, monkeypatch, access="second-token", account="111111111")
        assert r.headers["location"] == "/connect?connected=robinhood"
        assert store.get("scott").account_number == "111111111"
        assert store.get("scott").robinhood_bearer == "second-token"
