#!/usr/bin/env python3
"""Bucketed Verdict — automated PROMOTE/ARCHIVE decision for a specific bucket.

Runs evaluate() for candidate vs baseline with a bucket_filter, computes
delta metrics at each horizon, and produces a verdict.

Usage:
    python3 scripts/research/run_bucketed_verdict.py \
        --candidate-dir data/snapshots_reranked_v1100/ \
        --baseline-dir data/snapshots_reranked_baseline/ \
        --bucket binary_91_180
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.research.eval_by_bucket import BUCKET_FILTER_MAP

# Lazy import — evaluate is heavy
evaluate = None


def _get_evaluate():
    global evaluate
    if evaluate is None:
        from eval_forward_returns import evaluate as _eval

        evaluate = _eval
    return evaluate


def _extract_horizon_metrics(summary, horizons: List[int]) -> Dict[str, Dict]:
    """Extract per-horizon metrics from an EvalSummary."""
    result = {}
    for h in horizons:
        bh = summary.by_horizon.get(h, {})
        result[str(h)] = {
            "mean_net_return": bh.get("mean_net_return"),
            "mean_ic": bh.get("mean_ic"),
            "ic_t_stat": bh.get("ic_t_stat"),
            "mean_excess_return": bh.get("mean_excess_return"),
            "mean_hedged_return": bh.get("mean_hedged_return"),
            "mean_turnover": bh.get("mean_turnover"),
            "n_dates": bh.get("n_dates", 0),
        }
    return result


def compute_bucket_verdict(
    cand_by_horizon: Dict[str, Dict],
    base_by_horizon: Dict[str, Dict],
    primary_pp: float = 0.20,
    guardrail_pp: float = -0.05,
    metric_key: str = "mean_hedged_return",
) -> str:
    """Compute verdict from per-horizon metric dicts.

    PROMOTE if primary_h delta >= primary_pp AND guardrail_h delta >= guardrail_pp.
    ARCHIVE if primary_h delta < -0.10pp.
    NEEDS_MORE otherwise.

    metric_key: which return metric to compare (default: hedged, which is
    beta-neutral and more robust for A/B than raw net).
    Falls back to mean_net_return if hedged is None.
    """
    horizons = sorted(int(h) for h in cand_by_horizon.keys())
    if not horizons:
        return "NEEDS_MORE"

    primary_h = str(max(horizons))
    guardrail_h = str(sorted(horizons)[-2]) if len(horizons) >= 2 else None

    def _get_metric(by_h: Dict, h: str) -> float:
        d = by_h.get(h, {})
        val = d.get(metric_key)
        if val is None:
            val = d.get("mean_net_return")
        return val or 0

    c_val = _get_metric(cand_by_horizon, primary_h)
    b_val = _get_metric(base_by_horizon, primary_h)
    primary_delta_pp = (c_val - b_val) * 100

    guardrail_delta_pp = None
    if guardrail_h:
        gc = _get_metric(cand_by_horizon, guardrail_h)
        gb = _get_metric(base_by_horizon, guardrail_h)
        guardrail_delta_pp = (gc - gb) * 100

    primary_pass = primary_delta_pp >= primary_pp
    guardrail_pass = guardrail_delta_pp is None or guardrail_delta_pp >= guardrail_pp

    if primary_pass and guardrail_pass:
        return "PROMOTE"
    if primary_delta_pp < -0.10:
        return "ARCHIVE"
    return "NEEDS_MORE"


def run_bucketed_verdict(
    candidate_dir: Path,
    baseline_dir: Path,
    bucket: str,
    *,
    horizons: List[int] = None,
    oos_cutoff: str = "2025-01-01",
    primary_threshold_pp: float = 0.20,
    guardrail_threshold_pp: float = -0.05,
    price_csv: Optional[Path] = None,
    top_k: int = 20,
    cost_bps: float = 30.0,
    out_dir: Optional[Path] = None,
    family_filter: Optional[List[str]] = None,
    family_filter_mode: str = "primary",
    metric_key: str = "mean_hedged_return",
) -> Dict[str, Any]:
    """Run evaluate() with bucket_filter for both arms, compute verdict.

    Args:
        family_filter: If set, restrict to specific catalyst families
            (e.g. ["REGULATORY"] or ["CLINICAL"]).
        metric_key: Return metric for verdict comparison
            (default: mean_hedged_return for beta-neutral A/B).
    """
    if horizons is None:
        horizons = [84, 126]

    bucket_filter = BUCKET_FILTER_MAP.get(bucket)
    if bucket_filter is None:
        raise ValueError(f"Unknown bucket: {bucket}. Valid: {list(BUCKET_FILTER_MAP.keys())}")

    eval_fn = _get_evaluate()
    pcv = price_csv or (PROJECT_ROOT / "production_data" / "price_history.csv")

    eval_kwargs: Dict[str, Any] = dict(
        price_csv=pcv,
        horizons=horizons,
        top_k=top_k,
        cost_bps=cost_bps,
        date_from=oos_cutoff,
        bucket_filter=bucket_filter,
    )
    if family_filter:
        eval_kwargs["family_filter"] = family_filter
        eval_kwargs["family_filter_mode"] = family_filter_mode

    # Candidate arm (OOS only)
    cand_summary, _, _ = eval_fn(
        snapshot_root=candidate_dir,
        **eval_kwargs,
    )

    # Baseline arm (OOS only)
    base_summary, _, _ = eval_fn(
        snapshot_root=baseline_dir,
        **eval_kwargs,
    )

    cand_metrics = _extract_horizon_metrics(cand_summary, horizons)
    base_metrics = _extract_horizon_metrics(base_summary, horizons)

    verdict = compute_bucket_verdict(
        cand_metrics,
        base_metrics,
        primary_pp=primary_threshold_pp,
        guardrail_pp=guardrail_threshold_pp,
        metric_key=metric_key,
    )

    # Build evidence table
    evidence = []
    oos_delta = {}
    for h in horizons:
        sh = str(h)
        c_net = cand_metrics.get(sh, {}).get("mean_net_return") or 0
        b_net = base_metrics.get(sh, {}).get("mean_net_return") or 0
        delta_pp = round((c_net - b_net) * 100, 4)
        oos_delta[sh] = delta_pp
        evidence.append(
            {
                "horizon": h,
                "cand_net": round(c_net, 6),
                "base_net": round(b_net, 6),
                "delta_pp": delta_pp,
                "cand_ic": cand_metrics.get(sh, {}).get("mean_ic"),
                "base_ic": base_metrics.get(sh, {}).get("mean_ic"),
            }
        )

    recommendation = {
        "PROMOTE": "Candidate clears both primary and guardrail thresholds.",
        "ARCHIVE": "Candidate fails to beat baseline — archive.",
        "NEEDS_MORE": "Delta between thresholds — collect more data before deciding.",
    }.get(verdict, "")

    result = {
        "schema": "bucket_verdict.v2",
        "bucket": bucket,
        "bucket_filter": bucket_filter,
        "family_filter": family_filter,
        "family_filter_mode": family_filter_mode,
        "metric_key": metric_key,
        "verdict": verdict,
        "oos_cutoff": oos_cutoff,
        "oos_delta": oos_delta,
        "is_delta": {},  # placeholder — IS requires separate date_to run
        "evidence_table": evidence,
        "recommendation": recommendation,
        "thresholds": {
            "primary_pp": primary_threshold_pp,
            "guardrail_pp": guardrail_threshold_pp,
        },
        "n_dates_cand": cand_summary.n_dates,
        "n_dates_base": base_summary.n_dates,
    }

    # Write output if out_dir specified
    if out_dir:
        write_bucket_verdict(result, out_dir)

    return result


def write_bucket_verdict(result: Dict[str, Any], out_dir: Path) -> Tuple[Path, Path]:
    """Write VERDICT_{bucket}.md + .json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    bucket = result["bucket"]

    # JSON
    json_path = out_dir / f"VERDICT_{bucket}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    # Markdown
    md_path = out_dir / f"VERDICT_{bucket}.md"
    lines = [
        f"# Bucket Verdict: {bucket}",
        "",
        f"**Verdict**: **{result['verdict']}**",
        f"**OOS cutoff**: {result.get('oos_cutoff', '?')}",
        f"**Recommendation**: {result.get('recommendation', '')}",
        "",
        "## Evidence",
        "",
        "| Horizon | Cand Net | Base Net | Delta (pp) | Cand IC | Base IC |",
        "|---------|----------|----------|------------|---------|---------|",
    ]
    for e in result.get("evidence_table", []):
        c_ic = f"{e['cand_ic']:.4f}" if e.get("cand_ic") is not None else "—"
        b_ic = f"{e['base_ic']:.4f}" if e.get("base_ic") is not None else "—"
        lines.append(
            f"| {e['horizon']}d "
            f"| {e['cand_net']:.4%} "
            f"| {e['base_net']:.4%} "
            f"| {e['delta_pp']:+.3f} "
            f"| {c_ic} "
            f"| {b_ic} |"
        )
    lines.append("")
    thresholds = result.get("thresholds", {})
    if thresholds:
        lines.append(
            f"**Thresholds**: primary ≥ {thresholds.get('primary_pp', 0.20):+.2f}pp, "
            f"guardrail ≥ {thresholds.get('guardrail_pp', -0.05):+.2f}pp"
        )
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bucketed A/B verdict")
    parser.add_argument("--candidate-dir", type=Path, required=True, help="Candidate snapshot root")
    parser.add_argument("--baseline-dir", type=Path, required=True, help="Baseline snapshot root")
    parser.add_argument(
        "--bucket", type=str, required=True, choices=list(BUCKET_FILTER_MAP.keys()), help="Bucket to evaluate"
    )
    parser.add_argument("--horizons", default="84,126", help="Comma-separated horizons")
    parser.add_argument("--oos-cutoff", default="2025-01-01", help="OOS start date")
    parser.add_argument("--primary-threshold-pp", type=float, default=0.20)
    parser.add_argument("--guardrail-threshold-pp", type=float, default=-0.05)
    parser.add_argument("--price-csv", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--cost-bps", type=float, default=30.0)
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory (default: output/ab_verdict)")
    parser.add_argument(
        "--family-filter",
        type=str,
        default=None,
        help="Restrict to catalyst family (e.g. REGULATORY, CLINICAL)",
    )
    parser.add_argument(
        "--metric-key",
        type=str,
        default="mean_hedged_return",
        help="Return metric for verdict (default: mean_hedged_return)",
    )
    parser.add_argument(
        "--family-filter-mode",
        type=str,
        default="primary",
        choices=["primary", "secondary"],
        help=(
            "How to assign family membership. "
            "'primary' uses catalyst_family (nearest catalyst). "
            "'secondary' treats any ticker with has_regulatory_upcoming_180d=1 as REGULATORY."
        ),
    )
    args = parser.parse_args()

    horizons = [int(h.strip()) for h in args.horizons.split(",")]
    out_dir = args.out_dir or (PROJECT_ROOT / "output" / "ab_verdict")

    fam_filter = [args.family_filter] if args.family_filter else None

    result = run_bucketed_verdict(
        candidate_dir=args.candidate_dir,
        baseline_dir=args.baseline_dir,
        bucket=args.bucket,
        horizons=horizons,
        oos_cutoff=args.oos_cutoff,
        primary_threshold_pp=args.primary_threshold_pp,
        guardrail_threshold_pp=args.guardrail_threshold_pp,
        price_csv=args.price_csv,
        top_k=args.top_k,
        cost_bps=args.cost_bps,
        out_dir=out_dir,
        family_filter=fam_filter,
        family_filter_mode=args.family_filter_mode,
        metric_key=args.metric_key,
    )

    print(f"\nBucket: {result['bucket']}")
    print(f"Verdict: {result['verdict']}")
    print(f"Recommendation: {result['recommendation']}")
    for e in result["evidence_table"]:
        print(f"  {e['horizon']}d: delta = {e['delta_pp']:+.3f}pp")


if __name__ == "__main__":
    main()
