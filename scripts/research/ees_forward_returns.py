#!/usr/bin/env python3
"""PIT-safe forward-return joiner for EES validation.

For each (snapshot_date, ticker), compute T+1, T+3, T+5 close-to-close
returns using `production_data/price_history.csv`, plus the same-window
XBI return and resulting excess (ticker - xbi).

Anchor convention: the close on `snap_date` itself is T+0 (the price the
model "saw" at end-of-day). If `snap_date` is not a trading day in the
price-history calendar (e.g., 2026-04-25 Saturday research runs), roll
back to the most recent prior trading day. Forward horizons are counted
in TRADING days using the price-history's own date set, not calendar days.

PIT-safe: only price data with `date > anchor_date` is used for forward
returns. No leakage. If a horizon extends past the latest available date,
the row is emitted with `actual_return_Nd=None` and `forward_complete=False`.

Output: `data/snapshots/_forward_returns_panel.csv`, one row per
(snap_date, ticker), with columns:
  snap_date, ticker, anchor_date, anchor_close,
  actual_return_1d, actual_return_3d, actual_return_5d,
  actual_abs_move_5d, xbi_return_5d, excess_return_5d,
  forward_complete

Usage:
    python -m scripts.research.ees_forward_returns
    python -m scripts.research.ees_forward_returns --snapshot 2026-04-30
    python -m scripts.research.ees_forward_returns --since 2026-04-14
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
DEFAULT_SNAP_ROOT = PROJECT_ROOT / "data" / "snapshots"
DEFAULT_OUTPUT = DEFAULT_SNAP_ROOT / "_forward_returns_panel.csv"

XBI_TICKER = "XBI"
HORIZONS = (1, 3, 5)

# EES outputs first appeared on 2026-04-14 in production rankings.csv;
# 2026-04-13 has Universe A=0. Earlier snapshots have no EES to validate.
EES_VALID_FROM = "2026-04-14"


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "null", "none"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load_price_history(
    price_csv: Path,
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, List[str]]]:
    """Load long-format price_history.csv into (prices_by_ticker, sorted_dates).

    `prices_by_ticker[ticker][date_str] = close`
    `sorted_dates[ticker] = [date_str, ...]` ascending
    """
    prices: Dict[str, Dict[str, float]] = defaultdict(dict)
    with price_csv.open(newline="") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = _safe_float(row.get("close"))
            if t and d and c is not None and c > 0:
                prices[t][d] = c
    sorted_dates = {t: sorted(d.keys()) for t, d in prices.items()}
    return dict(prices), sorted_dates


def _resolve_anchor_idx(sorted_dates: List[str], snap_date: str) -> Optional[int]:
    """Return index of the most recent trading day <= snap_date.

    Returns None if snap_date predates the entire calendar.
    """
    if not sorted_dates:
        return None
    if snap_date in sorted_dates:
        return sorted_dates.index(snap_date)
    # Fall back to most recent prior date
    lo, hi = 0, len(sorted_dates) - 1
    if sorted_dates[0] > snap_date:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if sorted_dates[mid] <= snap_date:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _forward_return(
    ticker_prices: Dict[str, float],
    sorted_dates: List[str],
    anchor_idx: int,
    horizon: int,
) -> Optional[float]:
    end_idx = anchor_idx + horizon
    if end_idx >= len(sorted_dates):
        return None
    p0 = ticker_prices.get(sorted_dates[anchor_idx])
    p1 = ticker_prices.get(sorted_dates[end_idx])
    if p0 and p1 and p0 > 0:
        return (p1 / p0) - 1.0
    return None


def compute_row(
    ticker: str,
    snap_date: str,
    prices: Dict[str, Dict[str, float]],
    dates_by_ticker: Dict[str, List[str]],
    xbi_dates: List[str],
    xbi_prices: Dict[str, float],
) -> Optional[dict]:
    """Compute forward-return row for one (ticker, snap_date). Returns None
    if the ticker has no price history at all."""
    t_dates = dates_by_ticker.get(ticker)
    t_prices = prices.get(ticker)
    if not t_dates or not t_prices:
        return None

    anchor_idx = _resolve_anchor_idx(t_dates, snap_date)
    if anchor_idx is None:
        return None
    anchor_date = t_dates[anchor_idx]
    anchor_close = t_prices.get(anchor_date)

    rets = {}
    for h in HORIZONS:
        rets[h] = _forward_return(t_prices, t_dates, anchor_idx, h)

    # XBI uses its own anchor index (same snap_date logic)
    xbi_anchor_idx = _resolve_anchor_idx(xbi_dates, snap_date)
    xbi_5d = _forward_return(xbi_prices, xbi_dates, xbi_anchor_idx, 5) if xbi_anchor_idx is not None else None

    abs_5d = abs(rets[5]) if rets[5] is not None else None
    excess_5d = (rets[5] - xbi_5d) if (rets[5] is not None and xbi_5d is not None) else None

    forward_complete = all(rets[h] is not None for h in HORIZONS) and xbi_5d is not None

    return {
        "snap_date": snap_date,
        "ticker": ticker,
        "anchor_date": anchor_date,
        "anchor_close": round(anchor_close, 6) if anchor_close else None,
        "actual_return_1d": round(rets[1], 6) if rets[1] is not None else None,
        "actual_return_3d": round(rets[3], 6) if rets[3] is not None else None,
        "actual_return_5d": round(rets[5], 6) if rets[5] is not None else None,
        "actual_abs_move_5d": round(abs_5d, 6) if abs_5d is not None else None,
        "xbi_return_5d": round(xbi_5d, 6) if xbi_5d is not None else None,
        "excess_return_5d": round(excess_5d, 6) if excess_5d is not None else None,
        "forward_complete": "true" if forward_complete else "false",
    }


def _discover_eligible_snapshots(snap_root: Path, since: str = EES_VALID_FROM) -> List[str]:
    out = []
    for d in sorted(snap_root.iterdir()):
        if not d.is_dir():
            continue
        n = d.name
        if len(n) != 10 or n[4] != "-" or n[7] != "-":
            continue
        try:
            date.fromisoformat(n)
        except ValueError:
            continue
        if (snap_root / n / "rankings.csv").exists() and n >= since:
            out.append(n)
    return out


def _load_snapshot_tickers(snap_root: Path, snap_date: str) -> List[str]:
    p = snap_root / snap_date / "rankings.csv"
    if not p.exists():
        return []
    with p.open(newline="") as f:
        return [r["ticker"] for r in csv.DictReader(f) if r.get("ticker")]


def build_panel(
    snap_root: Path = DEFAULT_SNAP_ROOT,
    price_csv: Path = DEFAULT_PRICE_CSV,
    snapshots: Optional[List[str]] = None,
    since: str = EES_VALID_FROM,
) -> List[dict]:
    logger.info(f"Loading prices from {price_csv}")
    prices, dates_by_ticker = load_price_history(price_csv)
    if XBI_TICKER not in prices:
        raise RuntimeError(f"{XBI_TICKER} missing from price history; cannot compute baseline.")
    xbi_prices = prices[XBI_TICKER]
    xbi_dates = dates_by_ticker[XBI_TICKER]
    logger.info(f"Loaded {len(prices)} tickers; XBI has " f"{len(xbi_dates)} dates ({xbi_dates[0]} → {xbi_dates[-1]})")

    if snapshots is None:
        snapshots = _discover_eligible_snapshots(snap_root, since=since)
    logger.info(f"Joining {len(snapshots)} snapshot(s): {snapshots[0]} → {snapshots[-1]}")

    rows = []
    n_missing_ticker = 0
    n_incomplete = 0
    for snap in snapshots:
        tickers = _load_snapshot_tickers(snap_root, snap)
        for t in tickers:
            r = compute_row(t, snap, prices, dates_by_ticker, xbi_dates, xbi_prices)
            if r is None:
                n_missing_ticker += 1
                continue
            if r["forward_complete"] == "false":
                n_incomplete += 1
            rows.append(r)
    logger.info(
        f"Built {len(rows)} rows; {n_incomplete} incomplete (insufficient forward window); "
        f"{n_missing_ticker} dropped (no price history)"
    )
    return rows


def write_panel(rows: List[dict], output: Path = DEFAULT_OUTPUT) -> None:
    if not rows:
        logger.warning("No rows to write.")
        return
    cols = list(rows[0].keys())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    logger.info(f"Wrote {len(rows)} rows to {output}")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--price-csv",
        type=Path,
        default=DEFAULT_PRICE_CSV,
        help=f"Long-format price history (default {DEFAULT_PRICE_CSV.name})",
    )
    p.add_argument(
        "--snap-root",
        type=Path,
        default=DEFAULT_SNAP_ROOT,
        help="Snapshot root directory",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output panel CSV path",
    )
    p.add_argument(
        "--snapshot",
        action="append",
        help="Specific snapshot date(s); default = all eligible",
    )
    p.add_argument(
        "--since",
        default=EES_VALID_FROM,
        help=f"Earliest snapshot to join (default {EES_VALID_FROM}, " f"first date with EES outputs)",
    )
    args = p.parse_args(argv)

    rows = build_panel(
        snap_root=args.snap_root,
        price_csv=args.price_csv,
        snapshots=args.snapshot,
        since=args.since,
    )
    write_panel(rows, output=args.output)

    # Quick summary
    by_complete = defaultdict(int)
    for r in rows:
        by_complete[r["forward_complete"]] += 1
    logger.info(f"  forward_complete: {dict(by_complete)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
