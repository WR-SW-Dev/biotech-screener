#!/usr/bin/env python3
"""Standalone price refresh — downloads per-ticker and streams to CSV to avoid OOM.

Previous approach (pd.concat of 338 DataFrames) consumed ~16 GB RSS and was
killed by the OOM killer before writing any output. This version writes each
ticker's rows to the CSV immediately after download, keeping peak memory to
one ticker at a time.

Usage:
    python tools/_price_refresh_standalone.py --as-of-date 2026-06-02
"""
import sys
import csv
import json
import logging
import time
import random
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--as-of-date", required=True)
parser.add_argument("--delay-sec", type=float, default=1.0)
parser.add_argument("--start-date", default="2020-01-01")
args = parser.parse_args()

import yfinance as yf
import pandas as pd

universe_path = REPO_ROOT / "production_data" / "universe.json"
price_csv = REPO_ROOT / "production_data" / "price_history.csv"

with open(universe_path) as f:
    universe = json.load(f)

if isinstance(universe, list):
    tickers = [e.get("ticker", e) if isinstance(e, dict) else str(e) for e in universe]
elif isinstance(universe, dict):
    tickers = universe.get("tickers", [])

tickers = [t for t in tickers if t and not t.startswith("_")]
if "XBI" not in tickers:
    tickers.append("XBI")

logger.info("Price refresh: %d tickers -> %s", len(tickers), price_csv)

FIELDNAMES = ["date", "ticker", "close", "open", "high", "low", "volume"]

# Load existing data to know max date per ticker (for incremental refresh)
max_dates: dict[str, str] = {}
existing_rows: list[dict] = []
if price_csv.exists():
    with open(price_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            existing_rows.append(row)
            t = (row.get("ticker") or "").strip().upper()
            d = (row.get("date") or "").strip()[:10]
            if t and d and (t not in max_dates or d > max_dates[t]):
                max_dates[t] = d
    logger.info("Loaded %d existing rows, %d tickers", len(existing_rows), len(max_dates))

through_date = args.as_of_date
end_yf = pd.Timestamp(through_date) + pd.Timedelta(days=1)
end_str = end_yf.strftime("%Y-%m-%d")

n_ok = 0
n_fail = 0
n_skip = 0
new_rows: list[dict] = []

for i, ticker in enumerate(tickers):
    # Determine start date for this ticker
    if ticker in max_dates and max_dates[ticker] >= through_date:
        n_skip += 1
        continue
    start_str = args.start_date
    if ticker in max_dates:
        next_day = (pd.Timestamp(max_dates[ticker]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        start_str = next_day

    if i > 0:
        jitter = args.delay_sec * (0.5 + random.random())
        time.sleep(jitter)

    try:
        df = yf.download(ticker, start=start_str, end=end_str, progress=False, auto_adjust=False)
        if df is None or df.empty:
            logger.warning("  %s: empty response", ticker)
            n_fail += 1
            continue

        # Flatten MultiIndex columns if present (yfinance >= 0.2.x)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        count = 0
        for dt, row in df.iterrows():
            close = row.get("Close") or row.get("Adj Close")
            if close is None or (hasattr(close, '__float__') and close != close):
                continue
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            if close_f != close_f:  # NaN check
                continue

            def _f(v):
                try:
                    fv = float(v)
                    return "" if fv != fv else str(fv)
                except (TypeError, ValueError):
                    return ""

            def _vi(v):
                try:
                    return str(int(float(v)))
                except (TypeError, ValueError):
                    return ""

            new_rows.append({
                "date": dt.strftime("%Y-%m-%d"),
                "ticker": ticker,
                "close": str(close_f),
                "open": _f(row.get("Open")),
                "high": _f(row.get("High")),
                "low": _f(row.get("Low")),
                "volume": _vi(row.get("Volume")),
            })
            count += 1

        # Free DataFrame memory immediately
        del df
        n_ok += 1
        if (i + 1) % 50 == 0:
            logger.info("  Progress: %d/%d tickers done (%d new rows so far)", i + 1, len(tickers), len(new_rows))

    except Exception as e:
        logger.error("  %s: %s", ticker, str(e)[:120])
        n_fail += 1

logger.info("Download complete: %d ok, %d fail, %d skip, %d new rows", n_ok, n_fail, n_skip, len(new_rows))

# Merge and deduplicate
all_rows = existing_rows + new_rows
seen: dict[tuple, int] = {}
for idx, row in enumerate(all_rows):
    key = ((row.get("ticker") or "").upper(), (row.get("date") or "")[:10])
    seen[key] = idx
deduped = [all_rows[i] for i in sorted(seen.values())]
logger.info("Writing %d rows to %s", len(deduped), price_csv)

import tempfile, os
price_csv.parent.mkdir(parents=True, exist_ok=True)
fd, tmp_path = tempfile.mkstemp(suffix=".csv", dir=price_csv.parent)
try:
    with open(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in deduped:
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})
    Path(tmp_path).replace(price_csv)
    logger.info("Done. price_history.csv written (%d rows).", len(deduped))
except BaseException:
    Path(tmp_path).unlink(missing_ok=True)
    raise
