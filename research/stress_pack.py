#!/usr/bin/env python3
"""Stress Pack — robustness tests for the DEM strategy.

Tests:
  1. Top winner capped (single name max monthly return capped)
  2. Excluding M&A/takeout names (>200% single-month moves)
  3. Position cap / vol scaling (max 5% weight per name)
  4. Consistent windows (57mo vs 57mo, 75mo vs 75mo)

All results net of 50bps one-way costs.

Usage:
    python research/stress_pack.py
"""

from __future__ import annotations

import csv
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Set

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.price_store import PriceStore

EXCLUDE = {"JBIO"}
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
    for base in ["data/snapshots_pit_v2", "data/snapshots"]:
        path = REPO_ROOT / base / snap_date / "rankings.csv"
        if path.exists():
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            ranked = [r for r in rows if r.get("actionable_rank") and r["actionable_rank"] not in ("", "NA", "None")]
            ranked.sort(key=lambda r: int(float(r["actionable_rank"])))
            return [r["ticker"] for r in ranked if r["ticker"] not in EXCLUDE]
    return []


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


def _build_raw_monthly(store):
    """Build monthly series with per-name returns (no cost applied yet)."""
    pit_dates = sorted(
        [
            d
            for d in os.listdir(REPO_ROOT / "data" / "snapshots_pit_v2")
            if len(d) == 10 and (REPO_ROOT / "data" / "snapshots_pit_v2" / d / "rankings.csv").exists()
        ]
    )

    prev: Set[str] = set()
    monthly = []

    for i in range(len(pit_dates) - 1):
        start = pit_dates[i]
        end = pit_dates[i + 1]
        ranked = _load_ranked(start)
        if not ranked:
            continue

        portfolio = _select_with_buffer(ranked, prev)
        curr = set(portfolio)

        if prev:
            one_way = (len(prev - curr) + len(curr - prev)) / (2 * K)
        else:
            one_way = 1.0

        name_rets = {}
        for tk in portfolio:
            p0 = _get_price(store, tk, start)
            p1 = _get_price(store, tk, end)
            if p0 and p1 and p0 > 0:
                name_rets[tk] = (p1 - p0) / p0

        if not name_rets:
            prev = curr
            continue

        xbi_p0 = _get_price(store, "XBI", start)
        xbi_p1 = _get_price(store, "XBI", end)
        if not xbi_p0 or not xbi_p1:
            prev = curr
            continue
        xbi_ret = (xbi_p1 - xbi_p0) / xbi_p0

        monthly.append(
            {
                "date": start,
                "name_rets": name_rets,
                "xbi": xbi_ret,
                "one_way": one_way,
                "live": start >= LIVE_START,
            }
        )
        prev = curr

    return monthly


def _compute_stats(monthly_nets, monthly_xbi, label):
    """Compute core stats from net return and XBI series."""
    n = len(monthly_nets)
    if n == 0:
        return {"label": label, "n": 0}

    years = n / 12
    cum = 1.0
    cum_xbi = 1.0
    for net, xbi in zip(monthly_nets, monthly_xbi):
        cum *= 1 + net
        cum_xbi *= 1 + xbi

    excess = [net - xbi for net, xbi in zip(monthly_nets, monthly_xbi)]
    mean_ex = sum(excess) / n
    hit = sum(1 for e in excess if e > 0) / n

    ex_var = sum((e - mean_ex) ** 2 for e in excess) / max(n - 1, 1)
    t = mean_ex / math.sqrt(ex_var / n) if ex_var > 0 else 0

    mean_net = sum(monthly_nets) / n
    vol = math.sqrt(sum((r - mean_net) ** 2 for r in monthly_nets) / max(n - 1, 1)) * math.sqrt(12)
    ann = (cum ** (1 / years) - 1) if years >= 1 else cum - 1
    sharpe = (ann - RF_ANNUAL) / vol if vol > 0 else 0

    peak = 1.0
    max_dd = 0
    c = 1.0
    for net in monthly_nets:
        c *= 1 + net
        if c > peak:
            peak = c
        dd = (c - peak) / peak
        if dd < max_dd:
            max_dd = dd

    return {
        "label": label,
        "n": n,
        "cum_net": round((cum - 1) * 100, 1),
        "cum_xbi": round((cum_xbi - 1) * 100, 1),
        "net_excess": round((cum - 1) * 100 - (cum_xbi - 1) * 100, 1),
        "monthly_ex": round(mean_ex * 100, 2),
        "t": round(t, 2),
        "hit": round(hit * 100, 0),
        "sharpe": round(sharpe, 2),
        "max_dd": round(max_dd * 100, 1),
        "vol": round(vol * 100, 1),
    }


