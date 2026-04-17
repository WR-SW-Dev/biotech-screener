#!/usr/bin/env python3
"""Turnover Reduction Sweep — buffer + hysteresis + threshold.

Tests rebalance_buffer_ranks {30, 40, 50} × bucket_hysteresis {OFF, 7d, 14d}
and reports net-of-cost results for historical pseudo-PIT and live periods.

Usage:
    python research/turnover_reduction_sweep.py
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.price_store import PriceStore
from research._snapshot_loader import SnapshotLoader

EXCLUDE = {"JBIO"}
_loader = SnapshotLoader()
LIVE_START = "2024-10-01"
COST_SCENARIOS = {"Low (25bps)": 0.0025, "Base (50bps)": 0.0050, "High (100bps)": 0.0100}
K = 30  # top-K portfolio size


def _get_price(store: PriceStore, ticker: str, dt_str: str) -> Optional[float]:
    dt = date.fromisoformat(dt_str)
    for offset in range(5):
        d = (dt - timedelta(days=offset)).isoformat()
        val = store.get_price(ticker, d)
        if val:
            return val
    return None


def _load_ranked(snap_date: str) -> List[str]:
    """Load full ranked list (not just top-30) for buffer simulation."""
    return _loader.load_ranked(snap_date)


def _load_catalyst_days(snap_date: str) -> Dict[str, float]:
    """Load catalyst_days for hysteresis simulation."""
    return _loader.load_catalyst_days(snap_date)


def _select_with_buffer(
    ranked: List[str],
    prev_holdings: Set[str],
    buffer: int,
) -> List[str]:
    """Simulate rebalance_buffer_ranks selection.

    A previous holding stays if its rank is within K + buffer.
    Remaining slots filled from top of ranked list.
    """
    if not ranked:
        return []

    core_zone = set(ranked[:K])
    buffer_zone = set(ranked[: K + buffer]) if buffer > 0 else core_zone

    # Keep previous holdings that are in the buffer zone
    kept = [tk for tk in ranked if tk in prev_holdings and tk in buffer_zone]

    # Fill remaining slots from core zone (in rank order)
    remaining = K - len(kept)
    if remaining > 0:
        for tk in ranked:
            if tk not in set(kept) and tk in core_zone:
                kept.append(tk)
                if len(kept) >= K:
                    break

    return kept[:K]


def _apply_hysteresis(
    catalyst_days: Dict[str, float],
    prev_buckets: Dict[str, str],
    hysteresis_days: int,
) -> Dict[str, str]:
    """Simulate bucket hysteresis.

    Names stay in their previous bucket unless catalyst_days crosses
    boundary + hysteresis_days.
    """
    BOUNDARIES = [
        ("binary_0_30", 30),
        ("binary_31_90", 90),
        ("binary_91_180", 180),
    ]

    buckets = {}
    for tk, days in catalyst_days.items():
        # Standard bucket assignment
        if days <= 30:
            new_bucket = "binary_0_30"
        elif days <= 90:
            new_bucket = "binary_31_90"
        elif days <= 180:
            new_bucket = "binary_91_180"
        else:
            new_bucket = "less_binary"

        if hysteresis_days > 0 and tk in prev_buckets:
            old_bucket = prev_buckets[tk]
            if old_bucket != new_bucket:
                # Check if we've crossed boundary + hysteresis
                crossed = False
                for bname, bdays in BOUNDARIES:
                    if old_bucket == bname and days > bdays + hysteresis_days:
                        crossed = True
                        break
                if not crossed:
                    new_bucket = old_bucket  # stay in old bucket

        buckets[tk] = new_bucket
    return buckets


def run_sweep() -> Dict[str, Any]:
    """Run the full turnover reduction sweep."""
    store = PriceStore(str(REPO_ROOT / "data" / "prices.db"))

    pit_dates = sorted(
        [
            d
            for d in os.listdir(REPO_ROOT / "data" / "snapshots_pit_v2")
            if len(d) == 10 and (REPO_ROOT / "data" / "snapshots_pit_v2" / d / "rankings.csv").exists()
        ]
    )

    print("Turnover Reduction Sweep")
    print(f"Dates: {len(pit_dates)} ({pit_dates[0]} to {pit_dates[-1]})")
    print("=" * 90)

    # Define configs to test
    configs = []
    for buffer in [30, 40, 50]:
        for hyst in [0, 7, 14]:
            label = f"buf={buffer}_hyst={hyst}d" if hyst > 0 else f"buf={buffer}_hyst=OFF"
            configs.append({"label": label, "buffer": buffer, "hysteresis_days": hyst})

    results = {}

    for cfg in configs:
        label = cfg["label"]
        buffer = cfg["buffer"]
        hyst_days = cfg["hysteresis_days"]

        prev_holdings: Set[str] = set()
        prev_buckets: Dict[str, str] = {}
        monthly = []

        for i in range(len(pit_dates) - 1):
            start = pit_dates[i]
            end = pit_dates[i + 1]

            ranked = _load_ranked(start)
            if not ranked:
                continue

            # Apply hysteresis to bucket assignment (affects which names are "eligible")
            if hyst_days > 0:
                cat_days = _load_catalyst_days(start)
                new_buckets = _apply_hysteresis(cat_days, prev_buckets, hyst_days)
                prev_buckets = new_buckets

            # Apply buffer selection
            portfolio = _select_with_buffer(ranked, prev_holdings, buffer)
            curr_set = set(portfolio)

            # Compute turnover
            if prev_holdings:
                exited = prev_holdings - curr_set
                entered = curr_set - prev_holdings
                one_way = (len(exited) + len(entered)) / (2 * K)
            else:
                one_way = 1.0
                exited = set()
                entered = curr_set

            # Compute gross return
            rets = []
            for tk in portfolio:
                p0 = _get_price(store, tk, start)
                p1 = _get_price(store, tk, end)
                if p0 and p1 and p0 > 0:
                    rets.append((p1 - p0) / p0)
            if not rets:
                prev_holdings = curr_set
                continue

            gross_ret = sum(rets) / len(rets)
            xbi_p0 = _get_price(store, "XBI", start)
            xbi_p1 = _get_price(store, "XBI", end)
            if not xbi_p0 or not xbi_p1:
                prev_holdings = curr_set
                continue
            xbi_ret = (xbi_p1 - xbi_p0) / xbi_p0

            monthly.append(
                {
                    "date": start,
                    "gross_ret": gross_ret,
                    "xbi_ret": xbi_ret,
                    "one_way": one_way,
                    "live": start >= LIVE_START,
                }
            )

            prev_holdings = curr_set

        results[label] = _compute_metrics(monthly, label)

    # Print results
    _print_results(results)
    return results


def _compute_metrics(monthly: List[Dict], label: str) -> Dict[str, Any]:
    """Compute all metrics for a config."""
    if not monthly:
        return {"label": label, "n": 0}

    turnovers = [m["one_way"] for m in monthly[1:]]  # skip first (100% entry)

    out: Dict[str, Any] = {
        "label": label,
        "n": len(monthly),
        "avg_turnover": sum(turnovers) / len(turnovers) if turnovers else 0,
        "median_turnover": sorted(turnovers)[len(turnovers) // 2] if turnovers else 0,
        "avg_names_changed": sum(turnovers) * 2 * K / len(turnovers) if turnovers else 0,
    }

    for period_label, filter_fn in [
        ("full", lambda m: True),
        ("backtest", lambda m: not m["live"]),
        ("live", lambda m: m["live"]),
    ]:
        subset = [m for m in monthly if filter_fn(m)]
        if not subset:
            continue

        for cost_label, cost_bps in COST_SCENARIOS.items():
            key = f"{period_label}_{cost_label}"

            cum_dem = 1.0
            cum_xbi = 1.0
            excess_list = []

            for m in subset:
                cost_drag = m["one_way"] * cost_bps * 2
                net_ret = m["gross_ret"] - cost_drag
                cum_dem *= 1 + net_ret
                cum_xbi *= 1 + m["xbi_ret"]
                excess_list.append(net_ret - m["xbi_ret"])

            n = len(subset)
            mean_ex = sum(excess_list) / n
            hit = sum(1 for e in excess_list if e > 0) / n

            if n > 1:
                var = sum((e - mean_ex) ** 2 for e in excess_list) / (n - 1)
                t = mean_ex / math.sqrt(var / n) if var > 0 else 0
            else:
                t = 0

            # Max drawdown
            peak = 1.0
            max_dd = 0
            c = 1.0
            for m in subset:
                cost_drag = m["one_way"] * cost_bps * 2
                c *= 1 + m["gross_ret"] - cost_drag
                if c > peak:
                    peak = c
                dd = (c - peak) / peak
                if dd < max_dd:
                    max_dd = dd

            out[key] = {
                "n": n,
                "cum": (cum_dem - 1) * 100,
                "cum_xbi": (cum_xbi - 1) * 100,
                "excess": (cum_dem - 1) * 100 - (cum_xbi - 1) * 100,
                "monthly_ex": mean_ex * 100,
                "t": t,
                "hit": hit * 100,
                "max_dd": max_dd * 100,
            }

    return out


def _print_results(results: Dict[str, Any]) -> None:
    """Print sweep results."""
    base_cost = "Base (50bps)"

    # Main comparison table
    print()
    print(f'{"Config":>25s} {"TO%":>5s} {"Names":>5s}', end="")
    print(f' {"Hist Net Exc":>12s} {"Hist t":>7s}', end="")
    print(f' {"Live Net Exc":>12s} {"Live t":>7s}', end="")
    print(f' {"Live Hit":>8s}')
    print("-" * 90)

    for label, r in sorted(results.items()):
        if r.get("n", 0) == 0:
            continue
        to = r.get("avg_turnover", 0) * 100
        names = r.get("avg_names_changed", 0)

        hist = r.get(f"backtest_{base_cost}", {})
        live = r.get(f"live_{base_cost}", {})

        h_exc = f'{hist.get("excess", 0):+.1f}pp' if hist else "-"
        h_t = f'{hist.get("t", 0):.2f}' if hist else "-"
        l_exc = f'{live.get("excess", 0):+.1f}pp' if live else "-"
        l_t = f'{live.get("t", 0):.2f}' if live else "-"
        l_hit = f'{live.get("hit", 0):.0f}%' if live else "-"

        print(
            f"{label:>25s} {to:>4.1f}% {names:>4.1f}",
            end="",
        )
        print(f" {h_exc:>12s} {h_t:>7s}", end="")
        print(f" {l_exc:>12s} {l_t:>7s}", end="")
        print(f" {l_hit:>8s}")

    # Detailed comparison: baseline (buf=30) vs best
    print()
    print("=" * 90)
    print("BASELINE vs CANDIDATES — Net at Base Cost (50bps)")
    print("=" * 90)

    baseline = results.get("buf=30_hyst=OFF", {})
    if not baseline:
        return

    bl_live = baseline.get(f"live_{base_cost}", {})
    bl_hist = baseline.get(f"backtest_{base_cost}", {})
    bl_to = baseline.get("avg_turnover", 0)

    print(f'\n{"":>25s} {"ΔTurnover":>10s} {"ΔLive Exc":>10s} {"ΔHist Exc":>10s} {"Live t":>7s}')
    print("-" * 65)

    for label, r in sorted(results.items()):
        if r.get("n", 0) == 0 or label == "buf=30_hyst=OFF":
            continue

        r_live = r.get(f"live_{base_cost}", {})
        r_hist = r.get(f"backtest_{base_cost}", {})
        r_to = r.get("avg_turnover", 0)

        d_to = (r_to - bl_to) * 100
        d_live = r_live.get("excess", 0) - bl_live.get("excess", 0) if r_live and bl_live else 0
        d_hist = r_hist.get("excess", 0) - bl_hist.get("excess", 0) if r_hist and bl_hist else 0
        l_t = r_live.get("t", 0) if r_live else 0

        print(f"{label:>25s} {d_to:>+9.1f}pp {d_live:>+9.1f}pp {d_hist:>+9.1f}pp {l_t:>6.2f}")

    # Cost sensitivity for best candidate
    print()
    print("=" * 90)
    print("COST SENSITIVITY — Baseline (buf=30) vs Best Live Candidate")
    print("=" * 90)

    # Find best live candidate
    best_label = None
    best_live_excess = -999
    for label, r in results.items():
        live_r = r.get(f"live_{base_cost}", {})
        if live_r and live_r.get("excess", -999) > best_live_excess:
            best_live_excess = live_r["excess"]
            best_label = label

    if best_label:
        print(f"\nBest live candidate: {best_label}")
        print()
        print(f'{"Cost":>15s}', end="")
        print(f' {"Baseline Exc":>12s} {"Best Exc":>12s} {"Δ":>8s}')
        print("-" * 50)

        for cost_label in COST_SCENARIOS:
            bl = baseline.get(f"live_{cost_label}", {})
            best = results[best_label].get(f"live_{cost_label}", {})
            bl_e = bl.get("excess", 0) if bl else 0
            be_e = best.get("excess", 0) if best else 0
            print(f"{cost_label:>15s} {bl_e:>+11.1f}pp {be_e:>+11.1f}pp {be_e - bl_e:>+7.1f}pp")


if __name__ == "__main__":
    run_sweep()
