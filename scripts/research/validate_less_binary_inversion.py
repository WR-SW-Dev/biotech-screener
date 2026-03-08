#!/usr/bin/env python3
"""Less-Binary Inversion Robustness Battery.

Before treating the less-binary "bottom beats top" result as real, run:

1. PLACEBO — shuffle ranks within bucket per date.  If bottom-K edge
   survives randomisation, it's a measurement artifact.

2. K SWEEP — repeat with K ∈ {10, 20, 30, 50}.  If only one K shows
   the effect, it's fragile.

3. EXECUTION LAG — trade 5 trading days after snapshot.  If inversion
   collapses, it's microstructure/announcement timing.

4. INDUSTRY-NEUTRAL IC — raw vs industry-neutral IC side-by-side.
   If raw IC is very negative but neutral IC ≈ 0, the signal is sector
   composition, not stock selection.

5. LIQUIDITY FILTER (optional) — exclude XS band.  If inversion vanishes,
   the alpha is in untradeable microcaps.

Outputs:
    VALIDATION.md   — human-readable report
    VALIDATION.json — machine-readable results

Usage:
    python3 scripts/research/validate_less_binary_inversion.py \
        --snapshot-root data/snapshots \
        --price-csv production_data/price_history.csv \
        --date-manifest output/audited_sets/audited_dates_2020_2024_strict.txt \
        --out-dir output/research/less_binary_validation
"""
from __future__ import annotations

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
SCHEMA = "less_binary_inversion_validation.v1"

# Core bucket = "less-binary" names (no dated catalyst)
CORE_BUCKET_FILTER = ["core"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:.2%}" if v is not None else "\u2014"


def _fmt_f(v: Optional[float], dp: int = 4) -> str:
    return f"{v:.{dp}f}" if v is not None else "\u2014"


def _extract_horizon_metrics(summary, horizons: List[int]) -> Dict[int, Dict[str, Any]]:
    """Pull key metrics per horizon from EvalSummary."""
    out = {}
    for h in horizons:
        bh = summary.by_horizon.get(h, {})
        out[h] = {
            "mean_ic": bh.get("mean_ic"),
            "ic_t_stat": bh.get("ic_t_stat"),
            "mean_net": bh.get("mean_net_return"),
            "mean_excess": bh.get("mean_excess_return"),
            "mean_hedged": bh.get("mean_hedged_return"),
            "mean_turnover": bh.get("mean_turnover"),
            "industry_neutral_ic": bh.get("mean_industry_neutral_ic"),
            "industry_neutral_ic_t": bh.get("industry_neutral_ic_t_stat"),
            "n_evaluated": bh.get("n"),
        }
    return out


# ---------------------------------------------------------------------------
# Gate 1: Rank Randomisation Placebo
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
    """Shuffle ranks within less-binary bucket per date, run bottom-K.

    Returns placebo metrics (averaged across trials) for comparison with
    the unshuffled baseline.  If shuffled ≈ baseline, signal is structural.
    """
    from eval_forward_returns import evaluate

    rng = random.Random(seed)
    trial_results: List[Dict[int, Dict[str, Any]]] = []

    for trial in range(n_shuffles):
        trial_out = out_dir / f"placebo_trial_{trial}"
        trial_out.mkdir(parents=True, exist_ok=True)

        summary, _, _ = evaluate(
            snapshot_root=snapshot_root,
            price_csv=price_csv,
            horizons=horizons,
            top_k=top_k,
            cost_bps=cost_bps,
            date_from=date_from,
            date_to=date_to,
            allowed_dates=allowed_dates,
            benchmark=benchmark,
            bucket_filter=CORE_BUCKET_FILTER,
            rebalance_buffer_ranks=buffer,
            selection_mode="bottom",
            out_dir=trial_out,
            _shuffle_seed=rng.randint(0, 2**31),
        )
        trial_results.append(_extract_horizon_metrics(summary, horizons))

    # Average across trials
    placebo: Dict[int, Dict[str, Any]] = {}
    for h in horizons:
        hedged_vals = [t[h]["mean_hedged"] for t in trial_results if t[h]["mean_hedged"] is not None]
        excess_vals = [t[h]["mean_excess"] for t in trial_results if t[h]["mean_excess"] is not None]
        ic_vals = [t[h]["mean_ic"] for t in trial_results if t[h]["mean_ic"] is not None]
        net_vals = [t[h]["mean_net"] for t in trial_results if t[h]["mean_net"] is not None]
        placebo[h] = {
            "mean_hedged": statistics.mean(hedged_vals) if hedged_vals else None,
            "mean_excess": statistics.mean(excess_vals) if excess_vals else None,
            "mean_ic": statistics.mean(ic_vals) if ic_vals else None,
            "mean_net": statistics.mean(net_vals) if net_vals else None,
            "n_trials": len(hedged_vals),
        }

    return {"placebo_by_horizon": placebo, "n_shuffles": n_shuffles, "seed": seed}


