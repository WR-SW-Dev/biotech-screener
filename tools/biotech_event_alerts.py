#!/usr/bin/env python3
"""
Automated biotech event alerts using xAI (Grok) + X Search + Web Search.

What it does:
- Polls xAI on a schedule (run via cron/systemd/GitHub Actions)
- Searches X and the web for new material biotech events
- Restricts results to your watchlist
- Returns structured JSON using xAI structured outputs
- Deduplicates alerts in SQLite
- Sends alerts to Slack and/or email

Environment variables:
  XAI_API_KEY=...
  XAI_MODEL=grok-4-1-fast
  SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=587
  SMTP_USER=you@example.com
  SMTP_PASS=app_password
  ALERT_EMAIL_TO=you@example.com
  ALERT_EMAIL_FROM=you@example.com
  ALERT_DB=biotech_alerts.sqlite3
  ALERT_LOOKBACK_MINUTES=30
  ALERT_TZ=America/New_York
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import smtplib
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Literal, Optional

import requests
from openai import OpenAI
from pydantic import BaseModel, Field

API_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = os.getenv("XAI_MODEL", "grok-4-1-fast")
DEFAULT_DB = os.getenv("ALERT_DB", "biotech_alerts.sqlite3")
DEFAULT_LOOKBACK_MINUTES = int(os.getenv("ALERT_LOOKBACK_MINUTES", "30"))


# ---------- Structured output schema ----------


class Source(BaseModel):
    source_type: Literal["x", "web"] = Field(description="Where the evidence came from")
    publisher: str = Field(description="Publisher, X handle, company, FDA, or news site")
    title: str = Field(description="Short source title")
    url: str = Field(description="Canonical URL if available")
    published_at_utc: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp if known, else null",
    )


class EventAlert(BaseModel):
    ticker: str = Field(description="Public ticker, uppercase")
    company: str = Field(description="Company name")
    category: Literal[
        "mna",
        "clinical",
        "regulatory",
        "financing",
        "leadership",
        "safety",
        "legal",
        "other",
    ] = Field(description="Material event class")
    severity: Literal["critical", "high", "medium"] = Field(description="critical/high/medium only")
    headline: str = Field(description="One-line event headline")
    summary: str = Field(description="2-4 sentence plain-English summary")
    why_it_matters: str = Field(description="Why this matters for investors")
    event_time_utc: Optional[str] = Field(
        default=None,
        description="Best-known event timestamp in ISO-8601 UTC, else null",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Model confidence from 0 to 1")
    sources: list[Source] = Field(default_factory=list)
    official_source_present: bool = Field(
        description="True if one source is company IR, SEC, FDA, exchange, or official account"
    )
    duplicate_of_existing_story: bool = Field(
        description="True if this appears to be a stale/recycled story; should usually be false"
    )


class AlertBatch(BaseModel):
    alerts: list[EventAlert] = Field(default_factory=list)


# ---------- Persistence ----------


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            fingerprint TEXT PRIMARY KEY,
            created_at_utc TEXT NOT NULL,
            ticker TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            headline TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO meta(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
    conn.commit()


def normalize_text(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fingerprint_alert(alert: EventAlert) -> str:
    source_url = alert.sources[0].url if alert.sources else ""
    event_day = (alert.event_time_utc or "")[:10]
    base = "|".join(
        [
            alert.ticker.upper().strip(),
            alert.category,
            normalize_text(alert.headline),
            normalize_text(source_url),
            event_day,
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def alert_exists(conn: sqlite3.Connection, fingerprint: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM alerts WHERE fingerprint = ?",
        (fingerprint,),
    ).fetchone()
    return row is not None


def save_alert(conn: sqlite3.Connection, alert: EventAlert) -> str:
    fp = fingerprint_alert(alert)
    conn.execute(
        """
        INSERT OR IGNORE INTO alerts (
            fingerprint, created_at_utc, ticker, category, severity, headline, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fp,
            utcnow().isoformat(),
            alert.ticker,
            alert.category,
            alert.severity,
            alert.headline,
            alert.model_dump_json(),
        ),
    )
    conn.commit()
    return fp


# ---------- Config / watchlist ----------


@dataclass
class WatchItem:
    ticker: str
    company: str
    aliases: list[str]


def load_watchlist(path: Path) -> list[WatchItem]:
    raw = json.loads(path.read_text())
    items = raw["watchlist"] if isinstance(raw, dict) and "watchlist" in raw else raw
    watchlist: list[WatchItem] = []
    for item in items:
        watchlist.append(
            WatchItem(
                ticker=item["ticker"].upper(),
                company=item["company"],
                aliases=item.get("aliases", []),
            )
        )
    return watchlist


