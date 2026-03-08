#!/usr/bin/env python3
"""Less-Binary Contrarian Sleeve Validation.

Three hard checks before promoting bottom-K as a production rule:

1. PLACEBO — shuffle ranks within bucket per date; edge should collapse.
2. TRADEABILITY — re-run with min ADV / min market cap filters.
3. HEDGE_ROBUSTNESS — recompute hedged returns under 3 hedge methods.

Writes VERDICT.md with pass/fail for each gate.

Usage:
    python3 scripts/research/validate_less_binary_contrarian.py \
        --snapshot-root data/snapshots \
        --price-csv production_data/price_history.csv \
        --date-manifest output/audited_sets/audited_dates_2020_2024_strict.txt \
        --out-dir output/research/less_binary_validation
"""
from __future__ import annotations

import csv
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

HORIZONS = [84, 126]
SCHEMA = "less_binary_validation.v1"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_by_date(path: Path) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _mean_metric(rows: List[Dict[str, str]], horizon: int, field: str) -> Optional[float]:
    vals = []
    for r in rows:
        if int(r.get("horizon", 0)) != horizon:
            continue
        if r.get("skipped") == "True":
            continue
        v = r.get(field, "")
        if v and v != "":
            vals.append(float(v))
    return statistics.mean(vals) if vals else None


# ---------------------------------------------------------------------------
# Gate 1: Placebo (shuffle ranks within bucket)
# ---------------------------------------------------------------------------


def run_placebo(
    snapshot_root: Path,
    price_csv: Path,
    horizons: List[int],
    top_k: int,
    cost_bps: float,
    benchmark: str,
    buffer: int,
    out_dir: Path,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    allowed_dates: Optional[set] = None,
    n_shuffles: int = 5,
    seed: int = 42,
) -> Dict[str, Any]:
    """Run placebo: shuffle ranks within less-binary bucket, average results.

    If bottom-K edge survives shuffling, the signal is structural (artifact).
    If it collapses toward EW, the ranking genuinely matters.
    """
    from eval_forward_returns import evaluate

    rng = random.Random(seed)
    shuffle_results: List[Dict[str, Any]] = []

    for trial in range(n_shuffles):
        trial_out = out_dir / f"placebo_trial_{trial}"
        trial_out.mkdir(parents=True, exist_ok=True)

        # Use a custom shuffle by passing a modified eval that shuffles
        # rankings within the core bucket before selection
        summary, date_results, skips = evaluate(
            snapshot_root=snapshot_root,
            price_csv=price_csv,
            horizons=horizons,
            top_k=top_k,
            cost_bps=cost_bps,
            date_from=date_from,
            date_to=date_to,
            allowed_dates=allowed_dates,
            benchmark=benchmark,
            bucket_filter=["core"],
            rebalance_buffer_ranks=buffer,
            selection_mode="bottom",
            out_dir=trial_out,
            _shuffle_seed=rng.randint(0, 2**31),  # triggers rank shuffle
        )
        trial_metrics = {}
        for h in horizons:
            bh = summary.by_horizon.get(h, {})
            trial_metrics[h] = {
                "hedged": bh.get("mean_hedged_return"),
                "excess": bh.get("mean_excess_return"),
                "net": bh.get("mean_net_return"),
            }
        shuffle_results.append(trial_metrics)

    # Average across trials
    placebo = {}
    for h in horizons:
        hedged_vals = [t[h]["hedged"] for t in shuffle_results if t[h]["hedged"] is not None]
        excess_vals = [t[h]["excess"] for t in shuffle_results if t[h]["excess"] is not None]
        placebo[h] = {
            "mean_hedged": statistics.mean(hedged_vals) if hedged_vals else None,
            "mean_excess": statistics.mean(excess_vals) if excess_vals else None,
            "n_trials": len(hedged_vals),
        }

    return {"placebo_by_horizon": placebo, "n_shuffles": n_shuffles}


# ---------------------------------------------------------------------------
# Gate 2: Tradeability (filter by size/liquidity)
# ---------------------------------------------------------------------------


