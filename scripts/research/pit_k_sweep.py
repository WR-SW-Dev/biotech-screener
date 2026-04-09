#!/usr/bin/env python3
"""True PIT K-sweep — find optimal portfolio size for A4 selector.

Holds everything constant except K:
  - Selector: A4 (coinvest+inst 65/35)
  - Ranker: default (bounded ±15%)
  - Construction: equal-weight
  - Cost: 25 bps round-trip
  - Hedging: vs XBI

Tests K = 10, 15, 20, 25, 30, 35, 40, 50
Reports: net-of-cost excess, t-stat, hit rate, turnover, regime splits, yearly.

Usage:
    python3 scripts/research/pit_k_sweep.py
    python3 scripts/research/pit_k_sweep.py --cost-bps 30
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ranker_engine import compute_ranker_adjustments
from selector_engine import BlockWeight, SelectorConfig, SignalSpec, compute_selector_scores

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots_pit_v2"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
IPO_DATES_PATH = PROJECT_ROOT / "production_data" / "ipo_dates.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "pit_backtest"

K_VALUES = [10, 15, 20, 25, 30, 35, 40, 50]
DEFAULT_COST_BPS = 25
HORIZON = 63

A4_CONFIG = SelectorConfig(
    block_weights=(
        BlockWeight("clinical", 0.05),
        BlockWeight("catalyst", 0.10),
        BlockWeight("survivability", 0.10),
        BlockWeight("institutional", 0.65),
        BlockWeight("market_structure", 0.10),
    ),
    institutional_signals=(
        SignalSpec("coinvest_score_z", 0.65),
        SignalSpec("inst_delta_z", 0.35),
        SignalSpec(
            "coinvest_recency_state", 0.00, categorical=True, value_map=(("fresh", 1.0), ("stale", 0.3), ("", 0.0))
        ),
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _safe_mean(v):
    return statistics.mean(v) if v else None


def _safe_stdev(v):
    return statistics.stdev(v) if len(v) >= 2 else None


def _safe_tstat(v):
    if len(v) < 2:
        return None
    m, s = statistics.mean(v), statistics.stdev(v)
    return m / (s / len(v) ** 0.5) if s > 1e-9 else None


def _hit_rate(v):
    return sum(1 for x in v if x > 0) / len(v) if v else None


def _r(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, d)


def _fmt(v, d=2):
    if v is None:
        return "—"
    return f"{v:.{d}f}"


# ── Data loading ─────────────────────────────────────────────────────


def load_prices():
    series = {}
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            t, d, c = row.get("ticker", ""), row.get("date", ""), row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return series


def load_ipo_dates():
    if not IPO_DATES_PATH.exists():
        return {}
    with open(IPO_DATES_PATH) as f:
        raw = json.load(f)
    return {t: v.get("first_price_date", "") for t, v in raw.get("tickers", {}).items()}


def get_pit_dates(start):
    raw = sorted(
        d.name for d in SNAPSHOTS_DIR.iterdir() if d.is_dir() and d.name >= start and (d / "rankings.csv").exists()
    )
    # Dedupe to one snapshot per calendar month (last available)
    by_month = {}
    for d in raw:
        by_month[d[:7]] = d
    return sorted(by_month.values())


def load_snapshot(snap_date, ipo_dates):
    with open(SNAPSHOTS_DIR / snap_date / "rankings.csv") as f:
        rows = list(csv.DictReader(f))
    if ipo_dates:
        rows = [r for r in rows if ipo_dates.get(r.get("ticker", ""), "0000") <= snap_date]
    return rows


def forward_return_ew(prices, tickers, snap_date, horizon):
    rets = []
    for t in tickers:
        tp = prices.get(t, {})
        if not tp:
            continue
        sd = sorted(tp.keys())
        idx = None
        for i, d in enumerate(sd):
            if d >= snap_date:
                idx = i
                break
        if idx is None:
            continue
        ei = idx + horizon
        if ei >= len(sd):
            continue
        p0, p1 = tp[sd[idx]], tp[sd[ei]]
        if p0 > 0:
            rets.append((p1 - p0) / p0)
    return (statistics.mean(rets), len(rets)) if rets else (None, 0)


# ── inst_delta_z forward-fill ────────────────────────────────────────


def forward_fill_inst(rows, cache, snap_date, max_months=3):
    updated = dict(cache)
    for r in rows:
        t = r.get("ticker", "")
        v = _sf(r.get("inst_delta_z"), default=0.0)
        if abs(v) > 1e-9:
            updated[t] = (snap_date, v)
        elif t in updated:
            ld, lv = updated[t]
            try:
                months = (date.fromisoformat(snap_date).year - date.fromisoformat(ld).year) * 12 + (
                    date.fromisoformat(snap_date).month - date.fromisoformat(ld).month
                )
                if months <= max_months:
                    r["inst_delta_z"] = str(lv)
            except Exception:
                pass
    return updated


# ── Main sweep ───────────────────────────────────────────────────────


def run_sweep(start, cost_bps):
    print("Loading data...")
    prices = load_prices()
    ipo_dates = load_ipo_dates()
    pit_dates = get_pit_dates(start)
    print(f"  {len(prices)} tickers, {len(pit_dates)} PIT snapshots ({pit_dates[0]} to {pit_dates[-1]})")

    # Pre-compute: for each snapshot, get eligible rows + selector/ranker scores
    inst_cache = {}
    snap_data = []  # list of (date, eligible_rows_sorted_by_final_score, xbi_ret, regime)

    for snap_date in pit_dates:
        rows = load_snapshot(snap_date, ipo_dates)
        if not rows:
            continue
        inst_cache = forward_fill_inst(rows, inst_cache, snap_date)

        eligible = [r for r in rows if r.get("eligible") in ("1", "1.0", "True")]
        if len(eligible) < max(K_VALUES):
            continue

        # Selector
        sel_results = compute_selector_scores(eligible, config=A4_CONFIG)
        sel_scores = [sr.selector_score for sr in sel_results]
        sel_buckets = [sr.selector_rank_bucket for sr in sel_results]

        # Ranker
        rnk_results = compute_ranker_adjustments(eligible, sel_scores, sel_buckets)

        # Sort by final_score descending
        paired = sorted(zip(eligible, rnk_results), key=lambda x: -x[1].final_score)
        sorted_rows = [r for r, _ in paired]
        sorted_scores = [rr.final_score for _, rr in paired]

        # XBI return
        xbi_ret, _ = forward_return_ew(prices, ["XBI"], snap_date, HORIZON)

        # Regime (forward XBI 63d for labeling)
        if xbi_ret is not None:
            regime = "bear" if xbi_ret < -0.02 else ("bull" if xbi_ret > 0.02 else "neutral")
        else:
            regime = "unknown"

        # Also get baseline top-K tickers by actionable_rank
        baseline_sorted = sorted(eligible, key=lambda r: _sf(r.get("actionable_rank"), 9999))

        snap_data.append(
            {
                "date": snap_date,
                "sorted_rows": sorted_rows,
                "sorted_scores": sorted_scores,
                "baseline_sorted": baseline_sorted,
                "xbi_ret": xbi_ret,
                "regime": regime,
                "n_eligible": len(eligible),
            }
        )

    print(f"  {len(snap_data)} usable snapshots")

    # Evaluate each K
    results = {}
    for k in K_VALUES:
        hedged_vals = []
        bl_hedged_vals = []
        delta_vals = []
        turnover_vals = []
        regime_data = defaultdict(list)
        yearly_data = defaultdict(list)
        prev_tickers = set()

        for sd in snap_data:
            if sd["xbi_ret"] is None:
                continue
            if len(sd["sorted_rows"]) < k:
                continue

            # A4+ranker top-K
            topk_tickers = [r.get("ticker", "") for r in sd["sorted_rows"][:k]]
            ret, n = forward_return_ew(prices, topk_tickers, sd["date"], HORIZON)
            if ret is None:
                continue

            # Baseline top-K
            bl_tickers = [r.get("ticker", "") for r in sd["baseline_sorted"][:k]]
            bl_ret, _ = forward_return_ew(prices, bl_tickers, sd["date"], HORIZON)
            if bl_ret is None:
                continue

            hedged = ret - sd["xbi_ret"]
            bl_hedged = bl_ret - sd["xbi_ret"]
            delta = hedged - bl_hedged

            hedged_vals.append(hedged)
            bl_hedged_vals.append(bl_hedged)
            delta_vals.append(delta)

            # Turnover
            curr = set(topk_tickers)
            if prev_tickers:
                turnover_vals.append(1.0 - len(curr & prev_tickers) / k)
            prev_tickers = curr

            # Regime
            regime_data[sd["regime"]].append(delta)

            # Yearly
            year = sd["date"][:4]
            yearly_data[year].append(delta)

        mean_to = _safe_mean(turnover_vals) or 0
        cost_drag = 2 * mean_to * cost_bps / 10000

        results[k] = {
            "k": k,
            "n_periods": len(hedged_vals),
            "hedged_pp": _r((_safe_mean(hedged_vals) or 0) * 100),
            "cum_hedged_pp": _r(sum(hedged_vals) * 100),
            "net_pp": _r(((_safe_mean(hedged_vals) or 0) - cost_drag) * 100),
            "cum_net_pp": _r((sum(hedged_vals) - cost_drag * len(hedged_vals)) * 100),
            "tstat": _r(_safe_tstat([v * 100 for v in hedged_vals])),
            "hit_rate": _r(_hit_rate(hedged_vals)),
            "mean_turnover": _r(mean_to),
            "cost_drag_pp": _r(cost_drag * 100),
            # Vs baseline
            "bl_hedged_pp": _r((_safe_mean(bl_hedged_vals) or 0) * 100),
            "delta_pp": _r((_safe_mean(delta_vals) or 0) * 100),
            "delta_cum_pp": _r(sum(delta_vals) * 100),
            "delta_tstat": _r(_safe_tstat([v * 100 for v in delta_vals])),
            "delta_hit_rate": _r(_hit_rate(delta_vals)),
            # Regime
            "regime": {},
            # Yearly
            "yearly": {},
        }

        for regime in ["bear", "neutral", "bull"]:
            rv = regime_data.get(regime, [])
            results[k]["regime"][regime] = {
                "n": len(rv),
                "delta_pp": _r((_safe_mean(rv) or 0) * 100),
                "hit_rate": _r(_hit_rate(rv)),
            }

        for year in sorted(yearly_data.keys()):
            yv = yearly_data[year]
            results[k]["yearly"][year] = {
                "n": len(yv),
                "delta_cum_pp": _r(sum(yv) * 100),
                "delta_mean_pp": _r((_safe_mean(yv) or 0) * 100),
            }

    return results


def print_report(results, cost_bps):
    print(f"\n{'='*120}")
    print("TRUE PIT K-SWEEP — A4 Selector + Ranker EW")
    print(f"{'='*120}")
    print(f"Cost: {cost_bps} bps  |  Horizon: {HORIZON}d  |  Construction: EW")
    print()

    # Main table
    print(
        f"{'K':>4s} {'Hedged':>8s} {'Cum':>8s} {'Net':>8s} {'CumNet':>8s} {'t':>6s} {'hit%':>6s} {'TO':>6s} {'Cost':>6s} {'BL':>8s} {'Δ':>7s} {'Δcum':>8s} {'Δt':>6s} {'Δhit':>6s} {'N':>4s}"
    )
    print("-" * 115)

    best_net = max(results.values(), key=lambda r: r["net_pp"] or -999)
    best_net_pp = best_net["net_pp"]
    # Compute SE of best
    # We need the raw vals to compute SE... approximate from t-stat
    # SE ≈ mean / t, so 1 SE ≈ mean / t
    best_se = abs(best_net_pp / best_net["tstat"]) if best_net["tstat"] and abs(best_net["tstat"]) > 0.01 else 999

    for k in K_VALUES:
        r = results[k]
        within_1se = "◄" if r["net_pp"] and r["net_pp"] >= (best_net_pp - best_se) else ""
        is_best = " ★" if r["k"] == best_net["k"] else ""
        print(
            f"{k:4d} "
            f"{_fmt(r['hedged_pp']):>8s} "
            f"{_fmt(r['cum_hedged_pp']):>8s} "
            f"{_fmt(r['net_pp']):>8s} "
            f"{_fmt(r['cum_net_pp']):>8s} "
            f"{_fmt(r['tstat']):>6s} "
            f"{_fmt(r['hit_rate'], 0):>5s}% "
            f"{_fmt(r['mean_turnover']):>6s} "
            f"{_fmt(r['cost_drag_pp']):>6s} "
            f"{_fmt(r['bl_hedged_pp']):>8s} "
            f"{_fmt(r['delta_pp']):>7s} "
            f"{_fmt(r['delta_cum_pp']):>8s} "
            f"{_fmt(r['delta_tstat']):>6s} "
            f"{_fmt(r['delta_hit_rate'], 0):>5s}% "
            f"{r['n_periods']:4d}"
            f"{within_1se}{is_best}"
        )

    print(f"\n◄ = within 1 SE of best net ({best_net['k']}={best_net_pp:.2f}pp, SE≈{best_se:.2f})")

    # Regime table
    print(
        f"\n{'K':>4s} {'Bear Δ':>8s} {'Bear hit':>8s} {'Bear n':>6s} {'Neut Δ':>8s} {'Neut n':>6s} {'Bull Δ':>8s} {'Bull hit':>8s} {'Bull n':>6s}"
    )
    print("-" * 75)
    for k in K_VALUES:
        rg = results[k]["regime"]
        print(
            f"{k:4d} "
            f"{_fmt(rg['bear'].get('delta_pp')):>8s} "
            f"{_fmt(rg['bear'].get('hit_rate'), 0):>7s}% "
            f"{rg['bear'].get('n', 0):6d} "
            f"{_fmt(rg['neutral'].get('delta_pp')):>8s} "
            f"{rg['neutral'].get('n', 0):6d} "
            f"{_fmt(rg['bull'].get('delta_pp')):>8s} "
            f"{_fmt(rg['bull'].get('hit_rate'), 0):>7s}% "
            f"{rg['bull'].get('n', 0):6d}"
        )

    # Yearly table (delta vs baseline)
    all_years = sorted(set(y for r in results.values() for y in r["yearly"]))
    print(f"\n{'K':>4s}", end="")
    for y in all_years:
        print(f" {y:>8s}", end="")
    print()
    print("-" * (5 + 9 * len(all_years)))
    for k in K_VALUES:
        print(f"{k:4d}", end="")
        for y in all_years:
            yd = results[k]["yearly"].get(y, {})
            v = yd.get("delta_cum_pp")
            print(f" {_fmt(v):>8s}", end="")
        print()

    # Adjacency check
    print("\nAdjacency stability (net-of-cost pp/mo):")
    for i, k in enumerate(K_VALUES):
        net = results[k]["net_pp"] or 0
        neighbors = []
        if i > 0:
            neighbors.append(results[K_VALUES[i - 1]]["net_pp"] or 0)
        if i < len(K_VALUES) - 1:
            neighbors.append(results[K_VALUES[i + 1]]["net_pp"] or 0)
        avg_neighbor = statistics.mean(neighbors) if neighbors else 0
        diff = net - avg_neighbor
        print(f"  K={k:3d}: net={net:+.2f}pp, avg_neighbor={avg_neighbor:+.2f}pp, diff={diff:+.2f}pp")


def main():
    parser = argparse.ArgumentParser(description="True PIT K-sweep")
    parser.add_argument("--start", default="2020-06-01")
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    args = parser.parse_args()

    results = run_sweep(args.start, args.cost_bps)

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "pit_k_sweep.json"
    with open(out, "w") as f:
        json.dump(
            {
                "schema": "pit_k_sweep.v1",
                "generated": datetime.now(timezone.utc).isoformat(),
                "cost_bps": args.cost_bps,
                "horizon": HORIZON,
                "k_values": K_VALUES,
                "results": {str(k): v for k, v in results.items()},
            },
            f,
            indent=2,
        )
    print(f"\nJSON: {out}")

    print_report(results, args.cost_bps)


if __name__ == "__main__":
    main()
