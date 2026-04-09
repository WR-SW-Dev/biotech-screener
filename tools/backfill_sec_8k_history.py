#!/usr/bin/env python3
"""Backfill historical SEC 8-K catalyst cache for PIT research.

Iterates over a date range at configurable cadence, calling the existing
sec_8k_catalyst_collector for each date. Respects SEC EDGAR rate limits
(10 req/sec) and skips dates with existing cache files.

Usage:
    python tools/backfill_sec_8k_history.py \
        --date-from 2020-01-01 --date-to 2024-12-31 \
        --cadence quarterly

    python tools/backfill_sec_8k_history.py \
        --date-from 2022-01-01 --date-to 2024-12-31 \
        --cadence monthly --resume
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("backfill_sec_8k")

DEFAULT_CACHE_DIR = REPO_ROOT / "cache" / "sec" / "8k_catalysts"


def generate_dates(
    date_from: str,
    date_to: str,
    cadence: str,
) -> List[date]:
    """Generate backfill dates at the specified cadence."""
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    dates = []

    if cadence == "quarterly":
        # End of each quarter
        for year in range(start.year, end.year + 1):
            for month in [3, 6, 9, 12]:
                # Last day of quarter month
                if month == 12:
                    dt = date(year, 12, 31)
                else:
                    dt = date(year, month + 1, 1) - timedelta(days=1)
                if start <= dt <= end:
                    dates.append(dt)
    elif cadence == "monthly":
        dt = date(start.year, start.month, 1)
        while dt <= end:
            # Last day of month
            if dt.month == 12:
                eom = date(dt.year, 12, 31)
            else:
                eom = date(dt.year, dt.month + 1, 1) - timedelta(days=1)
            if start <= eom <= end:
                dates.append(eom)
            if dt.month == 12:
                dt = date(dt.year + 1, 1, 1)
            else:
                dt = date(dt.year, dt.month + 1, 1)
    else:
        raise ValueError(f"Unknown cadence: {cadence}")

    return dates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill SEC 8-K catalyst cache for PIT research",
    )
    parser.add_argument("--date-from", type=str, required=True)
    parser.add_argument("--date-to", type=str, required=True)
    parser.add_argument(
        "--cadence",
        type=str,
        choices=["quarterly", "monthly"],
        default="quarterly",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
    )
    parser.add_argument(
        "--universe",
        type=Path,
        default=REPO_ROOT / "production_data" / "universe.json",
    )
    parser.add_argument("--resume", action="store_true", help="Skip existing cache dates")
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from wake_robin_data_pipeline.collectors.sec_8k_catalyst_collector import (
        _versioned_cache_path,
        collect_8k_timing_events,
    )

    # Load universe
    universe_data = json.loads(args.universe.read_text())
    if isinstance(universe_data, list):
        universe = [{"ticker": t} if isinstance(t, str) else t for t in universe_data]
    else:
        universe = [{"ticker": t} if isinstance(t, str) else t for t in universe_data.get("tickers", [])]
    logger.info("Universe: %d tickers", len(universe))

    dates = generate_dates(args.date_from, args.date_to, args.cadence)
    logger.info(
        "Backfill: %d dates (%s), %s to %s",
        len(dates),
        args.cadence,
        dates[0] if dates else "none",
        dates[-1] if dates else "none",
    )

    if args.dry_run:
        for dt in dates:
            cache_path = _versioned_cache_path(args.cache_dir, dt)
            exists = cache_path.exists()
            print(f"  {dt}: {'SKIP (cached)' if exists else 'WOULD FETCH'}")
        return 0

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    n_fetched = 0
    n_skipped = 0
    n_failed = 0
    total_events = 0

    for i, dt in enumerate(dates):
        cache_path = _versioned_cache_path(args.cache_dir, dt)
        if args.resume and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                logger.info(
                    "[%d/%d] %s: cached (%d events)",
                    i + 1,
                    len(dates),
                    dt,
                    len(cached),
                )
                n_skipped += 1
                total_events += len(cached)
                continue
            except (json.JSONDecodeError, OSError):
                pass

        logger.info(
            "[%d/%d] %s: fetching (lookback=%dd)...",
            i + 1,
            len(dates),
            dt,
            args.lookback_days,
        )

        try:
            events = collect_8k_timing_events(
                universe=universe,
                as_of_date=dt,
                cache_dir=args.cache_dir,
                lookback_days=args.lookback_days,
            )
            n_fetched += 1
            total_events += len(events)
            logger.info("  → %d events", len(events))

            # Pause between dates to respect rate limits
            if i < len(dates) - 1:
                time.sleep(2)

        except Exception as exc:
            logger.warning("  → FAILED: %s", exc)
            n_failed += 1

    logger.info(
        "\nDone: %d fetched, %d skipped, %d failed, %d total events",
        n_fetched,
        n_skipped,
        n_failed,
        total_events,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
