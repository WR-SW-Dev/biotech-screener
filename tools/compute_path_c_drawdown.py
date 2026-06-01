#!/usr/bin/env python3
"""
Compute Path C drawdown vs XBI for daily governance monitoring.

Metric: portfolio cumulative return since 2026-05-29 baseline minus XBI cumulative return.
Hard exit: FAIL_HARD_EXIT if drawdown_vs_xbi_pp <= -2.00.
"""

import csv
from pathlib import Path
from typing import TypedDict


class DrawdownResult(TypedDict):
    """Result from drawdown computation."""

    pp: float | None
    status: str
    baseline_date: str
    latest_date: str | None


def compute_drawdown_vs_xbi(
    portfolio_holdings: dict[str, float],
    snapshot_date: str,
    baseline_date: str = "2026-05-29",
    price_history_path: Path | None = None,
) -> DrawdownResult:
    """
    Compute Path C drawdown vs XBI hard-exit metric.

    Args:
        portfolio_holdings: Dict of {ticker: target_weight_pct} for Phase 2 paper portfolio.
        snapshot_date: YYYY-MM-DD snapshot date.
        baseline_date: YYYY-MM-DD baseline date (default: 2026-05-29).
        price_history_path: Path to price_history_split_adj.csv (default: production_data/).

    Returns:
        DrawdownResult with:
        - pp: float (drawdown in percentage points) or None if unavailable
        - status: "PASS", "FAIL_HARD_EXIT", or "DATA_UNAVAILABLE"
        - baseline_date: str
        - latest_date: str (latest available price date) or None
    """
    if price_history_path is None:
        price_history_path = Path("production_data/price_history_split_adj.csv")

    if not price_history_path.exists():
        return DrawdownResult(
            pp=None,
            status="DATA_UNAVAILABLE",
            baseline_date=baseline_date,
            latest_date=None,
        )

    # Load price history
    prices = {}
    latest_date = None
    try:
        with open(price_history_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = row.get("ticker", "").strip()
                date = row.get("date", "").strip()
                close = row.get("close", "").strip()

                if not ticker or not date or not close:
                    continue

                latest_date = date  # Last row in file

                if ticker not in prices:
                    prices[ticker] = {}
                try:
                    prices[ticker][date] = float(close)
                except ValueError:
                    continue
    except OSError:
        return DrawdownResult(
            pp=None,
            status="DATA_UNAVAILABLE",
            baseline_date=baseline_date,
            latest_date=None,
        )

    # Check data availability
    if not latest_date:
        return DrawdownResult(
            pp=None,
            status="DATA_UNAVAILABLE",
            baseline_date=baseline_date,
            latest_date=None,
        )

    # Verify baseline and latest prices exist for all holdings
    missing_tickers = []
    for ticker in portfolio_holdings.keys():
        if ticker not in prices:
            missing_tickers.append(ticker)
        elif baseline_date not in prices[ticker]:
            missing_tickers.append(f"{ticker}@{baseline_date}")
        elif latest_date not in prices[ticker]:
            missing_tickers.append(f"{ticker}@{latest_date}")

    if missing_tickers:
        return DrawdownResult(
            pp=None,
            status="DATA_UNAVAILABLE",
            baseline_date=baseline_date,
            latest_date=latest_date,
        )

    # Compute portfolio and XBI returns
    portfolio_baseline = 0.0
    portfolio_latest = 0.0
    for ticker, weight in portfolio_holdings.items():
        w = weight / 100.0  # Convert percentage to decimal
        baseline_price = prices[ticker][baseline_date]
        latest_price = prices[ticker][latest_date]
        ticker_return = (latest_price - baseline_price) / baseline_price
        portfolio_baseline += w * 0.0  # Baseline is always 0
        portfolio_latest += w * ticker_return

    # XBI returns
    if "XBI" not in prices:
        return DrawdownResult(
            pp=None,
            status="DATA_UNAVAILABLE",
            baseline_date=baseline_date,
            latest_date=latest_date,
        )

    xbi_baseline_price = prices["XBI"][baseline_date]
    xbi_latest_price = prices["XBI"][latest_date]
    xbi_return = (xbi_latest_price - xbi_baseline_price) / xbi_baseline_price

    # Drawdown = portfolio return - XBI return (in percentage points)
    drawdown_pp = (portfolio_latest - xbi_return) * 100.0

    # Determine status
    if drawdown_pp <= -2.00:
        status = "FAIL_HARD_EXIT"
    else:
        status = "PASS"

    return DrawdownResult(
        pp=round(drawdown_pp, 2),
        status=status,
        baseline_date=baseline_date,
        latest_date=latest_date,
    )
