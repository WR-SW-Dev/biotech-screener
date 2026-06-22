#!/usr/bin/env python3
"""
import_etf_csvs.py - Simple CSV Import for XBI, IBB, NBI

Imports downloaded CSV files and creates complete ETF holdings JSON.

Usage:
    # After downloading XBI, IBB, NBI CSVs to etf_csvs/ directory:
    python import_etf_csvs.py
"""

import csv
import io
import json
import re
from pathlib import Path

_VALID_TICKER_RE = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")


# Non-biotech tickers and parsing artifacts to exclude at import time.
# PURR = Hyperliquid Strategies (crypto-adjacent fund, not a biotech).
# LLC = State Street legal disclaimer text parsed as a row by some CSV readers.
_EXCLUDE_TICKERS = {"PURR", "LLC"}


def load_csv_tickers(csv_path, ticker_columns=["Ticker", "Symbol", "Ticker Symbol"]):
    """
    Load tickers from CSV, automatically detecting ticker column.

    Args:
        csv_path: Path to CSV file
        ticker_columns: Possible ticker column names to check

    Returns:
        List of ticker symbols
    """
    if not csv_path.exists():
        return None

    tickers = []

    try:
        # Try UTF-8 with BOM first (common in Excel exports)
        with open(csv_path, encoding="utf-8-sig") as f:
            # Some ETF CSVs (e.g. SSGA/XBI) prepend fund-metadata rows before the
            # real header.  Scan forward until we find a line whose first field
            # contains one of our expected ticker column names, then reposition.
            lines = f.readlines()

        # Find the real data header: a line where one field *exactly* matches a
        # known ticker column name (case-insensitive). This avoids matching
        # metadata rows like "Ticker Symbol:,XBI" where the key is only a
        # partial match.
        header_line = 0
        for i, line in enumerate(lines):
            fields = [c.strip() for c in line.split(",")]
            if any(f.lower() == possible.lower() for f in fields for possible in ticker_columns):
                header_line = i
                break

        csv_text = "".join(lines[header_line:])
        reader = csv.DictReader(io.StringIO(csv_text))

        # Find ticker column (case-insensitive)
        columns = [c.strip() for c in reader.fieldnames]
        ticker_col = None

        for col in columns:
            col_lower = col.lower()
            for possible in ticker_columns:
                if possible.lower() in col_lower:
                    ticker_col = col
                    break
            if ticker_col:
                break

        if not ticker_col:
            print(f"  ❌ Warning: No ticker column found in {csv_path.name}")
            print(f"     Available columns: {columns}")
            return []

        print(f"  → Using column: '{ticker_col}'")

        # Extract tickers
        for row in reader:
            ticker = row.get(ticker_col, "").strip()

            # Clean and validate ticker
            if ticker and ticker not in ["", "Cash", "CASH", "Total", "cash"]:
                # Handle special cases
                ticker = ticker.replace(".", "-")  # Class A/B shares: BRK.A → BRK-A
                ticker = ticker.upper()

                # Skip non-standard identifiers (SEDOLs, Bloomberg IDs, etc.)
                if not _VALID_TICKER_RE.match(ticker):
                    continue

                if ticker in _EXCLUDE_TICKERS:
                    continue

                tickers.append(ticker)

    except Exception as e:
        print(f"  ❌ Error reading {csv_path.name}: {e}")
        return []

    return tickers


