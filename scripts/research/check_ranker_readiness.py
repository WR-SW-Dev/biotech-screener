"""Ranker data readiness gate.

Checks whether the historical feature dataset has sufficient coverage
of discriminating features to support within-top-30 ranker training.

Hard preconditions:
  - options present on >= 40% of top-30 names
  - inst_delta_z present on >= 50% of top-30 names
  - minimum 30 eligible dates in the test window

Usage:
    python scripts/research/check_ranker_readiness.py
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
PIT_CACHE_DIR = REPO_ROOT / "data" / "caches" / "price_pit" / "PIT"
OUTPUT_DIR = REPO_ROOT / "output" / "ranker"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("ranker_readiness")

OPTIONS_FEATURES = ["opt_atm_iv", "opt_rr_25d", "actual_implied_move_pctile"]
INST_FEATURES = ["inst_delta_z"]
MIN_OPTIONS_COVERAGE = 0.40
MIN_INST_COVERAGE = 0.50
MIN_ELIGIBLE_DATES = 30


def check_date(snapshot_date: str) -> dict:
    """Check feature coverage for one date's top-30."""
    rpath = SNAPSHOT_DIR / snapshot_date / "rankings.csv"
    if not rpath.exists():
        return {"date": snapshot_date, "eligible": False, "reason": "no_rankings"}

    with open(rpath, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    ranked = []
    for r in rows:
        ar = r.get("actionable_rank", "").strip()
        if ar:
            try:
                r["_rank"] = int(ar)
                ranked.append(r)
            except ValueError:
                pass
    ranked.sort(key=lambda r: r["_rank"])
    top30 = ranked[:30]

    if len(top30) < 20:
        return {"date": snapshot_date, "eligible": False, "reason": "too_few_ranked"}

    n = len(top30)

    # Options coverage
    opts_filled = 0
    for r in top30:
        has_any = any(r.get(f, "").strip() not in ("", "0", "0.0", "None") for f in OPTIONS_FEATURES)
        if has_any:
            opts_filled += 1
    opts_pct = opts_filled / n

    # Inst coverage — check if field is populated (zero is a valid signal value)
    inst_filled = 0
    for r in top30:
        val = r.get("inst_delta_z", "").strip()
        if val and val not in ("", "None"):
            try:
                float(val)  # parseable = populated
                inst_filled += 1
            except ValueError:
                pass
    inst_pct = inst_filled / n

    # PIT cache exists?
    has_pit = (PIT_CACHE_DIR / snapshot_date / "prices.csv").exists()

    eligible = opts_pct >= MIN_OPTIONS_COVERAGE and inst_pct >= MIN_INST_COVERAGE and has_pit

    reasons = []
    if opts_pct < MIN_OPTIONS_COVERAGE:
        reasons.append(f"options={opts_pct:.0%}<{MIN_OPTIONS_COVERAGE:.0%}")
    if inst_pct < MIN_INST_COVERAGE:
        reasons.append(f"inst_delta={inst_pct:.0%}<{MIN_INST_COVERAGE:.0%}")
    if not has_pit:
        reasons.append("no_pit_cache")

    return {
        "date": snapshot_date,
        "eligible": eligible,
        "options_coverage": round(opts_pct, 3),
        "inst_coverage": round(inst_pct, 3),
        "has_pit_cache": has_pit,
        "n_top30": n,
        "reason": "; ".join(reasons) if reasons else "OK",
    }


def run_readiness_check() -> dict:
    """Check readiness across all available snapshot dates."""
    dates = sorted(
        d.name
        for d in SNAPSHOT_DIR.iterdir()
        if d.is_dir() and d.name >= "2020-01-01" and (d / "rankings.csv").exists()
    )

    log.info("Checking %d snapshot dates...", len(dates))
    results = []
    for d in dates:
        results.append(check_date(d))

    eligible = [r for r in results if r["eligible"]]
    ineligible = [r for r in results if not r["eligible"]]

    # Find contiguous eligible windows
    eligible_dates = sorted(r["date"] for r in eligible)
    windows = []
    if eligible_dates:
        current_window = [eligible_dates[0]]
        for d in eligible_dates[1:]:
            current_window.append(d)
        windows.append(
            {
                "start": current_window[0],
                "end": current_window[-1],
                "n_dates": len(current_window),
            }
        )

    ready = len(eligible) >= MIN_ELIGIBLE_DATES

    summary = {
        "schema": "ranker_data_readiness.v1",
        "generated_at": datetime.now().isoformat(),
        "total_dates": len(dates),
        "eligible_dates": len(eligible),
        "ineligible_dates": len(ineligible),
        "ready_for_training": ready,
        "min_eligible_required": MIN_ELIGIBLE_DATES,
        "thresholds": {
            "min_options_coverage": MIN_OPTIONS_COVERAGE,
            "min_inst_coverage": MIN_INST_COVERAGE,
            "min_eligible_dates": MIN_ELIGIBLE_DATES,
        },
        "eligible_windows": windows,
        "recent_dates": results[-20:],
    }

    # Coverage trend (last 30 dates)
    recent = results[-30:]
    if recent:
        summary["recent_trend"] = {
            "dates": len(recent),
            "mean_options_coverage": round(sum(r.get("options_coverage", 0) for r in recent) / len(recent), 3),
            "mean_inst_coverage": round(sum(r.get("inst_coverage", 0) for r in recent) / len(recent), 3),
            "eligible_count": sum(1 for r in recent if r["eligible"]),
        }

    return summary


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = run_readiness_check()

    output_path = OUTPUT_DIR / "ranker_data_readiness.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    log.info("Wrote %s", output_path)

    print(f"\n{'='*60}")
    print("RANKER DATA READINESS")
    print(f"{'='*60}")
    print(f"Total dates checked: {summary['total_dates']}")
    print(f"Eligible dates: {summary['eligible_dates']}")
    print(f"Ready for training: {'YES' if summary['ready_for_training'] else 'NO'}")
    print(f"Required: >= {MIN_ELIGIBLE_DATES} eligible dates")

    if summary.get("recent_trend"):
        t = summary["recent_trend"]
        print(f"\nRecent trend (last {t['dates']} dates):")
        print(f"  Options coverage: {t['mean_options_coverage']:.0%}")
        print(f"  Inst coverage: {t['mean_inst_coverage']:.0%}")
        print(f"  Eligible: {t['eligible_count']}/{t['dates']}")

    if summary.get("eligible_windows"):
        for w in summary["eligible_windows"]:
            print(f"\nEligible window: {w['start']} to {w['end']} ({w['n_dates']} dates)")

    if not summary["ready_for_training"]:
        print(f"\nBLOCKER: Need {MIN_ELIGIBLE_DATES - summary['eligible_dates']} more eligible dates.")
        print("Action: wait for options coverage expansion + daily snapshots to accumulate.")


if __name__ == "__main__":
    main()