# ---------------------------------------------------------------------------
# Gate 2: K Sensitivity Sweep
# ---------------------------------------------------------------------------


def run_k_sweep(
    snapshot_root: Path,
    price_csv: Path,
    horizons: List[int],
    k_values: List[int],
    cost_bps: float,
    benchmark: str,
    buffer: int,
    out_dir: Path,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    allowed_dates: Optional[set] = None,
) -> Dict[str, Any]:
    """Run bottom-K and top-K for each K, report metrics."""
    from eval_forward_returns import evaluate

    results: Dict[int, Dict[str, Any]] = {}

    for k in k_values:
        k_dir = out_dir / f"k_{k}"
        k_dir.mkdir(parents=True, exist_ok=True)

        # Bottom-K
        bot_out = k_dir / "bottom"
        bot_out.mkdir(parents=True, exist_ok=True)
        bot_summary, _, _ = evaluate(
            snapshot_root=snapshot_root,
            price_csv=price_csv,
            horizons=horizons,
            top_k=k,
            cost_bps=cost_bps,
            date_from=date_from,
            date_to=date_to,
            allowed_dates=allowed_dates,
            benchmark=benchmark,
            bucket_filter=CORE_BUCKET_FILTER,
            rebalance_buffer_ranks=buffer,
            selection_mode="bottom",
            out_dir=bot_out,
        )

        # Top-K
        top_out = k_dir / "top"
        top_out.mkdir(parents=True, exist_ok=True)
        top_summary, _, _ = evaluate(
            snapshot_root=snapshot_root,
            price_csv=price_csv,
            horizons=horizons,
            top_k=k,
            cost_bps=cost_bps,
            date_from=date_from,
            date_to=date_to,
            allowed_dates=allowed_dates,
            benchmark=benchmark,
            bucket_filter=CORE_BUCKET_FILTER,
            rebalance_buffer_ranks=buffer,
            selection_mode="top",
            out_dir=top_out,
        )

        results[k] = {
            "bottom": _extract_horizon_metrics(bot_summary, horizons),
            "top": _extract_horizon_metrics(top_summary, horizons),
        }

    return {"k_sweep": results, "k_values": k_values}


# ---------------------------------------------------------------------------
# Gate 3: Execution Lag
# ---------------------------------------------------------------------------


