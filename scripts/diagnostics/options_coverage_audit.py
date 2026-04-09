#!/usr/bin/env python3
"""Options coverage audit -- identify realistic ceiling for coverage push.

Read-only diagnostic: checks which absent tickers might have options chains
available through Polygon/Massive.

Usage:
    python scripts/diagnostics/options_coverage_audit.py --mode offline
    python scripts/diagnostics/options_coverage_audit.py --mode online  # calls Polygon API
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
UNIVERSE_PATH = PROJECT_ROOT / "production_data" / "universe.json"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "diagnostics"

logger = logging.getLogger(__name__)


def find_latest_snapshot_dir(snapshots_dir: Path) -> Path | None:
    """Find the most recent date-stamped snapshot directory."""
    candidates = []
    for d in snapshots_dir.iterdir():
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-":
            candidates.append(d)
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.name)


def load_diagnostics_summary(snapshot_dir: Path) -> dict:
    """Load options_diagnostics_summary.json from a snapshot."""
    path = snapshot_dir / "options_diagnostics_summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def identify_absent_tickers(snapshot_dir: Path, universe: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Classify tickers by reading rankings.csv for opt_has_data.

    Returns (has_data, absent, no_liquid_expiry).
    """
    import csv as _csv

    rankings_path = snapshot_dir / "rankings.csv"
    if not rankings_path.exists():
        logger.warning("No rankings.csv in %s", snapshot_dir)
        return [], list(universe), []

    has_data: list[str] = []
    absent: list[str] = []
    no_liquid: list[str] = []
    seen: set[str] = set()

    with open(rankings_path) as f:
        for row in _csv.DictReader(f):
            tk = row.get("ticker", "").strip()
            if not tk or tk in seen:
                continue
            seen.add(tk)
            if str(row.get("opt_has_data", "0")) == "1":
                has_data.append(tk)
            elif row.get("opt_diagnostic_basis", "") == "no_liquid_expiry":
                no_liquid.append(tk)
            else:
                absent.append(tk)

    for tk in universe:
        if tk not in seen:
            absent.append(tk)

    return has_data, absent, no_liquid


def check_polygon_coverage(tickers: list[str], rate_limit_sec: float = 1.0) -> dict[str, str]:
    """Check Polygon for chain existence. Returns {ticker: classification}."""
    results = {}
    try:
        from common.options_history_massive import list_contracts
    except ImportError:
        logger.warning("Cannot import options_history_massive -- marking all as check_failed")
        return {tk: "check_failed" for tk in tickers}

    import time

    for tk in tickers:
        try:
            contracts = list_contracts(tk)
            if not contracts:
                results[tk] = "no_chain_anywhere"
            else:
                # Check if any are active (not expired)
                today = date.today().isoformat()
                active = [c for c in contracts if c.get("expiration_date", "") >= today]
                if active:
                    results[tk] = "has_polygon_chain"
                else:
                    results[tk] = "expired_only"
        except Exception as e:
            logger.warning("Polygon check failed for %s: %s", tk, e)
            results[tk] = "check_failed"

        time.sleep(rate_limit_sec)

    return results


