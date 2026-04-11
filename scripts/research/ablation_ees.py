#!/usr/bin/env python3
"""EES ablation study — decompose composite into Quality vs Trap vs Alpha.

Runs 4 ablation arms:
  A) Quality only:     -slippage - timing_decay
  B) Trap only:        -base_rate_gap - conditional_misprice - confidence
  C) Original alpha:   +base_rate_gap + conditional_misprice + crowding + divergence
  D) Quality + Trap:   A + B combined

Each arm computes a synthetic composite from the backfilled sub-scores
and measures Spearman IC / decile spread against forward returns.

Usage:
    python3 scripts/research/ablation_ees.py
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval_forward_returns import (
    compute_forward_return,
    discover_snapshot_dates,
    load_price_series,
    load_rankings,
    resolve_trade_date,
    spearman_ic,
)

# ── Ablation arm definitions ─────────────────────────────────────────────
# Each arm: (label, {column: weight})
# Negative weight = "avoid high values" = the backtest-validated direction

ARMS: List[Tuple[str, Dict[str, float]]] = [
    (
        "A_quality_only",
        {
            "slippage_penalty_score": -0.50,
            "timing_decay_risk_score": -0.50,
        },
    ),
    (
        "B_trap_only",
        {
            "base_rate_gap_score": -0.40,  # flipped: obvious cheap = trap
            "conditional_misprice_score": -0.35,  # flipped: scenario underpriced = trap
            "expectation_confidence": -0.25,  # flipped: high data = doesn't help
        },
    ),
    (
        "C_original_alpha",
        {
            "base_rate_gap_score": +0.30,  # original direction (unflipped)
            "conditional_misprice_score": +0.25,
            "crowding_bias_score": +0.25,
            "divergence_score": +0.20,
        },
    ),
    (
        "D_quality_plus_trap",
        {
            "slippage_penalty_score": -0.25,
            "timing_decay_risk_score": -0.25,
            "base_rate_gap_score": -0.20,
            "conditional_misprice_score": -0.15,
            "expectation_confidence": -0.15,
        },
    ),
    (
        "E_v1_composite",
        {
            # Original v1 EES weights for comparison
            "base_rate_gap_score": +0.30,
            "conditional_misprice_score": +0.20,
            "divergence_score": +0.10,
            "crowding_bias_score": +0.15,
            "slippage_penalty_score": -0.15,
            "timing_decay_risk_score": -0.10,
        },
    ),
]

HORIZONS = [5, 20, 63]


def _safe_float(v: str) -> Optional[float]:
    if not v or v in ("", "None", "nan"):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def compute_arm_score(row: Dict[str, str], weights: Dict[str, float]) -> Optional[float]:
    """Compute weighted composite from sub-score columns."""
    total = 0.0
    n_available = 0
    for col, w in weights.items():
        v = _safe_float(row.get(col, ""))
        if v is not None:
            total += w * v
            n_available += 1
    if n_available == 0:
        return None
    return total


def _decile_spread(
    signal: Dict[str, float],
    fwd_rets: Dict[str, float],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    common = [t for t in signal if t in fwd_rets]
    if len(common) < 10:
        return None, None, None
    common.sort(key=lambda t: signal[t], reverse=True)  # higher = better
    d = max(1, len(common) // 10)
    top_ret = statistics.mean(fwd_rets[t] for t in common[:d])
    bot_ret = statistics.mean(fwd_rets[t] for t in common[-d:])
    return top_ret - bot_ret, top_ret, bot_ret


def run_ablation(
    snapshot_root: Path,
    price_csv: Path,
    date_from: str = "2022-03-18",
    date_to: str = "2026-03-31",
) -> Dict[str, Any]:
    snap_dates = discover_snapshot_dates(snapshot_root, date_from, date_to)
    prices = load_price_series(price_csv)

    all_dates_set: set = set()
    for tp in prices.values():
        all_dates_set.update(tp.keys())
    sorted_dates = sorted(all_dates_set)

    # Collect per-date, per-arm, per-horizon IC
    # {(arm, horizon): [ic_values]}
    ic_by_arm_h: Dict[Tuple[str, int], List[float]] = defaultdict(list)
    spread_by_arm_h: Dict[Tuple[str, int], List[float]] = defaultdict(list)
    n_dates_used = 0

    for snap_date in snap_dates:
        snap_dir = snapshot_root / snap_date
        trade_date = resolve_trade_date(sorted_dates, snap_date, "next_trading_day")
        if trade_date is None:
            continue

        rankings = load_rankings(snap_dir)
        if not rankings:
            continue

        # Check EES columns exist
        if _safe_float(rankings[0].get("slippage_penalty_score", "")) is None:
            continue

        # Compute arm scores for all tickers
        arm_signals: Dict[str, Dict[str, float]] = {}
        for arm_name, weights in ARMS:
            sig: Dict[str, float] = {}
            for row in rankings:
                ticker = row.get("ticker", "")
                if not ticker:
                    continue
                score = compute_arm_score(row, weights)
                if score is not None:
                    sig[ticker] = score
            arm_signals[arm_name] = sig

        n_dates_used += 1

        for h in HORIZONS:
            # Compute forward returns for all tickers
            all_tickers: set = set()
            for sig in arm_signals.values():
                all_tickers.update(sig.keys())

            fwd_rets: Dict[str, float] = {}
            for ticker in all_tickers:
                if ticker not in prices:
                    continue
                ret = compute_forward_return(prices[ticker], sorted_dates, trade_date, h)
                if ret is not None:
                    fwd_rets[ticker] = ret

            if not fwd_rets:
                continue

            for arm_name, _ in ARMS:
                sig = arm_signals[arm_name]
                common = [t for t in sig if t in fwd_rets]
                n = len(common)

                if n >= 10:
                    # direction = +1 (higher arm score = better)
                    sig_vals = [sig[t] for t in common]
                    ret_vals = [fwd_rets[t] for t in common]
                    ic = spearman_ic(sig_vals, ret_vals)
                    if ic is not None:
                        ic_by_arm_h[(arm_name, h)].append(ic)

                spread, _, _ = _decile_spread(sig, fwd_rets)
                if spread is not None:
                    spread_by_arm_h[(arm_name, h)].append(spread)

    # Aggregate
    results: Dict[str, Any] = {"n_dates": n_dates_used, "arms": {}}

    for arm_name, _ in ARMS:
        arm_result: Dict[str, Any] = {}
        for h in HORIZONS:
            ics = ic_by_arm_h.get((arm_name, h), [])
            spreads = spread_by_arm_h.get((arm_name, h), [])

            mean_ic = statistics.mean(ics) if ics else None
            std_ic = statistics.stdev(ics) if len(ics) >= 2 else None
            t_stat = None
            if mean_ic is not None and std_ic and std_ic > 0 and len(ics) >= 2:
                t_stat = mean_ic / (std_ic / math.sqrt(len(ics)))

            hit_rate = sum(1 for ic in ics if ic > 0) / len(ics) if ics else None
            mean_spread = statistics.mean(spreads) if spreads else None

            arm_result[f"{h}d"] = {
                "mean_ic": round(mean_ic, 4) if mean_ic is not None else None,
                "std_ic": round(std_ic, 4) if std_ic is not None else None,
                "t_stat": round(t_stat, 2) if t_stat is not None else None,
                "hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
                "mean_ls_spread": round(mean_spread, 6) if mean_spread is not None else None,
                "n_ic_obs": len(ics),
            }
        results["arms"][arm_name] = arm_result

    return results


def main() -> None:
    snapshot_root = PROJECT_ROOT / "data" / "snapshots"
    price_csv = PROJECT_ROOT / "production_data" / "price_history.csv"
    out_dir = PROJECT_ROOT / "output" / "ees_ablation"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Running EES ablation study...")
    print(f"  Snapshot root: {snapshot_root}")
    print(f"  Horizons: {HORIZONS}")
    print()

    results = run_ablation(snapshot_root, price_csv)

    # Save JSON
    with open(out_dir / "ablation_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Print table
    n = results["n_dates"]
    print(f"Evaluated {n} snapshot dates\n")

    for h in HORIZONS:
        print(f"{'=' * 74}")
        print(f"  {h}d FORWARD RETURNS")
        print(f"{'=' * 74}")
        print(f"{'Arm':<28s} {'IC':>8s} {'t-stat':>8s} {'Hit%':>7s} {'L/S':>10s}")
        print(f"{'-' * 74}")

        rows = []
        for arm_name, _ in ARMS:
            r = results["arms"][arm_name][f"{h}d"]
            rows.append((arm_name, r))

        # Sort by IC descending
        rows.sort(key=lambda x: abs(x[1].get("mean_ic") or 0), reverse=True)

        for arm_name, r in rows:
            ic = f"{r['mean_ic']:+.4f}" if r["mean_ic"] is not None else "—"
            t = f"{r['t_stat']:+.2f}" if r["t_stat"] is not None else "—"
            hr = f"{r['hit_rate']:.0%}" if r["hit_rate"] is not None else "—"
            sp = f"{r['mean_ls_spread']:+.4f}" if r["mean_ls_spread"] is not None else "—"
            print(f"{arm_name:<28s} {ic:>8s} {t:>8s} {hr:>7s} {sp:>10s}")
        print()

    # Save markdown
    lines = ["# EES Ablation Study", "", f"**{n} snapshot dates evaluated**", ""]
    for h in HORIZONS:
        lines.append(f"## {h}d forward returns")
        lines.append("")
        lines.append("| Arm | IC | t-stat | Hit% | L/S Spread |")
        lines.append("|-----|---:|-------:|-----:|-----------:|")
        for arm_name, _ in ARMS:
            r = results["arms"][arm_name][f"{h}d"]
            ic = f"{r['mean_ic']:+.4f}" if r["mean_ic"] is not None else "—"
            t = f"{r['t_stat']:+.2f}" if r["t_stat"] is not None else "—"
            hr = f"{r['hit_rate']:.0%}" if r["hit_rate"] is not None else "—"
            sp = f"{r['mean_ls_spread']:+.4f}" if r["mean_ls_spread"] is not None else "—"
            lines.append(f"| {arm_name} | {ic} | {t} | {hr} | {sp} |")
        lines.append("")

    with open(out_dir / "ablation_results.md", "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Written: {out_dir / 'ablation_results.json'}")
    print(f"Written: {out_dir / 'ablation_results.md'}")


if __name__ == "__main__":
    main()
