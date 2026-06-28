#!/usr/bin/env python3
"""Portfolio IV snapshot collector — Tastytrade-based.

Fetches options diagnostics (ATM IV, term slope, put/call skew, greeks)
for the held portfolio positions and writes a dated artifact.

Diagnostic output only — does NOT affect rankings, sizing, or execution.

Requires:
    TT_SECRET   — tastytrade OAuth provider secret
    TT_REFRESH  — tastytrade refresh token
    (set in repo .env or environment)

Inputs (in priority order):
    --tickers A,B,C        explicit comma-separated list
    --positions-file PATH  JSON file from Robinhood positions export
    (no arg)               reads latest positions.json from artifacts/live_shadow/

Output:
    artifacts/portfolio_iv/{date}_portfolio_iv_snapshot.json

Usage:
    python tools/collect_portfolio_iv.py --as-of-date 2026-06-27
    python tools/collect_portfolio_iv.py --as-of-date 2026-06-27 --tickers ARWR,RVMD,NRIX,PRAX
    python tools/collect_portfolio_iv.py --as-of-date 2026-06-27 --positions-file /path/to/positions.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("collect_portfolio_iv")

ARTIFACT_DIR = REPO_ROOT / "artifacts" / "portfolio_iv"
SCHEMA_VERSION = "portfolio_iv.v1"

# Known liquid names from prior session testing (OI > 10 on at least one side)
_KNOWN_LIQUID = {"ARWR", "RVMD", "NRIX", "PRAX", "NBIX", "ALKS", "ARWR", "MIRM", "RYTM"}


def _load_tickers_from_positions_file(path: Path) -> list[str]:
    """Parse a Robinhood positions JSON file → list of tickers."""
    with open(path) as f:
        data = json.load(f)
    positions = data.get("data", {}).get("positions", data.get("positions", []))
    return [p["symbol"] for p in positions if p.get("symbol")]


def _find_latest_positions_file() -> Path | None:
    """Search standard artifact locations for a positions JSON."""
    candidates = sorted((REPO_ROOT / "artifacts" / "live_shadow" / "positions").glob("*.json"))
    return candidates[-1] if candidates else None


def _resolve_tickers(args: argparse.Namespace) -> list[str]:
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        logger.info("Using %d tickers from --tickers arg", len(tickers))
        return tickers

    if args.positions_file:
        path = Path(args.positions_file)
        tickers = _load_tickers_from_positions_file(path)
        logger.info("Loaded %d tickers from %s", len(tickers), path)
        return tickers

    latest = _find_latest_positions_file()
    if latest:
        tickers = _load_tickers_from_positions_file(latest)
        logger.info("Loaded %d tickers from %s", len(tickers), latest)
        return tickers

    logger.warning("No tickers source found — falling back to known liquid set")
    return sorted(_KNOWN_LIQUID)


def _build_artifact(
    as_of_date: str,
    diagnostics: dict,
    tickers: list[str],
) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for symbol in sorted(diagnostics):
        d = diagnostics[symbol]
        rows.append(
            {
                "symbol": symbol,
                "opt_has_data": d.get("opt_has_data", "0"),
                "opt_atm_iv": d.get("opt_atm_iv", ""),
                "opt_front_iv": d.get("opt_front_iv", ""),
                "opt_back_iv": d.get("opt_back_iv", ""),
                "opt_term_slope": d.get("opt_term_slope", ""),
                "opt_put_call_skew": d.get("opt_put_call_skew", ""),
                "opt_nearest_expiry": d.get("opt_nearest_expiry", ""),
                "opt_dte": d.get("opt_dte", ""),
                "opt_iv_regime": d.get("opt_iv_regime", ""),
                "opt_event_premium": d.get("opt_event_premium", ""),
                "opt_liquidity_state": d.get("opt_liquidity_state", "absent"),
                "opt_use_for_judgment": d.get("opt_use_for_judgment", ""),
                "opt_quote_ts": d.get("opt_quote_ts", ""),
                "opt_diagnostic_basis": d.get("opt_diagnostic_basis", ""),
            }
        )

    payload = json.dumps(rows, sort_keys=True).encode()
    content_hash = hashlib.sha256(payload).hexdigest()[:16]

    return {
        "schema": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "generated_at": generated_at,
        "n_tickers": len(tickers),
        "n_with_data": sum(1 for r in rows if r["opt_has_data"] == "1"),
        "n_liquid": sum(1 for r in rows if r["opt_liquidity_state"] == "liquid"),
        "content_hash": content_hash,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect portfolio IV snapshot via Tastytrade")
    parser.add_argument("--as-of-date", required=True, help="YYYY-MM-DD evaluation date")
    parser.add_argument("--tickers", help="Comma-separated ticker list (overrides auto-detect)")
    parser.add_argument("--positions-file", help="Path to Robinhood positions JSON export")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not write artifact")
    args = parser.parse_args()

    # Validate date
    try:
        date.fromisoformat(args.as_of_date)
    except ValueError:
        logger.error("Invalid --as-of-date: %s", args.as_of_date)
        return 1

    tickers = _resolve_tickers(args)
    if not tickers:
        logger.error("No tickers resolved — aborting")
        return 1

    logger.info("Fetching options diagnostics for %d tickers: %s", len(tickers), tickers)

    from common.options_diagnostics import _has_credentials, fetch_options_diagnostics

    if not _has_credentials():
        logger.error("TT_SECRET / TT_REFRESH not set — cannot fetch options data")
        return 1

    diagnostics = fetch_options_diagnostics(tickers, args.as_of_date)

    # Summary log
    n_ok = sum(1 for d in diagnostics.values() if d.get("opt_has_data") == "1")
    n_liquid = sum(1 for d in diagnostics.values() if d.get("opt_liquidity_state") == "liquid")
    logger.info("Results: %d/%d with data, %d liquid", n_ok, len(tickers), n_liquid)

    for sym, d in sorted(diagnostics.items()):
        if d.get("opt_has_data") == "1":
            logger.info(
                "  %-6s  IV=%.0f%%  regime=%-8s  liquidity=%-7s  term_slope=%s",
                sym,
                float(d.get("opt_atm_iv") or 0) * 100,
                d.get("opt_iv_regime", ""),
                d.get("opt_liquidity_state", ""),
                d.get("opt_term_slope", ""),
            )

    artifact = _build_artifact(args.as_of_date, diagnostics, tickers)

    if args.dry_run:
        logger.info("--dry-run: artifact not written")
        print(json.dumps(artifact, indent=2))
        return 0

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACT_DIR / f"{args.as_of_date}_portfolio_iv_snapshot.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
        f.write("\n")

    logger.info("Wrote %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
