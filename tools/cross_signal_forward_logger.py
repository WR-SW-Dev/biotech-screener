#!/usr/bin/env python3
"""Forward cross-signal bucket logger — read-only daily snapshot.

Each weekday, reads the latest snapshot rankings.csv and tags every ticker
with its DEM-quintile × cross-signal-bucket membership. Persists membership
+ scores under artifacts/audit/cross_signal_forward_shadow/ for later
forward-return evaluation when h20d (2026-05-26) / h60d (2026-07-21) mature.

Definitions (locked tonight, do not change without a new T0):
- DEM-high: top quintile of selector_score within the snapshot's universe
- DEM-low:  bottom quintile of selector_score
- cross-signal-high: agreement_score >= 0.50
- cross-signal-low:  agreement_score <= 0.10

agreement_score = (count of top-quintile independent signals) / (count of
available independent signals). Independent signals (excludes B6 components
+ institutional block):
  clinical_score_v2_z, financial_score,
  selector_clinical_block, selector_catalyst_block,
  selector_survivability_block, selector_market_block.

Outputs (all read-only):
- artifacts/audit/cross_signal_forward_shadow/buckets_{date}.json
- artifacts/audit/cross_signal_forward_shadow/buckets.jsonl  (append)

Constraints:
- No historical alpha conclusion drawn.
- No production logic modified.
- Forward evidence only — bucket memberships are forward-collection seeds.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHADOW_DIR = REPO / "artifacts" / "audit" / "cross_signal_forward_shadow"
INDEPENDENT_SIGNALS = [
    "clinical_score_v2_z",
    "financial_score",
    "selector_clinical_block",
    "selector_catalyst_block",
    "selector_survivability_block",
    "selector_market_block",
]
CROSS_HIGH = 0.50
CROSS_LOW = 0.10
DEM_QUINTILE = 0.20  # top/bottom 20%


def f(s):
    try:
        return float(s) if s not in ("", None, "nan") else None
    except (ValueError, TypeError):
        return None


def load_snapshot(date_iso: str):
    rk = REPO / "data" / "snapshots" / date_iso / "rankings.csv"
    if not rk.exists():
        return None
    with open(rk) as fh:
        rows = [dict(r) for r in csv.DictReader(fh)]
    universe = []
    for r in rows:
        rec = {"ticker": r.get("ticker"), "selector_score": f(r.get("selector_score"))}
        for col in INDEPENDENT_SIGNALS:
            rec[col] = f(r.get(col))
        rec["actionable_rank"] = f(r.get("actionable_rank"))
        rec["coinvest_score_z"] = f(r.get("coinvest_score_z"))
        rec["inst_delta_z"] = f(r.get("inst_delta_z"))
        universe.append(rec)
    return universe


def compute_agreement_scores(universe):
    """Return {ticker: agreement_score} using percentile-rank top-quintile counting."""
    # Per-signal sorted arrays for percentile rank
    signal_arrays = {}
    for col in INDEPENDENT_SIGNALS:
        vals = [u[col] for u in universe if u.get(col) is not None]
        if len(vals) >= 50:
            signal_arrays[col] = sorted(vals)
    available = list(signal_arrays.keys())

    def pct_rank(col, x):
        arr = signal_arrays.get(col)
        if arr is None or x is None:
            return None
        below = sum(1 for v in arr if v < x)
        return below / len(arr)

    out = {}
    for u in universe:
        n_avail = 0
        n_top = 0
        per_signal = {}
        for col in available:
            v = u.get(col)
            if v is None:
                per_signal[col] = None
                continue
            n_avail += 1
            pct = pct_rank(col, v)
            per_signal[col] = round(pct, 3) if pct is not None else None
            if pct is not None and pct >= 0.80:
                n_top += 1
        score = n_top / n_avail if n_avail > 0 else None
        out[u["ticker"]] = {
            "agreement_score": round(score, 4) if score is not None else None,
            "n_available_signals": n_avail,
            "n_top_quintile_signals": n_top,
            "per_signal_percentiles": per_signal,
        }
    return out, available


def assign_bucket(selector_pct, agreement_score):
    """Return one of HH/HL/LH/LL/MIDDLE/UNDEF given percentile-of-selector and agreement_score."""
    if selector_pct is None or agreement_score is None:
        return "UNDEF"
    if selector_pct >= 1 - DEM_QUINTILE:
        dem = "H"
    elif selector_pct <= DEM_QUINTILE:
        dem = "L"
    else:
        dem = "M"
    if agreement_score >= CROSS_HIGH:
        cs = "H"
    elif agreement_score <= CROSS_LOW:
        cs = "L"
    else:
        cs = "M"
    if dem == "M" or cs == "M":
        return "MIDDLE"
    return f"{dem}{cs}"


def find_prior_bucket_file(today_iso: str):
    """Return Path of most recent buckets_*.json strictly before today_iso, or None."""
    if not SHADOW_DIR.exists():
        return None
    candidates = sorted(SHADOW_DIR.glob("buckets_*.json"))
    eligible = [p for p in candidates if p.stem.replace("buckets_", "") < today_iso]
    return eligible[-1] if eligible else None


def persistence_diagnostics(today_buckets, prior_path):
    """Per-bucket Jaccard overlap + entrants + exits + top-5 by selector_score.

    Pure membership tracking. No returns, no performance.
    """
    if prior_path is None:
        return {"prior_date": None, "note": "no prior bucket file (T0 or first run)"}
    with open(prior_path) as fh:
        prior = json.load(fh)
    prior_date = prior.get("as_of")
    prior_buckets = prior.get("bucket_membership", {})
    out = {"prior_date": prior_date, "by_bucket": {}}
    for b in ["HH", "HL", "LH", "LL"]:
        today_set = {r["ticker"] for r in today_buckets.get(b, [])}
        prior_set = {r["ticker"] for r in prior_buckets.get(b, [])}
        inter = today_set & prior_set
        union = today_set | prior_set
        jaccard = len(inter) / len(union) if union else None
        entrants = today_set - prior_set
        exits = prior_set - today_set
        today_scored = {r["ticker"]: r["selector_score"] for r in today_buckets.get(b, [])}
        prior_scored = {r["ticker"]: r["selector_score"] for r in prior_buckets.get(b, [])}
        top5_entrants = sorted(
            [(t, today_scored.get(t)) for t in entrants if today_scored.get(t) is not None],
            key=lambda x: -x[1],
        )[:5]
        top5_exits = sorted(
            [(t, prior_scored.get(t)) for t in exits if prior_scored.get(t) is not None],
            key=lambda x: -x[1],
        )[:5]
        out["by_bucket"][b] = {
            "today_count": len(today_set),
            "prior_count": len(prior_set),
            "intersection_count": len(inter),
            "jaccard": round(jaccard, 4) if jaccard is not None else None,
            "entrants": sorted(entrants),
            "exits": sorted(exits),
            "top5_entrants_by_today_selector": top5_entrants,
            "top5_exits_by_prior_selector": top5_exits,
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--as-of", default=None, help="Snapshot date (YYYY-MM-DD). Default: today.")
    args = p.parse_args()
    as_of = args.as_of or datetime.now().date().isoformat()

    universe = load_snapshot(as_of)
    if universe is None:
        print(f"FATAL: data/snapshots/{as_of}/rankings.csv not found", file=sys.stderr)
        return 2

    # Filter to ranked universe
    rankable = [u for u in universe if u["selector_score"] is not None]
    n = len(rankable)
    if n < 50:
        print(f"FATAL: rankable universe too small (n={n})", file=sys.stderr)
        return 2

    # Selector percentile rank (for DEM quintile assignment)
    sorted_scores = sorted([u["selector_score"] for u in rankable])
    score_to_pct = {}
    for i, s in enumerate(sorted_scores):
        score_to_pct[s] = (i + 1) / n  # 1..n / n in [1/n .. 1]
    # Use index of last occurrence for ties (rank-based)
    selector_pct = {u["ticker"]: score_to_pct[u["selector_score"]] for u in rankable}

    agreement, available = compute_agreement_scores(rankable)

    # Bucket assignment
    bucket_membership = {"HH": [], "HL": [], "LH": [], "LL": [], "MIDDLE": [], "UNDEF": []}
    for u in rankable:
        t = u["ticker"]
        ag = agreement.get(t, {})
        ag_score = ag.get("agreement_score")
        sp = selector_pct.get(t)
        b = assign_bucket(sp, ag_score)
        rec = {
            "ticker": t,
            "selector_score": u["selector_score"],
            "selector_percentile": round(sp, 4) if sp is not None else None,
            "agreement_score": ag_score,
            "n_available_signals": ag.get("n_available_signals"),
            "actionable_rank": int(u["actionable_rank"]) if u["actionable_rank"] else None,
            "coinvest_score_z": u["coinvest_score_z"],
            "inst_delta_z": u["inst_delta_z"],
        }
        bucket_membership[b].append(rec)

    summary = {b: len(v) for b, v in bucket_membership.items()}

    # Persistence vs prior bucket file (purely membership-based; no returns)
    prior_path = find_prior_bucket_file(as_of)
    persistence = persistence_diagnostics(bucket_membership, prior_path)

    out = {
        "as_of": as_of,
        "schema_era_T0": "2026-04-28",
        "n_universe_rankable": n,
        "definitions": {
            "DEM_high": f"top {DEM_QUINTILE:.0%} by selector_score",
            "DEM_low": f"bottom {DEM_QUINTILE:.0%} by selector_score",
            "cross_signal_high": f"agreement_score >= {CROSS_HIGH}",
            "cross_signal_low": f"agreement_score <= {CROSS_LOW}",
            "independent_signals_used": available,
            "n_available_independent_signals": len(available),
        },
        "summary": summary,
        "bucket_membership": bucket_membership,
        "persistence_vs_prior": persistence,
        "constraints": [
            "Read-only forward logger — no historical alpha conclusion drawn.",
            "Bucket memberships persisted for forward-return evaluation at h20d (2026-05-26) and h60d (2026-07-21).",
            "Independent signals exclude B6 components (coinvest_score_z, inst_delta_z) and institutional block.",
            "Methodology fixed at T0=2026-04-28; do not change cutoffs without a new T0.",
            "persistence_vs_prior is membership-only; performance evaluation deferred to h20d/h60d.",
        ],
    }

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SHADOW_DIR / f"buckets_{as_of}.json"
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    with open(SHADOW_DIR / "buckets.jsonl", "a") as fh:
        # Trim to summary + counts for the running log; full membership lives in per-day file
        fh.write(json.dumps({"as_of": as_of, "summary": summary, "n_universe": n}) + "\n")

    # Console summary
    print(f"=== cross-signal forward bucket log — as_of={as_of}, n={n} ===")
    print(f"available signals: {available} ({len(available)}/{len(INDEPENDENT_SIGNALS)})")
    for b in ["HH", "HL", "LH", "LL", "MIDDLE", "UNDEF"]:
        print(f"  {b}: {summary.get(b, 0)} tickers")
    # Show HL tickers (the focal bucket)
    hl_names = sorted([r["ticker"] for r in bucket_membership["HL"]])
    print(f"  HL (DEM-high / cross-signal-low) tickers: {hl_names}")
    # Persistence
    if persistence.get("prior_date"):
        print(f"\n=== persistence vs prior ({persistence['prior_date']}) ===")
        for b in ["HH", "HL", "LH", "LL"]:
            d = persistence["by_bucket"].get(b, {})
            ents = ", ".join(t for t, _ in d.get("top5_entrants_by_today_selector", []))
            exs = ", ".join(t for t, _ in d.get("top5_exits_by_prior_selector", []))
            print(
                f"  {b}: today={d.get('today_count')}  prior={d.get('prior_count')}  "
                f"∩={d.get('intersection_count')}  J={d.get('jaccard')}  "
                f"entrants[{len(d.get('entrants', []))}]:{ents}  exits[{len(d.get('exits', []))}]:{exs}"
            )
    else:
        print(f"\npersistence: {persistence.get('note')}")
    print(f"\nartifact: {out_path}")
    print("No historical alpha conclusion drawn.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
