#!/usr/bin/env python3
"""Tests for self-service signup (GET/POST /signup).

Before this route existed the login page was a door with no way to get a key: the only
way to create a tenant was tools/provision_tenant.py on the host. The properties worth
pinning are the ones that stop signup from being a way *around* the other controls:

* a taken username is refused, never adopted — otherwise signing up as an existing user
  would reset their password and hand over their account
* the new tenant lands on /connect, not on a basket it cannot act on
* signup mints exactly one tenant and cannot set an account number, so it can never
  produce something the trading guard would let trade
"""

import importlib

import pytest

pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402

from common.credstore import CredentialNotFound, CredentialStore, generate_key  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    key = generate_key()
    monkeypatch.setenv("BIOTECH_CREDSTORE_KEY", key.decode())
    monkeypatch.setenv("BIOTECH_CREDSTORE_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("BIOTECH_SESSION_SECRET", "signup-test-secret")
    monkeypatch.setenv("BIOTECH_MULTI_TENANT", "1")
    monkeypatch.setenv("BIOTECH_COOKIE_INSECURE", "1")
    monkeypatch.delenv("BIOTECH_SIGNUP_INVITE_CODE", raising=False)

    store = CredentialStore(tmp_path / "c.db", key=key)

    import dashboard.app as app_module

    importlib.reload(app_module)
    app_module._credstore_singleton = None
    return app_module, store


def _client(app_module):
    return TestClient(app_module.app, raise_server_exceptions=False)


def _signup(client, user="newbie", pw="hunter2", confirm=None, **extra):
    data = {"user_id": user, "password": pw, "password_confirm": pw if confirm is None else confirm}
    data.update(extra)
    return client.post("/signup", data=data, follow_redirects=False)


class TestSignupIsReachable:
    def test_form_is_served_without_a_session(self, env):
        app_module, _ = env
        r = _client(app_module).get("/signup")
        assert r.status_code == 200
        assert 'name="user_id"' in r.text

    def test_login_page_links_to_it(self, env):
        app_module, _ = env
        assert 'href="/signup"' in _client(app_module).get("/login").text


class TestSuccessfulSignup:
    def test_creates_a_tenant_with_a_working_password(self, env):
        app_module, store = env
        _signup(_client(app_module))
        assert store.list_user_ids() == ["newbie"]
        assert store.verify_password("newbie", "hunter2") is True

    def test_redirects_to_connect_not_the_basket(self, env):
        app_module, _ = env
        r = _signup(_client(app_module))
        assert r.status_code == 302
        assert r.headers["location"] == "/connect"

    def test_signs_the_new_user_in(self, env):
        app_module, _ = env
        c = _client(app_module)
        _signup(c)
        # The session cookie from signup alone must be enough to reach /connect.
        assert c.get("/connect", follow_redirects=False).status_code == 200

    def test_session_cookie_is_httponly(self, env):
        app_module, _ = env
        assert "httponly" in _signup(_client(app_module)).headers.get("set-cookie", "").lower()

    def test_username_is_lowercased(self, env):
        app_module, store = env
        _signup(_client(app_module), user="MixedCase")
        assert store.list_user_ids() == ["mixedcase"]

    def test_new_tenant_has_no_account_number_or_token(self, env):
        """Signup must not be able to produce something the trading guard would pass."""
        app_module, store = env
        _signup(_client(app_module))
        creds = store.get("newbie")
        assert creds.account_number == ""
        assert creds.robinhood_bearer == ""


class TestSignupRefusals:
    def test_existing_username_is_refused(self, env):
        app_module, store = env
        _signup(_client(app_module), user="taken", pw="first-pw")
        r = _signup(_client(app_module), user="taken", pw="second-pw")
        assert r.status_code == 409
        assert "already taken" in r.text

    def test_refusal_does_not_reset_the_existing_password(self, env):
        """The whole point of refusing: signup must never be a password-reset oracle."""
        app_module, store = env
        _signup(_client(app_module), user="taken", pw="first-pw")
        _signup(_client(app_module), user="taken", pw="second-pw")
        assert store.verify_password("taken", "first-pw") is True
        assert store.verify_password("taken", "second-pw") is False

    def test_mismatched_confirmation_is_refused(self, env):
        app_module, store = env
        r = _signup(_client(app_module), pw="one", confirm="two")
        assert r.status_code == 400
        assert store.list_user_ids() == []

    def test_empty_password_is_refused(self, env):
        app_module, store = env
        r = _signup(_client(app_module), pw="", confirm="")
        assert r.status_code == 400
        assert store.list_user_ids() == []

    @pytest.mark.parametrize("bad", ["../escape", "a", "has space", "UPPER!", "_legacy", ""])
    def test_invalid_user_ids_are_refused(self, env, bad):
        """Same charset provision_tenant.py enforces — these become filesystem paths."""
        app_module, store = env
        r = _signup(_client(app_module), user=bad)
        assert r.status_code == 400
        assert store.list_user_ids() == []

    def test_a_refused_signup_creates_no_row(self, env):
        app_module, store = env
        _signup(_client(app_module), user="../escape")
        with pytest.raises(CredentialNotFound):
            store.get("newbie")


class TestInviteCode:
    def test_no_code_configured_means_open_signup(self, env):
        app_module, store = env
        assert _signup(_client(app_module)).status_code == 302
        assert store.list_user_ids() == ["newbie"]

    def test_configured_code_is_required(self, env, monkeypatch):
        app_module, store = env
        monkeypatch.setenv("BIOTECH_SIGNUP_INVITE_CODE", "let-me-in")
        r = _signup(_client(app_module))
        assert r.status_code == 403
        assert store.list_user_ids() == []

    def test_wrong_code_is_refused(self, env, monkeypatch):
        app_module, store = env
        monkeypatch.setenv("BIOTECH_SIGNUP_INVITE_CODE", "let-me-in")
        assert _signup(_client(app_module), invite_code="wrong").status_code == 403
        assert store.list_user_ids() == []

    def test_correct_code_is_accepted(self, env, monkeypatch):
        app_module, store = env
        monkeypatch.setenv("BIOTECH_SIGNUP_INVITE_CODE", "let-me-in")
        r = _signup(_client(app_module), invite_code="let-me-in")
        assert r.status_code == 302
        assert store.list_user_ids() == ["newbie"]

    def test_form_asks_for_the_code_when_configured(self, env, monkeypatch):
        app_module, _ = env
        monkeypatch.setenv("BIOTECH_SIGNUP_INVITE_CODE", "let-me-in")
        assert 'name="invite_code"' in _client(app_module).get("/signup").text

    def test_form_omits_the_code_when_not_configured(self, env):
        app_module, _ = env
        assert 'name="invite_code"' not in _client(app_module).get("/signup").text
