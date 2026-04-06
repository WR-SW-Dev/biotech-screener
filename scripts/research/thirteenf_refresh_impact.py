#!/usr/bin/env python3
"""13F refresh impact analysis tool.

Pre-computes the impact of a new 13F filing quarter on the Top-30 portfolio.
Designed to run BEFORE the new data arrives (using current data) and AFTER
(comparing old vs new).

Modes:
  --vulnerability   Show which current Top-30 names are at risk if sponsors exit
  --diff OLD NEW    Compare two PIT caches and show portfolio impact
  --preview         Simulate what the Top-30 would look like with decayed scores

Usage:
    python scripts/research/thirteenf_refresh_impact.py --vulnerability
    python scripts/research/thirteenf_refresh_impact.py --diff 2025-12-31 2026-03-31
    python scripts/research/thirteenf_refresh_impact.py --preview --decay-days 60
"""

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PIT_CACHE_DIR = REPO / "data" / "caches" / "sec_13f" / "PIT"
SNAPSHOTS_DIR = REPO / "data" / "snapshots"
RANKINGS_PATH = REPO / "data" / "snapshots" / "2026-04-03" / "rankings.csv"
INST_SUMMARY_PATH = REPO / "data" / "snapshots" / "2026-04-03" / "institutional_summary.json"
UNIVERSE_PATH = REPO / "production_data" / "universe.json"

FILING_HALFLIFE_DAYS = 90  # coinvest decay half-life


def load_rankings(path=RANKINGS_PATH):
    """Load rankings.csv into list of dicts with key score fields."""
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "")
            cz = row.get("coinvest_score_z", "")
            if not ticker or not cz:
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "coinvest_score_z": float(cz),
                    "inst_delta_z": float(row.get("inst_delta_z") or 0),
                    "actionable_rank": float(row.get("actionable_rank") or 999),
                    "coinvest_recency_state": row.get("coinvest_recency_state", ""),
                    "coinvest_tag": row.get("coinvest_tag", ""),
                }
            )
    return rows


def load_cache_index(cache_date):
    """Load 13F PIT cache index."""
    path = PIT_CACHE_DIR / cache_date / "index.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_cache_holdings(cache_date):
    """Load all manager holdings from a PIT cache.

    Returns dict: {ticker: {manager_name: shares}}.
    """
    cache_dir = PIT_CACHE_DIR / cache_date / "managers"
    if not cache_dir.exists():
        return {}

    idx = load_cache_index(cache_date)
    if not idx:
        return {}

    holdings = defaultdict(dict)
    for mgr in idx.get("managers", []):
        if not mgr.get("selected"):
            continue
        name = mgr["manager_name"]
        mgr_path = PIT_CACHE_DIR / cache_date / mgr["manager_json_path"]
        if not mgr_path.exists():
            continue
        data = json.loads(mgr_path.read_text())
        for h in data.get("holdings", []):
            ticker = h.get("ticker") or h.get("cusip_ticker", "")
            if ticker:
                shares = h.get("shares", 0) or h.get("value", 0)
                holdings[ticker][name] = shares

    return holdings


def decay_factor(age_days):
    """Exponential decay: half-life = FILING_HALFLIFE_DAYS."""
    return math.exp(-age_days / FILING_HALFLIFE_DAYS * math.log(2))


