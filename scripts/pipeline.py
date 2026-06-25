#!/usr/bin/env python
"""Biotech screener pipeline — run by cron jobs.

Modes (first arg):
  refresh  — Run screener for today, generate new snapshot
  catalyst — Check for upcoming catalysts, print alert if any new
  aact     — Sync AACT snapshots (stub — requires DB access)
  status   — Print current screener status (snapshots, universe size)

Usage:
  python scripts/pipeline.py refresh
  python scripts/pipeline.py catalyst
  python scripts/pipeline.py status

Cron integration:
  - Daily refresh:   '0 6 * * *'    → pipeline.py refresh
  - Hourly catalyst: '0 * * * *'    → pipeline.py catalyst
  - Weekly AACT:     '0 2 * * 0'    → pipeline.py aact

Output goes to stdout. Cron jobs deliver stdout to the user.
Stays SILENT (empty stdout) when there's nothing to report.
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("BIOTECH_PROJECT_DIR", Path(__file__).resolve().parent.parent))
DATA_DIR = PROJECT_DIR / "data"
UNIVERSE_FILE = DATA_DIR / "universe" / "biotech_universe_v1.csv"
TRIAL_MAP_FILE = DATA_DIR / "trial_mapping.csv"
AACT_DIR = DATA_DIR / "aact_snapshots"
OUTPUT_DIR = PROJECT_DIR / "output"


def load_universe() -> list[dict]:
    if not UNIVERSE_FILE.exists():
        return []
    with open(UNIVERSE_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_trial_map() -> dict[str, list[dict]]:
    if not TRIAL_MAP_FILE.exists():
        return {}
    mapping: dict[str, list[dict]] = {}
    with open(TRIAL_MAP_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").upper().strip()
            if ticker:
                mapping.setdefault(ticker, []).append(row)
    return mapping


def list_snapshots() -> list[str]:
    """Return sorted snapshot dates from output/."""
    if not OUTPUT_DIR.is_dir():
        return []
    dates = []
    for p in OUTPUT_DIR.glob("snapshot_*.json"):
        ds = p.stem.replace("snapshot_", "")
        if len(ds) == 10 and ds[4] == "-":
            dates.append(ds)
    return sorted(dates)


def latest_aact_snapshot() -> Path | None:
    if not AACT_DIR.is_dir():
        return None
    subdirs = sorted(p for p in AACT_DIR.iterdir() if p.is_dir())
    return subdirs[-1] if subdirs else None


def load_aact_studies(aact_dir: Path) -> dict[str, dict]:
    studies = aact_dir / "studies.csv"
    if not studies.exists():
        return {}
    out = {}
    with open(studies, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nct = (row.get("nct_id") or "").strip()
            if nct:
                out[nct] = row
    return out


# ─── Modes ───────────────────────────────────────────────────────────


def mode_status():
    """Print current screener status."""
    universe = load_universe()
    trials = load_trial_map()
    snapshots = list_snapshots()
    aact = latest_aact_snapshot()

    print("🧬 Biotech Screener Status")
    print(f"   Universe: {len(universe)} companies")
    print(f"   Trial mappings: {sum(len(v) for v in trials.values())} trials across {len(trials)} tickers")
    print(f"   Snapshots: {len(snapshots)}")
    if snapshots:
        print(f"     Latest: {snapshots[-1]}")
        print(f"     Range: {snapshots[0]} → {snapshots[-1]}")
    if aact:
        print(f"   AACT snapshot: {aact.name}")
    else:
        print("   AACT snapshot: none")
    print(f"   Project: {PROJECT_DIR}")


def mode_refresh():
    """Run the screener for today's date."""
    today = datetime.now().strftime("%Y-%m-%d")
    snapshots = list_snapshots()

    # Check if today's snapshot already exists
    expected = OUTPUT_DIR / f"snapshot_{today}.json"
    if expected.exists():
        # Silent — already done today
        return

    # Try to run the snapshot generator
    try:
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.snapshot_generator",
                "--as-of",
                today,
                "--universe",
                str(UNIVERSE_FILE),
                "--output",
                str(OUTPUT_DIR),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_DIR),
        )
        if result.returncode != 0:
            print(f"⚠️ Screener failed for {today}")
            print(f"   stderr: {result.stderr[:500]}")
            return
    except subprocess.TimeoutExpired:
        print(f"⚠️ Screener timed out for {today}")
        return
    except Exception as e:
        print(f"⚠️ Screener error: {e}")
        return

    # Check if snapshot was created
    if expected.exists():
        # Compare with previous
        if snapshots:
            prev = snapshots[-1]
            print(f"✅ New snapshot: {today} (previous: {prev})")
        else:
            print(f"✅ First snapshot created: {today}")
    else:
        print(f"⚠️ Screener ran but no snapshot file at {expected}")


def mode_catalyst():
    """Check for upcoming catalysts — print alert if any found."""
    trials = load_trial_map()
    aact_dir = latest_aact_snapshot()
    if not aact_dir:
        return  # Silent — no AACT data

    studies = load_aact_studies(aact_dir)
    today = date.today()
    upcoming = []

    for ticker, trial_list in trials.items():
        for t in trial_list:
            nct = t.get("nct_id", "")
            study = studies.get(nct, {})
            pcd = study.get("primary_completion_date", "")
            status = study.get("overall_status", "")

            if pcd and len(pcd) >= 10:
                try:
                    pcd_date = date.fromisoformat(pcd[:10])
                    days_until = (pcd_date - today).days
                    if 0 <= days_until <= 90:
                        upcoming.append(
                            {
                                "ticker": ticker,
                                "nct_id": nct,
                                "pcd": pcd[:10],
                                "days": days_until,
                                "phase": study.get("phase", "Unknown"),
                                "status": status,
                            }
                        )
                except ValueError:
                    pass

    if not upcoming:
        return  # Silent — nothing to report

    # Sort by days until PCD
    upcoming.sort(key=lambda x: x["days"])

    print(f"📡 {len(upcoming)} upcoming catalysts (next 90 days)")
    print()
    for c in upcoming[:15]:
        urgency = "🔴" if c["days"] <= 14 else "🟡" if c["days"] <= 30 else "🟢"
        print(f"  {urgency} {c['ticker']:5s} {c['nct_id']}  PCD: {c['pcd']} ({c['days']}d)  [{c['phase']}]")
    if len(upcoming) > 15:
        print(f"  ... +{len(upcoming) - 15} more")


def mode_aact():
    """Sync AACT snapshots — stub for now."""
    aact_dir = latest_aact_snapshot()
    if aact_dir:
        print(f"✅ AACT snapshot present: {aact_dir.name}")
        studies = load_aact_studies(aact_dir)
        print(f"   {len(studies)} studies loaded")
    else:
        print("⚠️ No AACT snapshot found. AACT sync requires database access.")
        print("   Run: python scripts/download_aact.py --date <YYYY-MM-DD>")


# ─── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"

    if mode == "refresh":
        mode_refresh()
    elif mode == "catalyst":
        mode_catalyst()
    elif mode == "aact":
        mode_aact()
    elif mode == "status":
        mode_status()
    else:
        print(f"Unknown mode: {mode}. Use: refresh, catalyst, aact, status")
        sys.exit(1)
