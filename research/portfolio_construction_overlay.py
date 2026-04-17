#!/usr/bin/env python3
"""Portfolio Construction Overlay Study.

Tests pure Top-30, core+overlay, capped, vol-scaled, and hybrid constructions.
All results net of 50bps one-way. Ex-tail metrics are first-class outputs.

Usage:
    python research/portfolio_construction_overlay.py
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


def _get_returns(store, tickers, start, end):
    """Get {ticker: return} for a list of tickers."""
    rets = {}
    for tk in tickers:
        p0 = _get_price(store, tk, start)
        p1 = _get_price(store, tk, end)
        if p0 and p1 and p0 > 0:
            rets[tk] = (p1 - p0) / p0
    return rets


def _weighted_return(weights, returns):
    """Compute portfolio return from {ticker: weight} and {ticker: return}."""
    total = 0.0
    w_sum = 0.0
    for tk, w in weights.items():
        if tk in returns:
            total += w * returns[tk]
            w_sum += w
    return total / w_sum if w_sum > 0 else 0.0


def _turnover(prev_weights, curr_weights):
    """One-way turnover between two weight dicts."""
    all_tickers = set(prev_weights) | set(curr_weights)
    total_change = sum(abs(curr_weights.get(tk, 0) - prev_weights.get(tk, 0)) for tk in all_tickers)
    return total_change / 2  # one-way


# ======================================================================
# Construction definitions
# ======================================================================


def build_constructions(store):
    """Build monthly series for all portfolio constructions."""
    pit_dates = sorted(
        [
            d
            for d in os.listdir(REPO_ROOT / "data" / "snapshots_pit_v2")
            if len(d) == 10 and (REPO_ROOT / "data" / "snapshots_pit_v2" / d / "rankings.csv").exists()
        ]
    )

    constructions = {
        "DEM Top-30 EW": [],
        "EW All Eligible": [],
        "70/30 Core+DEM": [],
        "60/40 Core+DEM": [],
        "50/50 Core+DEM": [],
        "DEM Cap 5%": [],
        "DEM Cap 7.5%": [],
        "DEM Cap 10%": [],
        "70/30 Core+Cap5% DEM": [],
    }

    prev_dem: Set[str] = set()
    prev_weights = {name: {} for name in constructions}

    for i in range(len(pit_dates) - 1):
        start = pit_dates[i]
        end = pit_dates[i + 1]

        ranked = _load_ranked(start)
        eligible = _load_eligible(start)
        if not ranked or not eligible:
            continue

        # DEM Top-30 with buffer
        dem30 = _select_with_buffer(ranked, prev_dem)
        prev_dem = set(dem30)

        # Get all returns
        all_tickers = set(dem30) | set(eligible)
        rets = _get_returns(store, all_tickers, start, end)

        xbi_p0 = _get_price(store, "XBI", start)
        xbi_p1 = _get_price(store, "XBI", end)
        if not xbi_p0 or not xbi_p1:
            continue
        xbi_ret = (xbi_p1 - xbi_p0) / xbi_p0
        is_live = start >= LIVE_START

        # Build weight dicts for each construction
        n_elig = len(eligible)
        n_dem = len(dem30)

        # 1. DEM Top-30 EW

        # 2. EW All Eligible

        # 3-5. Core + Overlay
        for overlay_pct, name in [(0.30, "70/30 Core+DEM"), (0.40, "60/40 Core+DEM"), (0.50, "50/50 Core+DEM")]:
            core_pct = 1.0 - overlay_pct
            weights = {}
            # Core: EW all eligible
            for tk in eligible:
                weights[tk] = weights.get(tk, 0) + core_pct / n_elig
            # Overlay: EW DEM Top-30
            for tk in dem30:
                weights[tk] = weights.get(tk, 0) + overlay_pct / n_dem
            # Normalize
            total_w = sum(weights.values())
            if total_w > 0:
                weights = {tk: w / total_w for tk, w in weights.items()}

            to = _turnover(prev_weights[name], weights)
            cost = to * COST_BPS * 2
            gross = _weighted_return(weights, rets)
            constructions[name].append(
                {
                    "date": start,
                    "gross": gross,
                    "net": gross - cost,
                    "xbi": xbi_ret,
                    "one_way": to,
                    "cost": cost,
                    "live": is_live,
                    "weights": weights,
                    "name_rets": rets,
                    "n_names": len(weights),
                }
            )
            prev_weights[name] = weights

        # 6-8. DEM with position caps
        for cap, name in [(0.05, "DEM Cap 5%"), (0.075, "DEM Cap 7.5%"), (0.10, "DEM Cap 10%")]:
            weights = {}
            base_w = 1.0 / n_dem if n_dem > 0 else 0
            for tk in dem30:
                weights[tk] = min(base_w, cap)
            # Renormalize
            total_w = sum(weights.values())
            if total_w > 0:
                weights = {tk: w / total_w for tk, w in weights.items()}

            to = _turnover(prev_weights[name], weights)
            cost = to * COST_BPS * 2
            gross = _weighted_return(weights, rets)
            constructions[name].append(
                {
                    "date": start,
                    "gross": gross,
                    "net": gross - cost,
                    "xbi": xbi_ret,
                    "one_way": to,
                    "cost": cost,
                    "live": is_live,
                    "weights": weights,
                    "name_rets": rets,
                    "n_names": len(weights),
                }
            )
            prev_weights[name] = weights

        # 9. 70/30 Core + Capped DEM
        weights = {}
        core_pct = 0.70
        overlay_pct = 0.30
        for tk in eligible:
            weights[tk] = weights.get(tk, 0) + core_pct / n_elig
        cap = 0.05
        dem_w = {}
        for tk in dem30:
            dem_w[tk] = min(1.0 / n_dem, cap)
        dem_total = sum(dem_w.values())
        if dem_total > 0:
            for tk, w in dem_w.items():
                weights[tk] = weights.get(tk, 0) + overlay_pct * w / dem_total
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {tk: w / total_w for tk, w in weights.items()}

        name = "70/30 Core+Cap5% DEM"
        to = _turnover(prev_weights[name], weights)
        cost = to * COST_BPS * 2
        gross = _weighted_return(weights, rets)
        constructions[name].append(
            {
                "date": start,
                "gross": gross,
                "net": gross - cost,
                "xbi": xbi_ret,
                "one_way": to,
                "cost": cost,
                "live": is_live,
                "weights": weights,
                "name_rets": rets,
                "n_names": len(weights),
            }
        )
        prev_weights[name] = weights

        # 1 & 2: Simple EW constructions
        for cname, tickers in [("DEM Top-30 EW", dem30), ("EW All Eligible", eligible)]:
            n = len(tickers)
            w = {tk: 1.0 / n for tk in tickers} if n > 0 else {}
            to = _turnover(prev_weights[cname], w)
            cost = to * COST_BPS * 2
            gross = _weighted_return(w, rets)
            constructions[cname].append(
                {
                    "date": start,
                    "gross": gross,
                    "net": gross - cost,
                    "xbi": xbi_ret,
                    "one_way": to,
                    "cost": cost,
                    "live": is_live,
                    "weights": w,
                    "name_rets": rets,
                    "n_names": len(w),
                }
            )
            prev_weights[cname] = w

    return constructions


# ======================================================================
# Metrics
# ======================================================================


def compute_full_metrics(series, label):
    if not series:
        return {"label": label, "n": 0}
    n = len(series)
    years = n / 12

    nets = [m["net"] for m in series]
    xbis = [m["xbi"] for m in series]
    excess = [net - xbi for net, xbi in zip(nets, xbis)]

    cum_net = 1.0
    cum_xbi = 1.0
    for m in series:
        cum_net *= 1 + m["net"]
        cum_xbi *= 1 + m["xbi"]

    mean_net = sum(nets) / n
    mean_ex = sum(excess) / n
    hit = sum(1 for e in excess if e > 0) / n

    vol = math.sqrt(sum((r - mean_net) ** 2 for r in nets) / max(n - 1, 1)) * math.sqrt(12)
    rf_m = (1 + RF_ANNUAL) ** (1 / 12) - 1
    down = [min(r - rf_m, 0) for r in nets]
    down_vol = math.sqrt(sum(d**2 for d in down) / max(n - 1, 1)) * math.sqrt(12)

    ex_var = sum((e - mean_ex) ** 2 for e in excess) / max(n - 1, 1)
    te = math.sqrt(ex_var) * math.sqrt(12)
    t = mean_ex / math.sqrt(ex_var / n) if ex_var > 0 else 0

    ann = (cum_net ** (1 / years) - 1) if years >= 1 else cum_net - 1
    sharpe = (ann - RF_ANNUAL) / vol if vol > 0 else 0
    sortino = (ann - RF_ANNUAL) / down_vol if down_vol > 0 else 0
    ir = mean_ex * 12 / te if te > 0 else 0

    # Drawdown
    peak = 1.0
    max_dd = 0
    c = 1.0
    for m in series:
        c *= 1 + m["net"]
        if c > peak:
            peak = c
        dd = (c - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # Turnover
    tos = [m["one_way"] for m in series[1:]]
    avg_to = sum(tos) / len(tos) if tos else 0
    total_cost = sum(m["cost"] for m in series)

    # Concentration / tail metrics
    name_contrib = {}
    for m in series:
        w = m["weights"]
        for tk, weight in w.items():
            ret = m["name_rets"].get(tk, 0)
            contrib = weight * ret
            name_contrib[tk] = name_contrib.get(tk, 0) + contrib

    sorted_contrib = sorted(name_contrib.items(), key=lambda x: -x[1])
    total_contrib = sum(v for _, v in sorted_contrib)

    top1_share = sorted_contrib[0][1] / total_contrib * 100 if total_contrib and sorted_contrib else 0
    top3_share = sum(v for _, v in sorted_contrib[:3]) / total_contrib * 100 if total_contrib else 0
    top5_share = sum(v for _, v in sorted_contrib[:5]) / total_contrib * 100 if total_contrib else 0

    # Ex-tail: cap biggest winner at 0
    biggest = sorted_contrib[0][0] if sorted_contrib else None
    cum_ex1 = 1.0
    for m in series:
        w = m["weights"]
        adj_ret = sum(w.get(tk, 0) * (m["name_rets"].get(tk, 0) if tk != biggest else 0) for tk in w)
        s = sum(w.values())
        if s > 0:
            adj_ret /= s
        cum_ex1 *= 1 + adj_ret - m["cost"]

    # Ex top 3
    top3_names = {tk for tk, _ in sorted_contrib[:3]}
    cum_ex3 = 1.0
    for m in series:
        w = m["weights"]
        adj_ret = sum(w.get(tk, 0) * (m["name_rets"].get(tk, 0) if tk not in top3_names else 0) for tk in w)
        s = sum(w.values())
        if s > 0:
            adj_ret /= s
        cum_ex3 *= 1 + adj_ret - m["cost"]

    # Ex M&A (months where any name >200%)
    cum_exma = 1.0
    for m in series:
        w = m["weights"]
        adj_rets = {tk: min(m["name_rets"].get(tk, 0), 2.0) for tk in w}
        adj_ret = sum(w.get(tk, 0) * adj_rets.get(tk, 0) for tk in w)
        s = sum(w.values())
        if s > 0:
            adj_ret /= s
        cum_exma *= 1 + adj_ret - m["cost"]

    avg_names = sum(m["n_names"] for m in series) / n

    return {
        "label": label,
        "n": n,
        "cum_net": round((cum_net - 1) * 100, 1),
        "net_excess": round((cum_net - 1) * 100 - (cum_xbi - 1) * 100, 1),
        "ann": round(ann * 100, 1),
        "monthly_ex": round(mean_ex * 100, 2),
        "t": round(t, 2),
        "hit": round(hit * 100, 0),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "ir": round(ir, 2),
        "max_dd": round(max_dd * 100, 1),
        "avg_to": round(avg_to * 100, 1),
        "total_cost": round(total_cost * 100, 1),
        "avg_names": round(avg_names, 0),
        "top1": round(top1_share, 0),
        "top3": round(top3_share, 0),
        "top5": round(top5_share, 0),
        "cum_ex1": round((cum_ex1 - 1) * 100, 1),
        "cum_ex3": round((cum_ex3 - 1) * 100, 1),
        "cum_exma": round((cum_exma - 1) * 100, 1),
    }


# ======================================================================
# Main
# ======================================================================


def run_study():
    store = PriceStore(str(REPO_ROOT / "data" / "prices.db"))
    constructions = build_constructions(store)

    print("PORTFOLIO CONSTRUCTION OVERLAY STUDY")
    print(f"Net of {COST_BPS * 10000:.0f} bps one-way")
    print("=" * 120)

    order = [
        "DEM Top-30 EW",
        "EW All Eligible",
        "70/30 Core+DEM",
        "60/40 Core+DEM",
        "50/50 Core+DEM",
        "DEM Cap 5%",
        "DEM Cap 7.5%",
        "DEM Cap 10%",
        "70/30 Core+Cap5% DEM",
    ]

    for period_label, filt in [
        ("LIVE (Oct 2024+)", lambda m: m["live"]),
        ("HISTORICAL (pseudo-PIT)", lambda m: not m["live"]),
    ]:
        print(f"\n{period_label}")
        header = (
            f"{'Construction':>25s} {'Net%':>7s} {'Exc':>7s} {'MoEx':>6s} {'t':>5s}"
            f" {'Hit':>4s} {'Sh':>5s} {'So':>5s} {'IR':>5s} {'DD':>6s}"
            f" {'TO':>5s} {'#':>4s} {'T1%':>4s} {'T3%':>4s} {'T5%':>4s}"
            f" {'Ex1':>7s} {'Ex3':>7s} {'ExMA':>7s}"
        )
        print(header)
        print("-" * 120)

        for name in order:
            subset = [m for m in constructions.get(name, []) if filt(m)]
            if not subset:
                continue
            r = compute_full_metrics(subset, name)
            if r["n"] == 0:
                continue
            print(
                f"{name:>25s}"
                f" {r['cum_net']:>+6.1f}%"
                f" {r['net_excess']:>+6.1f}pp"
                f" {r['monthly_ex']:>+5.2f}"
                f" {r['t']:>4.2f}"
                f" {r['hit']:>3.0f}%"
                f" {r['sharpe']:>4.2f}"
                f" {r['sortino']:>4.2f}"
                f" {r['ir']:>4.2f}"
                f" {r['max_dd']:>5.1f}%"
                f" {r['avg_to']:>4.1f}%"
                f" {r['avg_names']:>3.0f}"
                f" {r['top1']:>3.0f}%"
                f" {r['top3']:>3.0f}%"
                f" {r['top5']:>3.0f}%"
                f" {r['cum_ex1']:>+6.1f}%"
                f" {r['cum_ex3']:>+6.1f}%"
                f" {r['cum_exma']:>+6.1f}%"
            )

    # Verdict
    print("\n" + "=" * 120)
    print("VERDICT")
    print("=" * 120)

    live_results = {}
    for name in order:
        subset = [m for m in constructions.get(name, []) if m["live"]]
        if subset:
            live_results[name] = compute_full_metrics(subset, name)

    dem = live_results.get("DEM Top-30 EW", {})
    best_overlay = None
    best_overlay_score = -999

    for name, r in live_results.items():
        if name in ("DEM Top-30 EW", "EW All Eligible"):
            continue
        # Score: excess retention + dd improvement + ex-tail improvement
        excess_retention = r.get("net_excess", 0) / max(dem.get("net_excess", 1), 1)
        dd_improvement = (dem.get("max_dd", 0) - r.get("max_dd", 0)) / abs(dem.get("max_dd", -1))
        extail_improvement = r.get("cum_exma", 0) - dem.get("cum_exma", 0)

        score = excess_retention * 0.4 + dd_improvement * 0.3 + (1 if extail_improvement > 0 else 0) * 0.3
        if score > best_overlay_score:
            best_overlay_score = score
            best_overlay = name

    if best_overlay and dem:
        bo = live_results[best_overlay]
        print(f"\n  Best overlay: {best_overlay}")
        print("    vs DEM Top-30:")
        print(
            f"    Net excess:    {dem['net_excess']:+.1f}pp → {bo['net_excess']:+.1f}pp ({bo['net_excess'] - dem['net_excess']:+.1f}pp)"
        )
        print(f"    Max drawdown:  {dem['max_dd']:.1f}% → {bo['max_dd']:.1f}%")
        print(f"    Top-5 share:   {dem['top5']:.0f}% → {bo['top5']:.0f}%")
        print(f"    Ex-M&A return: {dem['cum_exma']:+.1f}% → {bo['cum_exma']:+.1f}%")
        print(f"    Sharpe:        {dem['sharpe']:.2f} → {bo['sharpe']:.2f}")
        print(f"    Avg names:     {dem['avg_names']:.0f} → {bo['avg_names']:.0f}")


if __name__ == "__main__":
    run_study()
