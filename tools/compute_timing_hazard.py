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
import logging
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("timing_hazard")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from event_ev.data_contracts import CatalystNode
from event_ev.timing_hazard import TimingHazardModel

SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
TRIAL_RECORDS = REPO_ROOT / "production_data" / "trial_records.json"
AACT_DELTAS_DIR = REPO_ROOT / "artifacts" / "aact_deltas"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "timing_hazard"
CALIBRATION_LEDGER = OUTPUT_DIR / "calibration_ledger.jsonl"
CALIBRATION_BY_SLICE = OUTPUT_DIR / "calibration_by_slice.json"

# Rolling base rate parameters (OOS-validated, v2 → v3 sliced)
ROLLING_WINDOW_DAYS = 120  # 120d rolling window (best ECE=0.030 on 1691 OOS records)
ROLLING_WINDOW_RECORDS = 200  # record-count fallback for global rate
ROLLING_FALLBACK = 0.70  # fallback when ledger has insufficient data
ROLLING_MIN_SLICE_SAMPLES = 10  # min records per family×horizon slice

# Near-term override: adaptive from rolling window, fallback to constants.
NEAR_TERM_DAYS = 30
NEAR_TERM_ADAPTIVE_WINDOW_DAYS = 90  # shorter window = more reactive
NEAR_TERM_MIN_SLICE_SAMPLES = 20  # require 20+ resolved outcomes per slice
# Fallback constants (from resolved OOS outcomes, 2026-04-06)
NEAR_TERM_REGULATORY_PROB = 0.98
NEAR_TERM_HARD_PROB = 0.95
NEAR_TERM_SOFT_PROB = 0.87
NEAR_TERM_UNKNOWN_PROB = 0.80

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

# ---------------------------------------------------------------------------
# Timing bucket classification (Spec 058)
# ---------------------------------------------------------------------------

HORIZON_NEAR_DAYS = 30
HORIZON_MEDIUM_DAYS = 90


def classify_horizon_bucket(catalyst_days: float) -> str:
    """Classify catalyst into NEAR / MEDIUM / FAR horizon bucket."""
    if catalyst_days <= HORIZON_NEAR_DAYS:
        return "NEAR"
    if catalyst_days <= HORIZON_MEDIUM_DAYS:
        return "MEDIUM"
    return "FAR"


def classify_hardness(is_hard_catalyst: bool, source: str) -> str:
    """Classify catalyst as HARD or SOFT based on source and hard flag."""
    if is_hard_catalyst:
        return "HARD"
    hard_sources = {"SEC_8K_FILING", "FDA_CALENDAR", "PDUFA_MANUAL"}
    if source in hard_sources:
        return "HARD"
    return "SOFT"


def classify_family_bucket(catalyst_family: str, event_type: str = "") -> str:
    """Normalize catalyst family to REGULATORY / CLINICAL / SAFETY / UNKNOWN.

    Falls back to event_type classification when catalyst_family is empty.
    """
    if catalyst_family in ("REGULATORY", "CLINICAL", "SAFETY"):
        return catalyst_family

    # Infer from event_type when family is missing
    if event_type:
        et = event_type.upper()
        if et.startswith("CT_") or et in (
            "DATA_READOUT",
            "PHASE_1_DATA",
            "PHASE_2_READOUT",
            "PHASE_3_READOUT",
            "INTERIM_ANALYSIS",
        ):
            return "CLINICAL"
        if et.startswith("FDA_") or et in (
            "PDUFA",
            "PDUFA_ACTION",
            "NDA_BLA_FILING",
            "ADVISORY_COMMITTEE",
            "REGULATORY_DESIGNATION",
        ):
            return "REGULATORY"

    # Default: biotech screener universe is overwhelmingly clinical,
    # but missing metadata signals lower-confidence scheduling.
    # Keep as separate bucket — UNKNOWN catalysts slip 2x more than confirmed CLINICAL.
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Calibration-by-slice (Spec 058)
# ---------------------------------------------------------------------------


