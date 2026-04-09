#!/usr/bin/env python3
"""Rollup institutional delta metrics into a time-series CSV for trending.

Scans ``data/snapshots/*/institutional_summary_delta.json`` and writes a
single CSV with one row per snapshot date.

Usage:
    python scripts/rollup_institutional_metrics.py [--snapshot-dir DIR] [--output PATH]
    python scripts/rollup_institutional_metrics.py --from-date 2026-01-15 --to-date 2026-03-06

Defaults:
    --snapshot-dir  data/snapshots
    --output        output/institutional_metrics_timeseries.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

COLUMNS = [
    "as_of_date",
    "prior_date",
    "tickers_in_universe",
    "tickers_common",
    "nonzero_count",
    "nonzero_pct",
    "total_new",
    "total_exit",
    "total_net",
    "max_abs_net",
    "positive_net_count",
    "negative_net_count",
    "coverage_guard_active",
]

# Matches run_screen.py default
DEFAULT_MIN_NONZERO_PCT = 10.0


def collect_institutional_metrics(
    snapshot_dir: Path,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    min_nonzero_pct: float = DEFAULT_MIN_NONZERO_PCT,
) -> list[dict]:
    """Read institutional_summary_delta.json files, return sorted rows."""
    rows: list[dict] = []
    if not snapshot_dir.exists():
        return rows

    for d in sorted(snapshot_dir.iterdir()):
        if not d.is_dir() or not _DATE_DIR_RE.match(d.name):
            continue
        if from_date and d.name < from_date:
            continue
        if to_date and d.name > to_date:
            continue
        delta_path = d / "institutional_summary_delta.json"
        if not delta_path.exists():
            continue
        # Skip degraded runs
        health_path = d / "cache_health.json"
        if health_path.exists():
            try:
                h = json.loads(health_path.read_text(encoding="utf-8"))
                if h.get("degraded_run", False):
                    continue
            except (json.JSONDecodeError, OSError):
                pass
        try:
            data = json.loads(delta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        tickers = data.get("tickers", {})
        n_universe = len(tickers)
        net_deltas = [v.get("net_elite_holders_delta", 0) for v in tickers.values()]
        new_counts = [v.get("elite_new_count", 0) for v in tickers.values()]
        exit_counts = [v.get("elite_exit_count", 0) for v in tickers.values()]

        nonzero = [n for n in net_deltas if n != 0]
        nonzero_count = len(nonzero)
        nonzero_pct = round(100.0 * nonzero_count / n_universe, 2) if n_universe else 0.0

        rows.append(
            {
                "as_of_date": data.get("as_of_date", d.name),
                "prior_date": data.get("prior_date", ""),
                "tickers_in_universe": n_universe,
                "tickers_common": data.get("tickers_common", ""),
                "nonzero_count": nonzero_count,
                "nonzero_pct": nonzero_pct,
                "total_new": sum(new_counts),
                "total_exit": sum(exit_counts),
                "total_net": sum(net_deltas),
                "max_abs_net": max((abs(n) for n in net_deltas), default=0),
                "positive_net_count": sum(1 for n in net_deltas if n > 0),
                "negative_net_count": sum(1 for n in net_deltas if n < 0),
                "coverage_guard_active": 1 if nonzero_pct < min_nonzero_pct else 0,
            }
        )

    rows.sort(key=lambda r: r.get("as_of_date", ""))
    return rows


def write_csv(rows: list[dict], output_path: Path) -> None:
    """Write rows to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rollup institutional delta metrics into a time-series CSV.",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=Path("data/snapshots"),
        help="Root snapshot directory (default: data/snapshots)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/institutional_metrics_timeseries.csv"),
        help="Output CSV path (default: output/institutional_metrics_timeseries.csv)",
    )
    parser.add_argument(
        "--from-date",
        default=None,
        help="Include snapshots on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--to-date",
        default=None,
        help="Include snapshots on or before this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--min-nonzero-pct",
        type=float,
        default=DEFAULT_MIN_NONZERO_PCT,
        help=f"Threshold for coverage guard (default: {DEFAULT_MIN_NONZERO_PCT}%%)",
    )
    args = parser.parse_args(argv)

    rows = collect_institutional_metrics(
        args.snapshot_dir,
        from_date=args.from_date,
        to_date=args.to_date,
        min_nonzero_pct=args.min_nonzero_pct,
    )
    if not rows:
        print("No institutional delta sidecars found.")
        return 1

    write_csv(rows, args.output)
    print(f"Wrote {len(rows)} rows to {args.output}")

    # Print summary
    guard_active = sum(1 for r in rows if r["coverage_guard_active"])
    print(f"  Coverage guard active: {guard_active}/{len(rows)} dates " f"({100 * guard_active / len(rows):.0f}%)")
    if rows:
        latest = rows[-1]
        print(
            f"  Latest ({latest['as_of_date']}): "
            f"nonzero={latest['nonzero_count']}/{latest['tickers_in_universe']} "
            f"({latest['nonzero_pct']}%), "
            f"net={latest['total_net']}, "
            f"guard={'ON' if latest['coverage_guard_active'] else 'OFF'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
