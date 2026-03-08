#!/usr/bin/env python3
"""Backfill Shadow History — seed position + performance history from prior snapshots.

Runs run_shadow_portfolio() on each snapshot date in chronological order,
then run_weekly_rebalance() on Fridays.

Usage:
    python3 tools/backfill_shadow_history.py --start-date 2026-03-01 --end-date 2026-03-08
    python3 tools/backfill_shadow_history.py --start-date 2026-03-01 --end-date 2026-03-08 --force
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.live_shadow_portfolio import (
    PRICE_HISTORY_PATH,
    SHADOW_ROOT,
    SNAPSHOTS_ROOT,
    append_performance,
    build_positions,
    compute_performance,
    load_metadata,
    load_policy,
    load_rankings,
    save_positions,
    write_weekly_summary,
)
from tools.run_weekly_rebalance import is_rebalance_day, run_weekly_rebalance


def dates_in_performance_csv(perf_csv: Path) -> Set[str]:
    """Read performance.csv and return set of date strings already present."""
    if not perf_csv.is_file():
        return set()
    dates: Set[str] = set()
    with open(perf_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("date", "").strip()
            if d:
                dates.add(d)
    return dates


def _remove_perf_date(perf_csv: Path, date: str) -> None:
    """Remove a single date row from performance.csv (for --force re-run)."""
    if not perf_csv.is_file():
        return
    with open(perf_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = [r for r in reader if r.get("date") != date]
    if fieldnames is None:
        return
    with open(perf_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def discover_snapshot_dates(
    snapshots_root: Path,
    start_date: str,
    end_date: str,
) -> list[str]:
    """Return sorted list of YYYY-MM-DD snapshot dirs in [start, end] range.

    Filters to dirs with rankings.csv present and exact 10-char date names.
    """
    if not snapshots_root.is_dir():
        return []
    dates = []
    for d in snapshots_root.iterdir():
        if not d.is_dir() or len(d.name) != 10:
            continue
        if start_date <= d.name <= end_date and (d / "rankings.csv").is_file():
            dates.append(d.name)
    dates.sort()
    return dates


def backfill_shadow_history(
    start_date: str,
    end_date: str,
    *,
    force: bool = False,
    snapshots_root: Path = SNAPSHOTS_ROOT,
    shadow_root: Path = SHADOW_ROOT,
    price_path: Path = PRICE_HISTORY_PATH,
    policy_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Backfill shadow portfolio history for a date range.

    Iterates snapshot dates chronologically, builds positions, computes
    performance, then generates trade packets on Fridays.

    Returns summary dict with n_dates_processed, n_skipped, n_trade_days, errors.
    """
    dates = discover_snapshot_dates(snapshots_root, start_date, end_date)
    if not dates:
        return {"n_dates_processed": 0, "n_skipped": 0, "n_trade_days": 0, "errors": []}

    policy = load_policy(policy_path)
    positions_dir = shadow_root / "positions"
    perf_csv = shadow_root / "performance.csv"
    existing_perf_dates = dates_in_performance_csv(perf_csv)

    n_processed = 0
    n_skipped = 0
    errors: list[str] = []

    # Phase 1: build positions + performance chronologically
    for date in dates:
        pos_path = positions_dir / f"{date}.json"
        if pos_path.is_file() and not force:
            n_skipped += 1
            continue

        try:
            snap_dir = snapshots_root / date
            rankings = load_rankings(snap_dir)
            metadata = load_metadata(snap_dir)
            as_of_date = metadata.get("as_of_date", date)
            positions_data = build_positions(rankings, policy)

            save_positions(as_of_date, positions_data, metadata, positions_dir)

            # Compute performance vs prior (if any)
            from tools.live_shadow_portfolio import load_prior_positions

            prior = load_prior_positions(as_of_date, positions_dir)
            perf = None
            if prior:
                prior_date, prior_positions = prior
                perf = compute_performance(
                    prior_positions,
                    positions_data["positions"],
                    prior_date,
                    as_of_date,
                    price_path,
                )
                # Guard against duplicate perf rows
                if as_of_date in existing_perf_dates:
                    if force:
                        _remove_perf_date(perf_csv, as_of_date)
                    else:
                        perf = None  # skip append
                if perf:
                    append_performance(as_of_date, perf, metadata.get("ruleset_id", ""), perf_csv)
                    existing_perf_dates.add(as_of_date)

            # Weekly summary (overwritten each time, last date wins)
            summary_path = shadow_root / "weekly_summary.md"
            write_weekly_summary(as_of_date, positions_data, perf, policy, metadata, summary_path)

            n_processed += 1
            print(f"  [{date}] positions OK ({positions_data['summary']['total_positions']} names)")
        except Exception as exc:
            errors.append(f"{date}: {exc}")
            print(f"  [{date}] ERROR: {exc}")

    # Phase 2: generate trade packets on Fridays
    n_trade_days = 0
    for date in dates:
        pos_path = positions_dir / f"{date}.json"
        if not pos_path.is_file():
            continue
        if not is_rebalance_day(date, policy):
            continue

        trades_dir = shadow_root / "trades" / date
        if (trades_dir / "trades.csv").is_file() and not force:
            continue

        try:
            result = run_weekly_rebalance(
                date,
                policy_path=policy_path,
                positions_dir=positions_dir,
                force=True,
            )
            n_trades = result.get("n_trades", 0)
            print(f"  [{date}] trades OK ({n_trades} trades, decision={result['decision']})")
            n_trade_days += 1
        except Exception as exc:
            errors.append(f"{date} trades: {exc}")
            print(f"  [{date}] trades ERROR: {exc}")

    return {
        "n_dates_processed": n_processed,
        "n_skipped": n_skipped,
        "n_trade_days": n_trade_days,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill shadow portfolio history")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing positions/perf")
    parser.add_argument("--policy", type=str, help="Portfolio policy JSON path")
    args = parser.parse_args()

    policy_path = Path(args.policy) if args.policy else None

    print(f"Backfilling shadow history: {args.start_date} → {args.end_date}")
    result = backfill_shadow_history(
        args.start_date,
        args.end_date,
        force=args.force,
        policy_path=policy_path,
    )

    print(
        f"\nDone: {result['n_dates_processed']} processed, {result['n_skipped']} skipped, "
        f"{result['n_trade_days']} trade days"
    )
    if result["errors"]:
        print(f"Errors ({len(result['errors'])}):")
        for e in result["errors"]:
            print(f"  - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