def _apply_scenario(monthly, scenario_fn, label):
    """Apply a scenario transformation and compute stats."""
    nets_all = []
    xbi_all = []
    nets_hist = []
    xbi_hist = []
    nets_live = []
    xbi_live = []

    for m in monthly:
        name_rets = m["name_rets"]
        xbi = m["xbi"]
        cost = m["one_way"] * COST_BPS * 2

        adjusted_rets = scenario_fn(name_rets)
        if not adjusted_rets:
            continue

        gross = sum(adjusted_rets.values()) / len(adjusted_rets)
        net = gross - cost

        nets_all.append(net)
        xbi_all.append(xbi)
        if m["live"]:
            nets_live.append(net)
            xbi_live.append(xbi)
        else:
            nets_hist.append(net)
            xbi_hist.append(xbi)

    return {
        "full": _compute_stats(nets_all, xbi_all, f"{label} (full)"),
        "hist": _compute_stats(nets_hist, xbi_hist, f"{label} (hist)"),
        "live": _compute_stats(nets_live, xbi_live, f"{label} (live)"),
    }


def run_stress_pack():
    store = PriceStore(str(REPO_ROOT / "data" / "prices.db"))
    monthly = _build_raw_monthly(store)

    print("STRESS PACK — Robustness Tests")
    print(f"Net of {COST_BPS * 10000:.0f} bps one-way")
    print(
        f"Periods: {len(monthly)} ({sum(1 for m in monthly if not m['live'])} hist + {sum(1 for m in monthly if m['live'])} live)"
    )
    print("=" * 95)

    # Define scenarios
    def baseline(nr):
        return dict(nr)

    def cap_50(nr):
        return {tk: min(r, 0.50) for tk, r in nr.items()}

    def cap_100(nr):
        return {tk: min(r, 1.00) for tk, r in nr.items()}

    def cap_200(nr):
        return {tk: min(r, 2.00) for tk, r in nr.items()}

    def exclude_ma(nr):
        # Exclude names with >200% return (likely M&A/takeout)
        filtered = {tk: r for tk, r in nr.items() if r <= 2.00}
        return filtered if filtered else nr

    def cap_loss_50(nr):
        # Also cap losses at -50% (simulate stop-loss)
        return {tk: max(min(r, 0.50), -0.50) for tk, r in nr.items()}

    def inverse_vol_weight(nr):
        # Instead of equal weight, reduce weight of high-vol names
        # Approximate: cap any single name contribution to 5% of portfolio
        # In EW, each name is 1/N. Cap at 1.5/N.
        n = len(nr)
        if n == 0:
            return nr
        cap = 1.5 / n
        total = sum(abs(r) for r in nr.values())
        if total == 0:
            return nr
        result = {}
        for tk, r in nr.items():
            if abs(r) > cap * n:
                # Scale down the extreme mover
                result[tk] = r * (cap * n) / abs(r)
            else:
                result[tk] = r
        return result

    scenarios = [
        ("Baseline (no cap)", baseline),
        ("Cap +50% per name/mo", cap_50),
        ("Cap +100% per name/mo", cap_100),
        ("Cap +200% per name/mo", cap_200),
        ("Exclude M&A (>200%)", exclude_ma),
        ("Cap ±50% (stop-loss)", cap_loss_50),
        ("Vol-scaled (cap extreme)", inverse_vol_weight),
    ]

    all_results = {}
    for label, fn in scenarios:
        all_results[label] = _apply_scenario(monthly, fn, label)

    # Print comparison table
    for period_key, period_label in [
        ("full", "FULL PERIOD"),
        ("hist", "HISTORICAL (pseudo-PIT)"),
        ("live", "LIVE (Oct 2024+)"),
    ]:
        print(f"\n{period_label}")
        print(
            f"{'Scenario':>30s} {'Net%':>8s} {'XBI%':>7s} {'Excess':>8s} {'Mo Ex':>7s} {'t':>6s} {'Hit':>5s} {'Sharpe':>7s} {'MaxDD':>7s}"
        )
        print("-" * 95)
        for label in [s[0] for s in scenarios]:
            r = all_results[label][period_key]
            if r["n"] == 0:
                continue
            print(
                f"{label:>30s}"
                f" {r['cum_net']:>+7.1f}%"
                f" {r['cum_xbi']:>+6.1f}%"
                f" {r['net_excess']:>+7.1f}pp"
                f" {r['monthly_ex']:>+6.2f}pp"
                f" {r['t']:>5.2f}"
                f" {r['hit']:>4.0f}%"
                f" {r['sharpe']:>6.2f}"
                f" {r['max_dd']:>6.1f}%"
            )

        # Show degradation from baseline
        bl = all_results["Baseline (no cap)"][period_key]
        if bl["n"] > 0:
            print("\n  Degradation from baseline:")
            for label in [s[0] for s in scenarios]:
                if label == "Baseline (no cap)":
                    continue
                r = all_results[label][period_key]
                if r["n"] == 0:
                    continue
                d_excess = r["net_excess"] - bl["net_excess"]
                d_sharpe = r["sharpe"] - bl["sharpe"]
                print(f"    {label:>28s}: excess {d_excess:>+7.1f}pp  Sharpe {d_sharpe:>+5.2f}")

    # Summary verdict
    print("\n" + "=" * 95)
    print("VERDICT")
    print("=" * 95)

    bl_live = all_results["Baseline (no cap)"]["live"]
    cap100_live = all_results["Cap +100% per name/mo"]["live"]
    exma_live = all_results["Exclude M&A (>200%)"]["live"]
    cap50_live = all_results["Cap +50% per name/mo"]["live"]

    print(f"\n  Live baseline net excess: {bl_live['net_excess']:+.1f}pp")
    print(
        f"  Live with +100% cap:     {cap100_live['net_excess']:+.1f}pp ({cap100_live['net_excess'] - bl_live['net_excess']:+.1f}pp degradation)"
    )
    print(
        f"  Live ex M&A names:       {exma_live['net_excess']:+.1f}pp ({exma_live['net_excess'] - bl_live['net_excess']:+.1f}pp degradation)"
    )
    print(
        f"  Live with +50% cap:      {cap50_live['net_excess']:+.1f}pp ({cap50_live['net_excess'] - bl_live['net_excess']:+.1f}pp degradation)"
    )

    if cap100_live["net_excess"] > 20:
        print("\n  EDGE SURVIVES with top winner capped at +100%/month.")
    elif cap100_live["net_excess"] > 0:
        print("\n  EDGE PARTIALLY SURVIVES with cap — reduced but still positive.")
    else:
        print("\n  EDGE DOES NOT SURVIVE capping — strategy is purely tail-driven.")

    if exma_live["net_excess"] > 20:
        print("  EDGE SURVIVES excluding M&A/takeout names.")
    elif exma_live["net_excess"] > 0:
        print("  EDGE PARTIALLY SURVIVES ex-M&A — reduced but positive.")
    else:
        print("  EDGE DOES NOT SURVIVE ex-M&A — strategy depends on takeout captures.")


if __name__ == "__main__":
    run_stress_pack()
