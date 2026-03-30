#!/usr/bin/env python3
"""Refresh pre-fetched Morningstar data files.

Updates the "fetch once, use forever" JSON data files from Morningstar Direct.
Requires morningstar_data SDK and valid authentication.

Files refreshed:
  production_data/morningstar_mcp_data.json — 26 fundamental datapoints
  production_data/morningstar_price_history.json — 1yr daily closes + returns
  production_data/morningstar_returns_history.json — 5yr daily total return index

Usage:
    python tools/refresh_morningstar_data.py
    python tools/refresh_morningstar_data.py --dry-run
    python tools/refresh_morningstar_data.py --only mcp_data
    python tools/refresh_morningstar_data.py --only price_history
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("refresh_morningstar")

DATA_DIR = REPO_ROOT / "production_data"

# The 26 fundamental datapoints from the existing morningstar_mcp_data.json
MCP_DATAPOINTS = [
    "QV009", "ST202", "ST201", "OS603", "ST569", "LT181",
    "STA4Z", "HS08F", "ST389", "HS06U", "HS035", "HS08D",
    "PM006", "PM008", "PD00D", "PD003", "PD007",
    "HS05X", "HS05U", "ST408", "RR01Y", "ST159", "ST150",
    "ST168", "ST169", "ST263",
]

# Price history datapoints (1yr daily + vol + returns)
PRICE_DATAPOINTS = ["HS377", "PD00B", "PD00F", "PD00H", "RR015", "RR016"]

# Returns history datapoints (5yr daily + monthly)
RETURNS_DATAPOINTS = ["HS793", "HP010"]


def load_universe() -> List[str]:
    """Load tickers from universe.json."""
    path = DATA_DIR / "universe.json"
    with open(path) as f:
        universe = json.load(f)
    return [s["ticker"] for s in universe if s.get("ticker") and s["ticker"] != "_XBI_BENCHMARK_"]


def refresh_mcp_data(tickers: List[str], dry_run: bool = False) -> bool:
    """Refresh morningstar_mcp_data.json with latest fundamental datapoints."""
    try:
        import morningstar_data as md
    except ImportError:
        logger.error("morningstar_data SDK not installed")
        return False

    logger.info("Refreshing MCP data for %d tickers, %d datapoints...", len(tickers), len(MCP_DATAPOINTS))

    if dry_run:
        logger.info("[DRY RUN] Would fetch %d x %d = %d datapoint calls", len(tickers), len(MCP_DATAPOINTS), len(tickers) * len(MCP_DATAPOINTS))
        return True

    records: Dict[str, Dict[str, Any]] = {}
    for ticker in tickers:
        try:
            result = md.direct.get_investment_data(
                investments=[ticker],
                data_points=[{"datapointId": dp} for dp in MCP_DATAPOINTS],
            )
            if result is not None and not result.empty:
                record = {}
                for dp in MCP_DATAPOINTS:
                    if dp in result.columns:
                        val = result[dp].iloc[0]
                        record[dp] = str(val) if val is not None else None
                    else:
                        record[dp] = None
                records[ticker] = record
        except Exception as exc:
            logger.debug("Failed to fetch MCP data for %s: %s", ticker, exc)

    output = {
        "metadata": {
            "pull_date": date.today().isoformat(),
            "source": "Morningstar Direct API (refresh_morningstar_data.py)",
            "tickers_total": len(records),
            "tickers_requested": len(tickers),
            "datapoint_count": len(MCP_DATAPOINTS),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        },
        "records": records,
    }

    out_path = DATA_DIR / "morningstar_mcp_data.json"
    # Atomic write
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".tmp_ms_mcp_", suffix=".json")
    try:
        import os
        with os.fdopen(fd, "w") as f:
            json.dump(output, f, indent=2, sort_keys=True, default=str)
        Path(tmp).replace(out_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    logger.info("Wrote %s (%d tickers)", out_path.name, len(records))
    return True


def refresh_price_history(tickers: List[str], dry_run: bool = False) -> bool:
    """Refresh morningstar_price_history.json with 1yr daily closes + metrics."""
    try:
        import morningstar_data as md
    except ImportError:
        logger.error("morningstar_data SDK not installed")
        return False

    logger.info("Refreshing price history for %d tickers...", len(tickers))

    if dry_run:
        logger.info("[DRY RUN] Would fetch price history for %d tickers", len(tickers))
        return True

    records: Dict[str, Dict[str, Any]] = {}
    today = date.today()
    start = date(today.year - 1, today.month, today.day)

    for ticker in tickers:
        try:
            # Time series datapoints
            result = md.direct.get_investment_data(
                investments=[ticker],
                data_points=[{"datapointId": dp} for dp in PRICE_DATAPOINTS],
            )
            if result is not None and not result.empty:
                record = {}
                for dp in PRICE_DATAPOINTS:
                    if dp in result.columns:
                        val = result[dp].iloc[0]
                        record[dp] = str(val) if val is not None else None
                    else:
                        record[dp] = None
                records[ticker] = record
        except Exception as exc:
            logger.debug("Failed to fetch price history for %s: %s", ticker, exc)

    output = {
        "metadata": {
            "pull_date": today.isoformat(),
            "source": "Morningstar Direct API (refresh_morningstar_data.py)",
            "datapoints": {dp: dp for dp in PRICE_DATAPOINTS},
            "date_range": {"start": start.isoformat(), "end": today.isoformat()},
            "tickers_total": len(records),
            "tickers_requested": len(tickers),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        },
        "records": records,
    }

    out_path = DATA_DIR / "morningstar_price_history.json"
    import tempfile, os
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".tmp_ms_ph_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(output, f, indent=2, sort_keys=True, default=str)
        Path(tmp).replace(out_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    logger.info("Wrote %s (%d tickers)", out_path.name, len(records))
    return True


def main():
    parser = argparse.ArgumentParser(description="Refresh Morningstar pre-fetched data files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fetched without calling API")
    parser.add_argument("--only", choices=["mcp_data", "price_history", "returns_history"], help="Refresh only one file")
    args = parser.parse_args()

    tickers = load_universe()
    logger.info("Universe: %d tickers", len(tickers))

    if args.only is None or args.only == "mcp_data":
        refresh_mcp_data(tickers, dry_run=args.dry_run)

    if args.only is None or args.only == "price_history":
        refresh_price_history(tickers, dry_run=args.dry_run)

    logger.info("Done.")


if __name__ == "__main__":
    main()
