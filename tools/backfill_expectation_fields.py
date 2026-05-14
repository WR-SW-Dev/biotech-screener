"""
Spec 102: Historical Backfill for Expectation Research

Backfills expectation model input fields (short_interest_pct, close_price, market_cap_mm,
priced_move_pct, insider_net_buy_value_90d) into historical snapshots for research use.

Strategy: Additive only (fill empty cells, never overwrite existing values).
Data sources: PIT-correct per-snapshot inputs/, price caches, insider form4 data.
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from common.insider_enrichment import enrich_rows_with_insider_net_buy_value


def discover_snapshots(root: Path, start_date: str, end_date: str) -> List[Path]:
    """Find all YYYY-MM-DD snapshot directories containing rankings.csv in date range."""
    from datetime import datetime, timedelta

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    snapshots = []
    current = start
    while current <= end:
        snapshot_dir = root / current.strftime("%Y-%m-%d")
        if (snapshot_dir / "rankings.csv").exists():
            snapshots.append(snapshot_dir)
        current += timedelta(days=1)

    return sorted(snapshots)


def load_price_pit(date: str) -> Dict[str, float]:
    """Load anchor_close prices from PIT cache for the given date."""
    pit_path = Path(f"data/caches/price_pit/PIT/{date}/prices.csv")
    prices = {}
    if not pit_path.exists():
        return prices

    try:
        with open(pit_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = (row.get("ticker") or "").upper()
                anchor_close = row.get("anchor_close", "").strip()
                if ticker and anchor_close:
                    try:
                        prices[ticker] = float(anchor_close)
                    except ValueError:
                        pass
    except Exception as e:
        print(f"  Warning: error loading price_pit for {date}: {e}")

    return prices


def load_shares_outstanding() -> Dict[str, float]:
    """Load shares_outstanding from production_data/market_data.json (loaded once)."""
    market_data_path = Path("production_data/market_data.json")
    shares = {}
    if not market_data_path.exists():
        return shares

    try:
        with open(market_data_path) as f:
            records = json.load(f)
            for record in records:
                ticker = (record.get("ticker") or "").upper()
                so = record.get("shares_outstanding")
                if ticker and so:
                    try:
                        shares[ticker] = float(so)
                    except (ValueError, TypeError):
                        pass
    except Exception as e:
        print(f"Warning: error loading market_data.json: {e}")

    return shares


def load_si_pit(snapshot_dir: Path) -> Dict[str, float]:
    """Load short_interest_pct from per-snapshot inputs/short_interest.json (PIT copy)."""
    si_path = snapshot_dir / "inputs" / "short_interest.json"
    si_lookup = {}

    if si_path.exists():
        try:
            with open(si_path) as f:
                records = json.load(f)
                if isinstance(records, list):
                    # List of dicts with "ticker" and "short_interest_pct" keys
                    for rec in records:
                        ticker = (rec.get("ticker") or "").upper()
                        si_pct = rec.get("short_interest_pct")
                        if ticker and si_pct is not None:
                            try:
                                si_lookup[ticker] = float(si_pct)
                            except (ValueError, TypeError):
                                pass
                elif isinstance(records, dict):
                    # Dict keyed by ticker
                    for ticker, si_pct in records.items():
                        ticker = ticker.upper()
                        if si_pct is not None:
                            try:
                                si_lookup[ticker] = float(si_pct)
                            except (ValueError, TypeError):
                                pass
        except Exception as e:
            print(f"  Warning: error loading inputs/short_interest.json: {e}")

    # Fallback to production short_interest.json
    if not si_lookup:
        prod_si_path = Path("production_data/short_interest.json")
        if prod_si_path.exists():
            try:
                with open(prod_si_path) as f:
                    records = json.load(f)
                    for rec in records:
                        ticker = (rec.get("ticker") or "").upper()
                        si_pct = rec.get("short_interest_pct")
                        if ticker and si_pct is not None:
                            try:
                                si_lookup[ticker] = float(si_pct)
                            except (ValueError, TypeError):
                                pass
            except Exception as e:
                print(f"  Warning: error loading production short_interest.json: {e}")

    return si_lookup


def measure_coverage(rows: List[Dict], fields: List[str]) -> Dict[str, float]:
    """Measure % non-empty for each field (None/empty string/nan treated as empty)."""
    coverage = {}
    if not rows:
        return {f: 0.0 for f in fields}

    for field in fields:
        non_empty = 0
        for row in rows:
            value = row.get(field)
            # Convert to string if not already
            if value is not None and value != "":
                value_str = str(value).strip()
                if value_str and value_str.lower() not in ("none", "nan"):
                    non_empty += 1
        coverage[field] = round(100 * non_empty / len(rows), 2)

    return coverage


def backfill_snapshot(
    snapshot_dir: Path,
    prices: Dict[str, float],
    shares: Dict[str, float],
    short_interest: Dict[str, float],
    dry_run: bool = False,
    skip_insider: bool = False,
    force: bool = False,
) -> Dict:
    """
    Backfill expectation fields into a single snapshot.
    Returns manifest dict with before/after coverage.
    """
    date = snapshot_dir.name
    rankings_path = snapshot_dir / "rankings.csv"

    # Read CSV
    rows = []
    fieldnames = None
    try:
        with open(rankings_path) as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
    except Exception as e:
        print(f"  {date}: ERROR reading CSV — {e}")
        return {"error": str(e)}

    if not rows:
        return {"error": "no rows"}

    # Pre-coverage
    target_fields = [
        "short_interest_pct",
        "close_price",
        "market_cap_mm",
        "priced_move_pct",
        "insider_net_buy_value_90d",
    ]
    coverage_before = measure_coverage(rows, target_fields)

    # Patch each row
    insider_added = False
    fields_patched = set()

    for row in rows:
        ticker = (row.get("ticker") or "").upper()

        # close_price
        if "close_price" not in fieldnames:
            fieldnames = list(fieldnames or []) + ["close_price"]
            insider_added = True
        if (not row.get("close_price") or not str(row.get("close_price")).strip()) and ticker in prices:
            row["close_price"] = prices[ticker]
            fields_patched.add("close_price")

        # market_cap_mm
        if "market_cap_mm" not in fieldnames:
            fieldnames = list(fieldnames or []) + ["market_cap_mm"]
            insider_added = True
        if (
            (not row.get("market_cap_mm") or not str(row.get("market_cap_mm")).strip())
            and ticker in prices
            and ticker in shares
        ):
            market_cap_mm = round(prices[ticker] * shares[ticker] / 1e6, 1)
            row["market_cap_mm"] = market_cap_mm
            fields_patched.add("market_cap_mm")

        # short_interest_pct
        if "short_interest_pct" not in fieldnames:
            fieldnames = list(fieldnames or []) + ["short_interest_pct"]
            insider_added = True
        if (
            not row.get("short_interest_pct") or not str(row.get("short_interest_pct")).strip()
        ) and ticker in short_interest:
            row["short_interest_pct"] = short_interest[ticker]
            fields_patched.add("short_interest_pct")

        # priced_move_pct: no-op (no backfill source)

    # insider: add column if missing
    if "insider_net_buy_value_90d" not in (fieldnames or []) and not skip_insider:
        fieldnames = list(fieldnames or []) + ["insider_net_buy_value_90d"]
        insider_added = True
        fields_patched.add("insider_net_buy_value_90d")

        try:
            enrich_rows_with_insider_net_buy_value(
                rows,
                raw_dir=Path("data/form4/raw"),
                as_of_date=date,
            )
        except Exception as e:
            print(f"  {date}: Warning — error computing insider: {e}")

    # Post-coverage
    coverage_after = measure_coverage(rows, target_fields)

    # Write back (unless dry-run)
    if not dry_run:
        try:
            with open(rankings_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        except Exception as e:
            print(f"  {date}: ERROR writing CSV — {e}")
            return {"error": f"write failed: {e}"}

        # Write .backfill_metadata.json
        metadata = {
            "backfill_expectation_fields": True,
            "backfill_date": datetime.utcnow().isoformat() + "Z",
            "spec": "102",
        }
        metadata_path = snapshot_dir / ".backfill_metadata.json"
        try:
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            print(f"  {date}: Warning — error writing metadata: {e}")

        # Write manifest
        manifest = {
            "snapshot_date": date,
            "fields_added": list(fields_patched),
            "insider_computed": insider_added and not skip_insider,
            "coverage_before": coverage_before,
            "coverage_after": coverage_after,
            "actions_recomputed": False,
            "ranks_recomputed": False,
        }
        manifest_dir = Path("artifacts/backfill_manifest")
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"backfill_expectation_fields_{date.replace('-', '_')}.json"
        try:
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)
        except Exception as e:
            print(f"  {date}: Warning — error writing manifest: {e}")

    # Return status
    return {
        "snapshot_date": date,
        "rows": len(rows),
        "coverage_before": coverage_before,
        "coverage_after": coverage_after,
        "fields_patched": list(fields_patched),
    }


def main():
    """Main entry point: backfill all snapshots in date range."""
    parser = argparse.ArgumentParser(description="Backfill expectation fields into historical snapshots")
    parser.add_argument(
        "--start-date",
        default="2026-04-20",
        help="Start date (YYYY-MM-DD), default: 2026-04-20",
    )
    parser.add_argument(
        "--end-date",
        default="2026-05-13",
        help="End date (YYYY-MM-DD), default: 2026-05-13",
    )
    parser.add_argument(
        "--snapshot-dir",
        default="data/snapshots",
        help="Path to snapshots directory, default: data/snapshots",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Audit only; do not write",
    )
    parser.add_argument(
        "--skip-insider",
        action="store_true",
        help="Skip insider column addition",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing non-empty values",
    )

    args = parser.parse_args()

    data_dir = Path(args.snapshot_dir)
    snapshots = discover_snapshots(data_dir, args.start_date, args.end_date)

    print(f"Backfilling {len(snapshots)} snapshots: {args.start_date} through {args.end_date}")
    if args.dry_run:
        print("  (DRY RUN — no writes)")

    # Load once
    shares = load_shares_outstanding()
    print(f"Loaded shares_outstanding for {len(shares)} tickers")

    results = []
    for snapshot_dir in snapshots:
        date = snapshot_dir.name

        prices = load_price_pit(date)
        short_interest = load_si_pit(snapshot_dir)

        result = backfill_snapshot(
            snapshot_dir,
            prices,
            shares,
            short_interest,
            dry_run=args.dry_run,
            skip_insider=args.skip_insider,
            force=args.force,
        )

        if "error" in result:
            print(f"  {date}: FAILED — {result['error']}")
        else:
            cov_before = result["coverage_before"]
            cov_after = result["coverage_after"]
            print(
                f"  {date}: {result['rows']} rows | "
                f"close_price {cov_before.get('close_price', 0)}% → {cov_after.get('close_price', 0)}% | "
                f"si {cov_before.get('short_interest_pct', 0)}% → {cov_after.get('short_interest_pct', 0)}%"
            )
            results.append(result)

    print(f"\nCompleted {len(results)} / {len(snapshots)} snapshots")


if __name__ == "__main__":
    main()
