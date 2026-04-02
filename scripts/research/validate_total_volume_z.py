#!/usr/bin/env python3
"""total_volume_z 4-step validation (April 7 gate).

Runs the exact sequence from april_validation_plan.md:
  1. Revalidation with snapshot_native hard filter — IC >= 0.10 gate
  2. Walk-forward split (2022-03..2024-06 vs 2024-07..present) — IC positive both halves
  3. Threshold calibration — tercile vs continuous z-score monotonic spread
  4. Interaction test — total_volume_z + rr_25d_canonical joint signal

Usage:
    python3 scripts/research/validate_total_volume_z.py
    python3 scripts/research/validate_total_volume_z.py --ic-gate 0.10 --min-obs 10
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from backtest_signal_robustness import spearman_rank_corr  # noqa: E402
from eval_options_signal_pack import _run_ic, _run_incr_ic, _run_terciles, _sf, build_dataset  # noqa: E402

SCHEMA = "total_volume_z_validation.v1"
OUTPUT_DIR = PROJECT_ROOT / "output" / "total_volume_z_validation"

SIGNAL = "total_volume_z"
PRIMARY_TARGET = "signed_gap"
TARGETS = ["signed_gap", "abs_gap"]
CONTROLS = ["catalyst_decay_w", "opt_atm_iv"]

# Walk-forward split boundary
WF_SPLIT = "2024-07-01"


def _verdict(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


# ---------------------------------------------------------------------------
# Step 1: Revalidation with snapshot_native
# ---------------------------------------------------------------------------


def step1_revalidation(dataset: List[Dict], ic_gate: float, min_obs: int) -> Dict:
    """Raw + incremental IC on snapshot_native hard events."""
    raw = _run_ic(dataset, [SIGNAL], TARGETS, min_obs)
    incr = _run_incr_ic(dataset, [SIGNAL], TARGETS, CONTROLS, min_obs)

    # Extract key IC
    key = f"ic_{SIGNAL}_vs_{PRIMARY_TARGET}"
    raw_entry = raw.get(key, {})
    raw_ic = raw_entry.get("ic")
    n = raw_entry.get("n", 0)

    incr_key = f"incr_{SIGNAL}_ctrl_catalyst_decay_w_vs_{PRIMARY_TARGET}"
    incr_entry = incr.get(incr_key, {})
    incr_ic = incr_entry.get("incr_ic")

    passed = raw_ic is not None and raw_ic >= ic_gate
    return {
        "step": "1_revalidation",
        "n_observations": n,
        "raw_ic_vs_signed_gap": raw_ic,
        "incr_ic_vs_signed_gap": incr_ic,
        "ic_gate": ic_gate,
        "verdict": _verdict(passed),
        "detail": {
            "raw_ics": raw,
            "incr_ics": incr,
        },
    }


# ---------------------------------------------------------------------------
# Step 2: Walk-forward split
# ---------------------------------------------------------------------------


def step2_walkforward(dataset: List[Dict], min_obs: int) -> Dict:
    """IC must be positive in both halves of the walk-forward split."""
    is_half = [r for r in dataset if r["date"] < WF_SPLIT]
    oos_half = [r for r in dataset if r["date"] >= WF_SPLIT]

    def _half_ic(subset, label):
        raw = _run_ic(subset, [SIGNAL], [PRIMARY_TARGET], min_obs)
        key = f"ic_{SIGNAL}_vs_{PRIMARY_TARGET}"
        entry = raw.get(key, {})
        return {
            "label": label,
            "n": entry.get("n", 0),
            "ic": entry.get("ic"),
            "status": entry.get("status", "unknown"),
        }

    is_result = _half_ic(is_half, f"IS (< {WF_SPLIT})")
    oos_result = _half_ic(oos_half, f"OOS (>= {WF_SPLIT})")

    is_ic = is_result["ic"]
    oos_ic = oos_result["ic"]

    is_positive = is_ic is not None and is_ic > 0
    oos_positive = oos_ic is not None and oos_ic > 0
    passed = is_positive and oos_positive

    return {
        "step": "2_walkforward",
        "split_date": WF_SPLIT,
        "in_sample": is_result,
        "out_of_sample": oos_result,
        "is_positive_both": passed,
        "verdict": _verdict(passed),
    }


# ---------------------------------------------------------------------------
# Step 3: Threshold calibration
# ---------------------------------------------------------------------------


def step3_threshold(dataset: List[Dict], min_obs: int) -> Dict:
    """Compare tercile (top/mid/bot) vs continuous z-score monotonic spread."""
    tercile_result = _run_terciles(dataset, [SIGNAL], [PRIMARY_TARGET], min_obs)
    key = f"tercile_{SIGNAL}_vs_{PRIMARY_TARGET}"
    tercile = tercile_result.get(key, {})

    # Continuous IC (already computed, but let's get it clean)
    raw = _run_ic(dataset, [SIGNAL], [PRIMARY_TARGET], min_obs)
    continuous_ic = raw.get(f"ic_{SIGNAL}_vs_{PRIMARY_TARGET}", {}).get("ic")

    # Tercile spread
    tercile_spread = tercile.get("top_minus_bot")
    monotonic = tercile.get("monotonic", False)

    # Verdict: tercile is preferred if monotonic AND spread > 0
    tercile_usable = tercile_spread is not None and tercile_spread > 0 and monotonic
    continuous_usable = continuous_ic is not None and continuous_ic > 0

    if tercile_usable and continuous_usable:
        recommendation = "tercile" if monotonic else "continuous"
    elif tercile_usable:
        recommendation = "tercile"
    elif continuous_usable:
        recommendation = "continuous"
    else:
        recommendation = "neither"

    return {
        "step": "3_threshold_calibration",
        "continuous_ic": continuous_ic,
        "tercile_top_mean": tercile.get("top_mean"),
        "tercile_mid_mean": tercile.get("mid_mean"),
        "tercile_bot_mean": tercile.get("bot_mean"),
        "tercile_spread": tercile_spread,
        "tercile_monotonic": monotonic,
        "recommendation": recommendation,
        "verdict": _verdict(recommendation != "neither"),
    }


# ---------------------------------------------------------------------------
# Step 4: Interaction test
# ---------------------------------------------------------------------------


def step4_interaction(dataset: List[Dict], min_obs: int) -> Dict:
    """Test total_volume_z + rr_25d as joint signal vs each alone."""
    # total_volume_z alone
    raw_vol = _run_ic(dataset, [SIGNAL], [PRIMARY_TARGET], min_obs)
    vol_ic = raw_vol.get(f"ic_{SIGNAL}_vs_{PRIMARY_TARGET}", {}).get("ic")

    # rr_25d alone (check both canonical name variants)
    rr_field = None
    for candidate in ["rr_25d_canonical", "rr_25d", "mean_rr"]:
        n_valid = sum(1 for r in dataset if not math.isnan(_sf(r.get(candidate))))
        if n_valid >= min_obs:
            rr_field = candidate
            break

    rr_ic = None
    if rr_field:
        raw_rr = _run_ic(dataset, [rr_field], [PRIMARY_TARGET], min_obs)
        rr_ic = raw_rr.get(f"ic_{rr_field}_vs_{PRIMARY_TARGET}", {}).get("ic")

    # Joint signal: average of z-scored ranks
    joint_data = []
    for r in dataset:
        vz = _sf(r.get(SIGNAL))
        rr = _sf(r.get(rr_field)) if rr_field else float("nan")
        tgt = _sf(r.get(PRIMARY_TARGET))
        if not math.isnan(vz) and not math.isnan(rr) and not math.isnan(tgt):
            joint_data.append((vz, rr, tgt))

    joint_ic = None
    if len(joint_data) >= min_obs:
        vz_vals, rr_vals, tgt_vals = zip(*joint_data)
        # Rank-average: rank each signal, average the ranks
        n = len(joint_data)

        def _ranks(vals):
            indexed = sorted(range(n), key=lambda i: vals[i])
            ranks = [0.0] * n
            for pos, idx in enumerate(indexed):
                ranks[idx] = pos + 1
            return ranks

        vz_ranks = _ranks(vz_vals)
        rr_ranks = _ranks(rr_vals)
        combined = [(vz_ranks[i] + rr_ranks[i]) / 2 for i in range(n)]
        joint_ic = round(spearman_rank_corr(combined, list(tgt_vals)), 6)

    # Does joint beat the best individual?
    best_individual = (
        max(ic for ic in [vol_ic, rr_ic] if ic is not None) if any(ic is not None for ic in [vol_ic, rr_ic]) else None
    )

    interaction_lift = None
    if joint_ic is not None and best_individual is not None:
        interaction_lift = round(joint_ic - best_individual, 6)

    passed = interaction_lift is not None and interaction_lift > 0

    return {
        "step": "4_interaction",
        "total_volume_z_ic": vol_ic,
        "rr_field_used": rr_field,
        "rr_ic": rr_ic,
        "joint_ic": joint_ic,
        "n_joint": len(joint_data),
        "interaction_lift": interaction_lift,
        "verdict": _verdict(passed),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="total_volume_z 4-step validation")
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "snapshots",
    )
    parser.add_argument(
        "--price-csv",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "price_history.csv",
    )
    parser.add_argument(
        "--iv-features",
        type=Path,
        default=PROJECT_ROOT / "data" / "research" / "historical_iv_features.csv",
    )
    parser.add_argument(
        "--event-move-table",
        type=Path,
        default=PROJECT_ROOT / "data" / "research" / "event_move_table.json",
    )
    parser.add_argument("--ic-gate", type=float, default=0.10)
    parser.add_argument("--min-obs", type=int, default=10)
    parser.add_argument("--max-catalyst-days", type=int, default=90)
    args = parser.parse_args()

    print("=" * 70)
    print("total_volume_z VALIDATION — 4-step gate sequence")
    print("=" * 70)

    # Build dataset using snapshot_native hard filter
    print("\nBuilding dataset (snapshot_native hard filter)...")
    dataset = build_dataset(
        args.snapshots_dir,
        args.price_csv,
        args.iv_features,
        event_subset="hard",
        hard_filter_mode="snapshot_native",
        max_catalyst_days=args.max_catalyst_days,
        horizons=[5, 21],
    )
    print(f"  Dataset: {len(dataset)} observations")

    if len(dataset) < args.min_obs:
        print(f"\n  INSUFFICIENT DATA ({len(dataset)} < {args.min_obs})")
        print("  Re-run after April 7 when more snapshot_native hard events accumulate.")
        result = {
            "schema": SCHEMA,
            "run_date": datetime.now(timezone.utc).isoformat(),
            "n_observations": len(dataset),
            "overall_verdict": "INSUFFICIENT_DATA",
            "steps": {},
        }
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / "validation_result.json"
        out_path.write_text(json.dumps(result, indent=2, default=str))
        print(f"\n  Saved: {out_path}")
        return

    # Step 1
    print(f"\n--- Step 1: Revalidation (IC gate >= {args.ic_gate}) ---")
    s1 = step1_revalidation(dataset, args.ic_gate, args.min_obs)
    print(f"  N={s1['n_observations']}, IC={s1['raw_ic_vs_signed_gap']}, " f"Incr IC={s1['incr_ic_vs_signed_gap']}")
    print(f"  Verdict: {s1['verdict']}")

    # Step 2
    print(f"\n--- Step 2: Walk-forward split ({WF_SPLIT}) ---")
    s2 = step2_walkforward(dataset, args.min_obs)
    print(f"  IS:  N={s2['in_sample']['n']}, IC={s2['in_sample']['ic']}")
    print(f"  OOS: N={s2['out_of_sample']['n']}, IC={s2['out_of_sample']['ic']}")
    print(f"  Verdict: {s2['verdict']}")

    # Step 3
    print("\n--- Step 3: Threshold calibration ---")
    s3 = step3_threshold(dataset, args.min_obs)
    print(f"  Continuous IC: {s3['continuous_ic']}")
    print(f"  Tercile: bot={s3['tercile_bot_mean']}, mid={s3['tercile_mid_mean']}, " f"top={s3['tercile_top_mean']}")
    print(f"  Spread: {s3['tercile_spread']}, Monotonic: {s3['tercile_monotonic']}")
    print(f"  Recommendation: {s3['recommendation']}")
    print(f"  Verdict: {s3['verdict']}")

    # Step 4
    print("\n--- Step 4: Interaction test (volume_z + RR) ---")
    s4 = step4_interaction(dataset, args.min_obs)
    print(f"  volume_z IC: {s4['total_volume_z_ic']}")
    print(f"  RR IC ({s4['rr_field_used']}): {s4['rr_ic']}")
    print(f"  Joint IC: {s4['joint_ic']} (N={s4['n_joint']})")
    print(f"  Interaction lift: {s4['interaction_lift']}")
    print(f"  Verdict: {s4['verdict']}")

    # Overall
    verdicts = [s1["verdict"], s2["verdict"], s3["verdict"], s4["verdict"]]
    n_pass = sum(1 for v in verdicts if v == "PASS")
    # Gate: steps 1 and 2 must pass; steps 3 and 4 are informational
    critical_pass = s1["verdict"] == "PASS" and s2["verdict"] == "PASS"
    overall = "GO" if critical_pass else "NO_GO"

    print(f"\n{'='*70}")
    print(f"OVERALL: {overall} ({n_pass}/4 steps passed)")
    print(f"  Critical gates (1+2): {'PASS' if critical_pass else 'FAIL'}")
    print(f"  Step 1 (IC >= {args.ic_gate}): {s1['verdict']}")
    print(f"  Step 2 (walk-forward):  {s2['verdict']}")
    print(f"  Step 3 (threshold):     {s3['verdict']}")
    print(f"  Step 4 (interaction):   {s4['verdict']}")
    print(f"{'='*70}")

    result = {
        "schema": SCHEMA,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "n_observations": len(dataset),
        "ic_gate": args.ic_gate,
        "overall_verdict": overall,
        "n_steps_passed": n_pass,
        "critical_gates_passed": critical_pass,
        "steps": {
            "revalidation": s1,
            "walkforward": s2,
            "threshold": s3,
            "interaction": s4,
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "validation_result.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