def main():
    print("=" * 80)
    print("IMPORTING ETF HOLDINGS FROM CSV FILES")
    print("=" * 80)

    csv_dir = Path("etf_csvs")

    if not csv_dir.exists():
        print(f"\n❌ Directory not found: {csv_dir}")
        print("\n📋 Setup Instructions:")
        print("   1. Create directory: mkdir etf_csvs")
        print("   2. Download CSV files:")
        print("      • XBI: https://www.ssga.com/us/en/individual/etfs/funds/xbi")
        print("      • IBB: https://www.ishares.com/us/products/239699/")
        print("      • NBI: https://indexes.nasdaqomx.com/Index/Weighting/NBI")
        print("   3. Save files as:")
        print("      • etf_csvs/XBI_holdings.csv")
        print("      • etf_csvs/IBB_holdings.csv")
        print("      • etf_csvs/NBI_holdings.csv")
        print("   4. Re-run this script")
        return 1

    holdings = {}

    # Import XBI
    print("\n📥 Loading XBI...")
    xbi_csv = csv_dir / "XBI_holdings.csv"
    holdings["xbi"] = load_csv_tickers(xbi_csv)

    if holdings["xbi"] is None:
        print(f"  ❌ File not found: {xbi_csv}")
        print("     Download from: https://www.ssga.com/us/en/individual/etfs/funds/xbi")
        holdings["xbi"] = []
    elif holdings["xbi"]:
        print(f"  ✅ Loaded {len(holdings['xbi'])} tickers")
    else:
        print(f"  ⚠️  No tickers found in {xbi_csv.name}")

    # Import IBB
    print("\n📥 Loading IBB...")
    ibb_csv = csv_dir / "IBB_holdings.csv"
    holdings["ibb"] = load_csv_tickers(ibb_csv)

    if holdings["ibb"] is None:
        print(f"  ❌ File not found: {ibb_csv}")
        print("     Download from: https://www.ishares.com/us/products/239699/")
        holdings["ibb"] = []
    elif holdings["ibb"]:
        print(f"  ✅ Loaded {len(holdings['ibb'])} tickers")
    else:
        print(f"  ⚠️  No tickers found in {ibb_csv.name}")

    # Import NBI
    print("\n📥 Loading NBI...")
    nbi_csv = csv_dir / "NBI_holdings.csv"
    holdings["nbi"] = load_csv_tickers(nbi_csv)

    if holdings["nbi"] is None:
        print(f"  ❌ File not found: {nbi_csv}")
        print("     Download from: https://indexes.nasdaqomx.com/Index/Weighting/NBI")
        holdings["nbi"] = []
    elif holdings["nbi"]:
        print(f"  ✅ Loaded {len(holdings['nbi'])} tickers")
    else:
        print(f"  ⚠️  No tickers found in {nbi_csv.name}")

    # Check if we got anything
    total_loaded = len(holdings["xbi"]) + len(holdings["ibb"]) + len(holdings["nbi"])

    if total_loaded == 0:
        print("\n❌ No tickers loaded from any ETF")
        return 1

    # Calculate unique tickers
    all_tickers = set(holdings["xbi"]) | set(holdings["ibb"]) | set(holdings["nbi"])

    # Overlap analysis
    xbi_set = set(holdings["xbi"])
    ibb_set = set(holdings["ibb"])
    nbi_set = set(holdings["nbi"])

    in_all_three = xbi_set & ibb_set & nbi_set

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"XBI holdings: {len(holdings['xbi'])}")
    print(f"IBB holdings: {len(holdings['ibb'])}")
    print(f"NBI holdings: {len(holdings['nbi'])}")
    print(f"Total unique: {len(all_tickers)}")
    print(f"In all three: {len(in_all_three)}")
    print("=" * 80)

    # Save to JSON
    output_file = "etf_holdings_complete.json"
    with open(output_file, "w") as f:
        json.dump(holdings, f, indent=2, sort_keys=True)

    print(f"\n✅ Saved to: {output_file}")

    # Show sample
    print("\n📋 Sample tickers (first 20):")
    for i, ticker in enumerate(sorted(all_tickers)[:20], 1):
        in_xbi = "✓" if ticker in xbi_set else "✗"
        in_ibb = "✓" if ticker in ibb_set else "✗"
        in_nbi = "✓" if ticker in nbi_set else "✗"
        print(f"   {i:2d}. {ticker:6s}  XBI:{in_xbi}  IBB:{in_ibb}  NBI:{in_nbi}")

    if len(all_tickers) > 20:
        print(f"   ... and {len(all_tickers) - 20} more")

    # Next steps
    print("\n" + "=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print("1. Verify the ticker counts look correct")
    print("2. Add these tickers to your universe:")
    print("   python add_etf_tickers_to_universe.py")
    print("3. Or manually inspect the JSON file:")
    print(f"   cat {output_file}")
    print("=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    exit(main())
