"""Build the top-30 rank dataset for the within-bucket ranker.

For each PIT snapshot date:
  1. Take the DEM top-30 names
  2. Compute forward returns (h20, h63)
  3. Generate pairwise labels (which name outperformed)
  4. Generate ordinal labels (top/mid/bottom tercile within top-30)
  5. Join within-bucket features: options, inst_delta, catalyst type, volume

Output:
  output/ranker/top30_rank_dataset.json   — full dataset
  output/ranker/top30_pairwise.jsonl      — pairwise training rows
  output/ranker/top30_features.csv        — per-name features + labels

Usage:
    python scripts/research/build_top30_rank_dataset.py
    python scripts/research/build_top30_rank_dataset.py --start-date 2022-01-01
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import statistics
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
PIT_CACHE_DIR = REPO_ROOT / "data" / "caches" / "price_pit" / "PIT"
OUTPUT_DIR = REPO_ROOT / "output" / "ranker"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("top30_dataset")

# Features to extract from rankings.csv for within-top-30 ranking
RANKING_FEATURES = [
    "actionable_rank",
    "tier_any",
    "archetype",
    "catalyst_days",
    "catalyst_event_type",
    "catalyst_family",
    "catalyst_source",
    "is_hard_catalyst",
    "lead_program_phase",
    "therapeutic_area",
    "mom_state",
    "coinvest_tag",
    "runway_bucket",
    # Options features
    "opt_has_data",
    "opt_atm_iv",
    "opt_rr_25d",
    "opt_term_slope",
    "opt_put_call_skew",
    "opt_event_premium",
    "actual_implied_move_pctile",
    "implied_event_move",
    "opt_iv_regime",
    "opt_liquidity_ok",
    "opt_use_for_judgment",
    # Institutional
    "inst_delta_z",
    "inst_n_managers_held",
    # Clinical
    "clinical_optionality_pct_dev",
    "clinical_quality_pct",
    # Sort contributions
    "de_sort_total_adj",
    "de_sort_contrib_institutional",
    # Volume / liquidity
    "adv_20d",
    "market_cap_mm",
    # Risk
    "de_vol_60d",
    "de_beta_xbi_60d",
    "de_drawdown",
    "de_rsi_14d",
    "de_alpha_60d",
]


def load_rankings_top30(snapshot_date: str) -> list[dict]:
    """Load top-30 names with all features."""
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
    return ranked[:30]


def load_forward_returns(snapshot_date: str) -> dict[str, dict[str, float]]:
    """Load forward returns from PIT cache."""
    cache_dir = PIT_CACHE_DIR / snapshot_date
    prices_path = cache_dir / "prices.csv"
    if not prices_path.exists():
        return {}

    result = {}
    with open(prices_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").strip().upper()
            anchor = row.get("anchor_close", "").strip()
            if not ticker or not anchor:
                continue
            try:
                p0 = float(anchor)
            except ValueError:
                continue
            if p0 <= 0:
                continue

            rets = {}
            for h in ["h5", "h20", "h63"]:
                hclose = row.get(f"{h}_close", "").strip()
                if hclose:
                    try:
                        p1 = float(hclose)
                        if p1 > 0 and abs(p1 / p0 - 1) < 3.0:
                            rets[h] = (p1 / p0) - 1.0
                    except ValueError:
                        pass
            if rets:
                result[ticker] = rets
    return result


def _safe_float(v: str | None) -> float | None:
    if not v or v.strip() in ("", "N/A", "NA", "—"):
        return None
    try:
        return float(v.strip())
    except ValueError:
        return None


def extract_features(row: dict) -> dict:
    """Extract numeric and categorical features from a rankings row."""
    features = {"ticker": row.get("ticker", "").upper()}

    for f in RANKING_FEATURES:
        val = row.get(f, "")
        # Try numeric first
        numeric = _safe_float(val)
        if numeric is not None:
            features[f] = numeric
        else:
            features[f] = val.strip() if val else None

    return features


def build_dataset(start_date: str = "2020-01-01") -> dict:
    """Build the full top-30 rank dataset."""

    # Find dates with both snapshots and PIT caches
    cache_dates = sorted(
        d.name
        for d in PIT_CACHE_DIR.iterdir()
        if d.is_dir() and d.name >= start_date and (SNAPSHOT_DIR / d.name / "rankings.csv").exists()
    )
    log.info("Found %d dates with PIT caches + rankings", len(cache_dates))

    feature_rows = []
    pairwise_rows = []
    snapshot_summaries = []

    for snapshot_date in cache_dates:
        top30 = load_rankings_top30(snapshot_date)
        returns = load_forward_returns(snapshot_date)

        if len(top30) < 20:
            continue

        # Extract features and join returns
        names_with_returns = []
        for r in top30:
            ticker = r.get("ticker", "").upper()
            rets = returns.get(ticker, {})
            if "h20" not in rets:
                continue

            features = extract_features(r)
            features["snapshot_date"] = snapshot_date
            features["return_h5"] = round(rets.get("h5", 0), 6) if "h5" in rets else None
            features["return_h20"] = round(rets["h20"], 6)
            features["return_h63"] = round(rets.get("h63", 0), 6) if "h63" in rets else None

            names_with_returns.append(features)

        if len(names_with_returns) < 10:
            continue

        # Ordinal labels: top/mid/bottom tercile by h20 return
        sorted_by_ret = sorted(names_with_returns, key=lambda x: x["return_h20"], reverse=True)
        n = len(sorted_by_ret)
        t1 = n // 3
        t2 = 2 * n // 3
        for i, f in enumerate(sorted_by_ret):
            if i < t1:
                f["ordinal_label"] = "top"
                f["ordinal_rank"] = i + 1
            elif i < t2:
                f["ordinal_label"] = "mid"
                f["ordinal_rank"] = i + 1
            else:
                f["ordinal_label"] = "bottom"
                f["ordinal_rank"] = i + 1

        feature_rows.extend(names_with_returns)

        # Pairwise labels: for each pair, which outperformed at h20?
        for i in range(len(names_with_returns)):
            for j in range(i + 1, len(names_with_returns)):
                a = names_with_returns[i]
                b = names_with_returns[j]
                ret_a = a["return_h20"]
                ret_b = b["return_h20"]

                # Skip near-ties (< 50bps difference)
                if abs(ret_a - ret_b) < 0.005:
                    continue

                winner = a["ticker"] if ret_a > ret_b else b["ticker"]
                pairwise_rows.append(
                    {
                        "snapshot_date": snapshot_date,
                        "ticker_a": a["ticker"],
                        "ticker_b": b["ticker"],
                        "return_a_h20": ret_a,
                        "return_b_h20": ret_b,
                        "winner": winner,
                        "margin": abs(ret_a - ret_b),
                    }
                )

        # Snapshot summary
        h20_rets = [f["return_h20"] for f in names_with_returns]
        snapshot_summaries.append(
            {
                "date": snapshot_date,
                "n_names": len(names_with_returns),
                "n_pairs": len([p for p in pairwise_rows if p["snapshot_date"] == snapshot_date]),
                "mean_h20": round(statistics.mean(h20_rets), 4),
                "std_h20": round(statistics.stdev(h20_rets), 4) if len(h20_rets) > 1 else 0,
                "spread_top_bottom": (
                    round(
                        statistics.mean(sorted(h20_rets, reverse=True)[:10]) - statistics.mean(sorted(h20_rets)[:10]), 4
                    )
                    if len(h20_rets) >= 20
                    else None
                ),
            }
        )

    # Feature coverage stats
    feature_coverage = {}
    for f in RANKING_FEATURES:
        filled = sum(1 for r in feature_rows if r.get(f) is not None and r.get(f) != "")
        feature_coverage[f] = round(filled / max(len(feature_rows), 1), 3)

    summary = {
        "schema": "top30_rank_dataset.v1",
        "generated_at": datetime.now().isoformat(),
        "n_snapshots": len(snapshot_summaries),
        "n_feature_rows": len(feature_rows),
        "n_pairwise_rows": len(pairwise_rows),
        "date_range": (
            f"{snapshot_summaries[0]['date']} to {snapshot_summaries[-1]['date']}" if snapshot_summaries else ""
        ),
        "feature_coverage": feature_coverage,
        "snapshot_summaries": snapshot_summaries,
    }

    # Top-bottom spread stats
    spreads = [s["spread_top_bottom"] for s in snapshot_summaries if s.get("spread_top_bottom") is not None]
    if spreads:
        summary["mean_top_bottom_spread_h20"] = round(statistics.mean(spreads), 4)
        summary["median_top_bottom_spread_h20"] = round(statistics.median(spreads), 4)
        summary["spread_positive_pct"] = round(sum(1 for s in spreads if s > 0) / len(spreads), 3)

    return {
        "summary": summary,
        "feature_rows": feature_rows,
        "pairwise_rows": pairwise_rows,
    }


def main():
    parser = argparse.ArgumentParser(description="Build top-30 rank dataset")
    parser.add_argument("--start-date", default="2020-01-01")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = build_dataset(start_date=args.start_date)

    if not result.get("feature_rows"):
        log.error("No data produced")
        return

    s = result["summary"]

    # Write summary
    summary_path = OUTPUT_DIR / "top30_rank_dataset.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"summary": s}, f, indent=2)
    log.info("Wrote summary: %s", summary_path)

    # Write feature CSV
    csv_path = OUTPUT_DIR / "top30_features.csv"
    all_cols = list(result["feature_rows"][0].keys())
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["feature_rows"])
    log.info("Wrote features: %s (%d rows)", csv_path, len(result["feature_rows"]))

    # Write pairwise JSONL
    pair_path = OUTPUT_DIR / "top30_pairwise.jsonl"
    with open(pair_path, "w", encoding="utf-8") as f:
        for row in result["pairwise_rows"]:
            f.write(json.dumps(row) + "\n")
    log.info("Wrote pairwise: %s (%d rows)", pair_path, len(result["pairwise_rows"]))

    # Print summary
    print(f"\n{'='*65}")
    print("TOP-30 RANK DATASET")
    print(f"{'='*65}")
    print(f"Date range: {s['date_range']}")
    print(f"Snapshots: {s['n_snapshots']}")
    print(f"Feature rows: {s['n_feature_rows']}")
    print(f"Pairwise rows: {s['n_pairwise_rows']}")

    if s.get("mean_top_bottom_spread_h20") is not None:
        print("\nWithin-top-30 spread (h20):")
        print(f"  Mean top-10 vs bottom-10: {s['mean_top_bottom_spread_h20']:+.4f}")
        print(f"  Median:                   {s['median_top_bottom_spread_h20']:+.4f}")
        print(f"  Spread positive:          {s['spread_positive_pct']:.1%}")

    print("\nFeature coverage (top 10 / bottom 5):")
    sorted_cov = sorted(s["feature_coverage"].items(), key=lambda x: -x[1])
    for f, c in sorted_cov[:10]:
        print(f"  {f:<40} {c:.1%}")
    print("  ...")
    for f, c in sorted_cov[-5:]:
        print(f"  {f:<40} {c:.1%}")


if __name__ == "__main__":
    main()
