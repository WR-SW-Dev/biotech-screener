"""Options surface signal computations for hard-catalyst queue overlay (Spec 020).

Computes actual_implied_move_pctile and atm_iv_change_5d from historical
IV features, then derives surface_move_extreme and iv_ramp_flag for
queue priority boosting.
"""

from __future__ import annotations

import csv
import logging
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum historical rows required for signal computation
MIN_HISTORY_ROWS = 30

# Trailing window for percentile computation
LOOKBACK_ROWS = 252

# IV change window (trading days)
IV_CHANGE_WINDOW = 5

# Thresholds
MOVE_EXTREME_HIGH = 0.80
MOVE_EXTREME_MED = 0.60
IV_RAMP_THRESHOLD = 0.05
IV_RAMP_STRONG = 0.10


def load_historical_iv_feature_history(
    path: Path,
) -> Dict[str, List[Dict[str, Any]]]:
    """Load historical_iv_features.csv → {ticker: [sorted rows by date]}.

    Each row has: date, atm_iv, actual_implied_move, rr_25d, etc.
    """
    index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip().upper()
            dt = (row.get("date") or "").strip()
            if not ticker or not dt:
                continue
            index[ticker].append(
                {
                    "date": dt,
                    "atm_iv": _sf(row.get("atm_iv")),
                    "actual_implied_move": _sf(row.get("actual_implied_move")),
                    "rr_25d": _sf(row.get("rr_25d")),
                }
            )

    # Sort each ticker's history by date
    for ticker in index:
        index[ticker].sort(key=lambda r: r["date"])

    logger.info(
        "Loaded IV history: %d tickers, %d total rows",
        len(index),
        sum(len(v) for v in index.values()),
    )
    return dict(index)


