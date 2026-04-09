#!/usr/bin/env python3
"""
Event EV Forward Validation — match EV predictions to resolved outcomes.

Connects three data sources:
  1. EV predictions (artifacts/event_ev/{date}_event_ev_scores.json)
  2. CRT resolutions (data/snapshots/resolutions/{YYYY-MM}/*.json)
  3. Price history (production_data/price_history.csv)

Produces a growing validation ledger that tracks:
  - Predicted vs actual outcome (p_hit accuracy → Brier score)
  - Predicted vs realized returns (EV accuracy → mean signed error)
  - Calibration by family, phase, and probability bucket

Output: artifacts/event_ev/ev_validation_ledger.jsonl (append-only)
        artifacts/event_ev/ev_validation_summary.json (rewritten each run)

Usage:
    python3 tools/build_ev_validation.py
    python3 tools/build_ev_validation.py --as-of-date 2026-04-09
    python3 tools/build_ev_validation.py --rebuild  # rebuild ledger from scratch
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ev_validation")

# Paths
EV_ARTIFACTS = REPO_ROOT / "artifacts" / "event_ev"
RESOLUTIONS_ROOT = REPO_ROOT / "data" / "snapshots" / "resolutions"
PRICE_CSV = REPO_ROOT / "production_data" / "price_history.csv"
LEDGER_PATH = EV_ARTIFACTS / "ev_validation_ledger.jsonl"
SUMMARY_PATH = EV_ARTIFACTS / "ev_validation_summary.json"

SCHEMA_VERSION = "ev_validation.v1"

# Event type mapping: CRT catalyst_type → EV event_type
_TYPE_MAP = {
    "PDUFA_ACTION": "PDUFA",
    "PHASE_3_READOUT": "DATA_READOUT",
    "PHASE_2_READOUT": "DATA_READOUT",
    "PHASE_1_READOUT": "DATA_READOUT",
    "REGULATORY_DESIGNATION": "REGULATORY",
    "ADCOM_VOTE": "ADCOM",
    "CORPORATE_UPDATE": "CORPORATE",
}


# ---------------------------------------------------------------------------
# Price loading
# ---------------------------------------------------------------------------


def load_prices(price_csv: Path) -> Dict[str, Dict[str, float]]:
    """Load price history into {ticker: {date_str: close}}."""
    prices: Dict[str, Dict[str, float]] = {}
    if not price_csv.exists():
        logger.warning("Price CSV not found: %s", price_csv)
        return prices
    with open(price_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "").strip()
            d = row.get("date", "").strip()
            c = row.get("close", "").strip()
            if t and d and c:
                try:
                    prices.setdefault(t, {})[d] = float(c)
                except ValueError:
                    pass
    return prices


def get_price(
    prices: Dict[str, Dict[str, float]], ticker: str, target_date: str, max_lookback: int = 5
) -> Optional[float]:
    """Get closing price on or near target_date (look back up to max_lookback days)."""
    ticker_prices = prices.get(ticker, {})
    if not ticker_prices:
        return None
    dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    for offset in range(max_lookback + 1):
        d = (dt - timedelta(days=offset)).isoformat()
        if d in ticker_prices:
            return ticker_prices[d]
    return None


def get_price_forward(
    prices: Dict[str, Dict[str, float]], ticker: str, anchor_date: str, trading_days: int
) -> Optional[float]:
    """Get closing price N trading days after anchor_date."""
    ticker_prices = prices.get(ticker, {})
    if not ticker_prices:
        return None
    sorted_dates = sorted(d for d in ticker_prices if d > anchor_date)
    if len(sorted_dates) >= trading_days:
        return ticker_prices[sorted_dates[trading_days - 1]]
    return None


# ---------------------------------------------------------------------------
# Load EV predictions
# ---------------------------------------------------------------------------


def load_ev_predictions(ev_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Load all EV score files, keyed by date."""
    predictions: Dict[str, List[Dict[str, Any]]] = {}
    for f in sorted(ev_dir.glob("*_event_ev_scores.json")):
        date_str = f.name[:10]
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            events = data.get("events", data.get("leaderboard", []))
            if events:
                predictions[date_str] = events
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Skipping %s: %s", f.name, exc)
    return predictions


