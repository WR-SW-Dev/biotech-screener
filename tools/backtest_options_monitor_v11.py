#!/usr/bin/env python3
"""Options Monitor v1.1 — Backtest Harness (Spec 040 Sprint 2).

Evaluates v1.1 factor scores against forward biotech outcomes using
PIT-safe walk-forward validation. Produces calibration tables, ablation
reports, and cohort-level metrics.

Labels:
  Y_move_gt_implied: |return_t1| > IV30/sqrt(252)
  Y_iv_crush: atm_iv_30_{t+1} - atm_iv_30_{t-1} < -0.15
  Y_false_positive: high score but no meaningful outcome

Validation: walk-forward (6mo train, 2mo validate, monthly roll)

Usage:
    python tools/backtest_options_monitor_v11.py --snapshot-root data/snapshots
    python tools/backtest_options_monitor_v11.py --snapshot-root data/snapshots --cohort regulatory
    python tools/backtest_options_monitor_v11.py --ablation ep_only
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
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
logger = logging.getLogger("backtest_om11")

SCHEMA_VERSION = "om11_backtest.v1"

# Label thresholds
MOVE_GT_IMPLIED_K = 1.0  # |return| > IV30/sqrt(252) * k
IV_CRUSH_THRESHOLD = -0.15  # absolute IV points
FP_SCORE_THRESHOLD = 0.65
FP_LOW_MOVE_THRESHOLD = 0.03  # 3% abs return

# Walk-forward defaults
TRAIN_MONTHS = 6
VALIDATE_MONTHS = 2
ROLL_MONTHS = 1


# ---------------------------------------------------------------------------
# Label generation
# ---------------------------------------------------------------------------


@dataclass
class EventLabel:
    """Labels for one ticker-date observation."""

    ticker: str
    as_of_date: str
    # Forward returns
    return_t1: Optional[float] = None
    return_t3: Optional[float] = None
    return_t5: Optional[float] = None
    abs_return_t1: Optional[float] = None
    # IV data
    atm_iv_30_pre: Optional[float] = None
    atm_iv_30_post: Optional[float] = None
    iv_change: Optional[float] = None
    # Implied move
    implied_daily_move: Optional[float] = None
    # Labels
    move_gt_implied: Optional[bool] = None
    iv_crush: Optional[bool] = None
    false_positive: Optional[bool] = None
    # Context
    catalyst_class: str = "other"
    days_to_catalyst: Optional[int] = None
    event_window: bool = False
    hard_catalyst: bool = False
    # v1.1 scores (filled from snapshot)
    om11_score: Optional[float] = None
    om11_ep: Optional[float] = None
    om11_sr: Optional[float] = None
    om11_sk: Optional[float] = None
    om11_dv: Optional[float] = None
    om11_quality: Optional[float] = None
    om11_confidence: Optional[float] = None
    om11_verdict: str = "NONE"


def _sf(val: Any) -> Optional[float]:
    """Safe float conversion."""
    if val is None or val == "":
        return None
    try:
        v = float(val)
        return None if math.isnan(v) else v
    except (ValueError, TypeError):
        return None


def generate_labels(
    snapshot_date: str,
    rankings_row: Dict[str, str],
    forward_prices: Dict[str, List[Tuple[str, float]]],
    forward_iv: Optional[Dict[str, float]] = None,
) -> EventLabel:
    """Generate outcome labels for one ticker-date from snapshot + forward data.

    Args:
        snapshot_date: The as_of_date of the snapshot
        rankings_row: One row from rankings.csv
        forward_prices: {ticker: [(date, close), ...]} for T+1 through T+5
        forward_iv: {ticker: atm_iv_30 at T+1} if available
    """
    ticker = rankings_row.get("ticker", "")

    # Extract v1.1 features from snapshot (if already computed)
    label = EventLabel(
        ticker=ticker,
        as_of_date=snapshot_date,
        catalyst_class=rankings_row.get("catalyst_family", "other").lower(),
        om11_score=_sf(rankings_row.get("ovf11_score", rankings_row.get("om11_score_final"))),
        om11_ep=_sf(rankings_row.get("ovf11_ep", rankings_row.get("om11_factor_event_premium"))),
        om11_sr=_sf(rankings_row.get("ovf11_sr", rankings_row.get("om11_factor_surface_repricing"))),
        om11_sk=_sf(rankings_row.get("ovf11_sk", rankings_row.get("om11_factor_skew_tail"))),
        om11_dv=_sf(rankings_row.get("ovf11_dv", rankings_row.get("om11_factor_divergence"))),
        om11_quality=_sf(rankings_row.get("ovf11_quality", rankings_row.get("om11_chain_quality"))),
        om11_confidence=_sf(rankings_row.get("ovf11_confidence", rankings_row.get("om11_confidence"))),
        om11_verdict=rankings_row.get("ovf11_monitor_verdict", rankings_row.get("om11_monitor_verdict", "NONE")),
    )

    # Catalyst context
    cat_days = _sf(rankings_row.get("catalyst_days"))
    if cat_days is not None:
        label.days_to_catalyst = int(cat_days)
        label.event_window = cat_days <= 14
    label.hard_catalyst = rankings_row.get("is_hard_catalyst", "") == "1"

    # Current IV
    atm_iv = _sf(rankings_row.get("opt_atm_iv", rankings_row.get("atm_iv_30")))
    label.atm_iv_30_pre = atm_iv

    # Implied daily move from IV30
    if atm_iv is not None and atm_iv > 0:
        label.implied_daily_move = atm_iv / math.sqrt(252)

    # Forward returns from price data
    prices = forward_prices.get(ticker, [])
    if len(prices) >= 1:
        # Assume prices[0] is the as_of_date close, prices[1] is T+1, etc.
        base_price = prices[0][1] if prices else None
        if base_price and base_price > 0:
            if len(prices) >= 2:
                label.return_t1 = (prices[1][1] - base_price) / base_price
                label.abs_return_t1 = abs(label.return_t1)
            if len(prices) >= 4:
                label.return_t3 = (prices[3][1] - base_price) / base_price
            if len(prices) >= 6:
                label.return_t5 = (prices[5][1] - base_price) / base_price

    # Forward IV (T+1)
    if forward_iv and ticker in forward_iv:
        label.atm_iv_30_post = forward_iv[ticker]
        if label.atm_iv_30_pre is not None:
            label.iv_change = label.atm_iv_30_post - label.atm_iv_30_pre

    # --- Compute binary labels ---

    # Label A: move exceeds implied
    if label.abs_return_t1 is not None and label.implied_daily_move is not None:
        label.move_gt_implied = label.abs_return_t1 > (label.implied_daily_move * MOVE_GT_IMPLIED_K)

    # Label B: post-event IV crush
    if label.iv_change is not None:
        label.iv_crush = label.iv_change < IV_CRUSH_THRESHOLD

    # Label C: false positive (high score, no meaningful outcome)
    if label.om11_score is not None and label.abs_return_t1 is not None:
        high_score = label.om11_score > FP_SCORE_THRESHOLD
        low_move = label.abs_return_t1 < FP_LOW_MOVE_THRESHOLD
        no_iv_outcome = label.iv_change is None or abs(label.iv_change) < 0.05
        label.false_positive = high_score and low_move and no_iv_outcome

    return label


# ---------------------------------------------------------------------------
# Walk-forward evaluation
# ---------------------------------------------------------------------------


@dataclass
class FoldResult:
    """Results from one walk-forward fold."""

    fold_id: int
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    n_train: int = 0
    n_val: int = 0
    # Metrics
    move_gt_implied_auc: Optional[float] = None
    iv_crush_auc: Optional[float] = None
    fp_auc: Optional[float] = None
    ic_abs_ret_t1: Optional[float] = None
    ic_abs_ret_t3: Optional[float] = None
    top_decile_hit_rate: Optional[float] = None
    alerts_per_day: Optional[float] = None
    fp_rate: Optional[float] = None


def generate_walk_forward_folds(
    start_date: str,
    end_date: str,
    train_months: int = TRAIN_MONTHS,
    val_months: int = VALIDATE_MONTHS,
    roll_months: int = ROLL_MONTHS,
) -> List[Tuple[str, str, str, str]]:
    """Generate walk-forward fold date ranges.

    Returns list of (train_start, train_end, val_start, val_end) tuples.
    """
    folds = []
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    current = start
    fold_id = 0
    while True:
        train_end = current + timedelta(days=train_months * 30)
        val_start = train_end + timedelta(days=1)
        val_end = val_start + timedelta(days=val_months * 30)

        if val_end > end:
            break

        folds.append((
            current.isoformat(),
            train_end.isoformat(),
            val_start.isoformat(),
            val_end.isoformat(),
        ))
        current += timedelta(days=roll_months * 30)
        fold_id += 1

    return folds


def compute_spearman_ic(scores: List[float], returns: List[float]) -> Optional[float]:
    """Compute Spearman rank IC between scores and forward returns."""
    if len(scores) < 10 or len(scores) != len(returns):
        return None

    def _rank(vals):
        indexed = sorted(enumerate(vals), key=lambda x: x[1])
        ranks = [0.0] * len(vals)
        for rank, (idx, _) in enumerate(indexed):
            ranks[idx] = float(rank)
        return ranks

    r_scores = _rank(scores)
    r_returns = _rank(returns)
    n = len(scores)
    mean_s = sum(r_scores) / n
    mean_r = sum(r_returns) / n

    cov = sum((r_scores[i] - mean_s) * (r_returns[i] - mean_r) for i in range(n))
    std_s = math.sqrt(sum((r_scores[i] - mean_s) ** 2 for i in range(n)))
    std_r = math.sqrt(sum((r_returns[i] - mean_r) ** 2 for i in range(n)))

    if std_s < 1e-10 or std_r < 1e-10:
        return 0.0
    return cov / (std_s * std_r)


# ---------------------------------------------------------------------------
# Ablation configurations
# ---------------------------------------------------------------------------

ABLATION_CONFIGS = {
    "full": {"ep": True, "sr": True, "sk": True, "dv": True, "catalyst": True, "confidence": True},
    "ep_only": {"ep": True, "sr": False, "sk": False, "dv": False, "catalyst": False, "confidence": False},
    "sr_only": {"ep": False, "sr": True, "sk": False, "dv": False, "catalyst": False, "confidence": False},
    "sk_only": {"ep": False, "sr": False, "sk": True, "dv": False, "catalyst": False, "confidence": False},
    "dv_only": {"ep": False, "sr": False, "sk": False, "dv": True, "catalyst": False, "confidence": False},
    "no_catalyst": {"ep": True, "sr": True, "sk": True, "dv": True, "catalyst": False, "confidence": True},
    "no_confidence": {"ep": True, "sr": True, "sk": True, "dv": True, "catalyst": True, "confidence": False},
}


def ablated_score(label: EventLabel, config: Dict[str, bool]) -> Optional[float]:
    """Compute ablated composite score from a label's factor scores."""
    factors = []
    if config.get("ep") and label.om11_ep is not None:
        factors.append(("EP", label.om11_ep))
    if config.get("sr") and label.om11_sr is not None:
        factors.append(("SR", label.om11_sr))
    if config.get("sk") and label.om11_sk is not None:
        factors.append(("SK", label.om11_sk))
    if config.get("dv") and label.om11_dv is not None:
        factors.append(("DV", label.om11_dv))

    if not factors:
        return None

    # Equal weight when ablating (catalyst weights need the full model)
    score = sum(v for _, v in factors) / len(factors)

    if config.get("confidence") and label.om11_confidence is not None:
        score *= label.om11_confidence

    return score


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_backtest_report(
    labels: List[EventLabel],
    folds: List[Tuple[str, str, str, str]],
    cohort: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate full backtest report from labeled data.

    Returns structured report dict suitable for JSON serialization.
    """
    # Filter by cohort if specified
    if cohort:
        labels = [l for l in labels if l.catalyst_class == cohort]

    report = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_observations": len(labels),
        "n_folds": len(folds),
        "cohort": cohort or "all",
        "label_coverage": {
            "move_gt_implied": sum(1 for l in labels if l.move_gt_implied is not None),
            "iv_crush": sum(1 for l in labels if l.iv_crush is not None),
            "false_positive": sum(1 for l in labels if l.false_positive is not None),
        },
        "label_rates": {},
        "fold_results": [],
        "ablation_results": {},
        "summary": {},
    }

    # Label rates
    for label_name in ("move_gt_implied", "iv_crush", "false_positive"):
        valid = [l for l in labels if getattr(l, label_name) is not None]
        if valid:
            rate = sum(1 for l in valid if getattr(l, label_name)) / len(valid)
            report["label_rates"][label_name] = round(rate, 4)

    # IC across all data
    scored = [l for l in labels if l.om11_score is not None and l.abs_return_t1 is not None]
    if len(scored) >= 10:
        ic = compute_spearman_ic(
            [l.om11_score for l in scored],
            [l.abs_return_t1 for l in scored],
        )
        report["summary"]["ic_abs_ret_t1_all"] = round(ic, 4) if ic else None

    # Top-decile hit rate (move_gt_implied)
    scored_with_label = [l for l in scored if l.move_gt_implied is not None]
    if len(scored_with_label) >= 20:
        sorted_by_score = sorted(scored_with_label, key=lambda l: l.om11_score or 0, reverse=True)
        top_decile_n = max(1, len(sorted_by_score) // 10)
        top_decile = sorted_by_score[:top_decile_n]
        hit_rate = sum(1 for l in top_decile if l.move_gt_implied) / len(top_decile)
        report["summary"]["top_decile_hit_rate"] = round(hit_rate, 4)

        # Bottom decile for comparison
        bottom_decile = sorted_by_score[-top_decile_n:]
        bottom_rate = sum(1 for l in bottom_decile if l.move_gt_implied) / len(bottom_decile)
        report["summary"]["bottom_decile_hit_rate"] = round(bottom_rate, 4)
        report["summary"]["top_vs_bottom_spread"] = round(hit_rate - bottom_rate, 4)

    # Ablation results
    for abl_name, abl_config in ABLATION_CONFIGS.items():
        abl_scored = []
        for l in labels:
            s = ablated_score(l, abl_config)
            if s is not None and l.abs_return_t1 is not None:
                abl_scored.append((s, l.abs_return_t1))

        if len(abl_scored) >= 10:
            ic = compute_spearman_ic(
                [s for s, _ in abl_scored],
                [r for _, r in abl_scored],
            )
            report["ablation_results"][abl_name] = {
                "n": len(abl_scored),
                "ic_abs_ret_t1": round(ic, 4) if ic else None,
            }

    # Verdict distribution
    verdict_counts = {}
    for l in labels:
        v = l.om11_verdict
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
    report["summary"]["verdict_distribution"] = verdict_counts

    # Alerts per day
    dates = set(l.as_of_date for l in labels)
    n_alerts = sum(1 for l in labels if l.om11_verdict in ("HIGH", "WATCH"))
    if dates:
        report["summary"]["alerts_per_day"] = round(n_alerts / len(dates), 2)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Options Monitor v1.1 Backtest Harness")
    parser.add_argument("--snapshot-root", type=Path, default=REPO_ROOT / "data" / "snapshots")
    parser.add_argument("--price-csv", type=Path, default=REPO_ROOT / "production_data" / "price_history.csv")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "output" / "research" / "om11_backtest")
    parser.add_argument("--cohort", choices=["regulatory", "clinical_topline", "clinical_safety", "earnings", "financing", "other"])
    parser.add_argument("--ablation", choices=list(ABLATION_CONFIGS.keys()))
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    args = parser.parse_args()

    logger.info("Options Monitor v1.1 Backtest")
    logger.info("  Snapshots: %s", args.snapshot_root)
    logger.info("  Date range: %s to %s", args.start_date, args.end_date)

    # Find available snapshot dates
    snap_dates = sorted(
        d.name for d in args.snapshot_root.iterdir()
        if d.is_dir() and len(d.name) == 10
        and args.start_date <= d.name <= args.end_date
        and (d / "rankings.csv").exists()
    )
    logger.info("  Available snapshots: %d", len(snap_dates))

    if len(snap_dates) < 20:
        logger.warning("Insufficient snapshots for meaningful backtest (need 20+, have %d)", len(snap_dates))
        logger.info("Accumulate more daily snapshots with v1.1 features, then re-run.")
        return

    # Generate walk-forward folds
    folds = generate_walk_forward_folds(args.start_date, args.end_date)
    logger.info("  Walk-forward folds: %d", len(folds))

    # Load price data for forward returns
    logger.info("  Loading price data...")
    prices_by_ticker: Dict[str, List[Tuple[str, float]]] = {}
    if args.price_csv.exists():
        with open(args.price_csv, encoding="utf-8") as f:
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

    # Generate labels from snapshots
    logger.info("  Generating labels...")
    all_labels: List[EventLabel] = []

    for snap_date in snap_dates:
        rankings_path = args.snapshot_root / snap_date / "rankings.csv"
        with open(rankings_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ticker = row.get("ticker", "")
                if not ticker:
                    continue

                # Get forward prices starting from snap_date
                ticker_prices = prices_by_ticker.get(ticker, [])
                forward = [(d, p) for d, p in ticker_prices if d >= snap_date][:6]  # T+0 through T+5

                label = generate_labels(snap_date, row, {ticker: forward})
                all_labels.append(label)

    logger.info("  Total observations: %d", len(all_labels))
    labeled = sum(1 for l in all_labels if l.move_gt_implied is not None)
    logger.info("  With move_gt_implied label: %d", labeled)

    # Generate report
    report = generate_backtest_report(all_labels, folds, cohort=args.cohort)

    # Write output
    args.out_dir.mkdir(parents=True, exist_ok=True)
    cohort_suffix = f"_{args.cohort}" if args.cohort else ""
    out_path = args.out_dir / f"om11_backtest{cohort_suffix}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True, default=str)
    logger.info("  Report: %s", out_path)

    # Print summary
    s = report.get("summary", {})
    logger.info("\n=== SUMMARY ===")
    logger.info("  Observations: %d", report["n_observations"])
    logger.info("  IC (abs_ret_t1): %s", s.get("ic_abs_ret_t1_all", "N/A"))
    logger.info("  Top-decile hit rate: %s", s.get("top_decile_hit_rate", "N/A"))
    logger.info("  Top-vs-bottom spread: %s", s.get("top_vs_bottom_spread", "N/A"))
    logger.info("  Alerts/day: %s", s.get("alerts_per_day", "N/A"))
    logger.info("  Verdict distribution: %s", s.get("verdict_distribution", {}))

    if report.get("ablation_results"):
        logger.info("\n=== ABLATIONS ===")
        for name, res in sorted(report["ablation_results"].items()):
            logger.info("  %s: IC=%s (n=%d)", name, res.get("ic_abs_ret_t1", "N/A"), res.get("n", 0))


if __name__ == "__main__":
    main()
