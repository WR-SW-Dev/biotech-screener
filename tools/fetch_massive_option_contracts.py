#!/usr/bin/env python3
"""Fetch options contracts from Massive REST API for one or more underlyings.

Usage:
    python tools/fetch_massive_option_contracts.py --ticker MRNA --as-of 2026-03-12
    python tools/fetch_massive_option_contracts.py --ticker MRNA,IONS --expiration-from 2026-04-01
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.options_history_massive import list_contracts, write_index

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("fetch_contracts")

DEFAULT_CACHE = REPO_ROOT / "data" / "caches" / "massive_options" / "contracts"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Massive options contracts")
    parser.add_argument("--ticker", required=True, help="Underlying ticker(s), comma-separated")
    parser.add_argument("--as-of", default=None, help="Historical snapshot date (YYYY-MM-DD)")
    parser.add_argument("--expiration-from", default=None, help="Min expiration (YYYY-MM-DD)")
    parser.add_argument("--expiration-to", default=None, help="Max expiration (YYYY-MM-DD)")
    parser.add_argument("--expired", action="store_true", help="Include expired contracts")
    parser.add_argument("--out", type=Path, default=None, help="Output directory")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.ticker.split(",") if t.strip()]
    as_of = args.as_of or date.today().isoformat()
    out_dir = args.out or DEFAULT_CACHE / as_of
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for tk in tickers:
        csv_path = out_dir / f"{tk}.csv"
        if csv_path.exists() and not args.force:
            logger.info("Already cached: %s", csv_path)
            continue

        logger.info("Fetching contracts for %s as_of=%s", tk, as_of)
        contracts = list_contracts(
            tk,
            as_of=as_of,
            expiration_from=args.expiration_from,
            expiration_to=args.expiration_to,
            expired=args.expired,
        )
        if not contracts:
            logger.warning("No contracts found for %s", tk)
            continue

        # Write CSV
        fieldnames = list(contracts[0].keys())
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(contracts)

        logger.info("%s: %d contracts → %s", tk, len(contracts), csv_path)
        total += len(contracts)

    write_index(out_dir, date.fromisoformat(as_of), total, "contracts")
    logger.info("Total: %d contracts for %d tickers", total, len(tickers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
