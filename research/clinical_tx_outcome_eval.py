#!/usr/bin/env python3
"""Outcome Evaluation + Alpha Attribution for Clinical Transmission Shadow.

Measures whether the clinical transmission layer improves real decision
quality by comparing default vs TX rankings against realized outcomes.

Reads from:
  - artifacts/clinical_transmission_shadow.jsonl (shadow ledger)
  - data/snapshots/resolutions/ (CRT outcomes)
  - production_data/price_history.csv (realized returns)

Produces:
  - Decision win rate
  - Dropped vs retained performance
  - Gained vs displaced performance
  - Calibration comparison (Brier)
  - EV realization accuracy
  - Layer-level alpha attribution
  - Failure mode / blind spot detection
  - Stability / drift monitoring

Usage:
    python research/clinical_tx_outcome_eval.py
    python research/clinical_tx_outcome_eval.py --min-days 7
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("tx_outcome_eval")

SHADOW_LEDGER = REPO_ROOT / "artifacts" / "clinical_transmission_shadow.jsonl"
RESOLUTIONS_DIR = REPO_ROOT / "data" / "snapshots" / "resolutions"
PRICE_CSV = REPO_ROOT / "production_data" / "price_history.csv"


# ======================================================================
# A. Dataset construction
# ======================================================================


def build_eval_dataset(min_days_since: int = 7) -> List[Dict[str, Any]]:
    """Build clean evaluation dataset from shadow + outcomes + prices.

    Args:
        min_days_since: minimum days since decision for inclusion
            (ensures enough time for outcome to materialize).

    Returns:
        List of evaluation rows, one per changed-decision event.
    """
    shadow_entries = _load_shadow_ledger()
    resolutions = _load_resolutions()
    prices = _load_prices()

    cutoff = (date.today() - timedelta(days=min_days_since)).isoformat()
    dataset = []

    for entry in shadow_entries:
        as_of = entry.get("as_of_date", "")
        if as_of > cutoff:
            continue  # too recent — outcome may not have resolved

        for name in entry.get("changed_names", []):
            ticker = name.get("ticker", "")
            if not ticker:
                continue

            # Classify decision type
            def_act = name.get("default_actionable", False)
            tx_act = name.get("tx_actionable", False)
            if def_act and not tx_act:
                decision_type = "dropped"
            elif not def_act and tx_act:
                decision_type = "gained"
            elif def_act and tx_act:
                decision_type = "common_changed"
            else:
                decision_type = "both_inactive"

            # Look up outcome
            outcome = _find_outcome(ticker, as_of, resolutions)
            ret_1d, ret_5d = _find_returns(ticker, as_of, name.get("days_to_event"), prices)

            row = {
                "ticker": ticker,
                "decision_date": as_of,
                "phase": name.get("phase", ""),
                "event_type": name.get("event_type", ""),
                "decision_type": decision_type,
                "default_rank": name.get("default_rank"),
                "tx_rank": name.get("tx_rank"),
                "rank_delta": name.get("rank_delta", 0),
                "default_p_hit": name.get("default_p_hit"),
                "tx_p_hit": name.get("tx_p_hit"),
                "default_ev": name.get("default_ev"),
                "tx_ev": name.get("tx_ev"),
                "tx_clamped": name.get("tx_clamped", 0),
                "tx_protocol": name.get("tx_protocol", 0),
                "tx_endpoint": name.get("tx_endpoint", 0),
                "tx_biomarker": name.get("tx_biomarker", 0),
                "days_to_event": name.get("days_to_event"),
                "realized_outcome": outcome,  # 1=HIT, 0=MISS, None=pending
                "realized_return_1d": ret_1d,
                "realized_return_5d": ret_5d,
            }
            dataset.append(row)

    logger.info(
        "Eval dataset: %d rows (%d with outcomes, %d with returns)",
        len(dataset),
        sum(1 for r in dataset if r["realized_outcome"] is not None),
        sum(1 for r in dataset if r["realized_return_1d"] is not None),
    )
    return dataset


def _load_shadow_ledger() -> List[Dict]:
    if not SHADOW_LEDGER.exists():
        return []
    entries = []
    for line in SHADOW_LEDGER.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _load_resolutions() -> Dict[str, Dict]:
    """Load CRT resolutions keyed by ticker."""
    result: Dict[str, List[Dict]] = defaultdict(list)
    if not RESOLUTIONS_DIR.exists():
        return result
    for f in RESOLUTIONS_DIR.rglob("*.json"):
        try:
            rec = json.loads(f.read_text())
            if isinstance(rec, dict) and "ticker" in rec:
                result[rec["ticker"]].append(rec)
        except (json.JSONDecodeError, OSError):
            continue
    return result


def _load_prices() -> Any:
    """Load price store or CSV fallback."""
    try:
        from common.price_store import PriceStore

        db_path = REPO_ROOT / "data" / "prices.db"
        store = PriceStore(str(db_path))
        if store.ticker_count() > 0:
            return store
    except Exception:
        pass
    return None


def _find_outcome(ticker: str, decision_date: str, resolutions: Dict) -> Optional[int]:
    """Find realized outcome for a ticker after decision date."""
    recs = resolutions.get(ticker, [])
    for rec in recs:
        res_date = rec.get("resolution_date", rec.get("catalyst_date", ""))
        if res_date and res_date >= decision_date:
            outcome = rec.get("outcome", "")
            if outcome == "HIT":
                return 1
            elif outcome == "MISS":
                return 0
    return None


def _get_price_pit_safe(prices: Any, ticker: str, target_date: str) -> Optional[float]:
    """Get price on or BEFORE target_date only (PIT-safe for entry prices)."""
    dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    for offset in range(6):
        d = (dt - timedelta(days=offset)).isoformat()
        val = prices.get_price(ticker, d)
        if val is not None:
            return val
    return None


def _get_price_post_event(prices: Any, ticker: str, target_date: str) -> Optional[float]:
    """Get price on or AFTER target_date (for exit / realized returns)."""
    dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    for offset in range(6):
        d = (dt + timedelta(days=offset)).isoformat()
        val = prices.get_price(ticker, d)
        if val is not None:
            return val
    return None


def _find_returns(
    ticker: str, decision_date: str, days_to_event: Any, prices: Any
) -> Tuple[Optional[float], Optional[float]]:
    """Find realized returns around the catalyst.

    PIT discipline:
      - Entry price: on or BEFORE decision_date (backward lookback only)
      - Exit price: on or AFTER estimated event date (forward lookback OK)
    """
    if prices is None or not hasattr(prices, "get_price"):
        return None, None
    try:
        dt = datetime.strptime(decision_date, "%Y-%m-%d").date()
        pre = _get_price_pit_safe(prices, ticker, decision_date)
        if pre is None or pre <= 0:
            return None, None
        dte = int(days_to_event) if days_to_event else 30
        event_dt = dt + timedelta(days=dte)
        post_1d = _get_price_post_event(prices, ticker, (event_dt + timedelta(days=1)).isoformat())
        post_5d = _get_price_post_event(prices, ticker, (event_dt + timedelta(days=5)).isoformat())
        ret_1d = round((post_1d - pre) / pre, 6) if post_1d else None
        ret_5d = round((post_5d - pre) / pre, 6) if post_5d else None
        return ret_1d, ret_5d
    except Exception:
        return None, None


# ======================================================================
# B. Decision quality evaluation
# ======================================================================


def evaluate_decisions(dataset: List[Dict]) -> Dict[str, Any]:
    """Compute decision quality metrics."""
    dropped = [r for r in dataset if r["decision_type"] == "dropped"]
    gained = [r for r in dataset if r["decision_type"] == "gained"]
    common = [r for r in dataset if r["decision_type"] == "common_changed"]
    all_changed = dropped + gained

    results: Dict[str, Any] = {
        "n_total": len(dataset),
        "n_dropped": len(dropped),
        "n_gained": len(gained),
        "n_common_changed": len(common),
        "n_with_outcome": sum(1 for r in dataset if r["realized_outcome"] is not None),
        "n_with_return": sum(1 for r in dataset if r["realized_return_1d"] is not None),
    }

    # Dropped performance
    results["dropped"] = _segment_performance(dropped, "dropped")

    # Gained performance
    results["gained"] = _segment_performance(gained, "gained")

    # Common changed (rank shifted but still actionable in both)
    results["common_changed"] = _segment_performance(common, "common_changed")

    # Decision win rate
    correct_drops = sum(1 for r in dropped if r["realized_outcome"] == 0)
    correct_gains = sum(1 for r in gained if r["realized_outcome"] == 1)
    total_resolved = sum(1 for r in all_changed if r["realized_outcome"] is not None)
    if total_resolved > 0:
        results["decision_win_rate"] = round((correct_drops + correct_gains) / total_resolved, 4)
    else:
        results["decision_win_rate"] = None

    return results


def _segment_performance(rows: List[Dict], label: str) -> Dict[str, Any]:
    """Compute performance metrics for a segment."""
    outcomes = [r["realized_outcome"] for r in rows if r["realized_outcome"] is not None]
    returns_1d = [r["realized_return_1d"] for r in rows if r["realized_return_1d"] is not None]
    returns_5d = [r["realized_return_5d"] for r in rows if r["realized_return_5d"] is not None]

    result: Dict[str, Any] = {"n": len(rows), "label": label}

    if outcomes:
        result["hit_rate"] = round(sum(outcomes) / len(outcomes), 4)
        result["n_resolved"] = len(outcomes)
    else:
        result["hit_rate"] = None

    if returns_1d:
        sorted_ret = sorted(returns_1d)
        result["mean_return_1d"] = round(sum(returns_1d) / len(returns_1d), 6)
        result["median_return_1d"] = round(sorted_ret[len(sorted_ret) // 2], 6)
        result["worst_10pct_return"] = round(sorted_ret[max(0, len(sorted_ret) // 10)], 6)
    if returns_5d:
        result["mean_return_5d"] = round(sum(returns_5d) / len(returns_5d), 6)

    return result


# ======================================================================
# C. Calibration analysis
# ======================================================================


def evaluate_calibration(dataset: List[Dict]) -> Dict[str, Any]:
    """Compare calibration: default p_hit vs TX p_hit vs reality."""
    resolved = [r for r in dataset if r["realized_outcome"] is not None]
    if not resolved:
        return {"status": "insufficient_data", "n": 0}

    def_preds = [r["default_p_hit"] for r in resolved if r["default_p_hit"] is not None]
    tx_preds = [r["tx_p_hit"] for r in resolved if r["tx_p_hit"] is not None]
    actuals = [r["realized_outcome"] for r in resolved]

    def _brier(preds, acts):
        if not preds:
            return None
        return round(sum((p - a) ** 2 for p, a in zip(preds, acts)) / len(preds), 6)

    return {
        "n_resolved": len(resolved),
        "default_brier": _brier(def_preds, actuals[: len(def_preds)]),
        "tx_brier": _brier(tx_preds, actuals[: len(tx_preds)]),
        "calibration_improved": (_brier(tx_preds, actuals[: len(tx_preds)]) or 999)
        < (_brier(def_preds, actuals[: len(def_preds)]) or 999),
    }


# ======================================================================
# D. EV realization
# ======================================================================


def evaluate_ev_realization(dataset: List[Dict]) -> Dict[str, Any]:
    """Compare predicted EV vs realized returns."""
    with_returns = [r for r in dataset if r["realized_return_1d"] is not None]
    if not with_returns:
        return {"status": "insufficient_data"}

    def_evs = [r["default_ev"] for r in with_returns if r["default_ev"] is not None]
    tx_evs = [r["tx_ev"] for r in with_returns if r["tx_ev"] is not None]
    actuals = [r["realized_return_1d"] * 100 for r in with_returns]  # convert to %

    def _mae(preds, acts):
        if not preds:
            return None
        return round(sum(abs(p - a) for p, a in zip(preds, acts)) / len(preds), 4)

    def _directional(preds, acts):
        if not preds:
            return None
        correct = sum(1 for p, a in zip(preds, acts) if (p > 0) == (a > 0))
        return round(correct / len(preds), 4)

    return {
        "n": len(with_returns),
        "default_mae": _mae(def_evs, actuals[: len(def_evs)]),
        "tx_mae": _mae(tx_evs, actuals[: len(tx_evs)]),
        "default_directional": _directional(def_evs, actuals[: len(def_evs)]),
        "tx_directional": _directional(tx_evs, actuals[: len(tx_evs)]),
    }


# ======================================================================
# E. Alpha attribution
# ======================================================================


def evaluate_attribution(dataset: List[Dict]) -> Dict[str, Any]:
    """Attribute outcomes to individual clinical layers."""
    resolved = [r for r in dataset if r["realized_outcome"] is not None]
    if not resolved:
        return {"status": "insufficient_data"}

    winners = [r for r in resolved if r["realized_outcome"] == 1]
    losers = [r for r in resolved if r["realized_outcome"] == 0]

    def _mean_contrib(rows, key):
        vals = [r.get(key, 0) for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    layers = {
        "protocol": "tx_protocol",
        "endpoint": "tx_endpoint",
        "biomarker": "tx_biomarker",
        "total": "tx_clamped",
    }

    attribution = {}
    for name, key in layers.items():
        attribution[name] = {
            "mean_for_winners": _mean_contrib(winners, key),
            "mean_for_losers": _mean_contrib(losers, key),
        }

    # Blind spots: high boost + failed, or high penalty + succeeded
    blind_spots = []
    for r in resolved:
        tx = r.get("tx_clamped", 0)
        outcome = r["realized_outcome"]
        if tx > 0.03 and outcome == 0:
            blind_spots.append(
                {
                    "ticker": r["ticker"],
                    "phase": r["phase"],
                    "tx_clamped": tx,
                    "outcome": "MISS",
                    "type": "boosted_but_failed",
                    "tx_protocol": r.get("tx_protocol", 0),
                    "tx_endpoint": r.get("tx_endpoint", 0),
                    "tx_biomarker": r.get("tx_biomarker", 0),
                }
            )
        elif tx < -0.03 and outcome == 1:
            blind_spots.append(
                {
                    "ticker": r["ticker"],
                    "phase": r["phase"],
                    "tx_clamped": tx,
                    "outcome": "HIT",
                    "type": "penalized_but_succeeded",
                    "tx_protocol": r.get("tx_protocol", 0),
                    "tx_endpoint": r.get("tx_endpoint", 0),
                    "tx_biomarker": r.get("tx_biomarker", 0),
                }
            )

    return {
        "n_resolved": len(resolved),
        "n_winners": len(winners),
        "n_losers": len(losers),
        "layer_attribution": attribution,
        "blind_spots": blind_spots[:20],
    }


# ======================================================================
# F. Stability / drift
# ======================================================================


def evaluate_stability() -> Dict[str, Any]:
    """Track shadow stability over time."""
    entries = _load_shadow_ledger()
    if not entries:
        return {"status": "no_data"}

    timeline = []
    for e in entries:
        timeline.append(
            {
                "date": e.get("as_of_date"),
                "default_n": e.get("default_actionable_n", 0),
                "tx_n": e.get("tx_actionable_n", 0),
                "dropped": len(e.get("dropped_from_actionable", [])),
                "gained": len(e.get("gained_actionable", [])),
                "top10_overlap": e.get("top10_overlap", 0),
                "n_changed": e.get("n_changed_names", 0),
            }
        )

    tx_counts = [t["tx_n"] for t in timeline]
    return {
        "n_snapshots": len(timeline),
        "date_range": [timeline[0]["date"], timeline[-1]["date"]] if timeline else [],
        "mean_tx_actionable": round(sum(tx_counts) / len(tx_counts), 1) if tx_counts else None,
        "min_tx_actionable": min(tx_counts) if tx_counts else None,
        "max_tx_actionable": max(tx_counts) if tx_counts else None,
        "mean_top10_overlap": round(sum(t["top10_overlap"] for t in timeline) / len(timeline), 1) if timeline else None,
        "timeline": timeline,
    }


# ======================================================================
# G. Main report
# ======================================================================


def run_evaluation(min_days: int = 7) -> Dict[str, Any]:
    """Run full outcome evaluation."""
    print("Clinical Transmission — Outcome Evaluation")
    print("=" * 60)

    dataset = build_eval_dataset(min_days_since=min_days)

    decisions = evaluate_decisions(dataset)
    calibration = evaluate_calibration(dataset)
    ev_real = evaluate_ev_realization(dataset)
    attribution = evaluate_attribution(dataset)
    stability = evaluate_stability()

    report = {
        "generated_at": datetime.now().isoformat(),
        "min_days_since": min_days,
        "dataset_size": len(dataset),
        "decisions": decisions,
        "calibration": calibration,
        "ev_realization": ev_real,
        "attribution": attribution,
        "stability": stability,
    }

    # Promotion recommendation
    report["recommendation"] = _recommend(decisions, calibration)

    # Print summary
    print(f"\nDataset: {len(dataset)} rows")
    print(f"  With outcomes: {decisions['n_with_outcome']}")
    print(f"  With returns: {decisions['n_with_return']}")
    print(f"  Dropped: {decisions['n_dropped']}")
    print(f"  Gained: {decisions['n_gained']}")

    if decisions.get("decision_win_rate") is not None:
        print(f"\nDecision win rate: {decisions['decision_win_rate']:.1%}")
    else:
        print("\nDecision win rate: pending (no resolved outcomes yet)")

    if calibration.get("default_brier") is not None:
        print("\nCalibration:")
        print(f"  Default Brier: {calibration['default_brier']}")
        print(f"  TX Brier:      {calibration['tx_brier']}")
        print(f"  Improved:      {calibration['calibration_improved']}")

    print("\nStability:")
    print(f"  Snapshots: {stability.get('n_snapshots', 0)}")
    print(f"  Mean TX actionable: {stability.get('mean_tx_actionable', '?')}")
    print(f"  Mean top-10 overlap: {stability.get('mean_top10_overlap', '?')}")

    print(f"\n{'='*60}")
    rec = report["recommendation"]
    print(f"RECOMMENDATION: {rec['verdict']}")
    print(f"  {rec['reasoning']}")

    # Write report
    out_path = REPO_ROOT / "artifacts" / "clinical_tx_outcome_eval.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport: {out_path}")

    return report


def _recommend(decisions: Dict, calibration: Dict) -> Dict[str, str]:
    """Generate promotion recommendation."""
    win_rate = decisions.get("decision_win_rate")
    n_outcomes = decisions.get("n_with_outcome", 0)

    if n_outcomes < 5:
        return {
            "verdict": "PENDING — insufficient outcomes",
            "reasoning": f"Only {n_outcomes} resolved outcomes. Need ≥5 for evaluation. Continue shadow.",
        }

    if win_rate is not None and win_rate >= 0.60:
        cal_improved = calibration.get("calibration_improved", False)
        return {
            "verdict": "PROMOTE to default",
            "reasoning": f"Win rate {win_rate:.0%} ≥ 60% threshold. "
            f"Calibration {'improved' if cal_improved else 'mixed'}. "
            f"Based on {n_outcomes} resolved outcomes.",
        }
    elif win_rate is not None and win_rate >= 0.50:
        return {
            "verdict": "EXTEND shadow — marginal",
            "reasoning": f"Win rate {win_rate:.0%} is positive but below 60% threshold. "
            f"Continue shadow for another 2 weeks.",
        }
    elif win_rate is not None:
        return {
            "verdict": "REDUCE weights — underperforming",
            "reasoning": f"Win rate {win_rate:.0%} < 50%. Transmission may be over-penalizing. "
            f"Consider halving weights before next review.",
        }
    else:
        return {
            "verdict": "PENDING — no resolved outcomes",
            "reasoning": "No changed decisions have resolved yet. Continue shadow.",
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clinical TX Outcome Evaluation")
    parser.add_argument(
        "--min-days",
        type=int,
        default=0,
        help="Minimum days since decision for inclusion (default: 0 for initial run)",
    )
    args = parser.parse_args()
    run_evaluation(min_days=args.min_days)
