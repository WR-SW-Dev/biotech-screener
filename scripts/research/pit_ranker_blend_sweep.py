#!/usr/bin/env python3
"""PIT ranker blend sweep — find optimal analyst-rank weight mix.

Holds A4 selector and EW Top-30 constant. Sweeps ranker block weights
across interpretable variants. Measures net-of-cost return, within-top-30 IC,
and regime splits.

Usage:
    python3 scripts/research/pit_ranker_blend_sweep.py
"""

from __future__ import annotations

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

from ranker_engine import RankerConfig, compute_ranker_adjustments
from selector_engine import BlockWeight, SelectorConfig, SignalSpec, compute_selector_scores

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots_pit_v2"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
IPO_DATES_PATH = PROJECT_ROOT / "production_data" / "ipo_dates.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "pit_backtest"

TOP_N = 30
COST_BPS = 25
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

# ── Blend variants ───────────────────────────────────────────────────
# Each variant specifies (options_w, institutional_w, aact_w, catalyst_w, micro_w)
# aact slot = clinical quality, micro slot = survivability + competitive
# Weights must sum to 1.0

BLENDS = {
    # Current analyst rank default
    "analyst_default": (0.05, 0.15, 0.30, 0.25, 0.25),
    # No ranker (selector only)
    "no_ranker": None,
    # Clinical-dominant
    "clinical_50": (0.05, 0.10, 0.50, 0.20, 0.15),
    "clinical_40": (0.05, 0.10, 0.40, 0.25, 0.20),
    # Catalyst-dominant
    "catalyst_40": (0.05, 0.10, 0.20, 0.40, 0.25),
    "catalyst_35": (0.05, 0.10, 0.25, 0.35, 0.25),
    # Survivability-dominant
    "survivability_40": (0.05, 0.10, 0.20, 0.25, 0.40),
    "survivability_35": (0.05, 0.10, 0.25, 0.25, 0.35),
    # Institutional heavier in ranker
    "inst_25": (0.05, 0.25, 0.25, 0.25, 0.20),
    "inst_30": (0.05, 0.30, 0.25, 0.20, 0.20),
    # Options heavier
    "options_15": (0.15, 0.10, 0.25, 0.25, 0.25),
    "options_20": (0.20, 0.10, 0.25, 0.25, 0.20),
    # Equal weight all blocks
    "equal_5x20": (0.20, 0.20, 0.20, 0.20, 0.20),
    # Clinical + catalyst heavy (analyst intuition)
    "clin_cat_heavy": (0.05, 0.10, 0.35, 0.35, 0.15),
    # Clinical + survivability (quality + safety)
    "clin_surv_heavy": (0.05, 0.10, 0.35, 0.15, 0.35),
    # Catalyst + survivability (event + safety)
    "cat_surv_heavy": (0.05, 0.10, 0.15, 0.35, 0.35),
    # Minimal ranker (all blocks low, inst higher)
    "light_touch": (0.05, 0.35, 0.20, 0.20, 0.20),
    # Prior default (options-heavy, for comparison)
    "prior_default": (0.35, 0.25, 0.20, 0.10, 0.10),
}


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


def _rank(values):
    indexed = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    for pos, idx in enumerate(indexed):
        ranks[idx] = pos + 1
    return ranks


def _spearman_ic(xs, ys):
    if len(xs) < 5:
        return None
    rx, ry = _rank(xs), _rank(ys)
    n = len(xs)
    d_sq = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1 - 6 * d_sq / (n * (n * n - 1))


# ── Data ─────────────────────────────────────────────────────────────


def load_prices():
    s = {}
    with open(PRICE_CSV) as f:
        for r in csv.DictReader(f):
            t, d, c = r.get("ticker", ""), r.get("date", ""), r.get("close", "")
            if t and d and c:
                try:
                    s.setdefault(t, {})[d] = float(c)
                except Exception:
                    pass
    return s


def load_ipo_dates():
    if not IPO_DATES_PATH.exists():
        return {}
    with open(IPO_DATES_PATH) as f:
        raw = json.load(f)
    return {t: v.get("first_price_date", "") for t, v in raw.get("tickers", {}).items()}


def get_pit_dates(start="2020-06-01"):
    raw = sorted(
        d.name for d in SNAPSHOTS_DIR.iterdir() if d.is_dir() and d.name >= start and (d / "rankings.csv").exists()
    )
    # Dedupe to one snapshot per calendar month (last available)
    by_month = {}
    for d in raw:
        by_month[d[:7]] = d
    return sorted(by_month.values())


def load_snapshot(d, ipo):
    with open(SNAPSHOTS_DIR / d / "rankings.csv") as f:
        rows = list(csv.DictReader(f))
    if ipo:
        rows = [r for r in rows if ipo.get(r.get("ticker", ""), "0000") <= d]
    return rows


