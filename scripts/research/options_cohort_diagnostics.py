"""Options cohort diagnostics — where do options features actually inform?

Cuts the options lane by cohort to identify where signal is strongest:
  - hard catalyst vs soft catalyst
  - regulatory vs clinical catalyst family
  - near-dated (≤45d) vs mid-dated (46-120d) vs far-dated (>120d)
  - options-covered vs absent
  - liquid chain vs thin chain
  - by surface regime (event_loaded, iv_ramping, flat)

For each cohort, computes:
  - coverage (n, % of total)
  - mean/median of key options features
  - dispersion (std) — higher = more informative for ranking
  - % with event premium
  - mean actual_implied_move_pctile

Usage:
    python scripts/research/options_cohort_diagnostics.py
    python scripts/research/options_cohort_diagnostics.py --date 2026-04-01
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
OUTPUT_DIR = REPO_ROOT / "output" / "options"

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("options_cohort")


def _sf(v) -> float:
    if v is None or v == "" or v == "None":
        return float("nan")
    try:
        return float(v)
    except (ValueError, TypeError):
        return float("nan")


def load_ranked_rows(snapshot_date: str) -> list[dict]:
    rpath = SNAPSHOT_DIR / snapshot_date / "rankings.csv"
    if not rpath.exists():
        return []
    with open(rpath, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r.get("actionable_rank", "").strip()]


def classify_cohorts(row: dict) -> dict[str, str]:
    """Assign cohort labels to a row."""
    cohorts = {}

    # Hard vs soft catalyst
    cohorts["catalyst_hardness"] = "hard" if row.get("is_hard_catalyst") == "1" else "soft"

    # Catalyst family
    fam = (row.get("catalyst_family") or "").upper()
    cohorts["catalyst_family"] = fam if fam in ("REGULATORY", "CLINICAL") else "OTHER"

    # Catalyst proximity
    cd = _sf(row.get("catalyst_days"))
    if math.isnan(cd) or cd <= 0:
        cohorts["catalyst_proximity"] = "no_catalyst"
    elif cd <= 45:
        cohorts["catalyst_proximity"] = "near"
    elif cd <= 120:
        cohorts["catalyst_proximity"] = "mid"
    else:
        cohorts["catalyst_proximity"] = "far"

    # Options coverage
    has_data = row.get("opt_has_data") == "1"
    liquid = row.get("opt_liquidity_ok") == "1"
    if has_data and liquid:
        cohorts["options_state"] = "liquid"
    elif has_data:
        cohorts["options_state"] = "illiquid"
    else:
        cohorts["options_state"] = "absent"

    # Surface regime (from event premium decomp if available, else from raw flags)
    ep = row.get("opt_event_premium", "")
    iv_regime = row.get("opt_iv_regime", "")
    if ep == "YES":
        cohorts["surface_type"] = "event_loaded"
    elif iv_regime == "EXTREME":
        cohorts["surface_type"] = "iv_extreme"
    elif iv_regime == "ELEVATED":
        cohorts["surface_type"] = "iv_elevated"
    else:
        cohorts["surface_type"] = "normal_or_absent"

    return cohorts


def compute_cohort_stats(rows: list[dict], cohort_dim: str) -> dict:
    """Compute stats for each value of a cohort dimension."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        cohorts = classify_cohorts(r)
        groups[cohorts.get(cohort_dim, "unknown")].append(r)

    stats = {}
    for label, group in sorted(groups.items()):
        n = len(group)

        # Options coverage in this cohort
        n_has_data = sum(1 for r in group if r.get("opt_has_data") == "1")
        n_liquid = sum(1 for r in group if r.get("opt_liquidity_ok") == "1")
        n_event_premium = sum(1 for r in group if r.get("opt_event_premium") == "YES")

        # Key feature distributions (for names with data)
        def _feature_stats(field):
            vals = [_sf(r.get(field)) for r in group if r.get("opt_has_data") == "1"]
            vals = [v for v in vals if not math.isnan(v)]
            if len(vals) < 2:
                return {"n": len(vals), "mean": None, "std": None, "median": None}
            return {
                "n": len(vals),
                "mean": round(statistics.mean(vals), 4),
                "std": round(statistics.stdev(vals), 4),
                "median": round(statistics.median(vals), 4),
            }

        stats[label] = {
            "n": n,
            "pct_of_total": round(100 * n / max(len(rows), 1), 1),
            "options_coverage": round(100 * n_has_data / max(n, 1), 1),
            "liquid_coverage": round(100 * n_liquid / max(n, 1), 1),
            "event_premium_pct": round(100 * n_event_premium / max(n, 1), 1),
            "atm_iv": _feature_stats("opt_atm_iv"),
            "rr_25d": _feature_stats("opt_rr_25d"),
            "term_slope": _feature_stats("opt_term_slope"),
            "actual_implied_move_pctile": _feature_stats("actual_implied_move_pctile"),
        }

    return stats