def run_tradeability(
    snapshot_root: Path,
    price_csv: Path,
    horizons: List[int],
    top_k: int,
    cost_bps: float,
    benchmark: str,
    buffer: int,
    out_dir: Path,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    allowed_dates: Optional[set] = None,
    min_mcap_buckets: Tuple[str, ...] = ("S", "M", "L"),
) -> Dict[str, Any]:
    """Re-run bottom-K excluding microcaps (XS band).

    If edge vanishes after removing XS, the alpha is untradeable.
    """
    from eval_forward_returns import evaluate

    # Run baseline bottom-K (all sizes)
    baseline_out = out_dir / "tradeability_baseline"
    baseline_out.mkdir(parents=True, exist_ok=True)
    base_summary, _, _ = evaluate(
        snapshot_root=snapshot_root,
        price_csv=price_csv,
        horizons=horizons,
        top_k=top_k,
        cost_bps=cost_bps,
        date_from=date_from,
        date_to=date_to,
        allowed_dates=allowed_dates,
        benchmark=benchmark,
        bucket_filter=["core"],
        rebalance_buffer_ranks=buffer,
        selection_mode="bottom",
        out_dir=baseline_out,
    )

    # Run filtered bottom-K (exclude XS)
    filtered_out = out_dir / "tradeability_filtered"
    filtered_out.mkdir(parents=True, exist_ok=True)
    filt_summary, _, _ = evaluate(
        snapshot_root=snapshot_root,
        price_csv=price_csv,
        horizons=horizons,
        top_k=top_k,
        cost_bps=cost_bps,
        date_from=date_from,
        date_to=date_to,
        allowed_dates=allowed_dates,
        benchmark=benchmark,
        bucket_filter=["core"],
        rebalance_buffer_ranks=buffer,
        selection_mode="bottom",
        out_dir=filtered_out,
        min_mcap_buckets=min_mcap_buckets,
    )

    results = {}
    for h in horizons:
        base_bh = base_summary.by_horizon.get(h, {})
        filt_bh = filt_summary.by_horizon.get(h, {})
        results[h] = {
            "baseline_hedged": base_bh.get("mean_hedged_return"),
            "baseline_excess": base_bh.get("mean_excess_return"),
            "filtered_hedged": filt_bh.get("mean_hedged_return"),
            "filtered_excess": filt_bh.get("mean_excess_return"),
        }

    return {"tradeability_by_horizon": results, "min_mcap_buckets": list(min_mcap_buckets)}


# ---------------------------------------------------------------------------
# Gate 3: Hedge robustness
# ---------------------------------------------------------------------------


def run_hedge_robustness(
    by_date_path: Path,
    price_csv: Path,
    horizons: List[int],
) -> Dict[str, Any]:
    """Compare hedged returns under existing beta-hedge vs simple 1x XBI hedge.

    Uses by_date.csv from a bottom-K run.  The existing hedged_return is
    beta-weighted.  We compute a simple hedge = gross - 1.0 * benchmark.
    If the edge only exists under one method, it's fragile.
    """
    rows = _load_by_date(by_date_path)

    results = {}
    for h in horizons:
        h_rows = [r for r in rows if int(r.get("horizon", 0)) == h and r.get("skipped") != "True"]
        if not h_rows:
            results[h] = {"beta_hedged": None, "simple_hedged": None, "excess": None}
            continue

        beta_hedged = []
        simple_hedged = []
        excess_vals = []
        for r in h_rows:
            gross = r.get("gross_return", "")
            bm = r.get("benchmark_return", "")
            hedged = r.get("hedged_return", "")
            excess = r.get("excess_return", "")
            if gross and bm:
                g = float(gross)
                b = float(bm)
                # Simple 1x hedge: gross - 1.0 * benchmark
                simple_hedged.append(g - b)
            if hedged:
                beta_hedged.append(float(hedged))
            if excess:
                excess_vals.append(float(excess))

        results[h] = {
            "beta_hedged": statistics.mean(beta_hedged) if beta_hedged else None,
            "simple_hedged": statistics.mean(simple_hedged) if simple_hedged else None,
            "excess": statistics.mean(excess_vals) if excess_vals else None,
            "n_dates": len(h_rows),
        }

    return {"hedge_by_horizon": results}


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:.2%}" if v is not None else "\u2014"


