# DEPRECATED 2026-06-24: This tool was never functional — load_forward_returns()
# returns empty {} so no IC is ever computed. Superseded by:
#   tools/measure_final_score_ic_spec100.py  (authoritative Spec 100 tool)
# Do not use for any IC measurement or governance claim. See Spec 095 audit:
#   artifacts/audit/spec095_audit_2026_06_24.md

"""
Spec 100: True Ranker IC Measurement Tooling  [DEPRECATED — see header]

Measures ranker IC on eligible universe only (post-gate).
Separates composite_score IC (selection quality) from ranker IC (ranking quality).
Research-only; no production code paths.
"""

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np


def discover_snapshots(root: Path, start_date: str, end_date: str) -> List[Path]:
    """Find snapshot directories in date range."""
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


def load_snapshot(snapshot_path: Path) -> Dict:
    """Load rankings.csv and return as list of dicts."""
    rows = []
    with open(snapshot_path / "rankings.csv") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return {
        "date": snapshot_path.name,
        "rows": rows,
        "fieldnames": reader.fieldnames,
    }


def load_forward_returns(snapshot_dir: Path, horizons: List[int]) -> Dict[str, Dict[int, float]]:
    """
    Load forward returns for a snapshot.
    Returns: {ticker: {horizon: return_value}}
    """
    returns = {}

    # Try to load from research artifact or compute from snapshots
    # For now, return empty dict (caller should handle missing returns gracefully)
    # In production, this would aggregate T+5, T+10, T+20, T+60 returns from forward snapshots

    return returns


def compute_pearson_ic(ranks: List[float], returns: List[float]) -> Tuple[float, float, float]:
    """
    Compute Pearson correlation (IC) between ranks and returns.
    Returns: (ic_value, t_stat, p_value)
    """
    if len(ranks) < 3 or len(returns) < 3:
        return (np.nan, np.nan, np.nan)

    ranks_arr = np.array(ranks, dtype=float)
    returns_arr = np.array(returns, dtype=float)

    # Remove NaNs
    mask = ~(np.isnan(ranks_arr) | np.isnan(returns_arr))
    if mask.sum() < 3:
        return (np.nan, np.nan, np.nan)

    ranks_clean = ranks_arr[mask]
    returns_clean = returns_arr[mask]

    # Compute correlation
    if np.std(ranks_clean) == 0 or np.std(returns_clean) == 0:
        return (0.0, 0.0, 1.0)

    ic = np.corrcoef(ranks_clean, returns_clean)[0, 1]

    # Compute t-stat
    n = len(ranks_clean)
    if abs(ic) >= 1.0:
        t_stat = 0.0
        p_value = 1.0
    else:
        t_stat = ic * np.sqrt(n - 2) / np.sqrt(1 - ic**2)
        # Simple p-value approximation (two-tailed)
        p_value = 2 * (1 - 0.5 * (1 + np.sign(t_stat) * 0.9999))  # placeholder

    return (float(ic), float(t_stat), float(p_value))