def run_execution_lag(
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
    lag_days: int = 5,
) -> Dict[str, Any]:
    """Re-run bottom-K with trade date shifted by lag_days trading days.

    If the inversion collapses under lag, it's announcement timing, not stable alpha.
    """
    from eval_forward_returns import evaluate

    # Lagged bottom-K
    lag_out = out_dir / f"lag_{lag_days}d_bottom"
    lag_out.mkdir(parents=True, exist_ok=True)
    lag_summary, _, _ = evaluate(
        snapshot_root=snapshot_root,
        price_csv=price_csv,
        horizons=horizons,
        top_k=top_k,
        cost_bps=cost_bps,
        date_from=date_from,
        date_to=date_to,
        allowed_dates=allowed_dates,
        benchmark=benchmark,
        bucket_filter=CORE_BUCKET_FILTER,
        rebalance_buffer_ranks=buffer,
        selection_mode="bottom",
        out_dir=lag_out,
        trade_lag_days=lag_days,
    )

    # Lagged top-K (for comparison)
    lag_top_out = out_dir / f"lag_{lag_days}d_top"
    lag_top_out.mkdir(parents=True, exist_ok=True)
    lag_top_summary, _, _ = evaluate(
        snapshot_root=snapshot_root,
        price_csv=price_csv,
        horizons=horizons,
        top_k=top_k,
        cost_bps=cost_bps,
        date_from=date_from,
        date_to=date_to,
        allowed_dates=allowed_dates,
        benchmark=benchmark,
        bucket_filter=CORE_BUCKET_FILTER,
        rebalance_buffer_ranks=buffer,
        selection_mode="top",
        out_dir=lag_top_out,
        trade_lag_days=lag_days,
    )

    return {
        "lag_days": lag_days,
        "lagged_bottom": _extract_horizon_metrics(lag_summary, horizons),
        "lagged_top": _extract_horizon_metrics(lag_top_summary, horizons),
    }


# ---------------------------------------------------------------------------
# Gate 4: Industry-Neutral IC
# ---------------------------------------------------------------------------


def run_industry_neutral(
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
) -> Dict[str, Any]:
    """Run bottom-K with industry_neutral=True to compare raw vs neutral IC."""
    from eval_forward_returns import evaluate

    neutral_out = out_dir / "industry_neutral"
    neutral_out.mkdir(parents=True, exist_ok=True)
    summary, _, _ = evaluate(
        snapshot_root=snapshot_root,
        price_csv=price_csv,
        horizons=horizons,
        top_k=top_k,
        cost_bps=cost_bps,
        date_from=date_from,
        date_to=date_to,
        allowed_dates=allowed_dates,
        benchmark=benchmark,
        bucket_filter=CORE_BUCKET_FILTER,
        rebalance_buffer_ranks=buffer,
        selection_mode="bottom",
        out_dir=neutral_out,
        industry_neutral=True,
    )

    return {"industry_neutral": _extract_horizon_metrics(summary, horizons)}


# ---------------------------------------------------------------------------
# Gate 5: Liquidity Filter
# ---------------------------------------------------------------------------


def run_liquidity_filter(
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
    """Bottom-K excluding XS band (microcaps)."""
    from eval_forward_returns import evaluate

    filt_out = out_dir / "liquidity_filtered"
    filt_out.mkdir(parents=True, exist_ok=True)
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
        bucket_filter=CORE_BUCKET_FILTER,
        rebalance_buffer_ranks=buffer,
        selection_mode="bottom",
        out_dir=filt_out,
        min_mcap_buckets=min_mcap_buckets,
    )

    return {"liquidity_filtered": _extract_horizon_metrics(filt_summary, horizons)}


# ---------------------------------------------------------------------------
# Verdict Writer
# ---------------------------------------------------------------------------