def vulnerability_analysis():
    """Show which current Top-30 names are most vulnerable to a 13F refresh."""
    print("=" * 70)
    print("13F REFRESH VULNERABILITY ANALYSIS")
    print("=" * 70)

    rankings = load_rankings()
    top30_coinvest = sorted(rankings, key=lambda x: x["coinvest_score_z"], reverse=True)[:30]

    with open(INST_SUMMARY_PATH) as f:
        inst = json.load(f)

    # Current filing age
    idx = load_cache_index("2026-04-03")
    periods = [m["period_of_report"] for m in idx["managers"] if m.get("selected")]
    most_common_period = Counter(periods).most_common(1)[0][0]
    filing_age = (date(2026, 4, 6) - date.fromisoformat(most_common_period)).days
    current_decay = decay_factor(filing_age)

    print(f"\n  Current filing period: {most_common_period}")
    print(f"  Filing age: {filing_age} days")
    print(f"  Decay factor: {current_decay:.3f} ({current_decay*100:.0f}% power remaining)")
    print("  Next refresh expected: ~May 15 (Q1 2026 filings)")

    # Simulate what happens at various decay ages
    refresh_age = (date(2026, 5, 15) - date.fromisoformat(most_common_period)).days
    refresh_decay = decay_factor(refresh_age)
    print(f"  At refresh (~May 15): {refresh_age} days old, decay={refresh_decay:.3f} ({refresh_decay*100:.0f}% power)")

    print(f"\n  {'Ticker':6s} {'CoinZ':>7s} {'Elite#':>7s} {'Decay@May15':>12s} {'DeltaZ':>8s} {'Risk':>8s}")
    print(f"  {'─'*6} {'─'*7} {'─'*7} {'─'*12} {'─'*8} {'─'*8}")

    vulnerable = []
    for r in top30_coinvest:
        ticker = r["ticker"]
        cz = r["coinvest_score_z"]
        elite = inst["tickers"].get(ticker, {}).get("elite_holders_count", 0)

        # Simulate score at May 15 with further decay
        # Score = raw_score * decay. Current score already has current decay applied.
        # At May 15, additional decay = refresh_decay / current_decay
        additional_decay = refresh_decay / current_decay if current_decay > 0 else 0
        decayed_cz = cz * additional_decay
        delta_cz = decayed_cz - cz

        # Risk classification
        if elite <= 3:
            risk = "HIGH"  # few sponsors, any exit drops score significantly
        elif delta_cz < -0.3:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        vulnerable.append(
            {
                "ticker": ticker,
                "coinvest_score_z": cz,
                "elite_holders": elite,
                "decayed_cz_may15": decayed_cz,
                "delta_cz": delta_cz,
                "risk": risk,
            }
        )

        flag = " <<<" if risk == "HIGH" else (" <<" if risk == "MEDIUM" else "")
        print(f"  {ticker:6s} {cz:+7.3f} {elite:>7d} {decayed_cz:+12.3f} {delta_cz:+8.3f} {risk:>8s}{flag}")

    # Summary
    high_risk = [v for v in vulnerable if v["risk"] == "HIGH"]
    medium_risk = [v for v in vulnerable if v["risk"] == "MEDIUM"]
    print(f"\n  HIGH risk (few sponsors, vulnerable to exits): {len(high_risk)}")
    for v in high_risk:
        print(f"    {v['ticker']:6s} — {v['elite_holders']} sponsors, score will decay to {v['decayed_cz_may15']:+.3f}")
    print(f"  MEDIUM risk (significant decay): {len(medium_risk)}")
    print(f"  LOW risk: {len(vulnerable) - len(high_risk) - len(medium_risk)}")

    # Borderline names that could enter Top-30 with fresh filings
    rank31_40 = sorted(rankings, key=lambda x: x["coinvest_score_z"], reverse=True)[30:40]
    print("\n  Next-in-line (rank 31-40, could enter with fresh filings):")
    for r in rank31_40:
        ticker = r["ticker"]
        elite = inst["tickers"].get(ticker, {}).get("elite_holders_count", 0)
        print(f"    {ticker:6s} coinvest_z={r['coinvest_score_z']:+.3f} elite={elite}")

    return vulnerable


