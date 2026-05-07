"""
common/alerts.py — Operator alert helper for the biotech screener.

Sends condition-triggered Telegram alerts for hard operational failures.
Designed for use from ops/QA wrappers only — never from scoring math.

Usage
-----
    from common.alerts import send_operator_alert

    send_operator_alert(
        severity="FAIL",
        system="daily_production",
        message="Snapshot missing after production run completed.",
        dedupe_key="daily_production:snapshot_missing:2026-05-07",
    )

Environment variables (read from repo .env via dotenv, falls back to os.environ)
-----------------
    TELEGRAM_BOT_TOKEN   — bot token from BotFather (required to send)
    TELEGRAM_CHAT_ID     — destination chat ID (required to send)
    ALERTS_DRY_RUN       — set to "1" or "true" to log without sending (tests)

Behaviour
---------
    - Missing token or chat_id: logs a warning and returns False (never raises).
    - ALERTS_DRY_RUN=1: logs the message at WARNING level, skips HTTP, returns True.
    - Duplicate suppression: uses AlertDedupeStore (common/alert_dedupe.py) keyed
      on dedupe_key. Default window: 4 hours. Pass dedupe_key=None to bypass.
    - Dedupe state persisted at: artifacts/alerts/operator_alert_dedupe.json
    - Rate limit: at most MAX_ALERTS_PER_HOUR distinct keys per hour (default 10).
      Protects against runaway loops in callers.
    - HTTP errors: logged at WARNING, returns False.

Severity levels
---------------
    FAIL  — hard failure, operator action required (🔴)
    WARN  — degraded state, monitor closely (🟡)
    INFO  — informational, no action needed (🔵)

Format
------
    🔴 FAIL | daily_production | 2026-05-07 09:15 ET
    Snapshot missing after production run completed.
    dedupe_key: daily_production:snapshot_missing:2026-05-07
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DEDUPE_STATE_PATH = REPO_ROOT / "artifacts" / "alerts" / "operator_alert_dedupe.json"
RATE_LIMIT_STATE_PATH = REPO_ROOT / "artifacts" / "alerts" / "rate_limit.json"

DEDUPE_WINDOW_HOURS: float = 4.0
MAX_ALERTS_PER_HOUR: int = 10
PRUNE_DAYS: int = 7

SEVERITY_EMOJI = {
    "FAIL": "🔴",
    "WARN": "🟡",
    "INFO": "🔵",
}

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_env() -> None:
    """Load repo .env into os.environ if dotenv is available."""
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(REPO_ROOT / ".env", override=False)
    except ImportError:
        pass


def _is_dry_run() -> bool:
    val = os.environ.get("ALERTS_DRY_RUN", "").strip().lower()
    return val in ("1", "true", "yes")


def _fmt_et(dt: datetime) -> str:
    """Format UTC datetime as ET wall-clock string (no pytz dependency)."""
    # ET = UTC-5 (EST) or UTC-4 (EDT); close enough for alert timestamps
    # Use a fixed -4 offset (EDT) — good enough for ops context
    et = dt.utcoffset() and dt or dt.replace(tzinfo=timezone.utc)
    et_naive = et.astimezone(timezone(timedelta(hours=-4)))
    return et_naive.strftime("%Y-%m-%d %H:%M ET")


def _build_message(severity: str, system: str, message: str, dedupe_key: Optional[str]) -> str:
    emoji = SEVERITY_EMOJI.get(severity, "⚪")
    now_et = _fmt_et(datetime.now(timezone.utc))
    lines = [
        f"{emoji} {severity} | {system} | {now_et}",
        message,
    ]
    if dedupe_key:
        lines.append(f"key: {dedupe_key}")
    return "\n".join(lines)


def _send_telegram(token: str, chat_id: str, text: str) -> bool:
    """POST to Telegram sendMessage. Returns True on success."""
    url = TELEGRAM_API.format(token=token)
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            if not body.get("ok"):
                logger.warning("Telegram API returned ok=false: %s", body)
                return False
            return True
    except urllib.error.HTTPError as exc:
        logger.warning("Telegram HTTP %s: %s", exc.code, exc.read()[:200])
        return False
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Dedupe store (simplified — reuses AlertDedupeStore pattern but generic)
# ---------------------------------------------------------------------------

_DEDUPE_SCHEMA = "operator_alert_dedupe.v1"


def _load_dedupe() -> dict:
    path = DEDUPE_STATE_PATH
    if not path.exists():
        return {"schema": _DEDUPE_SCHEMA, "entries": {}, "rate_limit": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema") != _DEDUPE_SCHEMA:
            return {"schema": _DEDUPE_SCHEMA, "entries": {}, "rate_limit": {}}
        return raw
    except Exception:
        return {"schema": _DEDUPE_SCHEMA, "entries": {}, "rate_limit": {}}


def _save_dedupe(state: dict) -> None:
    path = DEDUPE_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".op_alert.", suffix=".json.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _is_suppressed(state: dict, dedupe_key: str, now: datetime) -> bool:
    """Return True if this dedupe_key was sent within DEDUPE_WINDOW_HOURS."""
    entries = state.get("entries", {})
    entry = entries.get(dedupe_key)
    if entry is None:
        return False
    try:
        last_sent = datetime.fromisoformat(entry["last_sent_at"].replace("Z", "+00:00"))
        return (now - last_sent) < timedelta(hours=DEDUPE_WINDOW_HOURS)
    except (KeyError, ValueError):
        return False


def _is_rate_limited(state: dict, now: datetime) -> bool:
    """Return True if MAX_ALERTS_PER_HOUR distinct sends have occurred in last hour."""
    rl = state.get("rate_limit", {})
    cutoff = (now - timedelta(hours=1)).isoformat()
    recent = [ts for ts in rl.values() if ts >= cutoff]
    return len(recent) >= MAX_ALERTS_PER_HOUR


def _record_sent(state: dict, dedupe_key: Optional[str], now: datetime) -> None:
    ts = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if dedupe_key:
        entries = state.setdefault("entries", {})
        prior = entries.get(dedupe_key, {})
        entries[dedupe_key] = {
            "first_sent_at": prior.get("first_sent_at", ts),
            "last_sent_at": ts,
        }
    rl = state.setdefault("rate_limit", {})
    rl[ts] = ts
    # Prune rate_limit entries older than 2h
    cutoff = (now - timedelta(hours=2)).isoformat()
    state["rate_limit"] = {k: v for k, v in rl.items() if v >= cutoff}
    # Prune dedupe entries older than PRUNE_DAYS
    cutoff_days = (now - timedelta(days=PRUNE_DAYS)).isoformat()
    entries = state.get("entries", {})
    stale = [k for k, v in entries.items() if v.get("last_sent_at", "") < cutoff_days]
    for k in stale:
        del entries[k]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def send_operator_alert(
    *,
    severity: str,
    system: str,
    message: str,
    dedupe_key: Optional[str] = None,
) -> bool:
    """Send a Telegram alert to the operator.

    Parameters
    ----------
    severity:   "FAIL" | "WARN" | "INFO"
    system:     short label, e.g. "daily_production" | "ruleset_health" | "bioshort"
    message:    human-readable description of the condition
    dedupe_key: opaque string for suppression; None bypasses dedupe entirely.
                Recommend format: "<system>:<condition>:<date>"
                e.g. "daily_production:snapshot_missing:2026-05-07"

    Returns
    -------
    True if sent (or dry-run), False if suppressed, rate-limited, or failed.
    """
    _load_env()

    now = datetime.now(timezone.utc)
    text = _build_message(severity, system, message, dedupe_key)

    # Dry-run mode
    if _is_dry_run():
        logger.warning("[DRY_RUN] send_operator_alert: %s", text)
        return True

    # Load credentials
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.warning("send_operator_alert: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; skipping.")
        return False

    # Dedupe + rate limit
    state = _load_dedupe()

    if dedupe_key and _is_suppressed(state, dedupe_key, now):
        logger.debug("send_operator_alert: suppressed (dedupe_key=%s)", dedupe_key)
        return False

    if _is_rate_limited(state, now):
        logger.warning(
            "send_operator_alert: rate limit reached (%d/hr); dropping %s",
            MAX_ALERTS_PER_HOUR,
            dedupe_key or "<no key>",
        )
        return False

    # Send
    ok = _send_telegram(token, chat_id, text)
    if ok:
        _record_sent(state, dedupe_key, now)
        try:
            _save_dedupe(state)
        except Exception as exc:
            logger.warning("send_operator_alert: failed to save dedupe state: %s", exc)

    return ok


__all__ = ["send_operator_alert"]
