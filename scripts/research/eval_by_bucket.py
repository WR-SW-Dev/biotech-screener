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
    "microcap_inversion": "Microcap Inversion (XS bottom-K)",
}

# Aggregate books
BINARY_BUCKETS = ["binary_0_30", "binary_31_90", "binary_91_180"]
ALL_BUCKETS = ["binary_0_30", "binary_31_90", "binary_91_180", "less_binary"]

# Microcap inversion sleeve: XS-band names from core bucket, bottom-K (contrarian)
MICROCAP_BUCKET_FILTER = ["core"]
MICROCAP_SIZE_BANDS = ("XS",)
MICROCAP_HORIZONS = [84, 126]

SCHEMA = "eval_by_bucket.v1"

# Bucket-specific horizon defaults: primary + guardrail per bucket.
# binary_0_30: highest vol, event imminent → short horizons
# binary_31_90: setup window → 63d primary, 84d guardrail
# binary_91_180: pipeline on deck → 126d primary, 84d guardrail
# less_binary: carry/quality → 126d primary, 84d guardrail
BUCKET_DEFAULT_HORIZONS: Dict[str, List[int]] = {
    "binary_0_30": [20, 63],
    "binary_31_90": [63, 84],
    "binary_91_180": [84, 126],
    "less_binary": [84, 126],
}

