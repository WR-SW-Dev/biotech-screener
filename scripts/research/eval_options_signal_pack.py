#!/usr/bin/env python3
"""Unified options signal pack evaluator (post-volume-backfill).

Tests multiple options signal lanes through the standard research battery:
raw IC, incremental IC, portfolio slices, and walk-forward stability.

Lanes:
  1. put_call_volume_ratio — directional flow before hard catalysts
  2. total_volume (z-scored) — activity level before hard catalysts
  3. cheap_vol_score — straddle mispricing vs historical fair move
  4. iv_build_deviation — deviation from baseline IV approach curve
  5. crush_ratio_realized — empirical vs modeled crush (descriptive)

All lanes filtered to hard catalysts by default.

Usage:
    python scripts/research/eval_options_signal_pack.py \
        --snapshots-dir data/snapshots \
        --price-csv production_data/price_history.csv \
        --iv-features data/research/historical_iv_features.csv \
        --event-move-table data/research/event_move_table.json \
        --event-subset hard \
        --output-dir output/options_signal_pack
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
_SCRIPTS = PROJECT_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_RESEARCH = _SCRIPTS / "research"
if str(_RESEARCH) not in sys.path:
    sys.path.insert(0, str(_RESEARCH))

from backtest_signal_robustness import residualize_ranks, spearman_rank_corr  # noqa: E402
from options_prospective_analysis import compute_forward_return, load_price_series, resolve_event_outcome  # noqa: E402

from common.hard_catalyst import classify_hard_catalyst  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

STUDY_SCHEMA = "options_signal_pack.v1"
IC_THRESHOLD = 0.05
DEFAULT_HORIZONS = [5, 21]

SIGNALS = [
    "put_call_volume_ratio",
    "total_volume_z",
    "cheap_vol_score",
    "actual_implied_move_pctile",
    "atm_iv_change_5d",
    "atm_iv_dev_from_baseline",
]
TARGETS = ["signed_gap", "abs_gap"]
CONTROLS = ["catalyst_decay_w", "opt_atm_iv"]


def _sf(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Dataset builder
# ---------------------------------------------------------------------------


def load_iv_features(path: Path) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Load → {ticker: {date: {field: val}}}."""
    index: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip().upper()
            dt = (row.get("date") or "").strip()
            if not ticker or not dt:
                continue
            index[ticker][dt] = {
                "atm_iv": _sf(row.get("atm_iv")),
                "actual_implied_move": _sf(row.get("actual_implied_move")),
                "rr_25d": _sf(row.get("rr_25d")),
                "total_volume": _sf(row.get("total_volume")),
                "put_volume": _sf(row.get("put_volume")),
                "call_volume": _sf(row.get("call_volume")),
                "put_call_volume_ratio": _sf(row.get("put_call_volume_ratio")),
            }
    return dict(index)


def _percentile(current: float, hist_vals: List[float]) -> Optional[float]:
    if math.isnan(current) or not hist_vals:
        return None
    rank = sum(1 for v in hist_vals if v <= current)
    return max(0.0, min(1.0, rank / len(hist_vals)))


def _change_n(vals: List[float], n: int) -> Optional[float]:
    if len(vals) < n + 1:
        return None
    current = vals[-1]
    prior = vals[-(n + 1)]
    if math.isnan(current) or math.isnan(prior):
        return None
    return current - prior


