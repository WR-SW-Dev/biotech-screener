#!/usr/bin/env python3
"""Top-30 roster stability report across PIT snapshots.

Computes month-to-month overlap, turnover, tenure, survival curves,
and regime-sliced stability for three arms:
  1. Baseline (DEM actionable_rank)
  2. A4 selector only
  3. A4 + clinical_50 ranker

Usage:
    python3 scripts/research/top30_stability_report.py
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
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ranker_engine import compute_ranker_adjustments
from selector_engine import BlockWeight, SelectorConfig, SignalSpec, compute_selector_scores

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots_pit_v2"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
IPO_DATES_PATH = PROJECT_ROOT / "production_data" / "ipo_dates.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "pit_backtest"

TOP_N = 30

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
            "coinvest_recency_state",
            0.00,
            categorical=True,
            value_map=(("fresh", 1.0), ("stale", 0.3), ("", 0.0)),
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


def _r(v, d=2):
    if v is None:
        return None
    return round(v, d)


def _fmt(v, d=2):
    if v is None:
        return "—"
    return f"{v:.{d}f}"


# ── Data loading ─────────────────────────────────────────────────────


def load_ipo_dates():
    if not IPO_DATES_PATH.exists():
        return {}
    with open(IPO_DATES_PATH) as f:
        raw = json.load(f)
    return {t: v.get("first_price_date", "") for t, v in raw.get("tickers", {}).items()}


def load_prices():
    series: Dict[str, Dict[str, float]] = {}
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            t, d, c = row.get("ticker", ""), row.get("date", ""), row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except (ValueError, TypeError):
                    pass
    return series


def get_pit_dates(start="2020-06-01"):
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
            except (ValueError, TypeError):
                pass
    return updated


def get_xbi_regime(prices, snap_date):
    xbi = prices.get("XBI", {})
    sd = sorted(xbi.keys())
    idx = next((i for i, d in enumerate(sd) if d >= snap_date), None)
    if idx is None or idx < 20:
        return "unknown"
    p_now = xbi[sd[idx]]
    p_20 = xbi[sd[idx - 20]]
    if p_20 <= 0:
        return "unknown"
    trail = (p_now - p_20) / p_20
    if trail < -0.02:
        return "bear"
    elif trail > 0.02:
        return "bull"
    return "neutral"


# ── Selection functions ──────────────────────────────────────────────


def select_baseline(rows):
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
    return set(t for _, t in eligible[:TOP_N])


def select_a4(rows):
    eligible_rows = [r for r in rows if r.get("eligible") in ("1", "1.0", "True")]
    if len(eligible_rows) < TOP_N:
        return set()
    sel_results = compute_selector_scores(eligible_rows, config=A4_CONFIG)
    paired = sorted(zip(eligible_rows, sel_results), key=lambda x: -x[1].selector_score)
    return set(r.get("ticker", "") for r, _ in paired[:TOP_N])


def select_a4_ranker(rows):
    eligible_rows = [r for r in rows if r.get("eligible") in ("1", "1.0", "True")]
    if len(eligible_rows) < TOP_N:
        return set()
    sel_results = compute_selector_scores(eligible_rows, config=A4_CONFIG)
    sel_scores = [sr.selector_score for sr in sel_results]
    sel_buckets = [sr.selector_rank_bucket for sr in sel_results]
    rnk_results = compute_ranker_adjustments(eligible_rows, sel_scores, sel_buckets)
    paired = sorted(zip(eligible_rows, rnk_results), key=lambda x: -x[1].final_score)
    return set(r.get("ticker", "") for r, _ in paired[:TOP_N])


# ── Main ─────────────────────────────────────────────────────────────


def main():
    print("Loading data...")
    ipo_dates = load_ipo_dates()
    prices = load_prices()
    pit_dates = get_pit_dates()
    print(f"  {len(pit_dates)} PIT snapshots ({pit_dates[0]} to {pit_dates[-1]})")

    arms = {
        "baseline": {"sets": [], "dates": [], "regimes": []},
        "a4_selector": {"sets": [], "dates": [], "regimes": []},
        "a4_ranker": {"sets": [], "dates": [], "regimes": []},
    }

    inst_cache: Dict[str, Any] = {}

    for snap_date in pit_dates:
        rows = load_snapshot(snap_date, ipo_dates)
        if not rows:
            continue
        inst_cache = forward_fill_inst(rows, inst_cache, snap_date)

        bl = select_baseline(rows)
        a4 = select_a4(rows)
        a4r = select_a4_ranker(rows)
        regime = get_xbi_regime(prices, snap_date)

        if not bl or not a4:
            continue

        for arm_name, ticker_set in [("baseline", bl), ("a4_selector", a4), ("a4_ranker", a4r)]:
            arms[arm_name]["sets"].append(ticker_set)
            arms[arm_name]["dates"].append(snap_date)
            arms[arm_name]["regimes"].append(regime)

    # ── Compute metrics per arm ──────────────────────────────────────

    results: Dict[str, Any] = {}

    for arm_name, arm in arms.items():
        sets = arm["sets"]
        regimes = arm["regimes"]
        n = len(sets)

        # 1. Month-to-month overlap
        overlaps = []
        for i in range(1, n):
            ov = len(sets[i] & sets[i - 1]) / TOP_N
            overlaps.append(ov)

        # 2. Entrants and exits
        entrants_per_month = []
        exits_per_month = []
        for i in range(1, n):
            entrants_per_month.append(len(sets[i] - sets[i - 1]))
            exits_per_month.append(len(sets[i - 1] - sets[i]))

        # 3. Name tenure
        ticker_months: Dict[str, int] = defaultdict(int)
        ticker_consecutive: Dict[str, int] = defaultdict(int)
        ticker_max_consecutive: Dict[str, int] = defaultdict(int)
        prev_set: set = set()
        for s in sets:
            for t in s:
                ticker_months[t] += 1
                if t in prev_set:
                    ticker_consecutive[t] += 1
                else:
                    ticker_consecutive[t] = 1
                ticker_max_consecutive[t] = max(ticker_max_consecutive[t], ticker_consecutive[t])
            # Reset consecutive for names that dropped
            for t in prev_set - s:
                ticker_consecutive[t] = 0
            prev_set = s

        tenures = list(ticker_months.values())
        max_consec = list(ticker_max_consecutive.values())

        # 4. Survival curve (entry cohort analysis)
        survival = {1: [], 3: [], 6: []}
        for i in range(n):
            # Names entering at month i (not in i-1)
            if i == 0:
                cohort = sets[0]
            else:
                cohort = sets[i] - sets[i - 1]
            if not cohort:
                continue
            for horizon in survival:
                if i + horizon < n:
                    survived = len(cohort & sets[i + horizon])
                    survival[horizon].append(survived / len(cohort))

        # 5. Regime-sliced overlap
        regime_overlaps: Dict[str, List[float]] = defaultdict(list)
        for i in range(1, n):
            ov = len(sets[i] & sets[i - 1]) / TOP_N
            regime_overlaps[regimes[i]].append(ov)

        # 6. Top 10 longest-held names
        top_tenure = sorted(ticker_months.items(), key=lambda x: -x[1])[:10]

        # 7. Re-entrants
        ever_in: set = set()
        reentrants = 0
        for i, s in enumerate(sets):
            if i > 0:
                new_this_month = s - sets[i - 1]
                reentrants += len(new_this_month & ever_in)
            ever_in |= s

        results[arm_name] = {
            "n_months": n,
            "avg_overlap": _r(statistics.mean(overlaps) if overlaps else None),
            "median_overlap": _r(statistics.median(overlaps) if overlaps else None),
            "min_overlap": _r(min(overlaps) if overlaps else None),
            "max_overlap": _r(max(overlaps) if overlaps else None),
            "avg_entrants": _r(statistics.mean(entrants_per_month) if entrants_per_month else None),
            "avg_exits": _r(statistics.mean(exits_per_month) if exits_per_month else None),
            "unique_names": len(ticker_months),
            "median_tenure": _r(statistics.median(tenures) if tenures else None),
            "mean_tenure": _r(statistics.mean(tenures) if tenures else None),
            "max_tenure": max(tenures) if tenures else 0,
            "median_max_consecutive": _r(statistics.median(max_consec) if max_consec else None),
            "one_month_names_pct": _r(sum(1 for t in tenures if t == 1) / len(tenures) * 100 if tenures else None),
            "survival_1m": _r(statistics.mean(survival[1]) if survival[1] else None),
            "survival_3m": _r(statistics.mean(survival[3]) if survival[3] else None),
            "survival_6m": _r(statistics.mean(survival[6]) if survival[6] else None),
            "regime_overlap": {r: _r(statistics.mean(v) if v else None) for r, v in sorted(regime_overlaps.items())},
            "top_tenure": top_tenure,
            "reentrant_events": reentrants,
        }

    # ── Print report ─────────────────────────────────────────────────

    print(f"\n{'='*90}")
    print("TOP-30 ROSTER STABILITY — True PIT")
    print(f"{'='*90}")
    print(f"{pit_dates[0]} to {pit_dates[-1]}, {len(pit_dates)} monthly snapshots\n")

    # Summary table
    header = f"{'Metric':35s}"
    for arm_name in ["baseline", "a4_selector", "a4_ranker"]:
        header += f" {arm_name:>15s}"
    print(header)
    print("-" * 85)

    metrics = [
        ("Avg month-to-month overlap", "avg_overlap", lambda v: f"{v*100:.0f}%"),
        ("Median overlap", "median_overlap", lambda v: f"{v*100:.0f}%"),
        ("Min overlap", "min_overlap", lambda v: f"{v*100:.0f}%"),
        ("Max overlap", "max_overlap", lambda v: f"{v*100:.0f}%"),
        ("Avg entrants/month", "avg_entrants", lambda v: f"{v:.1f}"),
        ("Avg exits/month", "avg_exits", lambda v: f"{v:.1f}"),
        ("Unique names (total)", "unique_names", lambda v: f"{v}"),
        ("Median tenure (months)", "median_tenure", lambda v: f"{v:.1f}"),
        ("Mean tenure (months)", "mean_tenure", lambda v: f"{v:.1f}"),
        ("Max tenure (months)", "max_tenure", lambda v: f"{v}"),
        ("One-month names %", "one_month_names_pct", lambda v: f"{v:.0f}%"),
        ("Survival @ 1m", "survival_1m", lambda v: f"{v*100:.0f}%"),
        ("Survival @ 3m", "survival_3m", lambda v: f"{v*100:.0f}%"),
        ("Survival @ 6m", "survival_6m", lambda v: f"{v*100:.0f}%"),
        ("Re-entry events", "reentrant_events", lambda v: f"{v}"),
    ]

    for label, key, fmt_fn in metrics:
        row = f"{label:35s}"
        for arm_name in ["baseline", "a4_selector", "a4_ranker"]:
            v = results[arm_name].get(key)
            row += f" {fmt_fn(v) if v is not None else '—':>15s}"
        print(row)

    # Regime-sliced overlap
    print(f"\n{'Regime overlap':35s}", end="")
    for arm_name in ["baseline", "a4_selector", "a4_ranker"]:
        print(f" {arm_name:>15s}", end="")
    print()
    print("-" * 85)
    for regime in ["bear", "neutral", "bull"]:
        row = f"  {regime:33s}"
        for arm_name in ["baseline", "a4_selector", "a4_ranker"]:
            v = results[arm_name]["regime_overlap"].get(regime)
            row += f" {f'{v*100:.0f}%' if v is not None else '—':>15s}"
        print(row)

    # Top 10 longest-held names per arm
    for arm_name in ["baseline", "a4_selector", "a4_ranker"]:
        top = results[arm_name]["top_tenure"]
        print(f"\nTop 10 longest-held ({arm_name}):")
        for ticker, months in top:
            print(f"  {ticker:8s} {months:3d} months")

    # Monthly overlap time series (last 12)
    print("\nMonthly overlap (last 12 months):")
    print(f"{'Date':12s}", end="")
    for arm_name in ["baseline", "a4_selector", "a4_ranker"]:
        print(f" {arm_name:>15s}", end="")
    print(f" {'regime':>10s}")
    print("-" * 65)

    n_show = min(12, len(arms["baseline"]["dates"]) - 1)
    start_idx = len(arms["baseline"]["dates"]) - 1 - n_show
    for i in range(start_idx, len(arms["baseline"]["dates"]) - 1):
        idx = i + 1
        d = arms["baseline"]["dates"][idx]
        regime = arms["baseline"]["regimes"][idx]
        row = f"{d:12s}"
        for arm_name in ["baseline", "a4_selector", "a4_ranker"]:
            s = arms[arm_name]["sets"]
            ov = len(s[idx] & s[idx - 1]) / TOP_N
            row += f" {ov*100:14.0f}%"
        row += f" {regime:>10s}"
        print(row)

    # Save JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "top30_stability.json"
    # Convert sets to lists for JSON serialization
    json_results = {}
    for arm_name, r in results.items():
        jr = dict(r)
        jr["top_tenure"] = [(t, m) for t, m in r["top_tenure"]]
        json_results[arm_name] = jr

    with open(out, "w") as f:
        json.dump(
            {
                "schema": "top30_stability.v1",
                "generated": datetime.now(timezone.utc).isoformat(),
                "top_n": TOP_N,
                "n_months": len(pit_dates),
                "results": json_results,
            },
            f,
            indent=2,
        )
    print(f"\nJSON: {out}")


if __name__ == "__main__":
    main()
