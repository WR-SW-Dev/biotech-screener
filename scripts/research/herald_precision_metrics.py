#!/usr/bin/env python3
"""Herald precision metrics -- classification accuracy measurement.

Computes precision/recall/F1 using multiple ground-truth sources:
  B1: CRT cross-reference (agreement rate)
  B2: Price-reaction validation (informational + severity checks)
  B3: Full P/R/F1 from human-labeled ground truth
  B4: Source reliability breakdown

Usage:
    python scripts/research/herald_precision_metrics.py --as-of-date 2026-04-05
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

CLASSIFIED_DIR = PROJECT_ROOT / "data" / "press_releases" / "classified"
RESOLUTIONS_DIR = PROJECT_ROOT / "data" / "snapshots" / "resolutions"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
GROUND_TRUTH_DIR = PROJECT_ROOT / "artifacts" / "herald_ground_truth"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "herald_precision"

SCHEMA = "herald_precision_metrics.v1"

logger = logging.getLogger(__name__)


# ---- Data loading ----


def load_classified_records(classified_dir: Path, max_days: int = 30) -> list[dict]:
    """Load recent classified press releases."""
    records = []
    for f in sorted(classified_dir.glob("classified_*.jsonl"), reverse=True)[:max_days]:
        for line in f.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def load_crt_resolutions(resolutions_dir: Path) -> list[dict]:
    """Load all CRT resolution records."""
    resolutions = []
    if not resolutions_dir.exists():
        return resolutions
    for month_dir in resolutions_dir.iterdir():
        if not month_dir.is_dir():
            continue
        for f in month_dir.glob("*.json"):
            try:
                resolutions.append(json.loads(f.read_text()))
            except Exception:
                pass
    return resolutions


def load_price_history(price_csv_path: Path, tickers: set[str], lookback_days: int = 90) -> dict[str, dict[str, float]]:
    """Load price history: {ticker: {date_str: close}}."""
    cutoff = (date.today() - timedelta(days=lookback_days * 2)).isoformat()
    prices: dict[str, dict[str, float]] = defaultdict(dict)
    if not price_csv_path.exists():
        return prices
    with open(price_csv_path) as f:
        for row in csv.DictReader(f):
            tk = row.get("ticker", "").strip()
            dt = row.get("date", "").strip()
            cl = row.get("close", "")
            if tk in tickers and dt >= cutoff and cl:
                try:
                    prices[tk][dt] = float(cl)
                except ValueError:
                    pass
    return dict(prices)


def load_ground_truth(ground_truth_dir: Path) -> list[dict]:
    """Load the most recent ground truth sample JSONL."""
    files = sorted(ground_truth_dir.glob("sample_*.jsonl"), reverse=True)
    if not files:
        return []
    records = []
    for line in files[0].read_text().splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


# ---- B1: CRT cross-reference ----


def crt_cross_reference(classified: list[dict], resolutions: list[dict], match_window_days: int = 3) -> dict[str, Any]:
    """Match Herald -> CRT resolutions, compute agreement rates."""
    res_index: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for r in resolutions:
        tk = r.get("ticker", "")
        cd = r.get("catalyst_date", "")
        if tk and cd:
            res_index[tk].append((cd, r))

    type_to_cat = {
        "PDUFA_ACTION": "regulatory",
        "NDA_BLA_FILING": "regulatory",
        "REGULATORY_DESIGNATION": "regulatory",
        "ADVISORY_COMMITTEE": "regulatory",
        "PHASE_3_READOUT": "clinical",
        "PHASE_2_READOUT": "clinical",
        "PHASE_1_DATA": "clinical",
        "DATA_READOUT": "clinical",
    }

    matches = []
    for rec in classified:
        tk = rec.get("ticker", "")
        pub = rec.get("published_at_utc", "")[:10]
        cat = rec.get("event_category", "")
        if not tk or not pub or cat not in ("clinical", "regulatory", "safety"):
            continue
        if tk not in res_index:
            continue
        try:
            pub_d = datetime.strptime(pub, "%Y-%m-%d").date()
        except ValueError:
            continue
        for cat_date_str, res in res_index[tk]:
            try:
                cat_d = datetime.strptime(cat_date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if abs((pub_d - cat_d).days) <= match_window_days:
                crt_cat = type_to_cat.get(res.get("catalyst_type", ""), "other")
                matches.append(
                    {
                        "ticker": tk,
                        "herald_category": cat,
                        "crt_category": crt_cat,
                        "category_agree": cat == crt_cat,
                        "herald_outcome": rec.get("event_outcome_guess", ""),
                        "crt_outcome": (res.get("outcome", "") or "").lower(),
                        "outcome_agree": (
                            rec.get("event_outcome_guess", "").lower() == (res.get("outcome", "") or "").lower()
                        ),
                    }
                )
                break

    n = len(matches)
    cat_agree = sum(1 for m in matches if m["category_agree"])
    out_agree = sum(1 for m in matches if m["outcome_agree"])

    return {
        "n_matched": n,
        "category_agreement_rate": round(cat_agree / max(n, 1), 3),
        "outcome_agreement_rate": round(out_agree / max(n, 1), 3),
        "matches": matches[:20],  # top 20 for inspection
    }


# ---- B2: Price-reaction validation ----


def _get_return(prices: dict[str, dict[str, float]], ticker: str, dt_str: str) -> float | None:
    """Get 1-day return for ticker on date (or nearest trading day after)."""
    tk_prices = prices.get(ticker, {})
    if not tk_prices:
        return None
    sorted_dates = sorted(tk_prices.keys())
    # Find dt_str or next available date
    idx = None
    for i, d in enumerate(sorted_dates):
        if d >= dt_str:
            idx = i
            break
    if idx is None or idx == 0:
        return None
    p0 = tk_prices.get(sorted_dates[idx - 1])
    p1 = tk_prices.get(sorted_dates[idx])
    if p0 and p1 and p0 > 0:
        return (p1 / p0) - 1
    return None


def _compute_ticker_vol_thresholds(
    prices: dict[str, dict[str, float]],
    multiplier: float = 2.0,
    floor_pct: float = 10.0,
) -> dict[str, float]:
    """Compute per-ticker threshold = max(floor, multiplier * median |daily ret|).

    Biotech small-caps routinely move 5%+ on random days. A fixed 5% threshold
    produces ~25% false rate matching the base rate. Vol-adjusted thresholds
    flag only moves that are unusual *for that ticker*.
    """
    thresholds: dict[str, float] = {}
    for tk, tk_prices in prices.items():
        sorted_dates = sorted(tk_prices.keys())
        if len(sorted_dates) < 20:
            thresholds[tk] = floor_pct
            continue
        abs_rets = []
        for i in range(1, len(sorted_dates)):
            p0 = tk_prices[sorted_dates[i - 1]]
            p1 = tk_prices[sorted_dates[i]]
            if p0 > 0:
                abs_rets.append(abs((p1 / p0) - 1) * 100)
        if not abs_rets:
            thresholds[tk] = floor_pct
            continue
        abs_rets.sort()
        median = abs_rets[len(abs_rets) // 2]
        thresholds[tk] = max(floor_pct, median * multiplier)
    return thresholds


def informational_price_check(
    classified: list[dict],
    prices: dict[str, dict[str, float]],
    threshold_pct: float = 10.0,
    vol_adjusted: bool = True,
    vol_multiplier: float = 2.0,
    vol_floor_pct: float = 10.0,
) -> dict[str, Any]:
    """Check informational_only records for surprise price moves.

    Default uses vol-adjusted thresholds: flag only when the move exceeds
    max(floor, 2x median |daily return|) for that ticker. This avoids
    false-flagging normal biotech volatility (~25% of days have >5% moves).
    """
    if vol_adjusted:
        ticker_thresholds = _compute_ticker_vol_thresholds(prices, vol_multiplier, vol_floor_pct)
    else:
        ticker_thresholds = {}

    checked = 0
    surprised = 0
    examples: list[dict] = []

    for rec in classified:
        if not rec.get("informational_only"):
            continue
        tk = rec.get("ticker", "")
        dt = rec.get("published_at_utc", "")[:10]
        ret = _get_return(prices, tk, dt)
        if ret is None:
            continue
        checked += 1
        thresh = ticker_thresholds.get(tk, threshold_pct) if vol_adjusted else threshold_pct
        if abs(ret) * 100 > thresh:
            surprised += 1
            if len(examples) < 10:
                examples.append(
                    {
                        "ticker": tk,
                        "date": dt,
                        "headline": rec.get("headline", "")[:80],
                        "return_pct": round(ret * 100, 2),
                        "threshold_pct": round(thresh, 1),
                    }
                )

    return {
        "n_checked": checked,
        "n_surprised": surprised,
        "false_informational_rate": round(surprised / max(checked, 1), 3),
        "threshold_mode": "vol_adjusted" if vol_adjusted else "fixed",
        "threshold_pct": threshold_pct,
        "vol_multiplier": vol_multiplier if vol_adjusted else None,
        "vol_floor_pct": vol_floor_pct if vol_adjusted else None,
        "examples": examples,
    }


def severity_price_check(
    classified: list[dict],
    prices: dict[str, dict[str, float]],
    min_move_pct: float = 3.0,
) -> dict[str, Any]:
    """Check critical/high severity records for material price moves."""
    checked = 0
    with_move = 0
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "with_move": 0})

    for rec in classified:
        sev = rec.get("severity", "")
        if sev not in ("critical", "high"):
            continue
        tk = rec.get("ticker", "")
        dt = rec.get("published_at_utc", "")[:10]
        ret = _get_return(prices, tk, dt)
        if ret is None:
            continue
        checked += 1
        cat = rec.get("event_category", "unknown")
        by_category[cat]["n"] += 1
        if abs(ret) * 100 > min_move_pct:
            with_move += 1
            by_category[cat]["with_move"] += 1

    return {
        "n_checked": checked,
        "n_with_move": with_move,
        "severity_reaction_rate": round(with_move / max(checked, 1), 3),
        "min_move_pct": min_move_pct,
        "by_category": dict(by_category),
    }


# ---- B3: Full P/R/F1 from ground truth ----


def compute_category_metrics(labeled: list[dict]) -> dict[str, dict[str, float]]:
    """Per-category precision, recall, F1 using gt_event_category as truth."""
    # Only use records with human or CRT labels
    valid = [r for r in labeled if r.get("gt_event_category")]
    if not valid:
        return {}

    categories = set()
    for r in valid:
        categories.add(r.get("event_category", "unknown"))
        categories.add(r["gt_event_category"])

    metrics = {}
    for cat in sorted(categories):
        tp = sum(1 for r in valid if r.get("event_category") == cat and r["gt_event_category"] == cat)
        fp = sum(1 for r in valid if r.get("event_category") == cat and r["gt_event_category"] != cat)
        fn = sum(1 for r in valid if r.get("event_category") != cat and r["gt_event_category"] == cat)
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)
        metrics[cat] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support": tp + fn,
            "n_predicted": tp + fp,
        }

    return metrics


def compute_flag_metrics(labeled: list[dict]) -> dict[str, dict[str, float]]:
    """Precision/recall for boolean flags using gt_* counterparts."""
    flag_pairs = [
        ("informational_only", "gt_informational_only"),
        ("safety_signal_flag", "gt_noise"),  # noise as proxy
    ]
    metrics = {}
    for pred_key, gt_key in flag_pairs:
        valid = [r for r in labeled if r.get(gt_key) is not None]
        if not valid:
            continue
        tp = sum(1 for r in valid if r.get(pred_key) and r.get(gt_key))
        fp = sum(1 for r in valid if r.get(pred_key) and not r.get(gt_key))
        fn = sum(1 for r in valid if not r.get(pred_key) and r.get(gt_key))
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        metrics[pred_key] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "n_valid": len(valid),
        }
    return metrics


# ---- B4: Source reliability ----


def precision_by_source_type(classified: list[dict]) -> dict[str, dict[str, Any]]:
    """Precision breakdown by source_type. Noise rate per source."""
    by_source: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n_records": 0, "n_informational": 0, "n_high_severity": 0}
    )
    for rec in classified:
        src = rec.get("source_type", "unknown") or "unknown"
        by_source[src]["n_records"] += 1
        if rec.get("informational_only"):
            by_source[src]["n_informational"] += 1
        if rec.get("severity") in ("critical", "high"):
            by_source[src]["n_high_severity"] += 1

    result = {}
    for src, counts in sorted(by_source.items()):
        n = counts["n_records"]
        result[src] = {
            "n_records": n,
            "informational_rate": round(counts["n_informational"] / max(n, 1), 3),
            "high_severity_rate": round(counts["n_high_severity"] / max(n, 1), 3),
        }
    return result


# ---- Main report builder ----


def build_metrics_report(
    classified_dir: Path,
    price_csv_path: Path,
    ground_truth_dir: Path,
    resolutions_dir: Path,
    as_of_date: str,
) -> dict[str, Any]:
    """Build the complete metrics report."""
    classified = load_classified_records(classified_dir)
    resolutions = load_crt_resolutions(resolutions_dir)

    tickers = {r.get("ticker", "") for r in classified}
    prices = load_price_history(price_csv_path, tickers)

    ground_truth = load_ground_truth(ground_truth_dir)

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "as_of_date": as_of_date,
        "n_classified": len(classified),
        "n_resolutions": len(resolutions),
        "n_ground_truth": len(ground_truth),
    }

    # B1
    report["crt_cross_reference"] = crt_cross_reference(classified, resolutions)

    # B2
    report["informational_price_check"] = informational_price_check(classified, prices)
    report["severity_price_check"] = severity_price_check(classified, prices)

    # B3
    if ground_truth:
        report["category_metrics"] = compute_category_metrics(ground_truth)
        report["flag_metrics"] = compute_flag_metrics(ground_truth)
    else:
        report["category_metrics"] = None
        report["flag_metrics"] = None

    # B4
    report["source_reliability"] = precision_by_source_type(classified)

    return report


def main():
    parser = argparse.ArgumentParser(description="Herald precision metrics")
    parser.add_argument("--classified-dir", type=Path, default=CLASSIFIED_DIR)
    parser.add_argument("--price-csv", type=Path, default=PRICE_CSV)
    parser.add_argument("--ground-truth-dir", type=Path, default=GROUND_TRUTH_DIR)
    parser.add_argument("--resolutions-dir", type=Path, default=RESOLUTIONS_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    report = build_metrics_report(
        args.classified_dir,
        args.price_csv,
        args.ground_truth_dir,
        args.resolutions_dir,
        args.as_of_date,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"metrics_{args.as_of_date}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))

    print(f"\nHERALD PRECISION METRICS -- {args.as_of_date}")
    print(f"  Classified records: {report['n_classified']}")
    print(f"  CRT resolutions: {report['n_resolutions']}")
    crt = report["crt_cross_reference"]
    print(f"  CRT matches: {crt['n_matched']} (cat agree: {crt['category_agreement_rate']:.0%})")
    ipc = report["informational_price_check"]
    print(
        f"  Informational check: {ipc['n_surprised']}/{ipc['n_checked']} false ({ipc['false_informational_rate']:.0%})"
    )
    spc = report["severity_price_check"]
    print(f"  Severity reaction: {spc['n_with_move']}/{spc['n_checked']} ({spc['severity_reaction_rate']:.0%})")
    if report["category_metrics"]:
        print("  Category F1 (from ground truth):")
        for cat, m in sorted(report["category_metrics"].items()):
            print(f"    {cat}: P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} (n={m['support']})")
    print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
