#!/usr/bin/env python
"""Analyze top 10 biotech companies by composite score: compute 6M momentum, volatility, max drawdown."""
import csv
import json
import os
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))

# ── 1. Load snapshot ──────────────────────────────────────────────────────
with open(os.path.join(BASE, "output", "snapshot_2024-04-01.json")) as f:
    snap = json.load(f)

companies = snap["ranked_securities"]
# Sort by composite_rank (already sorted, but be explicit)
companies_sorted = sorted(companies, key=lambda c: c["composite_rank"])
top10 = companies_sorted[:10]
top10_tickers = [c["ticker"] for c in top10]

print("=" * 80)
print("SNAPSHOT 2024-04-01 — All 25 Companies (composite rank order)")
print("=" * 80)
print(f"{'Rank':>4}  {'Ticker':>6}  {'Comp':>7}  {'FinRaw':>8}  {'FinNorm':>8}  {'Sev':>5}  Flags")
print("-" * 80)
for c in companies_sorted:
    flags = ", ".join(c.get("flags", []))
    fr = c.get("financial_raw")
    fn = c.get("financial_normalized")
    print(f"{c['composite_rank']:>4}  {c['ticker']:>6}  {c['composite_score']:>7}  "
          f"{str(fr):>8}  {str(fn):>8}  {c.get('severity',''):>5}  {flags}")

print("\nTop 10 tickers:", top10_tickers)

# ── 2. Load daily prices ───────────────────────────────────────────────────
prices = {}  # ticker -> [(date, price), ...]
with open(os.path.join(BASE, "data", "daily_prices.csv")) as f:
    reader = csv.DictReader(f)
    for row in reader:
        t = row["ticker"]
        if t not in top10_tickers:
            continue
        d = datetime.strptime(row["date"], "%Y-%m-%d")
        p = float(row["adj_close"])
        prices.setdefault(t, []).append((d, p))

# Sort by date for each ticker
for t in prices:
    prices[t].sort(key=lambda x: x[0])

# ── 3. Compute metrics ────────────────────────────────────────────────────
# For 6-month momentum: use the last available date and ~126 trading days prior.
# Volatility: annualized std of daily returns over the full available history.
# Max drawdown: peak-to-trough over full history.

import math

results = {}
for t in top10_tickers:
    series = prices.get(t, [])
    if not series:
        results[t] = {"momentum6m": None, "volatility": None, "max_dd": None,
                       "n_days": 0, "last_price": None, "first_price": None}
        continue

    dates = [d for d, _ in series]
    px = [p for _, p in series]
    n = len(px)

    # 6-month momentum: compare last price to price ~126 trading days ago
    lookback = min(126, n - 1) if n > 1 else 0
    if lookback > 0:
        momentum = (px[-1] / px[-1 - lookback] - 1) * 100
    else:
        momentum = None

    # Daily returns for volatility
    rets = []
    for i in range(1, n):
        if px[i - 1] != 0:
            rets.append((px[i] / px[i - 1]) - 1)

    if rets:
        mean_r = sum(rets) / len(rets)
        var_r = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
        daily_vol = math.sqrt(var_r)
        annual_vol = daily_vol * math.sqrt(252) * 100  # annualized, in percent
    else:
        annual_vol = None

    # Max drawdown
    peak = px[0]
    max_dd = 0.0
    for p in px:
        if p > peak:
            peak = p
        dd = (peak - p) / peak * 100 if peak != 0 else 0
        if dd > max_dd:
            max_dd = dd

    results[t] = {
        "momentum6m": momentum,
        "volatility": annual_vol,
        "max_dd": max_dd,
        "n_days": n,
        "last_price": px[-1],
        "first_price": px[0],
        "last_date": dates[-1].strftime("%Y-%m-%d"),
        "first_date": dates[0].strftime("%Y-%m-%d"),
    }

# ── 4. Print detailed results ──────────────────────────────────────────────
print("\n" + "=" * 100)
print("PRICE-BASED METRICS (Top 10 by Composite Score)")
print("=" * 100)
for t in top10_tickers:
    r = results[t]
    if r["n_days"] == 0:
        print(f"{t}: NO PRICE DATA AVAILABLE")
        continue
    print(f"\n  {t}:")
    print(f"    Price history: {r['first_date']} → {r['last_date']}  ({r['n_days']} trading days)")
    print(f"    Start price: ${r['first_price']:.2f}   Last price: ${r['last_price']:.2f}")
    print(f"    6M Momentum:   {r['momentum6m']:+.2f}%" if r['momentum6m'] is not None else "    6M Momentum:   N/A")
    print(f"    Volatility:    {r['volatility']:.2f}%/yr" if r['volatility'] is not None else "    Volatility:    N/A")
    print(f"    Max Drawdown:  {r['max_dd']:.2f}%")

