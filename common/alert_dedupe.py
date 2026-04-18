"""Persistent on-disk dedupe state for alert-sending agents.

Primary consumer: `tools/build_intraday_mover_watch.py` (Spec 063 Phase 3).

Purpose
-------
Phase 2's throttle (`max_immediate_emails_per_hour`) caps emails within a
single invocation. When the builder runs on a cron cadence (Phase 3), the
same HIGH-severity mover will re-appear in consecutive polls and spam the
operator unless state is persisted across invocations.

This module provides a tiny JSON-backed store at
`artifacts/intraday_mover_watch/sent_alerts.json` that records which
`dedupe_key`s have been sent and lets callers decide whether to send again
based on Spec 063's step-up rules:

- Re-send if the prior send is older than `window_hours` (default 4h).
- Re-send if the abs-move widened by ≥ `step_up_pp` from the last-sent
  abs-move (absolute-value comparison, so a -6% that becomes -10% also
  widens).
- Re-send if rel-move vs XBI widened by ≥ `step_up_pp`.
- Severity step-ups (MEDIUM → HIGH) and news-status improvements
  (NONE → OFFICIAL) are captured naturally by the dedupe_key design:
  both components are part of the hash, so a step-up produces a
  different key and the new key is absent from the store → send.

Design is intentionally boring: JSON file, atomic write, schema version,
prune old entries. No external deps.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("alert_dedupe")

SCHEMA_VERSION = "sent_alerts.v1"
DEFAULT_WINDOW_HOURS = 4.0
DEFAULT_STEP_UP_PP = 3.0
DEFAULT_PRUNE_DAYS = 7


@dataclass(frozen=True)
class SendDecision:
    should_send: bool
    reason: str  # "new" | "expired" | "widened_abs" | "widened_rel" | "suppressed_recent"


def _parse_iso(ts: str) -> datetime:
    # Tolerate both "...Z" and "...+00:00"
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _fmt_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlertDedupeStore:
    """JSON-backed dedupe state.

    Not thread-safe; intended for single-process cron invocations. Each run
    opens, decides, records, saves, and exits.
    """

    def __init__(
        self,
        path: Path,
        *,
        window_hours: float = DEFAULT_WINDOW_HOURS,
        step_up_pp: float = DEFAULT_STEP_UP_PP,
    ):
        self.path = Path(path)
        self.window_hours = window_hours
        self.step_up_pp = step_up_pp
        self._data = self._load()

    # ------------------------------------------------------------------ I/O
    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"schema": SCHEMA_VERSION, "entries": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema") != SCHEMA_VERSION:
                logger.warning("dedupe state at %s has unknown schema; starting fresh", self.path)
                return {"schema": SCHEMA_VERSION, "entries": {}}
            entries = raw.get("entries")
            if not isinstance(entries, dict):
                raw["entries"] = {}
            return raw
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("failed to load dedupe state (%s); starting fresh", exc)
            return {"schema": SCHEMA_VERSION, "entries": {}}

    def save(self) -> None:
        """Atomic write via tempfile + rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".sent_alerts.", suffix=".json.tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, sort_keys=True)
            os.replace(tmp_path, self.path)
        except Exception:
            # best-effort cleanup
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ API
    def decide(
        self,
        dedupe_key: str,
        *,
        abs_move_pct: float,
        rel_move_pct: Optional[float],
        now: Optional[datetime] = None,
    ) -> SendDecision:
        """Return whether this alert should be sent, given prior state."""
        now = now or datetime.now(timezone.utc)
        entries = self._data.get("entries", {})
        prior = entries.get(dedupe_key)
        if prior is None:
            return SendDecision(True, "new")

        try:
            last_sent = _parse_iso(prior["last_sent_at"])
        except (KeyError, ValueError):
            # Corrupt entry — treat as absent
            return SendDecision(True, "new")

        age = now - last_sent
        if age >= timedelta(hours=self.window_hours):
            return SendDecision(True, "expired")

        # Widening check: absolute magnitude of the move vs what we last sent.
        prior_abs = float(prior.get("abs_move_pct") or 0.0)
        if abs(abs_move_pct) - abs(prior_abs) >= self.step_up_pp:
            return SendDecision(True, "widened_abs")

        prior_rel = prior.get("rel_move_vs_xbi_pct")
        if rel_move_pct is not None and prior_rel is not None:
            if abs(rel_move_pct) - abs(float(prior_rel)) >= self.step_up_pp:
                return SendDecision(True, "widened_rel")
        elif rel_move_pct is not None and prior_rel is None:
            # First time we have XBI context → treat as widening
            if abs(rel_move_pct) >= self.step_up_pp:
                return SendDecision(True, "widened_rel")

        return SendDecision(False, "suppressed_recent")

    def record_sent(
        self,
        dedupe_key: str,
        *,
        ticker: str,
        severity: str,
        news_status: str,
        abs_move_pct: float,
        rel_move_pct: Optional[float],
        now: Optional[datetime] = None,
    ) -> None:
        now = now or datetime.now(timezone.utc)
        ts = _fmt_iso(now)
        entries = self._data.setdefault("entries", {})
        prior = entries.get(dedupe_key) or {}
        entries[dedupe_key] = {
            "ticker": ticker,
            "severity": severity,
            "news_status": news_status,
            "abs_move_pct": float(abs_move_pct),
            "rel_move_vs_xbi_pct": float(rel_move_pct) if rel_move_pct is not None else None,
            "first_sent_at": prior.get("first_sent_at", ts),
            "last_sent_at": ts,
        }

    def prune_older_than(self, days: int = DEFAULT_PRUNE_DAYS) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        entries = self._data.setdefault("entries", {})
        stale = []
        for key, val in entries.items():
            try:
                last = _parse_iso(val["last_sent_at"])
                if last < cutoff:
                    stale.append(key)
            except (ValueError, KeyError, TypeError):
                stale.append(key)
        for key in stale:
            del entries[key]
        return len(stale)

    def snapshot(self) -> Dict[str, Any]:
        """Return a read-only copy of the current state (for tests/debugging)."""
        return json.loads(json.dumps(self._data))


__all__ = [
    "SendDecision",
    "AlertDedupeStore",
    "SCHEMA_VERSION",
    "DEFAULT_WINDOW_HOURS",
    "DEFAULT_STEP_UP_PP",
    "DEFAULT_PRUNE_DAYS",
]