def watchlist_prompt_block(watchlist: list[WatchItem]) -> str:
    lines = []
    for item in watchlist:
        alias_text = ", ".join(item.aliases) if item.aliases else "none"
        lines.append(f"- {item.ticker} | {item.company} | aliases: {alias_text}")
    return "\n".join(lines)


# ---------- xAI call ----------


def build_system_prompt() -> str:
    return """You are a biotech event-monitoring analyst.

Your job:
1) Search X and the web for NEW, MATERIAL events affecting only the watchlist.
2) Return only events that appear new since the supplied timestamp.
3) Ignore stale/recycled stories, old registry entries, speculative message-board chatter,
   low-signal reposts, and generic sector commentary.
4) Favor official sources (company IR, SEC, FDA, exchange notices, company/X executive accounts)
   and well-known news coverage.

Material event categories:
- mna: acquisition, merger, tender, strategic review, definitive buyout, CVR deal
- clinical: pivotal/topline/interim readout, trial halt, enrollment stop, major protocol change
- regulatory: FDA approval, CRL, AdCom, PDUFA update, BTD/RMAT/FT if clearly material
- financing: surprise equity/debt financing, major royalty deal, going-concern rescue
- leadership: CEO/CMO/CFO departure if likely material
- safety: safety signal, hold, boxed warning, death/SAE cluster
- legal: patent loss, major litigation/regulatory enforcement
- other: use only if clearly material

Alerting rules:
- critical: definitive M&A, FDA approval/CRL, halted pivotal trial, clearly price-moving event
- high: likely thesis-changing but slightly less definitive
- medium: meaningful but not urgent

Output rules:
- Only include events you believe are new since the supplied timestamp.
- If an item looks recycled, set duplicate_of_existing_story=true or omit it.
- Every alert must include at least 1 source URL.
- Keep summaries factual and concise.
- Do not include price targets or trading advice.
"""


def build_user_prompt(
    watchlist: list[WatchItem],
    now_utc: datetime,
    since_utc: datetime,
    window_minutes: int,
) -> str:
    return f"""
Current UTC time: {now_utc.isoformat()}
Only alert on events first reported or newly confirmed after: {since_utc.isoformat()}
Nominal poll window: last {window_minutes} minutes

Search both X and the web.
Use the watchlist only. If a story mentions a watchlist company only in passing, exclude it.

Watchlist:
{watchlist_prompt_block(watchlist)}

Return a JSON object matching the provided schema.
If there are no new material events, return {{"alerts": []}}.
"""


def fetch_alerts_from_xai(
    client: OpenAI,
    watchlist: list[WatchItem],
    now_utc: datetime,
    since_utc: datetime,
    window_minutes: int,
    model: str,
) -> AlertBatch:
    from_date = (since_utc - timedelta(days=1)).date().isoformat()
    to_date = now_utc.date().isoformat()

    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": build_system_prompt()},
            {
                "role": "user",
                "content": build_user_prompt(
                    watchlist=watchlist,
                    now_utc=now_utc,
                    since_utc=since_utc,
                    window_minutes=window_minutes,
                ),
            },
        ],
        tools=[
            {
                "type": "x_search",
                "from_date": from_date,
                "to_date": to_date,
                "enable_image_understanding": False,
            },
            {"type": "web_search"},
        ],
        tool_choice="required",
        text_format=AlertBatch,
    )
    return response.output_parsed


# ---------- Filtering / scoring ----------


def passes_local_quality_gate(alert: EventAlert) -> bool:
    if alert.duplicate_of_existing_story:
        return False
    if not alert.sources:
        return False
    if alert.confidence < 0.55:
        return False
    return True


def dedupe_and_filter_new(
    conn: sqlite3.Connection,
    alerts: list[EventAlert],
) -> list[EventAlert]:
    new_alerts: list[EventAlert] = []
    for alert in alerts:
        if not passes_local_quality_gate(alert):
            continue
        fp = fingerprint_alert(alert)
        if alert_exists(conn, fp):
            continue
        new_alerts.append(alert)
    return new_alerts


# ---------- Delivery ----------


