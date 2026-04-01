"""Decompose construction drag: which portfolio rules destroy selection alpha?

Runs 4 portfolio variants on the same rankings and prices:
  1. EW Top-20: pure selection, equal weight (baseline)
  2. EW Bucketed: sleeve assignment applied, equal weight within sleeve
  3. Policy-Weighted: 55/25/10/10 budget applied, equal weight within sleeve
  4. Shadow: actual constructed portfolio (from live_shadow artifacts)

The gap between each successive variant isolates which construction
rules are responsible for the drag.

Usage:
    python scripts/research/decompose_construction_drag.py
    python scripts/research/decompose_construction_drag.py --top-n 30
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
PRICE_PATH = REPO_ROOT / "production_data" / "price_history.csv"
SHADOW_PERF_PATH = REPO_ROOT / "artifacts" / "live_shadow" / "performance.csv"
OUTPUT_DIR = REPO_ROOT / "output" / "benchmarks"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("construction_decomp")

# Sleeve bucket targets from portfolio_policy.json
BUCKET_TARGETS = {
    "binary_91_180": 0.55,
    "binary_31_90": 0.25,
    "binary_0_30": 0.10,
    "less_binary": 0.10,
}

BUCKET_TOP_K = {
    "binary_91_180": 20,
    "binary_31_90": 15,
    "binary_0_30": 10,
    "less_binary": 15,
}


def load_price_map(price_path: Path) -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = defaultdict(dict)
    with open(price_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tk = row.get("ticker", "").strip()
            dt = row.get("date", "").strip()
            cl = row.get("close", "").strip()
            if tk and dt and cl:
                try:
                    prices[dt][tk] = float(cl)
                except ValueError:
                    pass
    return dict(prices)


def load_rankings(snapshot_date: str) -> list[dict]:
    rpath = SNAPSHOT_DIR / snapshot_date / "rankings.csv"
    if not rpath.exists():
        return []
    with open(rpath, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ranked = []
    for r in rows:
        ar = r.get("actionable_rank", "").strip()
        if ar:
            try:
                r["_rank"] = int(ar)
                ranked.append(r)
            except ValueError:
                pass
    ranked.sort(key=lambda r: r["_rank"])
    return ranked


def classify_bucket(row: dict) -> str:
    """Classify a ranked name into a catalyst sleeve bucket."""
    cat_days_raw = row.get("catalyst_days", "").strip()
    try:
        cat_days = float(cat_days_raw)
    except (ValueError, TypeError):
        return "less_binary"

    if cat_days <= 0:
        return "less_binary"
    elif cat_days <= 30:
        return "binary_0_30"
    elif cat_days <= 90:
        return "binary_31_90"
    elif cat_days <= 180:
        return "binary_91_180"
    else:
        return "less_binary"


def build_variant_positions(rankings: list[dict], variant: str, top_n: int = 20) -> list[dict]:
    """Build positions for a given construction variant."""
    if variant == "ew_top_n":
        # Pure equal-weight top-N
        selected = rankings[:top_n]
        if not selected:
            return []
        w = 100.0 / len(selected)
        return [{"ticker": r["ticker"].upper(), "weight_pct": w, "bucket": "all"} for r in selected]

    elif variant == "ew_bucketed":
        # Assign to sleeves, but equal weight across all selected names
        # Take enough names to fill sleeve top-K quotas
        by_bucket: dict[str, list] = defaultdict(list)
        for r in rankings:
            bucket = classify_bucket(r)
            if len(by_bucket[bucket]) < BUCKET_TOP_K.get(bucket, 15):
                by_bucket[bucket].append(r)

        all_selected = []
        for bucket, names in by_bucket.items():
            all_selected.extend([(r, bucket) for r in names])

        if not all_selected:
            return []
        w = 100.0 / len(all_selected)
        return [{"ticker": r["ticker"].upper(), "weight_pct": w, "bucket": b} for r, b in all_selected]

    elif variant == "policy_weighted":
        # Apply 55/25/10/10 budget, equal weight within each sleeve
        by_bucket: dict[str, list] = defaultdict(list)
        for r in rankings:
            bucket = classify_bucket(r)
            if len(by_bucket[bucket]) < BUCKET_TOP_K.get(bucket, 15):
                by_bucket[bucket].append(r)

        positions = []
        for bucket, names in by_bucket.items():
            if not names:
                continue
            target_pct = BUCKET_TARGETS.get(bucket, 0.10) * 100  # e.g., 55%
            w = target_pct / len(names)
            for r in names:
                positions.append({"ticker": r["ticker"].upper(), "weight_pct": w, "bucket": bucket})
        return positions

    return []


def compute_portfolio_return(
    positions: list[dict],
    prior_prices: dict[str, float],
    current_prices: dict[str, float],
) -> dict:
    """Compute weighted portfolio return."""
    if not positions:
        return {"pnl_pct": 0.0, "n_held": 0, "sleeve_pnl": {}}

    total_weight = sum(p["weight_pct"] for p in positions)
    if total_weight == 0:
        return {"pnl_pct": 0.0, "n_held": 0, "sleeve_pnl": {}}

    weighted_return = 0.0
    sleeve_pnl: dict[str, float] = defaultdict(float)
    sleeve_weight: dict[str, float] = defaultdict(float)
    n_priced = 0

    for pos in positions:
        tk = pos["ticker"]
        w = pos["weight_pct"] / total_weight
        bucket = pos.get("bucket", "all")
        p0 = prior_prices.get(tk)
        p1 = current_prices.get(tk)
        if p0 and p1 and p0 > 0:
            ret = (p1 / p0) - 1.0
            contrib = w * ret
            weighted_return += contrib
            sleeve_pnl[bucket] += contrib * 100
            sleeve_weight[bucket] += w
            n_priced += 1

    return {
        "pnl_pct": weighted_return * 100,
        "n_held": len(positions),
        "n_priced": n_priced,
        "sleeve_pnl": dict(sleeve_pnl),
        "sleeve_weight": {k: round(v * 100, 1) for k, v in sleeve_weight.items()},
    }


def load_shadow_perf() -> dict[str, dict]:
    if not SHADOW_PERF_PATH.exists():
        return {}
    result = {}
    with open(SHADOW_PERF_PATH, encoding="utf-8") as f:
        for line in csv.reader(f):
            if len(line) >= 10 and line[0] == "live_shadow_perf.v1":
                try:
                    result[line[1]] = {
                        "pnl_pct": float(line[4]) if line[4] else 0,
                        "xbi_pct": float(line[5]) if line[5] else 0,
                    }
                except (ValueError, IndexError):
                    pass
    return result


def run_decomposition(top_n: int = 20, start_date: str = "2000-01-01") -> dict:
    log.info("Loading prices...")
    all_prices = load_price_map(PRICE_PATH)

    dates = sorted(
        d.name for d in SNAPSHOT_DIR.iterdir() if d.is_dir() and d.name >= start_date and (d / "rankings.csv").exists()
    )
    log.info("Found %d snapshot dates", len(dates))

    if len(dates) < 2:
        return {}

    shadow_perf = load_shadow_perf()
    variants = ["ew_top_n", "ew_bucketed", "policy_weighted"]

    # Build all position sets for each date
    all_positions: dict[str, dict[str, list]] = {}
    for d in dates:
        rankings = load_rankings(d)
        all_positions[d] = {}
        for v in variants:
            all_positions[d][v] = build_variant_positions(rankings, v, top_n)

    # Compute period returns
    periods = []
    for i in range(1, len(dates)):
        prior_date = dates[i - 1]
        current_date = dates[i]
        prior_prices = all_prices.get(prior_date, {})
        current_prices = all_prices.get(current_date, {})
        if not prior_prices or not current_prices:
            continue

        period = {"date": current_date, "prior_date": prior_date}

        # XBI
        xbi_p0 = prior_prices.get("XBI")
        xbi_p1 = current_prices.get("XBI")
        xbi_ret = ((xbi_p1 / xbi_p0) - 1.0) * 100 if xbi_p0 and xbi_p1 else 0
        period["xbi_pct"] = round(xbi_ret, 4)

        for v in variants:
            result = compute_portfolio_return(all_positions[prior_date][v], prior_prices, current_prices)
            period[f"{v}_pnl_pct"] = round(result["pnl_pct"], 4)
            period[f"{v}_excess"] = round(result["pnl_pct"] - xbi_ret, 4)
            period[f"{v}_n_held"] = result["n_held"]
            if v == "policy_weighted":
                period[f"{v}_sleeve_pnl"] = {k: round(v2, 4) for k, v2 in result["sleeve_pnl"].items()}

        # Shadow
        sh = shadow_perf.get(current_date)
        if sh:
            period["shadow_pnl_pct"] = sh["pnl_pct"]
            period["shadow_excess"] = round(sh["pnl_pct"] - sh["xbi_pct"], 4)

        periods.append(period)

    # Cumulative
    cums = {v: 0.0 for v in variants}
    cums["shadow"] = 0.0
    cums["xbi"] = 0.0

    for p in periods:
        cums["xbi"] += p["xbi_pct"]
        for v in variants:
            cums[v] += p.get(f"{v}_pnl_pct", 0)
        if "shadow_pnl_pct" in p:
            cums["shadow"] += p["shadow_pnl_pct"]

    # Summary
    n = len(periods)
    summary = {
        "schema": "construction_decomp.v1",
        "generated_at": datetime.now().isoformat(),
        "top_n": top_n,
        "n_periods": n,
        "date_range": f"{periods[0]['prior_date']} to {periods[-1]['date']}" if periods else "",
    }

    for v in variants:
        summary[f"{v}_cumulative_pct"] = round(cums[v], 2)
        summary[f"{v}_excess_pct"] = round(cums[v] - cums["xbi"], 2)

    summary["shadow_cumulative_pct"] = round(cums["shadow"], 2)
    summary["shadow_excess_pct"] = round(cums["shadow"] - cums["xbi"], 2)
    summary["xbi_cumulative_pct"] = round(cums["xbi"], 2)

    # Drag decomposition
    summary["drag_sleeve_assignment"] = round((cums["ew_top_n"] - cums["ew_bucketed"]), 2)
    summary["drag_budget_allocation"] = round((cums["ew_bucketed"] - cums["policy_weighted"]), 2)
    summary["drag_full_construction"] = round((cums["policy_weighted"] - cums["shadow"]), 2)
    summary["drag_total"] = round(cums["ew_top_n"] - cums["shadow"], 2)

    return {"summary": summary, "periods": periods}


def main():
    parser = argparse.ArgumentParser(description="Decompose construction drag")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--start-date", default="2000-01-01")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = run_decomposition(top_n=args.top_n, start_date=args.start_date)

    if not result:
        log.error("No results")
        return

    s = result["summary"]
    output_path = OUTPUT_DIR / f"construction_decomp_top{args.top_n}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", output_path)

    print(f"\n{'='*70}")
    print(f"CONSTRUCTION DRAG DECOMPOSITION: Top-{args.top_n}")
    print(f"{'='*70}")
    print(f"Date range: {s['date_range']}")
    print(f"Periods: {s['n_periods']}")

    print(f"\n{'Variant':<25} {'Cumulative':<15} {'Excess vs XBI':<15}")
    print(f"{'-'*25} {'-'*15} {'-'*15}")
    print(
        f"{'EW Top-'+str(args.top_n):<25} {s['ew_top_n_cumulative_pct']:>+8.2f}%      {s['ew_top_n_excess_pct']:>+8.2f}%"
    )
    print(f"{'EW Bucketed':<25} {s['ew_bucketed_cumulative_pct']:>+8.2f}%      {s['ew_bucketed_excess_pct']:>+8.2f}%")
    print(
        f"{'Policy-Weighted':<25} {s['policy_weighted_cumulative_pct']:>+8.2f}%      {s['policy_weighted_excess_pct']:>+8.2f}%"
    )
    print(f"{'Shadow (constructed)':<25} {s['shadow_cumulative_pct']:>+8.2f}%      {s['shadow_excess_pct']:>+8.2f}%")
    print(f"{'XBI':<25} {s['xbi_cumulative_pct']:>+8.2f}%")

    print(f"\n{'DRAG DECOMPOSITION':}")
    print(f"  Sleeve assignment (EW→Bucketed):     {s['drag_sleeve_assignment']:>+8.2f}%")
    print(f"  Budget allocation (Bucketed→Policy):  {s['drag_budget_allocation']:>+8.2f}%")
    print(f"  Full construction (Policy→Shadow):    {s['drag_full_construction']:>+8.2f}%")
    print(f"  {'TOTAL DRAG':>41}:  {s['drag_total']:>+8.2f}%")
    print()


if __name__ == "__main__":
    main()