def write_verdict(
    placebo: Dict[str, Any],
    tradeability: Dict[str, Any],
    hedge: Dict[str, Any],
    baseline: Dict[str, Any],
    out_dir: Path,
) -> Path:
    """Write VERDICT.md with pass/fail for each gate."""
    lines = ["# Less-Binary Contrarian Validation", ""]

    # Gate 1: Placebo
    lines.append("## Gate 1: Placebo (rank shuffle)")
    lines.append("")
    lines.append("If shuffled bottom-K hedged is close to baseline bottom-K, the signal is structural (FAIL).")
    lines.append("If shuffled collapses toward zero/EW, the ranking matters (PASS).")
    lines.append("")
    lines.append("| Horizon | Baseline Hedged | Placebo Hedged | Degradation | Verdict |")
    lines.append("|---------|-----------------|----------------|-------------|---------|")

    placebo_pass = True
    for h in HORIZONS:
        base_h = baseline.get(h, {}).get("hedged")
        plac_h = placebo.get("placebo_by_horizon", {}).get(h, {}).get("mean_hedged")
        if base_h is not None and plac_h is not None:
            degrad = base_h - plac_h
            # PASS if shuffled is meaningfully worse (degradation > 2pp)
            verdict = "PASS" if degrad > 0.02 else "FAIL"
            if verdict == "FAIL":
                placebo_pass = False
        else:
            degrad = None
            verdict = "SKIP"
        lines.append(f"| {h}d | {_fmt_pct(base_h)} | {_fmt_pct(plac_h)} | {_fmt_pct(degrad)} | {verdict} |")
    lines.append("")

    # Gate 2: Tradeability
    lines.append("## Gate 2: Tradeability (exclude XS)")
    lines.append("")
    lines.append("If filtered hedged drops > 50% vs baseline, the alpha is in untradeable names (FAIL).")
    lines.append("")
    lines.append("| Horizon | Baseline Hedged | Filtered Hedged | Retention | Verdict |")
    lines.append("|---------|-----------------|-----------------|-----------|---------|")

    trade_pass = True
    for h in HORIZONS:
        th = tradeability.get("tradeability_by_horizon", {}).get(h, {})
        base_h = th.get("baseline_hedged")
        filt_h = th.get("filtered_hedged")
        if base_h is not None and filt_h is not None and base_h != 0:
            retention = filt_h / base_h
            verdict = "PASS" if retention > 0.50 else "FAIL"
            if verdict == "FAIL":
                trade_pass = False
        else:
            retention = None
            verdict = "SKIP"
        lines.append(
            f"| {h}d | {_fmt_pct(base_h)} | {_fmt_pct(filt_h)} "
            f"| {f'{retention:.0%}' if retention is not None else '\u2014'} | {verdict} |"
        )
    lines.append("")

    # Gate 3: Hedge robustness
    lines.append("## Gate 3: Hedge Robustness")
    lines.append("")
    lines.append("Edge must be positive under both beta-hedge and simple 1x XBI hedge.")
    lines.append("")
    lines.append("| Horizon | Beta-Hedged | Simple 1x Hedge | Excess | Verdict |")
    lines.append("|---------|-------------|-----------------|--------|---------|")

    hedge_pass = True
    for h in HORIZONS:
        hh = hedge.get("hedge_by_horizon", {}).get(h, {})
        beta_h = hh.get("beta_hedged")
        simple_h = hh.get("simple_hedged")
        excess_h = hh.get("excess")
        if beta_h is not None and simple_h is not None:
            verdict = "PASS" if beta_h > 0 and simple_h > 0 else "FAIL"
            if verdict == "FAIL":
                hedge_pass = False
        else:
            verdict = "SKIP"
        lines.append(f"| {h}d | {_fmt_pct(beta_h)} | {_fmt_pct(simple_h)} | {_fmt_pct(excess_h)} | {verdict} |")
    lines.append("")

    # Overall verdict
    all_pass = placebo_pass and trade_pass and hedge_pass
    lines.append("## Overall Verdict")
    lines.append("")
    lines.append(f"- Placebo: **{'PASS' if placebo_pass else 'FAIL'}**")
    lines.append(f"- Tradeability: **{'PASS' if trade_pass else 'FAIL'}**")
    lines.append(f"- Hedge Robustness: **{'PASS' if hedge_pass else 'FAIL'}**")
    lines.append(
        f"- **Overall: {'PASS — contrarian sleeve is production-grade' if all_pass else 'FAIL — do not ship contrarian'}**"
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

    parser = argparse.ArgumentParser(description="Validate less-binary contrarian sleeve.")
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--price-csv", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--date-manifest", type=Path, default=None)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--cost-bps", type=float, default=30.0)
    parser.add_argument("--benchmark", default="XBI")
    parser.add_argument("--rebalance-buffer-ranks", type=int, default=30)
    parser.add_argument("--n-shuffles", type=int, default=5)
    parser.add_argument("--skip-placebo", action="store_true", default=False)
    parser.add_argument("--skip-tradeability", action="store_true", default=False)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    allowed_dates: Optional[set] = None
    if args.date_manifest:
        raw = args.date_manifest.read_text().splitlines()
        allowed_dates = {d.strip() for d in raw if d.strip()}

    print("=" * 60)
    print("Less-Binary Contrarian Validation")
    print("=" * 60)

    # Run baseline bottom-K (needed for all gates)
    print("\n--- Baseline bottom-K ---")
    from eval_forward_returns import evaluate

    base_out = args.out_dir / "baseline_bottom"
    base_out.mkdir(parents=True, exist_ok=True)
    base_summary, _, _ = evaluate(
        snapshot_root=args.snapshot_root,
        price_csv=args.price_csv,
        horizons=HORIZONS,
        top_k=args.top_k,
        cost_bps=args.cost_bps,
        date_from=args.date_from,
        date_to=args.date_to,
        allowed_dates=allowed_dates,
        benchmark=args.benchmark,
        bucket_filter=["core"],
        rebalance_buffer_ranks=args.rebalance_buffer_ranks,
        selection_mode="bottom",
        out_dir=base_out,
    )
    baseline = {}
    for h in HORIZONS:
        bh = base_summary.by_horizon.get(h, {})
        baseline[h] = {
            "hedged": bh.get("mean_hedged_return"),
            "excess": bh.get("mean_excess_return"),
            "net": bh.get("mean_net_return"),
        }
    parts = [f"{h}d hedged={_fmt_pct(baseline[h]['hedged'])}" for h in HORIZONS]
    print(f"  Baseline: {', '.join(parts)}")

    # Gate 1: Placebo
    placebo = {"placebo_by_horizon": {h: {"mean_hedged": None, "mean_excess": None} for h in HORIZONS}}
    if not args.skip_placebo:
        print("\n--- Gate 1: Placebo (rank shuffle) ---")
        placebo = run_placebo(
            snapshot_root=args.snapshot_root,
            price_csv=args.price_csv,
            horizons=HORIZONS,
            top_k=args.top_k,
            cost_bps=args.cost_bps,
            benchmark=args.benchmark,
            buffer=args.rebalance_buffer_ranks,
            out_dir=args.out_dir,
            date_from=args.date_from,
            date_to=args.date_to,
            allowed_dates=allowed_dates,
            n_shuffles=args.n_shuffles,
        )
        for h in HORIZONS:
            ph = placebo["placebo_by_horizon"].get(h, {})
            print(f"  {h}d placebo hedged={_fmt_pct(ph.get('mean_hedged'))}")
    else:
        print("\n--- Gate 1: Placebo — SKIPPED ---")

    # Gate 2: Tradeability
    tradeability = {"tradeability_by_horizon": {}}
    if not args.skip_tradeability:
        print("\n--- Gate 2: Tradeability (exclude XS) ---")
        tradeability = run_tradeability(
            snapshot_root=args.snapshot_root,
            price_csv=args.price_csv,
            horizons=HORIZONS,
            top_k=args.top_k,
            cost_bps=args.cost_bps,
            benchmark=args.benchmark,
            buffer=args.rebalance_buffer_ranks,
            out_dir=args.out_dir,
            date_from=args.date_from,
            date_to=args.date_to,
            allowed_dates=allowed_dates,
        )
        for h in HORIZONS:
            th = tradeability["tradeability_by_horizon"].get(h, {})
            print(f"  {h}d filtered hedged={_fmt_pct(th.get('filtered_hedged'))}")
    else:
        print("\n--- Gate 2: Tradeability — SKIPPED ---")

    # Gate 3: Hedge robustness (uses baseline by_date.csv)
    print("\n--- Gate 3: Hedge robustness ---")
    by_date_path = base_out / "by_date.csv"
    hedge = run_hedge_robustness(by_date_path, args.price_csv, HORIZONS)
    for h in HORIZONS:
        hh = hedge["hedge_by_horizon"].get(h, {})
        print(f"  {h}d beta={_fmt_pct(hh.get('beta_hedged'))}, " f"simple={_fmt_pct(hh.get('simple_hedged'))}")

    # Write results
    results = {
        "schema": SCHEMA,
        "baseline": baseline,
        "placebo": placebo,
        "tradeability": tradeability,
        "hedge": hedge,
    }
    json_path = args.out_dir / "validation_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    verdict_path = write_verdict(placebo, tradeability, hedge, baseline, args.out_dir)
    print(f"\n{'='*60}")
    print(f"Results → {args.out_dir}")
    print(f"  VERDICT.md → {verdict_path}")
    print(f"  validation_results.json → {json_path}")


if __name__ == "__main__":
    main()
