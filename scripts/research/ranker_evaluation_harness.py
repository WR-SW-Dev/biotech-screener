#!/usr/bin/env python3
"""Ranker evaluation harness — top-30 signal ranking power.

Evaluates whether a signal can rank the DEM top-30 by asymmetric upside
potential: names where the upside on catalyst hit is largest relative to
the downside on miss.

For each monthly snapshot:
  1. Load top-30 (actionable_rank <= 30)
  2. Read signal column for each ticker
  3. Compute within-top-30 Spearman IC vs forward returns
  4. Compute upside skew metrics: mean positive return, positive/negative ratio
  5. Simulate rank-weighted portfolio (signal rank → weight)
  6. Compare RW vs EW returns, net of transaction costs

Promotion bar (from two-stage architecture):
  - Top-30 IC must be positive
  - Rank-weighted must beat EW net of costs

Usage:
    python3 scripts/research/ranker_evaluation_harness.py --signal inst_delta_z
    python3 scripts/research/ranker_evaluation_harness.py --signal total_volume_z
    python3 scripts/research/ranker_evaluation_harness.py --signal inst_delta_z --top-n 30 --start 2024-01-01
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "ranker_eval"
IPO_DATES_PATH = PROJECT_ROOT / "production_data" / "ipo_dates.json"

SCHEMA = "ranker_eval.v1"

# Module-level PIT state
_ipo_dates: Dict[str, str] = {}
_pit_mode: str = "off"


def _load_ipo_dates() -> Dict[str, str]:
    """Load ipo_dates.json → flat {ticker: first_price_date}."""
    if not IPO_DATES_PATH.exists():
        return {}
    with open(IPO_DATES_PATH) as f:
        raw = json.load(f)
    tickers = raw.get("tickers", {})
    return {t: v.get("first_price_date", "") for t, v in tickers.items()}


def _filter_pit(rows: List[Dict[str, str]], snap_date: str) -> List[Dict[str, str]]:
    """Remove pre-IPO tickers when PIT mode is active."""
    if _pit_mode == "off" or not _ipo_dates:
        return rows
    return [r for r in rows if _ipo_dates.get(r.get("ticker", ""), "0000") <= snap_date]


# Cost parameters (from txn_cost_model.py calibration)
ACCOUNT_USD = 500_000
SPREAD_BASE_BPS = 5.0
SPREAD_SCALE = 8000.0
IMPACT_ETA_BPS = 30.0
COST_PER_TURNOVER_BPS = 16.7  # from post-promotion monitor calibration


# ---------------------------------------------------------------------------
# Data loading (reuse patterns from selection_benchmark.py)
# ---------------------------------------------------------------------------


def load_prices() -> Dict[str, Dict[str, float]]:
    series: Dict[str, Dict[str, float]] = {}
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return series


def forward_return(
    prices: Dict[str, float],
    snap_date: str,
    horizon: int,
) -> Optional[float]:
    sorted_dates = sorted(prices.keys())
    candidates = [d for d in sorted_dates if d >= snap_date]
    if not candidates:
        return None
    idx = sorted_dates.index(candidates[0])
    target_idx = idx + horizon
    if target_idx >= len(sorted_dates):
        return None
    p0 = prices.get(sorted_dates[idx])
    p1 = prices.get(sorted_dates[target_idx])
    if p0 and p1 and p0 > 0:
        return (p1 - p0) / p0
    return None


def get_snapshot_dates(start: str) -> List[str]:
    dates = []
    for d in SNAPSHOTS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if d.name < start:
            continue
        if (d / "rankings.csv").exists():
            dates.append(d.name)
    return sorted(dates)


def dedupe_monthly(dates: List[str]) -> List[str]:
    by_month: Dict[str, str] = {}
    for d in dates:
        by_month[d[:7]] = d
    return sorted(by_month.values())


def load_rankings(snap_date: str) -> List[Dict[str, str]]:
    path = SNAPSHOTS_DIR / snap_date / "rankings.csv"
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return _filter_pit(rows, snap_date)


def spearman_ic(x: List[float], y: List[float]) -> Optional[float]:
    n = len(x)
    if n < 5:
        return None

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vals[indexed[j + 1]] == vals[indexed[j]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k]] = avg
            i = j + 1
        return ranks

    rx = _rank(x)
    ry = _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx < 1e-9 or dy < 1e-9:
        return None
    return num / (dx * dy)


def _sf(v, default=float("nan")):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Asymmetric return metrics
# ---------------------------------------------------------------------------


def upside_skew_metrics(returns: List[float]) -> Dict[str, Any]:
    """Compute asymmetry metrics for a set of forward returns."""
    if not returns:
        return {}
    pos = [r for r in returns if r > 0]
    neg = [r for r in returns if r < 0]
    mean_pos = statistics.mean(pos) if pos else 0
    mean_neg = statistics.mean(neg) if neg else 0
    hit_rate = len(pos) / len(returns) if returns else 0

    # Upside/downside ratio: mean positive return / abs(mean negative return)
    ud_ratio = abs(mean_pos / mean_neg) if mean_neg != 0 else float("inf")

    # Expectancy: hit_rate * mean_pos + (1 - hit_rate) * mean_neg
    expectancy = hit_rate * mean_pos + (1 - hit_rate) * mean_neg

    return {
        "n": len(returns),
        "mean": round(statistics.mean(returns) * 100, 2),
        "hit_rate": round(hit_rate * 100, 1),
        "mean_pos_pct": round(mean_pos * 100, 2),
        "mean_neg_pct": round(mean_neg * 100, 2),
        "upside_downside_ratio": round(ud_ratio, 2),
        "expectancy_pct": round(expectancy * 100, 2),
    }


# ---------------------------------------------------------------------------
# Rank-weighted portfolio simulation
# ---------------------------------------------------------------------------


def rank_weights(signal_vals: List[Tuple[str, float]], higher_is_better: bool = True) -> Dict[str, float]:
    """Convert signal values into rank-proportional weights.

    Higher signal → higher weight (if higher_is_better=True).
    Normalizes to sum=1.0.
    """
    if not signal_vals:
        return {}
    # Sort by signal value
    sorted_items = sorted(signal_vals, key=lambda x: x[1], reverse=higher_is_better)
    n = len(sorted_items)
    # Weight proportional to rank position (best=n, worst=1)
    raw_weights = {}
    for i, (ticker, _) in enumerate(sorted_items):
        raw_weights[ticker] = n - i  # best gets highest weight
    total = sum(raw_weights.values())
    return {t: w / total for t, w in raw_weights.items()}


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------


def evaluate_signal(
    signal: str,
    top_n: int,
    horizons: List[int],
    start: str,
    higher_is_better: bool,
) -> Dict[str, Any]:
    """Run full ranker evaluation for a signal within the DEM top-N."""
    print("Loading prices...")
    prices = load_prices()
    xbi_prices = prices.get("XBI", {})
    print(f"  {len(prices)} tickers, XBI: {len(xbi_prices)} dates")

    all_dates = get_snapshot_dates(start)
    eval_dates = dedupe_monthly(all_dates)
    print(f"Evaluation dates: {len(eval_dates)} ({eval_dates[0]} to {eval_dates[-1]})")

    monthly_records: List[Dict[str, Any]] = []
    ic_by_horizon: Dict[int, List[float]] = {h: [] for h in horizons}

    for snap_date in eval_dates:
        rows = load_rankings(snap_date)

        # Get top-N with signal values
        top_set = []
        for r in rows:
            rank_str = r.get("actionable_rank", "")
            try:
                rank = int(float(rank_str)) if rank_str else 9999
            except ValueError:
                rank = 9999
            if rank > top_n:
                continue

            sig_val = _sf(r.get(signal))
            ticker = r.get("ticker", "")
            if not ticker:
                continue
            top_set.append(
                {
                    "ticker": ticker,
                    "rank": rank,
                    "signal": sig_val,
                }
            )

        if len(top_set) < 10:
            continue

        # Filter to names with valid signal
        with_signal = [t for t in top_set if not math.isnan(t["signal"])]
        signal_coverage = len(with_signal) / len(top_set) if top_set else 0

        record: Dict[str, Any] = {
            "date": snap_date,
            "n_top": len(top_set),
            "n_with_signal": len(with_signal),
            "signal_coverage": round(signal_coverage, 2),
        }

        for horizon in horizons:
            h_key = f"h{horizon}"

            # Within-top-N IC: signal vs forward return
            pairs = []
            for t in with_signal:
                ret = forward_return(prices.get(t["ticker"], {}), snap_date, horizon)
                if ret is not None:
                    pairs.append((t["signal"], ret))

            if len(pairs) < 5:
                continue

            sigs, rets = zip(*pairs)
            ic = spearman_ic(list(sigs) if higher_is_better else [-s for s in sigs], list(rets))
            if ic is not None:
                ic_by_horizon[horizon].append(ic)
                record[f"{h_key}_ic"] = round(ic, 4)

            # EW returns (all top-N, including those without signal)
            ew_rets = []
            for t in top_set:
                ret = forward_return(prices.get(t["ticker"], {}), snap_date, horizon)
                if ret is not None:
                    ew_rets.append(ret)

            # RW returns (signal-weighted, only those with signal)
            rw_weights = rank_weights(
                [(t["ticker"], t["signal"]) for t in with_signal],
                higher_is_better=higher_is_better,
            )
            rw_rets_weighted = 0.0
            rw_n = 0
            for t in with_signal:
                ret = forward_return(prices.get(t["ticker"], {}), snap_date, horizon)
                if ret is not None:
                    w = rw_weights.get(t["ticker"], 0)
                    rw_rets_weighted += w * ret
                    rw_n += 1

            xbi_ret = forward_return(xbi_prices, snap_date, horizon)

            if len(ew_rets) < 10:
                continue

            ew_mean = statistics.mean(ew_rets)
            record[f"{h_key}_ew_ret"] = round(ew_mean * 100, 2)
            record[f"{h_key}_rw_ret"] = round(rw_rets_weighted * 100, 2)
            record[f"{h_key}_rw_minus_ew"] = round((rw_rets_weighted - ew_mean) * 100, 2)

            if xbi_ret is not None:
                record[f"{h_key}_xbi"] = round(xbi_ret * 100, 2)
                record[f"{h_key}_ew_excess"] = round((ew_mean - xbi_ret) * 100, 2)
                record[f"{h_key}_rw_excess"] = round((rw_rets_weighted - xbi_ret) * 100, 2)

            # Asymmetry: top quintile vs bottom quintile by signal
            n_q = max(1, len(pairs) // 5)
            sorted_pairs = sorted(pairs, key=lambda x: x[0], reverse=higher_is_better)
            top_q_rets = [r for _, r in sorted_pairs[:n_q]]
            bot_q_rets = [r for _, r in sorted_pairs[-n_q:]]
            record[f"{h_key}_top_q"] = upside_skew_metrics(top_q_rets)
            record[f"{h_key}_bot_q"] = upside_skew_metrics(bot_q_rets)

        monthly_records.append(record)

    # --- Aggregate ---
    result = {
        "schema": SCHEMA,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "pseudo_pit_version": 2 if _pit_mode != "off" else 1,
        "pit_mode": _pit_mode,
        "signal": signal,
        "top_n": top_n,
        "higher_is_better": higher_is_better,
        "n_months": len(monthly_records),
        "start": start,
        "horizons": {},
        "monthly_records": monthly_records,
    }

    print(f"\n{'='*70}")
    print(f"RANKER EVALUATION — {signal} within Top-{top_n}")
    print(f"{'='*70}")
    print(f"Months evaluated: {len(monthly_records)}")

    # Mean signal coverage
    covs = [r["signal_coverage"] for r in monthly_records]
    if covs:
        print(f"Signal coverage: {statistics.mean(covs):.0%} mean")

    for horizon in horizons:
        h_key = f"h{horizon}"
        ics = ic_by_horizon[horizon]
        rw_minus_ew = [r[f"{h_key}_rw_minus_ew"] for r in monthly_records if f"{h_key}_rw_minus_ew" in r]

        print(f"\n--- {horizon}d horizon ---")

        h_result: Dict[str, Any] = {"horizon": horizon}

        if ics:
            mean_ic = statistics.mean(ics)
            std_ic = statistics.stdev(ics) if len(ics) > 1 else 0
            t_stat = mean_ic / (std_ic / len(ics) ** 0.5) if std_ic > 0 else 0
            hit = sum(1 for x in ics if x > 0) / len(ics)
            print(f"  Within-top-{top_n} IC:")
            print(f"    Mean:    {mean_ic:+.4f}")
            print(f"    t-stat:  {t_stat:+.2f}")
            print(f"    Hit:     {hit:.0%} positive ({len(ics)} months)")
            h_result["ic_mean"] = round(mean_ic, 4)
            h_result["ic_t_stat"] = round(t_stat, 2)
            h_result["ic_hit_rate"] = round(hit, 2)
            h_result["ic_n"] = len(ics)

        if rw_minus_ew:
            mean_spread = statistics.mean(rw_minus_ew)
            cum_spread = sum(rw_minus_ew)
            # Cost adjustment: RW has ~1.5x turnover vs EW (from txn_cost_model)
            annual_rw_extra_cost_bps = 65  # incremental RW cost over EW (223 bps/yr base)
            monthly_cost_drag = annual_rw_extra_cost_bps / 12 / 100  # in pp
            net_spread = mean_spread - monthly_cost_drag
            cum_net = cum_spread - monthly_cost_drag * len(rw_minus_ew)

            print("  RW vs EW spread:")
            print(f"    Mean:     {mean_spread:+.2f}pp/mo (gross)")
            print(f"    Net:      {net_spread:+.2f}pp/mo (after ~{annual_rw_extra_cost_bps}bps/yr RW cost)")
            print(f"    Cum gross: {cum_spread:+.1f}pp")
            print(f"    Cum net:   {cum_net:+.1f}pp")
            h_result["rw_ew_spread_gross"] = round(mean_spread, 2)
            h_result["rw_ew_spread_net"] = round(net_spread, 2)
            h_result["rw_ew_cum_gross"] = round(cum_spread, 1)
            h_result["rw_ew_cum_net"] = round(cum_net, 1)
            h_result["rw_extra_cost_bps_yr"] = annual_rw_extra_cost_bps

        # Asymmetry summary: top quintile vs bottom quintile across months
        top_q_means = []
        bot_q_means = []
        for r in monthly_records:
            tq = r.get(f"{h_key}_top_q", {})
            bq = r.get(f"{h_key}_bot_q", {})
            if "mean" in tq:
                top_q_means.append(tq["mean"])
            if "mean" in bq:
                bot_q_means.append(bq["mean"])

        if top_q_means and bot_q_means:
            mean_top_q = statistics.mean(top_q_means)
            mean_bot_q = statistics.mean(bot_q_means)
            skew_spread = mean_top_q - mean_bot_q
            print("  Upside skew (signal quintiles):")
            print(f"    Top-Q mean ret:  {mean_top_q:+.2f}pp")
            print(f"    Bot-Q mean ret:  {mean_bot_q:+.2f}pp")
            print(f"    Skew spread:     {skew_spread:+.2f}pp")
            h_result["top_q_mean_ret"] = round(mean_top_q, 2)
            h_result["bot_q_mean_ret"] = round(mean_bot_q, 2)
            h_result["skew_spread"] = round(skew_spread, 2)

        result["horizons"][str(horizon)] = h_result

    # --- Promotion verdict ---
    verdict = "INSUFFICIENT_DATA"
    if monthly_records:
        ic_20 = result["horizons"].get("20", {}).get("ic_mean")
        ic_63 = result["horizons"].get("63", {}).get("ic_mean")
        net_20 = result["horizons"].get("20", {}).get("rw_ew_spread_net")
        net_63 = result["horizons"].get("63", {}).get("rw_ew_spread_net")

        any_ic_positive = (ic_20 is not None and ic_20 > 0) or (ic_63 is not None and ic_63 > 0)
        any_net_positive = (net_20 is not None and net_20 > 0) or (net_63 is not None and net_63 > 0)

        if any_ic_positive and any_net_positive:
            verdict = "PROMOTE"
        else:
            verdict = "NOT_READY"

    result["verdict"] = verdict

    print(f"\n{'='*70}")
    print(f"VERDICT: {verdict}")
    if verdict == "NOT_READY":
        reasons = []
        for h in horizons:
            ic = result["horizons"].get(str(h), {}).get("ic_mean")
            net = result["horizons"].get(str(h), {}).get("rw_ew_spread_net")
            if ic is not None and ic <= 0:
                reasons.append(f"  {h}d IC={ic:+.4f} (need positive)")
            if net is not None and net <= 0:
                reasons.append(f"  {h}d net spread={net:+.2f}pp (need positive)")
        if reasons:
            print("Reasons:")
            for r in reasons:
                print(r)
    print(f"{'='*70}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Ranker evaluation harness")
    parser.add_argument("--signal", required=True, help="Signal column name from rankings.csv")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--horizons", default="20,63", help="Comma-separated forward horizons")
    parser.add_argument("--start", default="2020-06-01")
    parser.add_argument(
        "--lower-is-better",
        action="store_true",
        help="Signal where lower values indicate higher upside (e.g. composite_rank)",
    )
    parser.add_argument(
        "--pit-mode",
        choices=["off", "survivorship", "full"],
        default="off",
        help="PIT filtering: off/survivorship/full (default: off)",
    )
    args = parser.parse_args()

    global _pit_mode, _ipo_dates
    _pit_mode = args.pit_mode
    if _pit_mode != "off":
        _ipo_dates = _load_ipo_dates()
        print(f"PIT mode: {_pit_mode} ({len(_ipo_dates)} IPO dates loaded)")

    horizons = [int(h) for h in args.horizons.split(",")]
    higher_is_better = not args.lower_is_better

    result = evaluate_signal(
        signal=args.signal,
        top_n=args.top_n,
        horizons=horizons,
        start=args.start,
        higher_is_better=higher_is_better,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{args.signal}_ranker_eval.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
