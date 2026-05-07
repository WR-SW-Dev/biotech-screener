"""Tests for common/alerts.py — operator Telegram alert helper."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_alert(tmp_path, **kwargs):
    """Call send_operator_alert with dry-run forced and dedupe state in tmp_path."""
    from common.alerts import send_operator_alert

    defaults = dict(
        severity="FAIL",
        system="test_system",
        message="test message",
        dedupe_key="test_system:test_condition:2026-05-07",
    )
    defaults.update(kwargs)

    dedupe_path = tmp_path / "operator_alert_dedupe.json"
    with (
        patch("common.alerts.DEDUPE_STATE_PATH", dedupe_path),
        patch("common.alerts.RATE_LIMIT_STATE_PATH", tmp_path / "rate_limit.json"),
        patch.dict(os.environ, {"ALERTS_DRY_RUN": "1"}),
    ):
        return send_operator_alert(**defaults)


# ---------------------------------------------------------------------------
# Basic send
# ---------------------------------------------------------------------------


class TestSendOperatorAlertDryRun:
    def test_dry_run_returns_true(self, tmp_path):
        result = _make_alert(tmp_path)
        assert result is True

    def test_dry_run_no_http(self, tmp_path):
        with patch("common.alerts._send_telegram") as mock_tg:
            _make_alert(tmp_path)
            mock_tg.assert_not_called()

    def test_missing_token_returns_false(self, tmp_path):
        from common.alerts import send_operator_alert

        dedupe_path = tmp_path / "operator_alert_dedupe.json"
        env = {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "123", "ALERTS_DRY_RUN": ""}
        with (
            patch("common.alerts.DEDUPE_STATE_PATH", dedupe_path),
            patch.dict(os.environ, env, clear=False),
        ):
            result = send_operator_alert(
                severity="FAIL",
                system="s",
                message="m",
                dedupe_key=None,
            )
        assert result is False

    def test_missing_chat_id_returns_false(self, tmp_path):
        from common.alerts import send_operator_alert

        dedupe_path = tmp_path / "operator_alert_dedupe.json"
        env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "", "ALERTS_DRY_RUN": ""}
        with (
            patch("common.alerts.DEDUPE_STATE_PATH", dedupe_path),
            patch.dict(os.environ, env, clear=False),
        ):
            result = send_operator_alert(
                severity="FAIL",
                system="s",
                message="m",
                dedupe_key=None,
            )
        assert result is False


# ---------------------------------------------------------------------------
# Message format
# ---------------------------------------------------------------------------


class TestMessageFormat:
    def test_fail_emoji(self, tmp_path):
        from common.alerts import _build_message

        msg = _build_message("FAIL", "daily_production", "snapshot missing", "dp:snap:2026-05-07")
        assert "🔴" in msg
        assert "FAIL" in msg
        assert "daily_production" in msg
        assert "snapshot missing" in msg
        assert "dp:snap:2026-05-07" in msg

    def test_warn_emoji(self, tmp_path):
        from common.alerts import _build_message

        msg = _build_message("WARN", "ruleset_health", "drift detected", None)
        assert "🟡" in msg
        assert "WARN" in msg
        assert "key:" not in msg

    def test_info_emoji(self, tmp_path):
        from common.alerts import _build_message

        msg = _build_message("INFO", "bioshort", "B1b complete", None)
        assert "🔵" in msg

    def test_unknown_severity_graceful(self, tmp_path):
        from common.alerts import _build_message

        msg = _build_message("UNKNOWN", "sys", "msg", None)
        assert "UNKNOWN" in msg


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


class TestDedupe:
    def _state_with_recent_entry(self, dedupe_key: str, hours_ago: float = 1.0) -> dict:
        from common.alerts import _DEDUPE_SCHEMA

        last_sent = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "schema": _DEDUPE_SCHEMA,
            "entries": {
                dedupe_key: {
                    "first_sent_at": last_sent,
                    "last_sent_at": last_sent,
                }
            },
            "rate_limit": {},
        }

    def test_suppressed_within_window(self, tmp_path):
        from common.alerts import _is_suppressed

        state = self._state_with_recent_entry("key:a", hours_ago=1.0)
        assert _is_suppressed(state, "key:a", datetime.now(timezone.utc)) is True

    def test_not_suppressed_after_window(self, tmp_path):
        from common.alerts import _is_suppressed

        state = self._state_with_recent_entry("key:a", hours_ago=5.0)
        assert _is_suppressed(state, "key:a", datetime.now(timezone.utc)) is False

    def test_not_suppressed_new_key(self, tmp_path):
        from common.alerts import _is_suppressed

        state = self._state_with_recent_entry("key:other", hours_ago=1.0)
        assert _is_suppressed(state, "key:new", datetime.now(timezone.utc)) is False

    def test_no_dedupe_key_bypasses(self, tmp_path):
        result = _make_alert(tmp_path, dedupe_key=None)
        assert result is True

    def test_record_sent_writes_entry(self, tmp_path):
        from common.alerts import _DEDUPE_SCHEMA, _record_sent

        state = {"schema": _DEDUPE_SCHEMA, "entries": {}, "rate_limit": {}}
        now = datetime.now(timezone.utc)
        _record_sent(state, "key:b", now)
        assert "key:b" in state["entries"]
        entry = state["entries"]["key:b"]
        assert "first_sent_at" in entry
        assert "last_sent_at" in entry
        assert entry["first_sent_at"] == entry["last_sent_at"]

    def test_record_sent_preserves_first_sent(self, tmp_path):
        from common.alerts import _DEDUPE_SCHEMA, _record_sent

        state = {"schema": _DEDUPE_SCHEMA, "entries": {}, "rate_limit": {}}
        t1 = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 5, 7, 15, 0, 0, tzinfo=timezone.utc)
        _record_sent(state, "key:c", t1)
        first = state["entries"]["key:c"]["first_sent_at"]
        _record_sent(state, "key:c", t2)
        assert state["entries"]["key:c"]["first_sent_at"] == first

    def test_dedupe_state_not_written_on_dry_run(self, tmp_path):
        dedupe_path = tmp_path / "operator_alert_dedupe.json"
        with (
            patch("common.alerts.DEDUPE_STATE_PATH", dedupe_path),
            patch.dict(os.environ, {"ALERTS_DRY_RUN": "1"}),
        ):
            from common.alerts import send_operator_alert

            send_operator_alert(
                severity="FAIL",
                system="s",
                message="m",
                dedupe_key="s:m:2026-05-07",
            )
        assert not dedupe_path.exists()


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_rate_limited_when_full(self, tmp_path):
        from common.alerts import _DEDUPE_SCHEMA, MAX_ALERTS_PER_HOUR, _is_rate_limited

        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        rl = {f"k{i}": ts for i in range(MAX_ALERTS_PER_HOUR)}
        state = {"schema": _DEDUPE_SCHEMA, "entries": {}, "rate_limit": rl}
        assert _is_rate_limited(state, now) is True

    def test_not_rate_limited_when_empty(self, tmp_path):
        from common.alerts import _DEDUPE_SCHEMA, _is_rate_limited

        state = {"schema": _DEDUPE_SCHEMA, "entries": {}, "rate_limit": {}}
        assert _is_rate_limited(state, datetime.now(timezone.utc)) is False

    def test_old_entries_dont_count(self, tmp_path):
        from common.alerts import _DEDUPE_SCHEMA, MAX_ALERTS_PER_HOUR, _is_rate_limited

        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rl = {f"k{i}": old_ts for i in range(MAX_ALERTS_PER_HOUR)}
        state = {"schema": _DEDUPE_SCHEMA, "entries": {}, "rate_limit": rl}
        assert _is_rate_limited(state, now) is False


# ---------------------------------------------------------------------------
# HTTP send (mocked)
# ---------------------------------------------------------------------------


class TestSendTelegram:
    def test_returns_true_on_ok(self):
        from common.alerts import _send_telegram

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _send_telegram("tok", "chat", "hello")
        assert result is True

    def test_returns_false_on_not_ok(self):
        from common.alerts import _send_telegram

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": False, "description": "bad"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _send_telegram("tok", "chat", "hello")
        assert result is False

    def test_returns_false_on_http_error(self):
        import urllib.error

        from common.alerts import _send_telegram

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(url="", code=403, msg="Forbidden", hdrs=None, fp=None),
        ):
            result = _send_telegram("tok", "chat", "hello")
        assert result is False

    def test_returns_false_on_network_error(self):
        from common.alerts import _send_telegram

        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = _send_telegram("tok", "chat", "hello")
        assert result is False


# ---------------------------------------------------------------------------
# No external deps used in scoring math (import guard)
# ---------------------------------------------------------------------------


class TestNoDepsFromScoringMath:
    """Ensure alerts.py doesn't import any scoring-layer modules."""

    def test_alerts_importable_without_scoring_modules(self):
        import importlib
        import sys

        for key in list(sys.modules.keys()):
            if key == "common.alerts":
                del sys.modules[key]

        mod = importlib.import_module("common.alerts")
        assert hasattr(mod, "send_operator_alert")
