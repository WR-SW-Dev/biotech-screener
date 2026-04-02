#!/usr/bin/env python3
"""Build and email biotech news digest from Herald classified releases.

Three windows per day:
  morning (08:00): last close (prior 16:00) → now
  midday  (15:00): 08:00 → now
  evening (18:00): 15:00 → now

Usage:
    python3 scripts/build_news_digest.py --window morning
    python3 scripts/build_news_digest.py --window midday
    python3 scripts/build_news_digest.py --window evening
    python3 scripts/build_news_digest.py --window morning --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RELEASES_DIR = PROJECT_ROOT / "data" / "press_releases"
CLASSIFIED_DIR = RELEASES_DIR / "classified"
UNIVERSE_PATH = PROJECT_ROOT / "production_data" / "universe.json"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "news_digest"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
ALERT_RECIPIENT = os.environ.get("ALERT_RECIPIENT", "")

MAX_ITEMS = 10
MAX_PER_TICKER = 3

# Category display order
CATEGORY_ORDER = ["regulatory", "clinical", "corporate", "financing", "other"]
CATEGORY_LABELS = {
    "regulatory": "Regulatory",
    "clinical": "Clinical / Data",
    "corporate": "Corporate",
    "financing": "Financing",
    "other": "Other",
}


def load_universe() -> set[str]:
    data = json.loads(UNIVERSE_PATH.read_text())
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            return {d["ticker"].upper() for d in data if "ticker" in d}
        return {s.upper() for s in data if isinstance(s, str)}
    return set()


def load_classified_releases(lookback_days: int = 3) -> list[dict]:
    """Load recent classified releases."""
    releases = []
    today = date.today()
    for days_ago in range(lookback_days + 1):
        d = today - timedelta(days=days_ago)
        path = CLASSIFIED_DIR / f"classified_{d.isoformat()}.jsonl"
        if not path.exists():
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        releases.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return releases


def load_raw_releases(lookback_days: int = 3) -> list[dict]:
    """Load recent raw releases as fallback if no classified data."""
    releases = []
    today = date.today()
    for days_ago in range(lookback_days + 1):
        d = today - timedelta(days=days_ago)
        path = RELEASES_DIR / f"releases_{d.isoformat()}.jsonl"
        if not path.exists():
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = json.loads(line)
                        r.setdefault("event_category", "other")
                        r.setdefault("event_subtype", "unclassified")
                        releases.append(r)
                    except json.JSONDecodeError:
                        pass
    return releases


def filter_window(releases: list[dict], window: str) -> list[dict]:
    """Filter releases to the appropriate time window."""
    now = datetime.now(timezone.utc)
    today_8am = now.replace(hour=12, minute=0, second=0, microsecond=0)  # 8am ET = 12:00 UTC
    today_3pm = now.replace(hour=19, minute=0, second=0, microsecond=0)  # 3pm ET = 19:00 UTC
    yesterday_close = (now - timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)  # 4pm ET

    if window == "morning":
        start = yesterday_close
        end = now
    elif window == "midday":
        start = today_8am
        end = now
    elif window == "evening":
        start = today_3pm
        end = now
    else:
        start = now - timedelta(hours=24)
        end = now

    filtered = []
    for r in releases:
        # Use classified_at_utc or fetched_at_utc as timestamp
        ts_str = r.get("classified_at_utc") or r.get("fetched_at_utc") or r.get("published_at_utc") or ""
        if not ts_str:
            # Include if no timestamp (better to over-include than miss)
            filtered.append(r)
            continue
        try:
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if start <= ts <= end:
                filtered.append(r)
        except (ValueError, TypeError):
            filtered.append(r)

    return filtered


def dedupe_and_limit(releases: list[dict], universe: set[str]) -> list[dict]:
    """Filter to universe, dedupe, limit per ticker."""
    # Filter to followed tickers
    filtered = [r for r in releases if r.get("ticker", "").upper() in universe]

    # Dedupe by content_hash or dedupe_key
    seen = set()
    deduped = []
    for r in filtered:
        key = r.get("dedupe_key") or r.get("content_hash") or r.get("headline", "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    # Limit per ticker
    ticker_counts: dict[str, int] = {}
    limited = []
    for r in deduped:
        t = r.get("ticker", "")
        ticker_counts[t] = ticker_counts.get(t, 0) + 1
        if ticker_counts[t] <= MAX_PER_TICKER:
            limited.append(r)

    # Sort: actionable first, then by category order
    def sort_key(r):
        cat = r.get("event_category", "other")
        cat_idx = CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else 99
        is_actionable = r.get("classification") == "actionable"
        return (0 if is_actionable else 1, cat_idx, r.get("ticker", ""))

    limited.sort(key=sort_key)
    return limited[:MAX_ITEMS]


def build_digest_text(items: list[dict], window: str) -> str:
    """Build plain-text digest."""
    today_str = date.today().strftime("%b %d, %Y")
    window_label = {"morning": "Pre-Market", "midday": "Midday", "evening": "End of Day"}.get(window, window)

    if not items:
        return (
            f"Biotech News Digest — {window_label} {today_str}\n\n"
            f"No major updates for followed tickers.\n\n"
            f"Source: Herald (company IR + wire services)\n"
        )

    lines = [f"Biotech News Digest — {window_label} {today_str}", f"{len(items)} items", ""]

    # Group by category
    by_cat: dict[str, list[dict]] = {}
    for item in items:
        cat = item.get("event_category", "other")
        by_cat.setdefault(cat, []).append(item)

    for cat in CATEGORY_ORDER:
        cat_items = by_cat.get(cat, [])
        if not cat_items:
            continue
        lines.append(f"=== {CATEGORY_LABELS.get(cat, cat)} ===")
        for item in cat_items:
            ticker = item.get("ticker", "?")
            headline = item.get("headline", "No headline")[:80]
            src = item.get("source_type", "?")
            lines.append(f"  [{ticker}] {headline}")
            lines.append(f"    Source: {src}")
            url = item.get("source_url", "")
            if url:
                lines.append(f"    {url}")
        lines.append("")

    lines.append("---")
    lines.append("Source: Herald (company IR + wire services)")
    return "\n".join(lines)


def build_digest_html(items: list[dict], window: str) -> str:
    """Build HTML digest."""
    today_str = date.today().strftime("%b %d, %Y")
    window_label = {"morning": "Pre-Market", "midday": "Midday", "evening": "End of Day"}.get(window, window)

    if not items:
        return f"""<html><body>
