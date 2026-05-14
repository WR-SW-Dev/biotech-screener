"""Shared SMTP alert-email helper.

Used by read-only alerting agents (Grok watch, intraday mover watch, Herald
digest) to send plain-text email notifications. Intentionally minimal:
- plain text body (HTML optional)
- configuration via env vars; fails softly if creds are missing
- returns True/False so callers can treat sending as best-effort

Env vars
--------
SMTP_HOST          default smtp.gmail.com
SMTP_PORT          default 587 (STARTTLS)
SMTP_USER          sender address (required)
SMTP_PASSWORD      app password (required; quote if it contains spaces)
ALERT_EMAIL_TO     primary recipient
ALERT_RECIPIENT    fallback recipient (older repo convention)

Callers can override the recipient per-call with `to_addr=`.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("alert_email")

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587
SMTP_TIMEOUT_S = 30


def is_smtp_configured() -> bool:
    """True iff SMTP_USER and SMTP_PASSWORD are both set."""
    return bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))


def resolve_recipient(to_addr: Optional[str] = None) -> Optional[list[str]]:
    """Pick recipients from: param → ALERT_EMAIL_TO → ALERT_RECIPIENT.

    Supports comma-separated email addresses. Returns list of emails or None.
    """
    recipients_str = to_addr or os.environ.get("ALERT_EMAIL_TO") or os.environ.get("ALERT_RECIPIENT")
    if not recipients_str:
        return None
    return [e.strip() for e in recipients_str.split(",") if e.strip()]


def send_email(
    subject: str,
    body_text: str,
    *,
    body_html: Optional[str] = None,
    to_addr: Optional[str] = None,
    smtp_cls=None,  # dependency injection for tests
) -> bool:
    """Send an email via SMTP. Returns True on success, False on any failure.

    Parameters
    ----------
    subject : str
    body_text : str   plain-text body (required)
    body_html : Optional[str]   optional HTML alternative
    to_addr : Optional[str]   override the default recipient(s); comma-separated supported
    smtp_cls : type   injection point for tests; defaults to smtplib.SMTP

    Soft failure modes (return False, log a warning):
    - SMTP_USER / SMTP_PASSWORD not set
    - no recipient resolvable
    - any smtplib exception during send

    Callers that need an exception to propagate should check
    `is_smtp_configured()` themselves first.
    """
    if not is_smtp_configured():
        logger.warning("SMTP credentials not configured — skipping email: %s", subject)
        return False

    recipients = resolve_recipient(to_addr)
    if not recipients:
        logger.warning("no recipient resolvable — skipping email: %s", subject)
        return False

    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASSWORD"]
    smtp_host = os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST)
    smtp_port = int(os.environ.get("SMTP_PORT", DEFAULT_SMTP_PORT))

    msg = MIMEMultipart("alternative") if body_html else MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    transport = smtp_cls if smtp_cls is not None else smtplib.SMTP
    try:
        with transport(smtp_host, smtp_port, timeout=SMTP_TIMEOUT_S) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipients, msg.as_string())
        logger.info("email sent to %s: %s", ", ".join(recipients), subject)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("email send failed (%s): %s", subject, exc)
        return False


__all__ = ["is_smtp_configured", "resolve_recipient", "send_email"]
