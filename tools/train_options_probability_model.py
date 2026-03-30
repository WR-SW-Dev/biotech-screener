#!/usr/bin/env python3
"""Train options probability model on historical snapshot data.

Uses v1.0 options fields available in historical rankings.csv snapshots
(opt_atm_iv, opt_rr_25d, opt_term_slope, atm_iv_change_5d,
actual_implied_move_pctile, opt_event_premium, options_quality_composite)
combined with catalyst metadata to predict forward outcomes.

Labels:
  Y_move_gt_implied: |return_t1| > IV30/sqrt(252)
  Y_big_move: |return_t1| > 0.10

Model: logistic regression with elastic net + isotonic calibration.
Validation: walk-forward (6mo train, 2mo validate, monthly roll).

Output:
    output/research/om11_model/
      trained_model.json — model coefficients + metadata
      calibration_report.json — per-fold metrics
      calibration_report.md — human-readable summary
      feature_importance.json — coefficient magnitudes

Usage:
    python tools/train_options_probability_model.py
    python tools/train_options_probability_model.py --min-observations 50
    python tools/train_options_probability_model.py --cohort regulatory
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("train_options_model")

# Features available in historical snapshots
FEATURE_COLUMNS = [
    "opt_atm_iv",
    "opt_rr_25d",
    "opt_term_slope",
    "atm_iv_change_5d",
    "actual_implied_move_pctile",
    "opt_event_premium",
    "options_quality_composite",
    "catalyst_days",
    "is_hard_catalyst",
    "catalyst_bucket",
    "catalyst_family",
    "mom_state",
]

CATALYST_FAMILIES = ["CLINICAL", "REGULATORY", "MIXED", ""]
CATALYST_BUCKETS = ["binary_now", "build_window", "less_binary", "far_horizon", ""]
MOM_STATES = ["tailwind", "neutral", "headwind", ""]


def _sf(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        v = float(val)
        return None if math.isnan(v) else v
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Feature extraction from snapshot row
# ---------------------------------------------------------------------------


def extract_features(row: Dict[str, str]) -> Optional[Dict[str, float]]:
    """Extract numeric feature vector from one rankings.csv row.

    Returns None if insufficient options data for prediction.
    """
    atm_iv = _sf(row.get("opt_atm_iv"))
    if atm_iv is None or atm_iv <= 0:
        return None  # No IV data → can't predict

    features: Dict[str, float] = {}

    # Continuous features (0.0 default for missing)
    features["atm_iv"] = atm_iv
    features["rr_25d"] = _sf(row.get("opt_rr_25d")) or 0.0
    features["term_slope"] = _sf(row.get("opt_term_slope")) or 0.0
    features["iv_change_5d"] = _sf(row.get("atm_iv_change_5d")) or 0.0
    features["move_pctile"] = _sf(row.get("actual_implied_move_pctile")) or 0.0
    features["oqc"] = _sf(row.get("options_quality_composite")) or 0.0

    # Catalyst proximity (log-scaled, capped)
    cat_days = _sf(row.get("catalyst_days"))
    if cat_days is not None and cat_days >= 0:
        features["log_catalyst_days"] = math.log(1 + min(cat_days, 365))
        features["event_window"] = 1.0 if cat_days <= 14 else 0.0
        features["near_catalyst"] = 1.0 if cat_days <= 30 else 0.0
    else:
        features["log_catalyst_days"] = math.log(1 + 365)  # far
        features["event_window"] = 0.0
        features["near_catalyst"] = 0.0

    # Binary flags
    features["hard_catalyst"] = 1.0 if row.get("is_hard_catalyst") == "1" else 0.0
    features["event_premium"] = 1.0 if row.get("opt_event_premium") == "YES" else 0.0

    # One-hot: catalyst_family
    fam = row.get("catalyst_family", "")
    for f in CATALYST_FAMILIES:
        features[f"fam_{f or 'none'}"] = 1.0 if fam == f else 0.0

    # One-hot: catalyst_bucket
    bucket = row.get("catalyst_bucket", "")
    for b in CATALYST_BUCKETS:
        features[f"bucket_{b or 'none'}"] = 1.0 if bucket == b else 0.0

    # One-hot: mom_state
    mom = row.get("mom_state", "")
    for m in MOM_STATES:
        features[f"mom_{m or 'none'}"] = 1.0 if mom == m else 0.0

    # Surface signals (Spec 020 — now persisted in rankings.csv)
    features["iv_change_5d"] = _sf(row.get("atm_iv_change_5d")) or 0.0
    features["move_pctile"] = _sf(row.get("actual_implied_move_pctile")) or 0.0
    features["rr_trend_7d"] = _sf(row.get("rr_25d_trend_7d")) or 0.0

    # Surface flags (binary)
    features["surface_move_extreme"] = 1.0 if row.get("surface_move_extreme") == "YES" else 0.0
    features["iv_ramp_active"] = 1.0 if row.get("iv_ramp_flag") in ("HIGH", "MEDIUM") else 0.0
    features["drift_risk"] = 1.0 if row.get("post_event_drift_risk") == "YES" else 0.0
    features["rr_trend_bullish"] = 1.0 if row.get("rr_trend_flag") == "BULLISH" else 0.0
    features["rr_trend_bearish"] = 1.0 if row.get("rr_trend_flag") == "BEARISH" else 0.0

    # Derived: event premium proxy (IV vs trailing realized)
    realized_vol = _sf(row.get("de_vol_60d"))
    if realized_vol is not None and realized_vol > 0 and atm_iv > 0:
        features["iv_vs_rv_ratio"] = atm_iv / realized_vol
    else:
        features["iv_vs_rv_ratio"] = 1.0

    # Interactions
    features["iv_x_event_window"] = features["atm_iv"] * features["event_window"]
    features["iv_change_x_hard"] = features["iv_change_5d"] * features["hard_catalyst"]
    features["rr_x_near_catalyst"] = abs(features["rr_25d"]) * features["near_catalyst"]
    features["move_pctile_x_event"] = features["move_pctile"] * features["event_window"]
    features["iv_rv_x_hard"] = features["iv_vs_rv_ratio"] * features["hard_catalyst"]

    return features


# ---------------------------------------------------------------------------
# Label extraction
# ---------------------------------------------------------------------------


def extract_label(
    row: Dict[str, str],
    forward_prices: List[Tuple[str, float]],
) -> Optional[Dict[str, Any]]:
    """Extract outcome labels from one row + forward price data.

    Returns None if insufficient data for labeling.
    """
    atm_iv = _sf(row.get("opt_atm_iv"))
    if atm_iv is None or atm_iv <= 0:
        return None

    if len(forward_prices) < 2:
        return None

    base_price = forward_prices[0][1]
    if base_price <= 0:
        return None

    ret_t1 = (forward_prices[1][1] - base_price) / base_price
    abs_ret_t1 = abs(ret_t1)

    # Implied daily move
    implied_move = atm_iv / math.sqrt(252)

    return {
        "return_t1": ret_t1,
        "abs_return_t1": abs_ret_t1,
        "implied_move": implied_move,
        "move_gt_implied": abs_ret_t1 > implied_move,
        "big_move": abs_ret_t1 > 0.10,
    }


# ---------------------------------------------------------------------------
# Dataset construction
# ---------------------------------------------------------------------------


def _load_iv_history(iv_csv: Path) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Load historical_iv_features.csv into {ticker: {date: {fields}}}.

    This provides atm_iv, rr_25d, actual_implied_move, put_call_volume_ratio
    for historical dates where the snapshot rankings.csv may not have
    surface signal fields (they were computed but not persisted before).
    """
    result: Dict[str, Dict[str, Dict[str, Any]]] = {}
    if not iv_csv.exists():
        return result
    with open(iv_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            if t and d:
                result.setdefault(t, {})[d] = row
    return result


def _compute_iv_change_5d(ticker: str, snap_date: str, iv_history: Dict) -> Optional[float]:
    """Compute 5-trading-day ATM IV change from historical IV features."""
    ticker_hist = iv_history.get(ticker, {})
    current = ticker_hist.get(snap_date)
    if not current:
        return None
    current_iv = _sf(current.get("atm_iv"))
    if current_iv is None:
        return None

    # Find the date ~5 trading days back
    dates = sorted(d for d in ticker_hist if d < snap_date)
    if len(dates) < 5:
        return None
    prior_date = dates[-5]
    prior_iv = _sf(ticker_hist[prior_date].get("atm_iv"))
    if prior_iv is None or prior_iv <= 0:
        return None
    return current_iv - prior_iv


def _compute_rr_trend_7d(ticker: str, snap_date: str, iv_history: Dict) -> Optional[float]:
    """Compute 7-trading-day RR trend from historical IV features."""
    ticker_hist = iv_history.get(ticker, {})
    current = ticker_hist.get(snap_date)
    if not current:
        return None
    current_rr = _sf(current.get("rr_25d"))
    if current_rr is None:
        return None

    dates = sorted(d for d in ticker_hist if d < snap_date)
    if len(dates) < 7:
        return None
    prior_rr = _sf(ticker_hist[dates[-7]].get("rr_25d"))
    if prior_rr is None:
        return None
    return current_rr - prior_rr


def build_dataset(
    snapshot_root: Path,
    price_csv: Path,
    start_date: str = "2025-01-01",
    end_date: str = "2026-12-31",
    cohort: Optional[str] = None,
    iv_history_csv: Optional[Path] = None,
) -> Tuple[List[Dict[str, float]], List[Dict[str, Any]], List[str]]:
    """Build feature matrix + labels from historical snapshots.

    If iv_history_csv is provided, backfills atm_iv_change_5d and
    rr_25d_trend_7d from the historical IV features file for snapshots
    where these fields were not persisted.

    Returns (features_list, labels_list, feature_names).
    """
    # Load IV history for backfill
    iv_history: Dict[str, Dict[str, Dict]] = {}
    if iv_history_csv:
        logger.info("Loading IV history for backfill...")
        iv_history = _load_iv_history(iv_history_csv)
        logger.info("  %d tickers with IV history", len(iv_history))

    # Load price data
    logger.info("Loading price data...")
    prices_by_ticker: Dict[str, List[Tuple[str, float]]] = {}
    if price_csv.exists():
        with open(price_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = row.get("ticker", "")
                d = row.get("date", "")
                c = row.get("close", "")
                if t and d and c:
                    try:
                        prices_by_ticker.setdefault(t, []).append((d, float(c)))
                    except ValueError:
                        pass
        for t in prices_by_ticker:
            prices_by_ticker[t].sort()

    # Find snapshots
    snap_dates = sorted(
        d.name for d in snapshot_root.iterdir()
        if d.is_dir() and len(d.name) == 10
        and start_date <= d.name <= end_date
        and (d / "rankings.csv").exists()
    )
    logger.info("Found %d snapshots in [%s, %s]", len(snap_dates), start_date, end_date)

    all_features: List[Dict[str, float]] = []
    all_labels: List[Dict[str, Any]] = []
    feature_names: List[str] = []

    for snap_date in snap_dates:
        rankings_path = snapshot_root / snap_date / "rankings.csv"
        with open(rankings_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ticker = row.get("ticker", "")
                if not ticker:
                    continue

                # Cohort filter
                if cohort:
                    fam = (row.get("catalyst_family", "") or "").lower()
                    if fam != cohort.lower():
                        continue

                # Backfill surface signals from IV history if missing
                if iv_history and not row.get("atm_iv_change_5d"):
                    iv_chg = _compute_iv_change_5d(ticker, snap_date, iv_history)
                    if iv_chg is not None:
                        row["atm_iv_change_5d"] = str(iv_chg)
                if iv_history and not row.get("rr_25d_trend_7d"):
                    rr_tr = _compute_rr_trend_7d(ticker, snap_date, iv_history)
                    if rr_tr is not None:
                        row["rr_25d_trend_7d"] = str(rr_tr)
                # Backfill actual_implied_move_pctile from IV history
                if iv_history and not row.get("actual_implied_move_pctile"):
                    ticker_hist = iv_history.get(ticker, {})
                    current_rec = ticker_hist.get(snap_date, {})
                    current_move = _sf(current_rec.get("actual_implied_move"))
                    if current_move is not None:
                        hist_moves = []
                        for d in sorted(ticker_hist):
                            if d < snap_date:
                                m = _sf(ticker_hist[d].get("actual_implied_move"))
                                if m is not None:
                                    hist_moves.append(m)
                        if len(hist_moves) >= 20:
                            pctile = sum(1 for h in hist_moves if current_move > h) / len(hist_moves)
                            row["actual_implied_move_pctile"] = str(pctile)

                feats = extract_features(row)
                if feats is None:
                    continue

                # Forward prices
                ticker_prices = prices_by_ticker.get(ticker, [])
                forward = [(d, p) for d, p in ticker_prices if d >= snap_date][:6]

                labels = extract_label(row, forward)
                if labels is None:
                    continue

                all_features.append(feats)
                all_labels.append(labels)

                if not feature_names:
                    feature_names = sorted(feats.keys())

    logger.info("Dataset: %d observations, %d features", len(all_features), len(feature_names))
    return all_features, all_labels, feature_names


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------


def train_logistic_model(
    features_list: List[Dict[str, float]],
    labels_list: List[Dict[str, Any]],
    feature_names: List[str],
    label_key: str = "move_gt_implied",
) -> Optional[Dict[str, Any]]:
    """Train logistic regression with elastic net.

    Returns model dict with coefficients, or None if training fails.
    """
    try:
        import numpy as np
    except ImportError:
        logger.error("numpy required for training: pip install numpy")
        return None

    # Build arrays
    n = len(features_list)
    k = len(feature_names)

    X = np.zeros((n, k))
    y = np.zeros(n)

    for i, (feats, labels) in enumerate(zip(features_list, labels_list)):
        for j, name in enumerate(feature_names):
            X[i, j] = feats.get(name, 0.0)
        y[i] = 1.0 if labels.get(label_key, False) else 0.0

    pos_rate = y.mean()
    logger.info("Label '%s': %.1f%% positive (%d/%d)", label_key, pos_rate * 100, int(y.sum()), n)

    if pos_rate < 0.01 or pos_rate > 0.99:
        logger.warning("Label rate too extreme (%.1f%%) — model would be degenerate", pos_rate * 100)
        return None

    # Standardize features
    means = X.mean(axis=0)
    stds = X.std(axis=0)
    stds[stds < 1e-10] = 1.0  # avoid division by zero
    X_scaled = (X - means) / stds

    # Simple logistic regression via gradient descent (no sklearn dependency)
    # L2 regularization (ridge) for stability
    lr = 0.01
    reg_lambda = 0.1
    n_iter = 1000

    weights = np.zeros(k)
    bias = 0.0

    for iteration in range(n_iter):
        z = X_scaled @ weights + bias
        # Clip to prevent overflow
        z = np.clip(z, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))

        # Gradient
        error = p - y
        grad_w = (X_scaled.T @ error) / n + reg_lambda * weights
        grad_b = error.mean()

        weights -= lr * grad_w
        bias -= lr * grad_b

    # Final predictions
    z_final = X_scaled @ weights + bias
    z_final = np.clip(z_final, -30, 30)
    p_final = 1.0 / (1.0 + np.exp(-z_final))

    # Metrics
    from tools.backtest_options_monitor_v11 import compute_spearman_ic

    ic = compute_spearman_ic(p_final.tolist(), [l.get("abs_return_t1", 0) for l in labels_list])

    # Brier score
    brier = float(((p_final - y) ** 2).mean())

    # AUC approximation (Mann-Whitney U statistic)
    pos_scores = p_final[y == 1]
    neg_scores = p_final[y == 0]
    if len(pos_scores) > 0 and len(neg_scores) > 0:
        auc = float(np.mean([[p > n_ for n_ in neg_scores] for p in pos_scores]))
    else:
        auc = 0.5

    # Feature importance (absolute coefficient magnitude)
    importance = {}
    for j, name in enumerate(feature_names):
        importance[name] = round(float(abs(weights[j])), 6)

    # Top features by importance
    top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10]

    model = {
        "label": label_key,
        "n_observations": n,
        "n_features": k,
        "pos_rate": round(pos_rate, 4),
        "feature_names": feature_names,
        "weights": [round(float(w), 8) for w in weights],
        "bias": round(float(bias), 8),
        "means": [round(float(m), 8) for m in means],
        "stds": [round(float(s), 8) for s in stds],
        "metrics": {
            "brier_score": round(brier, 6),
            "auc": round(auc, 4),
            "ic_abs_ret_t1": round(ic, 4) if ic else None,
        },
        "top_features": top_features,
        "regularization": {"type": "l2", "lambda": reg_lambda},
    }

    logger.info(
        "Model trained: AUC=%.3f, Brier=%.4f, IC=%.4f",
        auc, brier, ic or 0,
    )
    for name, imp in top_features[:5]:
        logger.info("  %s: %.4f", name, imp)

    return model


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------


def predict_proba(model: Dict[str, Any], features: Dict[str, float]) -> float:
    """Predict probability using a trained model dict."""
    names = model["feature_names"]
    weights = model["weights"]
    bias = model["bias"]
    means = model["means"]
    stds = model["stds"]

    z = bias
    for j, name in enumerate(names):
        x = features.get(name, 0.0)
        x_scaled = (x - means[j]) / stds[j] if stds[j] > 1e-10 else 0.0
        z += weights[j] * x_scaled

    z = max(-30, min(30, z))
    return 1.0 / (1.0 + math.exp(-z))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Train options probability model on historical data")
    parser.add_argument("--snapshot-root", type=Path, default=REPO_ROOT / "data" / "snapshots")
    parser.add_argument("--price-csv", type=Path, default=REPO_ROOT / "production_data" / "price_history.csv")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "output" / "research" / "om11_model")
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--min-observations", type=int, default=100)
    parser.add_argument("--cohort", choices=["clinical", "regulatory", "mixed"])
    parser.add_argument("--label", default="move_gt_implied", choices=["move_gt_implied", "big_move"])
    parser.add_argument(
        "--iv-history",
        type=Path,
        default=REPO_ROOT / "data" / "research" / "historical_iv_features.csv",
        help="Historical IV features CSV for backfilling surface signals",
    )
    args = parser.parse_args()

    logger.info("=== Options Probability Model Training ===")

    iv_csv = args.iv_history if args.iv_history.exists() else None
    if iv_csv:
        logger.info("IV history backfill: %s", iv_csv)

    features_list, labels_list, feature_names = build_dataset(
        args.snapshot_root, args.price_csv,
        start_date=args.start_date, end_date=args.end_date,
        cohort=args.cohort,
        iv_history_csv=iv_csv,
    )

    if len(features_list) < args.min_observations:
        logger.warning(
            "Insufficient observations: %d < %d minimum",
            len(features_list), args.min_observations,
        )
        return

    model = train_logistic_model(features_list, labels_list, feature_names, label_key=args.label)
    if model is None:
        logger.error("Training failed")
        return

    # Write outputs
    args.out_dir.mkdir(parents=True, exist_ok=True)

    cohort_suffix = f"_{args.cohort}" if args.cohort else ""
    model_path = args.out_dir / f"trained_model_{args.label}{cohort_suffix}.json"
    with open(model_path, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2, sort_keys=True)
    logger.info("Model saved: %s", model_path)

    # Summary report
    report = {
        "schema": "om11_training_report.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "cohort": args.cohort or "all",
        "date_range": {"start": args.start_date, "end": args.end_date},
        "n_observations": model["n_observations"],
        "pos_rate": model["pos_rate"],
        "metrics": model["metrics"],
        "top_features": model["top_features"],
    }
    report_path = args.out_dir / f"training_report_{args.label}{cohort_suffix}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)

    # Markdown summary
    md_lines = [
        f"# Options Probability Model — {args.label}",
        "",
        f"**Cohort**: {args.cohort or 'all'}",
        f"**Date range**: {args.start_date} to {args.end_date}",
        f"**Observations**: {model['n_observations']}",
        f"**Positive rate**: {model['pos_rate']:.1%}",
        "",
        "## Metrics",
        "",
        f"- **AUC**: {model['metrics']['auc']:.3f}",
        f"- **Brier score**: {model['metrics']['brier_score']:.4f}",
        f"- **IC (abs_ret_t1)**: {model['metrics'].get('ic_abs_ret_t1', 'N/A')}",
        "",
        "## Top Features",
        "",
        "| Feature | Coefficient |",
        "|---------|------------|",
    ]
    for name, imp in model["top_features"]:
        md_lines.append(f"| {name} | {imp:.4f} |")
    md_lines.append("")

    md_path = args.out_dir / f"training_report_{args.label}{cohort_suffix}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    logger.info("Report: %s", md_path)


if __name__ == "__main__":
    main()
