#!/usr/bin/env python3
"""Promotion weekly-live-sim gate.

Runs two weekly live-sim A/B evaluations (per-bucket policy + global top-K)
and emits PASS/FAIL verdict. A candidate cannot be promoted unless this gate
passes (or --force is used in promote_ruleset.py).

Acceptance rules:
  Policy mode (OOS):
    - cumulative hedged Δ >= +1.0pp
    - mean weekly hedged Δ >= 0.00pp
  Global top-K mode (OOS):
    - mean weekly hedged Δ >= -0.01pp
    - cumulative hedged Δ >= -1.0pp
  Guardrail:
    - no bucket's mean weekly hedged Δ <= -0.20pp

Output:
    {out_dir}/VERDICT.md
    {out_dir}/VERDICT.json
    {out_dir}/RESULTS_policy.csv
    {out_dir}/RESULTS_global.csv

Usage:
    python3 scripts/research/promotion_weekly_gate.py \\
      --baseline-root data/snapshots_reranked_v1100 \\
      --candidate-root data/snapshots_reranked_b91_quality_primary \\
      --date-manifest output/audited_sets/audited_dates_2020_2024_strict.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "research"))

from live_sim_weekly_ab import (
    BUCKET_NAMES,
    aggregate,
    discover_dates,
    load_date_manifest,
    load_policy,
    load_prices,
    run_arm,
    select_rebalance_dates,
    write_results_csv,
)

# ---------------------------------------------------------------------------
# Acceptance thresholds
# ---------------------------------------------------------------------------

# Policy mode (per-bucket, matches actual trading)
POLICY_CUM_HEDGED_MIN_PP = 1.0  # Δ cumulative hedged >= +1.0pp
POLICY_MEAN_HEDGED_MIN_PP = 0.0  # Δ mean weekly hedged >= 0.00pp

# Global top-K mode (sanity check)
GLOBAL_MEAN_HEDGED_MIN_PP = -0.01  # Δ mean weekly hedged >= -0.01pp
GLOBAL_CUM_HEDGED_MIN_PP = -1.0  # Δ cumulative hedged >= -1.0pp

# Bucket guardrail
BUCKET_MEAN_HEDGED_FLOOR_PP = -0.20  # no bucket mean weekly hedged Δ <= -0.20pp


def _pp(v: Optional[float]) -> Optional[float]:
    """Convert fraction to percentage points."""
    return v * 100 if v is not None else None


def _fmt_pp(v: Optional[float]) -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}pp"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


def evaluate_gate(
    base_agg: Dict[str, Any],
    cand_agg: Dict[str, Any],
    mode: str,
) -> Dict[str, Any]:
    """Evaluate one mode's results against thresholds.

    Returns dict with checks list and overall pass/fail.
    """
    checks = []

    mean_delta_pp = None
    cum_delta_pp = None
    if base_agg["mean_hedged"] is not None and cand_agg["mean_hedged"] is not None:
        mean_delta_pp = (cand_agg["mean_hedged"] - base_agg["mean_hedged"]) * 100
    if base_agg["cum_hedged"] is not None and cand_agg["cum_hedged"] is not None:
        cum_delta_pp = (cand_agg["cum_hedged"] - base_agg["cum_hedged"]) * 100

    if mode == "policy":
        checks.append(
            {
                "name": "policy_cum_hedged",
                "threshold": f">= {POLICY_CUM_HEDGED_MIN_PP:+.2f}pp",
                "actual": _fmt_pp(cum_delta_pp),
                "pass": cum_delta_pp is not None and cum_delta_pp >= POLICY_CUM_HEDGED_MIN_PP,
            }
        )
        checks.append(
            {
                "name": "policy_mean_hedged",
                "threshold": f">= {POLICY_MEAN_HEDGED_MIN_PP:+.2f}pp",
                "actual": _fmt_pp(mean_delta_pp),
                "pass": mean_delta_pp is not None and mean_delta_pp >= POLICY_MEAN_HEDGED_MIN_PP,
            }
        )
    elif mode == "global":
        checks.append(
            {
                "name": "global_mean_hedged",
                "threshold": f">= {GLOBAL_MEAN_HEDGED_MIN_PP:+.2f}pp",
                "actual": _fmt_pp(mean_delta_pp),
                "pass": mean_delta_pp is not None and mean_delta_pp >= GLOBAL_MEAN_HEDGED_MIN_PP,
            }
        )
        checks.append(
            {
                "name": "global_cum_hedged",
                "threshold": f">= {GLOBAL_CUM_HEDGED_MIN_PP:+.2f}pp",
                "actual": _fmt_pp(cum_delta_pp),
                "pass": cum_delta_pp is not None and cum_delta_pp >= GLOBAL_CUM_HEDGED_MIN_PP,
            }
        )

    # Bucket guardrail (applied to both modes)
    for b in BUCKET_NAMES:
        bk = f"{b}_mean_hedged"
        base_val = base_agg.get(bk)
        cand_val = cand_agg.get(bk)
        if base_val is not None and cand_val is not None:
            delta_pp = (cand_val - base_val) * 100
            passed = delta_pp > BUCKET_MEAN_HEDGED_FLOOR_PP
            checks.append(
                {
                    "name": f"bucket_{b}",
                    "threshold": f"> {BUCKET_MEAN_HEDGED_FLOOR_PP:+.2f}pp",
                    "actual": _fmt_pp(delta_pp),
                    "pass": passed,
                }
            )

    overall = all(c["pass"] for c in checks)
    return {"mode": mode, "checks": checks, "pass": overall}


def run_gate(
    baseline_root: Path,
    candidate_root: Path,
    policy_path: Path,
    price_csv: Path,
    dates: List[str],
    rebal_every: int = 1,
    cost_bps: float = 30.0,
    global_top_k: int = 20,
    buffer_ranks: int = 30,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run full promotion gate evaluation."""
    prices = load_prices(price_csv)
    policy = load_policy(policy_path)
    rebal_dates = select_rebalance_dates(dates, rebal_every)

    results = {}

    # --- Policy mode ---
    print("Running policy mode...")
    base_pol = run_arm("baseline", baseline_root, rebal_dates, prices, policy, cost_bps)
    cand_pol = run_arm("candidate", candidate_root, rebal_dates, prices, policy, cost_bps)
    base_pol_agg = aggregate(base_pol)
    cand_pol_agg = aggregate(cand_pol)
    pol_gate = evaluate_gate(base_pol_agg, cand_pol_agg, "policy")
    results["policy"] = {
        "gate": pol_gate,
        "base_agg": base_pol_agg,
        "cand_agg": cand_pol_agg,
    }

    if out_dir:
        write_results_csv(base_pol + cand_pol, out_dir / "RESULTS_policy.csv")

    # --- Global top-K mode ---
    print("Running global top-K mode...")
    base_gbl = run_arm(
        "baseline",
        baseline_root,
        rebal_dates,
        prices,
        policy,
        cost_bps,
        global_top_k=global_top_k,
        buffer_ranks=buffer_ranks,
    )
    cand_gbl = run_arm(
        "candidate",
        candidate_root,
        rebal_dates,
        prices,
        policy,
        cost_bps,
        global_top_k=global_top_k,
        buffer_ranks=buffer_ranks,
    )
    base_gbl_agg = aggregate(base_gbl)
    cand_gbl_agg = aggregate(cand_gbl)
    gbl_gate = evaluate_gate(base_gbl_agg, cand_gbl_agg, "global")
    results["global"] = {
        "gate": gbl_gate,
        "base_agg": base_gbl_agg,
        "cand_agg": cand_gbl_agg,
    }

    if out_dir:
        write_results_csv(base_gbl + cand_gbl, out_dir / "RESULTS_global.csv")

    overall = pol_gate["pass"] and gbl_gate["pass"]
    results["verdict"] = "PASS" if overall else "FAIL"
    results["n_periods"] = base_pol_agg["n_periods"]
    results["n_dates"] = len(rebal_dates)

    return results


