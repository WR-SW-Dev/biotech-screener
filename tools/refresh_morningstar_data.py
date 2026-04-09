#!/usr/bin/env python3
"""Refresh pre-fetched Morningstar data files.

Updates the "fetch once, use forever" JSON data files from Morningstar Direct.
Requires morningstar_data SDK and valid MD_AUTH_TOKEN.

Uses batch API calls (all tickers + all datapoints in one request) and maps
the SDK's human-readable column names back to datapoint IDs for compatibility
with the existing morningstar_signal_engine.py format.

Files refreshed:
  production_data/morningstar_mcp_data.json — 26 fundamental datapoints
  production_data/morningstar_price_history.json — vol + return metrics

Usage:
    python tools/refresh_morningstar_data.py
    python tools/refresh_morningstar_data.py --dry-run
    python tools/refresh_morningstar_data.py --only mcp_data
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
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

# Datapoint ID → SDK column name mapping (non-time-series columns)
# The SDK returns human-readable names; we need to map back to IDs.
MCP_COLUMN_MAP = {
    "QV009": "Quantitative Fair Value",
    "ST202": "Morningstar Fair Value Per Share",
    "ST201": "Fair Value Uncertainty",
    "OS603": "Price To Fair Value",
    "ST569": "Below 52 Wk High %",
    "LT181": "Economic Moat",
    "STA4Z": "Return On Invested Capital-TTM",
    "HS08F": "ROE % (TTM) (Long)",
    "ST389": "Long Term Debt To Equity Ratio-FY",
    "HS06U": "Debt to Capital % (trailing) (Long)",
    "HS035": "Equity Style Factor Sales Growth (Long)",
    "HS08D": "Net Margin % (trailing) (Long)",
    "PM006": "Total Ret 3 Mo (Mo-End)",
    "PM008": "Total Ret 6 Mo (Mo-End)",
    "PD00D": "Total Ret 1 Yr (Daily)",
    "PD003": "Total Ret 1 Day (Daily)",
    "PD007": "Total Ret 1 Mo (Daily)",
    "HS05X": "P/E Ratio (TTM) (Long)",
    "HS05U": "P/S Ratio (TTM) (Long)",
    "ST408": "Price To Book Ratio",
    "RR01Y": "Morningstar Rating Overall",
    "ST159": "Market Cap (mil) (Daily)",
    "ST150": "Avg Daily Volume (1 Yr)",
    "ST168": "Price 52 Wk High",
    "ST169": "Price 52 Wk Low",
    "ST263": "Diluted Eps Value-TTM",
}

# Price history / research diagnostic datapoints
PRICE_COLUMN_MAP = {
    "RR015": "Std Dev 3 Yr (Mo-End)",
    "RR016": "Std Dev 5 Yr (Mo-End)",
    "PD00B": "Total Ret YTD (Daily)",
    "PD00F": "Total Ret Annlzd 3 Yr (Daily)",
    "PD00H": "Total Ret Annlzd 5 Yr (Daily)",
}

# Batch size for API calls (SDK handles all tickers at once)
BATCH_SIZE = 50


def _clean_value(val: Any) -> Optional[str]:
    """Convert pandas/numpy values to clean JSON-safe strings."""
    if val is None:
        return None
    try:
        import pandas as pd

        if pd.isna(val):
            return None
    except (ImportError, TypeError, ValueError):
        pass
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val).strip()
    if s in ("", "nan", "NaN", "None", "<NA>"):
        return None
    return s


def load_universe() -> List[str]:
    """Load tickers from universe.json."""
    path = DATA_DIR / "universe.json"
    with open(path) as f:
        universe = json.load(f)
    return [s["ticker"] for s in universe if s.get("ticker") and s["ticker"] != "_XBI_BENCHMARK_"]


def load_id_map() -> Dict[str, str]:
    """Load ticker → Morningstar securityId map.

    The SDK requires Morningstar security IDs (e.g. '0P000005R7'),
    not ticker symbols, to return data.
    """
    path = DATA_DIR / "morningstar_id_map.json"
    if not path.exists():
        logger.warning("morningstar_id_map.json not found — SDK calls will use tickers (may return empty)")
        return {}
    with open(path) as f:
        data = json.load(f)
    return data.get("ticker_to_id", {})


def _atomic_write_json(path: Path, data: Dict) -> None:
    """Write JSON atomically via temp file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_ms_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True, default=str)
        Path(tmp).replace(path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def refresh_mcp_data(tickers: List[str], dry_run: bool = False) -> bool:
    """Refresh morningstar_mcp_data.json with latest fundamental datapoints."""
    try:
        import morningstar_data as md
    except ImportError:
        logger.error("morningstar_data SDK not installed")
        return False

    dp_ids = list(MCP_COLUMN_MAP.keys())
    id_map = load_id_map()
    # Build security ID → ticker reverse map
    id_to_ticker = {v: k for k, v in id_map.items()}
    # Only fetch tickers that have Morningstar IDs
    fetchable = [(t, id_map[t]) for t in tickers if t in id_map]
    skipped = [t for t in tickers if t not in id_map]

    logger.info(
        "Refreshing MCP data: %d tickers (%d have MS IDs, %d skipped), %d datapoints...",
        len(tickers),
        len(fetchable),
        len(skipped),
        len(dp_ids),
    )

    if dry_run:
        logger.info(
            "[DRY RUN] Would fetch %d tickers x %d datapoints in batches of %d", len(fetchable), len(dp_ids), BATCH_SIZE
        )
        return True

    # Reverse map: column name → datapoint ID
    col_to_id = {v: k for k, v in MCP_COLUMN_MAP.items()}

    records: Dict[str, Dict[str, Any]] = {}

    # Batch by security IDs
    for batch_start in range(0, len(fetchable), BATCH_SIZE):
        batch = fetchable[batch_start : batch_start + BATCH_SIZE]
        batch_ids = [sec_id for _, sec_id in batch]
        logger.info("  Batch %d-%d / %d ...", batch_start + 1, batch_start + len(batch), len(fetchable))

        try:
            result = md.direct.get_investment_data(
                investments=batch_ids,
                data_points=[{"datapointId": dp} for dp in dp_ids],
            )
            if result is None or result.empty:
                logger.warning("  Batch returned empty")
                continue

            # Map each row back to ticker → {datapointId: value}
            for _, row in result.iterrows():
                sec_id = str(row.get("Id", "")).strip()
                ticker = id_to_ticker.get(sec_id, sec_id)
                if not ticker:
                    continue
                record: Dict[str, Optional[str]] = {}
                for col in result.columns:
                    if col in ("Id", "Name"):
                        continue
                    if "display text" in col:
                        continue
                    # Skip time-series dated columns
                    if any(str(y) in col for y in range(2020, 2030)):
                        continue

                    dp_id = col_to_id.get(col)
                    if dp_id:
                        record[dp_id] = _clean_value(row[col])

                if any(v is not None for v in record.values()):
                    records[ticker] = record

        except Exception as exc:
            logger.warning("  Batch %d-%d failed: %s", batch_start + 1, batch_start + len(batch), exc)

    output = {
        "metadata": {
            "pull_date": date.today().isoformat(),
            "source": "Morningstar Direct SDK (refresh_morningstar_data.py)",
            "tickers_total": len(records),
            "tickers_requested": len(tickers),
            "tickers_with_data": sum(1 for r in records.values() if any(v is not None for v in r.values())),
            "datapoint_count": len(dp_ids),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "datapoint_catalog": {k: v for k, v in MCP_COLUMN_MAP.items()},
        },
        "records": records,
    }

    out_path = DATA_DIR / "morningstar_mcp_data.json"
    _atomic_write_json(out_path, output)
    logger.info(
        "Wrote %s (%d tickers, %d with data)", out_path.name, len(records), output["metadata"]["tickers_with_data"]
    )
    return True


def refresh_price_metrics(tickers: List[str], dry_run: bool = False) -> bool:
    """Refresh price-derived metrics (vol, annualized returns) in morningstar_price_history.json."""
    try:
        import morningstar_data as md
    except ImportError:
        logger.error("morningstar_data SDK not installed")
        return False

    dp_ids = list(PRICE_COLUMN_MAP.keys())
    id_map = load_id_map()
    id_to_ticker = {v: k for k, v in id_map.items()}
    fetchable = [(t, id_map[t]) for t in tickers if t in id_map]

    logger.info(
        "Refreshing price metrics: %d tickers (%d with MS IDs), %d datapoints...",
        len(tickers),
        len(fetchable),
        len(dp_ids),
    )

    if dry_run:
        logger.info("[DRY RUN] Would fetch %d tickers x %d datapoints", len(fetchable), len(dp_ids))
        return True

    col_to_id = {v: k for k, v in PRICE_COLUMN_MAP.items()}
    records: Dict[str, Dict[str, Any]] = {}

    for batch_start in range(0, len(fetchable), BATCH_SIZE):
        batch = fetchable[batch_start : batch_start + BATCH_SIZE]
        batch_ids = [sec_id for _, sec_id in batch]
        logger.info("  Batch %d-%d / %d ...", batch_start + 1, batch_start + len(batch), len(fetchable))

        try:
            result = md.direct.get_investment_data(
                investments=batch_ids,
                data_points=[{"datapointId": dp} for dp in dp_ids],
            )
            if result is None or result.empty:
                continue

            for _, row in result.iterrows():
                sec_id = str(row.get("Id", "")).strip()
                ticker = id_to_ticker.get(sec_id, sec_id)
                if not ticker:
                    continue
                record: Dict[str, Optional[str]] = {}
                for col in result.columns:
                    if col in ("Id", "Name") or "display text" in col:
                        continue
                    if any(str(y) in col for y in range(2020, 2030)):
                        continue
                    dp_id = col_to_id.get(col)
                    if dp_id:
                        record[dp_id] = _clean_value(row[col])
                if any(v is not None for v in record.values()):
                    records[ticker] = record

        except Exception as exc:
            logger.warning("  Batch failed: %s", exc)

    # Merge into existing price_history.json (preserve HS377 time series)
    existing_path = DATA_DIR / "morningstar_price_history.json"
    existing: Dict[str, Any] = {}
    if existing_path.exists():
        try:
            with open(existing_path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    existing_records = existing.get("records", {})
    for ticker, new_data in records.items():
        if ticker in existing_records:
            existing_records[ticker].update(new_data)
        else:
            existing_records[ticker] = new_data

    output = existing
    output["records"] = existing_records
    output.setdefault("metadata", {})
    output["metadata"]["price_metrics_refreshed_at"] = datetime.now(timezone.utc).isoformat()
    output["metadata"]["price_metrics_tickers"] = len(records)

    _atomic_write_json(existing_path, output)
    logger.info("Wrote %s (%d tickers updated)", existing_path.name, len(records))
    return True


def main():
    parser = argparse.ArgumentParser(description="Refresh Morningstar pre-fetched data files")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", choices=["mcp_data", "price_metrics"])
    args = parser.parse_args()

    tickers = load_universe()
    logger.info("Universe: %d tickers", len(tickers))

    if args.only is None or args.only == "mcp_data":
        refresh_mcp_data(tickers, dry_run=args.dry_run)

    if args.only is None or args.only == "price_metrics":
        refresh_price_metrics(tickers, dry_run=args.dry_run)

    logger.info("Done.")


if __name__ == "__main__":
    main()
