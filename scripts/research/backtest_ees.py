#!/usr/bin/env python3
"""Backtest Expectation Error Score (EES) — predictive power evaluation.

Walk-forward Spearman IC and decile spread for the composite EES and
each of the six sub-scores against 5d/20d/63d forward returns.

Reads backfilled rankings.csv snapshots with EES columns.

Usage:
    python3 scripts/research/backtest_ees.py \
        --snapshot-root data/snapshots \
        --price-csv production_data/price_history.csv \
        --date-from 2022-03-18 --date-to 2026-04-10 \
        --out-dir output/ees_backtest
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
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

# ── EES signal definitions ───────────────────────────────────────────────
# (column, direction, label, group)
# direction: +1 = higher value → better return expected

EES_SIGNALS = [
    # Composite
    ("expectation_error_score", +1, "EES_composite", "composite"),
    # Sub-scores (alpha-side: higher = more opportunity)
    ("base_rate_gap_score", -1, "base_rate_gap (inv)", "alpha"),
    ("conditional_misprice_score", +1, "conditional_misprice", "alpha"),
    ("divergence_score", -1, "divergence (inv)", "alpha"),
    ("crowding_bias_score", +1, "crowding_bias", "alpha"),
    # Friction-side (higher = worse)
    ("slippage_penalty_score", -1, "slippage_penalty (inv)", "friction"),
    ("timing_decay_risk_score", -1, "timing_decay (inv)", "friction"),
    # Confidence
    ("expectation_confidence", +1, "confidence", "meta"),
]


@dataclass
class SignalDateResult:
    date: str
    trade_date: str
    signal_name: str
    group: str
    horizon: int
    ic: Optional[float] = None
    ls_spread: Optional[float] = None
    n_obs: int = 0
    top_decile_ret: Optional[float] = None
    bottom_decile_ret: Optional[float] = None


def _extract_signal(rankings: List[Dict[str, str]], column: str) -> Dict[str, float]:
    result: Dict[str, float] = {}
    for r in rankings:
        t = r.get("ticker", "")
        v = r.get(column, "")
        if t and v and v not in ("", "nan", "None"):
            try:
                result[t] = float(v)
            except (ValueError, TypeError):
                pass
    return result


def _decile_spread(
    signal: Dict[str, float],
    fwd_rets: Dict[str, float],
    direction: int,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    common = [t for t in signal if t in fwd_rets]
    if len(common) < 10:
        return None, None, None
    common.sort(key=lambda t: signal[t], reverse=(direction == +1))
    d = max(1, len(common) // 10)
    top = common[:d]
    bot = common[-d:]
    top_ret = statistics.mean(fwd_rets[t] for t in top)
    bot_ret = statistics.mean(fwd_rets[t] for t in bot)
    return top_ret - bot_ret, top_ret, bot_ret


def evaluate(
    snapshot_root: Path,
    price_csv: Path,
    horizons: List[int],
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[SignalDateResult]:
    snap_dates = discover_snapshot_dates(snapshot_root, date_from, date_to)
    prices = load_price_series(price_csv)

    all_dates_set: set = set()
    for tp in prices.values():
        all_dates_set.update(tp.keys())
    sorted_dates = sorted(all_dates_set)

    results: List[SignalDateResult] = []

    for snap_date in snap_dates:
        snap_dir = snapshot_root / snap_date
        trade_date = resolve_trade_date(sorted_dates, snap_date, "next_trading_day")
        if trade_date is None:
            continue

        rankings = load_rankings(snap_dir)
        if not rankings:
            continue

        # Check EES is populated
        first_ees = next(
            (r.get("expectation_error_score", "") for r in rankings),
            "",
        )
        if first_ees.strip() in ("", "None", "nan"):
            continue

        signal_maps: Dict[str, Dict[str, float]] = {}
        for col, direction, label, group in EES_SIGNALS:
            signal_maps[label] = _extract_signal(rankings, col)

        for h in horizons:
            all_tickers = set()
            for sm in signal_maps.values():
                all_tickers.update(sm.keys())

            fwd_rets: Dict[str, float] = {}
            for ticker in all_tickers:
                if ticker not in prices:
                    continue
                ret = compute_forward_return(prices[ticker], sorted_dates, trade_date, h)
                if ret is not None:
                    fwd_rets[ticker] = ret

            if not fwd_rets:
                continue

            for col, direction, label, group in EES_SIGNALS:
                sig = signal_maps[label]
                common = [t for t in sig if t in fwd_rets]
                n = len(common)

                ic = None
                if n >= 10:
                    sig_vals = [sig[t] * direction for t in common]
                    ret_vals = [fwd_rets[t] for t in common]
                    ic = spearman_ic(sig_vals, ret_vals)

                spread, top_ret, bot_ret = _decile_spread(sig, fwd_rets, direction)

                results.append(
                    SignalDateResult(
                        date=snap_date,
                        trade_date=trade_date,
                        signal_name=label,
                        group=group,
                        horizon=h,
                        ic=round(ic, 4) if ic is not None else None,
                        ls_spread=round(spread, 6) if spread is not None else None,
                        n_obs=n,
                        top_decile_ret=round(top_ret, 6) if top_ret is not None else None,
                        bottom_decile_ret=round(bot_ret, 6) if bot_ret is not None else None,
                    )
                )

    return results


def aggregate(
    results: List[SignalDateResult],
    horizons: List[int],
) -> Dict[int, List[Dict[str, Any]]]:
    grouped: Dict[Tuple[str, int], List[SignalDateResult]] = defaultdict(list)
    for r in results:
        grouped[(r.signal_name, r.horizon)].append(r)

    out: Dict[int, List[Dict[str, Any]]] = {h: [] for h in horizons}

    for (signal_name, h), date_results in sorted(grouped.items()):
        if h not in out:
            continue
        ics = [r.ic for r in date_results if r.ic is not None]
        spreads = [r.ls_spread for r in date_results if r.ls_spread is not None]
        n_dates = len(date_results)
        n_obs_mean = statistics.mean(r.n_obs for r in date_results) if date_results else 0

        mean_ic = statistics.mean(ics) if ics else None
        std_ic = statistics.stdev(ics) if len(ics) >= 2 else None
        t_stat = None
        if mean_ic is not None and std_ic and std_ic > 0 and len(ics) >= 2:
            t_stat = mean_ic / (std_ic / math.sqrt(len(ics)))

        mean_spread = statistics.mean(spreads) if spreads else None
        hit_rate = sum(1 for ic in ics if ic > 0) / len(ics) if ics else None

        # Find group
        group = date_results[0].group if date_results else ""

        out[h].append(
            {
                "signal": signal_name,
                "group": group,
                "n_dates": n_dates,
                "n_obs_mean": round(n_obs_mean, 1),
                "mean_ic": round(mean_ic, 4) if mean_ic is not None else None,
                "std_ic": round(std_ic, 4) if std_ic is not None else None,
                "t_stat": round(t_stat, 2) if t_stat is not None else None,
                "hit_rate": round(hit_rate, 3) if hit_rate is not None else None,
                "mean_ls_spread": round(mean_spread, 6) if mean_spread is not None else None,
            }
        )

    # Sort each horizon by abs(mean_ic) descending
    for h in out:
        out[h].sort(key=lambda r: abs(r.get("mean_ic") or 0), reverse=True)

    return out


def write_outputs(
    agg: Dict[int, List[Dict[str, Any]]],
    results: List[SignalDateResult],
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # summary.json
    with open(out_dir / "summary.json", "w") as f:
        json.dump(agg, f, indent=2, default=str)

    # by_date_signal.csv
    with open(out_dir / "by_date_signal.csv", "w", newline="") as f:
        fields = [
            "date",
            "trade_date",
            "signal_name",
            "group",
            "horizon",
            "ic",
            "ls_spread",
            "n_obs",
            "top_decile_ret",
            "bottom_decile_ret",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "date": r.date,
                    "trade_date": r.trade_date,
                    "signal_name": r.signal_name,
                    "group": r.group,
                    "horizon": r.horizon,
                    "ic": r.ic,
                    "ls_spread": r.ls_spread,
                    "n_obs": r.n_obs,
                    "top_decile_ret": r.top_decile_ret,
                    "bottom_decile_ret": r.bottom_decile_ret,
                }
            )

    # summary.md
    lines = ["# EES Backtest Results", ""]
    for h, rows in sorted(agg.items()):
        lines.append(f"## {h}d forward returns")
        lines.append("")
        lines.append("| Signal | Group | Dates | IC | t-stat | Hit% | L/S Spread |")
        lines.append("|--------|-------|------:|---:|-------:|-----:|-----------:|")
        for r in rows:
            ic_str = f"{r['mean_ic']:+.4f}" if r["mean_ic"] is not None else "—"
            t_str = f"{r['t_stat']:+.2f}" if r["t_stat"] is not None else "—"
            hr_str = f"{r['hit_rate']:.1%}" if r["hit_rate"] is not None else "—"
            sp_str = f"{r['mean_ls_spread']:+.4f}" if r["mean_ls_spread"] is not None else "—"
            lines.append(
                f"| {r['signal']:<30s} | {r['group']:<10s} | {r['n_dates']:>5d} "
                f"| {ic_str:>7s} | {t_str:>6s} | {hr_str:>5s} | {sp_str:>10s} |"
            )
        lines.append("")

    with open(out_dir / "summary.md", "w") as f:
        f.write("\n".join(lines))
        f.write("\n")

    print(f"Written: {out_dir / 'summary.json'}")
    print(f"Written: {out_dir / 'by_date_signal.csv'}")
    print(f"Written: {out_dir / 'summary.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest EES against forward returns")
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=PROJECT_ROOT / "data" / "snapshots",
    )
    parser.add_argument(
        "--price-csv",
        type=Path,
        default=PROJECT_ROOT / "production_data" / "price_history.csv",
    )
    parser.add_argument("--horizons", default="5,20,63")
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "ees_backtest",
    )
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]

    print(f"Snapshot root: {args.snapshot_root}")
    print(f"Price CSV:     {args.price_csv}")
    print(f"Horizons:      {horizons}")
    print(f"Date range:    {args.date_from or 'all'} → {args.date_to or 'all'}")
    print()

    results = evaluate(
        args.snapshot_root,
        args.price_csv,
        horizons,
        args.date_from,
        args.date_to,
    )

    if not results:
        print("No results — check snapshot dates and EES column presence.")
        return

    n_dates = len(set(r.date for r in results))
    print(f"Evaluated {n_dates} snapshot dates, {len(results)} signal-date-horizon observations")
    print()

    agg = aggregate(results, horizons)
    write_outputs(agg, results, args.out_dir)

    # Print summary table
    for h, rows in sorted(agg.items()):
        print(f"=== {h}d horizon ===")
        print(f"{'Signal':<32s} {'IC':>7s} {'t':>6s} {'Hit%':>6s} {'L/S':>8s} {'N':>5s}")
        print("-" * 70)
        for r in rows:
            ic_str = f"{r['mean_ic']:+.4f}" if r["mean_ic"] is not None else "—"
            t_str = f"{r['t_stat']:+.2f}" if r["t_stat"] is not None else "—"
            hr_str = f"{r['hit_rate']:.0%}" if r["hit_rate"] is not None else "—"
            sp_str = f"{r['mean_ls_spread']:+.4f}" if r["mean_ls_spread"] is not None else "—"
            print(f"{r['signal']:<32s} {ic_str:>7s} {t_str:>6s} {hr_str:>6s} {sp_str:>8s} {r['n_dates']:>5d}")
        print()


if __name__ == "__main__":
    main()