# ---------------------------------------------------------------------------
# Load CRT resolutions
# ---------------------------------------------------------------------------


def load_resolutions(resolutions_root: Path) -> List[Dict[str, Any]]:
    """Load all CRT resolution files."""
    resolutions = []
    if not resolutions_root.exists():
        return resolutions
    for month_dir in sorted(resolutions_root.iterdir()):
        if not month_dir.is_dir():
            continue
        for f in sorted(month_dir.glob("*.json")):
            if f.name.startswith(("calibration", "manual", "watchlist")):
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    rec = json.load(fh)
                if rec.get("outcome") in ("HIT", "MISS", "MIXED"):
                    resolutions.append(rec)
            except (json.JSONDecodeError, OSError):
                pass
    return resolutions


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------


def _normalize_event_type(crt_type: str) -> str:
    """Map CRT catalyst_type to EV event_type for matching."""
    return _TYPE_MAP.get(crt_type, crt_type)


def _record_hash(ticker: str, catalyst_date: str, prediction_date: str) -> str:
    """Deterministic hash for dedup."""
    blob = f"{ticker}|{catalyst_date}|{prediction_date}"
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def match_predictions_to_resolutions(
    predictions: Dict[str, List[Dict[str, Any]]],
    resolutions: List[Dict[str, Any]],
    prices: Dict[str, Dict[str, float]],
    existing_hashes: set,
) -> List[Dict[str, Any]]:
    """Match EV predictions to CRT resolutions and compute realized returns.

    For each resolution, finds the most recent EV prediction that was made
    BEFORE the catalyst date for the same ticker and event type.
    """
    matched = []

    # Index resolutions by (ticker, normalized_type)
    for res in resolutions:
        ticker = res.get("ticker", "").upper()
        catalyst_date = res.get("catalyst_date", "")
        crt_type = res.get("catalyst_type", "")
        outcome = res.get("outcome", "")
        resolution_date = res.get("resolution_date", "")

        if not (ticker and catalyst_date and outcome):
            continue

        ev_type = _normalize_event_type(crt_type)

        # Find best matching prediction: most recent prediction_date < catalyst_date
        best_pred = None
        best_pred_date = ""

        for pred_date, events in sorted(predictions.items()):
            if pred_date >= catalyst_date:
                continue  # Prediction must be before the event
            for ev in events:
                ev_ticker = ev.get("ticker", "").upper()
                ev_event_type = ev.get("event_type", "")
                if ev_ticker == ticker and ev_event_type == ev_type:
                    if pred_date > best_pred_date:
                        best_pred = ev
                        best_pred_date = pred_date

        if best_pred is None:
            continue  # No matching prediction found

        # Dedup
        rec_hash = _record_hash(ticker, catalyst_date, best_pred_date)
        if rec_hash in existing_hashes:
            continue

        # Compute realized returns from price history
        pre_price = get_price(prices, ticker, catalyst_date, max_lookback=1)
        post_1d = get_price_forward(prices, ticker, catalyst_date, 1)
        post_5d = get_price_forward(prices, ticker, catalyst_date, 5)
        post_20d = get_price_forward(prices, ticker, catalyst_date, 20)

        realized_1d = ((post_1d / pre_price) - 1) if (pre_price and post_1d) else None
        realized_5d = ((post_5d / pre_price) - 1) if (pre_price and post_5d) else None
        realized_20d = ((post_20d / pre_price) - 1) if (pre_price and post_20d) else None

        # Outcome as binary for Brier score
        outcome_binary = 1.0 if outcome == "HIT" else 0.0 if outcome == "MISS" else 0.5

        record = {
            "schema": SCHEMA_VERSION,
            "record_hash": rec_hash,
            "ticker": ticker,
            "catalyst_date": catalyst_date,
            "catalyst_type": crt_type,
            "event_type": ev_type,
            "resolution_date": resolution_date,
            # Prediction (from EV score at prediction_date)
            "prediction_date": best_pred_date,
            "predicted_p_hit": best_pred.get("p_hit"),
            "predicted_p_miss": best_pred.get("p_miss"),
            "predicted_implied_p_hit": best_pred.get("implied_p_hit"),
            "predicted_mispricing": best_pred.get("mispricing"),
            "predicted_scenario_ev": best_pred.get("scenario_ev"),
            "predicted_ds_adj_ev": best_pred.get("ds_adj_ev"),
            "predicted_upside_hit": best_pred.get("upside_hit"),
            "predicted_downside_miss": best_pred.get("downside_miss"),
            "event_family": best_pred.get("event_family"),
            "phase": best_pred.get("phase"),
            "analog_conf": best_pred.get("analog_conf"),
            "days_to_event_at_prediction": best_pred.get("days_to_event"),
            # Outcome (from CRT resolution)
            "outcome": outcome,
            "outcome_binary": outcome_binary,
            "outcome_detail": res.get("outcome_detail", ""),
            # Realized returns (from price history)
            "pre_event_price": round(pre_price, 4) if pre_price else None,
            "realized_1d_return": round(realized_1d, 6) if realized_1d is not None else None,
            "realized_5d_return": round(realized_5d, 6) if realized_5d is not None else None,
            "realized_20d_return": round(realized_20d, 6) if realized_20d is not None else None,
            # Calibration metrics
            "brier_component": round((best_pred.get("p_hit", 0) - outcome_binary) ** 2, 6),
            "ev_error": (
                round((best_pred.get("scenario_ev", 0) or 0) - (realized_1d or 0), 6)
                if realized_1d is not None
                else None
            ),
        }

        matched.append(record)
        existing_hashes.add(rec_hash)

    return matched


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------