# Family-specific horizon overrides: when a (bucket, family) pair has different
# pricing dynamics than the bucket default.
# Regulatory events (PDUFA, AdCom) tend to reprice in the 31-90 window.
# Clinical events (PCD, data readout) carry into 91-180.
FAMILY_HORIZON_MAP: Dict[str, List[int]] = {
    # (bucket__family) → horizons
    "binary_0_30__REGULATORY": [20, 63],  # same as bucket default
    "binary_0_30__CLINICAL": [20, 63],  # same — too short to differentiate
    "binary_31_90__REGULATORY": [63, 84],  # regulatory reprices in setup window
    "binary_31_90__CLINICAL": [84, 126],  # clinical carry extends beyond 90d
    "binary_91_180__REGULATORY": [63, 84],  # rare regulatory > 90d, use shorter
    "binary_91_180__CLINICAL": [84, 126],  # clinical on-deck → full carry
}


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
    bucket_specific_horizons: bool = False,
    include_microcap_sleeve: bool = False,
    include_family_splits: bool = False,
    family_filter_mode: str = "primary",
) -> Dict[str, Any]:
    """Run evaluate() for each bucket and return combined results.

    Args:
        horizons: Default horizons used when bucket_specific_horizons is False.
        bucket_specific_horizons: If True, use BUCKET_DEFAULT_HORIZONS per bucket
            instead of the uniform ``horizons`` list.  Each bucket gets its own
            primary + guardrail horizons aligned to how the setup monetizes.
        include_microcap_sleeve: If True, add a microcap inversion bucket
            (core/XS, bottom-K) to the results.

    Returns a dict with schema, per-bucket summaries, and aggregate metrics.
    """
    from eval_forward_returns import evaluate

    # Load date manifest if provided
    allowed_dates: Optional[set] = None
    if date_manifest:
        raw = date_manifest.read_text().splitlines()
        allowed_dates = {d.strip() for d in raw if d.strip()}

    # Collect all horizons that will appear across any bucket
    all_horizons_set: set = set(horizons)
    if bucket_specific_horizons:
        for bh_list in BUCKET_DEFAULT_HORIZONS.values():
            all_horizons_set.update(bh_list)

    results: Dict[str, Any] = {
        "schema": SCHEMA,
        "horizons": sorted(all_horizons_set),
        "top_k": top_k,
        "cost_bps": cost_bps,
        "benchmark": benchmark,
        "bucket_specific_horizons": bucket_specific_horizons,
        "buckets": {},
    }

    for bucket_name in ALL_BUCKETS:
        bucket_filter = BUCKET_FILTER_MAP[bucket_name]
        bucket_out = out_dir / bucket_name
        bucket_out.mkdir(parents=True, exist_ok=True)

        # Choose horizons for this bucket
        if bucket_specific_horizons:
            eff_horizons = BUCKET_DEFAULT_HORIZONS.get(bucket_name, horizons)
        else:
            eff_horizons = horizons

        print(f"\n{'='*60}")
        print(f"Evaluating bucket: {BUCKET_DISPLAY[bucket_name]} " f"(filter={bucket_filter}, horizons={eff_horizons})")
        print(f"{'='*60}")

        summary, date_results, skips = evaluate(
            snapshot_root=snapshot_root,
            price_csv=price_csv,
            horizons=eff_horizons,
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
            "horizons": eff_horizons,
            "n_evaluated": summary.n_evaluated,
            "n_dates": summary.n_dates,
            "by_horizon": {},
        }

        for h in eff_horizons:
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

    # Regulatory vs Clinical sub-splits within binary buckets (opt-in)
    if include_family_splits:
        FAMILY_SPLITS = {
            "REGULATORY": ["REGULATORY"],
            "CLINICAL": ["CLINICAL"],
        }
        results["family_splits"] = {}

        for bucket_name in BINARY_BUCKETS:
            bucket_filter = BUCKET_FILTER_MAP[bucket_name]
            if bucket_specific_horizons:
                eff_horizons = BUCKET_DEFAULT_HORIZONS.get(bucket_name, horizons)
            else:
                eff_horizons = horizons

            for family_name, family_values in FAMILY_SPLITS.items():
                split_key = f"{bucket_name}__{family_name}"
                split_out = out_dir / "family_splits" / split_key
                split_out.mkdir(parents=True, exist_ok=True)

                # Family-specific horizon override (if available and bucket-specific mode)
                if bucket_specific_horizons:
                    eff_horizons = FAMILY_HORIZON_MAP.get(split_key, eff_horizons)
                    all_horizons_set.update(eff_horizons)

                print(f"\n{'='*60}")
                print(f"Family split: {BUCKET_DISPLAY[bucket_name]} / {family_name} " f"(horizons={eff_horizons})")
                print(f"{'='*60}")

                summary, _, _ = evaluate(
                    snapshot_root=snapshot_root,
                    price_csv=price_csv,
                    horizons=eff_horizons,
                    top_k=top_k,
                    cost_bps=cost_bps,
                    date_from=date_from,
                    date_to=date_to,
                    allowed_dates=allowed_dates,
                    anchor_mode=anchor_mode,
                    benchmark=benchmark,
                    out_dir=split_out,
                    bucket_filter=bucket_filter,
                    rebalance_buffer_ranks=rebalance_buffer_ranks,
                    industry_neutral=industry_neutral,
                    family_filter=family_values,
                    family_filter_mode=family_filter_mode,
                )

                split_metrics: Dict[str, Any] = {
                    "display_name": f"{BUCKET_DISPLAY[bucket_name]} / {family_name}",
                    "bucket": bucket_name,
                    "family": family_name,
                    "filter": bucket_filter,
                    "family_filter": family_values,
                    "horizons": eff_horizons,
                    "n_evaluated": summary.n_evaluated,
                    "n_dates": summary.n_dates,
                    "by_horizon": {},
                }

                for h in eff_horizons:
                    bh = summary.by_horizon.get(h, {})
                    split_metrics["by_horizon"][h] = {
                        "n_dates": bh.get("n_dates", 0),
                        "mean_ic": bh.get("mean_ic"),
                        "ic_t_stat": bh.get("ic_t_stat"),
                        "mean_net_return": bh.get("mean_net_return"),
                        "mean_excess_return": bh.get("mean_excess_return"),
                        "mean_hedged_return": bh.get("mean_hedged_return"),
                        "mean_turnover": bh.get("mean_turnover"),
                    }

                results["family_splits"][split_key] = split_metrics

    # Microcap inversion sleeve (opt-in)
    if include_microcap_sleeve:
        mc_name = "microcap_inversion"
        mc_out = out_dir / mc_name
        mc_out.mkdir(parents=True, exist_ok=True)
        mc_horizons = MICROCAP_HORIZONS

        if bucket_specific_horizons:
            all_horizons_set.update(mc_horizons)
            results["horizons"] = sorted(all_horizons_set)

        print(f"\n{'='*60}")
        print(
            f"Evaluating sleeve: {BUCKET_DISPLAY[mc_name]} "
            f"(filter={MICROCAP_BUCKET_FILTER}, size={MICROCAP_SIZE_BANDS}, "
            f"mode=bottom, horizons={mc_horizons})"
        )
        print(f"{'='*60}")

        mc_summary, _, _ = evaluate(
            snapshot_root=snapshot_root,
            price_csv=price_csv,
            horizons=mc_horizons,
            top_k=top_k,
            cost_bps=cost_bps,
            date_from=date_from,
            date_to=date_to,
            allowed_dates=allowed_dates,
            anchor_mode=anchor_mode,
            benchmark=benchmark,
            out_dir=mc_out,
            bucket_filter=MICROCAP_BUCKET_FILTER,
            rebalance_buffer_ranks=rebalance_buffer_ranks,
            industry_neutral=industry_neutral,
            selection_mode="bottom",
            min_mcap_buckets=MICROCAP_SIZE_BANDS,
        )

        mc_metrics: Dict[str, Any] = {
            "display_name": BUCKET_DISPLAY[mc_name],
            "filter": MICROCAP_BUCKET_FILTER,
            "size_bands": list(MICROCAP_SIZE_BANDS),
            "selection_mode": "bottom",
            "horizons": mc_horizons,
            "n_evaluated": mc_summary.n_evaluated,
            "n_dates": mc_summary.n_dates,
            "by_horizon": {},
        }

        for h in mc_horizons:
            bh = mc_summary.by_horizon.get(h, {})
            mc_metrics["by_horizon"][h] = {
                "n_dates": bh.get("n_dates", 0),
                "mean_ic": bh.get("mean_ic"),
                "ic_t_stat": bh.get("ic_t_stat"),
                "mean_net_return": bh.get("mean_net_return"),
                "mean_excess_return": bh.get("mean_excess_return"),
                "mean_hedged_return": bh.get("mean_hedged_return"),
                "mean_turnover": bh.get("mean_turnover"),
                "mean_industry_neutral_ic": bh.get("mean_industry_neutral_ic"),
            }

        results["buckets"][mc_name] = mc_metrics

    return results


