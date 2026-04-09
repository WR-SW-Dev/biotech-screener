#!/usr/bin/env python3
"""Build an intraday options-pressure panel from cached Massive minute aggs + trades.

Research-only panel for evaluating whether intraday options features carry a
cleaner, more stable crowding/event-pressure signal than daily volume and breadth.
NOT wired into the decision engine.

Output: CSV keyed by (ticker, date) with intraday activity, concentration,
and session-timing features derived from minute bars and trade tapes.

Usage:
    python3 scripts/research/build_intraday_options_pressure_panel.py \
        --minute-dir data/caches/massive_options/minute_aggs \
        --trades-dir data/caches/massive_options/trades \
        --universe production_data/universe.json \
        --out output/research/intraday_options_pressure_panel.csv
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("intraday_options_pressure")

# OCC option ticker regex: O:<UNDERLYING><YYMMDD><C|P><STRIKE*1000>
_OCC_RE = re.compile(r"^O:([A-Z]+)(\d{6})([CP])(\d{8})$")

# Market session boundaries (Eastern Time, minutes from midnight)
_MARKET_OPEN_MIN = 9 * 60 + 30  # 09:30
_MARKET_CLOSE_MIN = 16 * 60  # 16:00
_FIRST_HOUR_END = 10 * 60 + 30  # 10:30
_LAST_HOUR_START = 15 * 60  # 15:00


def _compute_utc_offset_seconds(trade_date: str) -> int:
    """Compute UTC→ET offset in seconds for a given trade date.

    Called once per date, then used for fast arithmetic on all rows.
    Returns offset such that: et_epoch = utc_epoch + offset
    (offset is negative: -18000 for EST, -14400 for EDT)
    """
    from zoneinfo import ZoneInfo

    # Use market open (14:30 UTC for EST, 13:30 for EDT) as reference
    d = datetime.strptime(trade_date, "%Y-%m-%d").replace(hour=12, tzinfo=ZoneInfo("UTC"))
    d_et = d.astimezone(ZoneInfo("America/New_York"))
    return int(d_et.utcoffset().total_seconds())


def _ns_to_et_minutes_fast(ns: int, utc_offset_s: int) -> int:
    """Convert nanosecond UTC timestamp to minutes-from-midnight ET using precomputed offset."""
    epoch_s = ns // 1_000_000_000
    et_s = epoch_s + utc_offset_s
    # seconds from midnight ET
    sod = et_s % 86400
    return sod // 60


def _load_universe(path: str) -> set[str]:
    """Load active tickers from universe.json."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return {d["ticker"] for d in data if isinstance(d, dict) and d.get("status") == "active"}
    return set(data.keys())


def _fast_extract(ticker: str):
    """Fast inline OCC parse without regex. Returns (underlying, cp_char, expiry_str) or None.

    OCC format: O:MRNA260320P00025000
    """
    if len(ticker) < 16 or ticker[0] != "O" or ticker[1] != ":":
        return None
    t = ticker[2:]
    # Find where digits start (end of underlying)
    i = 0
    while i < len(t) and t[i].isalpha():
        i += 1
    if i == 0 or i + 7 > len(t):
        return None
    underlying = t[:i]
    # Next 6 chars = YYMMDD, then C or P
    cp = t[i + 6]
    if cp not in ("C", "P"):
        return None
    expiry_str = t[i : i + 6]  # YYMMDD
    return underlying, cp, expiry_str


