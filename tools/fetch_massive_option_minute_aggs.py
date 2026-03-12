#!/usr/bin/env python3
"""Download options minute-aggregate flat files from Massive S3.

Usage:
    python tools/fetch_massive_option_minute_aggs.py --date 2025-01-02
    python tools/fetch_massive_option_minute_aggs.py --from 2025-01-02 --to 2025-01-10
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.options_history_massive import download_minute_aggs, ingest_minute_aggs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("fetch_minute_aggs")


def _date_range(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Massive options minute aggregates")
    parser.add_argument("--date", default=None, help="Single date (YYYY-MM-DD)")
    parser.add_argument("--from", dest="from_date", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="Re-download existing files")
    parser.add_argument("--ingest", action="store_true", help="Parse and print summary after download")
    args = parser.parse_args()

    if args.date:
        dates = [date.fromisoformat(args.date)]
    elif args.from_date and args.to_date:
        dates = list(_date_range(date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)))
    else:
        parser.error("Provide --date or --from/--to")
        return 1

    ok, fail = 0, 0
    for dt in dates:
        if dt.weekday() >= 5:
            continue
        path = download_minute_aggs(dt, force=args.force)
        if path:
            ok += 1
            if args.ingest:
                records = ingest_minute_aggs(dt)
                logger.info("  %s: %d records", dt, len(records))
        else:
            fail += 1

    logger.info("Done: %d downloaded, %d failed, %d skipped (weekends)", ok, fail, len(dates) - ok - fail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
