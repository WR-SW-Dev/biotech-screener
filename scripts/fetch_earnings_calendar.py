#!/usr/bin/env python3
"""Stage 1: Fetch upcoming earnings dates from yfinance per-ticker calendar.

Uses Ticker.calendar for each symbol in the universe, which returns the next
earnings date. The global Calendars API is market-cap-weighted and misses
small/mid-cap biotech names.

Usage:
    python scripts/fetch_earnings_calendar.py \
        --symbols-file production_data/universe.json \
        --start 2026-04-02 --end 2026-04-23 \
        --output artifacts/earnings_sync/earnings_raw_2026-04-02.json
"""

import argparse
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import yfinance as yf


def load_symbols(path: Path) -> list[str]:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            return [d["ticker"].upper() for d in data if "ticker" in d]
        return [s.upper() for s in data if isinstance(s, str)]
    if isinstance(data, dict) and "tickers" in data:
        return [s.upper() for s in data["tickers"]]
    raise ValueError(f"Cannot parse symbols from {path}")


def fetch_earnings(symbols: list[str], start: date, end: date) -> tuple[list[dict], list[dict]]:
    """Fetch next earnings date for each symbol via Ticker.calendar.

    Returns (rows, errors).
    """
    rows = []
    errors = []

    for i, symbol in enumerate(symbols):
        if i > 0 and i % 50 == 0:
            print(f"  ... {i}/{len(symbols)} tickers checked, {len(rows)} with earnings in window")
            time.sleep(0.5)  # gentle rate limit

        try:
            t = yf.Ticker(symbol)
            cal = t.calendar
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})
            continue

        if not cal or "Earnings Date" not in cal:
            continue

        earnings_dates = cal["Earnings Date"]
        if not isinstance(earnings_dates, list):
            earnings_dates = [earnings_dates]

        for ed in earnings_dates:
            if hasattr(ed, "isoformat"):
                ed_date = ed if isinstance(ed, date) else ed.date() if hasattr(ed, "date") else ed
            else:
                try:
                    ed_date = date.fromisoformat(str(ed)[:10])
                except ValueError:
                    continue

            if ed_date < start or ed_date > end:
                continue

            company = symbol
            try:
                info = t.info
                company = info.get("shortName", info.get("longName", symbol))
            except Exception:
                pass

            rows.append(
                {
                    "symbol": symbol,
                    "company": company,
                    "earnings_date": ed_date.isoformat(),
                    "earnings_time_hint": "unknown",
                    "eps_estimate": cal.get("Earnings Average"),
                    "revenue_estimate": cal.get("Revenue Average"),
                }
            )

    return rows, errors


def main():
    parser = argparse.ArgumentParser(description="Fetch upcoming earnings calendar")
    parser.add_argument("--symbols-file", required=True, type=Path)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    symbols = load_symbols(args.symbols_file)
    print(f"Loaded {len(symbols)} symbols from {args.symbols_file}")
    print(f"Fetching earnings in [{args.start}, {args.end}]...")

    rows, errors = fetch_earnings(symbols, args.start, args.end)
    print(f"Found {len(rows)} earnings events, {len(errors)} fetch errors")

    result = {
        "schema": "earnings_raw.v1",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "symbols_checked": len(symbols),
        "rows": rows,
        "errors": errors,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