def _process_minute_file(gz_path: Path, universe: set[str], trade_date: str) -> dict[str, dict]:
    """Process minute aggs into per-underlying intraday features.

    Returns: {underlying: {feature_dict}} with minute-bar derived features.
    """
    stats: dict[str, dict] = {}
    utc_offset = _compute_utc_offset_seconds(trade_date)
    td = datetime.strptime(trade_date, "%Y-%m-%d").date()
    td_ordinal = td.toordinal()
    # Precompute 30-day cutoff as ordinal for fast comparison
    cutoff_ordinal = td_ordinal + 30

    with gzip.open(gz_path, "rt") as f:
        reader = csv.reader(f)
        header = next(reader)
        # Columns: ticker, volume, open, close, high, low, window_start, transactions
        idx_ticker = header.index("ticker")
        idx_vol = header.index("volume")
        idx_txn = header.index("transactions")
        idx_ws = header.index("window_start")

        for row in reader:
            ticker = row[idx_ticker]
            parsed = _fast_extract(ticker)
            if parsed is None:
                continue
            underlying, cp, expiry_str = parsed
            if underlying not in universe:
                continue

            vol = int(row[idx_vol] or 0)
            txn = int(row[idx_txn] or 0)
            ts_ns = int(row[idx_ws] or 0)

            if underlying not in stats:
                stats[underlying] = {
                    "total_volume": 0,
                    "total_transactions": 0,
                    "minute_bars": 0,
                    "first_hour_volume": 0,
                    "last_hour_volume": 0,
                    "session_volume": 0,
                    "minute_volumes": [],
                    "call_volume": 0,
                    "put_volume": 0,
                    "near_expiry_volume": 0,
                    "expiry_strs": set(),
                }

            s = stats[underlying]
            s["total_volume"] += vol
            s["total_transactions"] += txn
            s["minute_bars"] += 1

            # Session timing (fast arithmetic)
            et_min = _ns_to_et_minutes_fast(ts_ns, utc_offset)
            if _MARKET_OPEN_MIN <= et_min < _MARKET_CLOSE_MIN:
                s["session_volume"] += vol
                if et_min < _FIRST_HOUR_END:
                    s["first_hour_volume"] += vol
                if et_min >= _LAST_HOUR_START:
                    s["last_hour_volume"] += vol

            s["minute_volumes"].append(vol)

            if cp == "C":
                s["call_volume"] += vol
            else:
                s["put_volume"] += vol

            s["expiry_strs"].add(expiry_str)

            # Near-expiry: within 30 calendar days (fast ordinal check)
            try:
                y = 2000 + int(expiry_str[:2])
                mo = int(expiry_str[2:4])
                dy = int(expiry_str[4:6])
                from datetime import date as _d

                exp_ord = _d(y, mo, dy).toordinal()
                if exp_ord <= cutoff_ordinal:
                    s["near_expiry_volume"] += vol
            except (ValueError, OverflowError):
                pass

    # Compute derived features
    results = {}
    for underlying, s in stats.items():
        total = s["total_volume"]
        session = s["session_volume"]

        # First-hour and last-hour share (of session volume)
        first_hour_pct = s["first_hour_volume"] / session * 100.0 if session > 0 else 0.0
        last_hour_pct = s["last_hour_volume"] / session * 100.0 if session > 0 else 0.0

        # Minute-burst concentration: top-5-minute share of total volume
        mvols = sorted(s["minute_volumes"], reverse=True)
        top5_vol = sum(mvols[:5]) if mvols else 0
        burst_concentration = top5_vol / total if total > 0 else 0.0

        # Minute-level HHI
        if total > 0 and mvols:
            minute_hhi = sum((v / total) ** 2 for v in mvols if v > 0)
        else:
            minute_hhi = None

        # Put/call split
        pc_ratio = s["put_volume"] / s["call_volume"] if s["call_volume"] > 0 else None

        # Front-expiry share
        front_pct = s["near_expiry_volume"] / total * 100.0 if total > 0 else 0.0

        results[underlying] = {
            "m_total_volume": total,
            "m_total_transactions": s["total_transactions"],
            "m_minute_bars": s["minute_bars"],
            "m_first_hour_pct": round(first_hour_pct, 2),
            "m_last_hour_pct": round(last_hour_pct, 2),
            "m_burst_top5_pct": round(burst_concentration * 100, 2),
            "m_minute_hhi": round(minute_hhi, 6) if minute_hhi is not None else "",
            "m_call_volume": s["call_volume"],
            "m_put_volume": s["put_volume"],
            "m_put_call_ratio": round(pc_ratio, 4) if pc_ratio is not None else "",
            "m_front_expiry_pct": round(front_pct, 2),
            "m_expiry_count": len(s["expiry_strs"]),
        }

    return results


