#!/usr/bin/env python3
"""Build Trade Deltas — compare prior vs current shadow positions to produce a trade packet.

Reads two consecutive live_shadow position JSONs and writes:
  - trades.csv: ticker, action, delta_usd, target_usd, bucket, tier, catalyst_days, gap_risk, reason
  - trade_summary.md: turnover, adds/drops, largest moves, bucket drift, risk flags

Usage:
    python3 tools/build_trade_deltas.py --as-of-date 2026-03-08
    python3 tools/build_trade_deltas.py --as-of-date 2026-03-08 --min-trade 500
    python3 tools/build_trade_deltas.py --current positions/2026-03-08.json --prior positions/2026-03-06.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SHADOW_ROOT = PROJECT_ROOT / "artifacts" / "live_shadow"
POSITIONS_DIR = SHADOW_ROOT / "positions"
TRADES_ROOT = SHADOW_ROOT / "trades"

# Minimum trade size — deltas smaller than this are suppressed
DEFAULT_MIN_TRADE_USD = 500.0

TRADES_COLUMNS = [
    "ticker",
    "action",
    "delta_usd",
    "target_usd",
    "prior_usd",
    "bucket",
    "tier",
    "catalyst_days",
    "gap_risk",
    "reason",
]

BUCKET_DISPLAY = {
    "binary_0_30": "Binary 0-30d",
    "binary_31_90": "Binary 31-90d",
    "binary_91_180": "Binary 91-180d",
    "less_binary": "Less Binary",
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_positions_json(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    """Load a positions JSON and return (as_of_date, positions_list)."""
    with open(path) as f:
        doc = json.load(f)
    return doc.get("as_of_date", path.stem), doc.get("positions", [])


def find_prior_positions(
    as_of_date: str,
    positions_dir: Path = POSITIONS_DIR,
) -> Optional[Path]:
    """Find the most recent positions file before as_of_date."""
    if not positions_dir.is_dir():
        return None
    candidates = [p for p in positions_dir.iterdir() if p.suffix == ".json" and p.stem < as_of_date]
    return max(candidates, key=lambda p: p.stem) if candidates else None


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------


def compute_trade_deltas(
    prior_positions: List[Dict[str, Any]],
    current_positions: List[Dict[str, Any]],
    min_trade_usd: float = DEFAULT_MIN_TRADE_USD,
) -> List[Dict[str, Any]]:
    """Compute trade deltas between prior and current positions.

    Returns a list of trade dicts sorted by abs(delta_usd) DESC, then ticker ASC.
    Trades below min_trade_usd are filtered out.
    """
    # Index by ticker
    prior_map = {p["ticker"]: p for p in prior_positions}
    current_map = {p["ticker"]: p for p in current_positions}

    all_tickers = sorted(set(prior_map) | set(current_map))
    trades = []

    for ticker in all_tickers:
        prior = prior_map.get(ticker)
        current = current_map.get(ticker)

        prior_usd = prior.get("target_dollars", 0.0) if prior else 0.0
        target_usd = current.get("target_dollars", 0.0) if current else 0.0
        delta = target_usd - prior_usd

        # Skip tiny trades
        if abs(delta) < min_trade_usd:
            continue

        if delta > 0:
            action = "BUY"
        elif delta < 0:
            action = "SELL"
        else:
            continue

        # Reason code
        if prior is None:
            reason = "NEW_ENTRY"
        elif current is None:
            reason = "EXIT"
        else:
            # Determine what changed
            reasons = []
            if prior.get("bucket") != current.get("bucket"):
                reasons.append("BUCKET_CHANGE")
            if abs(delta) > 0:
                reasons.append("REWEIGHT")
            reason = "+".join(reasons) if reasons else "REWEIGHT"

        # Use current position for annotations, fall back to prior
        ref = current or prior
        trades.append(
            {
                "ticker": ticker,
                "action": action,
                "delta_usd": round(delta, 2),
                "target_usd": round(target_usd, 2),
                "prior_usd": round(prior_usd, 2),
                "bucket": ref.get("bucket", ""),
                "tier": ref.get("tier", ""),
                "catalyst_days": ref.get("catalyst_days", ""),
                "gap_risk": ref.get("gap_risk", ""),
                "reason": reason,
            }
        )

    # Sort: largest absolute delta first, then ticker for determinism
    trades.sort(key=lambda t: (-abs(t["delta_usd"]), t["ticker"]))
    return trades


# ---------------------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------------------


def write_trades_csv(
    trades: List[Dict[str, Any]],
    out_path: Path,
) -> Path:
    """Write trades.csv with deterministic column order."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADES_COLUMNS)
        writer.writeheader()
        writer.writerows(trades)
    return out_path


