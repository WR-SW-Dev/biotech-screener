#!/usr/bin/env python3
"""Earnings email alerts: pre-earnings reminders and post-earnings results.

Two modes:
  --mode reminder   Send a digest of today's/tomorrow's earnings (run morning)
  --mode results    Check for newly reported earnings and send surprise summary

Usage:
    # Morning reminder: who reports today/tomorrow
    python scripts/earnings_email_alerts.py --mode reminder \
        --raw-file artifacts/earnings_sync/earnings_raw_2026-04-02.json

    # After-hours results check
    python scripts/earnings_email_alerts.py --mode results \
        --raw-file artifacts/earnings_sync/earnings_raw_2026-04-02.json
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
ALERT_RECIPIENT = os.environ.get("ALERT_RECIPIENT", "")


def send_email(subject: str, body_html: str, body_text: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"] = f"Bellringer <{SMTP_USER}>"
    msg["To"] = ALERT_RECIPIENT
    msg["Subject"] = subject

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, ALERT_RECIPIENT, msg.as_string())

    print(f"Sent: {subject} -> {ALERT_RECIPIENT}")


def load_events(raw_path: Path) -> list[dict]:
    data = json.loads(raw_path.read_text())
    return data.get("rows", [])


# --- Reminder mode ---


def build_reminder(events: list[dict], target_dates: list[date]) -> tuple[str, str, str]:
    """Build reminder email for earnings on target_dates."""
    target_strs = {d.isoformat() for d in target_dates}
    upcoming = [e for e in events if e["earnings_date"] in target_strs]
    upcoming.sort(key=lambda e: (e["earnings_date"], e["symbol"]))

    if not upcoming:
        return "", "", ""

    date_label = " & ".join(d.strftime("%b %d") for d in sorted(target_dates))
    subject = f"Bellringer: {len(upcoming)} biotech earnings {date_label}"

    # Group by date
    by_date: dict[str, list[dict]] = {}
    for e in upcoming:
        by_date.setdefault(e["earnings_date"], []).append(e)

    # Plain text
    lines = [f"Biotech Earnings — {date_label}", ""]
    for dt in sorted(by_date):
        lines.append(f"=== {dt} ({len(by_date[dt])} names) ===")
        for e in by_date[dt]:
            eps = f"  EPS est: {e['eps_estimate']:.2f}" if e.get("eps_estimate") else ""
            lines.append(f"  {e['symbol']:6s}  {e['company'][:35]}{eps}")
        lines.append("")
    body_text = "\n".join(lines)

    # HTML
    html_rows = []
    for dt in sorted(by_date):
        html_rows.append(
            '<tr><td colspan="4" style="background:#f0f0f0;padding:8px;">'
            f"<strong>{dt}</strong> ({len(by_date[dt])} names)</td></tr>"
        )
        for e in by_date[dt]:
            eps = f"{e['eps_estimate']:.2f}" if e.get("eps_estimate") else "—"
            rev = f"${e['revenue_estimate']/1e6:.0f}M" if e.get("revenue_estimate") else "—"
            html_rows.append(
                f'<tr><td style="padding:4px 8px;"><strong>{e["symbol"]}</strong></td>'
                f'<td style="padding:4px 8px;">{e["company"][:40]}</td>'
                f'<td style="padding:4px 8px;text-align:right;">{eps}</td>'
                f'<td style="padding:4px 8px;text-align:right;">{rev}</td></tr>'
            )

    body_html = """<html><body>
<h2 style="margin:0 0 12px 0;">Biotech Earnings — {date_label}</h2>
<table style="border-collapse:collapse;font-family:monospace;font-size:13px;">
<tr style="border-bottom:2px solid #333;">
  <th style="padding:4px 8px;text-align:left;">Ticker</th>
  <th style="padding:4px 8px;text-align:left;">Company</th>
  <th style="padding:4px 8px;text-align:right;">EPS Est</th>
  <th style="padding:4px 8px;text-align:right;">Rev Est</th>
</tr>
{''.join(html_rows)}
</table>
<p style="color:#888;font-size:11px;margin-top:16px;">
  Managed by Bellringer | Source: yfinance
</p>
</body></html>"""

    return subject, body_html, body_text


def run_reminder(events: list[dict]):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    # Skip weekends for tomorrow
    if tomorrow.weekday() >= 5:
        target_dates = [today]
    else:
        target_dates = [today, tomorrow]

    subject, body_html, body_text = build_reminder(events, target_dates)
    if not subject:
        print(f"No earnings on {[d.isoformat() for d in target_dates]} — no email sent")
        return
    send_email(subject, body_html, body_text)


# --- Results mode ---


def fetch_results(events: list[dict]) -> list[dict]:
    """Check which of today's earnings have reported results."""
    today_str = date.today().isoformat()
    todays = [e for e in events if e["earnings_date"] == today_str]

    results = []
    for e in todays:
        try:
            t = yf.Ticker(e["symbol"])
            cal = t.calendar
            if not cal:
                continue

            info = t.info
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

            # Try to get earnings history for surprise
            try:
                eh = t.earnings_history
                if eh is not None and not eh.empty:
                    latest = eh.iloc[-1]
                    eps_actual = latest.get("epsActual")
                    eps_estimate = latest.get("epsEstimate")
                    surprise_pct = latest.get("surprisePercent")
                    if eps_actual is not None:
                        results.append(
                            {
                                **e,
                                "eps_actual": float(eps_actual) if eps_actual else None,
                                "eps_estimate_reported": float(eps_estimate) if eps_estimate else e.get("eps_estimate"),
                                "surprise_pct": float(surprise_pct) if surprise_pct else None,
                                "price": current_price,
                                "prev_close": prev_close,
                                "price_change_pct": (
                                    ((current_price - prev_close) / prev_close * 100)
                                    if current_price and prev_close
                                    else None
                                ),
                            }
                        )
                        continue
            except Exception:
                pass

            # Fallback: if we have price move, still report it
            if current_price and prev_close:
                pct = (current_price - prev_close) / prev_close * 100
                if abs(pct) > 2:  # Only report meaningful moves
                    results.append(
                        {
                            **e,
                            "eps_actual": None,
                            "eps_estimate_reported": e.get("eps_estimate"),
                            "surprise_pct": None,
                            "price": current_price,
                            "prev_close": prev_close,
                            "price_change_pct": pct,
                        }
                    )

        except Exception as ex:
            print(f"  {e['symbol']}: error fetching results — {ex}")

    return results