def compute_calibration_by_slice(
    as_of_date: str,
    trailing_days: int = 90,
) -> dict:
    """Compute calibration metrics grouped by family x horizon x hardness.

    Only uses resolved entries from the calibration ledger (actual_outcome != null)
    within the trailing window.
    """
    if not CALIBRATION_LEDGER.exists():
        return {"slices": [], "n_resolved": 0, "trailing_days": trailing_days}

    from datetime import date as _date

    cutoff = _date.fromisoformat(as_of_date[:10]) - timedelta(days=trailing_days)
    cutoff_str = cutoff.isoformat()

    # Read resolved entries
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
            outcome = entry.get("actual_outcome")
            pred_date = entry.get("prediction_date", "")
            if outcome and pred_date >= cutoff_str and pred_date < as_of_date:
                resolved.append(entry)

    if not resolved:
        return {"slices": [], "n_resolved": 0, "trailing_days": trailing_days}

    # Group by (family_bucket, horizon_bucket, hardness)
    from collections import Counter, defaultdict

    # Each bucket entry: (prob, on_time, ticker, event_type)
    buckets = defaultdict(list)
    for entry in resolved:
        family = classify_family_bucket(entry.get("catalyst_family", ""), entry.get("catalyst_event_type", ""))
        horizon = entry.get("horizon_bucket", "UNKNOWN")
        hardness = entry.get("hardness", "UNKNOWN")
        on_time = 1 if entry["actual_outcome"] == "ON_TIME" else 0
        prob = entry.get("on_time_prob", 0.5)
        ticker = entry.get("ticker", "?")
        event_type = entry.get("catalyst_event_type", "?")
        buckets[(family, horizon, hardness)].append((prob, on_time, ticker, event_type))

    slices = []
    for (family, horizon, hardness), records in sorted(buckets.items()):
        n = len(records)
        if n == 0:
            continue
        probs, actuals, tickers, event_types = zip(*records)
        mean_prob = sum(probs) / n
        actual_rate = sum(actuals) / n
        brier = sum((p - a) ** 2 for p, a in zip(probs, actuals)) / n

        # --- Concentration diagnostics ---
        distinct_tickers = set(tickers)
        # Event = (ticker, event_type) pair
        distinct_events = set(zip(tickers, event_types))
        ticker_counts = Counter(tickers)
        top_ticker, top_count = ticker_counts.most_common(1)[0]
        top_ticker_share = top_count / n

        # Event-weighted rate: one vote per distinct ticker (de-duped)
        ticker_outcomes: dict[str, list[int]] = defaultdict(list)
        for a, t in zip(actuals, tickers):
            ticker_outcomes[t].append(a)
        # Each ticker votes once: majority outcome
        ticker_votes = [1 if sum(v) > len(v) / 2 else 0 for v in ticker_outcomes.values()]
        event_weighted_rate = sum(ticker_votes) / len(ticker_votes) if ticker_votes else 0.0

        slices.append(
            {
                "family": family,
                "horizon": horizon,
                "hardness": hardness,
                "n": n,
                "n_distinct_tickers": len(distinct_tickers),
                "n_distinct_events": len(distinct_events),
                "top_ticker": top_ticker,
                "top_ticker_share": round(top_ticker_share, 3),
                "mean_predicted_prob": round(mean_prob, 3),
                "actual_on_time_rate": round(actual_rate, 3),
                "event_weighted_on_time_rate": round(event_weighted_rate, 3),
                "brier_score": round(brier, 4),
                "overconfidence": round(mean_prob - actual_rate, 3),
            }
        )

    return {
        "slices": slices,
        "n_resolved": len(resolved),
        "trailing_days": trailing_days,
        "as_of_date": as_of_date,
    }


def _compute_calibration_curve(records, n_bins=10):
    """Compute calibration curve: predicted prob bins vs actual on-time rate."""
    if not records:
        return []
    from collections import defaultdict

    bins = defaultdict(list)
    for prob, actual in records:
        b = min(int(prob * n_bins), n_bins - 1)
        bins[b].append((prob, actual))

    curve = []
    for b in range(n_bins):
        items = bins.get(b, [])
        if not items:
            continue
        probs, actuals = zip(*items)
        curve.append(
            {
                "bin_lower": round(b / n_bins, 2),
                "bin_upper": round((b + 1) / n_bins, 2),
                "mean_predicted": round(sum(probs) / len(probs), 3),
                "actual_rate": round(sum(actuals) / len(actuals), 3),
                "n": len(items),
            }
        )
    return curve


