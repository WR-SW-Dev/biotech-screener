"""Unit tests for common.alert_email."""

from __future__ import annotations

import pytest

from common.alert_email import is_smtp_configured, resolve_recipient, send_email

SMTP_ENV_VARS = (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "ALERT_EMAIL_TO",
    "ALERT_RECIPIENT",
)


def _clear_env(monkeypatch):
    for name in SMTP_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def test_is_smtp_configured_false_when_unset(monkeypatch):
    _clear_env(monkeypatch)
    assert is_smtp_configured() is False


def test_is_smtp_configured_false_when_partial(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SMTP_USER", "u@example.com")
    assert is_smtp_configured() is False
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    assert is_smtp_configured() is True


def test_resolve_recipient_prefers_param(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ALERT_EMAIL_TO", "env@example.com")
    assert resolve_recipient("override@example.com") == "override@example.com"


def test_resolve_recipient_falls_back_to_alert_email_to(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ALERT_EMAIL_TO", "a@example.com")
    monkeypatch.setenv("ALERT_RECIPIENT", "b@example.com")
    assert resolve_recipient() == "a@example.com"


def test_resolve_recipient_falls_back_to_alert_recipient(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ALERT_RECIPIENT", "b@example.com")
    assert resolve_recipient() == "b@example.com"


def test_resolve_recipient_none_when_nothing_set(monkeypatch):
    _clear_env(monkeypatch)
    assert resolve_recipient() is None


# ---------------------------------------------------------------------------
# send_email — injected fake SMTP
# ---------------------------------------------------------------------------
class FakeSMTP:
    """Context-manager SMTP double that records calls."""

    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.starttls_called = False
        self.login_args = None
        self.sendmail_args = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, user, password):
        self.login_args = (user, password)

    def sendmail(self, sender, to, msg):
        self.sendmail_args = (sender, to, msg)


class FakeSMTPThatFails(FakeSMTP):
    def sendmail(self, sender, to, msg):
        raise RuntimeError("kaboom")


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    FakeSMTP.instances = []
    yield
    FakeSMTP.instances = []


def test_send_email_skips_when_unconfigured(monkeypatch):
    _clear_env(monkeypatch)
    assert send_email("subject", "body", smtp_cls=FakeSMTP) is False
    assert FakeSMTP.instances == []


def test_send_email_skips_when_no_recipient(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SMTP_USER", "u@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    assert send_email("s", "b", smtp_cls=FakeSMTP) is False
    assert FakeSMTP.instances == []


def test_send_email_sends_plain_text(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SMTP_USER", "u@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setenv("ALERT_EMAIL_TO", "to@example.com")
    assert send_email("hello", "world body", smtp_cls=FakeSMTP) is True
    assert len(FakeSMTP.instances) == 1
    inst = FakeSMTP.instances[0]
    assert inst.starttls_called is True
    assert inst.login_args == ("u@example.com", "pw")
    sender, recipients, raw = inst.sendmail_args
    assert sender == "u@example.com"
    assert recipients == ["to@example.com"]
    assert "Subject: hello" in raw
    assert "world body" in raw


def test_send_email_prefers_param_over_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SMTP_USER", "u@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setenv("ALERT_EMAIL_TO", "env@example.com")
    send_email("s", "b", to_addr="override@example.com", smtp_cls=FakeSMTP)
    _, recipients, _ = FakeSMTP.instances[0].sendmail_args
    assert recipients == ["override@example.com"]


def test_send_email_returns_false_on_smtp_failure(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SMTP_USER", "u@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setenv("ALERT_EMAIL_TO", "to@example.com")
    assert send_email("s", "b", smtp_cls=FakeSMTPThatFails) is False


def test_send_email_uses_alert_recipient_fallback(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("SMTP_USER", "u@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setenv("ALERT_RECIPIENT", "fallback@example.com")
    send_email("s", "b", smtp_cls=FakeSMTP)
    _, recipients, _ = FakeSMTP.instances[0].sendmail_args
    assert recipients == ["fallback@example.com"]
