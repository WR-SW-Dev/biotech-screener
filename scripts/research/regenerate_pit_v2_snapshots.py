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
PIT_13F_CACHE = PROJECT_ROOT / "data" / "caches" / "sec_13f" / "PIT"
STAGING_ROOT = PROJECT_ROOT / "data" / "staging" / "pit_regen"
LOG_PATH = PROJECT_ROOT / "output" / "pit" / "regeneration_log.json"

# Minimum 13F manager coverage required to consider a date PIT-stageable.
# Below this, the cache isn't representative enough to improve over the
# current-holdings fallback — label as contaminated instead.
PIT_STAGE_MIN_COVERAGE_PCT = 50.0


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
      - "pit_13f_staged" : data_dir is a staging dir with a PIT-derived coinvest_signals.json overlay
      - "archived"       : {data_dir}/coinvest_signals.json or holdings_detailed.json is the archived snapshot input
      - "bundle"         : a PIT bundle exists for this date (Option A)
      - "bundle_nearby"  : a bundle exists within 95 days prior (Option B with lag)
      - "contaminated"   : will fall back to current production_data/holdings_detailed.json (pseudo-PIT)
    """
    # If data_dir is a Option B-lite staging dir, prefer that label.
    try:
        if data_dir.is_relative_to(STAGING_ROOT):
            return "pit_13f_staged"
    except AttributeError:
        # Python <3.9 doesn't have is_relative_to; fall back to string compare
        if str(data_dir).startswith(str(STAGING_ROOT)):
            return "pit_13f_staged"
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


def _pit_13f_cache_coverage(date_str: str) -> float | None:
    """Return coverage_pct of the PIT 13F cache for this date, or None if missing."""
    idx = PIT_13F_CACHE / date_str / "index.json"
    if not idx.exists():
        return None
    try:
        data = json.load(open(idx))
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("schema_version") != "sec_13f_pit_index.v1":
        return None
    return float(data.get("coverage_pct", 0) or 0)


def stage_data_dir_with_pit_institutional(
    date_str: str,
    base_data_dir: Path,
) -> tuple[Path, str] | tuple[None, str]:
    """Materialize a per-date staging data_dir with PIT-correct institutional features.

    Reuses `scripts/build_coinvest_features_from_13f.py` (no new conversion logic).
    Output staging dir contains:
      - coinvest_signals.json : UNWRAPPED dict of per-ticker features from the PIT cache
      - symlinks to every file in base_data_dir (so run_screen.py sees everything else)

    Returns (staging_path, source_tag) where source_tag is one of:
      - "pit_13f_staged"  : cache coverage >= PIT_STAGE_MIN_COVERAGE_PCT, builder succeeded
      - "skipped_low_coverage"
      - "skipped_no_cache"
      - "skipped_builder_error"
    If staging was skipped, returns (None, source_tag).
    """
    cov = _pit_13f_cache_coverage(date_str)
    if cov is None:
        return None, "skipped_no_cache"
    if cov < PIT_STAGE_MIN_COVERAGE_PCT:
        return None, "skipped_low_coverage"

    staging = STAGING_ROOT / date_str
    staging.mkdir(parents=True, exist_ok=True)
    out_path = staging / "coinvest_signals.json"
    builder_raw = staging / "_builder_coinvest_features.json"

    # Idempotent: skip builder if output already exists
    if not out_path.exists():
        universe_src = base_data_dir / "universe.json"
        if not universe_src.exists():
            universe_src = PROD_DATA / "universe.json"
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "build_coinvest_features_from_13f.py"),
            "--as-of-date",
            date_str,
            "--cache-root",
            str(PIT_13F_CACHE),
            "--out",
            str(builder_raw),
            "--universe",
            str(universe_src),
            "--cusip-map",
            str(PROD_DATA / "cusip_static_map.json"),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0 or not builder_raw.exists():
            return None, "skipped_builder_error"

        try:
            with open(builder_raw) as f:
                wrapped = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None, "skipped_builder_error"

        tickers = wrapped.get("tickers", wrapped if isinstance(wrapped, dict) else {})
        with open(out_path, "w") as f:
            json.dump(tickers, f)

    # Shadow everything else from base_data_dir using hardlinks (run_screen.py's
    # security layer rejects symlinks). Fall back to recursive hardlink for
    # directories, and to file copy only as a last resort for small files.
    import os
    import shutil

    def _shadow(src: Path, dst: Path) -> None:
        if dst.exists() or dst.is_symlink():
            return
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for child in src.iterdir():
                _shadow(child, dst / child.name)
            return
        try:
            os.link(str(src), str(dst))
        except OSError:
            # Cross-filesystem or permission issue: copy small files only.
            if src.is_file() and src.stat().st_size < 50 * 1024 * 1024:
                shutil.copy2(str(src), str(dst))

    for item in base_data_dir.iterdir():
        if item.name == "coinvest_signals.json":
            continue
        _shadow(item, staging / item.name)

    return staging, "pit_13f_staged"


def run_one(
    date_str: str,
    dry_run: bool = False,
    use_bundle: bool = False,
    stage_pit_institutional: bool = False,
    out_dir: Path | None = None,
) -> dict:
    """Run a regen for one date. Returns status dict.

    When `use_bundle=True` and a PIT bundle exists for the exact date, uses
    `scripts/run_screen_from_bundle.py` (Option A). Otherwise subprocesses
    `run_screen.py --as-of-date` as before.

    When `stage_pit_institutional=True` and a PIT 13F cache exists for this
    date with sufficient coverage, builds a staging data_dir that overlays a
    PIT-derived `coinvest_signals.json` on top of symlinks to the base data
    dir (Option B-lite). Mutually exclusive with `use_bundle`.

    `out_dir` defaults to PIT_V2_DIR.
    """
    if dry_run:
        return {"date": date_str, "status": "dry_run"}

    data_dir, data_source = _resolve_data_dir(date_str)
    effective_out = out_dir or PIT_V2_DIR
    stage_result: str | None = None

    # Option B-lite: stage a PIT-derived coinvest_signals.json over symlinks.
    if stage_pit_institutional and not use_bundle:
        staged_dir, stage_tag = stage_data_dir_with_pit_institutional(date_str, data_dir)
        stage_result = stage_tag
        if staged_dir is not None:
            data_dir = staged_dir
            data_source = "pit_13f_staged"

    institutional_source = _resolve_institutional_source(date_str, data_dir)

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
            out = {
                "date": date_str,
                "status": "ok",
                "data_source": data_source,
                "institutional_source": institutional_source,
                "exec_path": exec_path,
                "elapsed_s": round(elapsed, 1),
            }
            if stage_result:
                out["stage_result"] = stage_result
            return out
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
                "stage_result": stage_result,
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
        "--stage-pit-institutional",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Option B-lite (default ON as of 2026-04-17 19-date quarter-end validation): "
        "when a PIT 13F cache exists with >=50%% manager coverage for this date, build a "
        "staging data_dir with a PIT-derived coinvest_signals.json overlay before calling "
        "run_screen.py. Preserves full current-model output schema. Pass "
        "--no-stage-pit-institutional to disable and fall back to current holdings_detailed.",
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
    if args.stage_pit_institutional:
        print("Mode:          PIT 13F staging (Option B-lite) when cache coverage >= 50%, current path otherwise")
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
        r = run_one(
            date_str,
            use_bundle=args.use_bundle,
            stage_pit_institutional=args.stage_pit_institutional,
            out_dir=effective_out,
        )
        results.append(r)

        if r["status"] == "ok":
            n_ok += 1
            src = r.get("data_source", "current")
            inst = r.get("institutional_source", "?")
            exe = r.get("exec_path", "?")
            stg = r.get("stage_result")
            stg_str = f", stage={stg}" if stg else ""
            print(f"OK ({r['elapsed_s']}s, exec={exe}, data={src}, inst={inst}{stg_str})")
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
