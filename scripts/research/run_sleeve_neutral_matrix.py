#!/usr/bin/env python3
"""Sleeve × universe matrix runner for exposure-neutral alpha experiments.

RESEARCH ONLY — not for production use.

Runs 6 experiments (3 sleeves × 2 universe modes) with sleeve-appropriate
horizons, then produces a combined MATRIX_REPORT.md with per-sleeve verdicts
and a go/no-go recommendation.

Example:
    python scripts/research/run_sleeve_neutral_matrix.py \
        --experiment-name sleeve_neutral_v1 \
        --date-from 2025-06-30 \
        --date-grid monthly
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from decision_engine import DecisionRuleset
from scripts.research.run_alpha_experiment import (
    DEFAULT_COST_BPS,
    DEFAULT_MISSINGNESS_THRESHOLD,
    ExperimentResult,
    _topk_overlap,
    generate_comparison_report,
    run_experiment,
)

# ---------------------------------------------------------------------------
# Matrix definition
# ---------------------------------------------------------------------------

SLEEVE_HORIZONS = {
    "all": [5, 20, 63],
    "binary": [5, 20, 84],
    "core": [84, 126],
}

DEFAULT_EXPOSURES = ["beta", "drawdown", "vol", "mcap"]

MATRIX_RUNS: List[Dict[str, Any]] = [
    {"sleeve": "all", "universe_mode": "current"},
    {"sleeve": "all", "universe_mode": "price_available"},
    {"sleeve": "binary", "universe_mode": "current"},
    {"sleeve": "binary", "universe_mode": "price_available"},
    {"sleeve": "core", "universe_mode": "current"},
    {"sleeve": "core", "universe_mode": "price_available"},
]


# ---------------------------------------------------------------------------
# Matrix runner
# ---------------------------------------------------------------------------


def run_matrix(
    experiment_name: str,
    snapshot_root: Path,
    price_csv: Path,
    ruleset: DecisionRuleset,
    exposure_names: List[str],
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    date_grid: str = "all",
    top_k: int = 20,
    cost_bps: float = DEFAULT_COST_BPS,
    missingness_threshold: float = DEFAULT_MISSINGNESS_THRESHOLD,
    min_cols: int = 50,
) -> List[Dict[str, Any]]:
    """Run the full sleeve × universe matrix.

    Returns a list of dicts, one per run, containing:
        sleeve, universe_mode, horizons, baseline, neutralized, overlap
    """
    results: List[Dict[str, Any]] = []

    for i, run_def in enumerate(MATRIX_RUNS, 1):
        sleeve = run_def["sleeve"]
        universe_mode = run_def["universe_mode"]
        horizons = SLEEVE_HORIZONS[sleeve]
        run_name = f"{experiment_name}_{sleeve}_{universe_mode}"

        print(f"\n{'='*60}")
        print(f"Matrix run {i}/{len(MATRIX_RUNS)}: sleeve={sleeve}, " f"universe={universe_mode}, horizons={horizons}")
        print(f"{'='*60}")

        baseline, neutralized = run_experiment(
            experiment_name=run_name,
            mode="compare",
            snapshot_root=snapshot_root,
            price_csv=price_csv,
            ruleset=ruleset,
            horizons=horizons,
            top_k=top_k,
            exposure_names=exposure_names,
            date_from=date_from,
            date_to=date_to,
            min_cols=min_cols,
            date_grid=date_grid,
            universe_mode=universe_mode,
            missingness_threshold=missingness_threshold,
            sleeve=sleeve,
        )

        overlap = None
        if neutralized and baseline.n_dates > 0 and neutralized.n_dates > 0:
            overlap = _topk_overlap(baseline, neutralized, top_k)

        results.append(
            {
                "sleeve": sleeve,
                "universe_mode": universe_mode,
                "horizons": horizons,
                "baseline": baseline,
                "neutralized": neutralized,
                "overlap": overlap,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------


def _compute_verdict(
    baseline: ExperimentResult,
    neutralized: Optional[ExperimentResult],
    overlap: Optional[Dict[str, Any]],
    ref_horizon: int,
    cost_bps: float,
) -> Dict[str, Any]:
    """Compute per-run verdict based on IC, overlap, and net returns."""
    if not neutralized or baseline.n_dates == 0 or neutralized.n_dates == 0:
        return {"verdict": "INCONCLUSIVE", "reason": "Insufficient data"}

    b_ic = baseline.mean_ic.get(ref_horizon)
    n_ic = neutralized.mean_ic.get(ref_horizon)
    if b_ic is None or n_ic is None:
        return {"verdict": "INCONCLUSIVE", "reason": f"No IC at {ref_horizon}d"}

    ic_delta = n_ic - b_ic
    ic_rel = ic_delta / abs(b_ic) * 100 if abs(b_ic) > 1e-6 else 0.0

    mean_jac = overlap.get("mean_jaccard") if overlap else None
    churn_ok = mean_jac is not None and mean_jac >= 0.70

    # Net returns after costs
    b_gross = baseline.mean_gross.get(ref_horizon)
    n_gross = neutralized.mean_gross.get(ref_horizon)
    if b_gross is not None and n_gross is not None and mean_jac is not None:
        churn_fraction = 1.0 - mean_jac
        b_net = b_gross - (0.5 * churn_fraction * cost_bps / 10_000)
        n_net = n_gross - (churn_fraction * cost_bps / 10_000)
        net_delta = n_net - b_net
    else:
        b_net = b_gross
        n_net = n_gross
        net_delta = None

    # Decision criteria
    ic_improves = ic_rel >= 2.5
    net_improves = net_delta is not None and net_delta > 0

    if ic_improves and net_improves and churn_ok:
        verdict = "PROMOTE"
        reason = f"IC +{ic_rel:.1f}% rel, net return +{net_delta:+.4%}, " f"Jaccard={mean_jac:.3f}"
    elif ic_improves and not churn_ok:
        verdict = "INVESTIGATE"
        jac_str = f"{mean_jac:.3f}" if mean_jac is not None else "N/A"
        reason = f"IC +{ic_rel:.1f}% rel but Jaccard={jac_str} < 0.70"
    elif ic_improves and churn_ok and not net_improves:
        verdict = "INVESTIGATE"
        nd_str = f"{net_delta:+.4%}" if net_delta is not None else "N/A"
        reason = f"IC +{ic_rel:.1f}% rel, churn OK, but net return flat ({nd_str})"
    elif abs(ic_rel) < 2.5:
        verdict = "KEEP BASELINE"
        reason = f"IC change negligible ({ic_rel:+.1f}% rel)"
    else:
        verdict = "REJECT"
        reason = f"IC degrades {ic_rel:+.1f}% rel"

    return {
        "verdict": verdict,
        "reason": reason,
        "ic_baseline": b_ic,
        "ic_neutralized": n_ic,
        "ic_delta": ic_delta,
        "ic_rel_pct": ic_rel,
        "mean_jaccard": mean_jac,
        "net_baseline": b_net,
        "net_neutralized": n_net,
        "net_delta": net_delta,
    }


# ---------------------------------------------------------------------------
# Matrix report
# ---------------------------------------------------------------------------


def generate_matrix_report(
    results: List[Dict[str, Any]],
    experiment_name: str,
    exposure_names: List[str],
    cost_bps: float,
) -> str:
    """Generate a combined matrix report."""
    lines: List[str] = []
    lines.append(f"# Sleeve-Neutral Matrix Report: {experiment_name}")
    lines.append("")
    lines.append(f"- **Exposures**: {', '.join(exposure_names)}")
    lines.append(f"- **Cost assumption**: {cost_bps} bps")
    lines.append("")

    # --- 1. Summary table ---
    lines.append("## 1. Summary")
    lines.append("")
    lines.append("| # | Sleeve | Universe | Horizons | Dates | Verdict |")
    lines.append("|---|--------|----------|----------|-------|---------|")

    verdicts: List[Dict[str, Any]] = []
    for i, r in enumerate(results, 1):
        baseline = r["baseline"]
        neutralized = r["neutralized"]
        overlap = r["overlap"]
        horizons = r["horizons"]
        # Use longest horizon as reference for verdict
        ref_h = horizons[-1]
        v = _compute_verdict(baseline, neutralized, overlap, ref_h, cost_bps)
        v["sleeve"] = r["sleeve"]
        v["universe_mode"] = r["universe_mode"]
        v["ref_horizon"] = ref_h
        verdicts.append(v)

        lines.append(
            f"| {i} | {r['sleeve']} | {r['universe_mode']} | "
            f"{','.join(str(h) for h in horizons)} | {baseline.n_dates} | "
            f"**{v['verdict']}** |"
        )
    lines.append("")

    # --- 2. IC comparison ---
    lines.append("## 2. IC Comparison")
    lines.append("")
    lines.append("| Sleeve | Universe | Horizon | Baseline IC | Neutral IC | Delta | Rel % |")
    lines.append("|--------|----------|---------|-------------|------------|-------|-------|")
    for r in results:
        baseline = r["baseline"]
        neutralized = r["neutralized"]
        if not neutralized:
            continue
        for h in r["horizons"]:
            b_ic = baseline.mean_ic.get(h)
            n_ic = neutralized.mean_ic.get(h)
            b_s = f"{b_ic:.4f}" if b_ic is not None else "—"
            n_s = f"{n_ic:.4f}" if n_ic is not None else "—"
            if b_ic is not None and n_ic is not None:
                d = n_ic - b_ic
                rel = d / abs(b_ic) * 100 if abs(b_ic) > 1e-6 else 0.0
                d_s = f"{d:+.4f}"
                r_s = f"{rel:+.1f}%"
            else:
                d_s = "—"
                r_s = "—"
            lines.append(f"| {r['sleeve']} | {r['universe_mode']} | {h}d | " f"{b_s} | {n_s} | {d_s} | {r_s} |")
    lines.append("")

    # --- 3. Top-K churn (Jaccard) ---
    lines.append("## 3. Top-K Churn Impact (Jaccard Overlap)")
    lines.append("")
    lines.append("| Sleeve | Universe | Mean Jaccard | Min Jaccard | Status |")
    lines.append("|--------|----------|--------------|-------------|--------|")
    for r in results:
        overlap = r["overlap"]
        if overlap:
            mj = overlap.get("mean_jaccard")
            mi = overlap.get("min_jaccard")
            mj_s = f"{mj:.3f}" if mj is not None else "—"
            mi_s = f"{mi:.3f}" if mi is not None else "—"
            status = "OK" if mj is not None and mj >= 0.70 else "HIGH CHURN"
        else:
            mj_s = mi_s = "—"
            status = "N/A"
        lines.append(f"| {r['sleeve']} | {r['universe_mode']} | {mj_s} | {mi_s} | {status} |")
    lines.append("")

    # --- 4. Exposure reduction ---
    lines.append("## 4. Exposure Reduction (Mean Top-K Shift)")
    lines.append("")
    lines.append("| Sleeve | Universe | " + " | ".join(f"{e} Δ" for e in exposure_names) + " |")
    lines.append("|--------|----------| " + " | ".join("------" for _ in exposure_names) + " |")
    for r in results:
        baseline = r["baseline"]
        neutralized = r["neutralized"]
        deltas = []
        for e in exposure_names:
            b_v = baseline.mean_exposure_topk.get(e)
            n_v = neutralized.mean_exposure_topk.get(e) if neutralized else None
            if b_v is not None and n_v is not None:
                deltas.append(f"{(n_v - b_v):+.4f}")
            else:
                deltas.append("—")
        lines.append(f"| {r['sleeve']} | {r['universe_mode']} | " + " | ".join(deltas) + " |")
    lines.append("")

    # --- 5. Net returns after costs ---
    lines.append("## 5. Net Returns After Costs")
    lines.append("")
    lines.append("| Sleeve | Universe | Horizon | Baseline Net | Neutral Net | Net Δ |")
    lines.append("|--------|----------|---------|-------------|-------------|-------|")
    for r, v in zip(results, verdicts):
        ref_h = v["ref_horizon"]
        b_net = v.get("net_baseline")
        n_net = v.get("net_neutralized")
        nd = v.get("net_delta")
        b_s = f"{b_net:+.4%}" if b_net is not None else "—"
        n_s = f"{n_net:+.4%}" if n_net is not None else "—"
        nd_s = f"{nd:+.4%}" if nd is not None else "—"
        lines.append(f"| {r['sleeve']} | {r['universe_mode']} | {ref_h}d | " f"{b_s} | {n_s} | {nd_s} |")
    lines.append("")

    # --- 6. Go/No-Go ---
    lines.append("## 6. Go/No-Go Recommendation")
    lines.append("")
    for v in verdicts:
        lines.append(f"- **{v['sleeve']}** ({v['universe_mode']}): " f"**{v['verdict']}** — {v['reason']}")
    lines.append("")

    # Combined recommendation
    promote_count = sum(1 for v in verdicts if v["verdict"] == "PROMOTE")
    reject_count = sum(1 for v in verdicts if v["verdict"] == "REJECT")
    if promote_count >= 4:
        combined = "PROMOTE"
        combined_reason = f"{promote_count}/6 runs recommend promotion"
    elif reject_count >= 3:
        combined = "REJECT"
        combined_reason = f"{reject_count}/6 runs show degradation"
    elif promote_count >= 2:
        combined = "INVESTIGATE"
        combined_reason = (
            f"{promote_count}/6 promote — consider sleeve-specific " "neutralization for promoted sleeves only"
        )
    else:
        combined = "KEEP BASELINE"
        combined_reason = "Insufficient evidence for sleeve-level neutralization"

    lines.append(f"**Combined: {combined}** — {combined_reason}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sleeve × universe matrix for exposure-neutral alpha experiments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--experiment-name", required=True, help="Name for this matrix run")
    parser.add_argument("--snapshot-root", type=Path, default=PROJECT_ROOT / "data" / "snapshots")
    parser.add_argument("--price-csv", type=Path, default=PROJECT_ROOT / "production_data" / "price_history.csv")
    parser.add_argument("--ruleset", type=Path, default=None, help="Path to ruleset JSON (default: latest snapshot)")
    parser.add_argument(
        "--exposures", type=str, default=",".join(DEFAULT_EXPOSURES), help="Comma-separated exposure names"
    )
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--date-from", type=str, default=None)
    parser.add_argument("--date-to", type=str, default=None)
    parser.add_argument("--date-grid", choices=["all", "monthly"], default="all")
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    parser.add_argument(
        "--out-root", type=Path, default=None, help="Output directory (default: output/alpha_experiments/{name})"
    )
    parser.add_argument("--min-cols", type=int, default=50)
    parser.add_argument("--missingness-threshold", type=float, default=DEFAULT_MISSINGNESS_THRESHOLD)
    args = parser.parse_args()

    exposure_names = [e.strip() for e in args.exposures.split(",") if e.strip()]

    # Load ruleset
    if args.ruleset:
        ruleset = DecisionRuleset.from_json(str(args.ruleset))
    else:
        dates = sorted(
            [
                p.name
                for p in args.snapshot_root.iterdir()
                if p.is_dir() and len(p.name) == 10 and p.name[4] == "-" and (p / "decision_ruleset.json").exists()
            ]
        )
        if not dates:
            print("ERROR: No snapshot with decision_ruleset.json found")
            sys.exit(1)
        rs_path = args.snapshot_root / dates[-1] / "decision_ruleset.json"
        ruleset = DecisionRuleset.from_json(str(rs_path))
    print(f"Ruleset: {ruleset.ruleset_id}")

    out_root = args.out_root or (PROJECT_ROOT / "output" / "alpha_experiments" / args.experiment_name)
    out_root.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    results = run_matrix(
        experiment_name=args.experiment_name,
        snapshot_root=args.snapshot_root,
        price_csv=args.price_csv,
        ruleset=ruleset,
        exposure_names=exposure_names,
        date_from=args.date_from,
        date_to=args.date_to,
        date_grid=args.date_grid,
        top_k=args.top_k,
        cost_bps=args.cost_bps,
        missingness_threshold=args.missingness_threshold,
        min_cols=args.min_cols,
    )
    elapsed = time.time() - t0

    # Save per-run results
    for i, r in enumerate(results, 1):
        run_label = f"{r['sleeve']}_{r['universe_mode']}"
        run_dir = out_root / run_label
        run_dir.mkdir(parents=True, exist_ok=True)

        baseline = r["baseline"]
        neutralized = r["neutralized"]

        if baseline.n_dates > 0:
            with open(run_dir / "baseline.json", "w", encoding="utf-8") as f:
                json.dump(baseline.to_dict(), f, indent=2, default=str)

        if neutralized and neutralized.n_dates > 0:
            with open(run_dir / "neutralized.json", "w", encoding="utf-8") as f:
                json.dump(neutralized.to_dict(), f, indent=2, default=str)

        if r["overlap"]:
            with open(run_dir / "overlap.json", "w", encoding="utf-8") as f:
                json.dump(r["overlap"], f, indent=2)

        # Per-run comparison report
        report = generate_comparison_report(
            baseline,
            neutralized,
            exposure_names,
            sleeve=r["sleeve"],
        )
        with open(run_dir / "compare.md", "w", encoding="utf-8") as f:
            f.write(report)

    # Generate combined matrix report
    matrix_report = generate_matrix_report(
        results,
        args.experiment_name,
        exposure_names,
        args.cost_bps,
    )
    report_path = out_root / "MATRIX_REPORT.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(matrix_report)

    print(f"\n{'='*60}")
    print(f"Matrix complete: {len(results)} runs in {elapsed:.1f}s")
    print(f"Report: {report_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
