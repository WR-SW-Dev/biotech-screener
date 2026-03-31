#!/usr/bin/env python3
"""Expand fda_designations.json by researching uncovered universe tickers.

Reads the current designations file, identifies uncovered tickers in the DEM
top-N, and produces a candidate file for manual review and merge.

Usage:
    # Generate candidates for top-60 DEM names
    python3 tools/expand_fda_designations.py --top-n 60

    # Merge reviewed candidates into production
    python3 tools/expand_fda_designations.py --merge candidates.json

    # Coverage diagnostics only
    python3 tools/expand_fda_designations.py --diagnostics
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

PRODUCTION_DIR = PROJECT_ROOT / "production_data"
DESIGNATIONS_PATH = PRODUCTION_DIR / "fda_designations.json"
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
OUTPUT_DIR = PROJECT_ROOT / "output" / "fda_designation_expansion"

# Priority order per user directive
DESIGNATION_PRIORITY = ["BTD", "RMAT", "ODD", "FT"]

# Required fields for new entries
REQUIRED_FIELDS = [
    "ticker",
    "drug_name",
    "designation_type",
    "indication",
    "grant_date",
    "source_url",
    "source_confidence",
    "active",
]


def load_designations(path: Path = DESIGNATIONS_PATH) -> Dict[str, Any]:
    """Load current fda_designations.json."""
    with open(path) as f:
        return json.load(f)


def load_dem_rankings(snapshots_dir: Path = SNAPSHOTS_DIR) -> List[Dict[str, str]]:
    """Load latest DEM decision_portfolio.csv."""
    # Find latest output snapshot with decision_portfolio
    output_snapshots = sorted((PROJECT_ROOT / "output" / "snapshots").iterdir(), reverse=True)
    for snap_dir in output_snapshots:
        dp = snap_dir / "decision_portfolio.csv"
        if dp.exists():
            with open(dp) as f:
                reader = csv.DictReader(f)
                rows = [r for r in reader if r.get("actionable_rank", "").strip()]
            rows.sort(key=lambda r: int(r["actionable_rank"]))
            logger.info(f"Loaded DEM from {dp} ({len(rows)} ranked)")
            return rows
    raise FileNotFoundError("No decision_portfolio.csv found in output/snapshots/")


def load_company_names(snapshots_dir: Path = SNAPSHOTS_DIR) -> Dict[str, str]:
    """Load ticker → company_name from latest rankings.csv."""
    snap_dates = sorted(
        [d for d in snapshots_dir.iterdir() if d.is_dir() and "__pre" not in d.name],
        reverse=True,
    )
    for snap_dir in snap_dates:
        rankings = snap_dir / "rankings.csv"
        if rankings.exists():
            names = {}
            with open(rankings) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    t = row.get("ticker", "")
                    n = row.get("company_name", "")
                    if t and n:
                        names[t] = n
            return names
    return {}


def coverage_diagnostics(
    designations: Dict[str, Any],
    dem_rows: List[Dict[str, str]],
    top_n: int = 60,
) -> Dict[str, Any]:
    """Compute coverage statistics."""
    entries = designations["designations"]
    covered_tickers = set(e["ticker"] for e in entries)

    top_tickers = [r["ticker"] for r in dem_rows[:top_n]]
    top_covered = [t for t in top_tickers if t in covered_tickers]
    top_uncovered = [t for t in top_tickers if t not in covered_tickers]

    type_counts = Counter(e["designation_type"] for e in entries)
    tickers_per_type = defaultdict(set)
    for e in entries:
        tickers_per_type[e["designation_type"]].add(e["ticker"])

    return {
        "total_entries": len(entries),
        "unique_tickers_covered": len(covered_tickers),
        "top_n": top_n,
        "top_n_covered": len(top_covered),
        "top_n_uncovered": len(top_uncovered),
        "top_n_coverage_pct": round(len(top_covered) / top_n * 100, 1),
        "type_counts": dict(type_counts),
        "tickers_per_type": {k: len(v) for k, v in tickers_per_type.items()},
        "uncovered_tickers": top_uncovered,
        "covered_tickers_in_top": top_covered,
    }


def generate_research_manifest(
    designations: Dict[str, Any],
    dem_rows: List[Dict[str, str]],
    company_names: Dict[str, str],
    top_n: int = 60,
) -> List[Dict[str, Any]]:
    """Generate research manifest for uncovered tickers."""
    covered = set(e["ticker"] for e in designations["designations"])
    manifest = []
    for r in dem_rows[:top_n]:
        ticker = r["ticker"]
        if ticker in covered:
            continue
        manifest.append(
            {
                "ticker": ticker,
                "company_name": company_names.get(ticker, ""),
                "actionable_rank": int(r["actionable_rank"]),
                "tier": r.get("tier_any", ""),
                "archetype": r.get("archetype", ""),
                "search_queries": [
                    f'"{company_names.get(ticker, ticker)}" FDA breakthrough therapy designation',
                    f'"{company_names.get(ticker, ticker)}" FDA orphan drug designation',
                    f'"{company_names.get(ticker, ticker)}" FDA RMAT designation',
                    f'"{company_names.get(ticker, ticker)}" FDA fast track designation',
                ],
            }
        )
    return manifest


def validate_candidate(entry: Dict[str, Any]) -> List[str]:
    """Validate a candidate designation entry."""
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in entry or not str(entry[field]).strip():
            errors.append(f"Missing required field: {field}")

    if entry.get("designation_type") not in DESIGNATION_PRIORITY + ["PR", "AA"]:
        errors.append(f"Unknown designation_type: {entry.get('designation_type')}")

    if entry.get("source_confidence") not in ("confirmed", "likely", "unconfirmed"):
        errors.append(f"Invalid source_confidence: {entry.get('source_confidence')}")

    if entry.get("active") not in (True, False, "true", "false"):
        errors.append(f"Invalid active flag: {entry.get('active')}")

    grant = entry.get("grant_date", "")
    if grant and len(grant) != 10:
        errors.append(f"grant_date should be YYYY-MM-DD, got: {grant}")

    return errors


def merge_candidates(
    base_path: Path,
    candidates_path: Path,
    output_path: Path,
) -> Dict[str, Any]:
    """Merge reviewed candidates into the designations file."""
    with open(base_path) as f:
        base = json.load(f)

    with open(candidates_path) as f:
        candidates = json.load(f)

    if isinstance(candidates, dict) and "designations" in candidates:
        new_entries = candidates["designations"]
    elif isinstance(candidates, list):
        new_entries = candidates
    else:
        raise ValueError("Candidates must be a list or have a 'designations' key")

    # Validate all candidates
    all_errors = []
    for i, entry in enumerate(new_entries):
        errs = validate_candidate(entry)
        if errs:
            all_errors.append((i, entry.get("ticker", "?"), errs))

    if all_errors:
        print("VALIDATION ERRORS:")
        for idx, ticker, errs in all_errors:
            print(f"  Entry {idx} ({ticker}):")
            for e in errs:
                print(f"    - {e}")
        raise ValueError(f"{len(all_errors)} entries failed validation")

    # Deduplicate: (ticker, designation_type, drug_name, indication) is unique key
    existing_keys = set()
    for e in base["designations"]:
        key = (e["ticker"], e["designation_type"], e.get("drug_name", ""), e.get("indication", ""))
        existing_keys.add(key)

    added = 0
    skipped = 0
    for entry in new_entries:
        # Normalize active field
        if isinstance(entry.get("active"), str):
            entry["active"] = entry["active"].lower() == "true"

        key = (entry["ticker"], entry["designation_type"], entry.get("drug_name", ""), entry.get("indication", ""))
        if key in existing_keys:
            skipped += 1
            continue
        base["designations"].append(entry)
        existing_keys.add(key)
        added += 1

    # Update metadata
    base["metadata"]["last_updated"] = date.today().isoformat()
    base["metadata"]["notes"] = f"Expanded {date.today().isoformat()}: +{added} entries from designation research"

    # Sort by ticker, then designation_type priority
    type_order = {t: i for i, t in enumerate(DESIGNATION_PRIORITY + ["PR", "AA"])}
    base["designations"].sort(key=lambda e: (e["ticker"], type_order.get(e["designation_type"], 99)))

    with open(output_path, "w") as f:
        json.dump(base, f, indent=2)
        f.write("\n")

    return {"added": added, "skipped": skipped, "total": len(base["designations"])}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="FDA designation expansion tool")
    parser.add_argument("--top-n", type=int, default=60, help="DEM top-N to research")
    parser.add_argument("--diagnostics", action="store_true", help="Coverage diagnostics only")
    parser.add_argument("--manifest", action="store_true", help="Generate research manifest")
    parser.add_argument(
        "--merge",
        type=Path,
        default=None,
        help="Path to reviewed candidates JSON to merge into production",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    desig = load_designations()
    dem = load_dem_rankings()
    names = load_company_names()

    if args.diagnostics:
        diag = coverage_diagnostics(desig, dem, args.top_n)
        print(json.dumps(diag, indent=2))
        (args.output_dir / "coverage_diagnostics.json").write_text(json.dumps(diag, indent=2) + "\n")
        return 0

    if args.manifest:
        manifest = generate_research_manifest(desig, dem, names, args.top_n)
        out_path = args.output_dir / "research_manifest.json"
        out_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Research manifest: {len(manifest)} tickers → {out_path}")

        # Also generate markdown for easy reading
        md_path = args.output_dir / "research_manifest.md"
        lines = [f"# FDA Designation Research Manifest ({date.today().isoformat()})\n"]
        lines.append(f"**{len(manifest)} tickers** in DEM top-{args.top_n} without FDA designation data.\n")
        lines.append("Priority: BTD > RMAT > ODD > FT\n")
        lines.append("| Rank | Ticker | Company | Tier |\n|------|--------|---------|------|\n")
        for m in manifest:
            lines.append(f"| {m['actionable_rank']} | {m['ticker']} | {m['company_name']} | {m['tier']} |\n")
        md_path.write_text("".join(lines))
        print(f"Markdown manifest: {md_path}")
        return 0

    if args.merge:
        if not args.merge.exists():
            print(f"FATAL: {args.merge} not found")
            return 1
        out_path = args.output_dir / "fda_designations_expanded.json"
        result = merge_candidates(DESIGNATIONS_PATH, args.merge, out_path)
        print(f"Merge complete: +{result['added']} added, {result['skipped']} skipped, {result['total']} total")
        print(f"Output: {out_path}")
        print("\nTo promote to production:")
        print(f"  cp {out_path} {DESIGNATIONS_PATH}")
        return 0

    # Default: run diagnostics + manifest
    diag = coverage_diagnostics(desig, dem, args.top_n)
    print("=== Coverage Diagnostics ===")
    print(f"Current entries: {diag['total_entries']}")
    print(f"Unique tickers: {diag['unique_tickers_covered']}")
    print(f"Top-{args.top_n} coverage: {diag['top_n_covered']}/{args.top_n} ({diag['top_n_coverage_pct']}%)")
    print(f"By type: {diag['type_counts']}")
    print()

    manifest = generate_research_manifest(desig, dem, names, args.top_n)
    out_path = args.output_dir / "research_manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Research manifest: {len(manifest)} tickers → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