def build_dataset(
    snapshots_dir: Path,
    price_csv: Path,
    iv_features_path: Path,
    event_subset: str,
    hard_filter_mode: str,
    max_catalyst_days: int,
    horizons: List[int],
) -> List[Dict[str, Any]]:
    """Build enriched dataset with all signal lanes."""
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    logger.info("Loading IV features ...")
    iv_index = load_iv_features(iv_features_path)

    logger.info("Loading prices ...")
    prices = load_price_series(price_csv)

    logger.info("Loading snapshots ...")
    dataset: List[Dict[str, Any]] = []

    for d in sorted(snapshots_dir.iterdir()):
        if not d.is_dir() or not date_re.match(d.name):
            continue
        csv_path = d / "rankings.csv"
        if not csv_path.exists():
            continue
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    ticker = (row.get("ticker") or "").strip().upper()
                    if not ticker:
                        continue

                    cat_days = _sf(row.get("catalyst_days"))
                    if math.isnan(cat_days) or cat_days <= 0 or cat_days > max_catalyst_days:
                        continue

                    et = row.get("catalyst_event_type", "")
                    src = row.get("catalyst_source", "")
                    family = row.get("catalyst_family", "")

                    if event_subset == "hard":
                        if hard_filter_mode == "snapshot_native":
                            if str(row.get("is_hard_catalyst", "0")).strip() != "1":
                                continue
                        else:
                            hc = classify_hard_catalyst(et, src)
                            if not hc["is_hard_catalyst"]:
                                continue

                    snap_date = d.name
                    hist = (iv_index.get(ticker) or {}).get(snap_date, {})

                    # Base fields
                    entry: Dict[str, Any] = {
                        "date": snap_date,
                        "ticker": ticker,
                        "catalyst_days": cat_days,
                        "catalyst_family": family,
                        "catalyst_event_type": et,
                        "composite_score": _sf(row.get("composite_score")),
                        "catalyst_decay_w": _sf(row.get("catalyst_decay_w")),
                    }

                    # ATM IV (live or historical)
                    opt_atm_iv = _sf(row.get("opt_atm_iv"))
                    if math.isnan(opt_atm_iv):
                        opt_atm_iv = hist.get("atm_iv", float("nan"))
                    entry["opt_atm_iv"] = opt_atm_iv

                    # Volume signals from historical features
                    entry["put_call_volume_ratio"] = hist.get("put_call_volume_ratio", float("nan"))
                    entry["total_volume"] = hist.get("total_volume", float("nan"))

                    # Z-score total_volume within date
                    # (deferred to post-loop)
                    entry["total_volume_z"] = float("nan")

                    # Cheap vol score from live rankings
                    entry["cheap_vol_score"] = _sf(row.get("cheap_vol_score"))

                    # Surface signals (from eval_surface_alpha_pack pattern)
                    ticker_hist = iv_index.get(ticker, {})
                    prior_dates = sorted(dt for dt in ticker_hist if dt < snap_date)

                    # actual_implied_move_pctile
                    aim = hist.get("actual_implied_move", float("nan"))
                    if not math.isnan(aim) and len(prior_dates) >= 30:
                        aim_vals = [
                            ticker_hist[dt].get("actual_implied_move", float("nan")) for dt in prior_dates[-252:]
                        ]
                        aim_vals = [v for v in aim_vals if not math.isnan(v)]
                        entry["actual_implied_move_pctile"] = (
                            _percentile(aim, aim_vals) if len(aim_vals) >= 20 else float("nan")
                        )
                    else:
                        entry["actual_implied_move_pctile"] = float("nan")

                    # atm_iv_change_5d
                    if not math.isnan(opt_atm_iv) and len(prior_dates) >= 30:
                        iv_series = [ticker_hist[dt].get("atm_iv", float("nan")) for dt in prior_dates[-10:]]
                        iv_series = [v for v in iv_series if not math.isnan(v)]
                        if len(iv_series) >= 5:
                            entry["atm_iv_change_5d"] = opt_atm_iv - iv_series[-5]
                        else:
                            entry["atm_iv_change_5d"] = float("nan")
                    else:
                        entry["atm_iv_change_5d"] = float("nan")

                    # IV build-curve deviation (simple: current ATM IV vs ticker's 60d median)
                    if not math.isnan(opt_atm_iv) and len(prior_dates) >= 30:
                        recent_ivs = [ticker_hist[dt].get("atm_iv", float("nan")) for dt in prior_dates[-60:]]
                        recent_ivs = [v for v in recent_ivs if not math.isnan(v)]
                        if len(recent_ivs) >= 20:
                            med = statistics.median(recent_ivs)
                            entry["atm_iv_dev_from_baseline"] = opt_atm_iv - med
                        else:
                            entry["atm_iv_dev_from_baseline"] = float("nan")
                    else:
                        entry["atm_iv_dev_from_baseline"] = float("nan")

                    # Targets
                    ticker_prices = prices.get(ticker, {})
                    sorted_dates = sorted(ticker_prices.keys()) if ticker_prices else []
                    outcome = resolve_event_outcome(ticker_prices, sorted_dates, snap_date, int(cat_days))
                    entry["signed_gap"] = _sf(outcome.get("signed_gap"))
                    entry["abs_gap"] = _sf(outcome.get("abs_gap"))
                    for h in horizons:
                        ret = compute_forward_return(ticker_prices, sorted_dates, snap_date, h)
                        entry[f"fwd_ret_{h}d"] = ret if ret is not None else float("nan")

                    dataset.append(entry)

        except (OSError, csv.Error) as exc:
            logger.warning("Skipping %s: %s", csv_path, exc)

    # Z-score total_volume within each date
    by_date: Dict[str, List[int]] = defaultdict(list)
    for i, r in enumerate(dataset):
        by_date[r["date"]].append(i)

    for dt, indices in by_date.items():
        vols = [dataset[i]["total_volume"] for i in indices if not math.isnan(dataset[i]["total_volume"])]
        if len(vols) >= 10:
            mu = sum(vols) / len(vols)
            sd = (sum((v - mu) ** 2 for v in vols) / len(vols)) ** 0.5
            if sd > 0:
                for i in indices:
                    v = dataset[i]["total_volume"]
                    if not math.isnan(v):
                        dataset[i]["total_volume_z"] = (v - mu) / sd

    logger.info("Dataset: %d rows", len(dataset))
    return dataset


