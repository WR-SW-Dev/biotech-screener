#!/usr/bin/env python3
"""Build a daily per-underlying options activity panel from cached Massive day aggs.

Research-only panel for evaluating options activity as a crowding/risk feature
around catalyst names. NOT wired into the decision engine.

Output: CSV keyed by (ticker, date) with activity, breadth, and concentration metrics.

Usage:
    python3 scripts/research/build_options_activity_panel.py \
        --cache-dir data/caches/massive_options/day_aggs \
        --universe production_data/universe.json \
        --out output/research/options_activity_panel.csv
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

logger = logging.getLogger("options_activity_panel")

# OCC option ticker regex: O:<UNDERLYING><YYMMDD><C|P><STRIKE*1000>
_OCC_RE = re.compile(r"^O:([A-Z]+)(\d{6})([CP])(\d{8})$")


def _parse_occ_ticker(occ: str) -> dict | None:
    """Parse OCC-format option ticker into components."""
    m = _OCC_RE.match(occ)
    if not m:
        return None
    underlying = m.group(1)
    date_str = m.group(2)  # YYMMDD
    option_type = "put" if m.group(3) == "P" else "call"
    strike = int(m.group(4)) / 1000.0
    try:
        expiry = datetime.strptime("20" + date_str, "%Y%m%d").date()
    except ValueError:
        return None
    return {
        "underlying": underlying,
        "expiry": expiry,
        "option_type": option_type,
        "strike": strike,
    }


def _load_universe(path: str) -> set[str]:
    """Load active tickers from universe.json."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return {d["ticker"] for d in data if isinstance(d, dict) and d.get("status") == "active"}
    return set(data.keys())


def _process_day_file(gz_path: Path, universe: set[str], trade_date: str) -> list[dict]:
    """Process one day-agg gz file into per-underlying activity rows."""
    # Accumulate per-underlying stats
    stats: dict[str, dict] = {}

    with gzip.open(gz_path, "rt") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = _parse_occ_ticker(row["ticker"])
            if parsed is None:
                continue
            underlying = parsed["underlying"]
            if underlying not in universe:
                continue

            vol = int(row.get("volume", 0))
            txn = int(row.get("transactions", 0))

            if underlying not in stats:
                stats[underlying] = {
                    "total_volume": 0,
                    "total_transactions": 0,
                    "call_volume": 0,
                    "put_volume": 0,
                    "active_contracts": 0,
                    "expiries": set(),
                    "strikes": set(),
                    "near_term_volume": 0,  # expiry <= 30d
                    "contract_volumes": [],  # for HHI
                }

            s = stats[underlying]
            s["total_volume"] += vol
            s["total_transactions"] += txn
            s["active_contracts"] += 1

            if parsed["option_type"] == "call":
                s["call_volume"] += vol
            else:
                s["put_volume"] += vol

            s["expiries"].add(parsed["expiry"])
            s["strikes"].add(parsed["strike"])
            s["contract_volumes"].append(vol)

            # Near-term: expiry within 30 calendar days of trade date
            td = datetime.strptime(trade_date, "%Y-%m-%d").date()
            days_to_exp = (parsed["expiry"] - td).days
            if 0 <= days_to_exp <= 30:
                s["near_term_volume"] += vol

    # Compute derived metrics
    rows = []
    for ticker, s in stats.items():
        total_vol = s["total_volume"]
        call_vol = s["call_volume"]
        put_vol = s["put_volume"]

        # Put/call ratio (avoid div by zero)
        pc_ratio = put_vol / call_vol if call_vol > 0 else None

        # Chain breadth = active contracts
        chain_breadth = s["active_contracts"]

        # Expiry spread = number of distinct expiry dates
        expiry_spread = len(s["expiries"])

        # Strike spread = number of distinct strikes
        strike_spread = len(s["strikes"])

        # Near-term volume percentage
        near_pct = s["near_term_volume"] / total_vol * 100.0 if total_vol > 0 else 0.0

        # Concentration HHI: sum of (vol_i / total_vol)^2 across contracts
        if total_vol > 0:
            hhi = sum((v / total_vol) ** 2 for v in s["contract_volumes"] if v > 0)
        else:
            hhi = None

        rows.append(
            {
                "ticker": ticker,
                "date": trade_date,
                "total_volume": total_vol,
                "total_transactions": s["total_transactions"],
                "active_contracts": chain_breadth,
                "call_volume": call_vol,
                "put_volume": put_vol,
                "put_call_ratio": round(pc_ratio, 4) if pc_ratio is not None else "",
                "chain_breadth": chain_breadth,
                "expiry_spread": expiry_spread,
                "strike_spread": strike_spread,
                "near_term_volume_pct": round(near_pct, 2),
                "concentration_hhi": round(hhi, 6) if hhi is not None else "",
            }
        )

    return rows


PANEL_COLUMNS = [
    "ticker",
    "date",
    "total_volume",
    "total_transactions",
    "active_contracts",
    "call_volume",
    "put_volume",
    "put_call_ratio",
    "chain_breadth",
    "expiry_spread",
    "strike_spread",
    "near_term_volume_pct",
    "concentration_hhi",
]


def build_panel(
    cache_dir: str,
    universe_path: str,
    out_path: str,
) -> dict:
    """Build the full panel across all cached day-agg files."""
    universe = _load_universe(universe_path)
    logger.info("Universe: %d active tickers", len(universe))

    cache_root = Path(cache_dir)
    gz_files = sorted(cache_root.rglob("*.csv.gz"))
    logger.info("Found %d day-agg files", len(gz_files))

    all_rows = []
    dates_processed = []
    tickers_seen = set()

    for gz_path in gz_files:
        # Extract date from filename: YYYY-MM-DD.csv.gz
        trade_date = gz_path.stem.replace(".csv", "")
        logger.info("Processing %s ...", trade_date)
        rows = _process_day_file(gz_path, universe, trade_date)
        all_rows.extend(rows)
        dates_processed.append(trade_date)
        for r in rows:
            tickers_seen.add(r["ticker"])

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
        "dates": len(dates_processed),
        "date_range": (f"{dates_processed[0]} to {dates_processed[-1]}" if dates_processed else "none"),
        "tickers_with_activity": len(tickers_seen),
        "universe_coverage_pct": round(100 * len(tickers_seen) / len(universe), 1) if universe else 0,
        "mean_rows_per_date": round(len(all_rows) / len(dates_processed), 1) if dates_processed else 0,
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
    parser = argparse.ArgumentParser(description="Build daily options activity panel from cached Massive day aggs")
    parser.add_argument(
        "--cache-dir",
        default="data/caches/massive_options/day_aggs",
        help="Path to day_aggs cache directory",
    )
    parser.add_argument(
        "--universe",
        default="production_data/universe.json",
        help="Path to universe.json",
    )
    parser.add_argument(
        "--out",
        default="output/research/options_activity_panel.csv",
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

    summary = build_panel(args.cache_dir, args.universe, args.out)

    # Print summary
    print("\n=== Options Activity Panel Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
