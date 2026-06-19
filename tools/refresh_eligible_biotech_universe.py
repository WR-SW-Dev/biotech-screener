#!/usr/bin/env python3
"""Refresh universe coverage status for active biotech tickers.

This is a data-quality refresh: tickers that lack local market/company/clinical
coverage are marked pending_data_collection instead of remaining silently active.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERIC_COMPANY_NAMES = {"healthcare", "biotechnology", "biotech", "unknown"}


def _ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or "").strip().upper()


def _is_active_status(row: dict[str, Any]) -> bool:
    return str(row.get("status", "active") or "active").strip().lower() in {"", "active"}


def _is_biotech(row: dict[str, Any]) -> bool:
    market_data = row.get("market_data") if isinstance(row.get("market_data"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            row.get("sector"),
            market_data.get("sector"),
            market_data.get("industry"),
        )
    ).lower()
    return "biotech" in text or "biotechnology" in text


def _real_company_name(row: dict[str, Any]) -> str | None:
    market_data = row.get("market_data") if isinstance(row.get("market_data"), dict) else {}
    ticker = _ticker(row).lower()
    for value in (
        row.get("company"),
        market_data.get("company_name"),
        row.get("company_name"),
        row.get("name"),
    ):
        if not value:
            continue
        name = str(value).strip()
        if not name:
            continue
        if name.lower() in GENERIC_COMPANY_NAMES or name.lower() == ticker:
            continue
        return name
    return None


def _market_data_status(row: dict[str, Any]) -> str:
    market_data = row.get("market_data") if isinstance(row.get("market_data"), dict) else {}
    has_price = market_data.get("price") not in (None, "")
    has_market_cap = market_data.get("market_cap") not in (None, "") or row.get("market_cap") not in (None, "")
    return "covered" if has_price and has_market_cap else "pending"


def _financial_status(row: dict[str, Any]) -> str:
    financial_data = row.get("financial_data") if isinstance(row.get("financial_data"), dict) else {}
    if financial_data:
        return "covered"
    # Some legacy rows carry flattened financial fields.
    for key in ("Cash", "Assets", "Liabilities", "NetIncome", "Revenue"):
        if row.get(key) not in (None, ""):
            return "covered"
    return "pending"


def _trial_ticker_sets(trial_records: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    trial_tickers = set()
    intervention_tickers = set()
    for record in trial_records:
        if not isinstance(record, dict):
            continue
        ticker = _ticker(record)
        if not ticker:
            continue
        trial_tickers.add(ticker)
        if record.get("interventions"):
            intervention_tickers.add(ticker)
    return trial_tickers, intervention_tickers


def _coverage_status(row: dict[str, Any], trial_tickers: set[str], intervention_tickers: set[str]) -> dict[str, str]:
    ticker = _ticker(row)
    return {
        "company_name": "covered" if _real_company_name(row) else "pending",
        "market_data": _market_data_status(row),
        "financials": _financial_status(row),
        "clinical_trials": "covered" if ticker in trial_tickers else "pending",
        "scientific_cartography": "covered" if ticker in intervention_tickers else "pending",
    }


def refresh_universe(
    universe: list[dict[str, Any]],
    trial_records: list[dict[str, Any]],
    as_of_date: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return refreshed universe rows and a summary report."""
    trial_tickers, intervention_tickers = _trial_ticker_sets(trial_records)
    refreshed = deepcopy(universe)
    pending_tickers = []
    active_biotech_count = 0

    for row in refreshed:
        ticker = _ticker(row)
        if not ticker or not _is_active_status(row) or not _is_biotech(row):
            continue

        active_biotech_count += 1
        coverage = _coverage_status(row, trial_tickers, intervention_tickers)
        pending_reasons = [
            name
            for name in ("company_name", "market_data", "clinical_trials", "scientific_cartography")
            if coverage[name] == "pending"
        ]

        if not pending_reasons:
            continue

        row["status"] = "pending_data_collection"
        row["status_reason"] = "coverage_pending:" + ",".join(pending_reasons)
        row["coverage_status"] = coverage
        row["coverage_refreshed_as_of"] = as_of_date
        pending_tickers.append(ticker)

    report = {
        "as_of_date": as_of_date,
        "active_biotech_before": active_biotech_count,
        "marked_pending_count": len(pending_tickers),
        "marked_pending_tickers": sorted(pending_tickers),
    }
    return refreshed, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--universe-path", type=Path, default=REPO_ROOT / "production_data" / "universe.json")
    parser.add_argument("--trial-records-path", type=Path, default=REPO_ROOT / "production_data" / "trial_records.json")
    args = parser.parse_args()

    universe = json.loads(args.universe_path.read_text(encoding="utf-8"))
    trial_records = json.loads(args.trial_records_path.read_text(encoding="utf-8"))
    refreshed, report = refresh_universe(universe, trial_records, args.as_of_date)

    args.universe_path.write_text(json.dumps(refreshed, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
