#!/usr/bin/env python3
"""Advanced Performance Analytics Pack.

Reusable analytics for all future backtests and live-performance reviews.
Reports net-of-cost results first. Separates historical/pseudo-PIT from live.

Usage:
    python research/advanced_performance_analytics.py
    python research/advanced_performance_analytics.py --cost-bps 50
"""

from __future__ import annotations

import json
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
COST_SCENARIOS = {"Low (25bps)": 0.0025, "Base (50bps)": 0.0050, "High (100bps)": 0.0100}
DEFAULT_COST = 0.0050
RF_ANNUAL = 0.045  # risk-free rate for Sharpe


# ======================================================================
# Data loading
# ======================================================================


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


def _select_with_buffer(ranked, prev_holdings, buffer=30):
    if not ranked:
        return []
    core = set(ranked[:K])
    buf_zone = set(ranked[: K + buffer]) if buffer > 0 else core
    kept = [tk for tk in ranked if tk in prev_holdings and tk in buf_zone]
    for tk in ranked:
        if len(kept) >= K:
            break
        if tk not in set(kept) and tk in core:
            kept.append(tk)
    return kept[:K]


def build_monthly_series(store, cost_bps=DEFAULT_COST):
    """Build complete monthly return series with per-name detail."""
    pit_dates = sorted(
        [
            d
            for d in os.listdir(REPO_ROOT / "data" / "snapshots_pit_v2")
            if len(d) == 10 and (REPO_ROOT / "data" / "snapshots_pit_v2" / d / "rankings.csv").exists()
        ]
    )

    prev_holdings: Set[str] = set()
    monthly = []

    for i in range(len(pit_dates) - 1):
        start = pit_dates[i]
        end = pit_dates[i + 1]
        ranked = _load_ranked(start)
        if not ranked:
            continue

        portfolio = _select_with_buffer(ranked, prev_holdings)
        curr_set = set(portfolio)

        if prev_holdings:
            exited = prev_holdings - curr_set
            entered = curr_set - prev_holdings
            one_way = (len(exited) + len(entered)) / (2 * K)
        else:
            one_way = 1.0
            exited = set()
            entered = curr_set

        # Per-name returns
        name_rets = {}
        for tk in portfolio:
            p0 = _get_price(store, tk, start)
            p1 = _get_price(store, tk, end)
            if p0 and p1 and p0 > 0:
                name_rets[tk] = (p1 - p0) / p0

        if not name_rets:
            prev_holdings = curr_set
            continue

        gross = sum(name_rets.values()) / len(name_rets)
        cost_drag = one_way * cost_bps * 2
        net = gross - cost_drag

        xbi_p0 = _get_price(store, "XBI", start)
        xbi_p1 = _get_price(store, "XBI", end)
        if not xbi_p0 or not xbi_p1:
            prev_holdings = curr_set
            continue
        xbi_ret = (xbi_p1 - xbi_p0) / xbi_p0

        monthly.append(
            {
                "date": start,
                "end": end,
                "gross": gross,
                "net": net,
                "xbi": xbi_ret,
                "cost_drag": cost_drag,
                "one_way": one_way,
                "name_rets": name_rets,
                "portfolio": list(portfolio),
                "n_exited": len(exited),
                "n_entered": len(entered),
                "live": start >= LIVE_START,
            }
        )
        prev_holdings = curr_set

    return monthly


# ======================================================================
# A) Core return and excess metrics
# ======================================================================