def build_report(
    universe: list[str],
    summary: dict,
    has_data: list[str],
    absent: list[str],
    no_liquid: list[str],
    polygon_results: dict[str, str] | None,
    as_of_date: str,
) -> dict[str, Any]:
    """Build the full audit report."""
    n_universe = len(universe)
    n_has_data = len(has_data)
    n_absent = len(absent)
    n_no_liquid = len(no_liquid)

    report: dict[str, Any] = {
        "schema": "options_coverage_audit.v1",
        "as_of_date": as_of_date,
        "n_universe": n_universe,
        "n_with_tt_data": n_has_data,
        "n_absent": n_absent,
        "n_no_liquid_expiry": n_no_liquid,
        "coverage_pct_current": round(n_has_data / max(n_universe, 1) * 100, 1),
        "absent_tickers": sorted(absent),
        "no_liquid_expiry_tickers": sorted(no_liquid),
    }

    if polygon_results:
        has_chain = [t for t, v in polygon_results.items() if v == "has_polygon_chain"]
        no_chain = [t for t, v in polygon_results.items() if v == "no_chain_anywhere"]
        expired = [t for t, v in polygon_results.items() if v == "expired_only"]
        failed = [t for t, v in polygon_results.items() if v == "check_failed"]

        ceiling = n_has_data + len(has_chain) + n_no_liquid
        report["polygon_check"] = {
            "n_has_polygon_chain": len(has_chain),
            "n_no_chain_anywhere": len(no_chain),
            "n_expired_only": len(expired),
            "n_check_failed": len(failed),
            "has_polygon_chain_tickers": sorted(has_chain),
            "no_chain_anywhere_tickers": sorted(no_chain),
            "expired_only_tickers": sorted(expired),
        }
        report["realistic_ceiling"] = ceiling
        report["realistic_ceiling_pct"] = round(ceiling / max(n_universe, 1) * 100, 1)
    else:
        report["polygon_check"] = None
        report["realistic_ceiling"] = None
        report["realistic_ceiling_pct"] = None

    return report


def main():
    parser = argparse.ArgumentParser(description="Options coverage audit")
    parser.add_argument(
        "--mode",
        choices=["offline", "online"],
        default="offline",
        help="offline=report absent tickers; online=check Polygon for chains",
    )
    parser.add_argument("--snapshots-dir", type=Path, default=SNAPSHOTS_DIR)
    parser.add_argument("--universe-path", type=Path, default=UNIVERSE_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Load universe
    if not args.universe_path.exists():
        logger.error("Universe file not found: %s", args.universe_path)
        sys.exit(1)
    raw = json.loads(args.universe_path.read_text())
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        universe = [r.get("ticker", r.get("name", "")) for r in raw if r.get("ticker") or r.get("name")]
    elif isinstance(raw, dict):
        universe = raw.get("tickers", list(raw.keys()))
    else:
        universe = raw
    logger.info("Universe: %d tickers", len(universe))

    # Find latest snapshot
    snap_dir = find_latest_snapshot_dir(args.snapshots_dir)
    if not snap_dir:
        logger.error("No snapshot directories found in %s", args.snapshots_dir)
        sys.exit(1)
    logger.info("Using snapshot: %s", snap_dir.name)

    summary = load_diagnostics_summary(snap_dir)

    has_data, absent, no_liquid = identify_absent_tickers(snap_dir, universe)
    logger.info(
        "Coverage: %d with data, %d absent, %d no liquid expiry",
        len(has_data),
        len(absent),
        len(no_liquid),
    )

    polygon_results = None
    if args.mode == "online" and absent:
        logger.info("Checking Polygon for %d absent tickers...", len(absent))
        polygon_results = check_polygon_coverage(absent)

    report = build_report(universe, summary, has_data, absent, no_liquid, polygon_results, args.as_of_date)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"options_coverage_audit_{args.as_of_date}.json"
    out_path.write_text(json.dumps(report, indent=2))

    print(f"\nOPTIONS COVERAGE AUDIT -- {args.as_of_date}")
    print(f"  Universe: {report['n_universe']}")
    print(f"  With TT data: {report['n_with_tt_data']} ({report['coverage_pct_current']:.1f}%)")
    print(f"  Absent: {report['n_absent']}")
    print(f"  No liquid expiry: {report['n_no_liquid_expiry']}")
    if report["realistic_ceiling"] is not None:
        print(f"  Realistic ceiling: {report['realistic_ceiling']} ({report['realistic_ceiling_pct']:.1f}%)")
        pc = report["polygon_check"]
        print(f"    Has Polygon chain: {pc['n_has_polygon_chain']}")
        print(f"    No chain anywhere: {pc['n_no_chain_anywhere']}")
        print(f"    Expired only: {pc['n_expired_only']}")
    print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