# ── 5. Financial health rating ────────────────────────────────────────────
# Heuristic: combine financial_normalized, flags, and price-based risk.
# If financial_raw is null → no fundamental financial data available → "Weak" (no financials to assess).
# If flags contain financial distress indicators → "Weak".
# Use volatility & drawdown as supplementary signals:
#   vol < 40% and max_dd < 30% → no additional stress
#   vol > 70% or max_dd > 50% → stress override toward weaker

def health_rating(company, result):
    """Rate financial health.

    NOTE: financial_raw is null for ALL companies in this snapshot, meaning no
    fundamental financial data (balance sheet, cash burn, runway, etc.) was
    available at the PIT cutoff. financial_normalized = 50.00 is a median-rank
    fill, not a real measurement. Therefore the rating is derived primarily
    from price-based risk signals (volatility, max drawdown, momentum) as a
    proxy for market-implied financial distress.

    Rating bands:
      Strong    — vol < 35%, max_dd < 40%, momentum >= 0%
      Moderate  — vol 35-55%, max_dd 40-60%, OR (low vol but negative momentum)
      Weak      — vol > 55% OR max_dd > 60% OR momentum < -30%
    """
    fin_raw = company.get("financial_raw")
    vol = result["volatility"] or 0
    mdd = result["max_dd"] or 0
    mom = result["momentum6m"] if result["momentum6m"] is not None else 0

    # If fundamental financial data exists, use it as the primary signal
    if fin_raw is not None:
        fin_score = float(fin_raw) / 100 if fin_raw else 0
        if fin_score >= 0.7:
            base = "Strong"
        elif fin_score >= 0.4:
            base = "Moderate"
        else:
            base = "Weak"
        if vol > 80 or mdd > 55:
            if base == "Strong":
                base = "Moderate"
        return base

    # No fundamental data → use price-based risk as proxy
    if vol > 55 or mdd > 60 or mom < -30:
        return "Weak"
    if vol < 35 and mdd < 40 and mom >= 0:
        return "Strong"
    return "Moderate"

print("\n" + "=" * 100)
print("FINANCIAL HEALTH RATING LOGIC")
print("=" * 100)
for c in top10:
    t = c["ticker"]
    r = results[t]
    rating = health_rating(c, r)
    print(f"  {t:>6}: fin_raw={c['financial_raw']}, fin_norm={c['financial_normalized']}, "
          f"sev={c['severity']}, vol={r['volatility']}, mdd={r['max_dd']:.1f}% → {rating}")

# ── 6. Build markdown table ────────────────────────────────────────────────
print("\n" + "=" * 100)
print("MARKDOWN SUMMARY TABLE")
print("=" * 100)

header = "| Ticker | Composite Score | 6M Momentum % | Volatility % | Max Drawdown % | Financial Health Rating |"
sep    = "|--------|----------------|---------------|-------------|----------------|--------------------------|"
print(header)
print(sep)
for c in top10:
    t = c["ticker"]
    r = results[t]
    rating = health_rating(c, r)
    mom = f"{r['momentum6m']:+.1f}" if r['momentum6m'] is not None else "N/A"
    vol = f"{r['volatility']:.1f}" if r['volatility'] is not None else "N/A"
    mdd = f"{r['max_dd']:.1f}" if r['max_dd'] is not None else "N/A"
    print(f"| {t:>6} | {c['composite_score']:>14} | {mom:>13} | {vol:>11} | {mdd:>14} | {rating:>24} |")

# ── 7. Strongest / Weakest summary ─────────────────────────────────────────
print("\n" + "=" * 100)
print("STRONGEST vs WEAKEST FINANCIAL HEALTH")
print("=" * 100)

ranked = []
for c in top10:
    t = c["ticker"]
    r = results[t]
    rating = health_rating(c, r)
    # Simple score: lower volatility + lower drawdown = stronger
    vol = r["volatility"] or 999
    mdd = r["max_dd"] or 999
    risk_score = vol + mdd
    ranked.append((t, rating, vol, mdd, risk_score))

ranked.sort(key=lambda x: x[4])  # ascending risk = strongest first

print("\nStrongest financial health signals (lowest price-based risk):")
for t, rating, vol, mdd, rs in ranked[:3]:
    print(f"  {t}: rating={rating}, vol={vol:.1f}%, max_dd={mdd:.1f}%")

print("\nWeakest financial health signals (highest price-based risk):")
for t, rating, vol, mdd, rs in ranked[-3:]:
    print(f"  {t}: rating={rating}, vol={vol:.1f}%, max_dd={mdd:.1f}%")

print("\n✅ Analysis complete.")
