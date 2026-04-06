#!/usr/bin/env python3
"""Backtest AACT execution_score as a ranker feature.

Joins execution_score from AACT delta snapshots to the top-30 book
from ranking snapshots, then evaluates predictive power for forward returns.

Metrics:
  1. IC (rank correlation of execution_score vs forward return) per period
  2. Spread (top-half vs bottom-half execution_score forward return)
  3. FM incremental t-stat (Fama-MacBeth cross-sectional regression)
  4. Checklist v2 pass/fail summary

Usage:
    python3 scripts/research/aact_execution_backtest.py
    python3 scripts/research/aact_execution_backtest.py --top-n 60
    python3 scripts/research/aact_execution_backtest.py --horizon 20
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

AACT_DELTAS_DIR = PROJECT_ROOT / "artifacts" / "aact_deltas"
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "aact_backtest"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_prices() -> Dict[str, Dict[str, float]]:
    """Load {ticker: {date: close}} from price_history.csv."""
    prices: Dict[str, Dict[str, float]] = {}
    with open(PRICE_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    prices.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return prices


def load_execution_scores() -> Dict[str, Dict[str, float]]:
    """Load {date: {ticker: execution_score}} from delta files."""
    scores: Dict[str, Dict[str, float]] = {}
    for f in sorted(AACT_DELTAS_DIR.glob("aact_deltas_*.json")):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        dt = data.get("as_of_date", f.stem.replace("aact_deltas_", ""))
        ticker_scores = {}
        for t in data.get("tickers", []):
            ticker = t.get("ticker", "")
            score = t.get("execution_score")
            if ticker and score is not None:
                ticker_scores[ticker] = float(score)
        if ticker_scores:
            scores[dt] = ticker_scores
    return scores


def load_top_n_book(snapshot_date: str, top_n: int = 30) -> List[str]:
    """Load top-N tickers from a ranking snapshot."""
    rankings_path = SNAPSHOTS_DIR / snapshot_date / "rankings.csv"
    if not rankings_path.exists():
        return []
    tickers = []
    with open(rankings_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rank_str = row.get("actionable_rank", "")
            try:
                rank = int(rank_str)
            except (ValueError, TypeError):
                continue
            if rank <= top_n:
                tickers.append((rank, row.get("ticker", "")))
    tickers.sort()
    return [t for _, t in tickers]


def find_nearest_snapshot(target_date: str, max_gap: int = 7) -> Optional[str]:
    """Find the nearest ranking snapshot to target_date."""
    if not SNAPSHOTS_DIR.exists():
        return None
    target = date.fromisoformat(target_date)
    best = None
    best_gap = max_gap + 1
    for d in SNAPSHOTS_DIR.iterdir():
        if not d.is_dir() or not (d / "rankings.csv").exists():
            continue
        name = d.name
        if "__" in name or not name[:4].isdigit():
            continue
        try:
            snap_date = date.fromisoformat(name)
        except ValueError:
            continue
        gap = abs((snap_date - target).days)
        if gap < best_gap:
            best_gap = gap
            best = name
    return best


def forward_return(prices: Dict[str, float], dt: str, horizon: int) -> Optional[float]:
    """Forward return for a ticker from dt over horizon trading days."""
    sorted_dates = sorted(prices.keys())
    idx = None
    for i, d in enumerate(sorted_dates):
        if d >= dt:
            idx = i
            break
    if idx is None:
        return None
    end = idx + horizon
    if end >= len(sorted_dates):
        return None
    p0 = prices[sorted_dates[idx]]
    p1 = prices[sorted_dates[end]]
    if p0 <= 0:
        return None
    return (p1 / p0 - 1) * 100


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def rank_correlation(x: List[float], y: List[float]) -> float:
    """Spearman rank correlation."""
    n = len(x)
    if n < 3:
        return 0.0
    rx = _ranks(x)
    ry = _ranks(y)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1 - 6 * d2 / (n * (n * n - 1))


def _ranks(vals: List[float]) -> List[float]:
    indexed = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    for rank, idx in enumerate(indexed):
        ranks[idx] = rank + 1.0
    return ranks


def _stats(vals: List[float]) -> Dict[str, Any]:
    if not vals:
        return {"n": 0, "mean": None, "t": None}
    n = len(vals)
    mean = sum(vals) / n
    if n > 1:
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
        t = mean / (std / math.sqrt(n)) if std > 0 else 0.0
    else:
        t = 0.0
    return {"n": n, "mean": round(mean, 4), "t": round(t, 2)}


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def run_backtest(top_n: int = 30, horizon: int = 20) -> Dict[str, Any]:
    print("Loading data...")
    all_prices = load_prices()
    exec_scores = load_execution_scores()
    aact_dates = sorted(exec_scores.keys())

    print(f"  AACT delta dates: {len(aact_dates)} ({aact_dates[0]} to {aact_dates[-1]})")
    print(f"  Top-N: {top_n}, Forward horizon: {horizon}d")

    periods: List[Dict] = []
    ic_series: List[float] = []
    spread_series: List[float] = []
    fm_betas: List[float] = []  # cross-sectional slope per period

    for dt in aact_dates:
        # Find nearest ranking snapshot
        snap_date = find_nearest_snapshot(dt)
        if snap_date is None:
            continue

        # Load top-N book
        book = load_top_n_book(snap_date, top_n)
        if len(book) < 10:
            continue

        # Join execution_score to book
        scores_today = exec_scores[dt]
        joined = []
        for ticker in book:
            score = scores_today.get(ticker)
            if score is None:
                continue
            fwd = forward_return(all_prices.get(ticker, {}), dt, horizon)
            if fwd is None:
                continue
            joined.append({"ticker": ticker, "score": score, "fwd": fwd})

        if len(joined) < 5:
            continue

        # IC: rank correlation of execution_score vs forward return
        x = [j["score"] for j in joined]
        y = [j["fwd"] for j in joined]
        ic = rank_correlation(x, y)
        ic_series.append(ic)

        # Spread: top-half vs bottom-half by execution_score
        joined.sort(key=lambda j: j["score"], reverse=True)
        mid = len(joined) // 2
        top_half = [j["fwd"] for j in joined[:mid]]
        bot_half = [j["fwd"] for j in joined[mid:]]
        spread = (sum(top_half) / len(top_half)) - (sum(bot_half) / len(bot_half))
        spread_series.append(spread)

        # FM: cross-sectional regression slope (execution_score → forward return)
        # Simple OLS: beta = cov(x, y) / var(x)
        x_mean = sum(x) / len(x)
        y_mean = sum(y) / len(y)
        cov_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y)) / len(x)
        var_x = sum((xi - x_mean) ** 2 for xi in x) / len(x)
        if var_x > 0:
            beta = cov_xy / var_x
            fm_betas.append(beta)

        periods.append(
            {
                "date": dt,
                "snap_date": snap_date,
                "n_joined": len(joined),
                "ic": round(ic, 4),
                "spread": round(spread, 3),
                "top_half_mean": round(sum(top_half) / len(top_half), 3),
                "bot_half_mean": round(sum(bot_half) / len(bot_half), 3),
            }
        )

    # Aggregate
    ic_stats = _stats(ic_series)
    spread_stats = _stats(spread_series)
    fm_stats = _stats(fm_betas)

    # Year stability
    by_year: Dict[str, List[float]] = defaultdict(list)
    for p in periods:
        by_year[p["date"][:4]].append(p["ic"])
    year_stability = {}
    for yr, ics in sorted(by_year.items()):
        s = _stats(ics)
        year_stability[yr] = {"n": s["n"], "mean_ic": s["mean"], "t": s["t"]}

    # LOSO: leave-one-slice-out (by year)
    loso_worst = None
    loso_results = {}
    for leave_yr in sorted(by_year.keys()):
        remaining = [ic for yr, ics in by_year.items() if yr != leave_yr for ic in ics]
        s = _stats(remaining)
        loso_results[f"excl_{leave_yr}"] = s
        if loso_worst is None or (s["mean"] is not None and s["mean"] < (loso_worst.get("mean") or 999)):
            loso_worst = s

    # Checklist v2 assessment
    checklist = {
        "fm_incremental_nwt": fm_stats["t"] if fm_stats["t"] else 0,
        "fm_pass": abs(fm_stats["t"] or 0) >= 1.96,
        "ic_mean": ic_stats["mean"],
        "ic_t": ic_stats["t"],
        "spread_mean": spread_stats["mean"],
        "spread_t": spread_stats["t"],
        "loso_worst_positive": loso_worst and loso_worst.get("mean", 0) and loso_worst["mean"] > 0,
        "year_stable": all(v.get("mean_ic", 0) and v["mean_ic"] > 0 for v in year_stability.values()),
        "n_periods": len(periods),
    }
    checklist["score"] = sum(
        [
            bool(checklist["fm_pass"]),
            bool((ic_stats["t"] or 0) >= 1.96),
            bool((spread_stats["t"] or 0) >= 1.96),
            bool(checklist["loso_worst_positive"]),
            bool(checklist["year_stable"]),
        ]
    )

    results = {
        "config": {"top_n": top_n, "horizon": horizon},
        "n_periods": len(periods),
        "date_range": (periods[0]["date"], periods[-1]["date"]) if periods else (None, None),
        "ic": ic_stats,
        "spread": spread_stats,
        "fm_beta": fm_stats,
        "year_stability": year_stability,
        "loso": loso_results,
        "checklist_v2": checklist,
        "periods": periods,
    }
    return results


def print_report(results: Dict[str, Any]):
    cfg = results["config"]
    print(f"\n{'=' * 65}")
    print(f"AACT EXECUTION_SCORE BACKTEST — top-{cfg['top_n']}, {cfg['horizon']}d forward")
    print(f"{'=' * 65}")
    print(f"Periods: {results['n_periods']} ({results['date_range'][0]} to {results['date_range'][1]})")

    ic = results["ic"]
    sp = results["spread"]
    fm = results["fm_beta"]
    print("\n--- Signal Quality ---")
    print(f"  IC (rank corr):    mean={ic['mean']}  t={ic['t']}  n={ic['n']}")
    print(f"  Spread (top-bot):  mean={sp['mean']}%  t={sp['t']}")
    print(f"  FM beta:           mean={fm['mean']}  t={fm['t']}")

    print("\n--- Year Stability ---")
    for yr, s in results["year_stability"].items():
        tag = "+" if s.get("mean_ic", 0) and s["mean_ic"] > 0 else "-"
        print(f"  {yr}: IC={s['mean_ic']}  t={s['t']}  n={s['n']}  [{tag}]")

    print("\n--- LOSO ---")
    for k, s in results["loso"].items():
        print(f"  {k}: IC={s['mean']}  t={s['t']}")

    cl = results["checklist_v2"]
    print(f"\n--- Checklist v2 ({cl['score']}/5) ---")
    print(f"  FM NW-t >= 1.96:      {'PASS' if cl['fm_pass'] else 'FAIL'} (t={cl['fm_incremental_nwt']})")
    print(f"  IC t >= 1.96:          {'PASS' if (ic['t'] or 0) >= 1.96 else 'FAIL'} (t={ic['t']})")
    print(f"  Spread t >= 1.96:      {'PASS' if (sp['t'] or 0) >= 1.96 else 'FAIL'} (t={sp['t']})")
    print(f"  LOSO worst positive:   {'PASS' if cl['loso_worst_positive'] else 'FAIL'}")
    print(f"  Year stable:           {'PASS' if cl['year_stable'] else 'FAIL'}")

    # Show last 5 periods
    print("\n--- Recent Periods ---")
    for p in results["periods"][-5:]:
        print(
            f"  {p['date']} (snap={p['snap_date']}): n={p['n_joined']}  IC={p['ic']:+.3f}  spread={p['spread']:+.2f}%"
        )


def main():
    parser = argparse.ArgumentParser(description="Backtest AACT execution_score")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = run_backtest(top_n=args.top_n, horizon=args.horizon)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"aact_backtest_top{args.top_n}_h{args.horizon}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print_report(results)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