def format_alerts_for_text(alerts: list[EventAlert]) -> str:
    lines: list[str] = []
    lines.append(f"Biotech Alert Digest — {utcnow().isoformat()}")
    for a in alerts:
        lines.append("")
        lines.append(f"[{a.severity.upper()}] {a.ticker} — {a.headline}")
        lines.append(f"Category: {a.category}")
        lines.append(f"Company: {a.company}")
        if a.event_time_utc:
            lines.append(f"Event time: {a.event_time_utc}")
        lines.append(f"Confidence: {a.confidence:.2f}")
        lines.append(f"Summary: {a.summary}")
        lines.append(f"Why it matters: {a.why_it_matters}")
        lines.append("Sources:")
        for s in a.sources[:5]:
            lines.append(f"  - ({s.source_type}) {s.publisher}: {s.title} — {s.url}")
    return "\n".join(lines)


def send_slack(webhook_url: str, alerts: list[EventAlert]) -> None:
    if not alerts:
        return
    blocks = []
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Biotech alerts* — {len(alerts)} new event(s)"},
        }
    )
    for a in alerts[:10]:
        src = a.sources[0].url if a.sources else ""
        text = (
            f"*{a.ticker}* — *{a.headline}*\n"
            f"`{a.severity}` / `{a.category}` / confidence {a.confidence:.2f}\n"
            f"{a.summary}\n"
            f"*Why it matters:* {a.why_it_matters}\n"
            f"{src}"
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
        blocks.append({"type": "divider"})

    resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=20)
    resp.raise_for_status()


def send_email(
    host: str,
    port: int,
    user: str,
    password: str,
    to_addr: str,
    from_addr: str,
    alerts: list[EventAlert],
) -> None:
    if not alerts:
        return
    body = format_alerts_for_text(alerts)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"Biotech alerts: {len(alerts)} new event(s)"
    msg["From"] = from_addr
    msg["To"] = to_addr

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())


# ---------- Main ----------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Biotech event alerts via xAI Grok")
    p.add_argument("--watchlist", type=Path, required=True, help="Path to watchlist JSON")
    p.add_argument(
        "--lookback-minutes",
        type=int,
        default=DEFAULT_LOOKBACK_MINUTES,
        help="Fallback window if no prior run state exists",
    )
    p.add_argument("--db", type=Path, default=Path(DEFAULT_DB), help="SQLite DB for dedupe")
    p.add_argument("--dry-run", action="store_true", help="Print alerts but do not send")
    p.add_argument("--stdout-only", action="store_true", help="Print alerts, skip Slack/email")
    p.add_argument("--model", default=DEFAULT_MODEL, help="xAI model name")
    return p.parse_args()


def build_client() -> OpenAI:
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY is not set")
    return OpenAI(api_key=api_key, base_url=API_BASE_URL)


def main() -> int:
    args = parse_args()
    watchlist = load_watchlist(args.watchlist)

    conn = sqlite3.connect(args.db)
    init_db(conn)

    now_utc = utcnow()
    last_success_raw = get_meta(conn, "last_success_utc")
    if last_success_raw:
        since_utc = datetime.fromisoformat(last_success_raw)
        if since_utc.tzinfo is None:
            since_utc = since_utc.replace(tzinfo=timezone.utc)
    else:
        since_utc = now_utc - timedelta(minutes=args.lookback_minutes)

    client = build_client()
    batch = fetch_alerts_from_xai(
        client=client,
        watchlist=watchlist,
        now_utc=now_utc,
        since_utc=since_utc,
        window_minutes=args.lookback_minutes,
        model=args.model,
    )

    candidate_alerts = batch.alerts if batch else []
    new_alerts = dedupe_and_filter_new(conn, candidate_alerts)

    if new_alerts:
        print(format_alerts_for_text(new_alerts))
    else:
        print(f"No new alerts at {now_utc.isoformat()}")

    if new_alerts:
        for alert in new_alerts:
            save_alert(conn, alert)

        if not args.dry_run and not args.stdout_only:
            slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
            if slack_webhook:
                send_slack(slack_webhook, new_alerts)

            smtp_host = os.getenv("SMTP_HOST")
            smtp_port = int(os.getenv("SMTP_PORT", "587"))
            smtp_user = os.getenv("SMTP_USER")
            smtp_pass = os.getenv("SMTP_PASS")
            email_to = os.getenv("ALERT_EMAIL_TO")
            email_from = os.getenv("ALERT_EMAIL_FROM", smtp_user or "")

            email_ready = all([smtp_host, smtp_user, smtp_pass, email_to, email_from])
            if email_ready:
                send_email(
                    host=smtp_host,
                    port=smtp_port,
                    user=smtp_user,
                    password=smtp_pass,
                    to_addr=email_to,
                    from_addr=email_from,
                    alerts=new_alerts,
                )

    set_meta(conn, "last_success_utc", now_utc.isoformat())
    conn.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