def diff_analysis(old_cache_date, new_cache_date):
    """Compare two 13F PIT caches and show portfolio impact."""
    print("=" * 70)
    print(f"13F CACHE DIFF: {old_cache_date} → {new_cache_date}")
    print("=" * 70)

    old_holdings = load_cache_holdings(old_cache_date)
    new_holdings = load_cache_holdings(new_cache_date)

    if not old_holdings or not new_holdings:
        print("ERROR: Could not load one or both caches")
        return

    all_tickers = set(old_holdings.keys()) | set(new_holdings.keys())

    changes = []
    for ticker in sorted(all_tickers):
        old_mgrs = set(old_holdings.get(ticker, {}).keys())
        new_mgrs = set(new_holdings.get(ticker, {}).keys())

        entered = new_mgrs - old_mgrs
        exited = old_mgrs - new_mgrs
        common = old_mgrs & new_mgrs

        if not entered and not exited:
            continue

        changes.append(
            {
                "ticker": ticker,
                "old_count": len(old_mgrs),
                "new_count": len(new_mgrs),
                "net_delta": len(new_mgrs) - len(old_mgrs),
                "entered": sorted(entered),
                "exited": sorted(exited),
                "retained": len(common),
            }
        )

    # Sort by net delta (biggest gainers first)
    changes.sort(key=lambda x: x["net_delta"], reverse=True)

    print(f"\n  Tickers with manager changes: {len(changes)}")
    print("\n  TOP GAINERS (new sponsors):")
    for c in changes[:10]:
        if c["net_delta"] <= 0:
            break
        print(
            f"    {c['ticker']:6s} {c['old_count']}→{c['new_count']} (+{c['net_delta']}) entered: {', '.join(c['entered'][:3])}"
        )

    print("\n  TOP LOSERS (lost sponsors):")
    for c in reversed(changes[-10:]):
        if c["net_delta"] >= 0:
            break
        print(
            f"    {c['ticker']:6s} {c['old_count']}→{c['new_count']} ({c['net_delta']}) exited: {', '.join(c['exited'][:3])}"
        )

    return changes


def preview_analysis(extra_decay_days=60):
    """Show what the Top-30 would look like with additional filing decay."""
    print("=" * 70)
    print(f"13F DECAY PREVIEW (+ {extra_decay_days} days)")
    print("=" * 70)

    rankings = load_rankings()
    additional = decay_factor(extra_decay_days)

    print(f"\n  Additional decay factor: {additional:.3f} ({additional*100:.0f}% of current score)")
    print("\n  Current Top-30 vs Decayed Top-30:")

    current_top30 = set(r["ticker"] for r in sorted(rankings, key=lambda x: x["coinvest_score_z"], reverse=True)[:30])

    # Apply decay
    for r in rankings:
        r["decayed_cz"] = r["coinvest_score_z"] * additional

    decayed_top30 = set(r["ticker"] for r in sorted(rankings, key=lambda x: x["decayed_cz"], reverse=True)[:30])

    dropped = current_top30 - decayed_top30
    entered = decayed_top30 - current_top30

    print(f"\n  Overlap: {len(current_top30 & decayed_top30)}/30")
    print(f"  Dropped: {sorted(dropped)}")
    print(f"  Entered: {sorted(entered)}")
    print("\n  Note: decay alone shifts ranks but doesn't add new information.")
    print("  Fresh Q1 filings will re-score everything — decay preview is worst-case.")


def main():
    parser = argparse.ArgumentParser(description="13F refresh impact analysis")
    parser.add_argument("--vulnerability", action="store_true", help="Vulnerability analysis of current Top-30")
    parser.add_argument("--diff", nargs=2, metavar=("OLD", "NEW"), help="Diff two PIT cache dates")
    parser.add_argument("--preview", action="store_true", help="Preview decay impact")
    parser.add_argument("--decay-days", type=int, default=60, help="Extra decay days for preview")
    args = parser.parse_args()

    if args.vulnerability:
        result = vulnerability_analysis()
        out = REPO / "artifacts" / "thirteenf_refresh_vulnerability.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump({"generated": str(date.today()), "vulnerability": result}, f, indent=2)
        print(f"\nSaved: {out}")

    elif args.diff:
        diff_analysis(args.diff[0], args.diff[1])

    elif args.preview:
        preview_analysis(args.decay_days)

    else:
        # Default: vulnerability
        vulnerability_analysis()


if __name__ == "__main__":
    main()
