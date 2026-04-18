#!/usr/bin/env python3
"""Regenerate historical snapshots with PIT financials (pseudo-PIT v2).

Runs run_screen.py for each monthly snapshot date with --pit-mode degrade,
writing to data/snapshots_pit_v2/. Only runs dates not already present
in the output directory (idempotent).

Usage:
    python scripts/research/regenerate_pit_v2_snapshots.py
    python scripts/research/regenerate_pit_v2_snapshots.py --start 2023-01-01
    python scripts/research/regenerate_pit_v2_snapshots.py --dry-run
    python scripts/research/regenerate_pit_v2_snapshots.py --max-dates 5
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PIT_V2_DIR = PROJECT_ROOT / "data" / "snapshots_pit_v2"
PROD_DATA = PROJECT_ROOT / "production_data"
BUNDLES_DIR = PROJECT_ROOT / "data" / "bundles" / "PIT"
LOG_PATH = PROJECT_ROOT / "output" / "pit" / "regeneration_log.json"


def get_monthly_dates(start: str = "2020-01-01") -> list[str]:
    """Get one snapshot date per month (last available per month)."""
    by_month: dict[str, str] = {}
    for d in sorted(SNAPSHOTS_DIR.iterdir()):
        if not d.is_dir() or not (d / "rankings.csv").exists():
            continue
        name = d.name
        if "__" in name:  # skip staging dirs like 2026-04-02__pre_*
            continue
        if name < start:
            continue
        by_month[name[:7]] = name
    return sorted(by_month.values())


def already_done(date_str: str) -> bool:
    """Check if PIT v2 snapshot already exists for this date."""
    return (PIT_V2_DIR / date_str / "rankings.csv").exists()


def _resolve_data_dir(date_str: str) -> tuple[Path, str]:
    """Resolve the best data directory for a given date.

    Prefers archived PIT inputs from the production snapshot if available,
    falls back to current production_data/.
    Returns (data_dir, source_tag).
    """
    archived = SNAPSHOTS_DIR / date_str / "inputs"
    # Require at least universe.json to consider the archive usable
    if archived.exists() and (archived / "universe.json").exists():
        return archived, "archived"
    return PROD_DATA, "current"


def _resolve_institutional_source(date_str: str, data_dir: Path) -> str:
    """Report where institutional (13F) features will come from for this date.

    Diagnostic only — does not change behavior. Return values:
      - "archived"       : {data_dir}/coinvest_signals.json or holdings_detailed.json is the archived snapshot input
      - "bundle"         : a PIT bundle exists for this date (not currently consumed by regen; see docs/13F_BACKFILL_PLAN.md)
      - "bundle_nearby"  : a bundle exists within 95 days prior (usable by Option B in the plan)
      - "contaminated"   : will fall back to current production_data/holdings_detailed.json (pseudo-PIT)
    """
    if (data_dir / "coinvest_signals.json").exists() or (data_dir / "holdings_detailed.json").exists():
        if data_dir != PROD_DATA:
            return "archived"
    if (BUNDLES_DIR / date_str / "manifest.json").exists():
        return "bundle"
    # Look for a prior bundle within 95 days
    try:
        from datetime import date, timedelta

        target = date.fromisoformat(date_str)
        for delta in range(1, 96):
            candidate = (target - timedelta(days=delta)).isoformat()
            if (BUNDLES_DIR / candidate / "manifest.json").exists():
                return "bundle_nearby"
    except (ValueError, OSError):
        pass
    return "contaminated"


def _bundle_dir_for(date_str: str) -> Path | None:
    """Return the bundle dir for an exact date match, else None."""
    d = BUNDLES_DIR / date_str
    if (d / "manifest.json").exists():
        return d
    return None


def run_one(
    date_str: str,
    dry_run: bool = False,
    use_bundle: bool = False,
    out_dir: Path | None = None,
) -> dict:
    """Run a regen for one date. Returns status dict.

    When `use_bundle=True` and a PIT bundle exists for the exact date, uses
    `scripts/run_screen_from_bundle.py` (Option A). Otherwise subprocesses
    `run_screen.py --as-of-date` as before. `out_dir` defaults to PIT_V2_DIR.
    """
    if dry_run:
        return {"date": date_str, "status": "dry_run"}

    data_dir, data_source = _resolve_data_dir(date_str)
    institutional_source = _resolve_institutional_source(date_str, data_dir)
    effective_out = out_dir or PIT_V2_DIR

    bundle_dir = _bundle_dir_for(date_str) if use_bundle else None
    if bundle_dir is not None:
        exec_path = "bundle_native"
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "run_screen_from_bundle.py"),
            "--bundle-dir",
            str(bundle_dir),
            "--out-root",
            str(effective_out),
            "--pit-mode",
            "lenient",
        ]
    else:
        exec_path = "run_screen_direct"
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "run_screen.py"),
            "--as-of-date",
            date_str,
            "--data-dir",
            str(data_dir),
            "--pit-mode",
            "degrade",
            "--snapshot-dir",
            str(effective_out),
            "--no-clinical-filter",
            "--diagnostics",
            "none",
        ]

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(PROJECT_ROOT),
        )
        elapsed = time.time() - t0
        if result.returncode == 0:
            return {
                "date": date_str,
                "status": "ok",
                "data_source": data_source,
                "institutional_source": institutional_source,
                "exec_path": exec_path,
                "elapsed_s": round(elapsed, 1),
            }
        else:
            # Extract last few lines of stderr for diagnosis
            err_tail = result.stderr.strip().split("\n")[-5:]
            return {
                "date": date_str,
                "status": "error",
                "returncode": result.returncode,
                "exec_path": exec_path,
                "elapsed_s": round(elapsed, 1),
                "error_tail": err_tail,
            }
    except subprocess.TimeoutExpired:
        return {"date": date_str, "status": "timeout", "elapsed_s": 600}
    except Exception as e:
        return {"date": date_str, "status": "exception", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Regenerate PIT v2 snapshots")
    parser.add_argument("--start", default="2020-01-01", help="Start date")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-dates", type=int, default=0, help="Max dates to process (0=all)")
    parser.add_argument(
        "--use-bundle",
        action="store_true",
        help="Option A: when a PIT bundle exists for the date, call scripts/run_screen_from_bundle.py. "
        "Otherwise use the existing run_screen.py path.",
    )
    parser.add_argument(
        "--dates",
        default="",
        help="Comma-separated explicit date list to process (overrides monthly discovery)",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="Override output snapshot dir (default: data/snapshots_pit_v2)",
    )
    args = parser.parse_args()

    effective_out = Path(args.out_dir) if args.out_dir else PIT_V2_DIR

    if args.dates:
        dates = [d.strip() for d in args.dates.split(",") if d.strip()]
        todo = [d for d in dates if not (effective_out / d / "rankings.csv").exists()]
    else:
        dates = get_monthly_dates(args.start)
        todo = [d for d in dates if not (effective_out / d / "rankings.csv").exists()]
    done = [d for d in dates if (effective_out / d / "rankings.csv").exists()]

    print(f"Dates:         {len(dates)}")
    print(f"Already done:  {len(done)}")
    print(f"To process:    {len(todo)}")
    if args.use_bundle:
        print("Mode:          bundle-native (Option A) when bundle exists, run_screen fallback otherwise")
    if args.out_dir:
        print(f"Out dir:       {effective_out}")

    if args.max_dates > 0:
        todo = todo[: args.max_dates]
        print(f"Limited to:    {len(todo)}")

    if not todo:
        print("Nothing to do.")
        return

    effective_out.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    results = []
    n_ok = 0
    n_err = 0
    t_start = time.time()

    for i, date_str in enumerate(todo, 1):
        prefix = f"[{i}/{len(todo)}]"
        if args.dry_run:
            print(f"{prefix} {date_str} — dry run")
            results.append(run_one(date_str, dry_run=True))
            continue

        print(f"{prefix} {date_str} ...", end=" ", flush=True)
        r = run_one(date_str, use_bundle=args.use_bundle, out_dir=effective_out)
        results.append(r)

        if r["status"] == "ok":
            n_ok += 1
            src = r.get("data_source", "current")
            inst = r.get("institutional_source", "?")
            exe = r.get("exec_path", "?")
            print(f"OK ({r['elapsed_s']}s, exec={exe}, data={src}, inst={inst})")
        else:
            n_err += 1
            print(f"FAIL: {r['status']}")
            if "error_tail" in r:
                for line in r["error_tail"]:
                    print(f"    {line}")

    elapsed_total = time.time() - t_start

    # Institutional-source summary (diagnostic — see docs/13F_BACKFILL_PLAN.md)
    inst_counts: dict[str, int] = {}
    for r in results:
        if r.get("status") == "ok":
            tag = r.get("institutional_source", "?")
            inst_counts[tag] = inst_counts.get(tag, 0) + 1

    # Save log
    log = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_dates": len(dates),
        "processed": len(results),
        "ok": n_ok,
        "errors": n_err,
        "elapsed_total_s": round(elapsed_total, 1),
        "institutional_source_counts": inst_counts,
        "results": results,
    }
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)

    print(f"\nDone: {n_ok} ok, {n_err} errors in {elapsed_total:.0f}s")
    print(f"Log: {LOG_PATH}")


if __name__ == "__main__":
    main()