# ---------------------------------------------------------------------------
# IC battery (reused from eval_surface_alpha_pack pattern)
# ---------------------------------------------------------------------------


def _run_ic(dataset, signals, targets, min_obs):
    results = {}
    for sig in signals:
        for tgt in targets:
            pairs = [(_sf(r.get(sig)), _sf(r.get(tgt))) for r in dataset]
            pairs = [(s, t) for s, t in pairs if not math.isnan(s) and not math.isnan(t)]
            key = f"ic_{sig}_vs_{tgt}"
            if len(pairs) < min_obs:
                results[key] = {"status": "insufficient", "n": len(pairs)}
                continue
            sx, tx = zip(*pairs)
            results[key] = {"status": "ok", "n": len(pairs), "ic": round(spearman_rank_corr(list(sx), list(tx)), 6)}
    return results


def _run_incr_ic(dataset, signals, targets, controls, min_obs):
    results = {}
    for sig in signals:
        for tgt in targets:
            for ctrl in controls:
                triples = [(_sf(r.get(sig)), _sf(r.get(tgt)), _sf(r.get(ctrl))) for r in dataset]
                triples = [
                    (s, t, c) for s, t, c in triples if not math.isnan(s) and not math.isnan(t) and not math.isnan(c)
                ]
                key = f"incr_{sig}_ctrl_{ctrl}_vs_{tgt}"
                if len(triples) < min_obs:
                    results[key] = {"status": "insufficient", "n": len(triples)}
                    continue
                sx, tx, cx = zip(*triples)
                resid = residualize_ranks(list(sx), list(cx))
                ic = spearman_rank_corr(resid, list(tx))
                results[key] = {
                    "status": "ok",
                    "n": len(triples),
                    "raw_ic": round(spearman_rank_corr(list(sx), list(tx)), 6),
                    "incr_ic": round(ic, 6),
                }
    return results


