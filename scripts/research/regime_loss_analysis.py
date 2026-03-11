#!/usr/bin/env python3
"""
Regime loss analysis — characterize weekly portfolio loss patterns vs XBI regime.

Reads archived snapshots + price_history.csv to build a weekly panel:
  - Portfolio return (equal-weight top N from rankings, 1-week forward)
  - XBI return (1-week forward)
  - Excess return
  - XBI drawdown from trailing peak
  - XBI 4-week rolling vol
  - Gap-risk exposure (% weight in names with catalyst_days <= 14)
  - Bucket-level returns (by tier)

Output: CSV + summary stats printed to stdout.
"""

import csv
import io
import math
import os
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARCHIVES_DIR = PROJECT_ROOT / "data" / "archives"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
OUTPUT_CSV = PROJECT_ROOT / "data" / "regime_loss_panel.csv"

TOP_N = 25  # mimic portfolio: top 25 ranked names


def load_price_history():
    """Load price_history.csv into {ticker: {date_str: close}}."""
    prices = defaultdict(dict)
    with open(PRICE_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            close = row.get("close", "")
            if close:
                try:
                    prices[row["ticker"]][row["date"]] = float(close)
                except (ValueError, KeyError):
                    pass
    return prices


def load_archive_rankings(archive_path, as_of_date):
    """Extract top-N ranked tickers + metadata from a snapshot archive."""
    try:
        with tarfile.open(archive_path, "r:gz") as tf:
            rankings_path = f"{as_of_date}/rankings.csv"
            try:
                member = tf.getmember(rankings_path)
            except KeyError:
                return None
            f = tf.extractfile(member)
            if f is None:
                return None
            text = io.TextIOWrapper(f, encoding="utf-8")
            reader = csv.DictReader(text)
            rows = []
            for row in reader:
                # Only eligible names with a rank
                rank_str = row.get("actionable_rank", "")
                if not rank_str:
                    continue
                try:
                    int(rank_str)
                except ValueError:
                    continue
                eligible = row.get("eligible", "1")
                if eligible == "0":
                    continue
                rows.append(row)
            # Sort by rank, take top N
            rows.sort(key=lambda r: int(r["actionable_rank"]))
            return rows[:TOP_N]
    except Exception as e:
        print(f"  WARN: failed to read {archive_path}: {e}", file=sys.stderr)
        return None


def get_weekly_dates():
    """Get sorted list of archive dates."""
    dates = []
    for fn in os.listdir(ARCHIVES_DIR):
        if fn.endswith(".tar.gz"):
            d = fn.replace(".tar.gz", "")
            dates.append(d)
    dates.sort()
    return dates


def find_next_price_date(prices_xbi, date_str, max_days=7):
    """Find the next trading date on or after date_str."""
    from datetime import datetime, timedelta

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    for i in range(max_days):
        candidate = (dt + timedelta(days=i)).strftime("%Y-%m-%d")
        if candidate in prices_xbi:
            return candidate
    return None


def compute_xbi_regime(prices_xbi, dates_sorted):
    """Compute XBI drawdown from trailing peak + rolling vol for each date."""
    regime = {}
    peak = 0.0
    returns_window = []
    for d in dates_sorted:
        if d not in prices_xbi:
            continue
        p = prices_xbi[d]
        peak = max(peak, p)
        dd = (p / peak - 1.0) * 100 if peak > 0 else 0.0

        # 20-day rolling vol (annualized) — approximate from daily returns
        returns_window.append(p)
        if len(returns_window) > 21:
            returns_window.pop(0)
        if len(returns_window) >= 5:
            daily_rets = [returns_window[i] / returns_window[i - 1] - 1 for i in range(1, len(returns_window))]
            vol = (sum(r**2 for r in daily_rets) / len(daily_rets)) ** 0.5 * (252**0.5)
        else:
            vol = float("nan")

        regime[d] = {"dd_pct": dd, "vol_ann": vol, "price": p, "peak": peak}
    return regime


def main():
    print("Loading price history...")
    prices = load_price_history()
    prices_xbi = prices.get("XBI", {})
    if not prices_xbi:
        print("ERROR: No XBI prices found", file=sys.stderr)
        return

    # Build sorted daily dates for XBI regime calc
    all_xbi_dates = sorted(prices_xbi.keys())
    xbi_regime = compute_xbi_regime(prices_xbi, all_xbi_dates)

    weekly_dates = get_weekly_dates()
    print(f"Found {len(weekly_dates)} archive dates, {len(all_xbi_dates)} XBI price dates")

    panel = []
    for i, as_of in enumerate(weekly_dates):
        if i >= len(weekly_dates) - 1:
            break  # need forward return

        next_date = weekly_dates[i + 1]
        archive_path = ARCHIVES_DIR / f"{as_of}.tar.gz"
        rankings = load_archive_rankings(archive_path, as_of)
        if rankings is None:
            continue

        # Find trading dates for return calc
        trade_start = find_next_price_date(prices_xbi, as_of)
        trade_end = find_next_price_date(prices_xbi, next_date)
        if not trade_start or not trade_end:
            continue

        # XBI return
        xbi_start = prices_xbi.get(trade_start)
        xbi_end = prices_xbi.get(trade_end)
        if not xbi_start or not xbi_end:
            continue
        xbi_ret = (xbi_end / xbi_start - 1.0) * 100

        # Portfolio return (equal-weight)
        ticker_rets = []
        gap_risk_weight = 0.0
        n_gap_risk = 0
        tier_rets = defaultdict(list)
        bucket_rets = defaultdict(list)

        for row in rankings:
            ticker = row["ticker"]
            t_prices = prices.get(ticker, {})
            p_start = t_prices.get(trade_start)
            p_end = t_prices.get(trade_end)
            if p_start and p_end and p_start > 0:
                ret = (p_end / p_start - 1.0) * 100
                ticker_rets.append(ret)

                # Tier
                tier = row.get("tier_any", "?")
                tier_rets[tier].append(ret)

                # Archetype / severity bucket
                archetype = row.get("archetype", "?")
                bucket_rets[archetype].append(ret)

                # Gap risk: catalyst within 14 days
                cat_days_str = row.get("catalyst_days", "")
                try:
                    cat_days = int(float(cat_days_str))
                    if 0 < cat_days <= 14:
                        gap_risk_weight += 1.0 / len(rankings)
                        n_gap_risk += 1
                except (ValueError, TypeError):
                    pass

        if not ticker_rets:
            continue

        port_ret = sum(ticker_rets) / len(ticker_rets)
        excess = port_ret - xbi_ret

        # XBI regime at snapshot date
        regime_info = xbi_regime.get(trade_start, {})
        xbi_dd = regime_info.get("dd_pct", float("nan"))
        xbi_vol = regime_info.get("vol_ann", float("nan"))

        # Tier-level returns
        tier_a_ret = sum(tier_rets["A"]) / len(tier_rets["A"]) if tier_rets["A"] else float("nan")
        tier_b_ret = sum(tier_rets["B"]) / len(tier_rets["B"]) if tier_rets["B"] else float("nan")

        panel.append(
            {
                "as_of": as_of,
                "trade_start": trade_start,
                "trade_end": trade_end,
                "port_ret_pct": round(port_ret, 4),
                "xbi_ret_pct": round(xbi_ret, 4),
                "excess_pct": round(excess, 4),
                "xbi_dd_pct": round(xbi_dd, 2),
                "xbi_vol_ann": round(xbi_vol, 4) if not math.isnan(xbi_vol) else "",
                "n_held": len(ticker_rets),
                "n_gap_risk": n_gap_risk,
                "gap_risk_wt_pct": round(gap_risk_weight * 100, 1),
                "tier_a_ret_pct": round(tier_a_ret, 4) if not math.isnan(tier_a_ret) else "",
                "tier_b_ret_pct": round(tier_b_ret, 4) if not math.isnan(tier_b_ret) else "",
                "n_tickers_ranked": len(rankings),
                "worst_ticker": (
                    min(
                        zip(ticker_rets, [r["ticker"] for r in rankings[: len(ticker_rets)]]),
                        key=lambda x: x[0],
                    )[1]
                    if ticker_rets
                    else ""
                ),
                "worst_ret_pct": round(min(ticker_rets), 2) if ticker_rets else "",
            }
        )

    # Write CSV
    if not panel:
        print("ERROR: no data produced", file=sys.stderr)
        return

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = list(panel[0].keys())
    with open(OUTPUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(panel)
    print(f"\nWrote {len(panel)} weeks to {OUTPUT_CSV}")

    # === ANALYSIS ===
    print("\n" + "=" * 70)
    print("REGIME LOSS ANALYSIS")
    print("=" * 70)

    excess_vals = [r["excess_pct"] for r in panel]
    port_vals = [r["port_ret_pct"] for r in panel]
    xbi_vals = [r["xbi_ret_pct"] for r in panel]

    print(f"\nTotal weeks: {len(panel)}")
    print(f"Date range: {panel[0]['as_of']} to {panel[-1]['as_of']}")
    print(f"Mean weekly excess: {sum(excess_vals)/len(excess_vals):.3f}%")
    print(f"Mean weekly port:   {sum(port_vals)/len(port_vals):.3f}%")
    print(f"Mean weekly XBI:    {sum(xbi_vals)/len(xbi_vals):.3f}%")

    # Split by XBI drawdown regime
    print("\n--- BY XBI DRAWDOWN REGIME ---")
    for label, lo, hi in [
        ("Peak (dd > -5%)", -5, 0.1),
        ("Mild (-15% to -5%)", -15, -5),
        ("Moderate (-25% to -15%)", -25, -15),
        ("Severe (< -25%)", -999, -25),
    ]:
        subset = [r for r in panel if lo <= r["xbi_dd_pct"] < hi]
        if not subset:
            continue
        ex = [r["excess_pct"] for r in subset]
        pr = [r["port_ret_pct"] for r in subset]
        xr = [r["xbi_ret_pct"] for r in subset]
        gr = [r["gap_risk_wt_pct"] for r in subset]
        print(
            f"  {label:30s}  n={len(subset):3d}  "
            f"excess={sum(ex)/len(ex):+.3f}%  "
            f"port={sum(pr)/len(pr):+.3f}%  "
            f"xbi={sum(xr)/len(xr):+.3f}%  "
            f"gap_risk={sum(gr)/len(gr):.1f}%"
        )

    # Worst 20 weeks by excess
    print("\n--- WORST 20 WEEKS BY EXCESS RETURN ---")
    worst = sorted(panel, key=lambda r: r["excess_pct"])[:20]
    print(
        f"  {'Date':12s} {'Excess':>8s} {'Port':>8s} {'XBI':>8s} {'XBI_DD':>8s} {'GapRsk':>6s} {'Worst':>8s} {'Ticker':>8s}"
    )
    for r in worst:
        print(
            f"  {r['as_of']:12s} {r['excess_pct']:+8.2f} {r['port_ret_pct']:+8.2f} "
            f"{r['xbi_ret_pct']:+8.2f} {r['xbi_dd_pct']:+8.1f} {r['gap_risk_wt_pct']:6.1f} "
            f"{r['worst_ret_pct']:+8.1f} {r['worst_ticker']:>8s}"
        )

    # Best 10 weeks
    print("\n--- BEST 10 WEEKS BY EXCESS RETURN ---")
    best = sorted(panel, key=lambda r: r["excess_pct"], reverse=True)[:10]
    for r in best:
        print(
            f"  {r['as_of']:12s} {r['excess_pct']:+8.2f} {r['port_ret_pct']:+8.2f} "
            f"{r['xbi_ret_pct']:+8.2f} {r['xbi_dd_pct']:+8.1f} {r['gap_risk_wt_pct']:6.1f}"
        )

    # Gap-risk concentration vs losses
    print("\n--- GAP-RISK EXPOSURE VS EXCESS RETURN ---")
    for label, lo, hi in [
        ("No gap-risk (0%)", -0.1, 0.1),
        ("Low (0-8%)", 0.1, 8),
        ("Medium (8-16%)", 8, 16),
        ("High (>16%)", 16, 101),
    ]:
        subset = [r for r in panel if lo <= r["gap_risk_wt_pct"] < hi]
        if not subset:
            continue
        ex = [r["excess_pct"] for r in subset]
        losses = [r for r in subset if r["excess_pct"] < -3.0]
        print(
            f"  {label:25s}  n={len(subset):3d}  "
            f"excess={sum(ex)/len(ex):+.3f}%  "
            f"big_loss_weeks={len(losses)} ({100*len(losses)/len(subset):.0f}%)"
        )

    # Tier A vs B in down weeks
    print("\n--- TIER A vs B IN DOWN XBI WEEKS (xbi_ret < -2%) ---")
    down_weeks = [
        r for r in panel if r["xbi_ret_pct"] < -2.0 and r["tier_a_ret_pct"] != "" and r["tier_b_ret_pct"] != ""
    ]
    if down_weeks:
        a_rets = [r["tier_a_ret_pct"] for r in down_weeks]
        b_rets = [r["tier_b_ret_pct"] for r in down_weeks]
        print(f"  n={len(down_weeks)} down weeks")
        print(f"  Tier A mean: {sum(a_rets)/len(a_rets):+.3f}%")
        print(f"  Tier B mean: {sum(b_rets)/len(b_rets):+.3f}%")

    # Rolling 4-week excess
    print("\n--- TRAILING 4-WEEK EXCESS: DISTRIBUTION ---")
    rolling_4w = []
    for i in range(3, len(panel)):
        r4 = sum(panel[j]["excess_pct"] for j in range(i - 3, i + 1))
        rolling_4w.append((panel[i]["as_of"], r4))
    if rolling_4w:
        vals = [v for _, v in rolling_4w]
        vals.sort()
        n = len(vals)
        print(f"  n={n}")
        print(f"  p5 = {vals[int(n*0.05)]:.2f}%")
        print(f"  p10 = {vals[int(n*0.10)]:.2f}%")
        print(f"  p25 = {vals[int(n*0.25)]:.2f}%")
        print(f"  p50 = {vals[int(n*0.50)]:.2f}%")
        print(f"  p75 = {vals[int(n*0.75)]:.2f}%")
        print(f"  p90 = {vals[int(n*0.90)]:.2f}%")

        # Worst 4-week stretches
        worst_4w = sorted(rolling_4w, key=lambda x: x[1])[:10]
        print("\n  Worst 10 trailing 4-week excess:")
        for d, v in worst_4w:
            print(f"    {d}: {v:+.2f}%")

    # Correlation: XBI drawdown depth vs excess
    print("\n--- CORRELATION: XBI DRAWDOWN vs WEEKLY EXCESS ---")
    # Simple Pearson
    dd_vals = [r["xbi_dd_pct"] for r in panel]
    n = len(dd_vals)
    if n > 10:
        mean_dd = sum(dd_vals) / n
        mean_ex = sum(excess_vals) / n
        cov = sum((dd_vals[i] - mean_dd) * (excess_vals[i] - mean_ex) for i in range(n)) / n
        std_dd = (sum((d - mean_dd) ** 2 for d in dd_vals) / n) ** 0.5
        std_ex = (sum((e - mean_ex) ** 2 for e in excess_vals) / n) ** 0.5
        if std_dd > 0 and std_ex > 0:
            corr = cov / (std_dd * std_ex)
            print(f"  Pearson r(xbi_dd, excess) = {corr:.3f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
