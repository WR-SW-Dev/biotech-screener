#!/usr/bin/env python3
"""Import Fills — normalize broker fill CSVs to internal schema.

Reads broker fill exports (IBKR, generic), normalizes columns,
matches against the trade plan, computes slippage, and writes fills.csv.

Usage:
    python3 tools/import_fills.py --broker-csv ~/Downloads/fills.csv --trade-date 2026-03-07
    python3 tools/import_fills.py --broker-csv ~/Downloads/fills.csv --trade-date 2026-03-07 --broker ibkr
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.record_fills import FILLS_COLUMNS, compute_slippage_bps

TRADES_ROOT = PROJECT_ROOT / "artifacts" / "live_shadow" / "trades"

BROKER_SCHEMAS: Dict[str, Dict[str, str]] = {
    "ibkr": {
        "symbol": "Symbol",
        "side": "Buy/Sell",
        "qty": "Quantity",
        "price": "Price",
        "date": "Date/Time",
    },
    "generic": {
        "symbol": "symbol",
        "side": "side",
        "qty": "qty",
        "price": "price",
        "date": "date",
    },
}

IBKR_SIDE_MAP = {"BOT": "BUY", "SLD": "SELL", "BUY": "BUY", "SELL": "SELL"}


def detect_broker_format(csv_path: Path) -> str:
    """Sniff headers to detect broker. Return 'ibkr' | 'generic'."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return "generic"
    header_set = {h.strip() for h in headers}
    ibkr_cols = set(BROKER_SCHEMAS["ibkr"].values())
    if ibkr_cols.issubset(header_set):
        return "ibkr"
    return "generic"


def normalize_broker_csv(csv_path: Path, broker: str = "auto") -> List[Dict]:
    """Read broker CSV, map columns, normalize side to BUY/SELL.

    Returns list of dicts with keys: symbol, side, qty, price, date.
    """
    if broker == "auto":
        broker = detect_broker_format(csv_path)

    schema = BROKER_SCHEMAS.get(broker, BROKER_SCHEMAS["generic"])

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fills: List[Dict] = []
    for row in rows:
        raw_side = (row.get(schema["side"], "") or "").strip().upper()
        side = IBKR_SIDE_MAP.get(raw_side, raw_side) if broker == "ibkr" else raw_side
        if side not in ("BUY", "SELL"):
            continue

        try:
            qty = abs(float(row.get(schema["qty"], "0") or "0"))
            price = abs(float(row.get(schema["price"], "0") or "0"))
        except (ValueError, TypeError):
            continue

        fills.append(
            {
                "symbol": (row.get(schema["symbol"], "") or "").strip(),
                "side": side,
                "qty": qty,
                "price": price,
                "date": (row.get(schema["date"], "") or "").strip(),
            }
        )
    return fills


