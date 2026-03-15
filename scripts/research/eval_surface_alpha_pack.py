#!/usr/bin/env python3
"""Hard-catalyst surface alpha pack (Spec 019).

Evaluates 6 options surface signals against 4 targets on hard-catalyst
rows only, using the standard research decision framework.

Signals: cheap_vol_score, opt_rr_25d, opt_put_call_skew,
         actual_implied_move_pctile, rr_25d_change_5d, atm_iv_change_5d

Targets: signed_gap, abs_gap, fwd_ret_5d, fwd_ret_21d

Usage:
    python scripts/research/eval_surface_alpha_pack.py \
        --snapshots-dir data/snapshots \
        --price-csv production_data/price_history.csv \
        --iv-features data/research/historical_iv_features.csv \
        --event-move-table data/research/event_move_table.json \
        [--event-subset hard] \
        [--max-catalyst-days 180] \
        [--horizons 5,21] \
        [--output-dir output/surface_alpha_pack]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
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

STUDY_SCHEMA = "surface_alpha_pack.v1"
IC_THRESHOLD = 0.05
DEFAULT_HORIZONS = [5, 21]
DEFAULT_SIGNALS = [
    "cheap_vol_score",
    "opt_rr_25d",
    "opt_put_call_skew",
    "actual_implied_move_pctile",
    "rr_25d_change_5d",
    "atm_iv_change_5d",
]
TARGETS = ["signed_gap", "abs_gap", "fwd_ret_5d", "fwd_ret_21d"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sf(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _mean(vals: List[float]) -> float:
    clean = [v for v in vals if not math.isnan(v)]
    return sum(clean) / len(clean) if clean else float("nan")


# ---------------------------------------------------------------------------
# Dataset construction
# ---------------------------------------------------------------------------


def load_rankings_snapshots(
    snapshots_dir: Path,
) -> List[Dict[str, Any]]:
    """Load rankings.csv from all dated snapshot directories."""
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    rows: List[Dict[str, Any]] = []

    for d in sorted(snapshots_dir.iterdir()):
        if not d.is_dir() or not date_re.match(d.name):
            continue
        csv_path = d / "rankings.csv"
        if not csv_path.exists():
            continue
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    row["snap_date"] = d.name
                    rows.append(row)
        except (OSError, csv.Error) as exc:
            logger.warning("Skipping %s: %s", csv_path, exc)

    return rows


def load_iv_features(path: Path) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Load historical_iv_features.csv → {ticker: {date: {field: val}}}."""
    index: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip().upper()
            dt = (row.get("date") or "").strip()
            if not ticker or not dt:
                continue
            index[ticker][dt] = {
                "atm_iv": _sf(row.get("atm_iv")),
                "rr_25d": _sf(row.get("rr_25d")),
                "atm_straddle_price": _sf(row.get("atm_straddle_price")),
                "actual_implied_move": _sf(row.get("actual_implied_move")),
            }
    return index


def _trading_days_back(dt_str: str, n: int, dates_set: set) -> Optional[str]:
    """Find the date n trading days before dt_str from dates_set."""
    sorted_dates = sorted(d for d in dates_set if d < dt_str)
    if len(sorted_dates) >= n:
        return sorted_dates[-n]
    return None


def _percentile_in_window(
    ticker: str,
    dt_str: str,
    field: str,
    iv_index: Dict[str, Dict[str, Dict[str, float]]],
    window: int = 60,
    min_obs: int = 20,
) -> float:
    """Compute percentile of current value vs trailing window."""
    ticker_data = iv_index.get(ticker, {})
    if dt_str not in ticker_data:
        return float("nan")
    current = ticker_data[dt_str].get(field, float("nan"))
    if math.isnan(current):
        return float("nan")

    sorted_dates = sorted(d for d in ticker_data if d < dt_str)[-window:]
    vals = [ticker_data[d].get(field, float("nan")) for d in sorted_dates]
    vals = [v for v in vals if not math.isnan(v)]
    if len(vals) < min_obs:
        return float("nan")

    rank = sum(1 for v in vals if v <= current)
    return rank / len(vals)


def _change_n_days(
    ticker: str,
    dt_str: str,
    field: str,
    iv_index: Dict[str, Dict[str, Dict[str, float]]],
    n: int = 5,
) -> float:
    """Compute change in field over n trading days."""
    ticker_data = iv_index.get(ticker, {})
    if dt_str not in ticker_data:
        return float("nan")
    current = ticker_data[dt_str].get(field, float("nan"))
    if math.isnan(current):
        return float("nan")

    prior_dt = _trading_days_back(dt_str, n, set(ticker_data.keys()))
    if prior_dt is None or prior_dt not in ticker_data:
        return float("nan")
    prior = ticker_data[prior_dt].get(field, float("nan"))
    if math.isnan(prior):
        return float("nan")

    return current - prior


