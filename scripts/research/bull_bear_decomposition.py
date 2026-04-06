#!/usr/bin/env python3
"""Bull/bear return asymmetry decomposition.

Answers: does the bear alpha come from coinvest selection specifically,
or is it a broader EW construction effect?

Two hypotheses:
  H1: Coinvest = institutional hedging signal. High-coinvest names
      outperform in bears because quality matters in downturns.
  H2: EW construction artifact. EW mechanically underweights momentum
      winners in bull markets.

Approach:
  For each monthly period in the PIT backtest:
  1. Load the PIT snapshot (ranked portfolio with coinvest scores)
  2. Compute forward 1-month returns from price_history.csv
  3. Split the top-30 into high-coinvest vs low-coinvest halves
  4. Compare returns by regime: do high-coinvest names drive bear alpha?
  5. Compare with EW-all-eligible to isolate selection vs construction
"""

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PIT_SNAPSHOTS = REPO / "data" / "snapshots_pit_v2"
PRICE_HISTORY = REPO / "production_data" / "price_history.csv"
BACKTEST = REPO / "output" / "pit_backtest" / "pit_backtest_a4.json"
REGIME_HISTORY = REPO / "artifacts" / "regime_shadow" / "history_summary.csv"


def load_prices():
    """Load price_history.csv into {ticker: {date_str: close}}."""
    prices = defaultdict(dict)
    with open(PRICE_HISTORY) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "")
            dt = row.get("date", "")
            close = row.get("close")
            if ticker and dt and close:
                try:
                    prices[ticker][dt] = float(close)
                except ValueError:
                    pass
    return prices


def get_forward_return(prices, ticker, start_date, horizon_days=21):
    """Compute forward return from start_date over horizon_days trading days."""
    ticker_prices = prices.get(ticker, {})
    if not ticker_prices:
        return None
    sorted_dates = sorted(ticker_prices.keys())
    # Find start index
    start_idx = None
    for i, d in enumerate(sorted_dates):
        if d >= start_date:
            start_idx = i
            break
    if start_idx is None:
        return None
    end_idx = start_idx + horizon_days
    if end_idx >= len(sorted_dates):
        return None
    p0 = ticker_prices[sorted_dates[start_idx]]
    p1 = ticker_prices[sorted_dates[end_idx]]
    if p0 <= 0:
        return None
    return (p1 - p0) / p0


def load_snapshot_scores(snap_date):
    """Load coinvest_score_z and actionable_rank from a PIT snapshot."""
    rankings_path = PIT_SNAPSHOTS / snap_date / "rankings.csv"
    if not rankings_path.exists():
        return None
    scores = []
    with open(rankings_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "")
            rank_str = row.get("actionable_rank", "")
            coinvest_str = row.get("coinvest_score_z", "")
            inst_delta_str = row.get("inst_delta_z", "")
            financial_str = row.get("financial_score", "")
            selector_str = row.get("selector_score", "")
            if not ticker or not rank_str:
                continue
            try:
                rank = float(rank_str)
            except ValueError:
                continue
            coinvest = float(coinvest_str) if coinvest_str else 0.0
            inst_delta = float(inst_delta_str) if inst_delta_str else 0.0
            financial = float(financial_str) if financial_str else 0.0
            selector = float(selector_str) if selector_str else 0.0
            scores.append(
                {
                    "ticker": ticker,
                    "rank": rank,
                    "coinvest_score_z": coinvest,
                    "inst_delta_z": inst_delta,
                    "financial_score": financial,
                    "selector_score": selector,
                }
            )
    return scores