def _sf(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def compute_atm_iv_change_5d(
    current_atm_iv: float,
    hist_rows: List[Dict[str, Any]],
    current_date: str,
    min_history_rows: int = MIN_HISTORY_ROWS,
    n: int = IV_CHANGE_WINDOW,
) -> Optional[float]:
    """Compute ATM IV change over n trading observations.

    Returns current_atm_iv - atm_iv[n observations back], or None.
    """
    if math.isnan(current_atm_iv):
        return None

    # Get rows strictly before current date
    prior = [r for r in hist_rows if r["date"] < current_date and not math.isnan(r["atm_iv"])]
    if len(prior) < max(n, min_history_rows):
        return None

    lag_row = prior[-n]
    lag_iv = lag_row["atm_iv"]
    if math.isnan(lag_iv):
        return None

    return current_atm_iv - lag_iv


def compute_actual_implied_move_pctile(
    current_move: float,
    hist_rows: List[Dict[str, Any]],
    current_date: str,
    lookback_rows: int = LOOKBACK_ROWS,
    min_history_rows: int = MIN_HISTORY_ROWS,
) -> Optional[float]:
    """Compute percentile of current actual implied move vs trailing history.

    Returns value in [0.0, 1.0], or None if insufficient data.
    PIT-safe: excludes current row.
    """
    if math.isnan(current_move):
        return None

    prior = [r for r in hist_rows if r["date"] < current_date]
    prior = prior[-lookback_rows:]  # trailing window
    vals = [r["actual_implied_move"] for r in prior if not math.isnan(r["actual_implied_move"])]

    if len(vals) < min_history_rows:
        return None

    rank = sum(1 for v in vals if v <= current_move)
    pctile = rank / len(vals)
    return max(0.0, min(1.0, pctile))


def derive_surface_move_extreme(pctile: Optional[float]) -> str:
    """Classify actual_implied_move_pctile into high/med/low."""
    if pctile is None:
        return ""
    if pctile >= MOVE_EXTREME_HIGH:
        return "high"
    if pctile >= MOVE_EXTREME_MED:
        return "med"
    return "low"


def derive_iv_ramp_flag(change: Optional[float]) -> str:
    """Classify atm_iv_change_5d into rising/flat/falling."""
    if change is None:
        return ""
    if change >= IV_RAMP_THRESHOLD:
        return "rising"
    if change <= -IV_RAMP_THRESHOLD:
        return "falling"
    return "flat"


def derive_post_event_drift_risk(
    pctile: Optional[float],
    iv_change: Optional[float],
) -> str:
    """Combined post-event giveback risk flag."""
    if pctile is None and iv_change is None:
        return ""
    high_move = pctile is not None and pctile >= MOVE_EXTREME_HIGH
    strong_ramp = iv_change is not None and iv_change >= IV_RAMP_STRONG
    med_move = pctile is not None and pctile >= MOVE_EXTREME_MED
    mild_ramp = iv_change is not None and iv_change >= IV_RAMP_THRESHOLD
    if high_move or strong_ramp:
        return "high"
    if med_move or mild_ramp:
        return "med"
    return "low"


def compute_rr_25d_trend_7d(
    current_rr: float,
    hist_rows: List[Dict[str, Any]],
    current_date: str,
    n: int = 7,
    min_history_rows: int = MIN_HISTORY_ROWS,
) -> Optional[float]:
    """Compute 7-trading-day change in rr_25d."""
    if math.isnan(current_rr):
        return None
    prior = [r for r in hist_rows if r["date"] < current_date and not math.isnan(r.get("rr_25d", float("nan")))]
    if len(prior) < max(n, min_history_rows):
        return None
    lag_rr = prior[-n].get("rr_25d", float("nan"))
    if math.isnan(lag_rr):
        return None
    return current_rr - lag_rr


def derive_rr_trend_flag(trend: Optional[float]) -> str:
    """Classify rr_25d_trend_7d into bullish/flat/bearish."""
    if trend is None:
        return ""
    if trend >= 0.03:
        return "bullish"
    if trend <= -0.03:
        return "bearish"
    return "flat"


def compute_surface_signal_quality(
    pctile: Optional[float],
    iv_change: Optional[float],
    has_current_surface: bool,
    n_hist: int,
) -> str:
    """Determine signal quality tier."""
    if not has_current_surface:
        return "missing_current_surface"
    if n_hist < MIN_HISTORY_ROWS:
        return "insufficient_history"
    if pctile is not None and iv_change is not None:
        return "ok"
    if pctile is not None or iv_change is not None:
        return "partial"
    return "insufficient_history"


def enrich_row_with_surface_signals(
    row: dict,
    hist_rows: List[Dict[str, Any]],
    current_date: str,
) -> dict:
    """Add surface signal fields to a row dict (in-place).

    Reads opt_atm_iv and actual implied move from the row,
    computes derived signals against hist_rows.
    """
    current_iv = _sf(row.get("opt_atm_iv"))
    current_move = _sf(row.get("implied_event_move"))  # actual implied move from chain analytics
    if math.isnan(current_move):
        current_move = _sf(row.get("actual_implied_move"))

    has_surface = not math.isnan(current_iv) or not math.isnan(current_move)
    n_hist = len([r for r in hist_rows if r["date"] < current_date])

    iv_change = compute_atm_iv_change_5d(current_iv, hist_rows, current_date)
    pctile = compute_actual_implied_move_pctile(current_move, hist_rows, current_date)

    row["actual_implied_move_pctile"] = f"{pctile:.4f}" if pctile is not None else ""
    row["surface_move_extreme"] = derive_surface_move_extreme(pctile)
    row["atm_iv_change_5d"] = f"{iv_change:.6f}" if iv_change is not None else ""
    row["iv_ramp_flag"] = derive_iv_ramp_flag(iv_change)
    row["post_event_drift_risk"] = derive_post_event_drift_risk(pctile, iv_change)

    # RR trend (7-trading-day change in rr_25d from historical features)
    current_rr = _sf(row.get("opt_rr_25d"))
    rr_trend = compute_rr_25d_trend_7d(current_rr, hist_rows, current_date)
    row["rr_25d_trend_7d"] = f"{rr_trend:.6f}" if rr_trend is not None else ""
    row["rr_trend_flag"] = derive_rr_trend_flag(rr_trend)

    row["surface_signal_quality"] = compute_surface_signal_quality(
        pctile,
        iv_change,
        has_surface,
        n_hist,
    )
    row["surface_validation_basis"] = "retro_hard_filter"

    return row
