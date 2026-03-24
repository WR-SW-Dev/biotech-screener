#!/usr/bin/env python3
"""Record Fills — track execution vs planned trades.

Reads trades.csv from a trade packet, generates a fills template,
accepts fill data, computes slippage, and writes a fill summary.

Usage:
    python3 tools/record_fills.py --trade-date 2026-03-06
    python3 tools/record_fills.py --trade-date 2026-03-06 --fills-input fills_input.csv
    python3 tools/record_fills.py --trade-date 2026-03-06 --mark-all-filled
    python3 tools/record_fills.py --trade-date 2026-03-06 --summary
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SHADOW_ROOT = PROJECT_ROOT / "artifacts" / "live_shadow"
TRADES_ROOT = SHADOW_ROOT / "trades"

FILLS_COLUMNS = [
    "ticker",
    "action",
    "target_usd",
    "fill_price",
    "fill_shares",
    "fill_usd",
    "slippage_bps",
    "fill_date",
    "status",
]

VALID_STATUSES = {"PENDING", "FILLED", "PARTIAL", "SKIPPED", "CANCELLED"}


def generate_fill_template(
    trades_csv: Path,
    out_path: Path,
) -> Path:
    """Read trades.csv, write fills.csv with PENDING status and empty fill fields."""
    if not trades_csv.is_file():
        raise FileNotFoundError(f"trades.csv not found: {trades_csv}")

    with open(trades_csv, encoding="utf-8") as f:
        trades = list(csv.DictReader(f))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for t in trades:
        rows.append(
            {
                "ticker": t.get("ticker", ""),
                "action": t.get("action", ""),
                "target_usd": t.get("delta_usd", "0"),
                "fill_price": "",
                "fill_shares": "",
                "fill_usd": "",
                "slippage_bps": "",
                "fill_date": "",
                "status": "PENDING",
            }
        )

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FILLS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def compute_slippage_bps(target_usd: float, fill_usd: float) -> float:
    """Compute slippage in basis points. Positive = worse than target."""
    if abs(target_usd) < 0.01:
        return 0.0
    return round((fill_usd / target_usd - 1.0) * 10000, 2)


def apply_fills(
    fills_csv: Path,
    fills_input: Path,
) -> Path:
    """Merge fill data into fills.csv from fills_input.csv.

    fills_input should have columns: ticker, fill_price, fill_shares, status
    (optional: fill_date). Matches by ticker.
    """
    with open(fills_csv, encoding="utf-8") as f:
        fills = list(csv.DictReader(f))

    with open(fills_input, encoding="utf-8") as f:
        inputs = list(csv.DictReader(f))

    input_map = {r["ticker"]: r for r in inputs}

    for fill in fills:
        ticker = fill["ticker"]
        inp = input_map.get(ticker)
        if not inp:
            continue

        status = inp.get("status", "FILLED").strip().upper()
        if status not in VALID_STATUSES:
            status = "FILLED"
        fill["status"] = status

        fill_price = inp.get("fill_price", "").strip()
        fill_shares = inp.get("fill_shares", "").strip()
        fill_date = inp.get("fill_date", "").strip()

        if fill_price:
            fill["fill_price"] = fill_price
        if fill_shares:
            fill["fill_shares"] = fill_shares
        if fill_date:
            fill["fill_date"] = fill_date

        # Compute fill_usd and slippage if we have price + shares
        if fill_price and fill_shares:
            try:
                fusd = float(fill_price) * float(fill_shares)
                fill["fill_usd"] = str(round(fusd, 2))
                target = float(fill.get("target_usd", "0") or "0")
                fill["slippage_bps"] = str(compute_slippage_bps(abs(target), fusd))
            except (ValueError, TypeError):
                pass

    with open(fills_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FILLS_COLUMNS)
        writer.writeheader()
        writer.writerows(fills)
    return fills_csv


def mark_all_filled(fills_csv: Path, fill_date: str = "") -> Path:
    """Mark all PENDING fills as FILLED with zero slippage (shadow/paper trading)."""
    with open(fills_csv, encoding="utf-8") as f:
        fills = list(csv.DictReader(f))

    if not fill_date:
        fill_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for fill in fills:
        if fill.get("status") == "PENDING":
            target = abs(float(fill.get("target_usd", "0") or "0"))
            fill["fill_usd"] = str(round(target, 2))
            fill["slippage_bps"] = "0.0"
            fill["fill_date"] = fill_date
            fill["status"] = "FILLED"

    with open(fills_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FILLS_COLUMNS)
        writer.writeheader()
        writer.writerows(fills)
    return fills_csv


def compute_execution_quality(fills_csv: Path) -> Dict[str, Any]:
    """Compute aggregate execution quality metrics from fills.csv."""
    with open(fills_csv, encoding="utf-8") as f:
        fills = list(csv.DictReader(f))

    total = len(fills)
    if total == 0:
        return {
            "total": 0,
            "fill_rate": 0.0,
            "mean_slippage_bps": 0.0,
            "median_slippage_bps": 0.0,
            "total_target_usd": 0.0,
            "total_filled_usd": 0.0,
            "worst_slippage": None,
        }

    filled = [f for f in fills if f.get("status") in ("FILLED", "PARTIAL")]
    fill_rate = len(filled) / total if total > 0 else 0.0

    slippages = []
    total_target = 0.0
    total_filled = 0.0
    worst = None
    worst_slip = 0.0

    for f in fills:
        try:
            target = abs(float(f.get("target_usd", "0") or "0"))
            total_target += target
        except (ValueError, TypeError):
            pass

        if f.get("status") not in ("FILLED", "PARTIAL"):
            continue
        try:
            fusd = float(f.get("fill_usd", "0") or "0")
            total_filled += fusd
        except (ValueError, TypeError):
            pass
        try:
            slip = float(f.get("slippage_bps", "0") or "0")
            slippages.append(slip)
            if abs(slip) > abs(worst_slip):
                worst_slip = slip
                worst = f.get("ticker", "")
        except (ValueError, TypeError):
            pass

    mean_slip = sum(slippages) / len(slippages) if slippages else 0.0
    sorted_slips = sorted(slippages)
    n = len(sorted_slips)
    if n == 0:
        median_slip = 0.0
    elif n % 2 == 1:
        median_slip = sorted_slips[n // 2]
    else:
        median_slip = (sorted_slips[n // 2 - 1] + sorted_slips[n // 2]) / 2.0

    return {
        "total": total,
        "n_filled": len(filled),
        "fill_rate": round(fill_rate, 4),
        "mean_slippage_bps": round(mean_slip, 2),
        "median_slippage_bps": round(median_slip, 2),
        "total_target_usd": round(total_target, 2),
        "total_filled_usd": round(total_filled, 2),
        "worst_slippage": {"ticker": worst, "slippage_bps": worst_slip} if worst else None,
    }


def write_fill_summary(fills_csv: Path, out_path: Path) -> Path:
    """Write fill_summary.md with execution quality metrics."""
    quality = compute_execution_quality(fills_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Fill Summary",
        "",
        f"**Generated**: {ts}",
        f"**Source**: {fills_csv.name}",
        "",
        "## Execution Quality",
        "",
        f"- **Total trades**: {quality['total']}",
        f"- **Filled**: {quality.get('n_filled', 0)} ({quality['fill_rate']:.0%})",
        f"- **Mean slippage**: {quality['mean_slippage_bps']:.1f} bps",
        f"- **Median slippage**: {quality['median_slippage_bps']:.1f} bps",
        f"- **Total target**: ${quality['total_target_usd']:,.0f}",
        f"- **Total filled**: ${quality['total_filled_usd']:,.0f}",
    ]
    worst = quality.get("worst_slippage")
    if worst:
        lines.append(f"- **Worst slippage**: {worst['ticker']} ({worst['slippage_bps']:.1f} bps)")
    lines.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    return out_path


def record_fills(
    trade_date: str,
    *,
    trades_root: Path = TRADES_ROOT,
    fills_input: Optional[Path] = None,
    do_mark_all_filled: bool = False,
    summary_only: bool = False,
) -> Dict[str, Any]:
    """Main entry: generate template, apply fills, or write summary."""
    trade_dir = trades_root / trade_date
    trades_csv = trade_dir / "trades.csv"
    fills_csv = trade_dir / "fills.csv"

    if summary_only:
        if not fills_csv.is_file():
            raise FileNotFoundError(f"fills.csv not found for {trade_date}")
        summary_path = write_fill_summary(fills_csv, trade_dir / "fill_summary.md")
        return {"action": "summary", "summary_path": str(summary_path)}

    # Generate template if fills.csv doesn't exist
    if not fills_csv.is_file():
        if not trades_csv.is_file():
            raise FileNotFoundError(f"No trades.csv for {trade_date}")
        generate_fill_template(trades_csv, fills_csv)
        print(f"  Generated fills template: {fills_csv}")

    # Apply fills from input
    if fills_input:
        apply_fills(fills_csv, fills_input)
        print(f"  Applied fills from {fills_input}")

    # Mark all filled (paper trading mode)
    if do_mark_all_filled:
        mark_all_filled(fills_csv, fill_date=trade_date)
        print("  Marked all as FILLED (paper trading)")

    # Write summary
    summary_path = write_fill_summary(fills_csv, trade_dir / "fill_summary.md")

    quality = compute_execution_quality(fills_csv)
    return {
        "action": "record",
        "fills_csv": str(fills_csv),
        "summary_path": str(summary_path),
        "quality": quality,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill/execution tracker")
    parser.add_argument("--trade-date", required=True, help="Trade date (YYYY-MM-DD)")
    parser.add_argument("--fills-input", type=str, help="Path to fills input CSV")
    parser.add_argument("--mark-all-filled", action="store_true", help="Mark all as FILLED (paper trading)")
    parser.add_argument("--summary", action="store_true", help="Write summary only")
    args = parser.parse_args()

    fills_input = Path(args.fills_input) if args.fills_input else None

    result = record_fills(
        args.trade_date,
        fills_input=fills_input,
        do_mark_all_filled=args.mark_all_filled,
        summary_only=args.summary,
    )

    if result.get("quality"):
        q = result["quality"]
        print(f"Fill rate: {q['fill_rate']:.0%} ({q.get('n_filled', 0)}/{q['total']})")
        print(f"Mean slippage: {q['mean_slippage_bps']:.1f} bps")
    print(f"Summary: {result.get('summary_path', 'N/A')}")


if __name__ == "__main__":
    main()