<h2>Biotech News Digest — {window_label} {today_str}</h2>
<p>No major updates for followed tickers.</p>
<p style="color:#888;font-size:11px;">Source: Herald (company IR + wire services)</p>
</body></html>"""

    rows_html = []
    current_cat = None

    for item in items:
        cat = item.get("event_category", "other")
        if cat != current_cat:
            current_cat = cat
            label = CATEGORY_LABELS.get(cat, cat)
            rows_html.append(
                f'<tr><td colspan="3" style="background:#f0f0f0;padding:8px;'
                f'font-weight:bold;border-top:2px solid #ccc;">{label}</td></tr>'
            )

        ticker = item.get("ticker", "?")
        headline = item.get("headline", "No headline")[:100]
        src = item.get("source_type", "?")
        url = item.get("source_url", "")
        link = f'<a href="{url}" style="color:#0066cc;">{headline}</a>' if url else headline
        subtype = item.get("event_subtype", "")

        rows_html.append(
            f"<tr>"
            f'<td style="padding:4px 8px;font-weight:bold;vertical-align:top;">{ticker}</td>'
            f'<td style="padding:4px 8px;">{link}'
            f'<br><span style="color:#888;font-size:11px;">{src}'
            f'{" | " + subtype if subtype else ""}</span></td>'
            f"</tr>"
        )

    return f"""<html><body>
<h2 style="margin:0 0 8px 0;">Biotech News Digest — {window_label} {today_str}</h2>
<p style="margin:0 0 12px 0;color:#666;">{len(items)} items from followed tickers</p>
<table style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;width:100%;">
{''.join(rows_html)}
</table>
<p style="color:#888;font-size:11px;margin-top:16px;">
  Source: Herald (company IR + wire services) | Managed by Herald Digest
</p>
</body></html>"""


def send_email(subject: str, body_html: str, body_text: str) -> bool:
    """Send digest email via Gmail SMTP."""
    if not SMTP_USER or not SMTP_PASSWORD or not ALERT_RECIPIENT:
        print("ERROR: SMTP credentials not configured in .env")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Herald Digest <{SMTP_USER}>"
    msg["To"] = ALERT_RECIPIENT
    msg["Subject"] = subject

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, ALERT_RECIPIENT, msg.as_string())
        return True
    except Exception as e:
        print(f"ERROR: Email send failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Build and send biotech news digest")
    parser.add_argument("--window", required=True, choices=["morning", "midday", "evening"])
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't email")
    parser.add_argument("--max-items", type=int, default=MAX_ITEMS)
    args = parser.parse_args()

    max_items = args.max_items

    universe = load_universe()
    print(f"Universe: {len(universe)} tickers")

    # Load classified first, fall back to raw
    releases = load_classified_releases()
    source = "classified"
    if not releases:
        releases = load_raw_releases()
        source = "raw"
    print(f"Loaded {len(releases)} {source} releases")

    # Filter to window
    windowed = filter_window(releases, args.window)
    print(f"In window ({args.window}): {len(windowed)}")

    # Dedupe, filter to universe, limit
    items = dedupe_and_limit(windowed, universe)
    items = items[:max_items]
    print(f"Final digest items: {len(items)}")

    # Build content
    body_text = build_digest_text(items, args.window)
    body_html = build_digest_html(items, args.window)

    today_str = date.today().strftime("%b %d")
    window_label = {"morning": "Pre-Market", "midday": "Midday", "evening": "EOD"}.get(args.window, args.window)
    subject = f"Biotech Digest: {window_label} {today_str} ({len(items)} items)"

    # Save artifacts
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    (OUTPUT_DIR / f"biotech_news_digest_{ts}.html").write_text(body_html)
    (OUTPUT_DIR / f"biotech_news_digest_{ts}.txt").write_text(body_text)
    (OUTPUT_DIR / f"biotech_news_digest_{ts}.json").write_text(
        json.dumps({"window": args.window, "n_items": len(items), "items": items}, indent=2, default=str)
    )

    if args.dry_run:
        print("\nDry run — not sending email")
        print(f"\n{body_text}")
        return

    # Send
    ok = send_email(subject, body_html, body_text)
    if ok:
        print(f"Sent: {subject} -> {ALERT_RECIPIENT}")
    else:
        print("FAILED to send digest email")
        sys.exit(1)


if __name__ == "__main__":
    main()