def build_dataset(
    snapshots_dir: Path,
    price_csv: Path,
    iv_features_path: Path,
    event_move_table_path: Path,
    event_subset: str = "hard",
    max_catalyst_days: int = 180,
    horizons: List[int] = None,
) -> List[Dict[str, Any]]:
    """Build enriched dataset for surface alpha evaluation."""
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    logger.info("Loading rankings snapshots from %s ...", snapshots_dir)
    raw_rows = load_rankings_snapshots(snapshots_dir)
    logger.info("Loaded %d raw rows", len(raw_rows))

    logger.info("Loading price series ...")
    prices = load_price_series(price_csv)

    logger.info("Loading IV features from %s ...", iv_features_path)
    iv_index = load_iv_features(iv_features_path)

    # Load event move table (reserved for cheap_vol_score recomputation)
    logger.info("Loading event move table ...")
    with open(event_move_table_path, encoding="utf-8") as f:
        _move_table = json.load(f)  # noqa: F841 — will be used when cheap_vol_score is populated

    dataset: List[Dict[str, Any]] = []

    for row in raw_rows:
        ticker = (row.get("ticker") or "").strip().upper()
        snap_date = row.get("snap_date", "")
        if not ticker or not snap_date:
            continue

        # Hard catalyst filter
        et = row.get("catalyst_event_type", "")
        src = row.get("catalyst_source", "")
        hc = classify_hard_catalyst(et, src)

        if event_subset == "hard" and not hc["is_hard_catalyst"]:
            continue

        # Catalyst days filter
        cat_days = _sf(row.get("catalyst_days"), float("nan"))
        if math.isnan(cat_days) or cat_days > max_catalyst_days or cat_days <= 0:
            continue

        # Base fields from rankings
        entry = {
            "date": snap_date,
            "ticker": ticker,
            "is_hard_catalyst": 1 if hc["is_hard_catalyst"] else 0,
            "catalyst_days": cat_days,
            "catalyst_family": row.get("catalyst_family", ""),
            "catalyst_event_type": et,
            "catalyst_source": src,
            "composite_score": _sf(row.get("composite_score")),
            "catalyst_decay_w": _sf(row.get("catalyst_decay_w")),
        }

        # Live chain fields from rankings
        entry["opt_rr_25d"] = _sf(row.get("opt_rr_25d"))
        entry["opt_put_call_skew"] = _sf(row.get("opt_put_call_skew"))
        entry["cheap_vol_score"] = _sf(row.get("cheap_vol_score"))
        entry["vol_classification"] = row.get("vol_classification", "")
        entry["atm_iv"] = _sf(row.get("opt_atm_iv"))

        # Historical IV features: join by (ticker, date)
        hist = (iv_index.get(ticker) or {}).get(snap_date, {})
        # If live fields missing, fill from historical
        if math.isnan(entry["atm_iv"]):
            entry["atm_iv"] = hist.get("atm_iv", float("nan"))
        if math.isnan(entry["opt_rr_25d"]):
            entry["opt_rr_25d"] = hist.get("rr_25d", float("nan"))

        entry["atm_straddle_price"] = hist.get("atm_straddle_price", float("nan"))
        entry["actual_implied_move"] = hist.get("actual_implied_move", float("nan"))

        # Derived signals
        entry["actual_implied_move_pctile"] = _percentile_in_window(
            ticker,
            snap_date,
            "actual_implied_move",
            iv_index,
            window=60,
            min_obs=20,
        )
        entry["rr_25d_change_5d"] = _change_n_days(
            ticker,
            snap_date,
            "rr_25d",
            iv_index,
            n=5,
        )
        entry["atm_iv_change_5d"] = _change_n_days(
            ticker,
            snap_date,
            "atm_iv",
            iv_index,
            n=5,
        )

        # Targets: event outcome
        ticker_prices = prices.get(ticker, {})
        sorted_dates = sorted(ticker_prices.keys()) if ticker_prices else []
        outcome = resolve_event_outcome(
            ticker_prices,
            sorted_dates,
            snap_date,
            int(cat_days),
        )
        entry["signed_gap"] = _sf(outcome.get("signed_gap"))
        entry["abs_gap"] = _sf(outcome.get("abs_gap"))

        # Forward returns
        for h in horizons:
            ret = compute_forward_return(ticker_prices, sorted_dates, snap_date, h)
            entry[f"fwd_ret_{h}d"] = ret if ret is not None else float("nan")

        dataset.append(entry)

    logger.info("Dataset: %d rows (%s subset)", len(dataset), event_subset)
    return dataset