def build_results_email(results: list[dict]) -> tuple[str, str, str]:
    if not results:
        return "", "", ""

    results.sort(key=lambda r: abs(r.get("price_change_pct") or 0), reverse=True)

    subject = f"Bellringer: {len(results)} biotech earnings results — {date.today().strftime('%b %d')}"

    lines = [f"Biotech Earnings Results — {date.today()}", ""]
    for r in results:
        eps_str = f"EPS: {r['eps_actual']:.2f}" if r.get("eps_actual") is not None else "EPS: pending"
        surp = f" ({r['surprise_pct']:+.1f}%)" if r.get("surprise_pct") is not None else ""
        pchg = f"  Price: {r['price_change_pct']:+.1f}%" if r.get("price_change_pct") is not None else ""
        lines.append(f"  {r['symbol']:6s}  {eps_str}{surp}{pchg}")
    body_text = "\n".join(lines)

    html_rows = []
    for r in results:
        eps = f"{r['eps_actual']:.2f}" if r.get("eps_actual") is not None else "—"
        est = f"{r['eps_estimate_reported']:.2f}" if r.get("eps_estimate_reported") else "—"
        surp = f"{r['surprise_pct']:+.1f}%" if r.get("surprise_pct") is not None else "—"
        pchg = r.get("price_change_pct")
        if pchg is not None:
            color = "#0a7c00" if pchg >= 0 else "#c00"
            pchg_str = f'<span style="color:{color};">{pchg:+.1f}%</span>'
        else:
            pchg_str = "—"

        html_rows.append(
            "<tr>"
            f'<td style="padding:4px 8px;"><strong>{r["symbol"]}</strong></td>'
            f'<td style="padding:4px 8px;">{r["company"][:35]}</td>'
            f'<td style="padding:4px 8px;text-align:right;">{eps}</td>'
            f'<td style="padding:4px 8px;text-align:right;">{est}</td>'
            f'<td style="padding:4px 8px;text-align:right;">{surp}</td>'
            f'<td style="padding:4px 8px;text-align:right;">{pchg_str}</td>'
            "</tr>"
        )

    body_html = """<html><body>
<h2 style="margin:0 0 12px 0;">Biotech Earnings Results — {date.today().strftime('%b %d')}</h2>
<table style="border-collapse:collapse;font-family:monospace;font-size:13px;">
<tr style="border-bottom:2px solid #333;">
  <th style="padding:4px 8px;text-align:left;">Ticker</th>
  <th style="padding:4px 8px;text-align:left;">Company</th>
  <th style="padding:4px 8px;text-align:right;">EPS</th>
  <th style="padding:4px 8px;text-align:right;">Est</th>
  <th style="padding:4px 8px;text-align:right;">Surprise</th>
  <th style="padding:4px 8px;text-align:right;">Price</th>
</tr>
{''.join(html_rows)}
</table>
<p style="color:#888;font-size:11px;margin-top:16px;">
  Managed by Bellringer | Source: yfinance
</p>
</body></html>"""

    return subject, body_html, body_text


def run_results(events: list[dict]):
    today_str = date.today().isoformat()
    todays = [e for e in events if e["earnings_date"] == today_str]
    if not todays:
        print(f"No earnings scheduled for {today_str} — no results to check")
        return

    print(f"Checking results for {len(todays)} tickers reporting {today_str}...")
    results = fetch_results(events)
    if not results:
        print("No results available yet")
        return

    subject, body_html, body_text = build_results_email(results)
    send_email(subject, body_html, body_text)

    # Also save to artifact
    report_path = Path(f"artifacts/earnings_sync/results_{today_str}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Wrote {report_path}")


# --- Main ---


def main():
    parser = argparse.ArgumentParser(description="Earnings email alerts")
    parser.add_argument("--mode", required=True, choices=["reminder", "results"])
    parser.add_argument(
        "--raw-file", required=True, type=Path, help="Path to earnings_raw JSON from fetch_earnings_calendar.py"
    )
    args = parser.parse_args()

    if not SMTP_USER or not SMTP_PASSWORD or not ALERT_RECIPIENT:
        print("ERROR: Set SMTP_USER, SMTP_PASSWORD, ALERT_RECIPIENT in .env")
        sys.exit(1)

    events = load_events(args.raw_file)
    print(f"Loaded {len(events)} events from {args.raw_file}")

    if args.mode == "reminder":
        run_reminder(events)
    elif args.mode == "results":
        run_results(events)


if __name__ == "__main__":
    main()
