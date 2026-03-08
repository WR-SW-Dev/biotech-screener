#!/usr/bin/env python3
"""Bucketed Forward-Return Evaluation.

Runs eval_forward_returns.evaluate() separately for each action list bucket,
then produces a combined VERDICT.md comparing bucket-level metrics.

Buckets:
    binary_0_30    catalyst_mode==specific_days, 1<=days<=30
    binary_31_90   catalyst_mode==specific_days, 31<=days<=90
    binary_91_180  catalyst_mode==specific_days, 91<=days<=180
    less_binary    everything else

For each bucket, computes: IC, net return, excess vs XBI, hedged, turnover.
Results go into the audited run folder.

Usage:
    python3 scripts/research/eval_by_bucket.py \\
        --snapshot-root data/snapshots \\
        --price-csv production_data/price_history.csv \\
        --out-dir output/eval_by_bucket \\
        --horizons 84,126 \\
        --benchmark XBI
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Bucket → catalyst_bucket values that map to it
# These align with assign_catalyst_bucket() output in decision_engine.py
BUCKET_FILTER_MAP: Dict[str, List[str]] = {
    "binary_0_30": ["binary_now"],
    "binary_31_90": ["build_window"],
    "binary_91_180": ["less_binary"],
    "less_binary": ["core"],
}

# Display names
BUCKET_DISPLAY = {
    "binary_0_30": "Binary 0-30d",
    "binary_31_90": "Binary 31-90d",
    "binary_91_180": "Binary 91-180d",
    "less_binary": "Less Binary",
}

# Aggregate books
BINARY_BUCKETS = ["binary_0_30", "binary_31_90", "binary_91_180"]
ALL_BUCKETS = ["binary_0_30", "binary_31_90", "binary_91_180", "less_binary"]

SCHEMA = "eval_by_bucket.v1"


def _fmt(v: Optional[float], decimals: int = 4) -> str:
    if v is None:
        return "\u2014"
    return f"{v:.{decimals}f}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "\u2014"
    return f"{v:.2%}"


def run_bucket_eval(
    snapshot_root: Path,
    price_csv: Path,
    horizons: List[int],
    out_dir: Path,
    *,
    top_k: int = 20,
    cost_bps: float = 30.0,
    benchmark: str = "XBI",
    anchor_mode: str = "prev_trading_day",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    date_manifest: Optional[Path] = None,
    rebalance_buffer_ranks: int = 0,
    industry_neutral: bool = False,
) -> Dict[str, Any]:
    """Run evaluate() for each bucket and return combined results.

    Returns a dict with schema, per-bucket summaries, and aggregate metrics.
    """
    from eval_forward_returns import evaluate

    # Load date manifest if provided
    allowed_dates: Optional[set] = None
    if date_manifest:
        raw = date_manifest.read_text().splitlines()
        allowed_dates = {d.strip() for d in raw if d.strip()}

    results: Dict[str, Any] = {
        "schema": SCHEMA,
        "horizons": horizons,
        "top_k": top_k,
        "cost_bps": cost_bps,
        "benchmark": benchmark,
        "buckets": {},
    }

    for bucket_name in ALL_BUCKETS:
        bucket_filter = BUCKET_FILTER_MAP[bucket_name]
        bucket_out = out_dir / bucket_name

        print(f"\n{'='*60}")
        print(f"Evaluating bucket: {BUCKET_DISPLAY[bucket_name]} (filter={bucket_filter})")
        print(f"{'='*60}")

        summary, date_results, skips = evaluate(
            snapshot_root=snapshot_root,
            price_csv=price_csv,
            horizons=horizons,
            top_k=top_k,
            cost_bps=cost_bps,
            date_from=date_from,
            date_to=date_to,
            allowed_dates=allowed_dates,
            anchor_mode=anchor_mode,
            benchmark=benchmark,
            out_dir=bucket_out,
            bucket_filter=bucket_filter,
            rebalance_buffer_ranks=rebalance_buffer_ranks,
            industry_neutral=industry_neutral,
        )

        # Extract per-horizon metrics
        bucket_metrics: Dict[str, Any] = {
            "display_name": BUCKET_DISPLAY[bucket_name],
            "filter": bucket_filter,
            "n_evaluated": summary.n_evaluated,
            "n_dates": summary.n_dates,
            "by_horizon": {},
        }

        for h in horizons:
            bh = summary.by_horizon.get(h, {})
            bucket_metrics["by_horizon"][h] = {
                "n_dates": bh.get("n_dates", 0),
                "mean_ic": bh.get("mean_ic"),
                "ic_t_stat": bh.get("ic_t_stat"),
                "mean_net_return": bh.get("mean_net_return"),
                "mean_excess_return": bh.get("mean_excess_return"),
                "mean_hedged_return": bh.get("mean_hedged_return"),
                "mean_turnover": bh.get("mean_turnover"),
                "mean_industry_neutral_ic": bh.get("mean_industry_neutral_ic"),
            }

        results["buckets"][bucket_name] = bucket_metrics

    return results


def write_verdict_md(results: Dict[str, Any], out_dir: Path) -> Path:
    """Write VERDICT.md comparing bucket-level metrics."""
    lines: List[str] = []
    lines.append("# Bucketed Evaluation Verdict")
    lines.append("")
    lines.append(f"**Horizons**: {results['horizons']}")
    lines.append(f"**Top-K**: {results['top_k']}")
    lines.append(f"**Cost**: {results['cost_bps']} bps")
    lines.append(f"**Benchmark**: {results['benchmark']}")
    lines.append("")

    for h in results["horizons"]:
        lines.append(f"## {h}-Day Horizon")
        lines.append("")
        lines.append("| Bucket | N | Mean IC | IC t | Net Return | " "Excess | Hedged | Turnover |")
        lines.append("|--------|---|---------|------|------------|" "--------|--------|----------|")

        for bucket_name in ALL_BUCKETS:
            bm = results["buckets"].get(bucket_name, {})
            bh = bm.get("by_horizon", {}).get(h, {})
            display = BUCKET_DISPLAY.get(bucket_name, bucket_name)
            lines.append(
                f"| {display} "
                f"| {bh.get('n_dates', 0)} "
                f"| {_fmt(bh.get('mean_ic'))} "
                f"| {_fmt(bh.get('ic_t_stat'), 2)} "
                f"| {_fmt_pct(bh.get('mean_net_return'))} "
                f"| {_fmt_pct(bh.get('mean_excess_return'))} "
                f"| {_fmt_pct(bh.get('mean_hedged_return'))} "
                f"| {_fmt(bh.get('mean_turnover'))} |"
            )
        lines.append("")

    # Binary vs less-binary aggregate comparison
    lines.append("## Binary vs Less-Binary Aggregate")
    lines.append("")
    for h in results["horizons"]:
        binary_ics = []
        binary_nets = []
        lb_metrics = results["buckets"].get("less_binary", {}).get("by_horizon", {}).get(h, {})

        for b in BINARY_BUCKETS:
            bh = results["buckets"].get(b, {}).get("by_horizon", {}).get(h, {})
            if bh.get("mean_ic") is not None:
                binary_ics.append(bh["mean_ic"])
            if bh.get("mean_net_return") is not None:
                binary_nets.append(bh["mean_net_return"])

        import statistics as _stats

        avg_binary_ic = _stats.mean(binary_ics) if binary_ics else None
        avg_binary_net = _stats.mean(binary_nets) if binary_nets else None
        lb_ic = lb_metrics.get("mean_ic")
        lb_net = lb_metrics.get("mean_net_return")

        lines.append(
            f"**{h}d**: Binary avg IC={_fmt(avg_binary_ic)}, "
            f"Net={_fmt_pct(avg_binary_net)} | "
            f"Less-binary IC={_fmt(lb_ic)}, Net={_fmt_pct(lb_net)}"
        )

    lines.append("")

    path = out_dir / "VERDICT.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run forward-return evaluation per action list bucket.",
    )
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--price-csv", type=Path, required=True)
    parser.add_argument("--horizons", default="84,126")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--cost-bps", type=float, default=30.0)
    parser.add_argument("--benchmark", default="XBI")
    parser.add_argument("--anchor-mode", default="prev_trading_day")
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--date-manifest", type=Path, default=None)
    parser.add_argument("--rebalance-buffer-ranks", type=int, default=0)
    parser.add_argument("--industry-neutral", action="store_true", default=False)
    args = parser.parse_args()

    horizons = [int(h.strip()) for h in args.horizons.split(",")]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    results = run_bucket_eval(
        snapshot_root=args.snapshot_root,
        price_csv=args.price_csv,
        horizons=horizons,
        out_dir=args.out_dir,
        top_k=args.top_k,
        cost_bps=args.cost_bps,
        benchmark=args.benchmark,
        anchor_mode=args.anchor_mode,
        date_from=args.date_from,
        date_to=args.date_to,
        date_manifest=args.date_manifest,
        rebalance_buffer_ranks=args.rebalance_buffer_ranks,
        industry_neutral=args.industry_neutral,
    )

    # Write combined results
    json_path = args.out_dir / "bucket_eval.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    verdict_path = write_verdict_md(results, args.out_dir)

    print(f"\nResults → {args.out_dir}")
    print(f"  bucket_eval.json → {json_path}")
    print(f"  VERDICT.md       → {verdict_path}")

    # Print summary
    for h in horizons:
        print(f"\n  {h}d:")
        for b in ALL_BUCKETS:
            bh = results["buckets"].get(b, {}).get("by_horizon", {}).get(h, {})
            print(
                f"    {BUCKET_DISPLAY[b]:25s} "
                f"IC={_fmt(bh.get('mean_ic'))}, "
                f"Net={_fmt_pct(bh.get('mean_net_return'))}, "
                f"Turn={_fmt(bh.get('mean_turnover'))}"
            )


if __name__ == "__main__":
    main()