# ---------------------------------------------------------------------------
# Evaluation battery
# ---------------------------------------------------------------------------


def _run_ic_tests(
    dataset: List[Dict[str, Any]],
    signals: List[str],
    targets: List[str],
    min_obs: int,
) -> Dict[str, Dict[str, Any]]:
    """Raw Spearman IC for each signal × target."""
    results = {}
    for sig in signals:
        for tgt in targets:
            pairs = [(_sf(r.get(sig)), _sf(r.get(tgt))) for r in dataset]
            pairs = [(s, t) for s, t in pairs if not math.isnan(s) and not math.isnan(t)]
            key = f"ic_{sig}_vs_{tgt}"
            if len(pairs) < min_obs:
                results[key] = {"status": "insufficient_sample", "n": len(pairs)}
                continue
            sx, tx = zip(*pairs)
            ic = spearman_rank_corr(list(sx), list(tx))
            results[key] = {"status": "ok", "n": len(pairs), "ic": round(ic, 6)}
    return results


def _run_incremental_ic(
    dataset: List[Dict[str, Any]],
    signals: List[str],
    targets: List[str],
    controls: List[str],
    min_obs: int,
) -> Dict[str, Dict[str, Any]]:
    """IC after residualizing signal against controls."""
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
                    results[key] = {"status": "insufficient_sample", "n": len(triples)}
                    continue
                sx, tx, cx = zip(*triples)
                resid = residualize_ranks(list(sx), list(cx))
                ic = spearman_rank_corr(resid, list(tx))
                results[key] = {
                    "status": "ok",
                    "n": len(triples),
                    "raw_ic": round(spearman_rank_corr(list(sx), list(tx)), 6),
                    "incremental_ic": round(ic, 6),
                }
    return results


