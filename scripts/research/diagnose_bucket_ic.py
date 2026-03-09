#!/usr/bin/env python3
"""Diagnose which features drive negative IC within a specific bucket.

For each snapshot date, filters to the target bucket, then computes
Spearman rank correlation of each candidate feature vs forward returns
at specified horizons.  Aggregates across dates to identify which
features are "wrong-way" (negative correlation with returns).

Usage:
    python3 scripts/research/diagnose_bucket_ic.py \
        --snapshot-root data/snapshots_reranked_baseline \
        --price-csv production_data/price_history.csv \
        --bucket less_binary \
        --horizons 84,126
"""
from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from eval_forward_returns import compute_forward_return, load_price_series, spearman_ic

from common.ranking_utils import backfill_columns

# Features to diagnose — covers all sort contributors + informational
DIAG_FEATURES = [
    # Sort anchor candidates
    "clinical_optionality_pct_dev",
    "alpha_cohort_pct",
    "alpha_cohort_raw",
    # Sort contributions (active or researched)
    "clinical_score_z_tier",
    "clinical_score_z",
    "clinical_alpha_z",
    "clinical_score_v2_z",
    "inst_delta_z",
    "catalyst_decay_w",
    "de_alpha_60d",
    # Catalyst features
    "catalyst_days",
    "catalyst_strength",
    # Quality / sizing
    "binary_quality_score",
    "design_quality_score",
    # Fundamental
    "composite_score",
    "score_rank_pct",
    "financial_score",
    "momentum_score",
    # Price-derived
    "de_drawdown",
    "de_rsi_14d",
    "de_vol_60d",
    "de_beta_xbi_60d",
]


def _safe_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (ValueError, TypeError):
        return None


