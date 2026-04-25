#!/usr/bin/env python3
"""onboard_manager.py — single-command 13F manager onboarding.

Wires the four steps of adding a new 13F filer into one deterministic flow:
  1. Append entry to production_data/manager_registry.json
  2. Backfill PIT 13F cache across every existing data/caches/sec_13f/PIT/<date>/
  3. Warm current as-of date (defaults to today)
  4. Run tools/test_manager_integration.py and print 6/6 gate status

Use any --skip-* flag to re-run individual steps.

Usage:
    python tools/onboard_manager.py \\
        --cik 1802528 \\
        --name "Fairmount Funds Management" \\
        --aum-b 1.3 \\
        --style concentrated_clinical_stage \\
        --tier elite_core \\
        --notes "Peter Harwin / Tommy Salzmann, concentrated biotech, 13 holdings"

    # Already in registry, just backfill + test:
    python tools/onboard_manager.py --cik 1802528 --skip-registry
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from warm_13f_cache import warm_13f_cache  # noqa: E402

REGISTRY_PATH = REPO_ROOT / "production_data" / "manager_registry.json"
PIT_ROOT = REPO_ROOT / "data" / "caches" / "sec_13f" / "PIT"
SNAPSHOTS_ROOT = REPO_ROOT / "data" / "snapshots"
PENDING_COHORT_FILE = REPO_ROOT / "production_data" / "cohort_pending.json"
ACCEPTANCE_TEST = REPO_ROOT / "tools" / "test_manager_integration.py"

VALID_TIERS = {"elite_core", "conditional"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("onboard_manager")


def _normalize_cik(cik: str) -> str:
    return cik.lstrip("0").zfill(10)


def add_to_registry(
    cik: str,
    name: str,
    aum_b: float,
    style: str,
    tier: str,
    notes: Optional[str] = None,
) -> bool:
    """Append manager to registry. Returns True if added, False if already present."""
    if tier not in VALID_TIERS:
        raise ValueError(f"tier must be one of {VALID_TIERS}, got {tier!r}")

    cik_padded = _normalize_cik(cik)

    with open(REGISTRY_PATH, encoding="utf-8") as f:
        registry = json.load(f)

    # Check for duplicate across all tiers
    for t, entries in registry.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and _normalize_cik(entry.get("cik", "")) == cik_padded:
                logger.info(
                    f"Manager CIK {cik_padded} already in registry tier {t!r} as {entry.get('name')!r} — skipping registry update"
                )
                return False

    new_entry: Dict[str, Any] = {
        "cik": cik_padded,
        "name": name,
        "aum_b": aum_b,
        "style": style,
    }
    if notes:
        new_entry["notes"] = notes

    registry.setdefault(tier, []).append(new_entry)

    # Update metadata
    if tier == "elite_core":
        total = sum(m.get("aum_b", 0) for m in registry["elite_core"] if isinstance(m, dict))
        registry.setdefault("metadata", {})["total_elite_aum_b"] = round(total, 2)
    registry.setdefault("metadata", {})["last_updated"] = date.today().isoformat()

    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    logger.info(f"Added {name!r} (CIK {cik_padded}) to {tier} tier")
    return True


def backfill_history(
    cik: str,
    *,
    elite_only: bool = True,
    filings_lookback_n: int = 40,
    max_workers: int = 4,
) -> Dict[str, int]:
    """Walk every existing PIT dir and warm the manager at each as-of date.

    Returns counts: {dates_total, dates_with_filing}.
    """
    cik_padded = _normalize_cik(cik)

    if not PIT_ROOT.exists():
        raise RuntimeError(f"PIT root does not exist: {PIT_ROOT}")

    existing_dates = sorted(d.name for d in PIT_ROOT.iterdir() if d.is_dir() and DATE_RE.match(d.name))
    if not existing_dates:
        logger.warning("No existing PIT dirs to backfill")
        return {"dates_total": 0, "dates_with_filing": 0}

    logger.info(
        f"Backfill: {cik_padded} across {len(existing_dates)} PIT dirs ({existing_dates[0]} → {existing_dates[-1]})"
    )

    n_with_filing = 0
    for as_of_str in existing_dates:
        as_of = date.fromisoformat(as_of_str)
        out_dir = PIT_ROOT / as_of_str
        index = warm_13f_cache(
            as_of_date=as_of,
            out_dir=out_dir,
            elite_only=elite_only,
            max_workers=max_workers,
            ciks_filter={cik_padded},
            filings_lookback_n=filings_lookback_n,
        )
        for m in index.get("managers", []):
            if m["manager_cik"] == cik_padded and m.get("selected"):
                n_with_filing += 1
                break

    return {"dates_total": len(existing_dates), "dates_with_filing": n_with_filing}


def warm_current(cik: str, *, elite_only: bool = True) -> bool:
    """Warm cache for today's date (creates new PIT dir if needed)."""
    cik_padded = _normalize_cik(cik)
    today = date.today()
    out_dir = PIT_ROOT / today.isoformat()
    is_new_dir = not out_dir.exists()
    index = warm_13f_cache(
        as_of_date=today,
        out_dir=out_dir,
        elite_only=elite_only,
        ciks_filter={cik_padded},
    )
    if is_new_dir:
        logger.info(f"Created new PIT dir for current date: {out_dir}")
    for m in index.get("managers", []):
        if m["manager_cik"] == cik_padded and m.get("selected"):
            return True
    return False