def fwd_ret_ew(prices, tickers, snap, h):
    rets = []
    for t in tickers:
        tp = prices.get(t, {})
        if not tp:
            continue
        sd = sorted(tp.keys())
        idx = next((i for i, d in enumerate(sd) if d >= snap), None)
        if idx is None:
            continue
        ei = idx + h
        if ei >= len(sd):
            continue
        p0, p1 = tp[sd[idx]], tp[sd[ei]]
        if p0 > 0:
            rets.append((p1 - p0) / p0)
    return (statistics.mean(rets), len(rets)) if rets else (None, 0)


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


# ── Core ─────────────────────────────────────────────────────────────


def make_config(weights_tuple):
    """Create a RankerConfig with given block weights, keeping signal specs from default."""
    opt_w, inst_w, aact_w, cat_w, micro_w = weights_tuple
    return RankerConfig(
        options_weight=opt_w,
        institutional_weight=inst_w,
        aact_weight=aact_w,
        catalyst_nuance_weight=cat_w,
        microstructure_weight=micro_w,
    )


def evaluate_blend(snap_data, prices, blend_name, weights_tuple):
    """Evaluate one ranker blend across all snapshots."""
    use_ranker = weights_tuple is not None
    cfg = make_config(weights_tuple) if use_ranker else None

    hedged = []
    delta_vs_sel = []  # ranker vs selector-only
    ic_vals = []
    rw_ew = []
    regime = defaultdict(list)
    turnover = []
    prev = set()

    for sd in snap_data:
        if sd["xbi_ret"] is None:
            continue
        n = len(sd["sel_rows"])
        if n < TOP_N:
            continue

        if use_ranker:
            rnk = compute_ranker_adjustments(sd["sel_rows"], sd["sel_scores"], sd["sel_buckets"], config=cfg)
            paired = sorted(zip(sd["sel_rows"], rnk), key=lambda x: -x[1].final_score)
            topk_rows = [r for r, _ in paired[:TOP_N]]
            topk_scores = [rr.final_score for _, rr in paired[:TOP_N]]
        else:
            paired = sorted(zip(sd["sel_rows"], sd["sel_scores"]), key=lambda x: -x[1])
            topk_rows = [r for r, _ in paired[:TOP_N]]
            topk_scores = [s for _, s in paired[:TOP_N]]

        tickers = [r.get("ticker", "") for r in topk_rows]
        ret, n_priced = fwd_ret_ew(prices, tickers, sd["date"], HORIZON)
        if ret is None:
            continue

        h = ret - sd["xbi_ret"]
        hedged.append(h)

        # Delta vs selector-only
        sel_ret, _ = fwd_ret_ew(prices, sd["sel_top30"], sd["date"], HORIZON)
        if sel_ret is not None:
            delta_vs_sel.append(h - (sel_ret - sd["xbi_ret"]))

        # Within-top-30 IC
        fwd_rets = []
        scores_for_ic = []
        for r, s in zip(topk_rows, topk_scores):
            t = r.get("ticker", "")
            tp = prices.get(t, {})
            if not tp:
                continue
            sd_dates = sorted(tp.keys())
            idx = next((i for i, d in enumerate(sd_dates) if d >= sd["date"]), None)
            if idx is None:
                continue
            ei = idx + HORIZON
            if ei >= len(sd_dates):
                continue
            p0, p1 = tp[sd_dates[idx]], tp[sd_dates[ei]]
            if p0 > 0:
                fwd_rets.append((p1 - p0) / p0)
                scores_for_ic.append(s)
        ic = _spearman_ic(scores_for_ic, fwd_rets) if len(scores_for_ic) >= 10 else None
        if ic is not None:
            ic_vals.append(ic)

        # RW vs EW
        if topk_scores:
            rw_ret_vals = []
            for r, s in zip(topk_rows, topk_scores):
                t = r.get("ticker", "")
                tp = prices.get(t, {})
                if not tp:
                    continue
                sd_dates = sorted(tp.keys())
                idx = next((i for i, d in enumerate(sd_dates) if d >= sd["date"]), None)
                if idx is None:
                    continue
                ei = idx + HORIZON
                if ei >= len(sd_dates):
                    continue
                p0, p1 = tp[sd_dates[idx]], tp[sd_dates[ei]]
                if p0 > 0:
                    rw_ret_vals.append(((p1 - p0) / p0, max(s, 0.001)))
            if rw_ret_vals:
                w_sum = sum(w for _, w in rw_ret_vals)
                rw_r = sum(r * w / w_sum for r, w in rw_ret_vals)
                ew_r = statistics.mean(r for r, _ in rw_ret_vals)
                rw_ew.append(rw_r - ew_r)

        # Turnover
        curr = set(tickers)
        if prev:
            turnover.append(1.0 - len(curr & prev) / TOP_N)
        prev = curr

        # Regime
        regime[sd["regime"]].append(h)

    mean_to = _safe_mean(turnover) or 0
    cost = 2 * mean_to * COST_BPS / 10000

    return {
        "name": blend_name,
        "weights": weights_tuple,
        "net_pp": _r(((_safe_mean(hedged) or 0) - cost) * 100),
        "hedged_pp": _r((_safe_mean(hedged) or 0) * 100),
        "cum_pp": _r(sum(hedged) * 100),
        "tstat": _r(_safe_tstat([v * 100 for v in hedged])),
        "hit_pct": _r((_hit_rate(hedged) or 0) * 100),
        "turnover": _r(mean_to),
        "ic": _r(_safe_mean(ic_vals)),
        "ic_t": _r(_safe_tstat(ic_vals)),
        "rw_ew_pp": _r((_safe_mean(rw_ew) or 0) * 100),
        "delta_vs_sel_pp": _r((_safe_mean(delta_vs_sel) or 0) * 100),
        "bear_pp": _r((_safe_mean(regime.get("bear", [])) or 0) * 100),
        "neut_pp": _r((_safe_mean(regime.get("neutral", [])) or 0) * 100),
        "bull_pp": _r((_safe_mean(regime.get("bull", [])) or 0) * 100),
        "n": len(hedged),
    }


