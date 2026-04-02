#!/usr/bin/env python3
"""Phase 2 signal evidence for Spec 041 — milestone optionality overlay.

Tests whether milestone_deadline_ev_pct predicts forward returns
on the dev subset, using the standard Spearman rank-IC framework.

Usage:
    python3 scripts/research/eval_milestone_signal.py
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from common.clinical_pos_prior import get_clinical_pos_prior
from common.milestone_optionality import compute_universe_milestone_features


def _load_price_series(price_csv: Path) -> Dict[str, Dict[str, float]]:
    """Load price_history.csv into {ticker: {date_str: close}}."""
    series: Dict[str, Dict[str, float]] = {}
    with open(price_csv) as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row.get("ticker") or row.get("symbol", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return series


def _forward_return(prices: Dict[str, float], snap_date: str, horizon_days: int) -> Optional[float]:
    """Compute forward return from snap_date over horizon_days trading days."""
    sorted_dates = sorted(prices.keys())
    try:
        idx = sorted_dates.index(snap_date)
    except ValueError:
        # Find nearest date on or after
        candidates = [d for d in sorted_dates if d >= snap_date]
        if not candidates:
            return None
        idx = sorted_dates.index(candidates[0])

    target_idx = idx + horizon_days
    if target_idx >= len(sorted_dates):
        return None

    p0 = prices.get(sorted_dates[idx])
    p1 = prices.get(sorted_dates[target_idx])
    if p0 and p1 and p0 > 0:
        return (p1 - p0) / p0
    return None


def _spearman_rank_corr(x: List[float], y: List[float]) -> Optional[float]:
    """Simple Spearman rank correlation."""
    n = len(x)
    if n < 5:
        return None

    def _rank(vals):
        indexed = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        for rank_pos, orig_idx in enumerate(indexed):
            ranks[orig_idx] = float(rank_pos)
        return ranks

    rx = _rank(x)
    ry = _rank(y)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den_x = sum((rx[i] - mean_rx) ** 2 for i in range(n)) ** 0.5
    den_y = sum((ry[i] - mean_ry) ** 2 for i in range(n)) ** 0.5
    if den_x < 1e-9 or den_y < 1e-9:
        return None
    return num / (den_x * den_y)


def main() -> int:
    # --- Config ---
    horizons = [5, 20, 63, 84]
    min_obs_per_date = 10
    prior_path = PROJECT_ROOT / "production_data" / "clinical_pos_priors_v3.json"
    if not prior_path.exists():
        prior_path = PROJECT_ROOT / "production_data" / "clinical_pos_priors_v2.json"
    price_csv = PROJECT_ROOT / "production_data" / "price_history.csv"
    snapshots_dir = PROJECT_ROOT / "data" / "snapshots"
    pdufa_path = PROJECT_ROOT / "production_data" / "pdufa_dates.json"
    desig_path = PROJECT_ROOT / "production_data" / "fda_designations.json"

    # --- Load static data ---
    print("Loading prices...")
    price_series = _load_price_series(price_csv)
    print(f"  {len(price_series)} tickers")

    with open(pdufa_path) as f:
        pdufa_entries = json.load(f)
    with open(desig_path) as f:
        fda_designations = json.load(f).get("designations", [])

    def pos_fn(phase, endpoint="other"):
        return get_clinical_pos_prior(phase, endpoint, prior_path)

    # --- Find snapshot dates ---
    # Limit to 2024+ where we have decent price coverage for forward returns
    all_snap_dates = sorted(
        [
            d.name
            for d in snapshots_dir.iterdir()
            if d.is_dir()
            and not d.name.startswith("_")
            and "__pre" not in d.name
            and (d / "rankings.csv").exists()
            and d.name >= "2024-01-01"
        ]
    )
    # Monthly sampling — one per calendar month (last available) to keep runtime sane
    by_month: Dict[str, str] = {}
    for d in all_snap_dates:
        by_month[d[:7]] = d
    snap_dates = sorted(by_month.values())
    print(f"Snapshots: {len(snap_dates)} dates ({snap_dates[0]} to {snap_dates[-1]})")

    # --- Load trial records per snapshot date ---
    ctgov_dir = PROJECT_ROOT / "cache" / "ctgov"

    # --- Evaluate signal IC per snapshot date ---
    ic_by_horizon: Dict[int, List[float]] = {h: [] for h in horizons}
    date_details: List[Dict[str, Any]] = []

    for snap_date in snap_dates:
        snap_dir = snapshots_dir / snap_date
        rankings_path = snap_dir / "rankings.csv"

        with open(rankings_path) as f:
            rankings_rows = list(csv.DictReader(f))

        # Find closest trial_records
        trial_path = ctgov_dir / f"trial_records_{snap_date}.json"
        if not trial_path.exists():
            candidates = sorted(ctgov_dir.glob("trial_records_*.json"))
            candidates = [c for c in candidates if c.stem.split("_")[-1] <= snap_date]
            trial_path = candidates[-1] if candidates else None
        if not trial_path or not trial_path.exists():
            continue

        try:
            with open(trial_path) as f:
                trial_records = json.load(f)
            if not isinstance(trial_records, list):
                continue
            if trial_records and not isinstance(trial_records[0], dict):
                continue
        except Exception:
            continue

        as_of = date.fromisoformat(snap_date)

        # Compute milestone features
        results = compute_universe_milestone_features(
            rankings_rows=rankings_rows,
            trial_records=trial_records,
            pdufa_entries=pdufa_entries,
            fda_designations=fda_designations,
            as_of_date=as_of,
            pos_prior_fn=pos_fn,
        )

        # Filter to dev-stage names with active milestones and nonzero EV
        active_tickers = [
            t for t, r in results.items() if r.milestone_count_active > 0 and r.milestone_deadline_ev_pct > 0
        ]

        if len(active_tickers) < min_obs_per_date:
            continue

        detail = {"date": snap_date, "n_active": len(active_tickers)}

        for horizon in horizons:
            signals = []
            returns = []
            for t in active_tickers:
                fwd = _forward_return(price_series.get(t, {}), snap_date, horizon)
                if fwd is not None:
                    signals.append(results[t].milestone_deadline_ev_pct)
                    returns.append(fwd)

            if len(signals) >= min_obs_per_date:
                ic = _spearman_rank_corr(signals, returns)
                if ic is not None:
                    ic_by_horizon[horizon].append(ic)
                    detail[f"ic_{horizon}d"] = round(ic, 4)
                    detail[f"n_{horizon}d"] = len(signals)

        date_details.append(detail)

    # --- Report ---
    print(f"\n{'='*60}")
    print(f"MILESTONE OPTIONALITY SIGNAL IC — {len(date_details)} dates evaluated")
    print(f"{'='*60}\n")

    print(f"{'Horizon':>8} {'N dates':>8} {'Mean IC':>8} {'Med IC':>8} {'Std':>8} {'Pos%':>6} {'t-stat':>8}")
    print("-" * 60)
    summary = {}
    for h in horizons:
        ics = ic_by_horizon[h]
        if not ics:
            print(f"{h:>5}d    {'N/A':>8}")
            continue
        mean_ic = statistics.mean(ics)
        med_ic = statistics.median(ics)
        std_ic = statistics.stdev(ics) if len(ics) > 1 else 0
        pos_pct = sum(1 for x in ics if x > 0) / len(ics) * 100
        t_stat = mean_ic / (std_ic / len(ics) ** 0.5) if std_ic > 0 else 0
        print(f"{h:>5}d   {len(ics):>8} {mean_ic:>8.4f} {med_ic:>8.4f} {std_ic:>8.4f} {pos_pct:>5.1f}% {t_stat:>8.2f}")
        summary[f"{h}d"] = {
            "n_dates": len(ics),
            "mean_ic": round(mean_ic, 4),
            "median_ic": round(med_ic, 4),
            "std_ic": round(std_ic, 4),
            "positive_pct": round(pos_pct, 1),
            "t_stat": round(t_stat, 2),
        }

    # --- Verdict ---
    print(f"\n{'='*60}")
    print("VERDICT")
    print(f"{'='*60}")

    primary_horizon = 84 if 84 in ic_by_horizon and ic_by_horizon[84] else max(horizons)
    primary_ics = ic_by_horizon.get(primary_horizon, [])
    if primary_ics:
        mean_primary = statistics.mean(primary_ics)
        if mean_primary >= 0.05:
            verdict = "PROMISING"
        elif mean_primary >= 0.02:
            verdict = "NEEDS_MORE"
        elif mean_primary >= -0.02:
            verdict = "NEUTRAL"
        else:
            verdict = "REJECT"
        print(f"Primary horizon ({primary_horizon}d): mean IC = {mean_primary:.4f} → {verdict}")
    else:
        verdict = "INSUFFICIENT_DATA"
        print("Insufficient data for primary horizon")

    # Check guardrail: no horizon worse than -0.05
    guardrail_breach = False
    for h in horizons:
        ics = ic_by_horizon[h]
        if ics and statistics.mean(ics) < -0.05:
            print(f"  GUARDRAIL BREACH: {h}d mean IC = {statistics.mean(ics):.4f} < -0.05")
            guardrail_breach = True

    if guardrail_breach:
        verdict = "REJECT"
        print("Final verdict: REJECT (guardrail breach)")
    else:
        print(f"Final verdict: {verdict}")

    # --- Save ---
    out_dir = PROJECT_ROOT / "output" / "milestone_optionality"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "signal_evidence.json"
    packet = {
        "schema": "milestone_signal_evidence.v1",
        "signal": "milestone_deadline_ev_pct",
        "n_dates": len(date_details),
        "horizons": {str(h): summary.get(f"{h}d", {}) for h in horizons},
        "verdict": verdict,
        "guardrail_breach": guardrail_breach,
        "per_date": date_details,
    }
    with open(out_path, "w") as f:
        json.dump(packet, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
