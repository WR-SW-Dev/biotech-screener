#!/usr/bin/env python3
"""
IEX Cloud price downloader — fallback for yfinance rate-limiting.

Setup:
  1. Sign up at https://iexcloud.io (free tier)
  2. Set IEX_CLOUD_API_KEY environment variable
  3. Run: python3 scripts/iex_cloud_price_download.py AAPL TSLA GOOG

Usage:
  - Single ticker: python3 scripts/iex_cloud_price_download.py AAPL
  - Multiple: python3 scripts/iex_cloud_price_download.py AAPL TSLA GOOG
  - From file: python3 scripts/iex_cloud_price_download.py < tickers.txt
  - With date range: --start-date 2026-05-20 --end-date 2026-05-27

Note: Free tier is 100 messages/month. For production, upgrade to paid plan.
"""

import os
import sys
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional, Dict

IEX_BASE_URL = "https://cloud.iexapis.com/stable"
IEX_API_KEY = os.environ.get("IEX_CLOUD_API_KEY")

def get_historical_bars(
    symbols: List[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    range_type: str = "3m"
) -> pd.DataFrame:
    """
    Fetch historical OHLCV bars from IEX Cloud.

    Args:
        symbols: List of ticker symbols
        start_date: Start date (YYYY-MM-DD), optional
        end_date: End date (YYYY-MM-DD), optional
        range_type: IEX range: '3m', '6m', '1y', '5y' etc.

    Returns:
        DataFrame with OHLCV data, indexed by ticker and date
    """

    if not IEX_API_KEY:
        raise ValueError("IEX_CLOUD_API_KEY not set. Sign up at https://iexcloud.io")

    all_data = []

    for symbol in symbols:
        try:
            # IEX endpoint: /data/CORE/HISTORICAL_PRICES/{symbol}
            url = f"{IEX_BASE_URL}/data/core/historical_prices/{symbol}"
            params = {
                "token": IEX_API_KEY,
                "chartRange": range_type,
            }

            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 401:
                raise ValueError("Invalid IEX_CLOUD_API_KEY or unauthorized")
            elif response.status_code == 429:
                raise RuntimeError("IEX Cloud rate-limited (free tier exhausted)")
            elif response.status_code != 200:
                print(f"⚠ {symbol}: HTTP {response.status_code}, skipping", file=sys.stderr)
                continue

            bars = response.json()

            for bar in bars:
                all_data.append({
                    'symbol': symbol,
                    'date': bar.get('date'),
                    'open': bar.get('open'),
                    'high': bar.get('high'),
                    'low': bar.get('low'),
                    'close': bar.get('close'),
                    'volume': bar.get('volume'),
                })

            print(f"✓ {symbol}: {len(bars)} bars", file=sys.stderr)

        except requests.exceptions.Timeout:
            print(f"✗ {symbol}: Timeout", file=sys.stderr)
            continue
        except Exception as e:
            print(f"✗ {symbol}: {e}", file=sys.stderr)
            continue

    df = pd.DataFrame(all_data)

    if df.empty:
        raise RuntimeError("No data retrieved from IEX Cloud")

    # Parse dates
    df['date'] = pd.to_datetime(df['date'])

    # Filter by date range if specified
    if start_date:
        df = df[df['date'] >= start_date]
    if end_date:
        df = df[df['date'] <= end_date]

    # Convert to float
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype(int)

    return df

def main():
    """CLI entrypoint."""

    import argparse

    parser = argparse.ArgumentParser(
        description="Download historical price data from IEX Cloud"
    )
    parser.add_argument("symbols", nargs="*", help="Ticker symbols (or read from stdin)")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--range", default="3m", help="IEX range: 3m, 6m, 1y, 5y")
    parser.add_argument("--csv", action="store_true", help="Output as CSV")

    args = parser.parse_args()

    symbols = args.symbols
    if not symbols:
        # Read from stdin
        symbols = [line.strip().upper() for line in sys.stdin if line.strip()]

    symbols = [s.upper() for s in symbols]

    if not symbols:
        parser.print_help()
        sys.exit(1)

    try:
        df = get_historical_bars(
            symbols,
            start_date=args.start_date,
            end_date=args.end_date,
            range_type=args.range
        )

        if args.csv:
            print(df.to_csv(index=False))
        else:
            print(df.to_string())

        print(f"\n{len(df)} rows, {df['symbol'].nunique()} symbols", file=sys.stderr)

    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
