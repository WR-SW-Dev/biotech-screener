#!/usr/bin/env python3
"""Phase 1 diagnostics for Spec 041 — milestone optionality overlay.

Runs the feature builder on the latest snapshot and reports coverage.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from common.clinical_pos_prior import get_clinical_pos_prior
from common.milestone_optionality import compute_universe_milestone_features, z_score_overlay


def main() -> int:
    as_of = date(2026, 3, 31)

    # Load rankings
    rankings_path = PROJECT_ROOT / "data" / "snapshots" / "2026-03-31" / "rankings.csv"
    with open(rankings_path) as f:
        rankings_rows = list(csv.DictReader(f))
    print(f"Rankings: {len(rankings_rows)} rows")

    # Load trial records
    trial_path = PROJECT_ROOT / "cache" / "ctgov" / f"trial_records_{as_of.isoformat()}.json"
    if not trial_path.exists():
        # Fallback to latest
        candidates = sorted(PROJECT_ROOT.glob("cache/ctgov/trial_records_*.json"), reverse=True)
        trial_path = candidates[0] if candidates else None
    if trial_path and trial_path.exists():
        with open(trial_path) as f:
            trial_records = json.load(f)
        print(f"Trial records: {len(trial_records)} from {trial_path.name}")
    else:
        trial_records = []
        print("WARNING: No trial records found")

    # Load PDUFA dates
    pdufa_path = PROJECT_ROOT / "production_data" / "pdufa_dates.json"
    with open(pdufa_path) as f:
        pdufa_entries = json.load(f)
    print(f"PDUFA dates: {len(pdufa_entries)}")

    # Load FDA designations
    desig_path = PROJECT_ROOT / "production_data" / "fda_designations.json"
    with open(desig_path) as f:
        fda_data = json.load(f)
    fda_designations = fda_data.get("designations", [])
    print(f"FDA designations: {len(fda_designations)}")

    # PoS prior function
    prior_path = PROJECT_ROOT / "production_data" / "clinical_pos_priors_v3.json"
    if not prior_path.exists():
        prior_path = PROJECT_ROOT / "production_data" / "clinical_pos_priors_v2.json"

    def pos_fn(phase, endpoint="other"):
        return get_clinical_pos_prior(phase, endpoint, prior_path, as_of.isoformat())

    # Run feature builder
    print("\nRunning milestone optionality feature builder...")
    results = compute_universe_milestone_features(
        rankings_rows=rankings_rows,
        trial_records=trial_records,
        pdufa_entries=pdufa_entries,
        fda_designations=fda_designations,
        as_of_date=as_of,
        pos_prior_fn=pos_fn,
    )
    z_score_overlay(results)

    # Coverage diagnostics
    total = len(results)
    has_milestones = sum(1 for r in results.values() if r.milestone_count_active > 0)
    has_hard = sum(1 for r in results.values() if r.milestone_deadline_mode == "fixed_deadline")
    has_dated = sum(1 for r in results.values() if r.milestone_deadline_mode == "dated_event")

    print("\n=== COVERAGE DIAGNOSTICS ===")
    print(f"Total tickers: {total}")
    print(f"With active milestones: {has_milestones} ({has_milestones/total*100:.1f}%)")
    print(f"  Hard deadlines (PDUFA etc): {has_hard}")
    print(f"  Dated events (CTGov PCD): {has_dated}")
    print(f"  No milestones: {total - has_milestones}")

    # EV distribution
    evs = sorted([r.milestone_deadline_ev_pct for r in results.values() if r.milestone_count_active > 0], reverse=True)
    if evs:
        print(f"\nEV distribution (active tickers only, n={len(evs)}):")
        print(f"  Max:  {evs[0]:.2f}%")
        print(f"  P90:  {evs[int(len(evs)*0.1)]:.2f}%")
        print(f"  P75:  {evs[int(len(evs)*0.25)]:.2f}%")
        print(f"  Med:  {evs[len(evs)//2]:.2f}%")
        print(f"  P25:  {evs[int(len(evs)*0.75)]:.2f}%")
        print(f"  Min:  {evs[-1]:.2f}%")

    # Milestone type distribution
    type_counts = Counter()
    for r in results.values():
        if r.milestone_primary_type:
            type_counts[r.milestone_primary_type] += 1
    print("\nPrimary milestone types:")
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")

    # Top 20 by EV
    top = sorted(results.values(), key=lambda r: r.milestone_deadline_ev_pct, reverse=True)[:20]
    print("\nTop 20 by milestone_deadline_ev_pct:")
    print(
        f"{'Ticker':<8} {'EV%':>6} {'Mode':<16} {'Primary Type':<16} {'Days':>5} {'Slack':>6} {'PoS':>5} {'TL_w':>5} {'Support'}"
    )
    for r in top:
        print(
            f"{r.ticker:<8} {r.milestone_deadline_ev_pct:>6.2f} {r.milestone_deadline_mode:<16} "
            f"{r.milestone_primary_type:<16} {r.milestone_primary_days_to_deadline or 0:>5} "
            f"{r.milestone_timeline_slack_days or 0:>6} {r.milestone_pos_by_deadline_raw:>5.2f} "
            f"{r.milestone_timeline_weight:>5.2f} {r.milestone_confidence_support}"
        )

    # DEM tier-A coverage
    with open(PROJECT_ROOT / "output" / "snapshots" / "2026-03-23" / "decision_portfolio.csv") as f:
        dem = [r for r in csv.DictReader(f) if r.get("actionable_rank", "").strip()]
        dem.sort(key=lambda r: int(r["actionable_rank"]))

    top30_tickers = [r["ticker"] for r in dem[:30]]
    top30_covered = sum(1 for t in top30_tickers if t in results and results[t].milestone_count_active > 0)
    print(f"\nDEM top-30 coverage: {top30_covered}/30 ({top30_covered/30*100:.1f}%)")

    print("\nDEM top-30 detail:")
    for r in dem[:30]:
        t = r["ticker"]
        mr = results.get(t)
        if mr and mr.milestone_count_active > 0:
            print(
                f"  {r['actionable_rank']:>3}. {t:<8} EV={mr.milestone_deadline_ev_pct:>5.2f}% "
                f"mode={mr.milestone_deadline_mode} type={mr.milestone_primary_type} "
                f"slack={mr.milestone_timeline_slack_days}"
            )
        else:
            print(f"  {r['actionable_rank']:>3}. {t:<8} (no milestones)")

    # Save results
    out_dir = PROJECT_ROOT / "output" / "milestone_optionality"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"diagnostics_{as_of.isoformat()}.json"
    out_data = {
        "schema": "milestone_diagnostics.v1",
        "as_of_date": as_of.isoformat(),
        "total_tickers": total,
        "active_milestones": has_milestones,
        "hard_deadlines": has_hard,
        "dated_events": has_dated,
        "ev_distribution": {
            "max": evs[0] if evs else 0,
            "p90": evs[int(len(evs) * 0.1)] if evs else 0,
            "median": evs[len(evs) // 2] if evs else 0,
        },
        "top20": [r.to_dict() for r in top],
    }
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
