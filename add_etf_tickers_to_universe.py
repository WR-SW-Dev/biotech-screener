#!/usr/bin/env python3
"""
add_etf_tickers_to_universe.py - Add Complete ETF Holdings to Universe

Takes the etf_holdings_complete.json and adds missing tickers to universe.json.

Usage:
    python add_etf_tickers_to_universe.py
"""

import json
from datetime import date
from pathlib import Path


def _normalise_ticker(ticker):
    """Return a clean uppercase ticker string."""
    return str(ticker or "").strip().upper()


def _iter_holdings_for_source(holdings, source_key):
    """Yield ticker rows from either legacy list or richer ETF holding objects."""
    rows = holdings.get(source_key, [])
    if isinstance(rows, dict) and "constituents" in rows:
        rows = rows["constituents"]
    if not isinstance(rows, list):
        return
    for row in rows:
        yield row


def _ticker_from_holding(row):
    """Extract ticker from a holding row."""
    if isinstance(row, str):
        return _normalise_ticker(row)
    if not isinstance(row, dict):
        return ""
    for key in ("ticker", "symbol", "Ticker", "Symbol"):
        if row.get(key):
            return _normalise_ticker(row[key])
    return ""


def _company_name_from_holding(row):
    """Extract company/security name from a holding row when ETF metadata has it."""
    if not isinstance(row, dict):
        return None
    for key in ("company_name", "name", "security_name", "Security Name", "Name", "issuer", "Issuer"):
        value = row.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return None


def _extract_ticker_metadata(holdings):
    """Build ticker -> source/name metadata from ETF holdings."""
    metadata = {}
    for source_key, source_name in (("xbi", "XBI"), ("ibb", "IBB"), ("nbi", "NBI")):
        for row in _iter_holdings_for_source(holdings, source_key):
            ticker = _ticker_from_holding(row)
            if not ticker:
                continue
            entry = metadata.setdefault(ticker, {"sources": set(), "company_name": None})
            entry["sources"].add(source_name)
            company_name = _company_name_from_holding(row)
            if company_name and not entry["company_name"]:
                entry["company_name"] = company_name

    return {
        ticker: {
            "sources": sorted(values["sources"]),
            "company_name": values["company_name"],
        }
        for ticker, values in metadata.items()
    }


def _build_new_security(ticker, metadata, today):
    """Create a new universe entry for an ETF ticker awaiting data coverage."""
    company_name = metadata.get("company_name")
    sources = metadata.get("sources", [])
    entry = {
        "ticker": ticker,
        "name": company_name,
        "exchange": metadata.get("exchange") or "",
        "sector": "Biotechnology",
        "status": "pending_data_collection",
        "added_from_etf": True,
        "added_date": today,
        "etf_sources": sources,
        "market_cap": None,
        "description": f'Added from ETF holdings ({", ".join(sources)})',
        "coverage_status": {
            "market_data": "pending",
            "financials": "pending",
            "clinical_trials": "pending",
            "scientific_cartography": "pending",
        },
    }
    if company_name:
        entry["company_name"] = company_name
        entry["market_data"] = {"company_name": company_name}
    return entry


def add_etf_tickers_to_universe():
    """Add complete ETF holdings to universe"""

    print("=" * 80)
    print("ADDING ETF TICKERS TO UNIVERSE")
    print("=" * 80)

    # Load ETF holdings
    etf_file = Path("etf_holdings_complete.json")
    if not etf_file.exists():
        print(f"\n❌ ETF holdings file not found: {etf_file}")
        print("\nRun this first:")
        print("  python import_etf_csvs.py")
        return 1

    with open(etf_file) as f:
        holdings = json.load(f)

    # Get all unique ETF tickers and any available company-name metadata.
    ticker_metadata = _extract_ticker_metadata(holdings)
    all_etf_tickers = set(ticker_metadata)

    print(f"\n📊 Complete ETF universe: {len(all_etf_tickers)} tickers")

    # Load current universe
    universe_file = Path("production_data/universe.json")
    if not universe_file.exists():
        print(f"\n❌ Universe file not found: {universe_file}")
        print("\nCreate production_data/ directory and add universe.json")
        return 1

    with open(universe_file) as f:
        universe = json.load(f)

    # Extract current tickers
    current_tickers = set()
    for security in universe:
        ticker = security.get("ticker")
        if ticker and ticker != "_XBI_BENCHMARK_":
            current_tickers.add(ticker)

    print(f"📊 Current universe: {len(current_tickers)} tickers")

    # Find missing tickers
    missing_tickers = all_etf_tickers - current_tickers

    if not missing_tickers:
        print("\n✅ No new tickers to add - universe is already complete!")
        return 0

    print(f"📊 Missing from universe: {len(missing_tickers)} tickers")
    print("\n📝 Tickers to add (first 20):")
    for i, ticker in enumerate(sorted(missing_tickers)[:20], 1):
        sources = ticker_metadata[ticker]["sources"]

        print(f"   {i:2d}. {ticker:6s}  ({', '.join(sources)})")

    if len(missing_tickers) > 20:
        print(f"   ... and {len(missing_tickers) - 20} more")

    # Ask for confirmation
    print("\n" + "=" * 80)
    response = input(f"Add {len(missing_tickers)} tickers to universe? (yes/no): ")

    if response.lower() not in ["yes", "y"]:
        print("❌ Cancelled - no changes made")
        return 0

    # Add missing tickers
    added_count = 0
    today = date.today().isoformat()

    for ticker in sorted(missing_tickers):
        # Create new security entry as pending until market/scientific data is populated.
        new_security = _build_new_security(ticker, ticker_metadata[ticker], today)

        universe.append(new_security)
        added_count += 1

    # Backup original
    backup_file = universe_file.parent / f"universe_backup_{today}.json"
    with open(backup_file, "w") as f:
        json.dump(json.load(open(universe_file)), f, indent=2)

    print(f"\n✅ Backup saved to: {backup_file}")

    # Save expanded universe
    with open(universe_file, "w") as f:
        json.dump(universe, f, indent=2)

    print(f"✅ Updated universe saved to: {universe_file}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Original universe: {len(current_tickers)} tickers")
    print(f"Added: {added_count} tickers")
    print(f"New universe: {len(universe)} tickers")
    print("ETF coverage: 100% ✅")
    print("=" * 80)

    # Next steps
    print("\n" + "=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print("1. Populate data for new tickers:")
    print("   python collect_financial_data.py")
    print("   python collect_ctgov_data.py --output production_data/trial_records.json")
    print("\n2. Re-run screening:")
    print(f"   python run_screen.py --as-of-date {today} --data-dir production_data --output screening_complete.json")
    print("\n3. Expect Module 1 to filter many new tickers:")
    print("   - Recent IPOs (no financial data yet)")
    print("   - Platform companies (no clinical trials)")
    print("   - Pre-clinical (no Phase 1+ trials)")
    print("   - Illiquid names")
    print("\n4. Final active universe will be ~150-200 tickers (correct!)")
    print("=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    exit(add_etf_tickers_to_universe())
