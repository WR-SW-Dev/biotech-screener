#!/usr/bin/env python3
"""Tests for dashboard session authentication (PR 2).

The property this file exists to defend is narrow and load-bearing:

    the acting tenant is derived from the signed session and from nothing else.

If a ``user_id`` supplied anywhere in a request could influence resolution, every
downstream control — credential lookup, trading guard, path scoping — would be
bypassable by editing a URL. ``TestUserIdCannotComeFromTheRequest`` is the regression
barrier for that and should never be deleted.
"""

import time

import pytest

from common.credstore import CredentialStore, generate_key
from dashboard.auth import SESSION_COOKIE, AuthError, SessionExpired, issue_session, read_session, resolve_session_user


@pytest.fixture()
def secret() -> bytes:
    return b"unit-test-signing-secret-not-real"


@pytest.fixture()
def store(tmp_path):
    s = CredentialStore(tmp_path / "cred.db", key=generate_key())
    s.put("scott", account_number="111111111", robinhood_bearer="rh-scott")
    s.set_password("scott", "scott-password")
    s.put("darren", account_number="802349084", robinhood_bearer="rh-darren")
    s.set_password("darren", "darren-password")
    return s


class TestSessionToken:
    def test_round_trip(self, secret):
        tok = issue_session("scott", secret=secret)
        assert read_session(tok, secret=secret) == "scott"

    def test_tampered_payload_rejected(self, secret):
        """Swap the subject to another tenant, keep the original signature."""
        import base64
        import json

        tok = issue_session("scott", secret=secret)
        body, sig = tok.rsplit(".", 1)
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        assert payload["sub"] == "scott"
        payload["sub"] = "darren"
        forged_body = (
            base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
            .decode()
            .rstrip("=")
        )
        with pytest.raises(AuthError):
            read_session(forged_body + "." + sig, secret=secret)

    def test_signature_from_other_secret_rejected(self, secret):
        tok = issue_session("scott", secret=b"attacker-secret")
        with pytest.raises(AuthError):
            read_session(tok, secret=secret)

    def test_garbage_rejected(self, secret):
        for junk in ["", "...", "abc", "a.b.c.d"]:
            with pytest.raises(AuthError):
                read_session(junk, secret=secret)

    def test_absolute_expiry_enforced(self, secret):
        tok = issue_session("scott", secret=secret, issued_at=time.time() - 10_000, max_age=60)
        with pytest.raises(SessionExpired):
            read_session(tok, secret=secret, max_age=60)

    def test_not_expired_within_window(self, secret):
        tok = issue_session("scott", secret=secret, issued_at=time.time() - 10, max_age=600)
        assert read_session(tok, secret=secret, max_age=600) == "scott"


class TestUserIdCannotComeFromTheRequest:
    """The core isolation property. Do not delete."""

    def _req(self, cookie=None, **request_controlled):
        class _Req:
            def __init__(self):
                self.cookies = {SESSION_COOKIE: cookie} if cookie else {}
                self.query_params = dict(request_controlled)
                self.headers = {k.replace("_", "-"): v for k, v in request_controlled.items()}
                self.path_params = dict(request_controlled)

        return _Req()

    def test_query_param_user_id_is_ignored(self, secret, store):
        tok = issue_session("scott", secret=secret)
        ctx = resolve_session_user(self._req(cookie=tok, user_id="darren"), secret=secret, store=store)
        assert ctx.user_id == "scott"
        assert ctx.account_number == "111111111"

    def test_header_user_id_is_ignored(self, secret, store):
        tok = issue_session("scott", secret=secret)
        ctx = resolve_session_user(self._req(cookie=tok, x_user_id="darren"), secret=secret, store=store)
        assert ctx.user_id == "scott"

    def test_no_cookie_is_unauthenticated_even_with_user_id_supplied(self, secret, store):
        with pytest.raises(AuthError):
            resolve_session_user(self._req(user_id="darren"), secret=secret, store=store)

    def test_session_for_unknown_tenant_fails_closed(self, secret, store):
        tok = issue_session("ghost", secret=secret)
        with pytest.raises(AuthError):
            resolve_session_user(self._req(cookie=tok), secret=secret, store=store)

    def test_resolved_context_carries_that_tenants_account_only(self, secret, store):
        tok = issue_session("darren", secret=secret)
        ctx = resolve_session_user(self._req(cookie=tok, user_id="scott"), secret=secret, store=store)
        assert ctx.account_number == "802349084"


class TestLoginFlow:
    def test_correct_password_authenticates(self, store):
        assert store.verify_password("scott", "scott-password") is True

    def test_wrong_password_refused(self, store):
        assert store.verify_password("scott", "darren-password") is False