def _run_portfolio_slices(
    dataset: List[Dict[str, Any]],
    signals: List[str],
    targets: List[str],
    top_k: int,
    min_obs: int,
) -> Dict[str, Dict[str, Any]]:
    """Top-K vs rest mean for each signal × target."""
    results = {}
    for sig in signals:
        for tgt in targets:
            pairs = [(r, _sf(r.get(sig)), _sf(r.get(tgt))) for r in dataset]
            pairs = [(r, s, t) for r, s, t in pairs if not math.isnan(s) and not math.isnan(t)]
            key = f"{sig}_vs_{tgt}"
            if len(pairs) < min_obs:
                results[key] = {"status": "insufficient_sample", "n": len(pairs)}
                continue

            pairs.sort(key=lambda x: x[1], reverse=True)
            k = min(top_k, len(pairs) // 3)
            top_vals = [t for _, _, t in pairs[:k]]
            rest_vals = [t for _, _, t in pairs[k:]]
            results[key] = {
                "status": "ok",
                "n": len(pairs),
                "top_k": k,
                "top_mean": round(_mean(top_vals), 6),
                "rest_mean": round(_mean(rest_vals), 6),
                "spread": round(_mean(top_vals) - _mean(rest_vals), 6),
            }
    return results


def _run_subgroup_splits(
    dataset: List[Dict[str, Any]],
    signals: List[str],
    min_obs: int,
) -> Dict[str, Dict[str, Any]]:
    """IC splits by catalyst_family and catalyst_days bucket."""
    splits = {}

    def _ic_for_subset(subset, sig, tgt):
        pairs = [(_sf(r.get(sig)), _sf(r.get(tgt))) for r in subset]
        pairs = [(s, t) for s, t in pairs if not math.isnan(s) and not math.isnan(t)]
        if len(pairs) < min_obs:
            return {"n": len(pairs), "ic": None}
        sx, tx = zip(*pairs)
        return {"n": len(pairs), "ic": round(spearman_rank_corr(list(sx), list(tx)), 6)}

    for sig in signals:
        # By catalyst_family
        for fam in ("CLINICAL", "REGULATORY"):
            sub = [r for r in dataset if r.get("catalyst_family") == fam]
            key = f"{sig}_family_{fam}"
            splits[key] = _ic_for_subset(sub, sig, "signed_gap")

        # By catalyst_days bucket
        near = [r for r in dataset if _sf(r.get("catalyst_days")) <= 90]
        far = [r for r in dataset if 90 < _sf(r.get("catalyst_days")) <= 180]
        splits[f"{sig}_cat_0_90d"] = _ic_for_subset(near, sig, "signed_gap")
        splits[f"{sig}_cat_91_180d"] = _ic_for_subset(far, sig, "signed_gap")

    return splits


# ---------------------------------------------------------------------------
# Decision rule
# ---------------------------------------------------------------------------


def _decide(raw_ics: dict, incr_ics: dict) -> Dict[str, Any]:
    """Apply decision rule per signal."""
    decisions = {}
    for sig in DEFAULT_SIGNALS:
        # Find best raw IC across targets
        signed_ic = None
        abs_ic = None
        fwd_ic = None
        for key, val in raw_ics.items():
            if val.get("status") != "ok":
                continue
            if key == f"ic_{sig}_vs_signed_gap":
                signed_ic = val["ic"]
            elif key == f"ic_{sig}_vs_abs_gap":
                abs_ic = val["ic"]
            elif key == f"ic_{sig}_vs_fwd_ret_21d":
                fwd_ic = val["ic"]

        # Check incremental survival (both controls)
        survives_timing = False
        survives_quality = False
        for key, val in incr_ics.items():
            if val.get("status") != "ok":
                continue
            if sig in key and "catalyst_decay_w" in key:
                if abs(val.get("incremental_ic", 0)) >= IC_THRESHOLD:
                    survives_timing = True
            if sig in key and "composite_score" in key:
                if abs(val.get("incremental_ic", 0)) >= IC_THRESHOLD:
                    survives_quality = True

        has_signed = signed_ic is not None and abs(signed_ic) >= IC_THRESHOLD
        has_fwd = fwd_ic is not None and abs(fwd_ic) >= IC_THRESHOLD
        has_abs = abs_ic is not None and abs(abs_ic) >= IC_THRESHOLD

        if (has_signed or has_fwd) and survives_timing and survives_quality:
            verdict = "ALPHA_CANDIDATE"
        elif has_abs and survives_timing:
            verdict = "RISK_OVERLAY_CANDIDATE"
        elif has_signed or has_fwd or has_abs:
            verdict = "SIGNAL_PRESENT_BUT_NOT_INCREMENTAL"
        else:
            verdict = "ABANDON"

        decisions[sig] = {
            "verdict": verdict,
            "signed_gap_ic": signed_ic,
            "abs_gap_ic": abs_ic,
            "fwd_ret_21d_ic": fwd_ic,
            "survives_timing": survives_timing,
            "survives_quality": survives_quality,
        }

    return decisions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Hard-catalyst surface alpha pack (Spec 019)")
    parser.add_argument("--snapshots-dir", type=Path, required=True)
    parser.add_argument("--price-csv", type=Path, required=True)
    parser.add_argument("--iv-features", type=Path, required=True)
    parser.add_argument("--event-move-table", type=Path, required=True)
    parser.add_argument("--event-subset", default="hard", choices=["hard", "all"])
    parser.add_argument("--max-catalyst-days", type=int, default=180)
    parser.add_argument("--signals", default=None, help="Comma-separated signal override")
    parser.add_argument("--horizons", default="5,21")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--min-obs", type=int, default=30)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output" / "surface_alpha_pack")
    args = parser.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    signals = args.signals.split(",") if args.signals else DEFAULT_SIGNALS
    targets = ["signed_gap", "abs_gap"] + [f"fwd_ret_{h}d" for h in horizons]

    # Build dataset
    dataset = build_dataset(
        args.snapshots_dir,
        args.price_csv,
        args.iv_features,
        args.event_move_table,
        event_subset=args.event_subset,
        max_catalyst_days=args.max_catalyst_days,
        horizons=horizons,
    )

    if not dataset:
        logger.warning("Empty dataset — no hard-catalyst rows with data")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "schema": STUDY_SCHEMA,
            "metadata": {"n_rows": 0, "event_subset": args.event_subset},
            "decision": {},
        }
        (args.output_dir / "surface_alpha_pack_report.json").write_text(json.dumps(report, indent=2))
        return 0

    # Signal coverage
    coverage = {}
    for sig in signals:
        n_valid = sum(1 for r in dataset if not math.isnan(_sf(r.get(sig))))
        coverage[sig] = {"n_valid": n_valid, "n_total": len(dataset), "pct": round(100 * n_valid / len(dataset), 1)}
    logger.info("Signal coverage: %s", {k: v["pct"] for k, v in coverage.items()})

    # Run battery
    logger.info("Running raw IC tests ...")
    raw_ics = _run_ic_tests(dataset, signals, targets, args.min_obs)

    logger.info("Running incremental IC tests ...")
    controls = ["catalyst_decay_w", "composite_score"]
    incr_ics = _run_incremental_ic(dataset, signals, targets, controls, args.min_obs)

    logger.info("Running portfolio slices ...")
    slices = _run_portfolio_slices(dataset, signals, targets, args.top_k, args.min_obs)

    logger.info("Running subgroup splits ...")
    subgroups = _run_subgroup_splits(dataset, signals, args.min_obs)

    logger.info("Computing decision rule ...")
    decisions = _decide(raw_ics, incr_ics)

    # Write dataset CSV
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ds_path = args.output_dir / "surface_alpha_pack_dataset.csv"
    if dataset:
        fields = list(dataset[0].keys())
        with open(ds_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(dataset)
        logger.info("Dataset → %s (%d rows)", ds_path, len(dataset))

    # Build report
    n_hard = sum(1 for r in dataset if r.get("is_hard_catalyst") == 1)
    snap_dates = sorted(set(r["date"] for r in dataset))
    tickers = sorted(set(r["ticker"] for r in dataset))

    report = {
        "schema": STUDY_SCHEMA,
        "metadata": {
            "event_subset": args.event_subset,
            "max_catalyst_days": args.max_catalyst_days,
            "n_rows": len(dataset),
            "n_hard": n_hard,
            "n_snap_dates": len(snap_dates),
            "snap_dates": snap_dates,
            "n_tickers": len(tickers),
            "horizons": horizons,
            "signals": signals,
            "min_obs": args.min_obs,
            "top_k": args.top_k,
        },
        "signal_coverage": coverage,
        "raw_ics": raw_ics,
        "incremental_ics": incr_ics,
        "portfolio_slices": slices,
        "subgroup_splits": subgroups,
        "decision": decisions,
    }

    json_path = args.output_dir / "surface_alpha_pack_report.json"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n")

    # Write markdown summary
    md_lines = [
        "# Hard-Catalyst Surface Alpha Pack",
        "",
        f"**Schema**: {STUDY_SCHEMA}",
        f"**Event subset**: {args.event_subset}",
        f"**Rows**: {len(dataset)} ({n_hard} hard)",
        f"**Snapshots**: {len(snap_dates)}",
        f"**Tickers**: {len(tickers)}",
        "",
        "## Signal Coverage",
        "",
        "| Signal | Valid | Total | Coverage |",
        "|--------|-------|-------|----------|",
    ]
    for sig in signals:
        c = coverage.get(sig, {})
        md_lines.append(f"| {sig} | {c.get('n_valid', 0)} | {c.get('n_total', 0)} | {c.get('pct', 0)}% |")

    md_lines += [
        "",
        "## Decision Summary",
        "",
        "| Signal | Verdict | signed_gap IC | abs_gap IC | fwd_21d IC | Timing | Quality |",
        "|--------|---------|---------------|------------|------------|--------|---------|",
    ]
    for sig in signals:
        d = decisions.get(sig, {})
        md_lines.append(
            f"| {sig} | **{d.get('verdict', '?')}** "
            f"| {d.get('signed_gap_ic', '—')} "
            f"| {d.get('abs_gap_ic', '—')} "
            f"| {d.get('fwd_ret_21d_ic', '—')} "
            f"| {'Y' if d.get('survives_timing') else 'N'} "
            f"| {'Y' if d.get('survives_quality') else 'N'} |"
        )

    md_lines += ["", "## Raw ICs", "", "| Test | IC | N |", "|------|----|---|"]
    for key, val in sorted(raw_ics.items()):
        ic_str = f"{val['ic']:.4f}" if val.get("status") == "ok" else "—"
        md_lines.append(f"| {key} | {ic_str} | {val.get('n', 0)} |")

    md_lines.append("")
    md_path = args.output_dir / "surface_alpha_pack_report.md"
    md_path.write_text("\n".join(md_lines))

    logger.info("Report → %s", json_path)
    logger.info("Report → %s", md_path)

    # Print decision summary
    for sig, d in decisions.items():
        logger.info("  %s: %s", sig, d["verdict"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
