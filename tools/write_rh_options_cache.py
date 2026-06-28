#!/usr/bin/env python3
"""Write RH options cache file from pre-fetched Robinhood MCP data.

Called during Claude sessions after fetching options data via Robinhood MCP
tools (get_option_chains / get_option_instruments / get_option_quotes).

The cache file is later read by collect_options_shadow.py in TT-only pipeline
mode to enrich the shadow artifact with contract-level greeks and liquidity.

Schema written: rh_quotes_cache.v1

Usage (from Python — typical use in a skill or interactive session):

    from tools.write_rh_options_cache import write_rh_cache

    tickers_data = {
        "ARWR": {
            "underlying_price": 79.04,
            "nearest_expiry": "2026-07-17",
            "atm_strike": 80.0,
            "call": {
                "implied_volatility": 0.573,
                "delta": 0.496,
                "gamma": 0.038,
                "theta": -0.110,
                "vega": 0.073,
                "open_interest": 526,
                "volume": 105,
                "bid": 2.65,
                "ask": 5.00,
                "mark": 3.83,
            },
            "put": {
                "implied_volatility": 0.615,
                "delta": -0.500,
                "gamma": 0.035,
                "theta": -0.110,
                "vega": 0.073,
                "open_interest": 441,
                "volume": 5,
                "bid": 3.90,
                "ask": 6.00,
                "mark": 4.95,
            },
        },
        # ... more tickers
    }

    path = write_rh_cache("2026-06-27", tickers_data)
    print(f"Wrote {path}")

Usage (CLI):

    python tools/write_rh_options_cache.py --as-of-date 2026-06-27 --data '{"ARWR": {...}}'
    python tools/write_rh_options_cache.py --as-of-date 2026-06-27 --data-file /tmp/rh_raw.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "options_shadow"
SCHEMA_VERSION = "rh_quotes_cache.v1"

_REQUIRED_SIDE_FIELDS = {"implied_volatility", "bid", "ask", "open_interest"}


def _validate_ticker(symbol: str, data: Dict[str, Any]) -> list[str]:
    """Return list of validation warnings for one ticker entry."""
    warnings = []
    for side in ("call", "put"):
        if side not in data:
            warnings.append(f"{symbol}.{side} missing")
            continue
        for f in _REQUIRED_SIDE_FIELDS:
            if f not in data[side]:
                warnings.append(f"{symbol}.{side}.{f} missing")
    if "underlying_price" not in data:
        warnings.append(f"{symbol}.underlying_price missing")
    return warnings


def write_rh_cache(
    as_of_date: str,
    tickers: Dict[str, Dict[str, Any]],
    out_dir: Optional[Path] = None,
    validate: bool = True,
) -> Path:
    """Serialize RH MCP data to the standard cache file.

    Args:
        as_of_date: YYYY-MM-DD string (market date of the quotes)
        tickers: dict of {SYMBOL: {underlying_price, nearest_expiry, atm_strike,
                                    call: {...}, put: {...}}}
        out_dir: override output directory (default: artifacts/options_shadow)
        validate: if True, warn on missing fields but do not raise

    Returns:
        Path to the written cache file.
    """
    if out_dir is None:
        out_dir = ARTIFACT_DIR

    if validate:
        all_warnings = []
        for sym, data in tickers.items():
            all_warnings.extend(_validate_ticker(sym, data))
        for w in all_warnings:
            import logging

            logging.getLogger("write_rh_options_cache").warning("Validation: %s", w)

    payload = {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(tickers),
        "tickers": tickers,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{as_of_date}_rh_quotes_cache.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
        f.write("\n")

    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Write RH options cache file")
    parser.add_argument("--as-of-date", required=True, help="YYYY-MM-DD market date")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--data", help="JSON string of ticker data")
    grp.add_argument("--data-file", help="Path to JSON file of ticker data")
    parser.add_argument("--out-dir", help="Output directory (default: artifacts/options_shadow)")
    parser.add_argument("--no-validate", action="store_true", help="Skip field validation")
    args = parser.parse_args()

    if args.data:
        tickers = json.loads(args.data)
    else:
        with open(args.data_file) as f:
            tickers = json.load(f)

    out_dir = Path(args.out_dir) if args.out_dir else None
    path = write_rh_cache(args.as_of_date, tickers, out_dir=out_dir, validate=not args.no_validate)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