def compute_summary(ledger: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute calibration summary from the validation ledger."""
    if not ledger:
        return {
            "schema": SCHEMA_VERSION,
            "n_matched": 0,
            "status": "insufficient_data",
        }

    n = len(ledger)
    brier_scores = [r["brier_component"] for r in ledger if r.get("brier_component") is not None]
    ev_errors = [r["ev_error"] for r in ledger if r.get("ev_error") is not None]
    outcomes = [r["outcome"] for r in ledger]

    # Outcome distribution
    outcome_counts = defaultdict(int)
    for o in outcomes:
        outcome_counts[o] += 1

    # P(hit) calibration by bucket
    p_hit_buckets: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for r in ledger:
        p = r.get("predicted_p_hit")
        ob = r.get("outcome_binary")
        if p is not None and ob is not None:
            if p < 0.3:
                bucket = "low (<0.30)"
            elif p < 0.6:
                bucket = "mid (0.30-0.60)"
            else:
                bucket = "high (>=0.60)"
            p_hit_buckets[bucket].append((p, ob))

    calibration_by_bucket = {}
    for bucket, pairs in sorted(p_hit_buckets.items()):
        preds = [p for p, _ in pairs]
        actuals = [a for _, a in pairs]
        calibration_by_bucket[bucket] = {
            "n": len(pairs),
            "mean_predicted": round(sum(preds) / len(preds), 4),
            "mean_actual": round(sum(actuals) / len(actuals), 4),
            "calibration_gap": round(sum(preds) / len(preds) - sum(actuals) / len(actuals), 4),
        }

    # By family
    by_family: Dict[str, List[Dict]] = defaultdict(list)
    for r in ledger:
        fam = r.get("event_family", "UNKNOWN")
        by_family[fam].append(r)

    family_stats = {}
    for fam, records in sorted(by_family.items()):
        fam_brier = [r["brier_component"] for r in records if r.get("brier_component") is not None]
        fam_ev_err = [r["ev_error"] for r in records if r.get("ev_error") is not None]
        hit_count = sum(1 for r in records if r["outcome"] == "HIT")
        family_stats[fam] = {
            "n": len(records),
            "hit_rate": round(hit_count / len(records), 4) if records else None,
            "mean_brier": round(sum(fam_brier) / len(fam_brier), 4) if fam_brier else None,
            "mean_ev_error": round(sum(fam_ev_err) / len(fam_ev_err), 4) if fam_ev_err else None,
        }

    summary = {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(tz=__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_matched": n,
        "status": "accumulating" if n < 20 else "evaluable",
        "outcome_distribution": dict(outcome_counts),
        # Aggregate calibration
        "brier_score": round(sum(brier_scores) / len(brier_scores), 4) if brier_scores else None,
        "mean_ev_error": round(sum(ev_errors) / len(ev_errors), 4) if ev_errors else None,
        "mean_abs_ev_error": round(sum(abs(e) for e in ev_errors) / len(ev_errors), 4) if ev_errors else None,
        # Breakdowns
        "calibration_by_p_hit_bucket": calibration_by_bucket,
        "by_family": family_stats,
        # Data quality
        "n_with_prices": sum(1 for r in ledger if r.get("realized_1d_return") is not None),
        "n_without_prices": sum(1 for r in ledger if r.get("realized_1d_return") is None),
        "earliest_prediction": min((r["prediction_date"] for r in ledger), default=None),
        "latest_resolution": max((r["resolution_date"] for r in ledger if r.get("resolution_date")), default=None),
    }

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(rebuild: bool = False) -> Dict[str, Any]:
    """Run the forward validation loop."""

    # Load data sources
    logger.info("Loading EV predictions...")
    predictions = load_ev_predictions(EV_ARTIFACTS)
    logger.info("  %d prediction dates loaded", len(predictions))

    logger.info("Loading CRT resolutions...")
    resolutions = load_resolutions(RESOLUTIONS_ROOT)
    logger.info("  %d resolved events loaded", len(resolutions))

    logger.info("Loading price history...")
    prices = load_prices(PRICE_CSV)
    logger.info("  %d tickers with price data", len(prices))

    # Load existing ledger (for dedup)
    existing_hashes: set = set()
    existing_records: List[Dict[str, Any]] = []
    if not rebuild and LEDGER_PATH.exists():
        with open(LEDGER_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        existing_records.append(rec)
                        existing_hashes.add(rec.get("record_hash", ""))
                    except json.JSONDecodeError:
                        pass
        logger.info("  %d existing ledger entries loaded", len(existing_records))

    # Match predictions to resolutions
    new_matches = match_predictions_to_resolutions(
        predictions,
        resolutions,
        prices,
        existing_hashes,
    )
    logger.info("  %d new matches found", len(new_matches))

    # Append new matches to ledger
    if new_matches:
        EV_ARTIFACTS.mkdir(parents=True, exist_ok=True)
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            for rec in new_matches:
                f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
        logger.info("  Appended %d records to %s", len(new_matches), LEDGER_PATH.name)

    # Compute summary over full ledger
    all_records = existing_records + new_matches if not rebuild else new_matches
    summary = compute_summary(all_records)

    # Write summary
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    logger.info("  Summary written to %s", SUMMARY_PATH.name)

    # Print report
    print(f"\n{'='*60}")
    print("EVENT EV FORWARD VALIDATION")
    print("=" * 60)
    print(f"  Matched records:  {summary['n_matched']}")
    print(f"  Status:           {summary['status']}")
    if summary.get("outcome_distribution"):
        od = summary["outcome_distribution"]
        print(f"  Outcomes:         HIT={od.get('HIT', 0)} MISS={od.get('MISS', 0)} MIXED={od.get('MIXED', 0)}")
    if summary.get("brier_score") is not None:
        print(f"  Brier score:      {summary['brier_score']:.4f}")
    if summary.get("mean_ev_error") is not None:
        print(f"  Mean EV error:    {summary['mean_ev_error']:+.4f}")
        print(f"  Mean |EV error|:  {summary['mean_abs_ev_error']:.4f}")
    print(f"  With prices:      {summary.get('n_with_prices', 0)}")
    print(f"  Without prices:   {summary.get('n_without_prices', 0)}")

    if summary.get("by_family"):
        print("\n  By family:")
        for fam, stats in summary["by_family"].items():
            print(
                f"    {fam}: n={stats['n']}, hit_rate={stats.get('hit_rate', '?')}, brier={stats.get('mean_brier', '?')}"
            )

    if summary.get("calibration_by_p_hit_bucket"):
        print("\n  P(hit) calibration:")
        for bucket, cal in summary["calibration_by_p_hit_bucket"].items():
            print(
                f"    {bucket}: n={cal['n']}, predicted={cal['mean_predicted']:.3f}, actual={cal['mean_actual']:.3f}, gap={cal['calibration_gap']:+.3f}"
            )

    print(f"{'='*60}\n")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Event EV forward validation")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild ledger from scratch")
    parser.add_argument("--as-of-date", type=str, help="Unused (runs against all available data)")
    args = parser.parse_args()

    run(rebuild=args.rebuild)


if __name__ == "__main__":
    main()