def write_verdict_json(results: Dict[str, Any], out_path: Path) -> Path:
    """Write machine-readable verdict."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "promotion_weekly_gate.v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": results["verdict"],
        "n_periods": results["n_periods"],
        "n_dates": results["n_dates"],
        "policy_pass": results["policy"]["gate"]["pass"],
        "global_pass": results["global"]["gate"]["pass"],
        "checks": (results["policy"]["gate"]["checks"] + results["global"]["gate"]["checks"]),
    }
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=2)
    return out_path


def write_verdict_md(results: Dict[str, Any], out_path: Path) -> Path:
    """Write human-readable verdict."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    v = results["verdict"]
    lines = [
        f"# Promotion Weekly Gate: **{v}**",
        "",
        f"*{results['n_periods']} periods, {results['n_dates']} rebalance dates*",
        "",
    ]

    for mode_key, mode_label in [("policy", "Per-Bucket Policy"), ("global", "Global Top-K")]:
        gate = results[mode_key]["gate"]
        base_agg = results[mode_key]["base_agg"]
        cand_agg = results[mode_key]["cand_agg"]

        status = "PASS" if gate["pass"] else "FAIL"
        lines.extend(
            [
                f"## {mode_label} Mode: **{status}**",
                "",
                "| Metric | Baseline | Candidate | Δ |",
                "|--------|----------|-----------|---|",
                f"| Mean weekly hedged | {_fmt_pct(base_agg['mean_hedged'])} "
                f"| {_fmt_pct(cand_agg['mean_hedged'])} "
                f"| {_fmt_pp(_pp(cand_agg['mean_hedged']) - _pp(base_agg['mean_hedged']) if base_agg['mean_hedged'] is not None and cand_agg['mean_hedged'] is not None else None)} |",
                f"| Cumulative hedged | {_fmt_pct(base_agg['cum_hedged'])} "
                f"| {_fmt_pct(cand_agg['cum_hedged'])} "
                f"| {_fmt_pp(_pp(cand_agg['cum_hedged']) - _pp(base_agg['cum_hedged']) if base_agg['cum_hedged'] is not None and cand_agg['cum_hedged'] is not None else None)} |",
                f"| Mean turnover | {_fmt_pct(base_agg['mean_turnover'])} "
                f"| {_fmt_pct(cand_agg['mean_turnover'])} | |",
                "",
                "### Checks",
                "",
                "| Check | Threshold | Actual | Result |",
                "|-------|-----------|--------|--------|",
            ]
        )
        for c in gate["checks"]:
            mark = "PASS" if c["pass"] else "**FAIL**"
            lines.append(f"| {c['name']} | {c['threshold']} | {c['actual']} | {mark} |")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "### Acceptance Rules",
            "",
            f"- Policy: cum hedged Δ >= {POLICY_CUM_HEDGED_MIN_PP:+.2f}pp "
            f"AND mean weekly Δ >= {POLICY_MEAN_HEDGED_MIN_PP:+.2f}pp",
            f"- Global: mean weekly Δ >= {GLOBAL_MEAN_HEDGED_MIN_PP:+.2f}pp "
            f"AND cum hedged Δ >= {GLOBAL_CUM_HEDGED_MIN_PP:+.2f}pp",
            f"- Bucket guardrail: no bucket mean weekly Δ <= {BUCKET_MEAN_HEDGED_FLOOR_PP:+.2f}pp",
            "",
        ]
    )

    out_path.write_text("\n".join(lines))
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Promotion weekly-live-sim gate")
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "portfolio_policy.json",
    )
    parser.add_argument(
        "--price-csv",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "price_history.csv",
    )
    parser.add_argument("--date-manifest", type=Path, required=True)
    parser.add_argument("--global-top-k", type=int, default=20)
    parser.add_argument("--buffer-ranks", type=int, default=30)
    parser.add_argument("--rebal-every", type=int, default=1)
    parser.add_argument("--cost-bps", type=float, default=30.0)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "research" / "promotion_weekly_gate",
    )
    args = parser.parse_args()

    # Discover common dates
    base_dates = set(discover_dates(args.baseline_root))
    cand_dates = set(discover_dates(args.candidate_root))
    allowed = load_date_manifest(args.date_manifest)
    common = sorted((base_dates & cand_dates) & allowed)

    print(f"Dates: {len(common)} (from {common[0]} to {common[-1]})")

    if len(common) < 2:
        print("ERROR: need >= 2 common dates")
        sys.exit(1)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    results = run_gate(
        baseline_root=args.baseline_root,
        candidate_root=args.candidate_root,
        policy_path=args.policy,
        price_csv=args.price_csv,
        dates=common,
        rebal_every=args.rebal_every,
        cost_bps=args.cost_bps,
        global_top_k=args.global_top_k,
        buffer_ranks=args.buffer_ranks,
        out_dir=args.out_dir,
    )

    # Write verdicts
    json_path = write_verdict_json(results, args.out_dir / "VERDICT.json")
    md_path = write_verdict_md(results, args.out_dir / "VERDICT.md")

    print(f"\nVerdict: {results['verdict']}")
    print(f"  Policy: {'PASS' if results['policy']['gate']['pass'] else 'FAIL'}")
    print(f"  Global: {'PASS' if results['global']['gate']['pass'] else 'FAIL'}")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")

    sys.exit(0 if results["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