def diagnose_bucket(
    snapshot_root: Path,
    price_csv: Path,
    bucket: str,
    horizons: List[int],
    *,
    anchor_mode: str = "prev_trading_day",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Dict[int, Dict[str, float]]]:
    """Compute per-feature Spearman IC within a bucket.

    Returns: {feature: {horizon: {mean_ic, ic_t, n_dates, pct_nonzero}}}
    """
    from decision_engine import assign_catalyst_bucket

    all_prices = load_price_series(price_csv)
    # Build sorted trading dates from all price data
    all_dates_set: set = set()
    for ticker_prices in all_prices.values():
        all_dates_set.update(ticker_prices.keys())
    sorted_dates = sorted(all_dates_set)

    snap_dates = sorted(
        d.name
        for d in snapshot_root.iterdir()
        if d.is_dir()
        and not d.name.startswith("_")
        and (d / "rankings.csv").exists()
        and len(d.name) == 10
        and d.name[4] == "-"
    )
    if date_from:
        snap_dates = [d for d in snap_dates if d >= date_from]
    if date_to:
        snap_dates = [d for d in snap_dates if d <= date_to]

    # Accumulate per-feature per-horizon IC values
    ic_accum: Dict[str, Dict[int, List[float]]] = {f: {h: [] for h in horizons} for f in DIAG_FEATURES}
    nonzero_accum: Dict[str, Dict[int, List[float]]] = {f: {h: [] for h in horizons} for f in DIAG_FEATURES}

    n_processed = 0
    for snap_date in snap_dates:
        snap_dir = snapshot_root / snap_date
        with open(snap_dir / "rankings.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows or len(rows[0]) < 50:
            continue

        backfill_columns(rows)

        # Assign catalyst_bucket if missing
        for r in rows:
            if not r.get("catalyst_bucket"):
                cd = _safe_float(r.get("catalyst_days"))
                cm = str(r.get("catalyst_mode", ""))
                r["catalyst_bucket"] = assign_catalyst_bucket(cd, cm)

        # Filter to target bucket + eligible
        bucket_rows = [r for r in rows if r.get("catalyst_bucket") == bucket and r.get("eligible") == "1"]
        if len(bucket_rows) < 5:
            continue

        # Find anchor price date
        if anchor_mode == "prev_trading_day":
            anchor_candidates = [d for d in sorted_dates if d <= snap_date]
            if not anchor_candidates:
                continue
            price_date = anchor_candidates[-1]
        else:
            price_date = snap_date

        # Compute forward returns for bucket tickers
        fwd_returns: Dict[str, Dict[int, float]] = {}
        for r in bucket_rows:
            t = r.get("ticker", "")
            if not t or t not in all_prices:
                continue
            ticker_prices = all_prices[t]
            for h in horizons:
                ret = compute_forward_return(ticker_prices, sorted_dates, price_date, h)
                if ret is not None:
                    fwd_returns.setdefault(t, {})[h] = ret

        # For each feature, compute IC vs forward returns
        for feat in DIAG_FEATURES:
            for h in horizons:
                signal = []
                returns = []
                n_nonzero = 0
                n_total = 0
                for r in bucket_rows:
                    t = r.get("ticker", "")
                    v = _safe_float(r.get(feat))
                    if v is not None and t in fwd_returns and h in fwd_returns[t]:
                        signal.append(v)
                        returns.append(fwd_returns[t][h])
                        n_total += 1
                        if abs(v) > 1e-9:
                            n_nonzero += 1

                if len(signal) >= 5:
                    ic = spearman_ic(signal, returns)
                    if ic is not None:
                        ic_accum[feat][h].append(ic)
                        nonzero_accum[feat][h].append(n_nonzero / n_total if n_total > 0 else 0)

        n_processed += 1

    # Aggregate
    results: Dict[str, Dict[int, Dict[str, float]]] = {}
    for feat in DIAG_FEATURES:
        results[feat] = {}
        for h in horizons:
            ics = ic_accum[feat][h]
            nz = nonzero_accum[feat][h]
            if len(ics) < 3:
                results[feat][h] = {
                    "mean_ic": None,
                    "ic_t": None,
                    "n_dates": len(ics),
                    "pct_nonzero": None,
                }
                continue
            mu = statistics.mean(ics)
            se = statistics.stdev(ics) / (len(ics) ** 0.5)
            t = mu / se if se > 0 else 0.0
            results[feat][h] = {
                "mean_ic": round(mu, 6),
                "ic_t": round(t, 2),
                "n_dates": len(ics),
                "pct_nonzero": round(statistics.mean(nz), 4) if nz else None,
            }

    return results


def print_diagnosis(
    results: Dict[str, Dict[int, Dict[str, float]]],
    horizons: List[int],
    bucket: str,
) -> str:
    """Format diagnosis as markdown table, sorted by |IC t-stat| descending."""
    lines = []
    lines.append(f"# Within-Bucket Feature Attribution: {bucket}")
    lines.append("")
    lines.append("Positive IC = feature ranks correctly (higher value → higher return)")
    lines.append("Negative IC = feature is **wrong-way** (higher value → lower return)")
    lines.append("")

    for h in horizons:
        lines.append(f"## {h}-Day Horizon")
        lines.append("")
        lines.append("| Feature | Mean IC | IC t | N | %NonZero | Direction |")
        lines.append("|---------|---------|------|---|----------|-----------|")

        # Sort by absolute t-stat descending
        feat_list = []
        for feat, by_h in results.items():
            m = by_h.get(h, {})
            t_val = m.get("ic_t")
            if t_val is not None:
                feat_list.append((feat, m))
        feat_list.sort(key=lambda x: abs(x[1].get("ic_t", 0)), reverse=True)

        for feat, m in feat_list:
            ic = m.get("mean_ic")
            t = m.get("ic_t")
            n = m.get("n_dates", 0)
            nz = m.get("pct_nonzero")
            if ic is None:
                continue
            direction = "WRONG" if ic < -0.02 else ("RIGHT" if ic > 0.02 else "flat")
            ic_str = f"{ic:+.4f}"
            t_str = f"{t:+.2f}"
            nz_str = f"{nz:.0%}" if nz is not None else "—"
            lines.append(f"| {feat} | {ic_str} | {t_str} | {n} | {nz_str} | {direction} |")
        lines.append("")

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Diagnose within-bucket feature IC",
    )
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--price-csv", type=Path, required=True)
    parser.add_argument("--bucket", default="less_binary")
    parser.add_argument("--horizons", default="84,126")
    parser.add_argument("--anchor-mode", default="prev_trading_day")
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    print(f"Diagnosing bucket={args.bucket}, horizons={horizons}")
    print(f"Snapshot root: {args.snapshot_root}")

    results = diagnose_bucket(
        snapshot_root=args.snapshot_root,
        price_csv=args.price_csv,
        bucket=args.bucket,
        horizons=horizons,
        anchor_mode=args.anchor_mode,
        date_from=args.date_from,
        date_to=args.date_to,
    )

    md = print_diagnosis(results, horizons, args.bucket)
    print(md)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