def write_validation(
    baseline: Dict[int, Dict[str, Any]],
    placebo: Dict[str, Any],
    k_sweep: Dict[str, Any],
    lag: Dict[str, Any],
    neutral: Dict[str, Any],
    liquidity: Dict[str, Any],
    out_dir: Path,
) -> Path:
    """Write VALIDATION.md with per-gate diagnostics and verdicts."""
    lines = ["# Less-Binary Inversion Robustness Battery", ""]

    # ---- Baseline ----
    lines.append("## Baseline (bottom-K, unshuffled, K=20, lag=0)")
    lines.append("")
    lines.append("| Horizon | Net | Excess | Hedged | IC | IC t | Turnover |")
    lines.append("|---------|-----|--------|--------|----|------|----------|")
    for h in HORIZONS:
        m = baseline.get(h, {})
        lines.append(
            f"| {h}d | {_fmt_pct(m.get('mean_net'))} | {_fmt_pct(m.get('mean_excess'))} "
            f"| {_fmt_pct(m.get('mean_hedged'))} | {_fmt_f(m.get('mean_ic'))} "
            f"| {_fmt_f(m.get('ic_t_stat'), 2)} | {_fmt_f(m.get('mean_turnover'))} |"
        )
    lines.append("")

    # ---- Gate 1: Placebo ----
    lines.append("## Gate 1: Rank Randomisation Placebo")
    lines.append("")
    lines.append("Shuffled ranks within bucket → bottom-K re-run.")
    lines.append("**PASS** if shuffled hedged collapses vs baseline (degradation > 2pp).")
    lines.append("**FAIL** if shuffled ≈ baseline (signal is structural/artifact).")
    lines.append("")
    lines.append("| Horizon | Baseline Hedged | Placebo Hedged | Degradation | Verdict |")
    lines.append("|---------|-----------------|----------------|-------------|---------|")

    placebo_pass = True
    for h in HORIZONS:
        base_h = baseline.get(h, {}).get("mean_hedged")
        plac_h = placebo.get("placebo_by_horizon", {}).get(h, {}).get("mean_hedged")
        if base_h is not None and plac_h is not None:
            degrad = base_h - plac_h
            verdict = "PASS" if degrad > 0.02 else "FAIL"
            if verdict == "FAIL":
                placebo_pass = False
        else:
            degrad = None
            verdict = "SKIP"
        lines.append(f"| {h}d | {_fmt_pct(base_h)} | {_fmt_pct(plac_h)} " f"| {_fmt_pct(degrad)} | {verdict} |")
    lines.append("")

    # ---- Gate 2: K Sweep ----
    lines.append("## Gate 2: K Sensitivity Sweep")
    lines.append("")
    lines.append("Bottom-K must beat top-K at ≥ 3 of 4 K values to be robust.")
    lines.append("")
    lines.append("| K | Horizon | Bot Hedged | Top Hedged | Bot-Top | Bot IC | Top IC |")
    lines.append("|---|---------|------------|------------|---------|--------|--------|")

    k_results = k_sweep.get("k_sweep", {})
    k_pass_count = 0
    k_total = 0
    for k in sorted(k_results.keys()):
        for h in HORIZONS:
            bot_m = k_results[k]["bottom"].get(h, {})
            top_m = k_results[k]["top"].get(h, {})
            bot_h = bot_m.get("mean_hedged")
            top_h = top_m.get("mean_hedged")
            diff = (bot_h - top_h) if (bot_h is not None and top_h is not None) else None
            if diff is not None:
                k_total += 1
                if diff > 0:
                    k_pass_count += 1
            lines.append(
                f"| {k} | {h}d | {_fmt_pct(bot_h)} | {_fmt_pct(top_h)} "
                f"| {_fmt_pct(diff)} | {_fmt_f(bot_m.get('mean_ic'))} "
                f"| {_fmt_f(top_m.get('mean_ic'))} |"
            )

    k_sweep_pass = k_pass_count >= max(1, k_total * 3 // 4) if k_total > 0 else False
    lines.append("")
    lines.append(
        f"Bottom beats top in {k_pass_count}/{k_total} cells. "
        f"**{'PASS' if k_sweep_pass else 'FAIL'}** (threshold: 75%)"
    )
    lines.append("")

    # ---- Gate 3: Execution Lag ----
    lines.append("## Gate 3: Execution Lag")
    lines.append("")
    lag_days = lag.get("lag_days", 5)
    lines.append(
        f"Trade {lag_days} trading days after snapshot. " "If inversion collapses → microstructure/timing artifact."
    )
    lines.append("")
    lines.append(
        "| Horizon | Lagged Bot Hedged | Lagged Top Hedged | Bot-Top | " "Baseline Bot-Top | Retention | Verdict |"
    )
    lines.append(
        "|---------|-------------------|-------------------|---------|" "-----------------|-----------|---------|"
    )

    lag_pass = True
    for h in HORIZONS:
        lag_bot_h = lag.get("lagged_bottom", {}).get(h, {}).get("mean_hedged")
        lag_top_h = lag.get("lagged_top", {}).get(h, {}).get("mean_hedged")
        base_bot_h = baseline.get(h, {}).get("mean_hedged")
        # For baseline top, we don't have it here — use lag comparison only
        lag_diff = (lag_bot_h - lag_top_h) if (lag_bot_h is not None and lag_top_h is not None) else None
        # Baseline diff: bottom hedged - assume top is much lower (from K sweep K=20 if available)
        base_top_h = k_results.get(20, {}).get("top", {}).get(h, {}).get("mean_hedged") if k_results else None
        base_diff = (base_bot_h - base_top_h) if (base_bot_h is not None and base_top_h is not None) else None

        if lag_diff is not None and base_diff is not None and base_diff != 0:
            retention = lag_diff / base_diff
            # PASS if lagged inversion retains > 50% of baseline inversion
            verdict = "PASS" if retention > 0.50 else "FAIL"
            if verdict == "FAIL":
                lag_pass = False
        else:
            retention = None
            verdict = "SKIP" if lag_diff is None else "PASS"  # if no baseline to compare, pass if diff > 0
            if lag_diff is not None and lag_diff <= 0:
                verdict = "FAIL"
                lag_pass = False
        lines.append(
            f"| {h}d | {_fmt_pct(lag_bot_h)} | {_fmt_pct(lag_top_h)} "
            f"| {_fmt_pct(lag_diff)} | {_fmt_pct(base_diff)} "
            f"| {f'{retention:.0%}' if retention is not None else chr(8212)} | {verdict} |"
        )
    lines.append("")

    # ---- Gate 4: Industry-Neutral IC ----
    lines.append("## Gate 4: Industry-Neutral IC Comparison")
    lines.append("")
    lines.append("If raw IC is very negative but neutral IC ≈ 0 → sector composition leakage.")
    lines.append("")
    lines.append("| Horizon | Raw IC | Raw IC t | Industry-Neutral IC | IN-IC t | Verdict |")
    lines.append("|---------|--------|----------|---------------------|---------|---------|")

    neutral_pass = True
    for h in HORIZONS:
        nm = neutral.get("industry_neutral", {}).get(h, {})
        raw_ic = nm.get("mean_ic")
        raw_ic_t = nm.get("ic_t_stat")
        in_ic = nm.get("industry_neutral_ic")
        in_ic_t = nm.get("industry_neutral_ic_t")
        # FAIL if raw IC is significant (|t|>2) but neutral IC is not (|t|<1.5)
        if raw_ic_t is not None and in_ic_t is not None:
            raw_sig = abs(raw_ic_t) > 2.0
            neutral_sig = abs(in_ic_t) > 1.5
            if raw_sig and not neutral_sig:
                verdict = "FAIL"
                neutral_pass = False
            else:
                verdict = "PASS"
        else:
            verdict = "SKIP"
        lines.append(
            f"| {h}d | {_fmt_f(raw_ic)} | {_fmt_f(raw_ic_t, 2)} "
            f"| {_fmt_f(in_ic)} | {_fmt_f(in_ic_t, 2)} | {verdict} |"
        )
    lines.append("")

    # ---- Gate 5: Liquidity Filter ----
    lines.append("## Gate 5: Liquidity Filter (exclude XS)")
    lines.append("")
    lines.append("| Horizon | Baseline Hedged | Filtered Hedged | Retention | Verdict |")
    lines.append("|---------|-----------------|-----------------|-----------|---------|")

    liq_pass = True
    for h in HORIZONS:
        lm = liquidity.get("liquidity_filtered", {}).get(h, {})
        base_h = baseline.get(h, {}).get("mean_hedged")
        filt_h = lm.get("mean_hedged")
        if base_h is not None and filt_h is not None and base_h != 0:
            retention = filt_h / base_h
            verdict = "PASS" if retention > 0.50 else "FAIL"
            if verdict == "FAIL":
                liq_pass = False
        else:
            retention = None
            verdict = "SKIP"
        lines.append(
            f"| {h}d | {_fmt_pct(base_h)} | {_fmt_pct(filt_h)} "
            f"| {f'{retention:.0%}' if retention is not None else chr(8212)} | {verdict} |"
        )
    lines.append("")

    # ---- Overall ----
    gates = {
        "placebo": placebo_pass,
        "k_sweep": k_sweep_pass,
        "execution_lag": lag_pass,
        "industry_neutral": neutral_pass,
        "liquidity_filter": liq_pass,
    }
    n_pass = sum(1 for v in gates.values() if v)
    all_pass = all(gates.values())

    lines.append("## Overall Verdict")
    lines.append("")
    for gate_name, passed in gates.items():
        lines.append(f"- {gate_name}: **{'PASS' if passed else 'FAIL'}**")
    lines.append("")
    if all_pass:
        lines.append(f"**{n_pass}/{len(gates)} gates passed. Inversion is robust — proceed to shadow portfolio.**")
    else:
        failed = [g for g, v in gates.items() if not v]
        lines.append(f"**{n_pass}/{len(gates)} gates passed. Failed: {', '.join(failed)}.**")
        lines.append("**Do NOT ship contrarian sleeve. Investigate failed gates.**")
    lines.append("")

    path = out_dir / "VALIDATION.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_validation_json(
    baseline: Dict[int, Dict[str, Any]],
    placebo: Dict[str, Any],
    k_sweep: Dict[str, Any],
    lag: Dict[str, Any],
    neutral: Dict[str, Any],
    liquidity: Dict[str, Any],
    out_dir: Path,
) -> Path:
    """Write VALIDATION.json with all results."""
    data = {
        "schema": SCHEMA,
        "baseline": {str(k): v for k, v in baseline.items()},
        "placebo": placebo,
        "k_sweep": {
            "k_values": k_sweep.get("k_values", []),
            "results": {
                str(k): {mode: {str(h): metrics for h, metrics in horizons.items()} for mode, horizons in modes.items()}
                for k, modes in k_sweep.get("k_sweep", {}).items()
            },
        },
        "execution_lag": lag,
        "industry_neutral": neutral,
        "liquidity_filter": liquidity,
    }
    path = out_dir / "VALIDATION.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Less-binary inversion robustness battery.")
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
    parser.add_argument("--lag-days", type=int, default=5)
    parser.add_argument(
        "--k-values",
        default="10,20,30,50",
        help="Comma-separated K values for sweep (default: 10,20,30,50).",
    )
    parser.add_argument("--skip-placebo", action="store_true")
    parser.add_argument("--skip-k-sweep", action="store_true")
    parser.add_argument("--skip-lag", action="store_true")
    parser.add_argument("--skip-neutral", action="store_true")
    parser.add_argument("--skip-liquidity", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    allowed_dates: Optional[set] = None
    if args.date_manifest:
        raw = args.date_manifest.read_text().splitlines()
        allowed_dates = {d.strip() for d in raw if d.strip()}

    k_values = [int(x.strip()) for x in args.k_values.split(",")]

    common = dict(
        snapshot_root=args.snapshot_root,
        price_csv=args.price_csv,
        horizons=HORIZONS,
        cost_bps=args.cost_bps,
        benchmark=args.benchmark,
        buffer=args.rebalance_buffer_ranks,
        date_from=args.date_from,
        date_to=args.date_to,
        allowed_dates=allowed_dates,
    )

    print("=" * 60)
    print("Less-Binary Inversion Robustness Battery")
    print("=" * 60)

    # ---- Baseline ----
    print("\n--- Baseline (bottom-K, K=20, lag=0) ---")
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
        bucket_filter=CORE_BUCKET_FILTER,
        rebalance_buffer_ranks=args.rebalance_buffer_ranks,
        selection_mode="bottom",
        out_dir=base_out,
    )
    baseline = _extract_horizon_metrics(base_summary, HORIZONS)
    for h in HORIZONS:
        m = baseline[h]
        print(f"  {h}d hedged={_fmt_pct(m['mean_hedged'])}, IC={_fmt_f(m['mean_ic'])}")

    # ---- Gate 1: Placebo ----
    if not args.skip_placebo:
        print(f"\n--- Gate 1: Placebo ({args.n_shuffles} shuffles) ---")
        placebo = run_placebo(**common, top_k=args.top_k, out_dir=args.out_dir, n_shuffles=args.n_shuffles)
        for h in HORIZONS:
            ph = placebo["placebo_by_horizon"].get(h, {})
            print(f"  {h}d placebo hedged={_fmt_pct(ph.get('mean_hedged'))}")
    else:
        print("\n--- Gate 1: Placebo — SKIPPED ---")
        placebo = {"placebo_by_horizon": {h: {} for h in HORIZONS}, "n_shuffles": 0}

    # ---- Gate 2: K Sweep ----
    if not args.skip_k_sweep:
        print(f"\n--- Gate 2: K Sweep ({k_values}) ---")
        k_sweep = run_k_sweep(**common, k_values=k_values, out_dir=args.out_dir)
        for k in k_values:
            for h in HORIZONS:
                bm = k_sweep["k_sweep"][k]["bottom"].get(h, {})
                tm = k_sweep["k_sweep"][k]["top"].get(h, {})
                print(f"  K={k} {h}d bot={_fmt_pct(bm.get('mean_hedged'))} " f"top={_fmt_pct(tm.get('mean_hedged'))}")
    else:
        print("\n--- Gate 2: K Sweep — SKIPPED ---")
        k_sweep = {"k_sweep": {}, "k_values": []}

    # ---- Gate 3: Execution Lag ----
    if not args.skip_lag:
        print(f"\n--- Gate 3: Execution Lag ({args.lag_days}d) ---")
        lag = run_execution_lag(**common, top_k=args.top_k, out_dir=args.out_dir, lag_days=args.lag_days)
        for h in HORIZONS:
            lm = lag["lagged_bottom"].get(h, {})
            print(f"  {h}d lagged bot hedged={_fmt_pct(lm.get('mean_hedged'))}")
    else:
        print("\n--- Gate 3: Execution Lag — SKIPPED ---")
        lag = {"lag_days": args.lag_days, "lagged_bottom": {}, "lagged_top": {}}

    # ---- Gate 4: Industry-Neutral ----
    if not args.skip_neutral:
        print("\n--- Gate 4: Industry-Neutral IC ---")
        neutral = run_industry_neutral(**common, top_k=args.top_k, out_dir=args.out_dir)
        for h in HORIZONS:
            nm = neutral["industry_neutral"].get(h, {})
            print(f"  {h}d raw IC={_fmt_f(nm.get('mean_ic'))} " f"neutral IC={_fmt_f(nm.get('industry_neutral_ic'))}")
    else:
        print("\n--- Gate 4: Industry-Neutral IC — SKIPPED ---")
        neutral = {"industry_neutral": {}}

    # ---- Gate 5: Liquidity ----
    if not args.skip_liquidity:
        print("\n--- Gate 5: Liquidity Filter (exclude XS) ---")
        liquidity = run_liquidity_filter(**common, top_k=args.top_k, out_dir=args.out_dir)
        for h in HORIZONS:
            lm = liquidity["liquidity_filtered"].get(h, {})
            print(f"  {h}d filtered hedged={_fmt_pct(lm.get('mean_hedged'))}")
    else:
        print("\n--- Gate 5: Liquidity — SKIPPED ---")
        liquidity = {"liquidity_filtered": {}}

    # ---- Write outputs ----
    md_path = write_validation(baseline, placebo, k_sweep, lag, neutral, liquidity, args.out_dir)
    json_path = write_validation_json(baseline, placebo, k_sweep, lag, neutral, liquidity, args.out_dir)

    print(f"\n{'=' * 60}")
    print(f"Results → {args.out_dir}")
    print(f"  VALIDATION.md  → {md_path}")
    print(f"  VALIDATION.json → {json_path}")


if __name__ == "__main__":
    main()
