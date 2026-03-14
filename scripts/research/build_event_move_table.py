#!/usr/bin/env python3
"""Build the historical event-move lookup table from snapshot outcomes.

Scans enriched snapshot data for rows with abs_gap outcomes, groups by
(catalyst_family, phase_bucket, indication_bucket), and computes
percentile distributions per cell.

Output:
    data/research/event_move_table.json — canonical lookup artifact
    data/research/event_move_table.md   — human-readable summary

CCFT: table is frozen at build time with built_as_of timestamp and
input data SHA256. Not auto-rebuilt on every screen run.

Usage:
    python scripts/research/build_event_move_table.py
    python scripts/research/build_event_move_table.py --snapshots-dir data/snapshots
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
_SCRIPTS = PROJECT_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_RESEARCH = _SCRIPTS / "research"
if str(_RESEARCH) not in sys.path:
    sys.path.insert(0, str(_RESEARCH))

from eval_options_alpha import load_enriched_dataset  # noqa: E402

from common.event_move_lookup import build_table  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SCHEMA = "event_move_table.v1"


def _enrich_with_rankings(
    dataset: List[Dict[str, Any]],
    snapshots_dir: Path,
) -> None:
    """Add lead_program_phase and therapeutic_area from rankings.csv."""
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in dataset:
        by_date.setdefault(row["snap_date"], []).append(row)

    for snap_date, date_rows in by_date.items():
        csv_path = snapshots_dir / snap_date / "rankings.csv"
        rankings_map: Dict[str, Dict[str, str]] = {}
        if csv_path.exists():
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                for rr in csv.DictReader(f):
                    t = (rr.get("ticker") or "").strip().upper()
                    if t:
                        rankings_map[t] = rr

        for row in date_rows:
            rr = rankings_map.get(row["ticker"], {})
            row["lead_program_phase"] = rr.get("lead_program_phase", "")
            row["therapeutic_area"] = rr.get("therapeutic_area", "")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build historical event-move lookup table.")
    p.add_argument("--snapshots-dir", type=Path, default=Path("data/snapshots"))
    p.add_argument("--price-csv", type=Path, default=Path("production_data/price_history.csv"))
    p.add_argument("--output-dir", type=Path, default=Path("data/research"))
    p.add_argument("--horizons", default="5,21", help="Forward return horizons (for dataset loading)")
    args = p.parse_args(argv)

    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    logger.info("Loading enriched dataset...")
    dataset = load_enriched_dataset(args.snapshots_dir, args.price_csv, horizons)
    logger.info("Loaded %d rows", len(dataset))

    # Filter to rows with abs_gap outcomes
    with_gap = [r for r in dataset if r.get("abs_gap") is not None and not math.isnan(r.get("abs_gap", float("nan")))]
    logger.info("Rows with abs_gap outcome: %d", len(with_gap))

    if len(with_gap) < 20:
        logger.error("Only %d outcome rows — too thin to build a useful table. Need >= 20.", len(with_gap))
        return 1

    # Enrich with phase/indication from rankings
    _enrich_with_rankings(with_gap, args.snapshots_dir)

    # Build table
    table = build_table(with_gap)

    # Compute input hash for CCFT
    input_str = json.dumps(
        [{"ticker": r["ticker"], "snap_date": r["snap_date"], "abs_gap": r["abs_gap"]} for r in with_gap],
        sort_keys=True,
    )
    input_hash = hashlib.sha256(input_str.encode()).hexdigest()[:16]

    # Build output
    output = {
        "schema": SCHEMA,
        "built_as_of": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_hash": input_hash,
        "n_outcomes": len(with_gap),
        "n_snap_dates": len({r["snap_date"] for r in with_gap}),
        "n_tickers": len({r["ticker"] for r in with_gap}),
        "table": table,
    }

    # Write JSON
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "event_move_table.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
        f.write("\n")
    logger.info("Table: %s", json_path)

    # Write Markdown
    md_lines = [
        "# Event Move Lookup Table",
        "",
        f"Built: {output['built_as_of']}",
        f"Outcomes: {output['n_outcomes']} rows, {output['n_snap_dates']} dates, {output['n_tickers']} tickers",
        f"Input hash: {input_hash}",
        "",
        "| Key | n | p25 | p50 | p75 | p90 | Confidence |",
        "|-----|---|-----|-----|-----|-----|------------|",
    ]
    for key, cell in sorted(table.items()):
        n = cell.get("n", 0)
        conf = cell.get("confidence", "")
        p25 = f"{cell['p25']:.4f}" if cell.get("p25") is not None else "-"
        p50 = f"{cell['p50']:.4f}" if cell.get("p50") is not None else "-"
        p75 = f"{cell['p75']:.4f}" if cell.get("p75") is not None else "-"
        p90 = f"{cell['p90']:.4f}" if cell.get("p90") is not None else "-"
        md_lines.append(f"| {key} | {n} | {p25} | {p50} | {p75} | {p90} | {conf} |")

    md_lines.append("")
    md_path = args.output_dir / "event_move_table.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    logger.info("Summary: %s", md_path)

    # Report cell quality
    n_ok = sum(1 for c in table.values() if c.get("confidence") == "ok")
    n_low = sum(1 for c in table.values() if c.get("confidence") == "low_confidence")
    n_insuf = sum(1 for c in table.values() if c.get("confidence") == "insufficient")
    logger.info(
        "Cell quality: %d ok, %d low_confidence, %d insufficient (of %d total)", n_ok, n_low, n_insuf, len(table)
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