def match_fills_to_trades(fills: List[Dict], trades_csv: Path) -> List[Dict]:
    """Match normalized fills to trade plan rows by ticker+side.

    Computes fill_usd, slippage_bps, and status per trade.
    """
    with open(trades_csv, newline="", encoding="utf-8") as f:
        trades = list(csv.DictReader(f))

    # Index fills by (symbol, side) — aggregate if multiple partial fills
    fill_map: Dict[tuple, List[Dict]] = {}
    for fl in fills:
        key = (fl["symbol"], fl["side"])
        fill_map.setdefault(key, []).append(fl)

    matched: List[Dict] = []
    for t in trades:
        ticker = t.get("ticker", "")
        action = t.get("action", "BUY")
        target_usd = abs(float(t.get("delta_usd", "0") or "0"))
        key = (ticker, action)

        fls = fill_map.pop(key, [])
        if not fls:
            matched.append(
                {
                    "ticker": ticker,
                    "action": action,
                    "target_usd": str(round(target_usd, 2)),
                    "fill_price": "",
                    "fill_shares": "",
                    "fill_usd": "",
                    "slippage_bps": "",
                    "fill_date": "",
                    "status": "SKIPPED",
                }
            )
            continue

        total_shares = sum(fl["qty"] for fl in fls)
        # VWAP across partial fills
        total_notional = sum(fl["qty"] * fl["price"] for fl in fls)
        vwap = total_notional / total_shares if total_shares > 0 else 0.0
        fill_usd = round(total_notional, 2)
        fill_date = fls[0].get("date", "")

        slip = compute_slippage_bps(target_usd, fill_usd)

        # Determine status: FILLED if fill_usd >= 90% of target, else PARTIAL
        ratio = fill_usd / target_usd if target_usd > 0 else 0.0
        status = "FILLED" if ratio >= 0.90 else "PARTIAL"

        matched.append(
            {
                "ticker": ticker,
                "action": action,
                "target_usd": str(round(target_usd, 2)),
                "fill_price": str(round(vwap, 4)),
                "fill_shares": str(round(total_shares, 4)),
                "fill_usd": str(fill_usd),
                "slippage_bps": str(slip),
                "fill_date": fill_date,
                "status": status,
            }
        )

    # Remaining fills with no matching trade
    for key, fls in fill_map.items():
        for fl in fls:
            fill_usd = round(fl["qty"] * fl["price"], 2)
            matched.append(
                {
                    "ticker": fl["symbol"],
                    "action": fl["side"],
                    "target_usd": "0",
                    "fill_price": str(round(fl["price"], 4)),
                    "fill_shares": str(round(fl["qty"], 4)),
                    "fill_usd": str(fill_usd),
                    "slippage_bps": "0.0",
                    "fill_date": fl.get("date", ""),
                    "status": "SKIPPED",
                }
            )

    return matched


def write_matched_fills(matched: List[Dict], out_path: Path) -> Path:
    """Write fills.csv in FILLS_COLUMNS format."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FILLS_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(matched)
    return out_path


def import_fills(
    broker_csv: Path,
    trade_date: str,
    *,
    broker: str = "auto",
    trades_root: Path = TRADES_ROOT,
) -> Path:
    """Top-level: detect format -> normalize -> match -> write fills.csv."""
    trade_dir = trades_root / trade_date
    trades_csv = trade_dir / "trade_plan.csv"
    if not trades_csv.is_file():
        # Try trades.csv (from build_trade_deltas)
        trades_csv = trade_dir / "trades.csv"
    if not trades_csv.is_file():
        raise FileNotFoundError(f"No trade plan found for {trade_date} in {trade_dir}")

    fills = normalize_broker_csv(broker_csv, broker=broker)
    matched = match_fills_to_trades(fills, trades_csv)
    out_path = write_matched_fills(matched, trade_dir / "fills.csv")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Import broker fill CSV")
    parser.add_argument("--broker-csv", type=str, required=True, help="Path to broker fill export CSV")
    parser.add_argument("--trade-date", type=str, required=True, help="Trade date (YYYY-MM-DD)")
    parser.add_argument(
        "--broker",
        type=str,
        default="auto",
        choices=["auto", "ibkr", "generic"],
        help="Broker format (default: auto-detect)",
    )
    parser.add_argument("--trades-root", type=str, help="Override trades root directory")
    args = parser.parse_args()

    trades_root = Path(args.trades_root) if args.trades_root else TRADES_ROOT
    out_path = import_fills(
        Path(args.broker_csv),
        args.trade_date,
        broker=args.broker,
        trades_root=trades_root,
    )
    print(f"Fills written: {out_path}")

    # Print summary
    from tools.record_fills import compute_execution_quality

    quality = compute_execution_quality(out_path)
    n_filled = quality.get("n_filled", 0)
    total = quality.get("total", 0)
    print(f"Fill rate: {quality['fill_rate']:.0%} ({n_filled}/{total})")
    print(f"Mean slippage: {quality['mean_slippage_bps']:.1f} bps")


if __name__ == "__main__":
    main()