def build_calibration_dashboard(as_of_date: str, trailing_days: int = 90) -> dict:
    """Build extended calibration dashboard with per-horizon curves and source breakdown.

    Extends compute_calibration_by_slice with:
    - Per-horizon calibration curves (decile bins)
    - Source provenance breakdown
    - Overall summary
    """
    if not CALIBRATION_LEDGER.exists():
        return {
            "slices": [],
            "horizons": {},
            "sources": {},
            "overall": {},
            "n_resolved": 0,
            "trailing_days": trailing_days,
            "as_of_date": as_of_date,
        }

    cutoff = (date.fromisoformat(as_of_date[:10]) - timedelta(days=trailing_days)).isoformat()

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
            outcome = entry.get("actual_outcome")
            pred_date = entry.get("prediction_date", "")
            if outcome and pred_date >= cutoff and pred_date < as_of_date:
                resolved.append(entry)

    if not resolved:
        return {
            "slices": [],
            "horizons": {},
            "sources": {},
            "overall": {},
            "n_resolved": 0,
            "trailing_days": trailing_days,
            "as_of_date": as_of_date,
        }

    from collections import defaultdict

    # Slice-level (reuse existing logic)
    slice_buckets = defaultdict(list)
    horizon_buckets = defaultdict(list)
    source_buckets = defaultdict(list)
    all_records = []

    for entry in resolved:
        family = classify_family_bucket(entry.get("catalyst_family", ""), entry.get("catalyst_event_type", ""))
        horizon = entry.get("horizon_bucket", "UNKNOWN")
        hardness = entry.get("hardness", "UNKNOWN")
        source = entry.get("source_provenance", "UNKNOWN")
        on_time = 1 if entry["actual_outcome"] == "ON_TIME" else 0
        prob = entry.get("on_time_prob", 0.5)

        rec = (prob, on_time)
        slice_buckets[(family, horizon, hardness)].append(rec)
        horizon_buckets[horizon].append(rec)
        source_buckets[source].append(rec)
        all_records.append(rec)

    def _summarize(records):
        n = len(records)
        if n == 0:
            return {"n": 0}
        probs, actuals = zip(*records)
        return {
            "n": n,
            "mean_predicted": round(sum(probs) / n, 3),
            "actual_rate": round(sum(actuals) / n, 3),
            "brier": round(sum((p - a) ** 2 for p, a in records) / n, 4),
            "overconfidence": round(sum(probs) / n - sum(actuals) / n, 3),
        }

    # Slices
    slices = []
    for (family, horizon, hardness), recs in sorted(slice_buckets.items()):
        s = _summarize(recs)
        s.update(family=family, horizon=horizon, hardness=hardness)
        slices.append(s)

    # Horizons with calibration curves
    horizons = {}
    for hz, recs in sorted(horizon_buckets.items()):
        summary = _summarize(recs)
        summary["calibration_curve"] = _compute_calibration_curve(recs)
        horizons[hz] = summary

    # Sources
    sources = {}
    for src, recs in sorted(source_buckets.items()):
        sources[src] = _summarize(recs)

    overall = _summarize(all_records)
    overall["calibration_curve"] = _compute_calibration_curve(all_records)

    return {
        "schema": "calibration_dashboard.v1",
        "as_of_date": as_of_date,
        "trailing_days": trailing_days,
        "n_resolved": len(resolved),
        "slices": slices,
        "horizons": horizons,
        "sources": sources,
        "overall": overall,
    }


def _load_rolling_base_rate_with_trend(as_of_date: str):
    """Compute rolling base rate AND trend vs prior window.

    Returns (current_rate, prior_rate, trend_delta).
    trend_delta = current - prior (positive = improving).
    """
    if not CALIBRATION_LEDGER.exists():
        return ROLLING_FALLBACK, None, None

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
            outcome = entry.get("actual_outcome")
            pred_date = entry.get("prediction_date", "")
            if outcome and pred_date < as_of_date:
                on_time = 1 if outcome == "ON_TIME" else 0
                resolved.append(on_time)

    if len(resolved) < 20:
        return ROLLING_FALLBACK, None, None

    w = ROLLING_WINDOW_RECORDS
    recent = resolved[-w:]
    current_rate = sum(recent) / len(recent)

    # Prior window: the w records before the current window
    if len(resolved) >= 2 * w:
        prior = resolved[-2 * w : -w]
        prior_rate = sum(prior) / len(prior)
        trend = round(current_rate - prior_rate, 4)
    else:
        prior_rate = None
        trend = None

    return current_rate, prior_rate, trend


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