# ── Main ─────────────────────────────────────────────────────────────


def main():
    print("Loading data...")
    prices = load_prices()
    ipo = load_ipo_dates()
    dates = get_pit_dates()
    print(f"  {len(prices)} tickers, {len(dates)} PIT snapshots")

    # Pre-compute selector results for all snapshots
    print("Pre-computing A4 selector...")
    inst_cache = {}
    snap_data = []
    for snap_date in dates:
        rows = load_snapshot(snap_date, ipo)
        if not rows:
            continue
        inst_cache = forward_fill_inst(rows, inst_cache, snap_date)
        eligible = [r for r in rows if r.get("eligible") in ("1", "1.0", "True")]
        if len(eligible) < TOP_N:
            continue

        sel_results = compute_selector_scores(eligible, config=A4_CONFIG)
        sel_scores = [sr.selector_score for sr in sel_results]
        sel_buckets = [sr.selector_rank_bucket for sr in sel_results]

        # Selector-only top-30
        paired = sorted(zip(eligible, sel_scores), key=lambda x: -x[1])
        sel_top30 = [r.get("ticker", "") for r, _ in paired[:TOP_N]]

        xbi_ret, _ = fwd_ret_ew(prices, ["XBI"], snap_date, HORIZON)
        regime = "bear" if xbi_ret and xbi_ret < -0.02 else ("bull" if xbi_ret and xbi_ret > 0.02 else "neutral")

        snap_data.append(
            {
                "date": snap_date,
                "sel_rows": eligible,
                "sel_scores": sel_scores,
                "sel_buckets": sel_buckets,
                "sel_top30": sel_top30,
                "xbi_ret": xbi_ret,
                "regime": regime,
            }
        )

    print(f"  {len(snap_data)} usable snapshots")

    # Evaluate all blends
    results = []
    for name, weights in BLENDS.items():
        r = evaluate_blend(snap_data, prices, name, weights)
        results.append(r)
        print(
            f"  {name:25s} net={_fmt(r['net_pp']):>6s}  t={_fmt(r['tstat']):>5s}  IC={_fmt(r['ic'], 3):>6s}  Δsel={_fmt(r['delta_vs_sel_pp']):>6s}"
        )

    # Sort by net
    results.sort(key=lambda x: x["net_pp"] or -999, reverse=True)

    # Print report
    print(f"\n{'='*140}")
    print(f"RANKER BLEND SWEEP — A4 Selector, EW Top-{TOP_N}, {COST_BPS} bps")
    print(f"{'='*140}")
    print(
        f"{'Blend':25s} {'Weights':30s} {'Net':>6s} {'Cum':>7s} {'t':>5s} {'hit%':>5s} {'TO':>5s} {'IC':>6s} {'IC_t':>5s} {'RWEW':>6s} {'Δsel':>6s} {'Bear':>6s} {'Neut':>6s} {'Bull':>6s}"
    )
    print("-" * 140)
    for r in results:
        w = f"({','.join(f'{x:.0%}' for x in r['weights'])})" if r["weights"] else "(none)"
        print(
            f"{r['name']:25s} {w:30s} "
            f"{_fmt(r['net_pp']):>6s} {_fmt(r['cum_pp']):>7s} {_fmt(r['tstat']):>5s} "
            f"{_fmt(r['hit_pct'], 0):>4s}% {_fmt(r['turnover']):>5s} "
            f"{_fmt(r['ic'], 3):>6s} {_fmt(r['ic_t']):>5s} "
            f"{_fmt(r['rw_ew_pp']):>6s} {_fmt(r['delta_vs_sel_pp']):>6s} "
            f"{_fmt(r['bear_pp']):>6s} {_fmt(r['neut_pp']):>6s} {_fmt(r['bull_pp']):>6s}"
        )

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "pit_ranker_blend_sweep.json"
    with open(out, "w") as f:
        json.dump(
            {
                "schema": "pit_ranker_blend_sweep.v1",
                "generated": datetime.now(timezone.utc).isoformat(),
                "top_n": TOP_N,
                "cost_bps": COST_BPS,
                "results": results,
            },
            f,
            indent=2,
        )
    print(f"\nJSON: {out}")


if __name__ == "__main__":
    main()