def write_verdict_md(results: Dict[str, Any], out_dir: Path) -> Path:
    """Write VERDICT.md comparing bucket-level metrics."""
    import statistics as _stats

    bucket_specific = results.get("bucket_specific_horizons", False)

    lines: List[str] = []
    lines.append("# Bucketed Evaluation Verdict")
    lines.append("")
    lines.append(f"**Top-K**: {results['top_k']}")
    lines.append(f"**Cost**: {results['cost_bps']} bps")
    lines.append(f"**Benchmark**: {results['benchmark']}")
    if bucket_specific:
        lines.append("**Horizon mode**: bucket-specific (aligned to holding period)")
    else:
        lines.append(f"**Horizons**: {results['horizons']}")
    lines.append("")

    if bucket_specific:
        # Per-bucket table with its own horizons
        for bucket_name in ALL_BUCKETS:
            bm = results["buckets"].get(bucket_name, {})
            display = BUCKET_DISPLAY.get(bucket_name, bucket_name)
            bh_horizons = bm.get("horizons", results["horizons"])

            lines.append(f"## {display}")
            lines.append("")
            lines.append(f"Horizons: {bh_horizons}")
            lines.append("")
            lines.append("| Horizon | N | Mean IC | IC t | Net Return | " "Excess | Hedged | Turnover |")
            lines.append("|---------|---|---------|------|------------|" "--------|--------|----------|")
            for h in bh_horizons:
                bh = bm.get("by_horizon", {}).get(h, {})
                lines.append(
                    f"| {h}d "
                    f"| {bh.get('n_dates', 0)} "
                    f"| {_fmt(bh.get('mean_ic'))} "
                    f"| {_fmt(bh.get('ic_t_stat'), 2)} "
                    f"| {_fmt_pct(bh.get('mean_net_return'))} "
                    f"| {_fmt_pct(bh.get('mean_excess_return'))} "
                    f"| {_fmt_pct(bh.get('mean_hedged_return'))} "
                    f"| {_fmt(bh.get('mean_turnover'))} |"
                )
            lines.append("")
    else:
        # Uniform horizons: cross-bucket comparison table per horizon
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

    # Microcap inversion sleeve (if present)
    if "microcap_inversion" in results.get("buckets", {}):
        mc = results["buckets"]["microcap_inversion"]
        mc_horizons = mc.get("horizons", [84, 126])
        lines.append("## Microcap Inversion Sleeve (opt-in)")
        lines.append("")
        lines.append("XS-band bottom-K from core bucket (contrarian). " "Intentionally microcap/illiquidity-exposed.")
        lines.append("")
        lines.append("| Horizon | N | Mean IC | IC t | Net Return | " "Excess | Hedged | Turnover |")
        lines.append("|---------|---|---------|------|------------|" "--------|--------|----------|")
        for h in mc_horizons:
            bh = mc.get("by_horizon", {}).get(h, {})
            lines.append(
                f"| {h}d "
                f"| {bh.get('n_dates', 0)} "
                f"| {_fmt(bh.get('mean_ic'))} "
                f"| {_fmt(bh.get('ic_t_stat'), 2)} "
                f"| {_fmt_pct(bh.get('mean_net_return'))} "
                f"| {_fmt_pct(bh.get('mean_excess_return'))} "
                f"| {_fmt_pct(bh.get('mean_hedged_return'))} "
                f"| {_fmt(bh.get('mean_turnover'))} |"
            )
        lines.append("")

    # Binary vs less-binary aggregate (use primary horizons)
    lines.append("## Binary vs Less-Binary Aggregate")
    lines.append("")
    # Use 84d as common guardrail if bucket-specific, else all horizons
    compare_horizons = [84] if bucket_specific else results["horizons"]
    for h in compare_horizons:
        binary_ics = []
        binary_nets = []
        lb_metrics = results["buckets"].get("less_binary", {}).get("by_horizon", {}).get(h, {})

        for b in BINARY_BUCKETS:
            bh = results["buckets"].get(b, {}).get("by_horizon", {}).get(h, {})
            if bh.get("mean_ic") is not None:
                binary_ics.append(bh["mean_ic"])
            if bh.get("mean_net_return") is not None:
                binary_nets.append(bh["mean_net_return"])

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

    # Family splits: regulatory vs clinical within binary buckets
    if "family_splits" in results and results["family_splits"]:
        lines.append("## Regulatory vs Clinical Sub-Splits")
        lines.append("")
        lines.append("| Bucket | Family | N | Horizon | Mean IC | IC t | " "Hedged | Turnover |")
        lines.append("|--------|--------|---|---------|---------|------|" "--------|----------|")
        for split_key in sorted(results["family_splits"].keys()):
            sm = results["family_splits"][split_key]
            for h in sm.get("horizons", []):
                bh = sm.get("by_horizon", {}).get(h, {})
                lines.append(
                    f"| {sm.get('bucket', '')} "
                    f"| {sm.get('family', '')} "
                    f"| {bh.get('n_dates', 0)} "
                    f"| {h}d "
                    f"| {_fmt(bh.get('mean_ic'))} "
                    f"| {_fmt(bh.get('ic_t_stat'), 2)} "
                    f"| {_fmt_pct(bh.get('mean_hedged_return'))} "
                    f"| {_fmt(bh.get('mean_turnover'))} |"
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
    parser.add_argument(
        "--bucket-specific-horizons",
        action="store_true",
        default=True,
        help=(
            "Use bucket-specific horizons aligned to holding period (default). "
            "binary_0_30=20/63d, binary_31_90=63/84d, "
            "binary_91_180=84/126d, less_binary=84/126d."
        ),
    )
    parser.add_argument(
        "--uniform-horizons",
        action="store_true",
        default=False,
        help="Use uniform horizons (from --horizons) for all buckets instead of bucket-specific.",
    )
    parser.add_argument(
        "--include-microcap-sleeve",
        action="store_true",
        default=False,
        help=(
            "Include microcap inversion sleeve: core/XS bottom-K (contrarian). "
            "Deliberately illiquidity-exposed (research/opt-in)."
        ),
    )
    parser.add_argument(
        "--include-family-splits",
        action="store_true",
        default=False,
        help="Include regulatory vs clinical sub-splits within binary buckets.",
    )
    parser.add_argument(
        "--family-filter-mode",
        type=str,
        default="primary",
        choices=["primary", "secondary"],
        help=(
            "How to assign family membership for splits. "
            "'primary' uses catalyst_family (nearest catalyst). "
            "'secondary' treats any ticker with has_regulatory_upcoming_180d=1 as REGULATORY."
        ),
    )
    args = parser.parse_args()

    horizons = [int(h.strip()) for h in args.horizons.split(",")]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # --uniform-horizons overrides --bucket-specific-horizons
    use_bucket_specific = args.bucket_specific_horizons and not args.uniform_horizons

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
        bucket_specific_horizons=use_bucket_specific,
        include_microcap_sleeve=args.include_microcap_sleeve,
        include_family_splits=args.include_family_splits,
        family_filter_mode=args.family_filter_mode,
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
    all_bucket_names = ALL_BUCKETS + (["microcap_inversion"] if "microcap_inversion" in results["buckets"] else [])
    for b in all_bucket_names:
        bm = results["buckets"].get(b, {})
        if not bm:
            continue
        eff_h = bm.get("horizons", horizons)
        display = BUCKET_DISPLAY.get(b, b)
        print(f"\n  {display} (horizons={eff_h}):")
        for h in eff_h:
            bh = bm.get("by_horizon", {}).get(h, {})
            print(
                f"    {h:>4d}d  "
                f"IC={_fmt(bh.get('mean_ic'))}, "
                f"Net={_fmt_pct(bh.get('mean_net_return'))}, "
                f"Turn={_fmt(bh.get('mean_turnover'))}"
            )


if __name__ == "__main__":
    main()