def _load_rolling_base_rate_sliced(as_of_date: str):
    """Compute rolling base rate by family × horizon slice (v3).

    OOS-validated: Brier 0.109 vs 0.232 fixed rules on 1,691 resolved outcomes.
    120d window, family × horizon grouping, falls back to global rate per slice.

    Returns:
        dict mapping (family_bucket, horizon_bucket) → float on-time probability,
        plus ("__global__",) key for fallback.
    """
    if not CALIBRATION_LEDGER.exists():
        return {("__global__",): ROLLING_FALLBACK}

    cutoff_date_str = as_of_date
    try:
        cutoff = date.fromisoformat(as_of_date[:10])
        window_start = cutoff - timedelta(days=ROLLING_WINDOW_DAYS)
        window_start_str = str(window_start)
    except (ValueError, TypeError):
        return {("__global__",): ROLLING_FALLBACK}

    # Load entries within the rolling window
    from collections import defaultdict

    slices = defaultdict(list)
    all_vals = []

    with open(CALIBRATION_LEDGER, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            outcome = entry.get("actual_outcome")
            pred_date = entry.get("prediction_date", "")
            if not outcome or pred_date >= cutoff_date_str:
                continue
            if pred_date < window_start_str:
                continue
            on_time = 1.0 if outcome == "ON_TIME" else 0.0
            fb = entry.get("family_bucket", "UNKNOWN")
            hb = entry.get("horizon_bucket", "NEAR")
            slices[(fb, hb)].append(on_time)
            all_vals.append(on_time)

    if len(all_vals) < 20:
        return {("__global__",): ROLLING_FALLBACK}

    global_rate = sum(all_vals) / len(all_vals)
    rates = {("__global__",): global_rate}
    for key, vals in slices.items():
        if len(vals) >= ROLLING_MIN_SLICE_SAMPLES:
            rates[key] = sum(vals) / len(vals)
        else:
            rates[key] = global_rate

    return rates


def _load_near_term_adaptive_rates(
    as_of_date: str,
    trailing_days: int = NEAR_TERM_ADAPTIVE_WINDOW_DAYS,
) -> dict:
    """Compute adaptive on-time rates for near-term (0-30d) catalysts.

    Groups resolved near-term outcomes by the same decision tree used in the
    rule logic: REGULATORY → HARD → UNKNOWN → SOFT.  Falls back to constants
    if any slice has fewer than NEAR_TERM_MIN_SLICE_SAMPLES outcomes.

    Includes concentration diagnostics (distinct tickers, top-ticker share,
    event-weighted rates) and shrinks toward fallback constants when effective
    sample size is low (high ticker concentration).

    Returns dict with per-slice rates, counts, concentration metrics,
    and a fallback flag.
    """
    from collections import Counter, defaultdict

    _FALLBACK_CONSTANTS = {
        "regulatory": NEAR_TERM_REGULATORY_PROB,
        "hard": NEAR_TERM_HARD_PROB,
        "unknown": NEAR_TERM_UNKNOWN_PROB,
        "soft": NEAR_TERM_SOFT_PROB,
    }
    fallback_result = {
        **{k: None for k in _FALLBACK_CONSTANTS},
        **{f"n_{k}": 0 for k in _FALLBACK_CONSTANTS},
        **{f"n_tickers_{k}": 0 for k in _FALLBACK_CONSTANTS},
        **{f"top_ticker_share_{k}": 0.0 for k in _FALLBACK_CONSTANTS},
        **{f"event_weighted_{k}": None for k in _FALLBACK_CONSTANTS},
        "fallback": True,
    }
    if not CALIBRATION_LEDGER.exists():
        return fallback_result

    try:
        cutoff = date.fromisoformat(as_of_date[:10])
        window_start = cutoff - timedelta(days=trailing_days)
    except (ValueError, TypeError):
        return fallback_result

    window_start_str = str(window_start)
    cutoff_str = as_of_date[:10]

    # Each bucket entry: (on_time, ticker)
    buckets: dict[str, list[tuple[float, str]]] = {
        "regulatory": [],
        "hard": [],
        "unknown": [],
        "soft": [],
    }

    with open(CALIBRATION_LEDGER, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            outcome = entry.get("actual_outcome")
            pred_date = entry.get("prediction_date", "")
            if not outcome or pred_date >= cutoff_str or pred_date < window_start_str:
                continue
            cat_days = entry.get("catalyst_days", 999)
            if cat_days > NEAR_TERM_DAYS:
                continue

            on_time = 1.0 if outcome == "ON_TIME" else 0.0
            ticker = entry.get("ticker", "?")
            family = entry.get("catalyst_family", entry.get("family_bucket", ""))
            is_hard = entry.get("is_hard_catalyst", False)

            if family == "REGULATORY":
                buckets["regulatory"].append((on_time, ticker))
            elif is_hard:
                buckets["hard"].append((on_time, ticker))
            elif family in ("", "UNKNOWN"):
                buckets["unknown"].append((on_time, ticker))
            else:
                buckets["soft"].append((on_time, ticker))

    min_n = NEAR_TERM_MIN_SLICE_SAMPLES
    insufficient = any(len(v) < min_n for v in buckets.values())

    result: dict = {"fallback": insufficient}
    for key, entries in buckets.items():
        n = len(entries)
        result[f"n_{key}"] = n

        if n < min_n:
            result[key] = None
            result[f"n_tickers_{key}"] = 0
            result[f"top_ticker_share_{key}"] = 0.0
            result[f"event_weighted_{key}"] = None
            continue

        # Raw prediction-weighted rate
        raw_rate = sum(ot for ot, _ in entries) / n

        # Concentration diagnostics
        ticker_counts = Counter(t for _, t in entries)
        n_tickers = len(ticker_counts)
        top_ticker, top_count = ticker_counts.most_common(1)[0]
        top_share = top_count / n

        # Event-weighted rate: one vote per distinct ticker (majority outcome)
        ticker_outcomes: dict[str, list[float]] = defaultdict(list)
        for ot, t in entries:
            ticker_outcomes[t].append(ot)
        ticker_votes = [1.0 if sum(v) > len(v) / 2 else 0.0 for v in ticker_outcomes.values()]
        event_weighted_rate = sum(ticker_votes) / len(ticker_votes)

        # Shrinkage: blend toward fallback constant based on effective sample size.
        # effective_n = n_tickers (not n_predictions). When a few tickers dominate,
        # effective_n is small and we lean more on the prior (fallback constant).
        # alpha = effective_n / (effective_n + prior_weight)
        # prior_weight=10 means ~10 distinct tickers needed for 50/50 blend.
        prior_weight = 10.0
        alpha = n_tickers / (n_tickers + prior_weight)
        shrunk_rate = alpha * raw_rate + (1.0 - alpha) * _FALLBACK_CONSTANTS[key]

        result[key] = shrunk_rate
        result[f"raw_{key}"] = round(raw_rate, 4)
        result[f"n_tickers_{key}"] = n_tickers
        result[f"top_ticker_share_{key}"] = round(top_share, 3)
        result[f"event_weighted_{key}"] = round(event_weighted_rate, 3)
        result[f"shrinkage_alpha_{key}"] = round(alpha, 3)

    return result


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
    *,
    catalyst_family="",
    catalyst_days=None,
    precision="UNKNOWN",
    date_confidence=0.5,
    source="",
    n_revisions=0,
    last_revision_pushout=False,
    source_action="ALLOW",
):
    """Flag positions that need operator attention (Spec 058 enhanced).

    Returns (has_warning, list_of_warning_dicts) where each dict has:
      - label: structured warning label
      - reason: plain-text explanation
      - drivers: top 1-2 features contributing
      - severity: HIGH / MEDIUM / INFO
      - context_bucket: family_hardness_horizon (e.g. REGULATORY_HARD_NEAR)
    """
    # Classify context for suppression rules
    family_bucket = classify_family_bucket(catalyst_family)
    horizon_bucket = classify_horizon_bucket(catalyst_days) if catalyst_days is not None else "FAR"
    hardness = "HARD" if is_hard else "SOFT"
    context_bucket = f"{family_bucket}_{hardness}_{horizon_bucket}"

    # Regulatory + hard + near-term = effectively deterministic
    is_regulatory_deterministic = family_bucket == "REGULATORY" and hardness == "HARD" and horizon_bucket == "NEAR"

    warnings = []

    # REGULATORY_DETERMINISTIC — positive signal: no timing concern
    if is_regulatory_deterministic:
        warnings.append(
            {
                "label": "REGULATORY_DETERMINISTIC",
                "reason": f"Regulatory hard catalyst ({catalyst_days}d) — date is effectively fixed",
                "drivers": ["is_regulatory", "is_hard_catalyst"],
                "severity": "INFO",
                "context_bucket": context_bucket,
            }
        )
        # Return early — suppress all other warnings for deterministic dates
        return False, warnings

    # SHORT_DATED_REVISION_RISK — near-term + recent pushout
    if catalyst_days is not None and catalyst_days <= 30 and last_revision_pushout:
        # Elevate to HIGH if clinical + soft + near (highest slip risk)
        sev = "HIGH" if (family_bucket == "CLINICAL" and hardness == "SOFT") else "MEDIUM"
        warnings.append(
            {
                "label": "SHORT_DATED_REVISION_RISK",
                "reason": f"Near-term catalyst ({catalyst_days}d) with recent date pushout",
                "drivers": ["last_revision_pushout", "days_to_expected_near"],
                "severity": sev,
                "context_bucket": context_bucket,
            }
        )

    # LOW_CONFIDENCE_DATE — vague precision or low model confidence
    # Suppressed for regulatory hard catalysts (already returned above)
    low_precision = precision in ("MONTH", "QUARTER", "HALF_YEAR", "YEAR", "UNKNOWN")
    low_model_conf = logistic_prob is not None and logistic_prob < 0.50
    if low_precision or date_confidence < 0.50 or low_model_conf:
        drivers = []
        parts = []
        if low_precision:
            drivers.append("precision_month_or_worse")
            parts.append(f"precision={precision}")
        if date_confidence < 0.50:
            drivers.append("date_confidence")
            parts.append(f"confidence={date_confidence:.2f}")
        if low_model_conf:
            drivers.append("logistic_prob")
            parts.append(f"model_prob={logistic_prob:.2f}")
        warnings.append(
            {
                "label": "LOW_CONFIDENCE_DATE",
                "reason": f"Low date confidence: {', '.join(parts)}",
                "drivers": drivers[:2],
                "severity": "HIGH" if (horizon_bucket == "NEAR" and hardness == "SOFT") else "MEDIUM",
                "context_bucket": context_bucket,
            }
        )

    # STALE_EVENT_RECORD — no recent AACT/CTgov update
    if last_update_age is not None and last_update_age > 120:
        # Downgrade to INFO for hard catalysts (date is source-confirmed)
        sev = "INFO" if hardness == "HARD" else "MEDIUM"
        warnings.append(
            {
                "label": "STALE_EVENT_RECORD",
                "reason": f"Last AACT/CTgov update {last_update_age}d ago (>120d threshold)",
                "drivers": ["last_update_age"],
                "severity": sev,
                "context_bucket": context_bucket,
            }
        )

    # FAMILY_MISSING — empty or NO_CATALYST after all carry steps
    if not catalyst_family or catalyst_family == "NO_CATALYST":
        warnings.append(
            {
                "label": "FAMILY_MISSING",
                "reason": "No catalyst family assigned — timing bucket unknown",
                "drivers": ["catalyst_family"],
                "severity": "HIGH",
                "context_bucket": context_bucket,
            }
        )

    # SOURCE_UNRELIABLE — source reliability policy flags this source
    if source_action in ("DEMOTE", "SUPPRESS"):
        warnings.append(
            {
                "label": "SOURCE_UNRELIABLE",
                "reason": f"Source '{source}' has reliability action={source_action}",
                "drivers": ["source_reliability"],
                "severity": "HIGH" if source_action == "SUPPRESS" else "MEDIUM",
                "context_bucket": context_bucket,
            }
        )

    # PCD_DELAYED / STATUS_DOWNGRADE from AACT deltas
    if aact_delta:
        n_delayed = aact_delta.get("n_pcd_delayed", 0)
        n_downgrades = aact_delta.get("n_status_downgrades", 0)
        if n_delayed > 0:
            warnings.append(
                {
                    "label": "PCD_DELAYED",
                    "reason": f"{n_delayed} trial(s) with PCD delayed in latest AACT delta",
                    "drivers": ["pcd_delayed"],
                    "severity": "HIGH" if horizon_bucket == "NEAR" else "MEDIUM",
                    "context_bucket": context_bucket,
                }
            )
        if n_downgrades > 0:
            warnings.append(
                {
                    "label": "STATUS_DOWNGRADE",
                    "reason": f"{n_downgrades} trial status downgrade(s) in latest AACT delta",
                    "drivers": ["status_downgrade"],
                    "severity": "HIGH",
                    "context_bucket": context_bucket,
                }
            )

    # Sort by severity: HIGH first, then MEDIUM, then INFO
    _SEV_ORDER = {"HIGH": 0, "MEDIUM": 1, "INFO": 2}
    warnings.sort(key=lambda w: _SEV_ORDER.get(w.get("severity", "MEDIUM"), 1))

    return bool(warnings), warnings


# ---------------------------------------------------------------------------
# Hygiene + calibration status helpers
# ---------------------------------------------------------------------------


def _hygiene_check_family(catalysts: list) -> dict:
    """Check catalyst_family coverage across the snapshot."""
    from collections import Counter

    n_total = len(catalysts)
    family_counts = Counter(c.get("family_bucket", "UNKNOWN") for c in catalysts)
    n_missing = family_counts.get("UNKNOWN", 0)
    if n_total > 0 and n_missing / n_total > 0.10:
        log.warning(
            "Family hygiene: %d/%d (%.0f%%) catalysts have UNKNOWN family",
            n_missing,
            n_total,
            100 * n_missing / n_total,
        )
    return {
        "n_total": n_total,
        "n_missing": n_missing,
        "missing_pct": round(100 * n_missing / n_total, 1) if n_total > 0 else 0,
        "n_by_family": dict(family_counts),
    }


def _compute_calibration_status() -> str:
    """Determine calibration status from resolved outcomes in the ledger."""
    if not CALIBRATION_LEDGER.exists():
        return "EXPERIMENTAL"
    n_resolved = 0
    with open(CALIBRATION_LEDGER, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("actual_outcome") is not None:
                    n_resolved += 1
            except (json.JSONDecodeError, AttributeError):
                pass
    if n_resolved < 50:
        return "EXPERIMENTAL"
    if n_resolved < 200:
        return "UNDER_CALIBRATION"
    return "CALIBRATED"


CALIBRATION_CYCLE_LOG = OUTPUT_DIR / "calibration_cycle_log.jsonl"


def emit_calibration_cycle_summary(result: dict, as_of_date: str):
    """Write one-line cycle summary to calibration_cycle_log.jsonl.

    Tracks calibration health over time without parsing the full ledger.
    """
    from collections import Counter

    catalysts = result.get("catalysts", [])
    family_dist = dict(Counter(c.get("family_bucket", "UNKNOWN") for c in catalysts))
    horizon_dist = dict(Counter(c.get("horizon_bucket", "FAR") for c in catalysts))

    # Trailing resolved count + Brier by family from calibration_by_slice
    brier_by_family = {}
    brier_by_horizon = {}
    n_resolved_trailing = 0
    slice_path = CALIBRATION_BY_SLICE
    if slice_path.exists():
        try:
            slices = json.loads(slice_path.read_text())
            n_resolved_trailing = slices.get("n_resolved", 0)
            for s in slices.get("slices", []):
                fam = s.get("family", "ALL")
                hor = s.get("horizon", "ALL")
                brier = s.get("brier")
                if fam != "ALL" and hor == "ALL" and brier is not None:
                    brier_by_family[fam] = round(brier, 4)
                if hor != "ALL" and fam == "ALL" and brier is not None:
                    brier_by_horizon[hor] = round(brier, 4)
        except (json.JSONDecodeError, OSError):
            pass

    entry = {
        "cycle_date": as_of_date,
        "n_predictions": len(catalysts),
        "family_dist": family_dist,
        "horizon_dist": horizon_dist,
        "n_resolved_trailing": n_resolved_trailing,
        "rolling_base_rate": result.get("rolling_base_rate"),
        "calibration_status": result.get("calibration_status", "UNKNOWN"),
        "brier_by_family": brier_by_family,
        "brier_by_horizon": brier_by_horizon,
    }

    # Dedup guard
    if CALIBRATION_CYCLE_LOG.exists():
        with open(CALIBRATION_CYCLE_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    if json.loads(line.strip()).get("cycle_date") == as_of_date:
                        return
                except (json.JSONDecodeError, AttributeError):
                    pass

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CALIBRATION_CYCLE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    log.info(
        "Calibration cycle log: %s (%d predictions, %d resolved trailing)",
        as_of_date,
        len(catalysts),
        n_resolved_trailing,
    )


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
    rolling_base, prior_base, base_rate_trend = _load_rolling_base_rate_with_trend(snapshot_date)
    # Sliced rolling rates (v3): Brier 0.109, ECE 0.030 on 1691 OOS records
    rolling_sliced = _load_rolling_base_rate_sliced(snapshot_date)

    # Adaptive near-term rates from rolling window
    near_term_adaptive = _load_near_term_adaptive_rates(snapshot_date)
    use_adaptive = not near_term_adaptive["fallback"]
    if use_adaptive:
        for _k in ("regulatory", "hard", "soft", "unknown"):
            log.info(
                "  %s: %.3f (raw=%.3f, α=%.2f, n=%d pred, %d tickers, top=%.0f%%)",
                _k,
                near_term_adaptive[_k],
                near_term_adaptive.get(f"raw_{_k}", 0),
                near_term_adaptive.get(f"shrinkage_alpha_{_k}", 0),
                near_term_adaptive[f"n_{_k}"],
                near_term_adaptive.get(f"n_tickers_{_k}", 0),
                near_term_adaptive.get(f"top_ticker_share_{_k}", 0) * 100,
            )
    else:
        log.info("Near-term rates: using fallback constants (insufficient adaptive data)")

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
        source = row.get("catalyst_source", "")

        # Timing bucket classification (Spec 058)
        horizon_bucket = classify_horizon_bucket(catalyst_days)
        hardness = classify_hardness(is_hard, source)
        event_type = row.get("catalyst_event_type", "")
        family_bucket = classify_family_bucket(catalyst_family, event_type)

        if catalyst_days <= NEAR_TERM_DAYS:
            # Near-term: adaptive from rolling window, fallback to constants
            if catalyst_family == "REGULATORY":
                on_time_prob = near_term_adaptive["regulatory"] if use_adaptive else NEAR_TERM_REGULATORY_PROB
            elif is_hard:
                on_time_prob = near_term_adaptive["hard"] if use_adaptive else NEAR_TERM_HARD_PROB
            elif catalyst_family in ("", "UNKNOWN"):
                on_time_prob = near_term_adaptive["unknown"] if use_adaptive else NEAR_TERM_UNKNOWN_PROB
            else:
                on_time_prob = near_term_adaptive["soft"] if use_adaptive else NEAR_TERM_SOFT_PROB
            on_time_prob = max(on_time_prob, 0.05)  # floor
            prob_method = "near_term_adaptive" if use_adaptive else "near_term_rule_fallback"
        else:
            # Medium/far: sliced rolling base rate (v3, family × horizon)
            slice_key = (family_bucket, horizon_bucket)
            sliced_rate = rolling_sliced.get(slice_key)
            if sliced_rate is not None:
                on_time_prob = max(sliced_rate, 0.05)  # floor: no catalyst is truly 0%
                prob_method = "rolling_base_rate_sliced"
            else:
                on_time_prob = rolling_sliced.get(("__global__",), rolling_base)
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
            catalyst_family=catalyst_family,
            catalyst_days=catalyst_days,
            precision=row.get("clinical_days_precision", "UNKNOWN"),
            date_confidence=_sf(row.get("clinical_date_confidence"), 0.5),
            source=source,
            n_revisions=int(estimate.features_used.get("n_revisions", 0)),
            last_revision_pushout=estimate.features_used.get("last_revision_pushout", 0) > 0,
            source_action=row.get("source_reliability_action", "ALLOW"),
        )

        results.append(
            {
                "ticker": ticker,
                "rank": int(rank),
                "catalyst_days": int(catalyst_days),
                "catalyst_event_type": row.get("catalyst_event_type", ""),
                "catalyst_family": row.get("catalyst_family", ""),
                "catalyst_source": source,
                "is_hard_catalyst": is_hard,
                # Timing buckets (Spec 058)
                "family_bucket": family_bucket,
                "horizon_bucket": horizon_bucket,
                "hardness": hardness,
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

    # Family hygiene check
    family_hygiene = _hygiene_check_family(results)

    # Calibration status from ledger
    calibration_status = _compute_calibration_status()

    # Warning severity summary
    n_high_sev = sum(
        1
        for r in results
        if r["execution_warning_flag"]
        for w in r.get("warning_reasons", [])
        if w.get("severity") == "HIGH"
    )

    return {
        "schema": "timing_hazard_overlay.v3",
        "snapshot_date": snapshot_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probability_method": "hybrid_v2.1",
        "rolling_base_rate": round(rolling_base, 3),
        "prior_base_rate": round(prior_base, 3) if prior_base is not None else None,
        "base_rate_trend": base_rate_trend,
        "calibration_status": calibration_status,
        "n_catalysts": len(results),
        "n_warnings": n_warnings,
        "n_warnings_high": n_high_sev,
        "confidence_dist": {
            "HIGH": n_high,
            "MEDIUM": n_medium,
            "LOW": n_low,
            "STALE": n_stale,
        },
        "family_hygiene": family_hygiene,
        "mean_on_time_prob": (round(sum(r["on_time_prob"] for r in results) / len(results), 3) if results else None),
        "catalysts": results,
    }


def append_calibration_ledger(result: dict):
    """Append timing predictions to calibration ledger for future outcome tracking.

    Each entry records the prediction at the time it was made. When the catalyst
    resolves, a separate process will match predictions to outcomes for Brier scoring.

    Dedup guard: skips append if any entry for this prediction_date already exists.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snap_date = result.get("snapshot_date", "")

    # Dedup: check if this prediction_date is already in the ledger
    if CALIBRATION_LEDGER.exists():
        with open(CALIBRATION_LEDGER, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    if json.loads(line).get("prediction_date") == snap_date:
                        return  # already recorded
                except json.JSONDecodeError:
                    continue

    with open(CALIBRATION_LEDGER, "a") as f:
        for cat in result.get("catalysts", []):
            entry = {
                "prediction_date": snap_date,
                "ticker": cat["ticker"],
                "catalyst_days": cat["catalyst_days"],
                "catalyst_event_type": cat["catalyst_event_type"],
                "catalyst_family": cat["catalyst_family"],
                "is_hard_catalyst": cat["is_hard_catalyst"],
                # Timing buckets (Spec 058)
                "family_bucket": cat.get("family_bucket", "UNKNOWN"),
                "horizon_bucket": cat.get("horizon_bucket", "UNKNOWN"),
                "hardness": cat.get("hardness", "UNKNOWN"),
                "source_provenance": cat.get("catalyst_source", ""),
                # Probabilities
                "on_time_prob": cat["on_time_prob"],
                "on_time_prob_logistic": cat.get("on_time_prob_logistic"),
                "probability_method": result.get("probability_method", "rolling_base_rate_90d"),
                "slip_prob_30d": cat["slip_prob_30d"],
                "slip_prob_60d_plus": cat["slip_prob_60d_plus"],
                "timing_confidence_bucket": cat["timing_confidence_bucket"],
                "execution_warning_flag": cat["execution_warning_flag"],
                "warning_labels": [w["label"] for w in cat.get("warning_reasons", [])],
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

    # Calibration-by-slice (Spec 058)
    cal_slices = compute_calibration_by_slice(snap)
    if cal_slices["n_resolved"] > 0:
        CALIBRATION_BY_SLICE.write_text(json.dumps(cal_slices, indent=2, default=str))
        print(f"  Calibration by slice: {cal_slices['n_resolved']} resolved, {len(cal_slices['slices'])} slices")
    else:
        print("  Calibration by slice: no resolved outcomes yet")

    # Calibration dashboard (extended views with curves + source breakdown)
    cal_dashboard = build_calibration_dashboard(snap)
    cal_dash_path = OUTPUT_DIR / "calibration_dashboard.json"
    if cal_dashboard["n_resolved"] > 0:
        cal_dash_path.write_text(json.dumps(cal_dashboard, indent=2, default=str))
        print(
            f"  Calibration dashboard: {cal_dashboard['n_resolved']} resolved, "
            f"{len(cal_dashboard['horizons'])} horizons, {len(cal_dashboard['sources'])} sources"
        )
    else:
        print("  Calibration dashboard: no resolved outcomes yet")

    print(f"TIMING HAZARD OVERLAY — {snap}")
    print(f"  Catalysts: {result['n_catalysts']}")
    print(f"  Warnings: {result['n_warnings']}")
    print(f"  Confidence: {result['confidence_dist']}")
    print(f"  Mean P(on_time): {result['mean_on_time_prob']}")
    if result.get("base_rate_trend") is not None:
        trend_str = (
            f"+{result['base_rate_trend']:.3f}"
            if result["base_rate_trend"] >= 0
            else f"{result['base_rate_trend']:.3f}"
        )
        print(
            f"  Base rate trend: {trend_str} (current={result['rolling_base_rate']:.3f}, prior={result['prior_base_rate']:.3f})"
        )

    # Print warnings first, then all
    for cat in result["catalysts"]:
        if cat["execution_warning_flag"]:
            reasons = ", ".join(w["label"] for w in cat["warning_reasons"])
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