def _process_trades_file(gz_path: Path, universe: set[str], trade_date: str) -> dict[str, dict]:
    """Process trades tape into per-underlying trade features.

    Returns: {underlying: {feature_dict}} with trade-derived features.
    """
    stats: dict[str, dict] = {}
    utc_offset = _compute_utc_offset_seconds(trade_date)

    with gzip.open(gz_path, "rt") as f:
        reader = csv.reader(f)
        header = next(reader)
        # Columns: ticker, conditions, correction, exchange, price, sip_timestamp, size
        idx_ticker = header.index("ticker")
        idx_price = header.index("price")
        idx_ts = header.index("sip_timestamp")
        idx_size = header.index("size")

        for row in reader:
            ticker = row[idx_ticker]
            parsed = _fast_extract(ticker)
            if parsed is None:
                continue
            underlying = parsed[0]
            if underlying not in universe:
                continue

            price = float(row[idx_price] or 0)
            size = int(row[idx_size] or 0)
            ts_ns = int(row[idx_ts] or 0)

            if underlying not in stats:
                stats[underlying] = {
                    "trade_count": 0,
                    "total_size": 0,
                    "total_notional": 0.0,
                    "sizes": [],
                    "first_hour_trades": 0,
                    "last_hour_trades": 0,
                    "session_trades": 0,
                }

            s = stats[underlying]
            s["trade_count"] += 1
            s["total_size"] += size
            # Notional proxy: price * size * 100 (shares per contract)
            s["total_notional"] += price * size * 100
            s["sizes"].append(size)

            et_min = _ns_to_et_minutes_fast(ts_ns, utc_offset)
            if _MARKET_OPEN_MIN <= et_min < _MARKET_CLOSE_MIN:
                s["session_trades"] += 1
                if et_min < _FIRST_HOUR_END:
                    s["first_hour_trades"] += 1
                if et_min >= _LAST_HOUR_START:
                    s["last_hour_trades"] += 1

    results = {}
    for underlying, s in stats.items():
        sizes = sorted(s["sizes"])
        n = len(sizes)
        median_size = sizes[n // 2] if n > 0 else 0
        mean_size = s["total_size"] / n if n > 0 else 0

        # Session timing for trades
        session = s["session_trades"]
        first_hour_trade_pct = s["first_hour_trades"] / session * 100.0 if session > 0 else 0.0
        last_hour_trade_pct = s["last_hour_trades"] / session * 100.0 if session > 0 else 0.0

        # Large trade fraction (size >= 10 contracts)
        large_trades = sum(1 for sz in sizes if sz >= 10)
        large_pct = large_trades / n * 100.0 if n > 0 else 0.0

        results[underlying] = {
            "t_trade_count": s["trade_count"],
            "t_total_size": s["total_size"],
            "t_total_notional": round(s["total_notional"], 2),
            "t_median_trade_size": median_size,
            "t_mean_trade_size": round(mean_size, 2),
            "t_first_hour_trade_pct": round(first_hour_trade_pct, 2),
            "t_last_hour_trade_pct": round(last_hour_trade_pct, 2),
            "t_large_trade_pct": round(large_pct, 2),
        }

    return results


PANEL_COLUMNS = [
    "ticker",
    "date",
    # Minute-bar features
    "m_total_volume",
    "m_total_transactions",
    "m_minute_bars",
    "m_first_hour_pct",
    "m_last_hour_pct",
    "m_burst_top5_pct",
    "m_minute_hhi",
    "m_call_volume",
    "m_put_volume",
    "m_put_call_ratio",
    "m_front_expiry_pct",
    "m_expiry_count",
    # Trade features
    "t_trade_count",
    "t_total_size",
    "t_total_notional",
    "t_median_trade_size",
    "t_mean_trade_size",
    "t_first_hour_trade_pct",
    "t_last_hour_trade_pct",
    "t_large_trade_pct",
]


def build_panel(
    minute_dir: str,
    trades_dir: str,
    universe_path: str,
    out_path: str,
) -> dict:
    """Build the intraday options pressure panel."""
    universe = _load_universe(universe_path)
    logger.info("Universe: %d active tickers", len(universe))

    minute_root = Path(minute_dir)
    trades_root = Path(trades_dir)

    # Find all dates that have BOTH minute aggs and trades
    minute_files = {f.stem.replace(".csv", ""): f for f in sorted(minute_root.rglob("*.csv.gz"))}
    trades_files = {f.stem.replace(".csv", ""): f for f in sorted(trades_root.rglob("*.csv.gz"))}
    common_dates = sorted(set(minute_files.keys()) & set(trades_files.keys()))
    logger.info(
        "Minute files: %d, Trades files: %d, Common dates: %d",
        len(minute_files),
        len(trades_files),
        len(common_dates),
    )

    all_rows = []
    tickers_seen = set()

    for trade_date in common_dates:
        logger.info("Processing %s ...", trade_date)

        minute_feats = _process_minute_file(minute_files[trade_date], universe, trade_date)
        trade_feats = _process_trades_file(trades_files[trade_date], universe, trade_date)

        # Merge on underlying ticker
        all_underlyings = set(minute_feats.keys()) | set(trade_feats.keys())
        for underlying in sorted(all_underlyings):
            row = {"ticker": underlying, "date": trade_date}
            # Add minute features (default empty)
            mf = minute_feats.get(underlying, {})
            for col in PANEL_COLUMNS:
                if col.startswith("m_"):
                    row[col] = mf.get(col, "")
            # Add trade features (default empty)
            tf = trade_feats.get(underlying, {})
            for col in PANEL_COLUMNS:
                if col.startswith("t_"):
                    row[col] = tf.get(col, "")

            all_rows.append(row)
            tickers_seen.add(underlying)

    # Sort by date, then ticker
    all_rows.sort(key=lambda r: (r["date"], r["ticker"]))

    # Write output
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=PANEL_COLUMNS,
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(all_rows)

    summary = {
        "total_rows": len(all_rows),
        "dates": len(common_dates),
        "date_range": f"{common_dates[0]} to {common_dates[-1]}" if common_dates else "none",
        "tickers_with_activity": len(tickers_seen),
        "universe_coverage_pct": round(100 * len(tickers_seen) / len(universe), 1) if universe else 0,
        "mean_rows_per_date": round(len(all_rows) / len(common_dates), 1) if common_dates else 0,
    }

    logger.info(
        "Panel written to %s: %d rows, %d dates, %d tickers (%.1f%% coverage)",
        out_path,
        summary["total_rows"],
        summary["dates"],
        summary["tickers_with_activity"],
        summary["universe_coverage_pct"],
    )

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Build intraday options pressure panel from Massive minute aggs + trades"
    )
    parser.add_argument(
        "--minute-dir",
        default="data/caches/massive_options/minute_aggs",
        help="Path to minute_aggs cache directory",
    )
    parser.add_argument(
        "--trades-dir",
        default="data/caches/massive_options/trades",
        help="Path to trades cache directory",
    )
    parser.add_argument(
        "--universe",
        default="production_data/universe.json",
        help="Path to universe.json",
    )
    parser.add_argument(
        "--out",
        default="output/research/intraday_options_pressure_panel.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    summary = build_panel(args.minute_dir, args.trades_dir, args.universe, args.out)

    print("\n=== Intraday Options Pressure Panel Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