def run_acceptance_test(cik: str) -> int:
    """Run tools/test_manager_integration.py --cik {cik}. Returns process exit code."""
    cik_padded = _normalize_cik(cik)
    cmd = [sys.executable, str(ACCEPTANCE_TEST), "--cik", cik_padded]
    logger.info(f"Running acceptance test: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return proc.returncode


def emit_cohort_quarantine(
    cik: str,
    name: str,
) -> None:
    """Emit/update cohort-change quarantine markers.

    Writes two artifacts:
      1. ``production_data/cohort_pending.json`` — marker the next production
         screen run should consume (still TODO: integrate into run_screen.py).
      2. ``data/snapshots/<today>/cohort_state.json`` — if a snapshot dir exists
         for today, append the new manager so the contamination is documented
         on the affected snapshot directly.

    The deltas in the affected snapshot's rankings.csv are not decision-grade
    until the NEXT snapshot is produced (which will compare like-for-like
    against this snapshot's cohort).
    """
    cik_padded = _normalize_cik(cik)
    today = date.today().isoformat()

    # --- 1. production_data/cohort_pending.json (consumed by next prod run) ---
    if PENDING_COHORT_FILE.exists():
        try:
            pending = json.loads(PENDING_COHORT_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pending = {}
    else:
        pending = {}

    pending.setdefault("schema_version", "cohort_pending.v1")
    pending["pending_since"] = pending.get("pending_since") or today
    pending.setdefault("new_manager_ciks", [])
    pending.setdefault("new_manager_names", [])
    if cik_padded not in pending["new_manager_ciks"]:
        pending["new_manager_ciks"].append(cik_padded)
        pending["new_manager_names"].append(name)
    pending["last_addition"] = today

    PENDING_COHORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_COHORT_FILE.write_text(json.dumps(pending, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info(f"  cohort_pending: appended CIK {cik_padded} → {PENDING_COHORT_FILE.relative_to(REPO_ROOT)}")

    # --- 2. data/snapshots/<today>/cohort_state.json (already-built snapshot, if any) ---
    today_snap = SNAPSHOTS_ROOT / today
    if not today_snap.exists():
        logger.info(f"  cohort_state: no snapshot at {today_snap.relative_to(REPO_ROOT)} yet — pending marker only")
        return

    state_path = today_snap / "cohort_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    else:
        state = {}

    state.setdefault("schema_version", "cohort_state.v1")
    state["snapshot_date"] = today
    state["institutional_cohort_changed"] = True
    state.setdefault("new_manager_ciks", [])
    state.setdefault("new_manager_names", [])
    if cik_padded not in state["new_manager_ciks"]:
        state["new_manager_ciks"].append(cik_padded)
        state["new_manager_names"].append(name)
    state.setdefault(
        "validity",
        {
            "coinvest_score_z_valid": True,
            "coinvest_score_z_note": "Empirically a small renormalization shift only.",
            "inst_delta_z_valid": False,
            "inst_delta_z_note": "Artificially inflated: new managers' existing holdings appear as 'new institutional buys' against a prior snapshot built with a smaller cohort.",
            "rank_delta_valid": False,
            "rank_delta_note": "Selector_score weights inst_delta_z, so rank deltas vs prior snapshot are not decision-grade until the next snapshot compares like-for-like cohorts.",
        },
    )

    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info(
        f"  cohort_state: updated {state_path.relative_to(REPO_ROOT)} ({len(state['new_manager_ciks'])} new manager(s) flagged)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Onboard a new 13F manager: registry + backfill + test")
    parser.add_argument("--cik", required=True, help="Manager CIK (will be zero-padded to 10 digits)")
    parser.add_argument("--name", help="Display name (required unless --skip-registry)")
    parser.add_argument("--aum-b", type=float, help="AUM in $B (required unless --skip-registry)")
    parser.add_argument(
        "--style", help="Style label, e.g. concentrated_clinical_stage (required unless --skip-registry)"
    )
    parser.add_argument(
        "--tier", choices=sorted(VALID_TIERS), default="elite_core", help="Registry tier (default: elite_core)"
    )
    parser.add_argument("--notes", default=None, help='Free-form notes (auto-prefixed with "Added YYYY-MM-DD.")')
    parser.add_argument("--skip-registry", action="store_true", help="Skip registry update (manager already added)")
    parser.add_argument("--skip-backfill", action="store_true", help="Skip historical PIT backfill")
    parser.add_argument("--skip-current", action="store_true", help="Skip warming current as-of date")
    parser.add_argument("--skip-test", action="store_true", help="Skip acceptance test at end")
    parser.add_argument(
        "--skip-quarantine",
        action="store_true",
        help="Skip emitting cohort_state.json + cohort_pending.json markers (rarely correct — only for re-runs that didn't change the registry)",
    )
    parser.add_argument(
        "--filings-lookback-n", type=int, default=40, help="Filings lookback for backfill (default: 40 ≈ 10y quarterly)"
    )
    args = parser.parse_args()

    cik_padded = _normalize_cik(args.cik)
    print(f"\n=== Onboarding manager CIK {cik_padded} ===\n")

    # Step 1: registry
    if not args.skip_registry:
        missing = [k for k in ("name", "aum_b", "style") if getattr(args, k.replace("-", "_")) is None]
        if missing:
            parser.error(f"--{', --'.join(missing)} required unless --skip-registry")
        notes = args.notes
        if notes:
            today = date.today().isoformat()
            if not notes.startswith(f"Added {today}"):
                notes = f"Added {today}. {notes}"
        added = add_to_registry(
            cik=cik_padded,
            name=args.name,
            aum_b=args.aum_b,
            style=args.style,
            tier=args.tier,
            notes=notes,
        )
        print(f"  [STEP 1] registry: {'ADDED' if added else 'ALREADY PRESENT'}")
    else:
        print("  [STEP 1] registry: SKIPPED")

    # Step 2: backfill
    if not args.skip_backfill:
        result = backfill_history(cik=cik_padded, filings_lookback_n=args.filings_lookback_n)
        print(f"  [STEP 2] backfill: {result['dates_with_filing']}/{result['dates_total']} PIT dates have a filing")
    else:
        print("  [STEP 2] backfill: SKIPPED")

    # Step 3: warm current
    if not args.skip_current:
        ok = warm_current(cik=cik_padded)
        print(f"  [STEP 3] current: {'OK' if ok else 'NO_FILING'} (today={date.today().isoformat()})")
    else:
        print("  [STEP 3] current: SKIPPED")

    # Step 3.5: cohort-change quarantine markers
    # Always emit (even if --skip-* flags were passed) — the registry is changed
    # and downstream consumers need to know inst_delta/rank deltas are not
    # decision-grade for the next snapshot.
    if not args.skip_quarantine:
        # Best-effort: prefer the registry-supplied name, else look it up
        name = args.name
        if not name:
            try:
                with open(REGISTRY_PATH, encoding="utf-8") as f:
                    reg = json.load(f)
                for entries in reg.values():
                    if not isinstance(entries, list):
                        continue
                    for e in entries:
                        if isinstance(e, dict) and _normalize_cik(e.get("cik", "")) == cik_padded:
                            name = e.get("name", cik_padded)
                            break
                    if name:
                        break
            except (OSError, json.JSONDecodeError):
                name = cik_padded
        emit_cohort_quarantine(cik=cik_padded, name=name or cik_padded)
        print("  [STEP 3.5] cohort quarantine: EMITTED")
    else:
        print("  [STEP 3.5] cohort quarantine: SKIPPED")

    # Step 4: acceptance test
    if not args.skip_test:
        print("  [STEP 4] acceptance test:")
        rc = run_acceptance_test(cik=cik_padded)
        return rc

    return 0


if __name__ == "__main__":
    sys.exit(main())