def main():
    print("Loading prices...")
    prices = load_prices()
    print(f"  {len(prices)} tickers loaded")

    print("Loading backtest periods...")
    with open(BACKTEST) as f:
        bt = json.load(f)
    records = bt["records"]
    print(f"  {len(records)} periods")

    # Available PIT snapshots
    available_snaps = {d.name for d in PIT_SNAPSHOTS.iterdir() if d.is_dir() and d.name[:4].isdigit()}

    # Results accumulators
    regime_results = defaultdict(list)  # regime -> list of period results
    all_periods = []

    for rec in records:
        snap_date = rec["date"]
        regime = rec["regime"]
        xbi_ret = rec.get("xbi_ret", 0)

        if snap_date not in available_snaps:
            continue

        scores = load_snapshot_scores(snap_date)
        if not scores:
            continue

        # Get all eligible names
        all_eligible = [s for s in scores if s["rank"] <= 999]

        # DEM top-30 (baseline)
        dem_top30 = sorted([s for s in scores if s["rank"] <= 30], key=lambda x: x["rank"])

        # Coinvest-ranked top-30 (proxy for A4 selector)
        coinvest_ranked = sorted(all_eligible, key=lambda x: x["coinvest_score_z"], reverse=True)
        top30 = coinvest_ranked[:30]

        if len(top30) < 20:
            continue

        # Compute forward returns for each name
        for s in scores:
            s["fwd_ret"] = get_forward_return(prices, s["ticker"], snap_date)

        # Filter to names with valid returns
        top30_valid = [s for s in top30 if s["fwd_ret"] is not None]
        eligible_valid = [s for s in all_eligible if s["fwd_ret"] is not None]

        if len(top30_valid) < 15:
            continue

        # Portfolio return (coinvest-ranked top-30)
        port_ret = sum(s["fwd_ret"] for s in top30_valid) / len(top30_valid)
        # EW all-eligible return
        ew_all_ret = sum(s["fwd_ret"] for s in eligible_valid) / len(eligible_valid) if eligible_valid else 0
        # DEM top-30 return (baseline)
        dem_valid = [s for s in dem_top30 if s["fwd_ret"] is not None]
        dem_ret = sum(s["fwd_ret"] for s in dem_valid) / len(dem_valid) if dem_valid else 0

        # Split top-30 by coinvest: high vs low halves
        sorted_by_coinvest = sorted(top30_valid, key=lambda x: x["coinvest_score_z"], reverse=True)
        mid = len(sorted_by_coinvest) // 2
        high_coinvest = sorted_by_coinvest[:mid]
        low_coinvest = sorted_by_coinvest[mid:]

        high_ret = sum(s["fwd_ret"] for s in high_coinvest) / len(high_coinvest)
        low_ret = sum(s["fwd_ret"] for s in low_coinvest) / len(low_coinvest)
        high_minus_low = high_ret - low_ret

        # Mean coinvest scores
        high_mean_coinvest = sum(s["coinvest_score_z"] for s in high_coinvest) / len(high_coinvest)
        low_mean_coinvest = sum(s["coinvest_score_z"] for s in low_coinvest) / len(low_coinvest)

        # Hedged returns (vs XBI and vs EW-all benchmark)
        port_excess = port_ret - xbi_ret / 100  # xbi_ret is in pp
        port_excess_ew = port_ret - ew_all_ret  # vs EW all-eligible (true benchmark)

        period = {
            "date": snap_date,
            "regime": regime,
            "n_top30": len(top30_valid),
            "n_eligible": len(eligible_valid),
            "xbi_ret": xbi_ret,
            "port_ret_pct": port_ret * 100,
            "ew_all_ret_pct": ew_all_ret * 100,
            "high_coinvest_ret_pct": high_ret * 100,
            "low_coinvest_ret_pct": low_ret * 100,
            "high_minus_low_pp": high_minus_low * 100,
            "high_mean_coinvest_z": high_mean_coinvest,
            "low_mean_coinvest_z": low_mean_coinvest,
            "dem_ret_pct": dem_ret * 100,
            "selection_effect_pp": (port_ret - ew_all_ret) * 100,  # coinvest-top30 vs all-eligible
            "coinvest_vs_dem_pp": (port_ret - dem_ret) * 100,
            "port_excess_xbi_pp": port_excess * 100,
            "port_excess_ew_pp": port_excess_ew * 100,  # vs EW all-eligible benchmark
        }
        all_periods.append(period)
        regime_results[regime].append(period)

    # === REPORT ===
    print("\n" + "=" * 80)
    print("BULL/BEAR RETURN ASYMMETRY DECOMPOSITION")
    print("=" * 80)
    print(f"Periods analyzed: {len(all_periods)}")

    for regime in ["bear", "neutral", "bull"]:
        periods = regime_results.get(regime, [])
        if not periods:
            continue
        n = len(periods)

        def avg(key):
            return sum(p[key] for p in periods) / n

        print("\n" + "─" * 60)
        print(f"REGIME: {regime.upper()} (n={n})")
        print("─" * 60)
        print(f"  XBI avg return:           {avg('xbi_ret'):+.2f} pp")
        print(f"  EW All-Eligible:           {avg('ew_all_ret_pct'):+.2f}%")
        print(f"  Coinvest Top-30:           {avg('port_ret_pct'):+.2f}%")
        print(f"  DEM Top-30 (baseline):     {avg('dem_ret_pct'):+.2f}%")
        print()
        print(f"  Excess vs XBI (cap-wt):    {avg('port_excess_xbi_pp'):+.2f} pp")
        print(f"  Excess vs EW-all:          {avg('port_excess_ew_pp'):+.2f} pp  <-- TRUE ALPHA")
        print()
        print("  --- SELECTION EFFECT ---")
        print(f"  Coinvest vs All-Eligible:  {avg('selection_effect_pp'):+.2f} pp")
        print(f"  Coinvest vs DEM:           {avg('coinvest_vs_dem_pp'):+.2f} pp")
        print()
        print("  --- WITHIN-PORTFOLIO COINVEST DECOMPOSITION ---")
        print(
            f"  High-coinvest half:        {avg('high_coinvest_ret_pct'):+.2f}%  (mean z={avg('high_mean_coinvest_z'):+.2f})"
        )
        print(
            f"  Low-coinvest half:         {avg('low_coinvest_ret_pct'):+.2f}%  (mean z={avg('low_mean_coinvest_z'):+.2f})"
        )
        print(f"  High minus Low:            {avg('high_minus_low_pp'):+.2f} pp")

    # === HYPOTHESIS VERDICT ===
    bear = regime_results.get("bear", [])
    bull = regime_results.get("bull", [])

    if bear and bull:

        def avg_key(periods, key):
            return sum(p[key] for p in periods) / len(periods)

        bear_ew_all = avg_key(bear, "ew_all_ret_pct")
        bull_ew_all = avg_key(bull, "ew_all_ret_pct")
        bear_port = avg_key(bear, "port_ret_pct")
        bull_port = avg_key(bull, "port_ret_pct")
        bear_xbi_excess = avg_key(bear, "port_excess_xbi_pp")
        bull_xbi_excess = avg_key(bull, "port_excess_xbi_pp")
        bear_ew_excess = avg_key(bear, "port_excess_ew_pp")
        bull_ew_excess = avg_key(bull, "port_excess_ew_pp")
        bear_cv_dem = avg_key(bear, "coinvest_vs_dem_pp")
        bull_cv_dem = avg_key(bull, "coinvest_vs_dem_pp")
        bear_xbi = avg_key(bear, "xbi_ret")
        bull_xbi = avg_key(bull, "xbi_ret")

        neutral = regime_results.get("neutral", [])

        def n_avg(k):
            return avg_key(neutral, k) if neutral else 0

        print("\n" + "=" * 80)
        print("BENCHMARK COMPARISON: XBI (cap-weighted) vs EW-ALL (equal-weighted)")
        print("=" * 80)
        print()
        hdr = f"  {'':35s} {'BEAR':>10s} {'NEUTRAL':>10s} {'BULL':>10s}"
        print(hdr)
        print(f"  {'XBI return':35s} {bear_xbi:+10.2f}pp {n_avg('xbi_ret'):+10.2f}pp {bull_xbi:+10.2f}pp")
        print(
            f"  {'EW All-Eligible return':35s} {bear_ew_all:+10.2f}% {n_avg('ew_all_ret_pct'):+10.2f}% {bull_ew_all:+10.2f}%"
        )
        ew_xbi_gap_bear = bear_ew_all + bear_xbi / 100 * 100
        ew_xbi_gap_bull = bull_ew_all - bull_xbi / 100 * 100
        print(f"  {'EW-All vs XBI (benchmark gap)':35s} {ew_xbi_gap_bear:+10.2f}pp {'':10s} {ew_xbi_gap_bull:+10.2f}pp")
        print()
        print(
            f"  {'Coinvest Top-30 return':35s} {bear_port:+10.2f}% {n_avg('port_ret_pct'):+10.2f}% {bull_port:+10.2f}%"
        )
        print(
            f"  {'Excess vs XBI':35s} {bear_xbi_excess:+10.2f}pp {n_avg('port_excess_xbi_pp'):+10.2f}pp {bull_xbi_excess:+10.2f}pp"
        )
        print(
            f"  {'Excess vs EW-All (TRUE ALPHA)':35s} {bear_ew_excess:+10.2f}pp {n_avg('port_excess_ew_pp'):+10.2f}pp {bull_ew_excess:+10.2f}pp"
        )
        print()
        print(
            f"  {'Coinvest vs DEM':35s} {bear_cv_dem:+10.2f}pp {n_avg('coinvest_vs_dem_pp'):+10.2f}pp {bull_cv_dem:+10.2f}pp"
        )

        print(f"\n{'=' * 80}")
        print("DIAGNOSIS")
        print(f"{'=' * 80}")
        print()
        print(f"  Bull 'underperformance' vs XBI:     {bull_xbi_excess:+.2f} pp/month")
        print(f"  Of which benchmark mismatch (EW-XBI): {bull_ew_all - bull_xbi / 100 * 100:+.2f} pp")
        print(f"  Of which true selection alpha:       {bull_ew_excess:+.2f} pp")
        print()
        print(f"  Bear 'outperformance' vs XBI:        {bear_xbi_excess:+.2f} pp/month")
        print(f"  Of which benchmark mismatch (EW-XBI): {bear_ew_all + bear_xbi / 100 * 100:+.2f} pp")
        print(f"  Of which true selection alpha:        {bear_ew_excess:+.2f} pp")

    # Write output
    output_path = REPO / "artifacts" / "bull_bear_decomposition.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(
            {
                "generated": str(date.today()),
                "n_periods": len(all_periods),
                "periods": all_periods,
                "regime_summary": {
                    regime: {
                        "n": len(periods),
                        "avg_port_ret_pct": sum(p["port_ret_pct"] for p in periods) / len(periods),
                        "avg_ew_all_ret_pct": sum(p["ew_all_ret_pct"] for p in periods) / len(periods),
                        "avg_selection_effect_pp": sum(p["selection_effect_pp"] for p in periods) / len(periods),
                        "avg_high_minus_low_pp": sum(p["high_minus_low_pp"] for p in periods) / len(periods),
                        "avg_high_coinvest_ret_pct": sum(p["high_coinvest_ret_pct"] for p in periods) / len(periods),
                        "avg_low_coinvest_ret_pct": sum(p["low_coinvest_ret_pct"] for p in periods) / len(periods),
                    }
                    for regime, periods in regime_results.items()
                    if periods
                },
            },
            f,
            indent=2,
        )
    print(f"\nOutput: {output_path}")


if __name__ == "__main__":
    main()
