#!/usr/bin/env python3
"""Full-pipeline A/B evaluation for sizing-only features.

Unlike rerank_snapshots.py (which only re-sorts), this script re-runs the
full run_screen.py pipeline for each historical date with a candidate
ruleset, then evaluates forward returns. This is needed for features that
affect portfolio weights (catalyst_tilt, clinical_sizing) rather than sort
order.

Usage:
    python scripts/research/eval_sizing_ab.py \
        --ruleset production_data/decision_rulesets/research_catalyst_tilt_on.json \
        --date-from 2025-06-01 --date-to 2025-12-31 \
        --out-root data/snapshots_fullpipeline_catalyst_tilt \
        --data-dir production_data \
        [--horizons 20,63,126] [--top-k 20] [--dry-run]

Workflow:
    1. For each snapshot date in [date-from, date-to]:
       a. Run run_screen.py --as-of-date {date} --ruleset {candidate}
       b. Save snapshot to out-root/{date}/
    2. Run eval_forward_returns.py on the generated snapshots
    3. Print summary comparison vs baseline
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _discover_dates(snapshot_root: Path, date_from: str, date_to: str) -> list[str]:
    """Find existing snapshot dates in range to know which dates to evaluate."""
    import re

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    all_dates = sorted(d.name for d in snapshot_root.iterdir() if d.is_dir() and date_re.match(d.name))
    return [d for d in all_dates if date_from <= d <= date_to]


def _run_screen(
    as_of_date: str,
    data_dir: Path,
    ruleset_path: Path,
    snapshot_dir: Path,
    extra_args: list[str] | None = None,
) -> bool:
    """Run run_screen.py for a single date. Returns True on success."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "run_screen.py"),
        "--as-of-date",
        as_of_date,
        "--data-dir",
        str(data_dir),
        "--ruleset",
        str(ruleset_path),
        "--snapshot-dir",
        str(snapshot_dir),
        "--decision-mode",
        "phase2",
        "--ranking-mode",
        "decision",
        "--pit-mode",
        "degrade",
        "--no-enhancements",  # Speed: skip momentum/alpha enrichment
    ]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        print(f"  FAIL {as_of_date}: exit {result.returncode}")
        if result.stderr:
            # Print last 5 lines of stderr for diagnosis
            for line in result.stderr.strip().split("\n")[-5:]:
                print(f"    {line}")
        return False
    return True


def _run_eval(
    snapshot_root: Path,
    out_dir: Path,
    ruleset_path: Path,
    date_from: str,
    date_to: str,
    horizons: str = "20,63,126",
    top_k: int = 20,
) -> dict | None:
    """Run eval_forward_returns.py and return summary dict."""
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "eval_forward_returns.py"),
        "--snapshot-root",
        str(snapshot_root),
        "--date-from",
        date_from,
        "--date-to",
        date_to,
        "--horizons",
        horizons,
        "--top-k",
        str(top_k),
        "--out-dir",
        str(out_dir),
        "--ruleset",
        str(ruleset_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        print(f"  Eval failed: {result.stderr[-500:]}")
        return None

    summary_path = out_dir / "summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            return json.load(f)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ruleset", required=True, help="Candidate ruleset JSON path")
    parser.add_argument("--date-from", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--date-to", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--out-root", required=True, help="Output snapshot directory")
    parser.add_argument("--data-dir", default="production_data", help="Data directory for run_screen.py")
    parser.add_argument(
        "--reference-snapshots", default="data/snapshots", help="Existing baseline snapshot root (for date discovery)"
    )
    parser.add_argument("--horizons", default="20,63,126", help="Forward-return horizons")
    parser.add_argument("--top-k", type=int, default=20, help="Top-K for IC evaluation")
    parser.add_argument("--dry-run", action="store_true", help="Print dates without running")
    parser.add_argument("--max-dates", type=int, default=0, help="Limit number of dates (0=all)")
    parser.add_argument("--skip-screen", action="store_true", help="Skip screen runs, only eval")
    args = parser.parse_args()

    out_root = Path(args.out_root)
    ref_root = Path(args.reference_snapshots)
    data_dir = Path(args.data_dir)
    ruleset_path = Path(args.ruleset)

    if not ruleset_path.exists():
        print(f"ERROR: Ruleset not found: {ruleset_path}")
        sys.exit(1)

    # Discover dates from reference snapshots
    dates = _discover_dates(ref_root, args.date_from, args.date_to)
    if args.max_dates > 0:
        dates = dates[: args.max_dates]

    print(f"Full-pipeline A/B eval: {len(dates)} dates, {args.date_from} to {args.date_to}")
    print(f"  Ruleset: {ruleset_path}")
    print(f"  Output:  {out_root}")

    if args.dry_run:
        for d in dates:
            print(f"  {d}")
        print(f"\n{len(dates)} dates would be processed.")
        return

    # Step 1: Run screen for each date
    if not args.skip_screen:
        print(f"\n[1/2] Running full screen pipeline for {len(dates)} dates...")
        ok, fail = 0, 0
        for i, d in enumerate(dates):
            existing = out_root / d / "rankings.csv"
            if existing.exists():
                print(f"  [{i+1}/{len(dates)}] {d}: already exists, skipping")
                ok += 1
                continue
            print(f"  [{i+1}/{len(dates)}] {d}: running...", end="", flush=True)
            success = _run_screen(d, data_dir, ruleset_path, out_root)
            if success:
                ok += 1
                print(" OK")
            else:
                fail += 1
        print(f"  Screen complete: {ok} ok, {fail} failed")
    else:
        print("\n[1/2] Skipping screen runs (--skip-screen)")

    # Step 2: Evaluate forward returns
    eval_dir = out_root / "_eval"
    print("\n[2/2] Evaluating forward returns...")
    summary = _run_eval(
        out_root,
        eval_dir,
        ruleset_path,
        args.date_from,
        args.date_to,
        args.horizons,
        args.top_k,
    )

    if summary:
        bh = summary.get("by_horizon", {})
        print(f"\n  {'Horizon':>8s}  {'IC':>8s}  {'t-stat':>8s}  {'Turnover':>8s}  {'GrossRet':>10s}  {'n':>4s}")
        for h in sorted(bh.keys(), key=int):
            d = bh[h]
            t_stat = d.get("ic_t_stat")
            t_str = f"{t_stat:>8.3f}" if t_stat is not None else "     N/A"
            print(
                f"  {h+'d':>8s}  {d['mean_ic']:>8.4f}  {t_str}  {d['mean_turnover']:>8.4f}  {d['mean_gross_return']:>10.4f}  {d['n_dates']:>4d}"
            )
        print(f"\n  Full results: {eval_dir}/summary.json")
    else:
        print("  Evaluation failed or no data.")


if __name__ == "__main__":
    main()