def core_metrics(series, label=""):
    if not series:
        return {}
    n = len(series)
    years = n / 12
    rf_monthly = (1 + RF_ANNUAL) ** (1 / 12) - 1

    net_rets = [m["net"] for m in series]
    xbi_rets = [m["xbi"] for m in series]
    excess = [m["net"] - m["xbi"] for m in series]

    cum_net = 1.0
    cum_xbi = 1.0
    for m in series:
        cum_net *= 1 + m["net"]
        cum_xbi *= 1 + m["xbi"]

    mean_net = sum(net_rets) / n
    mean_xbi = sum(xbi_rets) / n
    mean_ex = sum(excess) / n
    hit = sum(1 for e in excess if e > 0) / n

    vol = math.sqrt(sum((r - mean_net) ** 2 for r in net_rets) / max(n - 1, 1)) * math.sqrt(12)
    down_rets = [min(r - rf_monthly, 0) for r in net_rets]
    downside_vol = math.sqrt(sum(d**2 for d in down_rets) / max(n - 1, 1)) * math.sqrt(12)

    ex_var = sum((e - mean_ex) ** 2 for e in excess) / max(n - 1, 1)
    tracking_error = math.sqrt(ex_var) * math.sqrt(12)
    t_stat = mean_ex / math.sqrt(ex_var / n) if ex_var > 0 else 0

    ann_net = (cum_net ** (1 / years) - 1) if years >= 1 else cum_net - 1
    ann_xbi = (cum_xbi ** (1 / years) - 1) if years >= 1 else cum_xbi - 1
    sharpe = (ann_net - RF_ANNUAL) / vol if vol > 0 else 0
    sortino = (ann_net - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0
    info_ratio = mean_ex * 12 / tracking_error if tracking_error > 0 else 0

    # Beta and alpha vs XBI
    cov = sum((net_rets[i] - mean_net) * (xbi_rets[i] - mean_xbi) for i in range(n)) / max(n - 1, 1)
    xbi_var = sum((x - mean_xbi) ** 2 for x in xbi_rets) / max(n - 1, 1)
    beta = cov / xbi_var if xbi_var > 0 else 1.0
    alpha_monthly = mean_net - rf_monthly - beta * (mean_xbi - rf_monthly)
    alpha_annual = alpha_monthly * 12

    return {
        "label": label,
        "n": n,
        "years": round(years, 1),
        "cum_net": round((cum_net - 1) * 100, 1),
        "cum_xbi": round((cum_xbi - 1) * 100, 1),
        "net_excess": round((cum_net - 1) * 100 - (cum_xbi - 1) * 100, 1),
        "ann_net": round(ann_net * 100, 1),
        "ann_xbi": round(ann_xbi * 100, 1),
        "monthly_excess": round(mean_ex * 100, 2),
        "t_stat": round(t_stat, 2),
        "hit_rate": round(hit * 100, 0),
        "volatility": round(vol * 100, 1),
        "downside_vol": round(downside_vol * 100, 1),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "info_ratio": round(info_ratio, 2),
        "tracking_error": round(tracking_error * 100, 1),
        "beta": round(beta, 2),
        "alpha_annual": round(alpha_annual * 100, 1),
    }


# ======================================================================
# B) Drawdown and path-risk metrics
# ======================================================================


def drawdown_metrics(series):
    if not series:
        return {}

    cum = 1.0
    peak = 1.0
    current_dd_start = None
    max_dd = 0
    dd_history = []

    for i, m in enumerate(series):
        cum *= 1 + m["net"]
        if cum > peak:
            if current_dd_start is not None and dd_history:
                dd_history[-1]["recovery"] = m["date"]
            peak = cum
            current_dd_start = None
        dd = (cum - peak) / peak
        if dd < 0 and current_dd_start is None:
            current_dd_start = m["date"]
            dd_history.append({"start": m["date"], "trough": m["date"], "trough_dd": dd, "recovery": None})
        if dd < 0 and dd_history:
            if dd < dd_history[-1]["trough_dd"]:
                dd_history[-1]["trough"] = m["date"]
                dd_history[-1]["trough_dd"] = dd
        if dd < max_dd:
            max_dd = dd

    # Sort by depth
    dd_history.sort(key=lambda d: d["trough_dd"])

    # Time underwater
    underwater_months = 0
    cum2 = 1.0
    peak2 = 1.0
    longest_uw = 0
    current_uw = 0
    for m in series:
        cum2 *= 1 + m["net"]
        if cum2 >= peak2:
            peak2 = cum2
            longest_uw = max(longest_uw, current_uw)
            current_uw = 0
        else:
            current_uw += 1
            underwater_months += 1
    longest_uw = max(longest_uw, current_uw)

    # Ulcer index
    dd_sq = []
    cum3 = 1.0
    peak3 = 1.0
    for m in series:
        cum3 *= 1 + m["net"]
        if cum3 > peak3:
            peak3 = cum3
        dd_pct = ((cum3 - peak3) / peak3) * 100
        dd_sq.append(dd_pct**2)
    ulcer = math.sqrt(sum(dd_sq) / len(dd_sq)) if dd_sq else 0

    ann_ret = core_metrics(series).get("ann_net", 0)
    calmar = ann_ret / abs(max_dd * 100) if max_dd != 0 else 0

    # Worst excess periods
    excess_list = [m["net"] - m["xbi"] for m in series]
    worst_1m = min(excess_list) if excess_list else 0

    # 3-month rolling worst
    worst_3m = 0
    for i in range(len(series) - 2):
        cum_e = 1.0
        cum_x = 1.0
        for j in range(3):
            cum_e *= 1 + series[i + j]["net"]
            cum_x *= 1 + series[i + j]["xbi"]
        exc_3m = (cum_e - 1) - (cum_x - 1)
        worst_3m = min(worst_3m, exc_3m)

    # Rolling 12-month win rate
    rolling_12_wins = 0
    rolling_12_total = 0
    for i in range(len(series) - 11):
        w = series[i : i + 12]
        wd = 1.0
        wx = 1.0
        for m in w:
            wd *= 1 + m["net"]
            wx *= 1 + m["xbi"]
        if wd > wx:
            rolling_12_wins += 1
        rolling_12_total += 1

    return {
        "max_drawdown": round(max_dd * 100, 1),
        "top5_drawdowns": [
            {
                "start": d["start"],
                "trough": d["trough"],
                "depth": round(d["trough_dd"] * 100, 1),
                "recovery": d["recovery"],
            }
            for d in dd_history[:5]
        ],
        "avg_underwater_months": round(underwater_months / max(len(dd_history), 1), 1),
        "longest_underwater": longest_uw,
        "ulcer_index": round(ulcer, 2),
        "calmar": round(calmar, 2),
        "worst_1m_excess": round(worst_1m * 100, 1),
        "worst_3m_excess": round(worst_3m * 100, 1),
        "rolling_12m_win_rate": f"{rolling_12_wins}/{rolling_12_total}" if rolling_12_total > 0 else "n/a",
    }


# ======================================================================
# C-D) Attribution
# ======================================================================


def attribution(series, label=""):
    if not series:
        return {}

    # Name-level
    name_contrib = {}
    for m in series:
        n_names = len(m["name_rets"])
        for tk, ret in m["name_rets"].items():
            if tk not in name_contrib:
                name_contrib[tk] = {"total": 0, "months": 0, "best": -999, "worst": 999, "rets": []}
            contrib = ret / n_names  # EW contribution
            name_contrib[tk]["total"] += contrib
            name_contrib[tk]["months"] += 1
            name_contrib[tk]["best"] = max(name_contrib[tk]["best"], ret)
            name_contrib[tk]["worst"] = min(name_contrib[tk]["worst"], ret)
            name_contrib[tk]["rets"].append(ret)

    sorted_names = sorted(name_contrib.items(), key=lambda x: -x[1]["total"])
    total_contrib = sum(v["total"] for _, v in sorted_names)

    top10 = [
        {
            "ticker": tk,
            "contrib_pp": round(v["total"] * 100, 1),
            "months": v["months"],
            "best": round(v["best"] * 100, 0),
            "worst": round(v["worst"] * 100, 0),
            "pct_of_total": round(v["total"] / total_contrib * 100, 1) if total_contrib else 0,
        }
        for tk, v in sorted_names[:10]
    ]
    bot10 = [
        {
            "ticker": tk,
            "contrib_pp": round(v["total"] * 100, 1),
            "months": v["months"],
            "best": round(v["best"] * 100, 0),
            "worst": round(v["worst"] * 100, 0),
        }
        for tk, v in sorted_names[-10:]
    ]

    # Month-level
    month_sorted = sorted(series, key=lambda m: -m["net"])
    best_months = [
        {
            "date": m["date"],
            "net": round(m["net"] * 100, 1),
            "top_name": max(m["name_rets"].items(), key=lambda x: x[1])[0] if m["name_rets"] else "-",
            "top_ret": round(max(m["name_rets"].values()) * 100, 0) if m["name_rets"] else 0,
        }
        for m in month_sorted[:10]
    ]
    worst_months = [
        {
            "date": m["date"],
            "net": round(m["net"] * 100, 1),
            "worst_name": min(m["name_rets"].items(), key=lambda x: x[1])[0] if m["name_rets"] else "-",
            "worst_ret": round(min(m["name_rets"].values()) * 100, 0) if m["name_rets"] else 0,
        }
        for m in month_sorted[-10:]
    ]

    # Top 5 months contribution share
    cum_total = 1.0
    for m in series:
        cum_total *= 1 + m["net"]
    total_ret = cum_total - 1

    # Approximate: what would return be without these months?
    cum_ex_top5 = 1.0
    sorted_by_ret = sorted(series, key=lambda m: -m["net"])
    for m in sorted_by_ret[5:]:
        cum_ex_top5 *= 1 + m["net"]
    ret_ex_top5 = cum_ex_top5 - 1
    top5_share = (total_ret - ret_ex_top5) / total_ret * 100 if total_ret > 0 else 0

    # Concentration: top 1/3/5 name share
    top1_share = sorted_names[0][1]["total"] / total_contrib * 100 if total_contrib and sorted_names else 0
    top3_share = sum(v["total"] for _, v in sorted_names[:3]) / total_contrib * 100 if total_contrib else 0
    top5_share_names = sum(v["total"] for _, v in sorted_names[:5]) / total_contrib * 100 if total_contrib else 0

    # Return excluding biggest winner
    biggest = sorted_names[0][0] if sorted_names else None
    cum_ex_biggest = 1.0
    for m in series:
        nr = {k: v for k, v in m["name_rets"].items() if k != biggest}
        if nr:
            cum_ex_biggest *= 1 + sum(nr.values()) / len(nr)
    ret_ex_biggest = (cum_ex_biggest - 1) * 100

    # Excluding top 3
    top3_names = {tk for tk, _ in sorted_names[:3]}
    cum_ex_top3 = 1.0
    for m in series:
        nr = {k: v for k, v in m["name_rets"].items() if k not in top3_names}
        if nr:
            cum_ex_top3 *= 1 + sum(nr.values()) / len(nr)
    ret_ex_top3 = (cum_ex_top3 - 1) * 100

    # Tail moves (>100% monthly)
    tail_contrib = sum(v["total"] for _, v in sorted_names if v["best"] > 1.0)
    tail_share = tail_contrib / total_contrib * 100 if total_contrib else 0

    return {
        "top10_contributors": top10,
        "bot10_contributors": bot10,
        "best10_months": best_months,
        "worst10_months": worst_months,
        "top5_months_share": round(top5_share, 0),
        "top1_name_share": round(top1_share, 0),
        "top3_name_share": round(top3_share, 0),
        "top5_name_share": round(top5_share_names, 0),
        "tail_winner_share": round(tail_share, 0),
        "cum_ex_biggest_winner": round(ret_ex_biggest, 1),
        "cum_ex_top3_winners": round(ret_ex_top3, 1),
        "cum_with_all": round(total_ret * 100, 1),
    }


# ======================================================================
# E) Turnover diagnostics
# ======================================================================


def turnover_diagnostics(series):
    if not series:
        return {}
    turnovers = [m["one_way"] for m in series[1:]]
    costs = [m["cost_drag"] for m in series]
    if not turnovers:
        return {}

    return {
        "avg_turnover": round(sum(turnovers) / len(turnovers) * 100, 1),
        "median_turnover": round(sorted(turnovers)[len(turnovers) // 2] * 100, 1),
        "avg_names_changed": round(sum(m["n_exited"] + m["n_entered"] for m in series[1:]) / len(series[1:]), 1),
        "total_cost_drag_pp": round(sum(costs) * 100, 1),
        "avg_monthly_cost_bps": round(sum(costs) / len(costs) * 10000, 1),
        "worst5_turnover": sorted(
            [{"date": m["date"], "turnover": round(m["one_way"] * 100, 1)} for m in series[1:]],
            key=lambda x: -x["turnover"],
        )[:5],
    }


# ======================================================================
# F) Stability by regime
# ======================================================================


def stability_analysis(series):
    if not series:
        return {}

    from collections import defaultdict

    by_year = defaultdict(list)
    for m in series:
        by_year[m["date"][:4]].append(m)

    year_stats = {}
    for yr, ms in sorted(by_year.items()):
        cm = core_metrics(ms, yr)
        year_stats[yr] = {
            "n": len(ms),
            "net_excess": cm.get("net_excess", 0),
            "monthly_excess": cm.get("monthly_excess", 0),
            "hit_rate": cm.get("hit_rate", 0),
        }

    # Strong vs weak XBI months
    median_xbi = sorted(m["xbi"] for m in series)[len(series) // 2]
    strong_xbi = [m for m in series if m["xbi"] >= median_xbi]
    weak_xbi = [m for m in series if m["xbi"] < median_xbi]

    strong_ex = sum(m["net"] - m["xbi"] for m in strong_xbi) / len(strong_xbi) if strong_xbi else 0
    weak_ex = sum(m["net"] - m["xbi"] for m in weak_xbi) / len(weak_xbi) if weak_xbi else 0

    # High vs low turnover months
    median_to = sorted(m["one_way"] for m in series[1:])[len(series[1:]) // 2] if len(series) > 1 else 0
    high_to = [m for m in series[1:] if m["one_way"] >= median_to]
    low_to = [m for m in series[1:] if m["one_way"] < median_to]

    high_to_ex = sum(m["net"] - m["xbi"] for m in high_to) / len(high_to) if high_to else 0
    low_to_ex = sum(m["net"] - m["xbi"] for m in low_to) / len(low_to) if low_to else 0

    return {
        "by_year": year_stats,
        "strong_xbi_excess": round(strong_ex * 100, 2),
        "weak_xbi_excess": round(weak_ex * 100, 2),
        "high_turnover_excess": round(high_to_ex * 100, 2),
        "low_turnover_excess": round(low_to_ex * 100, 2),
    }


# ======================================================================
# Main
# ======================================================================


def run_analytics(cost_bps=DEFAULT_COST):
    store = PriceStore(str(REPO_ROOT / "data" / "prices.db"))
    monthly = build_monthly_series(store, cost_bps)

    hist = [m for m in monthly if not m["live"]]
    live = [m for m in monthly if m["live"]]

    print("ADVANCED PERFORMANCE ANALYTICS")
    print(f"Cost assumption: {cost_bps * 10000:.0f} bps one-way")
    print(f"Periods: {len(monthly)} total ({len(hist)} backtest + {len(live)} live)")
    print("CAVEAT: Historical is pseudo-PIT. Live starts Oct 2024.")
    print("=" * 80)

    for label, subset in [("HISTORICAL (pseudo-PIT)", hist), ("LIVE (Oct 2024+)", live)]:
        if not subset:
            continue
        print(f"\n{'=' * 80}")
        print("  {label} — {len(subset)} months")
        print(f"{'=' * 80}")

        # A) Core metrics
        print(f"\n  A) CORE METRICS (net at {cost_bps*10000:.0f}bps)")
        print("  {'Net cumulative':>25s}: {cm['cum_net']:>+8.1f}%")
        print("  {'XBI cumulative':>25s}: {cm['cum_xbi']:>+8.1f}%")
        print("  {'Net excess vs XBI':>25s}: {cm['net_excess']:>+8.1f}pp")
        print("  {'Annualized net':>25s}: {cm['ann_net']:>+8.1f}%")
        print("  {'Monthly net excess':>25s}: {cm['monthly_excess']:>+7.2f}pp (t={cm['t_stat']:.2f})")
        print("  {'Hit rate':>25s}: {cm['hit_rate']:>7.0f}%")
        print("  {'Volatility (ann)':>25s}: {cm['volatility']:>7.1f}%")
        print("  {'Downside vol (ann)':>25s}: {cm['downside_vol']:>7.1f}%")
        print("  {'Sharpe':>25s}: {cm['sharpe']:>7.2f}")
        print("  {'Sortino':>25s}: {cm['sortino']:>7.2f}")
        print("  {'Information ratio':>25s}: {cm['info_ratio']:>7.2f}")
        print("  {'Tracking error (ann)':>25s}: {cm['tracking_error']:>7.1f}%")
        print("  {'Beta vs XBI':>25s}: {cm['beta']:>7.2f}")
        print("  {'Alpha vs XBI (ann)':>25s}: {cm['alpha_annual']:>+7.1f}%")

        # B) Drawdown
        dd = drawdown_metrics(subset)
        print("\n  B) DRAWDOWN & PATH RISK")
        print("  {'Max drawdown':>25s}: {dd['max_drawdown']:>7.1f}%")
        print("  {'Avg time underwater':>25s}: {dd['avg_underwater_months']:>7.1f} months")
        print("  {'Longest underwater':>25s}: {dd['longest_underwater']:>7d} months")
        print("  {'Ulcer index':>25s}: {dd['ulcer_index']:>7.2f}")
        print("  {'Calmar ratio':>25s}: {dd['calmar']:>7.2f}")
        print("  {'Worst 1mo excess':>25s}: {dd['worst_1m_excess']:>+7.1f}pp")
        print("  {'Worst 3mo excess':>25s}: {dd['worst_3m_excess']:>+7.1f}pp")
        print("  {'Rolling 12mo win rate':>25s}: {dd['rolling_12m_win_rate']}")
        if dd.get("top5_drawdowns"):
            print("  Top 5 drawdowns:")
            for d in dd["top5_drawdowns"]:
                print("    {d['start']} → {d['trough']}: {d['depth']:+.1f}% (recovered: {d['recovery'] or 'ongoing'})")

        # C-D) Attribution
        attr = attribution(subset)
        print("\n  C-D) ATTRIBUTION & CONCENTRATION")
        print("  {'Top 1 name share':>25s}: {attr['top1_name_share']:>7.0f}%")
        print("  {'Top 3 name share':>25s}: {attr['top3_name_share']:>7.0f}%")
        print("  {'Top 5 name share':>25s}: {attr['top5_name_share']:>7.0f}%")
        print("  {'Top 5 months share':>25s}: {attr['top5_months_share']:>7.0f}%")
        print("  {'Tail winner share':>25s}: {attr['tail_winner_share']:>7.0f}%")
        print("  {'Cum with all names':>25s}: {attr['cum_with_all']:>+7.1f}%")
        print("  {'Cum ex biggest winner':>25s}: {attr['cum_ex_biggest_winner']:>+7.1f}%")
        print("  {'Cum ex top 3 winners':>25s}: {attr['cum_ex_top3_winners']:>+7.1f}%")
        print("\n  Top 10 contributors:")
        for c in attr["top10_contributors"]:
            print(
                f"    {c['ticker']:>6s}: {c['contrib_pp']:>+6.1f}pp ({c['months']:>2d}mo, best {c['best']:>+4.0f}%, {c['pct_of_total']:.0f}% of total)"
            )
        print("  Bottom 5 detractors:")
        for c in attr["bot10_contributors"][-5:]:
            print(
                f"    {c['ticker']:>6s}: {c['contrib_pp']:>+6.1f}pp ({c['months']:>2d}mo, worst {c['worst']:>+4.0f}%)"
            )

        # E) Turnover
        print("\n  E) TURNOVER & COST")
        print("  {'Avg one-way turnover':>25s}: {to.get('avg_turnover', 0):>7.1f}%")
        print("  {'Median turnover':>25s}: {to.get('median_turnover', 0):>7.1f}%")
        print("  {'Avg names changed':>25s}: {to.get('avg_names_changed', 0):>7.1f}")
        print("  {'Total cost drag':>25s}: {to.get('total_cost_drag_pp', 0):>7.1f}pp")
        print("  {'Avg monthly cost':>25s}: {to.get('avg_monthly_cost_bps', 0):>7.1f} bps")

        # F) Stability
        stab = stability_analysis(subset)
        print("\n  F) STABILITY")
        print("  {'Strong XBI months excess':>25s}: {stab.get('strong_xbi_excess', 0):>+7.2f}pp")
        print("  {'Weak XBI months excess':>25s}: {stab.get('weak_xbi_excess', 0):>+7.2f}pp")
        print("  {'High turnover excess':>25s}: {stab.get('high_turnover_excess', 0):>+7.2f}pp")
        print("  {'Low turnover excess':>25s}: {stab.get('low_turnover_excess', 0):>+7.2f}pp")
        if stab.get("by_year"):
            print("  By year:")
            for yr, ys in stab["by_year"].items():
                print(
                    f"    {yr}: {ys['n']:>2d}mo  excess {ys['net_excess']:>+7.1f}pp  mo_exc {ys['monthly_excess']:>+5.2f}pp  hit {ys['hit_rate']:.0f}%"
                )

    # G) Live vs Historical comparison
    if hist and live:
        print(f"\n{'=' * 80}")
        print("  G) LIVE vs HISTORICAL COMPARISON")
        print(f"{'=' * 80}")
        lm = core_metrics(live, "live")
        ha = attribution(hist)
        la = attribution(live)

        print(f"\n  {'Metric':>25s} {'Historical':>12s} {'Live':>12s}")
        print("  {'-'*50}")
        print("  {'Net excess pp':>25s} {hm['net_excess']:>+11.1f} {lm['net_excess']:>+11.1f}")
        print("  {'Sharpe':>25s} {hm['sharpe']:>11.2f} {lm['sharpe']:>11.2f}")
        print("  {'Info ratio':>25s} {hm['info_ratio']:>11.2f} {lm['info_ratio']:>11.2f}")
        print("  {'Max drawdown':>25s} {hd['max_drawdown']:>10.1f}% {ld['max_drawdown']:>10.1f}%")
        print("  {'Avg turnover':>25s} {ht.get('avg_turnover',0):>10.1f}% {lt.get('avg_turnover',0):>10.1f}%")
        print("  {'Top 5 name share':>25s} {ha['top5_name_share']:>10.0f}% {la['top5_name_share']:>10.0f}%")
        print("  {'Tail winner share':>25s} {ha['tail_winner_share']:>10.0f}% {la['tail_winner_share']:>10.0f}%")
        print(
            f"  {'Cum ex top 3 winners':>25s} {ha['cum_ex_top3_winners']:>+10.1f}% {la['cum_ex_top3_winners']:>+10.1f}%"
        )

        # Verdict
        edge_broad = la["top5_name_share"] < 60
        live_positive = lm["net_excess"] > 0
        live_consistent = lm["hit_rate"] > 50

        print("\n  VERDICT:")
        if live_positive and live_consistent:
            if edge_broad:
                print("  Live is POSITIVE, CONSISTENT, and BROAD-BASED.")
            else:
                print("  Live is POSITIVE and CONSISTENT but CONCENTRATED in a few names.")
        elif live_positive:
            print("  Live is POSITIVE but INCONSISTENT (low hit rate).")
        else:
            print("  Live is NEGATIVE. Edge does not persist in production.")

    # Save
    out = REPO_ROOT / "artifacts" / "advanced_performance_analytics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Can't easily serialize name_rets, save summary only
    summary = {
        "cost_bps": cost_bps * 10000,
        "historical": core_metrics(hist, "hist") if hist else {},
        "live": core_metrics(live, "live") if live else {},
        "historical_drawdown": drawdown_metrics(hist) if hist else {},
        "live_drawdown": drawdown_metrics(live) if live else {},
    }
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--cost-bps", type=int, default=50, help="One-way cost in bps")
    args = parser.parse_args()
    run_analytics(cost_bps=args.cost_bps / 10000)
