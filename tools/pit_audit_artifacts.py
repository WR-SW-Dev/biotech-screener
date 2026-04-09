#!/usr/bin/env python3
"""Generate PIT audit artifacts for output/pit/.

Two artifacts:
  1. survivorship_audit_YYYY-MM-DD.json — IPO/delist violations in snapshots
  2. financials_pit_coverage_YYYY-MM-DD.json — PIT financials coverage report

These are lightweight wrappers that call existing infrastructure and write
structured output to the spec-048 artifact directory.

Usage:
    python tools/pit_audit_artifacts.py --as-of-date 2026-04-02
    python tools/pit_audit_artifacts.py --as-of-date 2026-04-02 --audit survivorship
    python tools/pit_audit_artifacts.py --as-of-date 2026-04-02 --audit financials
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

PROD_DATA = PROJECT_ROOT / "production_data"
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PIT_FIN_DIR = PROD_DATA / "pit_financials"
PIT_OUTPUT = PROJECT_ROOT / "output" / "pit"
IPO_DATES_PATH = PROD_DATA / "ipo_dates.json"


def generate_survivorship_audit(as_of_date: str) -> dict:
    """Check all snapshots up to as_of_date for survivorship violations."""
    if not IPO_DATES_PATH.exists():
        return {"error": "ipo_dates.json not found", "violations": 0}

    with open(IPO_DATES_PATH) as f:
        raw = json.load(f)
    # Format: {tickers: {TICKER: {first_price_date, last_price_date}}}
    ipo_dates = {t: v.get("first_price_date", "") for t, v in raw.get("tickers", {}).items()}

    # Scan snapshots
    violations = []
    snapshots_checked = 0
    snapshots_clean = 0

    if not SNAPSHOTS_DIR.exists():
        return {"error": "snapshots directory not found", "violations": 0}

    import csv

    for snap_dir in sorted(SNAPSHOTS_DIR.iterdir()):
        if not snap_dir.is_dir() or snap_dir.name > as_of_date:
            continue
        rankings_path = snap_dir / "rankings.csv"
        if not rankings_path.exists():
            continue

        snapshots_checked += 1
        snap_violations = []

        with open(rankings_path) as f:
            for row in csv.DictReader(f):
                ticker = row.get("ticker", "").strip()
                if not ticker or ticker not in ipo_dates:
                    continue
                ipo = ipo_dates[ticker]
                if ipo > snap_dir.name:
                    snap_violations.append(
                        {
                            "ticker": ticker,
                            "ipo_date": ipo,
                            "snapshot_date": snap_dir.name,
                            "days_ahead": (date.fromisoformat(ipo) - date.fromisoformat(snap_dir.name)).days,
                        }
                    )

        if snap_violations:
            violations.extend(snap_violations)
        else:
            snapshots_clean += 1

    contaminated = snapshots_checked - snapshots_clean
    return {
        "audit_type": "survivorship",
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshots_checked": snapshots_checked,
        "snapshots_clean": snapshots_clean,
        "snapshots_contaminated": contaminated,
        "contamination_rate": round(contaminated / max(snapshots_checked, 1), 4),
        "total_ipo_violations": len(violations),
        "unique_tickers_violating": len(set(v["ticker"] for v in violations)),
        "worst_offenders": _worst_offenders(violations),
        "verdict": "CLEAN" if len(violations) == 0 else "CONTAMINATED",
        "violations_sample": violations[:100],
    }


def _worst_offenders(violations: list[dict], top_n: int = 20) -> list[dict]:
    """Top tickers by violation count."""
    counts: dict[str, int] = {}
    for v in violations:
        counts[v["ticker"]] = counts.get(v["ticker"], 0) + 1
    return [{"ticker": t, "violation_count": c} for t, c in sorted(counts.items(), key=lambda x: -x[1])[:top_n]]


def generate_financials_coverage(as_of_date: str) -> dict:
    """Report PIT financials coverage across the universe."""
    if not PIT_FIN_DIR.is_dir():
        return {
            "audit_type": "financials_pit_coverage",
            "error": "pit_financials/ directory not found",
            "coverage_pct": 0,
        }

    # Load universe
    universe_path = PROD_DATA / "universe.json"
    if not universe_path.exists():
        return {"error": "universe.json not found"}

    with open(universe_path) as f:
        universe = json.load(f)

    if isinstance(universe, list):
        # List of dicts with "ticker" key
        tickers = [entry["ticker"] if isinstance(entry, dict) else str(entry) for entry in universe]
    else:
        tickers = list(universe.keys())

    # Check coverage
    has_pit = 0
    has_filing_before_aod = 0
    missing = []
    coverage_details = []

    for ticker in sorted(tickers):
        pit_path = PIT_FIN_DIR / f"{ticker}.json"
        if not pit_path.exists():
            missing.append(ticker)
            continue

        has_pit += 1
        try:
            with open(pit_path) as f:
                pit_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            missing.append(ticker)
            continue

        # Check if any filing exists on or before as_of_date
        # Structure: {ticker, cik, collected_at, facts: {field: [{filed, val, ...}, ...]}}
        facts = pit_data.get("facts", {})
        if not isinstance(facts, dict):
            facts = pit_data  # fallback: maybe flat structure
        filings_before = []
        for field_name, entries in facts.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                filed = entry.get("filed", "")
                if filed and filed <= as_of_date:
                    filings_before.append(filed)

        if filings_before:
            has_filing_before_aod += 1
            coverage_details.append(
                {
                    "ticker": ticker,
                    "n_filings_before_aod": len(filings_before),
                    "latest_filing": max(filings_before),
                }
            )

    n_universe = len(tickers)
    return {
        "audit_type": "financials_pit_coverage",
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "universe_size": n_universe,
        "tickers_with_pit_file": has_pit,
        "tickers_with_filing_before_aod": has_filing_before_aod,
        "tickers_missing_pit": len(missing),
        "coverage_pct": round(100 * has_pit / max(n_universe, 1), 1),
        "effective_coverage_pct": round(100 * has_filing_before_aod / max(n_universe, 1), 1),
        "missing_tickers": missing,
        "coverage_sample": coverage_details[:50],
    }


def main():
    parser = argparse.ArgumentParser(description="Generate PIT audit artifacts")
    parser.add_argument("--as-of-date", required=True, help="Audit date (YYYY-MM-DD)")
    parser.add_argument(
        "--audit",
        nargs="+",
        default=["all"],
        choices=["all", "survivorship", "financials"],
        help="Which audits to run",
    )
    args = parser.parse_args()

    PIT_OUTPUT.mkdir(parents=True, exist_ok=True)
    run_all = "all" in args.audit

    if run_all or "survivorship" in args.audit:
        print("Running survivorship audit...")
        result = generate_survivorship_audit(args.as_of_date)
        out_path = PIT_OUTPUT / f"survivorship_audit_{args.as_of_date}.json"
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"  Verdict: {result.get('verdict', '?')}")
        print(f"  Violations: {result.get('total_ipo_violations', '?')}")
        print(f"  Written: {out_path}")

    if run_all or "financials" in args.audit:
        print("Running PIT financials coverage audit...")
        result = generate_financials_coverage(args.as_of_date)
        out_path = PIT_OUTPUT / f"financials_pit_coverage_{args.as_of_date}.json"
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"  Coverage: {result.get('coverage_pct', '?')}%")
        print(f"  Effective: {result.get('effective_coverage_pct', '?')}%")
        print(f"  Written: {out_path}")


if __name__ == "__main__":
    main()
