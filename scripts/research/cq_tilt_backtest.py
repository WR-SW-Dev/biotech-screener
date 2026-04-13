#!/usr/bin/env python3
"""CQ conviction tilt backtest — 4-arm comparison.

Arms:
  1. EW Top-30 (baseline)
  2. Conviction B6^1.5 (current production)
  3. Conviction + CQ sizing tilt (strength=0.15, cap=0.20)
  4. Conviction + CQ sizing tilt (strength=0.10, cap=0.15, conservative)

Measures per arm per snapshot:
  - Weighted portfolio return (5d, 20d, 63d)
  - HHI (concentration)
  - Overlap with baseline

Usage:
    python scripts/research/cq_tilt_backtest.py [--from DATE] [--to DATE]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.clinical_quality_score import compute_clinical_quality_scores
from event_ev.portfolio_sizing import compute_weights
from scripts.eval_forward_returns import (
    compute_forward_return,
    discover_snapshot_dates,
    load_price_series,
    load_rankings,
    resolve_trade_date,
)

HORIZONS = [5, 20, 63]

ARM_CONFIGS = {
    "ew_baseline": {"alpha": 1.0, "cq_strength": 0.0, "label": "EW Top-30"},
    "conviction": {"alpha": 1.5, "cq_strength": 0.0, "label": "B6^1.5 (production)"},
    "cq_tilt_015": {"alpha": 1.5, "cq_strength": 0.15, "label": "B6^1.5 + CQ tilt 0.15"},
    "cq_tilt_010": {"alpha": 1.5, "cq_strength": 0.10, "label": "B6^1.5 + CQ tilt 0.10 (conservative)"},
}


def _safe_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        v = float(val)
        return v if v == v else None
    except (ValueError, TypeError):
        return None


def _portfolio_return(weights: Dict[str, float], fwd: Dict[str, float]) -> Optional[float]:
    """Compute weighted portfolio return."""
    total_w = 0.0
    total_ret = 0.0
    for t, w in weights.items():
        if t in fwd:
            total_ret += w * fwd[t]
            total_w += w
    if total_w < 0.5:  # need at least 50% of weight to have returns
        return None
    return total_ret / total_w


def _hhi(weights: Dict[str, float]) -> float:
    return sum(w**2 for w in weights.values())


def _overlap(w1: Dict[str, float], w2: Dict[str, float]) -> int:
    return len(set(w1.keys()) & set(w2.keys()))


def run_backtest(
    snapshot_root: Path,
    price_csv: Path,
    trial_records_path: Path,
    date_from: str = "2022-01-01",
    date_to: str = "2026-03-31",
    top_n: int = 30,
) -> Dict[str, Any]:
    with open(trial_records_path) as f:
        trial_records = json.load(f)

    snap_dates = discover_snapshot_dates(snapshot_root, date_from, date_to)
    prices = load_price_series(price_csv)

    all_dates_set: set = set()
    for tp in prices.values():
        all_dates_set.update(tp.keys())
    sorted_dates = sorted(all_dates_set)

    # Per-arm accumulators: {arm: {horizon: [returns]}}
    arm_returns: Dict[str, Dict[int, List[float]]] = {arm: {h: [] for h in HORIZONS} for arm in ARM_CONFIGS}
    arm_hhi: Dict[str, List[float]] = {arm: [] for arm in ARM_CONFIGS}
    arm_overlap: Dict[str, List[int]] = {arm: [] for arm in ARM_CONFIGS}

    n_dates = 0

    for snap_date in snap_dates:
        trade_date = resolve_trade_date(sorted_dates, snap_date, "next_trading_day")
        if not trade_date:
            continue

        rankings = load_rankings(snapshot_root / snap_date)
        if not rankings:
            continue

        # Extract conviction scores (coinvest_score_z as B6 proxy for older snapshots)
        b6_map: Dict[str, float] = {}
        for row in rankings:
            tk = (row.get("ticker") or "").upper()
            # Try selector_score first (Spec 050+), fall back to coinvest_score_z
            sel = _safe_float(row.get("selector_score"))
            if sel is None:
                sel = _safe_float(row.get("coinvest_score_z"))
            if tk and sel is not None:
                b6_map[tk] = sel

        if len(b6_map) < 30:
            continue

        # Normalize to 0-1 percentile (compute_weights expects this)
        sorted_by_score = sorted(b6_map.items(), key=lambda x: x[1])
        n = len(sorted_by_score)
        b6_pct: Dict[str, float] = {}
        for rank_i, (tk, _) in enumerate(sorted_by_score):
            b6_pct[tk] = (rank_i + 0.5) / n  # midpoint percentile

        # Rank by score, take top-N
        ranked = sorted(b6_map.keys(), key=lambda t: b6_map[t], reverse=True)[:top_n]

        # Uniform trap (we're isolating the CQ effect)
        trap_map = {t: 1.0 for t in ranked}

        # Compute CQ scores at this snapshot
        cq_results = compute_clinical_quality_scores(trial_records, snap_date)
        cq_map = {tk: r.clinical_quality_score for tk, r in cq_results.items()}

        n_dates += 1

        # Compute forward returns for all tickers
        for h in HORIZONS:
            fwd: Dict[str, float] = {}
            for tk in ranked:
                if tk in prices:
                    ret = compute_forward_return(prices[tk], sorted_dates, trade_date, h)
                    if ret is not None:
                        fwd[tk] = ret

            if len(fwd) < 15:
                continue

            # Compute weights and returns for each arm
            for arm_name, cfg in ARM_CONFIGS.items():
                if cfg["alpha"] == 1.0:
                    # EW
                    weights = {t: 1.0 / len(ranked) for t in ranked}
                else:
                    weights = compute_weights(
                        ranked,
                        b6_pct,
                        trap_map,
                        alpha=cfg["alpha"],
                        cq_scores=cq_map if cfg["cq_strength"] > 0 else None,
                        cq_tilt_strength=cfg["cq_strength"],
                    )

                port_ret = _portfolio_return(weights, fwd)
                if port_ret is not None:
                    arm_returns[arm_name][h].append(port_ret)

                if h == HORIZONS[0]:  # only compute once per snapshot
                    arm_hhi[arm_name].append(_hhi(weights))
                    arm_overlap[arm_name].append(_overlap(weights, {t: 1.0 / len(ranked) for t in ranked}))

    # Compile results
    result: Dict[str, Any] = {
        "n_dates": n_dates,
        "date_range": [date_from, date_to],
        "top_n": top_n,
        "arms": {},
    }

    for arm_name, cfg in ARM_CONFIGS.items():
        arm_result: Dict[str, Any] = {"label": cfg["label"], "horizons": {}}
        for h in HORIZONS:
            rets = arm_returns[arm_name][h]
            if len(rets) >= 2:
                mean_ret = statistics.mean(rets)
                std_ret = statistics.stdev(rets)
                sharpe = mean_ret / std_ret * math.sqrt(12) if std_ret > 0 else 0
                arm_result["horizons"][str(h)] = {
                    "mean_ret_pct": round(mean_ret * 100, 3),
                    "std_ret_pct": round(std_ret * 100, 3),
                    "sharpe_annualized": round(sharpe, 3),
                    "hit_rate": round(sum(1 for r in rets if r > 0) / len(rets), 3),
                    "n": len(rets),
                }
            else:
                arm_result["horizons"][str(h)] = {"n": len(rets)}

        if arm_hhi[arm_name]:
            arm_result["mean_hhi"] = round(statistics.mean(arm_hhi[arm_name]), 6)
            arm_result["effective_n"] = round(1.0 / statistics.mean(arm_hhi[arm_name]), 1)
        if arm_overlap[arm_name]:
            arm_result["mean_overlap_with_ew"] = round(statistics.mean(arm_overlap[arm_name]), 1)

        result["arms"][arm_name] = arm_result

    return result


def _format_report(result: Dict[str, Any]) -> str:
    lines = []
    lines.append("=" * 75)
    lines.append("CQ CONVICTION TILT BACKTEST — 4-ARM COMPARISON")
    lines.append(f"Snapshots: {result['n_dates']}, Top-{result['top_n']}")
    lines.append(f"Date range: {result['date_range'][0]} → {result['date_range'][1]}")
    lines.append("=" * 75)

    for arm_name, arm in result["arms"].items():
        lines.append(f"\n--- {arm['label']} ---")
        if "mean_hhi" in arm:
            lines.append(
                f"  HHI={arm['mean_hhi']:.4f}  Eff-N={arm['effective_n']:.0f}  "
                f"Overlap={arm.get('mean_overlap_with_ew', 'N/A')}"
            )
        for h_str, h_data in sorted(arm["horizons"].items(), key=lambda x: int(x[0])):
            if "mean_ret_pct" in h_data:
                lines.append(
                    f"  {h_str:>3}d: ret={h_data['mean_ret_pct']:+.3f}%  "
                    f"std={h_data['std_ret_pct']:.3f}%  "
                    f"Sharpe={h_data['sharpe_annualized']:+.3f}  "
                    f"hit={h_data['hit_rate']:.1%}  "
                    f"n={h_data['n']}"
                )
            else:
                lines.append(f"  {h_str:>3}d: insufficient data (n={h_data['n']})")

    # Comparison table
    lines.append("\n" + "=" * 75)
    lines.append("COMPARISON: mean return % and Sharpe by horizon")
    lines.append(f"{'Arm':<40s}  {'5d':>8s}  {'20d':>8s}  {'63d':>8s}")
    lines.append("-" * 75)
    for arm_name, arm in result["arms"].items():
        parts = [f"{arm['label']:<40s}"]
        for h in ["5", "20", "63"]:
            h_data = arm["horizons"].get(h, {})
            if "mean_ret_pct" in h_data:
                parts.append(f"{h_data['mean_ret_pct']:+7.3f}%")
            else:
                parts.append(f"{'N/A':>8s}")
        lines.append("  ".join(parts))

    lines.append("\nSharpe (annualized from monthly):")
    lines.append(f"{'Arm':<40s}  {'5d':>8s}  {'20d':>8s}  {'63d':>8s}")
    lines.append("-" * 75)
    for arm_name, arm in result["arms"].items():
        parts = [f"{arm['label']:<40s}"]
        for h in ["5", "20", "63"]:
            h_data = arm["horizons"].get(h, {})
            if "sharpe_annualized" in h_data:
                parts.append(f"{h_data['sharpe_annualized']:+7.3f}")
            else:
                parts.append(f"{'N/A':>8s}")
        lines.append("  ".join(parts))

    lines.append("\n" + "=" * 75)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="CQ conviction tilt backtest")
    parser.add_argument("--from", dest="date_from", default="2022-01-01")
    parser.add_argument("--to", dest="date_to", default="2026-03-31")
    parser.add_argument("--snapshot-root", type=Path, default=PROJECT_ROOT / "data" / "snapshots_pit")
    parser.add_argument("--price-csv", type=Path, default=PROJECT_ROOT / "production_data" / "price_history.csv")
    parser.add_argument("--trial-records", type=Path, default=PROJECT_ROOT / "production_data" / "trial_records.json")
    args = parser.parse_args()

    result = run_backtest(
        args.snapshot_root,
        args.price_csv,
        args.trial_records,
        args.date_from,
        args.date_to,
    )

    out_dir = PROJECT_ROOT / "output" / "cq_tilt_backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "backtest_results.json", "w") as f:
        json.dump(result, f, indent=2)

    report = _format_report(result)
    print(report)
    with open(out_dir / "backtest_report.txt", "w") as f:
        f.write(report)

    print(f"\nResults written to {out_dir}/")


if __name__ == "__main__":
    main()
