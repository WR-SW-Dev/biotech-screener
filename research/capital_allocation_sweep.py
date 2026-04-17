#!/usr/bin/env python3
"""Capital Allocation Sizing Sweep.

Tests DEM sleeve + core (XBI or EW-all) at 0-100% in 10% steps.
All results net of 50bps one-way. Ex-tail metrics as first-class outputs.

Usage:
    python research/capital_allocation_sweep.py
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.price_store import PriceStore
from research._snapshot_loader import SnapshotLoader

EXCLUDE = {"JBIO"}
_loader = SnapshotLoader()
LIVE_START = "2024-10-01"
K = 30
COST_BPS = 0.0050
RF_ANNUAL = 0.045


def _get_price(store, ticker, dt_str):
    dt = date.fromisoformat(dt_str)
    for offset in range(5):
        d = (dt - timedelta(days=offset)).isoformat()
        val = store.get_price(ticker, d)
        if val:
            return val
    return None


def _load_ranked(snap_date):
    return _loader.load_ranked(snap_date)


def _load_eligible(snap_date):
    return _loader.load_eligible(snap_date)


def _select_with_buffer(ranked, prev, buffer=30):
    if not ranked:
        return []
    core = set(ranked[:K])
    buf = set(ranked[: K + buffer]) if buffer > 0 else core
    kept = [tk for tk in ranked if tk in prev and tk in buf]
    for tk in ranked:
        if len(kept) >= K:
            break
        if tk not in set(kept) and tk in core:
            kept.append(tk)
    return kept[:K]


def _build_sleeve_series(store):
    """Build monthly net returns for DEM, EW-all, and XBI separately."""
    pit_dates = sorted(
        [
            d
            for d in os.listdir(REPO_ROOT / "data" / "snapshots_pit_v2")
            if len(d) == 10 and (REPO_ROOT / "data" / "snapshots_pit_v2" / d / "rankings.csv").exists()
        ]
    )

    prev_dem: Set[str] = set()
    prev_ew: Set[str] = set()
    monthly = []

    for i in range(len(pit_dates) - 1):
        start = pit_dates[i]
        end = pit_dates[i + 1]

        ranked = _load_ranked(start)
        eligible = _load_eligible(start)
        if not ranked or not eligible:
            continue

        dem30 = _select_with_buffer(ranked, prev_dem)
        curr_dem = set(dem30)
        curr_ew = set(eligible)

        # DEM turnover
        if prev_dem:
            dem_to = (len(prev_dem - curr_dem) + len(curr_dem - prev_dem)) / (2 * K)
        else:
            dem_to = 1.0

        # EW-all turnover
        if prev_ew:
            n_max = max(len(prev_ew), len(curr_ew), 1)
            ew_to = (len(prev_ew - curr_ew) + len(curr_ew - prev_ew)) / (2 * n_max)
        else:
            ew_to = 1.0

        # Returns
        dem_rets = []
        for tk in dem30:
            p0 = _get_price(store, tk, start)
            p1 = _get_price(store, tk, end)
            if p0 and p1 and p0 > 0:
                dem_rets.append((tk, (p1 - p0) / p0))

        ew_rets = []
        for tk in eligible:
            p0 = _get_price(store, tk, start)
            p1 = _get_price(store, tk, end)
            if p0 and p1 and p0 > 0:
                ew_rets.append((tk, (p1 - p0) / p0))

        xbi_p0 = _get_price(store, "XBI", start)
        xbi_p1 = _get_price(store, "XBI", end)
        if not xbi_p0 or not xbi_p1 or not dem_rets:
            prev_dem = curr_dem
            prev_ew = curr_ew
            continue

        xbi_ret = (xbi_p1 - xbi_p0) / xbi_p0

        dem_gross = sum(r for _, r in dem_rets) / len(dem_rets)
        dem_cost = dem_to * COST_BPS * 2
        dem_net = dem_gross - dem_cost

        ew_gross = sum(r for _, r in ew_rets) / len(ew_rets) if ew_rets else 0
        ew_cost = ew_to * COST_BPS * 2
        ew_net = ew_gross - ew_cost

        # Per-name DEM returns for tail analysis
        dem_name_rets = {tk: r for tk, r in dem_rets}

        monthly.append(
            {
                "date": start,
                "dem_net": dem_net,
                "ew_net": ew_net,
                "xbi": xbi_ret,
                "dem_name_rets": dem_name_rets,
                "live": start >= LIVE_START,
            }
        )

        prev_dem = curr_dem
        prev_ew = curr_ew

    return monthly


def _compute_stats(rets, xbi_rets, label):
    n = len(rets)
    if n == 0:
        return {"label": label, "n": 0}
    years = n / 12
    rf_m = (1 + RF_ANNUAL) ** (1 / 12) - 1

    cum = 1.0
    cum_xbi = 1.0
    for r, x in zip(rets, xbi_rets):
        cum *= 1 + r
        cum_xbi *= 1 + x

    mean_r = sum(rets) / n
    excess = [r - x for r, x in zip(rets, xbi_rets)]
    mean_ex = sum(excess) / n
    hit = sum(1 for e in excess if e > 0) / n

    vol = math.sqrt(sum((r - mean_r) ** 2 for r in rets) / max(n - 1, 1)) * math.sqrt(12)
    down = [min(r - rf_m, 0) for r in rets]
    down_vol = math.sqrt(sum(d**2 for d in down) / max(n - 1, 1)) * math.sqrt(12)

    ex_var = sum((e - mean_ex) ** 2 for e in excess) / max(n - 1, 1)
    te = math.sqrt(ex_var) * math.sqrt(12)
    t = mean_ex / math.sqrt(ex_var / n) if ex_var > 0 else 0

    ann = (cum ** (1 / years) - 1) if years >= 1 else cum - 1
    sharpe = (ann - RF_ANNUAL) / vol if vol > 0 else 0
    sortino = (ann - RF_ANNUAL) / down_vol if down_vol > 0 else 0
    ir = mean_ex * 12 / te if te > 0 else 0

    # Drawdown
    peak = 1.0
    max_dd = 0
    c = 1.0
    dd_sq = []
    for r in rets:
        c *= 1 + r
        if c > peak:
            peak = c
        dd = (c - peak) / peak
        dd_sq.append((dd * 100) ** 2)
        if dd < max_dd:
            max_dd = dd

    ulcer = math.sqrt(sum(dd_sq) / len(dd_sq)) if dd_sq else 0
    calmar = ann * 100 / abs(max_dd * 100) if max_dd != 0 else 0

    return {
        "label": label,
        "n": n,
        "cum": round((cum - 1) * 100, 1),
        "excess": round((cum - 1) * 100 - (cum_xbi - 1) * 100, 1),
        "ann": round(ann * 100, 1),
        "mo_ex": round(mean_ex * 100, 2),
        "t": round(t, 2),
        "hit": round(hit * 100, 0),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "ir": round(ir, 2),
        "max_dd": round(max_dd * 100, 1),
        "ulcer": round(ulcer, 1),
        "calmar": round(calmar, 2),
    }


def run_sweep():
    store = PriceStore(str(REPO_ROOT / "data" / "prices.db"))
    monthly = _build_sleeve_series(store)

    print("CAPITAL ALLOCATION SIZING SWEEP")
    print(f"Net of {COST_BPS * 10000:.0f} bps one-way")
    n_hist = sum(1 for m in monthly if not m["live"])
    n_live = sum(1 for m in monthly if m["live"])
    print(f"Periods: {len(monthly)} ({n_hist} hist + {n_live} live)")
    print("=" * 130)

    # Compute name-level contributions for tail analysis
    # Track biggest DEM contributor across the series
    dem_name_total = {}
    for m in monthly:
        n_dem = len(m["dem_name_rets"])
        for tk, r in m["dem_name_rets"].items():
            dem_name_total[tk] = dem_name_total.get(tk, 0) + r / max(n_dem, 1)

    sorted_dem_names = sorted(dem_name_total.items(), key=lambda x: -x[1])
    biggest_dem = sorted_dem_names[0][0] if sorted_dem_names else None
    top3_dem = {tk for tk, _ in sorted_dem_names[:3]}

    alloc_points = [i / 10 for i in range(11)]  # 0.0 to 1.0

    for core_label, core_key in [("XBI", "xbi"), ("EW-All", "ew_net")]:
        print(f"\nCORE = {core_label}")

        for period_label, filt in [("LIVE", lambda m: m["live"]), ("HISTORICAL (pseudo-PIT)", lambda m: not m["live"])]:
            subset = [m for m in monthly if filt(m)]
            if not subset:
                continue

            print(f"\n  {period_label} ({len(subset)} months)")
            header = (
                f"  {'DEM%':>5s} {'Net%':>7s} {'Exc':>7s} {'MoEx':>6s} {'t':>5s}"
                f" {'Hit':>4s} {'Sh':>5s} {'So':>5s} {'IR':>5s}"
                f" {'DD':>6s} {'Ulc':>5s} {'Cal':>5s}"
                f" {'Ex1':>7s} {'Ex3':>7s} {'ExMA':>7s}"
            )
            print(header)
            print("  " + "-" * 110)

            for w_dem in alloc_points:
                w_core = 1.0 - w_dem

                # Blend returns
                blended = []
                xbi_list = []
                for m in subset:
                    core_ret = m[core_key]
                    port_ret = w_dem * m["dem_net"] + w_core * core_ret
                    blended.append(port_ret)
                    xbi_list.append(m["xbi"])

                s = _compute_stats(blended, xbi_list, f"{w_dem:.0%} DEM")

                # Ex-tail: replace DEM portion with DEM-ex-biggest
                ex1_rets = []
                ex3_rets = []
                exma_rets = []
                for m in subset:
                    nr = m["dem_name_rets"]
                    n_dem = len(nr)
                    if n_dem == 0:
                        ex1_rets.append(w_core * m[core_key])
                        ex3_rets.append(w_core * m[core_key])
                        exma_rets.append(w_core * m[core_key])
                        continue

                    # Ex biggest
                    nr_ex1 = {tk: r for tk, r in nr.items() if tk != biggest_dem}
                    dem_ex1 = sum(nr_ex1.values()) / n_dem if nr_ex1 else 0
                    ex1_rets.append(w_dem * dem_ex1 + w_core * m[core_key])

                    # Ex top 3
                    nr_ex3 = {tk: r for tk, r in nr.items() if tk not in top3_dem}
                    dem_ex3 = sum(nr_ex3.values()) / n_dem if nr_ex3 else 0
                    ex3_rets.append(w_dem * dem_ex3 + w_core * m[core_key])

                    # Ex M&A (cap at 200%)
                    nr_capped = {tk: min(r, 2.0) for tk, r in nr.items()}
                    dem_exma = sum(nr_capped.values()) / n_dem
                    exma_rets.append(w_dem * dem_exma + w_core * m[core_key])

                cum_ex1 = 1.0
                cum_ex3 = 1.0
                cum_exma = 1.0
                for r1, r3, rma in zip(ex1_rets, ex3_rets, exma_rets):
                    cum_ex1 *= 1 + r1
                    cum_ex3 *= 1 + r3
                    cum_exma *= 1 + rma

                pct = f"{w_dem * 100:.0f}%"
                print(
                    f"  {pct:>5s}"
                    f" {s['cum']:>+6.1f}%"
                    f" {s['excess']:>+6.1f}pp"
                    f" {s['mo_ex']:>+5.2f}"
                    f" {s['t']:>4.2f}"
                    f" {s['hit']:>3.0f}%"
                    f" {s['sharpe']:>4.2f}"
                    f" {s['sortino']:>4.2f}"
                    f" {s['ir']:>4.2f}"
                    f" {s['max_dd']:>5.1f}%"
                    f" {s['ulcer']:>4.1f}"
                    f" {s['calmar']:>4.2f}"
                    f" {(cum_ex1 - 1) * 100:>+6.1f}%"
                    f" {(cum_ex3 - 1) * 100:>+6.1f}%"
                    f" {(cum_exma - 1) * 100:>+6.1f}%"
                )

    # Verdict
    print("\n" + "=" * 130)
    print("RECOMMENDATION")
    print("=" * 130)

    # Find best live allocation for each core
    for core_label, core_key in [("XBI", "xbi"), ("EW-All", "ew_net")]:
        live_sub = [m for m in monthly if m["live"]]
        if not live_sub:
            continue

        print(f"\n  Core = {core_label}:")

        best_w = 0
        best_sharpe = -999
        for w_dem in alloc_points:
            w_core = 1.0 - w_dem
            blended = [w_dem * m["dem_net"] + w_core * m[core_key] for m in live_sub]
            xbi_list = [m["xbi"] for m in live_sub]
            s = _compute_stats(blended, xbi_list, "")
            if s.get("sharpe", -999) > best_sharpe:
                best_sharpe = s["sharpe"]
                best_w = w_dem

        print(f"    Best live Sharpe: {best_sharpe:.2f} at {best_w * 100:.0f}% DEM")

        # Show the recommended allocation
        for w_label, w in [("Conservative (20%)", 0.20), ("Moderate (30%)", 0.30), ("Best Sharpe", best_w)]:
            blended = [w * m["dem_net"] + (1 - w) * m[core_key] for m in live_sub]
            xbi_list = [m["xbi"] for m in live_sub]
            s = _compute_stats(blended, xbi_list, w_label)
            print(f"    {w_label:>20s}: excess {s['excess']:>+.1f}pp  Sharpe {s['sharpe']:.2f}  DD {s['max_dd']:.1f}%")


if __name__ == "__main__":
    run_sweep()