def _run_slices(dataset, signals, targets, top_k, min_obs):
    results = {}
    for sig in signals:
        for tgt in targets:
            pairs = [(_sf(r.get(sig)), _sf(r.get(tgt))) for r in dataset]
            pairs = [(s, t) for s, t in pairs if not math.isnan(s) and not math.isnan(t)]
            key = f"{sig}_vs_{tgt}"
            if len(pairs) < min_obs:
                results[key] = {"status": "insufficient", "n": len(pairs)}
                continue
            pairs.sort(key=lambda x: x[0], reverse=True)
            k = min(top_k, len(pairs) // 3)
            top = [t for _, t in pairs[:k]]
            rest = [t for _, t in pairs[k:]]
            m_top = sum(top) / len(top) if top else 0
            m_rest = sum(rest) / len(rest) if rest else 0
            results[key] = {
                "status": "ok",
                "n": len(pairs),
                "top_mean": round(m_top, 6),
                "rest_mean": round(m_rest, 6),
                "spread": round(m_top - m_rest, 6),
            }
    return results


def _walkforward_monthly(dataset, signals, targets, min_obs):
    buckets: Dict[str, List[Dict]] = defaultdict(list)
    for r in dataset:
        dt = r.get("date", "")
        if len(dt) >= 7:
            buckets[dt[:7]].append(r)

    results = {}
    for sig in signals:
        periods = []
        for pkey in sorted(buckets):
            subset = buckets[pkey]
            entry = {"period": pkey, "n": len(subset)}
            for tgt in targets:
                pairs = [(_sf(r.get(sig)), _sf(r.get(tgt))) for r in subset]
                pairs = [(s, t) for s, t in pairs if not math.isnan(s) and not math.isnan(t)]
                if len(pairs) >= min_obs:
                    sx, tx = zip(*pairs)
                    entry[f"ic_{tgt}"] = round(spearman_rank_corr(list(sx), list(tx)), 6)
                    entry[f"n_{tgt}"] = len(pairs)
                else:
                    entry[f"ic_{tgt}"] = None
                    entry[f"n_{tgt}"] = len(pairs)
            periods.append(entry)
        results[sig] = periods
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified options signal pack evaluator")
    parser.add_argument("--snapshots-dir", type=Path, required=True)
    parser.add_argument("--price-csv", type=Path, required=True)
    parser.add_argument("--iv-features", type=Path, required=True)
    parser.add_argument("--event-move-table", type=Path, required=True)
    parser.add_argument("--event-subset", default="hard", choices=["hard", "all"])
    parser.add_argument("--hard-filter-mode", default="retro", choices=["retro", "snapshot_native"])
    parser.add_argument("--max-catalyst-days", type=int, default=180)
    parser.add_argument("--horizons", default="5,21")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--min-obs", type=int, default=20)
    parser.add_argument("--walkforward", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output" / "options_signal_pack")
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    targets = TARGETS + [f"fwd_ret_{h}d" for h in horizons]

    dataset = build_dataset(
        args.snapshots_dir,
        args.price_csv,
        args.iv_features,
        args.event_subset,
        args.hard_filter_mode,
        args.max_catalyst_days,
        horizons,
    )

    if not dataset:
        logger.warning("Empty dataset")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "report.json").write_text(json.dumps({"schema": STUDY_SCHEMA, "n_rows": 0}))
        return 0

    # Coverage
    coverage = {}
    for sig in SIGNALS:
        n = sum(1 for r in dataset if not math.isnan(_sf(r.get(sig))))
        coverage[sig] = {"n": n, "total": len(dataset), "pct": round(100 * n / len(dataset), 1)}
    logger.info("Coverage: %s", {k: v["pct"] for k, v in coverage.items()})

    # Battery
    logger.info("Running raw IC ...")
    raw_ics = _run_ic(dataset, SIGNALS, targets, args.min_obs)

    logger.info("Running incremental IC ...")
    incr_ics = _run_incr_ic(dataset, SIGNALS, targets, CONTROLS, args.min_obs)

    logger.info("Running portfolio slices ...")
    slices = _run_slices(dataset, SIGNALS, targets, args.top_k, args.min_obs)

    walkforward = {}
    if args.walkforward:
        logger.info("Running walk-forward ...")
        walkforward = _walkforward_monthly(dataset, SIGNALS, targets, args.min_obs)

    # Write outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Dataset CSV
    if dataset:
        ds_path = args.output_dir / "dataset.csv"
        fields = list(dataset[0].keys())
        with open(ds_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(dataset)

    n_dates = len(set(r["date"] for r in dataset))
    n_tickers = len(set(r["ticker"] for r in dataset))

    report = {
        "schema": STUDY_SCHEMA,
        "metadata": {
            "event_subset": args.event_subset,
            "hard_filter_mode": args.hard_filter_mode,
            "max_catalyst_days": args.max_catalyst_days,
            "n_rows": len(dataset),
            "n_dates": n_dates,
            "n_tickers": n_tickers,
        },
        "coverage": coverage,
        "raw_ics": raw_ics,
        "incremental_ics": incr_ics,
        "slices": slices,
        "walkforward": walkforward,
    }
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")

    # Markdown
    md = [
        "# Options Signal Pack",
        "",
        f"**Schema**: {STUDY_SCHEMA}",
        f"**Subset**: {args.event_subset} ({args.hard_filter_mode})",
        f"**Rows**: {len(dataset)}, **Dates**: {n_dates}, **Tickers**: {n_tickers}",
        "",
        "## Coverage",
        "",
        "| Signal | Valid | Total | % |",
        "|--------|-------|-------|---|",
    ]
    for sig in SIGNALS:
        c = coverage[sig]
        md.append(f"| {sig} | {c['n']} | {c['total']} | {c['pct']}% |")

    md += [
        "",
        "## Raw ICs (vs signed_gap and abs_gap)",
        "",
        "| Signal | signed_gap IC | abs_gap IC | N |",
        "|--------|--------------|-----------|---|",
    ]
    for sig in SIGNALS:
        sg = raw_ics.get(f"ic_{sig}_vs_signed_gap", {})
        ag = raw_ics.get(f"ic_{sig}_vs_abs_gap", {})
        sg_ic = f"{sg['ic']:.4f}" if sg.get("status") == "ok" else "—"
        ag_ic = f"{ag['ic']:.4f}" if ag.get("status") == "ok" else "—"
        n = sg.get("n", ag.get("n", 0))
        md.append(f"| {sig} | {sg_ic} | {ag_ic} | {n} |")

    md += [
        "",
        "## Incremental ICs (controlling for catalyst_decay_w)",
        "",
        "| Signal | signed_gap raw | incr | abs_gap raw | incr | N |",
        "|--------|---------------|------|------------|------|---|",
    ]
    for sig in SIGNALS:
        sg = incr_ics.get(f"incr_{sig}_ctrl_catalyst_decay_w_vs_signed_gap", {})
        ag = incr_ics.get(f"incr_{sig}_ctrl_catalyst_decay_w_vs_abs_gap", {})
        if sg.get("status") == "ok":
            md.append(
                f"| {sig} | {sg['raw_ic']:.4f} | {sg['incr_ic']:.4f} | {ag.get('raw_ic', '—')} | {ag.get('incr_ic', '—')} | {sg['n']} |"
            )
        else:
            md.append(f"| {sig} | — | — | — | — | {sg.get('n', 0)} |")

    md.append("")
    (args.output_dir / "report.md").write_text("\n".join(md))

    logger.info("Report → %s", args.output_dir / "report.json")

    # Print key results
    for sig in SIGNALS:
        sg = raw_ics.get(f"ic_{sig}_vs_signed_gap", {})
        ag = raw_ics.get(f"ic_{sig}_vs_abs_gap", {})
        ic_sg = sg.get("ic", "—")
        ic_ag = ag.get("ic", "—")
        logger.info("  %s: signed=%s abs=%s n=%s", sig, ic_sg, ic_ag, sg.get("n", 0))

    return 0


if __name__ == "__main__":
    sys.exit(main())
