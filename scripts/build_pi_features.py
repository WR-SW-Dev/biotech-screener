#!/usr/bin/env python3
"""Build PIT-safe PI trial count features from AACT + trial_records.json.

Reads AACT facility_investigators.txt and trial_records.json, computes
per-ticker investigator experience metrics, and writes a JSON artifact.

Usage:
    python3 scripts/build_pi_features.py \
        --as-of-date 2026-03-01 \
        --aact-dir aact/ \
        --trial-records production_data/trial_records.json \
        --universe production_data/universe.json \
        --out-dir data/caches/pi_features/

See specs/changes/032_pi_trial_count.md for design.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.pi_features import (
    SCHEMA_VERSION,
    VERSION,
    compute_pi_features_universe,
    load_facility_investigators,
    load_pi_supplement,
    merge_pi_indices,
)


def _load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def _load_universe(path: Path) -> set:
    data = _load_json(path)
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            return {r.get("ticker", r.get("symbol", "")) for r in data} - {""}
        return set(data)
    return set()


def main():
    parser = argparse.ArgumentParser(description="Build PIT-safe PI trial count features")
    parser.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--aact-dir", default="aact/")
    parser.add_argument("--trial-records", default="production_data/trial_records.json")
    parser.add_argument("--universe", default="production_data/universe.json")
    parser.add_argument("--out-dir", default="data/caches/pi_features/")
    parser.add_argument(
        "--supplement",
        default="data/caches/pi_features/ctgov_api_pi_supplement.json",
        help="CT.gov API PI supplement JSON (optional, merged with AACT)",
    )
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of_date)
    aact_dir = Path(args.aact_dir)
    fi_path = aact_dir / "facility_investigators.txt"

    if not fi_path.exists():
        print(f"ERROR: {fi_path} not found", file=sys.stderr)
        sys.exit(1)

    # Load data
    print(f"Loading AACT facility_investigators from {fi_path}...")
    pi_index = load_facility_investigators(fi_path)
    print(f"  {sum(len(v) for v in pi_index.values())} PI records across {len(pi_index)} trials")

    # Load optional API supplement
    supp_path = Path(args.supplement)
    if supp_path.exists():
        print(f"Loading API PI supplement from {supp_path}...")
        supplement = load_pi_supplement(supp_path)
        print(f"  {len(supplement)} trials in supplement")
        pi_index = merge_pi_indices(pi_index, supplement)
        print(f"  Merged: {len(pi_index)} trials with PI data")
    else:
        print(f"No supplement at {supp_path} — using AACT only")

    print(f"Loading trial_records from {args.trial_records}...")
    trial_records = _load_json(Path(args.trial_records))
    print(f"  {len(trial_records)} trials")

    print(f"Loading universe from {args.universe}...")
    universe = _load_universe(Path(args.universe))
    print(f"  {len(universe)} tickers")

    # Compute features
    print(f"Computing PI features (as_of={as_of})...")
    features = compute_pi_features_universe(trial_records, pi_index, universe, as_of)

    # Coverage stats
    n_with_pi = sum(1 for f in features.values() if f["pi_count"] > 0)
    n_total = len(features)
    print(f"  Coverage: {n_with_pi}/{n_total} tickers ({n_with_pi/n_total*100:.1f}%)")

    # Distribution
    max_counts = sorted(
        [f["pi_max_trial_count"] for f in features.values() if f["pi_count"] > 0],
        reverse=True,
    )
    if max_counts:
        print(
            f"  pi_max_trial_count: min={min(max_counts)} median={max_counts[len(max_counts)//2]} max={max_counts[0]}"
        )

    z_vals = sorted(
        [f["pi_experience_z"] for f in features.values() if f["pi_count"] > 0],
        reverse=True,
    )
    if z_vals:
        print(f"  pi_experience_z: min={z_vals[-1]:.2f} median={z_vals[len(z_vals)//2]:.2f} max={z_vals[0]:.2f}")

    # Top tickers by pi_experience_z
    top = sorted(
        [(t, f) for t, f in features.items() if f["pi_count"] > 0],
        key=lambda x: x[1]["pi_experience_z"],
        reverse=True,
    )
    print("\n  Top 10 by pi_experience_z:")
    for t, f in top[:10]:
        print(
            f"    {t:6s}  z={f['pi_experience_z']:+6.2f}  "
            f"max_trials={f['pi_max_trial_count']:3d}  "
            f"max_late={f['pi_max_late_stage_count']:3d}  "
            f"max_completed={f['pi_max_completed_count']:3d}  "
            f"pi_count={f['pi_count']:4d}"
        )

    print("\n  Bottom 5 (with PI data) by pi_experience_z:")
    for t, f in top[-5:]:
        print(
            f"    {t:6s}  z={f['pi_experience_z']:+6.2f}  "
            f"max_trials={f['pi_max_trial_count']:3d}  "
            f"pi_count={f['pi_count']:4d}"
        )

    # Write output
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"pi_features_{args.as_of_date}.json"

    output = {
        "schema": SCHEMA_VERSION,
        "version": VERSION,
        "as_of_date": args.as_of_date,
        "aact_snapshot_date": "2026-02-02",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": {
            "universe_tickers": n_total,
            "tickers_with_pi": n_with_pi,
            "coverage_pct": round(n_with_pi / n_total * 100, 1) if n_total else 0,
        },
        "features": features,
    }

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, sort_keys=True)
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