def run_diagnostics(snapshot_date: str) -> dict:
    rows = load_ranked_rows(snapshot_date)
    if not rows:
        return {"error": f"No rankings for {snapshot_date}"}

    log.info("Loaded %d ranked names for %s", len(rows), snapshot_date)

    dimensions = [
        "catalyst_hardness",
        "catalyst_family",
        "catalyst_proximity",
        "options_state",
        "surface_type",
    ]

    result = {
        "schema": "options_cohort_diagnostics.v1",
        "as_of_date": snapshot_date,
        "n_total": len(rows),
        "n_with_options": sum(1 for r in rows if r.get("opt_has_data") == "1"),
        "n_liquid": sum(1 for r in rows if r.get("opt_liquidity_ok") == "1"),
        "dimensions": {},
    }

    for dim in dimensions:
        result["dimensions"][dim] = compute_cohort_stats(rows, dim)

    return result


def print_diagnostics(result: dict):
    print(f"\n{'='*70}")
    print(f"OPTIONS COHORT DIAGNOSTICS — {result['as_of_date']}")
    print(f"{'='*70}")
    print(
        f"Total ranked: {result['n_total']}, "
        f"With options: {result['n_with_options']} ({100*result['n_with_options']/result['n_total']:.0f}%), "
        f"Liquid: {result['n_liquid']} ({100*result['n_liquid']/result['n_total']:.0f}%)"
    )

    for dim, cohorts in result["dimensions"].items():
        print(f"\n--- {dim} ---")
        print(
            f"  {'Cohort':<18} {'N':<5} {'Opt%':<7} {'Liq%':<7} {'EP%':<6} "
            f"{'IV mean':<9} {'IV std':<9} {'RR std':<9} {'AIM med':<9}"
        )
        for label, s in cohorts.items():
            iv = s["atm_iv"]
            rr = s["rr_25d"]
            aim = s["actual_implied_move_pctile"]
            print(
                f"  {label:<18} {s['n']:<5} {s['options_coverage']:>5.0f}% {s['liquid_coverage']:>5.0f}% {s['event_premium_pct']:>4.0f}% "
                f"{iv['mean'] or '—':>8} {iv['std'] or '—':>8} {rr['std'] or '—':>8} {aim['median'] or '—':>8}"
            )


def main():
    parser = argparse.ArgumentParser(description="Options cohort diagnostics")
    parser.add_argument("--date", default="")
    args = parser.parse_args()

    if not args.date:
        dates = sorted(d.name for d in SNAPSHOT_DIR.iterdir() if d.is_dir() and (d / "rankings.csv").exists())
        args.date = dates[-1] if dates else date.today().isoformat()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = run_diagnostics(args.date)

    output_path = OUTPUT_DIR / f"cohort_diagnostics_{args.date}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", output_path)

    print_diagnostics(result)


if __name__ == "__main__":
    main()