def write_trade_summary(
    trades: List[Dict[str, Any]],
    prior_date: str,
    current_date: str,
    prior_positions: List[Dict[str, Any]],
    current_positions: List[Dict[str, Any]],
    out_path: Path,
) -> Path:
    """Write trade_summary.md with human-readable trade overview."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    buys = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]
    new_entries = [t for t in trades if t["reason"] == "NEW_ENTRY"]
    exits = [t for t in trades if t["reason"] == "EXIT"]

    prior_tickers = {p["ticker"] for p in prior_positions}
    current_tickers = {p["ticker"] for p in current_positions}
    overlap = prior_tickers & current_tickers
    turnover = 1.0 - (len(overlap) / len(prior_tickers)) if prior_tickers else 0.0

    total_buy = sum(t["delta_usd"] for t in buys)
    total_sell = sum(abs(t["delta_usd"]) for t in sells)
    net_delta = sum(t["delta_usd"] for t in trades)

    gap_risk_buys = [t for t in buys if t["gap_risk"] == "HIGH"]

    lines = []
    lines.append("# Trade Summary")
    lines.append("")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"**Rebalance**: {prior_date} → {current_date}")
    lines.append(f"**Generated**: {ts}")
    lines.append(f"**Execution**: NEXT_OPEN after {current_date}")
    lines.append("")

    # Overview
    lines.append("## Overview")
    lines.append("")
    lines.append(f"- **Buys**: {len(buys)} (${total_buy:,.0f})")
    lines.append(f"- **Sells**: {len(sells)} (${total_sell:,.0f})")
    lines.append(f"- **Net delta**: ${net_delta:+,.0f}")
    lines.append(f"- **New entries**: {len(new_entries)}")
    lines.append(f"- **Exits**: {len(exits)}")
    lines.append(f"- **Turnover**: {turnover:.1%}")
    lines.append(f"- **Prior names**: {len(prior_tickers)} → **Current**: {len(current_tickers)}")
    lines.append("")

    # Risk flags
    if gap_risk_buys:
        lines.append("## Risk Flags")
        lines.append("")
        lines.append(
            f"**{len(gap_risk_buys)} BUY(s) with gap-risk HIGH**: " f"{', '.join(t['ticker'] for t in gap_risk_buys)}"
        )
        lines.append("")

    # Largest moves
    lines.append("## Largest Trades")
    lines.append("")
    lines.append("| Ticker | Action | Delta | Target | Bucket | Gap Risk | Reason |")
    lines.append("|--------|--------|-------|--------|--------|----------|--------|")
    for t in trades[:15]:
        lines.append(
            f"| {t['ticker']} | {t['action']} "
            f"| ${t['delta_usd']:+,.0f} | ${t['target_usd']:,.0f} "
            f"| {BUCKET_DISPLAY.get(t['bucket'], t['bucket'])} "
            f"| {t['gap_risk'] or '-'} | {t['reason']} |"
        )
    if len(trades) > 15:
        lines.append(f"| ... | *{len(trades) - 15} more* | | | | | |")
    lines.append("")

    # Bucket drift
    prior_buckets: Dict[str, int] = {}
    current_buckets: Dict[str, int] = {}
    for p in prior_positions:
        b = p.get("bucket", "")
        prior_buckets[b] = prior_buckets.get(b, 0) + 1
    for p in current_positions:
        b = p.get("bucket", "")
        current_buckets[b] = current_buckets.get(b, 0) + 1

    lines.append("## Bucket Drift")
    lines.append("")
    lines.append("| Bucket | Prior | Current | Delta |")
    lines.append("|--------|-------|---------|-------|")
    for b in ["binary_0_30", "binary_31_90", "binary_91_180", "less_binary"]:
        pc = prior_buckets.get(b, 0)
        cc = current_buckets.get(b, 0)
        lines.append(f"| {BUCKET_DISPLAY.get(b, b)} | {pc} | {cc} | {cc - pc:+d} |")
    lines.append("")

    text = "\n".join(lines)
    with open(out_path, "w") as f:
        f.write(text)
    return out_path


def build_no_trades_summary(
    as_of_date: str,
    reason: str,
    out_path: Path,
) -> Path:
    """Write a minimal summary when no trades are generated."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = (
        f"# Trade Summary\n\n"
        f"**Date**: {as_of_date}\n"
        f"**Generated**: {ts}\n\n"
        f"**No trades generated**: {reason}\n"
    )
    with open(out_path, "w") as f:
        f.write(text)
    return out_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def build_trade_packet(
    current_path: Path,
    prior_path: Optional[Path] = None,
    *,
    min_trade_usd: float = DEFAULT_MIN_TRADE_USD,
    out_dir: Optional[Path] = None,
    positions_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build a complete trade packet from two position files.

    Returns dict with trades, paths, summary stats.
    """
    current_date, current_positions = load_positions_json(current_path)

    if prior_path is None:
        prior_path = find_prior_positions(current_date, positions_dir or POSITIONS_DIR)

    if prior_path is None:
        # First snapshot — all positions are new entries
        prior_date = ""
        prior_positions: List[Dict[str, Any]] = []
    else:
        prior_date, prior_positions = load_positions_json(prior_path)

    trades = compute_trade_deltas(prior_positions, current_positions, min_trade_usd)

    if out_dir is None:
        out_dir = TRADES_ROOT / current_date
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = write_trades_csv(trades, out_dir / "trades.csv")

    if trades:
        md_path = write_trade_summary(
            trades,
            prior_date,
            current_date,
            prior_positions,
            current_positions,
            out_dir / "trade_summary.md",
        )
    else:
        md_path = build_no_trades_summary(
            current_date,
            "No position changes above threshold",
            out_dir / "trade_summary.md",
        )

    return {
        "as_of_date": current_date,
        "prior_date": prior_date,
        "n_trades": len(trades),
        "n_buys": sum(1 for t in trades if t["action"] == "BUY"),
        "n_sells": sum(1 for t in trades if t["action"] == "SELL"),
        "total_buy_usd": sum(t["delta_usd"] for t in trades if t["action"] == "BUY"),
        "total_sell_usd": sum(abs(t["delta_usd"]) for t in trades if t["action"] == "SELL"),
        "csv_path": str(csv_path),
        "summary_path": str(md_path),
        "trades": trades,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Build weekly trade deltas")
    parser.add_argument("--as-of-date", type=str, help="Current snapshot date")
    parser.add_argument("--current", type=str, help="Path to current positions JSON")
    parser.add_argument("--prior", type=str, help="Path to prior positions JSON")
    parser.add_argument(
        "--min-trade",
        type=float,
        default=DEFAULT_MIN_TRADE_USD,
        help=f"Minimum trade size in USD (default: {DEFAULT_MIN_TRADE_USD})",
    )
    parser.add_argument("--out-dir", type=str, help="Output directory for trade packet")
    args = parser.parse_args()

    if args.current:
        current_path = Path(args.current)
    elif args.as_of_date:
        current_path = POSITIONS_DIR / f"{args.as_of_date}.json"
    else:
        # Find latest
        candidates = sorted(POSITIONS_DIR.glob("*.json"))
        if not candidates:
            print("ERROR: No position files found", file=sys.stderr)
            sys.exit(1)
        current_path = candidates[-1]

    if not current_path.is_file():
        print(f"ERROR: Position file not found: {current_path}", file=sys.stderr)
        sys.exit(1)

    prior_path = Path(args.prior) if args.prior else None
    out_dir = Path(args.out_dir) if args.out_dir else None

    result = build_trade_packet(
        current_path,
        prior_path,
        min_trade_usd=args.min_trade,
        out_dir=out_dir,
    )

    print(f"Trade packet for {result['as_of_date']}")
    print(f"  Prior: {result['prior_date'] or '(none — first snapshot)'}")
    print(f"  Trades: {result['n_trades']} ({result['n_buys']} buys, {result['n_sells']} sells)")
    print(f"  Buy total: ${result['total_buy_usd']:,.0f}")
    print(f"  Sell total: ${result['total_sell_usd']:,.0f}")
    print(f"  CSV: {result['csv_path']}")
    print(f"  Summary: {result['summary_path']}")


if __name__ == "__main__":
    main()