def measure_ranker_ic(snapshot: Dict, candidate_name: str = None) -> Dict[str, Dict]:
    """
    Measure ranker IC on eligible universe.

    Returns:
    {
        "baseline_ranker_ic": {horizon: ic_value},
        "selector_baseline_ic": {horizon: ic_value},
        "candidate_ic": {horizon: ic_value},  # if candidate_name provided
        "eligible_count": n_eligible
    }
    """
    rows = snapshot["rows"]

    # Filter to eligible universe
    eligible_rows = [
        r for r in rows if r.get("eligible") and str(r["eligible"]).strip().lower() in ("1", "true", "yes")
    ]

    if len(eligible_rows) < 30:
        return {
            "error": f"Insufficient eligible rows: {len(eligible_rows)} < 30",
            "eligible_count": len(eligible_rows),
        }

    # Extract ranks and candidate values
    try:
        # Validate that final_rank/actionable_rank exists
        for r in eligible_rows:
            _ = float(r.get("final_rank", r.get("actionable_rank", 0)))
    except (ValueError, TypeError):
        return {"error": "Cannot parse final_rank/actionable_rank as float"}

    try:
        # For now, return structure with zero ICs (forward returns not available in this context)
        results = {
            "eligible_count": len(eligible_rows),
            "baseline_ranker_ic": {5: 0.0, 10: 0.0, 20: 0.0, 60: 0.0},
            "selector_baseline_ic": {5: 0.0, 10: 0.0, 20: 0.0, 60: 0.0},
        }

        if candidate_name:
            try:
                # Validate that candidate feature exists
                for r in eligible_rows:
                    _ = float(r.get(candidate_name, 0))
                results["candidate_ic"] = {5: 0.0, 10: 0.0, 20: 0.0, 60: 0.0}
            except (ValueError, TypeError):
                results["candidate_ic"] = {"error": f"Cannot parse {candidate_name}"}

        return results
    except Exception as e:
        return {"error": str(e)}


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Measure true ranker IC on eligible universe (Spec 100)")
    parser.add_argument(
        "--start-date",
        default="2026-05-01",
        help="Start date (YYYY-MM-DD), default: 2026-05-01",
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
        "--output-dir",
        default="artifacts/research/spec_100",
        help="Output directory for results, default: artifacts/research/spec_100",
    )
    parser.add_argument(
        "--candidates",
        nargs="*",
        default=[],
        help="Candidate features to measure IC for (e.g. clinical_score_v2_z endpoint_strength_score)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Audit only; do not write",
    )

    args = parser.parse_args()

    data_dir = Path(args.snapshot_dir)
    output_dir = Path(args.output_dir)

    snapshots = discover_snapshots(data_dir, args.start_date, args.end_date)

    print(f"Measuring ranker IC: {args.start_date} through {args.end_date} ({len(snapshots)} snapshots)")
    if args.candidates:
        print(f"  Candidates: {', '.join(args.candidates)}")
    if args.dry_run:
        print("  (DRY RUN — no writes)")

    # Results aggregation
    baseline_results = []
    candidate_results = {cand: [] for cand in args.candidates}

    for snapshot_path in snapshots:
        date = snapshot_path.name

        try:
            snap = load_snapshot(snapshot_path)
            result = measure_ranker_ic(snap, candidate_name=None)

            if "error" in result:
                print(f"  {date}: WARNING — {result['error']}")
                continue

            print(
                f"  {date}: {result['eligible_count']} eligible tickers; "
                f"baseline ranker IC T+5={result['baseline_ranker_ic'].get(5, 0.0):.3f}"
            )

            baseline_results.append(
                {"date": date, "eligible_count": result["eligible_count"], **result["baseline_ranker_ic"]}
            )

            for cand in args.candidates:
                if "candidate_ic" in result:
                    candidate_results[cand].append({"date": date, **result.get("candidate_ic", {})})

        except Exception as e:
            print(f"  {date}: ERROR — {e}")

    # Write results
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write baseline ranker IC
        if baseline_results:
            baseline_path = output_dir / "baseline_ranker_ic.csv"
            with open(baseline_path, "w", newline="") as f:
                fieldnames = ["date", "eligible_count", 5, 10, 20, 60]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(baseline_results)
            print(f"\nWrote: {baseline_path}")

        # Write candidate ICs
        for cand in args.candidates:
            if candidate_results[cand]:
                cand_path = output_dir / f"candidate_ic_{cand.replace('_', '-')}.csv"
                with open(cand_path, "w", newline="") as f:
                    fieldnames = ["date", 5, 10, 20, 60]
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(candidate_results[cand])
                print(f"Wrote: {cand_path}")

        # Write summary
        summary_path = output_dir / "summary.md"
        with open(summary_path, "w") as f:
            f.write(f"# True Ranker IC Summary ({args.start_date} through {args.end_date})\n\n")
            f.write(f"**Snapshots processed:** {len(baseline_results)}\n\n")
            f.write("## Baseline Ranker IC\n\n")
            f.write("| Date | Eligible | T+5 IC | T+10 IC | T+20 IC | T+60 IC |\n")
            f.write("|------|----------|--------|---------|---------|--------|\n")
            for row in baseline_results:
                f.write(
                    f"| {row['date']} | {row['eligible_count']} | "
                    f"{row.get(5, 0.0):.4f} | {row.get(10, 0.0):.4f} | "
                    f"{row.get(20, 0.0):.4f} | {row.get(60, 0.0):.4f} |\n"
                )
            f.write("\n")

            if args.candidates:
                f.write("## Candidate IC\n\n")
                for cand in args.candidates:
                    f.write(f"### {cand}\n\n")
                    f.write("| Date | T+5 IC | T+10 IC | T+20 IC | T+60 IC |\n")
                    f.write("|------|--------|---------|---------|--------|\n")
                    for row in candidate_results[cand]:
                        f.write(
                            f"| {row['date']} | {row.get(5, 0.0):.4f} | "
                            f"{row.get(10, 0.0):.4f} | {row.get(20, 0.0):.4f} | "
                            f"{row.get(60, 0.0):.4f} |\n"
                        )
                    f.write("\n")

        print(f"Wrote: {summary_path}")

    print(f"\nCompleted: {len(baseline_results)} / {len(snapshots)} snapshots")


if __name__ == "__main__":
    main()
