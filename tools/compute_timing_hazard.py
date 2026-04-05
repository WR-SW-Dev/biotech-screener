#!/usr/bin/env python3
"""Timing-hazard dashboard overlay.

Computes per-catalyst timing estimates from the latest production snapshot
and writes dashboard-readable artifacts. No portfolio override — purely
informational overlay for operator attention.

Outputs per catalyst:
  - on_time_prob, slip_prob_30d, slip_prob_60d_plus
  - timing_confidence_bucket (HIGH/MEDIUM/LOW/STALE)
  - top_driver_1..3 explaining the score
  - last_update_age (days since last AACT/CTgov update)
  - execution_warning_flag (boolean)

Usage:
    python3 tools/compute_timing_hazard.py
    python3 tools/compute_timing_hazard.py --snapshot-date 2026-04-03
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from event_ev.data_contracts import CatalystNode
from event_ev.timing_hazard import TimingHazardModel

SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
TRIAL_RECORDS = REPO_ROOT / "production_data" / "trial_records.json"
AACT_DELTAS_DIR = REPO_ROOT / "artifacts" / "aact_deltas"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "timing_hazard"
CALIBRATION_LEDGER = OUTPUT_DIR / "calibration_ledger.jsonl"

# Rolling base rate parameters (OOS-validated, v2)
ROLLING_WINDOW_RECORDS = 200  # ~90 days of weekly-deduped outcomes
ROLLING_FALLBACK = 0.70  # fallback when ledger has insufficient data

# Hybrid near-term override (OOS-validated, v2.1)
# Near-term catalysts (0-30d) have 28% base rate — rolling base (~70%) is catastrophically wrong.
# Rule-based override: Brier 0.175 vs current 0.396 on near-term OOS data.
NEAR_TERM_DAYS = 30
NEAR_TERM_REGULATORY_PROB = 0.98  # regulatory events are near-deterministic
NEAR_TERM_HARD_PROB = 0.85  # hard catalysts with confirmed dates
NEAR_TERM_SOFT_PROB = 0.28  # empirical near-term base rate from OOS data

# Source quality hierarchy for catalyst sources
SOURCE_QUALITY = {
    "SEC_8K_FILING": 0.90,
    "FDA_CALENDAR": 0.95,
    "PDUFA_MANUAL": 0.95,
    "CTGOV_CALENDAR": 0.60,
    "CTGOV_PCD_FAR": 0.35,
    "IR_EVENTS": 0.50,
    "CTGOV": 0.40,
}

# Phase mapping from rankings.csv to event_ev node format
PHASE_MAP = {
    "1": "1",
    "1.0": "1",
    "1.5": "1_2",
    "2": "2",
    "2.0": "2",
    "2.5": "2_3",
    "3": "3",
    "3.0": "3",
    "4": "4",
    "4.0": "4",
}

# Event family mapping
FAMILY_MAP = {
    "CLINICAL": "CLINICAL",
    "REGULATORY": "REGULATORY",
    "SAFETY": "SAFETY",
}

# Precision mapping
PRECISION_MAP = {
    "DAY": "DAY",
    "WEEK": "WEEK",
    "MONTH": "MONTH",
    "QUARTER": "QUARTER",
    "HALF_YEAR": "HALF_YEAR",
    "YEAR": "YEAR",
    "UNKNOWN": "UNKNOWN",
}


def _sf(v, default=None):
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _load_trial_update_dates():
    """Load last_update_posted by ticker from trial records."""
    if not TRIAL_RECORDS.exists():
        return {}
    trials = json.loads(TRIAL_RECORDS.read_text())
    # For each ticker, find the most recent last_update_posted across active trials
    by_ticker = {}
    for t in trials:
        ticker = t.get("ticker", "")
        if not ticker:
            continue
        status = t.get("status", "")
        if status not in (
            "RECRUITING",
            "ACTIVE_NOT_RECRUITING",
            "ENROLLING_BY_INVITATION",
            "NOT_YET_RECRUITING",
            "COMPLETED",
        ):
            continue
        lup = _parse_date(t.get("last_update_posted"))
        if lup:
            if ticker not in by_ticker or lup > by_ticker[ticker]:
                by_ticker[ticker] = lup
    return by_ticker


def _load_aact_delta_for_ticker(ticker, snap_date_str):
    """Load latest AACT delta for a ticker on or before snapshot date."""
    if not AACT_DELTAS_DIR.exists():
        return None
    for path in sorted(AACT_DELTAS_DIR.glob("aact_deltas_*.json"), reverse=True):
        fname = path.stem.replace("aact_deltas_", "")
        if fname > snap_date_str:
            continue
        data = json.loads(path.read_text())
        for t in data.get("tickers", []):
            if t.get("ticker") == ticker:
                return t
        break  # only check most recent delta file on or before snapshot
    return None


def _load_rolling_base_rate(as_of_date: str) -> float:
    """Compute trailing on-time rate from calibration ledger.

    Uses resolved predictions (actual_outcome != null) up to as_of_date.
    Returns the rolling base rate, or ROLLING_FALLBACK if insufficient data.
    """
    if not CALIBRATION_LEDGER.exists():
        return ROLLING_FALLBACK

    resolved = []
    with open(CALIBRATION_LEDGER, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Only use resolved entries with a known outcome
            outcome = entry.get("actual_outcome")
            pred_date = entry.get("prediction_date", "")
            if outcome and pred_date < as_of_date:
                on_time = 1 if outcome == "ON_TIME" else 0
                resolved.append(on_time)

    if len(resolved) < 20:
        return ROLLING_FALLBACK

    # Use the most recent ROLLING_WINDOW_RECORDS
    recent = resolved[-ROLLING_WINDOW_RECORDS:]
    return sum(recent) / len(recent)


def _build_catalyst_node(row, snap_date, trial_update_dates, aact_delta):
    """Convert a rankings.csv row into a CatalystNode for timing estimation."""
    ticker = row.get("ticker", "")
    catalyst_days = _sf(row.get("catalyst_days"))
    if catalyst_days is None or catalyst_days <= 0:
        return None

    expected_date = snap_date + timedelta(days=int(catalyst_days))

    event_type = row.get("catalyst_event_type", "")
    event_family = FAMILY_MAP.get(row.get("catalyst_family", ""), "CLINICAL")
    source = row.get("catalyst_source", "")
    precision = PRECISION_MAP.get(row.get("clinical_days_precision", ""), "UNKNOWN")
    confidence = _sf(row.get("clinical_date_confidence"), 0.5)
    phase_raw = str(_sf(row.get("lead_program_phase"), 0))
    phase = PHASE_MAP.get(phase_raw, "unknown")

    # Sponsor quality from source hierarchy
    sponsor_quality = SOURCE_QUALITY.get(source, 0.40)

    # Build a minimal CatalystNode
    node = CatalystNode(
        ticker=ticker,
        event_family=event_family,
        event_type=event_type or ("PDUFA" if event_family == "REGULATORY" else "CT_PRIMARY_COMPLETION"),
        event_subtype="",
        expected_date=str(expected_date),
        date_range_start=None,
        date_range_end=None,
        date_precision=precision,
        date_confidence=confidence,
        source=source or "UNKNOWN",
        source_uid=f"rankings_{ticker}_{snap_date}",
        disclosed_at=str(snap_date),
        phase=phase,
        indication=row.get("therapeutic_area", ""),
        sponsor_quality=sponsor_quality,
        nct_id=None,
    )

    return node


def _compute_confidence_bucket(on_time_prob, slip_prob, last_update_age, logistic_prob=None):
    """Assign a timing confidence bucket.

    With rolling base rate, on_time_prob is the same for all catalysts.
    Confidence is now driven by the per-ticker logistic estimate + data quality.
    """
    if last_update_age is not None and last_update_age > 180:
        return "STALE"
    # Use logistic prob for per-ticker differentiation when available
    p = logistic_prob if logistic_prob is not None else on_time_prob
    if p >= 0.70:
        return "HIGH"
    if p >= 0.45:
        return "MEDIUM"
    return "LOW"


def _compute_top_drivers(features, coefficients):
    """Identify top 3 drivers of the timing score."""
    contributions = []
    for key, value in features.items():
        coeff = coefficients.get(key, 0.0)
        contrib = coeff * float(value)
        if abs(contrib) > 0.01:
            direction = "↑on_time" if contrib > 0 else "↑slip"
            contributions.append((key, abs(contrib), direction))

    contributions.sort(key=lambda x: x[1], reverse=True)
    return [{"feature": c[0], "magnitude": round(c[1], 3), "direction": c[2]} for c in contributions[:3]]


def _compute_execution_warning(
    on_time_prob,
    last_update_age,
    aact_delta,
    is_hard,
    logistic_prob=None,
):
    """Flag positions that need operator attention.

    With rolling base rate, on_time_prob is the same for all catalysts.
    Warnings now use logistic_prob (per-ticker model estimate) and
    non-probability signals (stale update, PCD delays, status downgrades).
    """
    warnings = []

    # Logistic model flags this as high-risk (below 0.50 — per-ticker signal)
    if logistic_prob is not None and logistic_prob < 0.50:
        warnings.append("low_logistic_prob")

    if last_update_age is not None and last_update_age > 120:
        warnings.append("stale_update")

    if aact_delta:
        n_delayed = aact_delta.get("n_pcd_delayed", 0)
        n_downgrades = aact_delta.get("n_status_downgrades", 0)
        if n_delayed > 0:
            warnings.append("pcd_delayed")
        if n_downgrades > 0:
            warnings.append("status_downgrade")

    return bool(warnings), warnings


def compute_timing_hazard(snapshot_date=None):
    """Compute timing hazard for all catalysts in a snapshot.

    Returns dict with per-position timing estimates and summary.
    """
    # Find snapshot
    if not snapshot_date:
        available = sorted(
            d.name
            for d in SNAPSHOTS_DIR.iterdir()
            if d.is_dir() and (d / "rankings.csv").exists() and "__pre_" not in d.name and not d.name.startswith("_")
        )
        if not available:
            return {"error": "no snapshots found"}
        snapshot_date = available[-1]

    rankings_path = SNAPSHOTS_DIR / snapshot_date / "rankings.csv"
    if not rankings_path.exists():
        return {"error": f"no rankings.csv for {snapshot_date}"}

    snap_date = _parse_date(snapshot_date)
    if not snap_date:
        return {"error": f"invalid date {snapshot_date}"}

    # Load data
    with open(rankings_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    trial_update_dates = _load_trial_update_dates()
    model = TimingHazardModel()

    # Load rolling base rate (OOS-validated adaptive anchor)
    rolling_base = _load_rolling_base_rate(snapshot_date)

    # Process each position with a catalyst
    results = []
    for row in rows:
        rank = _sf(row.get("actionable_rank"))
        if rank is None or rank > 60:
            continue

        ticker = row.get("ticker", "")
        catalyst_days = _sf(row.get("catalyst_days"))
        if catalyst_days is None or catalyst_days <= 0:
            continue

        # Load AACT delta for this ticker
        aact_delta = _load_aact_delta_for_ticker(ticker, snapshot_date)

        # Build node
        node = _build_catalyst_node(row, snap_date, trial_update_dates, aact_delta)
        if not node:
            continue

        # Run timing model
        estimate = model.estimate(node, snap_date)

        # Last update age
        last_lup = trial_update_dates.get(ticker)
        last_update_age = (snap_date - last_lup).days if last_lup else None

        # Derived fields — hybrid probability (OOS-validated v2.1)
        # Near-term (0-30d): rule-based override (Brier 0.175 vs current 0.396)
        # Medium+ (31d+): rolling base rate anchor (Brier 0.184 overall)
        logistic_prob = estimate.prob_on_time
        catalyst_family = row.get("catalyst_family", "")
        is_hard = _sf(row.get("is_hard_catalyst"), 0) == 1.0

        if catalyst_days <= NEAR_TERM_DAYS:
            # Near-term: rule-based by catalyst type
            if catalyst_family == "REGULATORY":
                on_time_prob = NEAR_TERM_REGULATORY_PROB
            elif is_hard:
                on_time_prob = NEAR_TERM_HARD_PROB
            else:
                on_time_prob = NEAR_TERM_SOFT_PROB
            prob_method = "near_term_rule"
        else:
            # Medium/far: rolling base rate
            on_time_prob = rolling_base
            prob_method = "rolling_base_rate"

        slip_prob = 1.0 - on_time_prob
        # Split slip into 30d and 60d+
        slip_prob_30d = slip_prob * 0.55
        slip_prob_60d_plus = slip_prob * 0.45

        confidence_bucket = _compute_confidence_bucket(
            on_time_prob,
            slip_prob,
            last_update_age,
            logistic_prob=logistic_prob,
        )
        top_drivers = _compute_top_drivers(
            estimate.features_used,
            model.coefficients,
        )
        warning_flag, warning_reasons = _compute_execution_warning(
            on_time_prob,
            last_update_age,
            aact_delta,
            _sf(row.get("is_hard_catalyst"), 0) == 1.0,
            logistic_prob=logistic_prob,
        )

        results.append(
            {
                "ticker": ticker,
                "rank": int(rank),
                "catalyst_days": int(catalyst_days),
                "catalyst_event_type": row.get("catalyst_event_type", ""),
                "catalyst_family": row.get("catalyst_family", ""),
                "catalyst_source": row.get("catalyst_source", ""),
                "is_hard_catalyst": _sf(row.get("is_hard_catalyst"), 0) == 1.0,
                # Timing estimates (v2.1: hybrid — near-term rule + rolling base)
                "on_time_prob": round(on_time_prob, 3),
                "on_time_prob_logistic": round(logistic_prob, 3),  # legacy logistic for comparison
                "prob_method": prob_method,
                "slip_prob_30d": round(slip_prob_30d, 3),
                "slip_prob_60d_plus": round(slip_prob_60d_plus, 3),
                "expected_delay_days": estimate.expected_delay_days,
                # Confidence
                "timing_confidence_bucket": confidence_bucket,
                # Drivers
                "top_driver_1": top_drivers[0] if len(top_drivers) > 0 else None,
                "top_driver_2": top_drivers[1] if len(top_drivers) > 1 else None,
                "top_driver_3": top_drivers[2] if len(top_drivers) > 2 else None,
                # Update age
                "last_update_age": last_update_age,
                # Warning
                "execution_warning_flag": warning_flag,
                "warning_reasons": warning_reasons if warning_flag else [],
                # Full estimate for downstream
                "hazard_rate": estimate.hazard_rate,
                "median_arrival_days": estimate.median_arrival_days,
            }
        )

    # Sort by warning flag (warnings first), then by on_time_prob ascending
    results.sort(key=lambda x: (-x["execution_warning_flag"], x["on_time_prob"]))

    # Summary
    n_warnings = sum(1 for r in results if r["execution_warning_flag"])
    n_high = sum(1 for r in results if r["timing_confidence_bucket"] == "HIGH")
    n_medium = sum(1 for r in results if r["timing_confidence_bucket"] == "MEDIUM")
    n_low = sum(1 for r in results if r["timing_confidence_bucket"] == "LOW")
    n_stale = sum(1 for r in results if r["timing_confidence_bucket"] == "STALE")

    return {
        "schema": "timing_hazard_overlay.v2",
        "snapshot_date": snapshot_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probability_method": "rolling_base_rate_90d",
        "rolling_base_rate": round(rolling_base, 3),
        "n_catalysts": len(results),
        "n_warnings": n_warnings,
        "confidence_dist": {
            "HIGH": n_high,
            "MEDIUM": n_medium,
            "LOW": n_low,
            "STALE": n_stale,
        },
        "mean_on_time_prob": (round(sum(r["on_time_prob"] for r in results) / len(results), 3) if results else None),
        "catalysts": results,
    }


def append_calibration_ledger(result: dict):
    """Append timing predictions to calibration ledger for future outcome tracking.

    Each entry records the prediction at the time it was made. When the catalyst
    resolves, a separate process will match predictions to outcomes for Brier scoring.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snap_date = result.get("snapshot_date", "")

    with open(CALIBRATION_LEDGER, "a") as f:
        for cat in result.get("catalysts", []):
            entry = {
                "prediction_date": snap_date,
                "ticker": cat["ticker"],
                "catalyst_days": cat["catalyst_days"],
                "catalyst_event_type": cat["catalyst_event_type"],
                "catalyst_family": cat["catalyst_family"],
                "is_hard_catalyst": cat["is_hard_catalyst"],
                "on_time_prob": cat["on_time_prob"],
                "on_time_prob_logistic": cat.get("on_time_prob_logistic"),
                "probability_method": result.get("probability_method", "rolling_base_rate_90d"),
                "slip_prob_30d": cat["slip_prob_30d"],
                "slip_prob_60d_plus": cat["slip_prob_60d_plus"],
                "timing_confidence_bucket": cat["timing_confidence_bucket"],
                "execution_warning_flag": cat["execution_warning_flag"],
                # Outcome fields — filled later by calibration scorer
                "actual_outcome": None,  # ON_TIME, SLIP_30D, SLIP_60D_PLUS, EARLY
                "actual_delay_days": None,
                "outcome_recorded_at": None,
            }
            f.write(json.dumps(entry, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Timing hazard dashboard overlay",
    )
    parser.add_argument(
        "--snapshot-date",
        default=None,
        help="Snapshot date (default: latest)",
    )
    parser.add_argument(
        "--no-ledger",
        action="store_true",
        help="Skip calibration ledger append",
    )
    args = parser.parse_args()

    result = compute_timing_hazard(args.snapshot_date)

    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snap = result["snapshot_date"]
    out_path = OUTPUT_DIR / f"timing_hazard_{snap}.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    if not args.no_ledger:
        append_calibration_ledger(result)
        print(f"  Calibration ledger: {CALIBRATION_LEDGER}")

    print(f"TIMING HAZARD OVERLAY — {snap}")
    print(f"  Catalysts: {result['n_catalysts']}")
    print(f"  Warnings: {result['n_warnings']}")
    print(f"  Confidence: {result['confidence_dist']}")
    print(f"  Mean P(on_time): {result['mean_on_time_prob']}")

    # Print warnings first, then all
    for cat in result["catalysts"]:
        if cat["execution_warning_flag"]:
            reasons = ", ".join(cat["warning_reasons"])
            print(
                f"  ⚠ {cat['ticker']:6s} rank={cat['rank']:2d} "
                f"P(on_time)={cat['on_time_prob']:.2f} "
                f"conf={cat['timing_confidence_bucket']} "
                f"[{reasons}]"
            )

    print("\n  All catalysts:")
    for cat in result["catalysts"][:20]:
        warn = "⚠" if cat["execution_warning_flag"] else " "
        d1 = cat.get("top_driver_1", {})
        driver_str = f"{d1.get('feature', '?')} {d1.get('direction', '')}" if d1 else ""
        print(
            f"  {warn} {cat['ticker']:6s} rank={cat['rank']:2d} "
            f"days={cat['catalyst_days']:3d} "
            f"P(on_time)={cat['on_time_prob']:.2f} "
            f"slip30={cat['slip_prob_30d']:.2f} "
            f"slip60+={cat['slip_prob_60d_plus']:.2f} "
            f"conf={cat['timing_confidence_bucket']:6s} "
            f"upd_age={cat['last_update_age'] or '?':>4} "
            f"[{driver_str}]"
        )

    print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
