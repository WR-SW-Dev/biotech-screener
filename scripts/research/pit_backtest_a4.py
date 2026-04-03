#!/usr/bin/env python3
"""True PIT backtest — A4 selector and A4+ranker vs DEM baseline.

Reads directly from snapshots_pit_v2/ (not the research panel).
Computes selector/ranker scores fresh on each snapshot.
Forward-fills inst_delta_z from quarterly 13F filings.
Measures actual portfolio returns with turnover and transaction costs.

Four arms:
  1. DEM baseline (actionable_rank top-30 EW)
  2. A4 selector (top-30 EW)
  3. A4 selector + ranker (top-30 EW)
  4. A4 selector + ranker (top-30 rank-weighted, for RW-EW comparison)

Usage:
    python3 scripts/research/pit_backtest_a4.py
    python3 scripts/research/pit_backtest_a4.py --start 2021-01-01 --cost-bps 30
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
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ranker_engine import compute_ranker_adjustments
from selector_engine import BlockWeight, SelectorConfig, SignalSpec, compute_selector_scores

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots_pit_v2"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
IPO_DATES_PATH = PROJECT_ROOT / "production_data" / "ipo_dates.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "pit_backtest"

TOP_N = 30
DEFAULT_COST_BPS = 25  # round-trip cost per turnover event

# ── A4 selector config ───────────────────────────────────────────────

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


def _safe_mean(vals):
    return statistics.mean(vals) if vals else None


def _safe_stdev(vals):
    return statistics.stdev(vals) if len(vals) >= 2 else None


def _safe_tstat(vals):
    if len(vals) < 2:
        return None
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    if s < 1e-9:
        return None
    return m / (s / len(vals) ** 0.5)


def _hit_rate(vals):
    return sum(1 for v in vals if v > 0) / len(vals) if vals else None


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


def load_prices() -> Dict[str, Dict[str, float]]:
    series: Dict[str, Dict[str, float]] = {}
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            t, d, c = row.get("ticker", ""), row.get("date", ""), row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return series


def load_ipo_dates() -> Dict[str, str]:
    if not IPO_DATES_PATH.exists():
        return {}
    with open(IPO_DATES_PATH) as f:
        raw = json.load(f)
    return {t: v.get("first_price_date", "") for t, v in raw.get("tickers", {}).items()}


def get_pit_dates(start: str) -> List[str]:
    dates = []
    for d in sorted(SNAPSHOTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        if d.name < start:
            continue
        if (d / "rankings.csv").exists():
            dates.append(d.name)
    return dates


def load_snapshot(snap_date: str, ipo_dates: Dict[str, str]) -> List[Dict[str, str]]:
    path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    with open(path) as f:
        rows = list(csv.DictReader(f))
    # PIT filter: exclude pre-IPO tickers
    if ipo_dates:
        rows = [r for r in rows if ipo_dates.get(r.get("ticker", ""), "0000") <= snap_date]
    return rows


def forward_return_ew(
    prices: Dict[str, Dict[str, float]],
    tickers: List[str],
    snap_date: str,
    horizon: int,
) -> Tuple[Optional[float], int]:
    """EW forward return for a basket. Returns (return, n_priced)."""
    rets = []
    for t in tickers:
        t_prices = prices.get(t, {})
        if not t_prices:
            continue
        sorted_dates = sorted(t_prices.keys())
        # Find start
        idx = None
        for i, d in enumerate(sorted_dates):
            if d >= snap_date:
                idx = i
                break
        if idx is None:
            continue
        end_idx = idx + horizon
        if end_idx >= len(sorted_dates):
            continue
        p0 = t_prices[sorted_dates[idx]]
        p1 = t_prices[sorted_dates[end_idx]]
        if p0 > 0:
            rets.append((p1 - p0) / p0)
    if not rets:
        return (None, 0)
    return (statistics.mean(rets), len(rets))


def forward_return_rw(
    prices: Dict[str, Dict[str, float]],
    tickers_scores: List[Tuple[str, float]],
    snap_date: str,
    horizon: int,
) -> Optional[float]:
    """Score-weighted forward return."""
    rets = []
    weights = []
    for t, score in tickers_scores:
        t_prices = prices.get(t, {})
        if not t_prices:
            continue
        sorted_dates = sorted(t_prices.keys())
        idx = None
        for i, d in enumerate(sorted_dates):
            if d >= snap_date:
                idx = i
                break
        if idx is None:
            continue
        end_idx = idx + horizon
        if end_idx >= len(sorted_dates):
            continue
        p0 = t_prices[sorted_dates[idx]]
        p1 = t_prices[sorted_dates[end_idx]]
        if p0 > 0:
            rets.append((p1 - p0) / p0)
            weights.append(max(score, 0.001))
    if not rets:
        return None
    w_sum = sum(weights)
    return sum(r * w / w_sum for r, w in zip(rets, weights))


# ── inst_delta_z forward-fill ────────────────────────────────────────


def forward_fill_inst_delta(
    rows: List[Dict[str, str]],
    prior_values: Dict[str, Tuple[str, float]],  # ticker → (date, value)
    snap_date: str,
    max_stale_months: int = 3,
) -> Dict[str, Tuple[str, float]]:
    """Forward-fill inst_delta_z from prior 13F quarters.

    Returns updated prior_values dict.
    """
    updated = dict(prior_values)
    for r in rows:
        t = r.get("ticker", "")
        v = _sf(r.get("inst_delta_z"), default=0.0)
        if abs(v) > 1e-9:
            # Real value: update the carry-forward cache
            updated[t] = (snap_date, v)
        elif t in updated:
            # Zero/missing: try to fill from cache
            last_date, last_val = updated[t]
            try:
                d_now = date.fromisoformat(snap_date)
                d_last = date.fromisoformat(last_date)
                months = (d_now.year - d_last.year) * 12 + (d_now.month - d_last.month)
                if months <= max_stale_months:
                    r["inst_delta_z"] = str(last_val)
            except (ValueError, TypeError):
                pass
    return updated


# ── Selection functions ──────────────────────────────────────────────


def select_baseline(rows: List[Dict[str, str]]) -> List[str]:
    """DEM baseline: top-30 by actionable_rank."""
    eligible = []
    for r in rows:
        if r.get("eligible") not in ("1", "1.0", "True"):
            continue
        try:
            rank = int(float(r.get("actionable_rank", "9999")))
        except (ValueError, TypeError):
            continue
        eligible.append((rank, r.get("ticker", "")))
    eligible.sort()
    return [t for _, t in eligible[:TOP_N]]


def select_a4(rows: List[Dict[str, str]]) -> Tuple[List[str], List[float]]:
    """A4 selector: top-30 by selector_score."""
    eligible_rows = [r for r in rows if r.get("eligible") in ("1", "1.0", "True")]
    if len(eligible_rows) < TOP_N:
        return ([], [])
    sel_results = compute_selector_scores(eligible_rows, config=A4_CONFIG)
    paired = list(zip(eligible_rows, sel_results))
    paired.sort(key=lambda x: -x[1].selector_score)
    top = paired[:TOP_N]
    return (
        [r.get("ticker", "") for r, _ in top],
        [sr.selector_score for _, sr in top],
    )


def select_a4_ranker(rows: List[Dict[str, str]]) -> Tuple[List[str], List[float]]:
    """A4 selector + ranker: top-30 by final_score."""
    eligible_rows = [r for r in rows if r.get("eligible") in ("1", "1.0", "True")]
    if len(eligible_rows) < TOP_N:
        return ([], [])
    sel_results = compute_selector_scores(eligible_rows, config=A4_CONFIG)
    sel_scores = [sr.selector_score for sr in sel_results]
    sel_buckets = [sr.selector_rank_bucket for sr in sel_results]
    rnk_results = compute_ranker_adjustments(eligible_rows, sel_scores, sel_buckets)

    paired = list(zip(eligible_rows, rnk_results))
    paired.sort(key=lambda x: -x[1].final_score)
    top = paired[:TOP_N]
    return (
        [r.get("ticker", "") for r, _ in top],
        [rr.final_score for _, rr in top],
    )


# ── Main backtest ────────────────────────────────────────────────────


def run_backtest(start: str, cost_bps: float) -> Dict[str, Any]:
    print("Loading prices...")
    prices = load_prices()
    xbi_prices = prices.get("XBI", {})
    print(f"  {len(prices)} tickers, XBI dates: {len(xbi_prices)}")

    ipo_dates = load_ipo_dates()
    print(f"  {len(ipo_dates)} IPO dates")

    pit_dates = get_pit_dates(start)
    print(f"PIT snapshots: {len(pit_dates)} ({pit_dates[0]} to {pit_dates[-1]})")

    # Arms
    arms = {
        "baseline": {"tickers": [], "ew": [], "hedged": [], "turnover": [], "prev": set()},
        "a4_selector": {"tickers": [], "ew": [], "hedged": [], "turnover": [], "prev": set()},
        "a4_ranker_ew": {"tickers": [], "ew": [], "hedged": [], "turnover": [], "prev": set()},
        "a4_ranker_rw": {"tickers": [], "rw": [], "hedged_rw": [], "turnover": [], "prev": set()},
    }

    inst_cache: Dict[str, Tuple[str, float]] = {}  # ticker → (date, value)
    records: List[Dict[str, Any]] = []

    for snap_date in pit_dates:
        rows = load_snapshot(snap_date, ipo_dates)
        if not rows:
            continue

        # Forward-fill inst_delta_z
        inst_cache = forward_fill_inst_delta(rows, inst_cache, snap_date)

        n_eligible = sum(1 for r in rows if r.get("eligible") in ("1", "1.0", "True"))

        # Select each arm
        bl_tickers = select_baseline(rows)
        a4_tickers, a4_scores = select_a4(rows)
        a4r_tickers, a4r_scores = select_a4_ranker(rows)

        if not bl_tickers or not a4_tickers:
            continue

        # Forward returns (63d)
        horizon = 63
        bl_ret, bl_n = forward_return_ew(prices, bl_tickers, snap_date, horizon)
        a4_ret, a4_n = forward_return_ew(prices, a4_tickers, snap_date, horizon)
        a4r_ret, a4r_n = forward_return_ew(prices, a4r_tickers, snap_date, horizon)
        xbi_ret, _ = forward_return_ew(prices, ["XBI"], snap_date, horizon)

        # RW return for ranker arm
        a4r_rw_ret = forward_return_rw(prices, list(zip(a4r_tickers, a4r_scores)), snap_date, horizon)

        if bl_ret is None or a4_ret is None or xbi_ret is None:
            continue

        # Hedged returns (vs XBI)
        bl_hedged = bl_ret - xbi_ret
        a4_hedged = a4_ret - xbi_ret
        a4r_hedged = (a4r_ret - xbi_ret) if a4r_ret is not None else None
        a4r_rw_hedged = (a4r_rw_ret - xbi_ret) if a4r_rw_ret is not None else None

        # Turnover
        for arm_name, tickers in [
            ("baseline", bl_tickers),
            ("a4_selector", a4_tickers),
            ("a4_ranker_ew", a4r_tickers),
            ("a4_ranker_rw", a4r_tickers),
        ]:
            arm = arms[arm_name]
            curr = set(tickers)
            if arm["prev"]:
                overlap = len(curr & arm["prev"])
                to = 1.0 - overlap / TOP_N
                arm["turnover"].append(to)
            arm["prev"] = curr

        # Overlap A4 vs baseline
        a4_overlap = len(set(a4_tickers) & set(bl_tickers))
        a4r_overlap = len(set(a4r_tickers) & set(bl_tickers))

        # Store
        arms["baseline"]["hedged"].append(bl_hedged)
        arms["a4_selector"]["hedged"].append(a4_hedged)
        if a4r_hedged is not None:
            arms["a4_ranker_ew"]["hedged"].append(a4r_hedged)
        if a4r_rw_hedged is not None:
            arms["a4_ranker_rw"]["hedged_rw"].append(a4r_rw_hedged)

        # Regime (trailing XBI 20d)
        xbi_20, _ = forward_return_ew(prices, ["XBI"], snap_date, 20)
        if xbi_20 is not None:
            if xbi_20 < -0.02:
                regime = "bear"
            elif xbi_20 > 0.02:
                regime = "bull"
            else:
                regime = "neutral"
        else:
            regime = "unknown"

        rec = {
            "date": snap_date,
            "n_eligible": n_eligible,
            "regime": regime,
            "bl_hedged": _r(bl_hedged * 100),
            "a4_hedged": _r(a4_hedged * 100),
            "a4r_hedged": _r(a4r_hedged * 100) if a4r_hedged else None,
            "a4r_rw_hedged": _r(a4r_rw_hedged * 100) if a4r_rw_hedged else None,
            "xbi_ret": _r(xbi_ret * 100),
            "a4_overlap_bl": a4_overlap,
            "a4r_overlap_bl": a4r_overlap,
            "bl_n": bl_n,
            "a4_n": a4_n,
        }
        records.append(rec)

    # ── Summary statistics ───────────────────────────────────────────
    result = {
        "schema": "pit_backtest_a4.v1",
        "generated": datetime.now(timezone.utc).isoformat(),
        "start": start,
        "n_periods": len(records),
        "top_n": TOP_N,
        "cost_bps": cost_bps,
        "arms": {},
        "records": records,
    }

    for arm_name, hedged_key in [
        ("baseline", "hedged"),
        ("a4_selector", "hedged"),
        ("a4_ranker_ew", "hedged"),
        ("a4_ranker_rw", "hedged_rw"),
    ]:
        arm = arms[arm_name]
        vals = arm.get(hedged_key, [])
        if not vals:
            continue

        mean_to = _safe_mean(arm["turnover"]) or 0
        # Net return: hedged - turnover cost
        cost_per_period = 2 * mean_to * cost_bps / 10000
        net_vals = [v - cost_per_period for v in vals]

        # Regime splits
        regime_vals = defaultdict(list)
        for rec in records:
            key = f"{arm_name.replace('_rw', '')}_hedged"
            if arm_name == "a4_ranker_rw":
                key = "a4r_rw_hedged"
            elif arm_name == "a4_ranker_ew":
                key = "a4r_hedged"
            elif arm_name == "a4_selector":
                key = "a4_hedged"
            else:
                key = "bl_hedged"
            v = rec.get(key)
            if v is not None:
                regime_vals[rec.get("regime", "unknown")].append(v / 100)

        arm_result = {
            "mean_hedged_pp": _r((_safe_mean(vals) or 0) * 100),
            "cum_hedged_pp": _r(sum(vals) * 100),
            "mean_net_pp": _r((_safe_mean(net_vals) or 0) * 100),
            "cum_net_pp": _r(sum(net_vals) * 100),
            "tstat": _r(_safe_tstat([v * 100 for v in vals])),
            "hit_rate": _r(_hit_rate(vals)),
            "mean_turnover": _r(mean_to),
            "cost_drag_pp": _r(cost_per_period * 100),
            "n_periods": len(vals),
            "regime": {},
        }
        for regime in ["bear", "neutral", "bull"]:
            rv = regime_vals.get(regime, [])
            arm_result["regime"][regime] = {
                "n": len(rv),
                "mean_pp": _r((_safe_mean(rv) or 0) * 100),
                "hit_rate": _r(_hit_rate(rv)),
            }
        result["arms"][arm_name] = arm_result

    # Improvement: A4 vs baseline
    bl_vals = arms["baseline"]["hedged"]
    a4_vals = arms["a4_selector"]["hedged"]
    if bl_vals and a4_vals and len(bl_vals) == len(a4_vals):
        delta = [a - b for a, b in zip(a4_vals, bl_vals)]
        result["a4_vs_baseline"] = {
            "mean_delta_pp": _r((_safe_mean(delta) or 0) * 100),
            "cum_delta_pp": _r(sum(delta) * 100),
            "tstat": _r(_safe_tstat([d * 100 for d in delta])),
            "hit_rate": _r(_hit_rate(delta)),
        }

    a4r_vals = arms["a4_ranker_ew"]["hedged"]
    if bl_vals and a4r_vals and len(bl_vals) == len(a4r_vals):
        delta = [a - b for a, b in zip(a4r_vals, bl_vals)]
        result["a4r_vs_baseline"] = {
            "mean_delta_pp": _r((_safe_mean(delta) or 0) * 100),
            "cum_delta_pp": _r(sum(delta) * 100),
            "tstat": _r(_safe_tstat([d * 100 for d in delta])),
            "hit_rate": _r(_hit_rate(delta)),
        }

    # RW-EW spread
    a4r_ew = arms["a4_ranker_ew"]["hedged"]
    a4r_rw = arms["a4_ranker_rw"].get("hedged_rw", [])
    if a4r_ew and a4r_rw and len(a4r_ew) == len(a4r_rw):
        rw_ew = [rw - ew for rw, ew in zip(a4r_rw, a4r_ew)]
        result["rw_vs_ew"] = {
            "mean_spread_pp": _r((_safe_mean(rw_ew) or 0) * 100),
            "tstat": _r(_safe_tstat([s * 100 for s in rw_ew])),
            "hit_rate": _r(_hit_rate(rw_ew)),
        }

    # Overlap stats
    a4_overlaps = [rec["a4_overlap_bl"] for rec in records]
    a4r_overlaps = [rec["a4r_overlap_bl"] for rec in records]
    result["overlap"] = {
        "a4_mean": _r(_safe_mean(a4_overlaps)),
        "a4r_mean": _r(_safe_mean(a4r_overlaps)),
    }

    return result


# ── Output ───────────────────────────────────────────────────────────


def print_report(result: Dict[str, Any]):
    print(f"\n{'='*100}")
    print("TRUE PIT BACKTEST — A4 Selector + Ranker")
    print(f"{'='*100}")
    print(
        f"Periods: {result['n_periods']}  |  Top-N: {result['top_n']}  |  Cost: {result['cost_bps']} bps  |  Start: {result['start']}"
    )
    print()

    print(
        f"{'Arm':25s} {'Hedged(pp)':>10s} {'Cum(pp)':>8s} {'Net(pp)':>8s} {'CumNet':>8s} {'t-stat':>8s} {'Hit%':>6s} {'TO':>6s} {'N':>4s}"
    )
    print("-" * 90)
    for arm_name in ["baseline", "a4_selector", "a4_ranker_ew", "a4_ranker_rw"]:
        arm = result["arms"].get(arm_name, {})
        if not arm:
            continue
        rw = "(RW)" if arm_name == "a4_ranker_rw" else ""
        print(
            f"{arm_name:25s} "
            f"{_fmt(arm.get('mean_hedged_pp')):>10s} "
            f"{_fmt(arm.get('cum_hedged_pp')):>8s} "
            f"{_fmt(arm.get('mean_net_pp')):>8s} "
            f"{_fmt(arm.get('cum_net_pp')):>8s} "
            f"{_fmt(arm.get('tstat')):>8s} "
            f"{_fmt(arm.get('hit_rate'), 0):>5s}% "
            f"{_fmt(arm.get('mean_turnover')):>6s} "
            f"{arm.get('n_periods', 0):>4d}"
        )

    # Deltas
    for key, label in [("a4_vs_baseline", "A4 vs BL"), ("a4r_vs_baseline", "A4R vs BL")]:
        d = result.get(key, {})
        if d:
            print(
                f"\n{label}: Δ={_fmt(d.get('mean_delta_pp'))}pp/mo  cum={_fmt(d.get('cum_delta_pp'))}pp  t={_fmt(d.get('tstat'))}  hit={_fmt(d.get('hit_rate'), 0)}%"
            )

    rw = result.get("rw_vs_ew", {})
    if rw:
        print(
            f"RW-EW: spread={_fmt(rw.get('mean_spread_pp'))}pp  t={_fmt(rw.get('tstat'))}  hit={_fmt(rw.get('hit_rate'), 0)}%"
        )

    ovl = result.get("overlap", {})
    if ovl:
        print(f"Overlap with baseline: A4={_fmt(ovl.get('a4_mean'), 1)}/30  A4R={_fmt(ovl.get('a4r_mean'), 1)}/30")

    # Regime splits
    print(f"\n{'Arm':25s} {'Bear':>12s} {'Neutral':>12s} {'Bull':>12s}")
    print("-" * 65)
    for arm_name in ["baseline", "a4_selector", "a4_ranker_ew"]:
        arm = result["arms"].get(arm_name, {})
        if not arm:
            continue
        rg = arm.get("regime", {})
        parts = []
        for regime in ["bear", "neutral", "bull"]:
            rv = rg.get(regime, {})
            parts.append(f"{_fmt(rv.get('mean_pp'))}({rv.get('n', 0)})")
        print(f"{arm_name:25s} {parts[0]:>12s} {parts[1]:>12s} {parts[2]:>12s}")


def main():
    parser = argparse.ArgumentParser(description="True PIT backtest: A4 selector + ranker")
    parser.add_argument("--start", default="2020-06-01")
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    args = parser.parse_args()

    result = run_backtest(args.start, args.cost_bps)

    # Save JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUTPUT_DIR / "pit_backtest_a4.json"
    with open(out_json, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nJSON: {out_json}")

    # Print report
    print_report(result)


if __name__ == "__main__":
    main()
