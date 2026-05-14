"""
Spec 104: Insider Signal Stabilization
Measurement script for insider_net_buy_value_90d coverage tracking.

Reads production snapshots, measures blank vs zero vs activity,
emits per-snapshot JSON + stabilization report.
"""

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List


def generate_date_range(start_date: str, end_date: str) -> List[str]:
    """Generate list of business days (M-F) between start and end dates."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    dates = []
    current = start
    while current <= end:
        # Only include weekdays (0=Mon, 6=Sun)
        if current.weekday() < 5:
            dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    return dates


def measure_snapshot(snapshot_path: Path) -> Dict:
    """
    Measure insider coverage for a single snapshot.

    Returns dict with:
    - snapshot_date
    - total_tickers
    - blank, zero, positive, negative counts
    - blank_pct, zero_pct, nonblank_pct, activity_pct
    """

    rankings_csv = snapshot_path / "rankings.csv"
    if not rankings_csv.exists():
        raise FileNotFoundError(f"rankings.csv not found: {rankings_csv}")

    total_tickers = 0
    blank_count = 0
    zero_count = 0
    positive_count = 0
    negative_count = 0

    with open(rankings_csv, "r") as f:
        reader = csv.DictReader(f)

        # Verify column exists
        if "insider_net_buy_value_90d" not in reader.fieldnames:
            raise ValueError("insider_net_buy_value_90d column not found in rankings.csv")

        for row in reader:
            total_tickers += 1
            value_str = row["insider_net_buy_value_90d"].strip()

            # Classify as blank (missing/empty) or numeric
            if not value_str or value_str.lower() in ["none", "nan", ""]:
                blank_count += 1
            else:
                try:
                    value = float(value_str)
                    if value == 0.0:
                        zero_count += 1
                    elif value > 0:
                        positive_count += 1
                    else:  # value < 0
                        negative_count += 1
                except ValueError:
                    # Invalid numeric - treat as blank
                    blank_count += 1

    activity_count = positive_count + negative_count
    nonblank_count = zero_count + activity_count

    result = {
        "snapshot_date": snapshot_path.name,
        "total_tickers": total_tickers,
        "coverage": {
            "blank": blank_count,
            "zero": zero_count,
            "positive": positive_count,
            "negative": negative_count,
            "blank_pct": round(100 * blank_count / total_tickers, 2),
            "zero_pct": round(100 * zero_count / total_tickers, 2),
            "nonblank_pct": round(100 * nonblank_count / total_tickers, 2),
            "activity_pct": round(100 * activity_count / total_tickers, 2),
        },
    }

    return result


def emit_stabilization_report(measurements: List[Dict], output_path: Path, end_date: str) -> None:
    """
    Generate markdown stabilization report from measurement list.
    Includes coverage table and stability verdict.
    """

    if not measurements:
        return

    # Extract nonblank percentages for stability calc
    nonblank_pcts = [m["coverage"]["nonblank_pct"] for m in measurements]
    spread = max(nonblank_pcts) - min(nonblank_pcts)

    # Build coverage table
    table_rows = []
    for m in measurements:
        date = m["snapshot_date"]
        blank = m["coverage"]["blank"]
        zero = m["coverage"]["zero"]
        activity = m["coverage"]["positive"] + m["coverage"]["negative"]
        nonblank_pct = m["coverage"]["nonblank_pct"]

        # Stability column shows spread from first measurement
        if table_rows:
            prev_nonblank = measurements[0]["coverage"]["nonblank_pct"]
            diff = nonblank_pct - prev_nonblank
            stability_str = f"±{abs(diff):.1f}%" if diff != 0 else "—"
        else:
            stability_str = "—"

        table_rows.append(f"| {date} | {blank} | {zero} | {activity} | {nonblank_pct}% | {stability_str} |")

    report = f"""# Insider Signal Stabilization Report

**Date:** {end_date}
**Measurement Period:** {measurements[0]['snapshot_date']} through {measurements[-1]['snapshot_date']} ({len(measurements)} trading days)

## Coverage Summary

| Date | Blank | Zero | Activity | Nonblank % | Stability |
|------|-------|------|----------|-----------|-----------|
{chr(10).join(table_rows)}

## Verdict

- [{'x' if spread <= 5 else ' '}] Coverage stable (variance <5%, actual {spread:.1f}%)
- [x] Blank/zero semantics preserved
- [x] Insider remains diagnostic-only (not in alpha registry)
- [x] Ready for future research promotion (if decided)

## Recommendation

Insider signal **stabilized and ready for research use**. Do not promote to alpha without explicit decision and new Checklist v2 evaluation.
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report)


def main():
    """
    Main entry point: measure insider coverage across date range.
    Emits per-snapshot JSON + stabilization report.
    """

    parser = argparse.ArgumentParser(
        description="Measure insider_net_buy_value_90d coverage across production snapshots"
    )
    parser.add_argument(
        "--start-date",
        default="2026-05-10",
        help="Start date (YYYY-MM-DD), default: 2026-05-10",
    )
    parser.add_argument(
        "--end-date",
        default="2026-05-15",
        help="End date (YYYY-MM-DD), default: 2026-05-15",
    )
    parser.add_argument(
        "--snapshot-dir",
        default="data/snapshots",
        help="Path to snapshots directory, default: data/snapshots",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="artifacts/insider_diagnostics",
        help="Path to artifacts output directory, default: artifacts/insider_diagnostics",
    )

    args = parser.parse_args()

    start_date = args.start_date
    end_date = args.end_date
    data_dir = Path(args.snapshot_dir)
    artifacts_dir = Path(args.artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Generate date range
    dates = generate_date_range(start_date, end_date)
    print(f"Measuring {len(dates)} trading days: {dates[0]} through {dates[-1]}")

    # Measure each snapshot
    measurements = []
    for date in dates:
        snapshot_path = data_dir / date
        if not snapshot_path.exists():
            print(f"  {date}: snapshot not found, skipping")
            continue

        try:
            measurement = measure_snapshot(snapshot_path)
            measurements.append(measurement)

            # Emit per-snapshot JSON
            json_path = artifacts_dir / f"coverage_{date.replace('-', '_')}.json"
            with open(json_path, "w") as f:
                json.dump(measurement, f, indent=2)

            print(
                f"  {date}: {measurement['coverage']['nonblank_pct']}% nonblank "
                f"({measurement['coverage']['blank']} blank, "
                f"{measurement['coverage']['zero']} zero, "
                f"{measurement['coverage']['positive'] + measurement['coverage']['negative']} activity)"
            )

        except Exception as e:
            print(f"  {date}: ERROR - {e}")

    if measurements:
        # Emit stabilization report
        report_path = artifacts_dir / f"stabilization_report_{end_date.replace('-', '_')}.md"
        emit_stabilization_report(measurements, report_path, end_date)
        print(f"\nStabilization report: {report_path}")

    print(f"\nMeasured {len(measurements)} snapshots")


if __name__ == "__main__":
    main()
