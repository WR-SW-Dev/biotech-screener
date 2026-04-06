"""Implied-vs-Realized Move Calibration (Spec 059 Phase A).

Builds a calibration table from CRT × options join data:
for each (event_family, phase_bucket, outcome), what is the historical
ratio of realized absolute move to options-implied move?

This allows the payoff engine to adjust its static move priors using
the options market's current implied move for a specific catalyst.

Policy: OVERLAY-ONLY. This module does not touch the selector or ranker.
All outputs are gated on opt_liquidity_state == "liquid".
"""

from __future__ import annotations

import logging
import statistics
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Phase mapping (mirrors payoff_engine._phase_bucket)
_PHASE_MAP = {
    "3": "phase3",
    "4": "phase3",
    "2": "phase2",
    "2_3": "phase2",
    "1": "early",
    "1_2": "early",
}

# Event type to family mapping for CRT records that have catalyst_type but not event_family
_TYPE_TO_FAMILY = {
    "PDUFA_ACTION": "REGULATORY",
    "ADVISORY_COMMITTEE": "REGULATORY",
    "NDA_BLA_FILING": "REGULATORY",
    "REGULATORY_DESIGNATION": "REGULATORY",
    "pdufa": "REGULATORY",
    "fda_pdufa_date": "REGULATORY",
    "fda_decision": "REGULATORY",
    "fda_approval": "REGULATORY",
    "advisory_committee": "REGULATORY",
    "fda_adcom": "REGULATORY",
    "regulatory_decision": "REGULATORY",
    "approval_decision": "REGULATORY",
    "DATA_READOUT": "CLINICAL",
    "PHASE_3_READOUT": "CLINICAL",
    "PHASE_2_READOUT": "CLINICAL",
    "INTERIM_ANALYSIS": "CLINICAL",
    "data_readout": "CLINICAL",
    "clinical_data": "CLINICAL",
}


def _phase_bucket(phase: str) -> str:
    return _PHASE_MAP.get(phase, "phase2")


def _infer_family(rec: dict) -> str:
    """Infer event family from record fields."""
    if rec.get("event_family"):
        return rec["event_family"]
    ct = rec.get("catalyst_type", "")
    return _TYPE_TO_FAMILY.get(ct, "CLINICAL")


def build_calibration_table(
    crt_records: List[Dict[str, Any]],
    min_n: int = 5,
) -> Dict[str, Any]:
    """Build implied-vs-realized calibration table from CRT × options data.

    Args:
        crt_records: List of CRT-options join records. Each must have:
            - outcome: HIT/MISS/MIXED
            - opt_liquidity_state: liquid/thin/absent
            - implied_event_move: float (decimal, e.g. 0.15 = 15%)
            - realized_1d_return: float (decimal)
            - event_family or catalyst_type
            - phase
        min_n: Minimum observations for a bucket to be flagged as usable.

    Returns:
        {
            "buckets": {
                "FAMILY|phase_bucket|OUTCOME": {
                    "implied_p50": float,
                    "realized_abs_p50": float,
                    "realized_signed_p50": float,
                    "ratio": float,
                    "n": int,
                    "usable": bool,
                    "tickers": [str],
                }
            },
            "meta": {
                "n_total": int,
                "n_included": int,
                "n_excluded_liquidity": int,
                "n_excluded_missing_implied": int,
            }
        }
    """
    n_total = len(crt_records)
    n_excluded_liquidity = 0
    n_excluded_missing_implied = 0

    # Collect observations per bucket
    buckets_raw: Dict[str, List[Dict[str, Any]]] = {}

    for rec in crt_records:
        # Gate: liquid only
        if rec.get("opt_liquidity_state") != "liquid":
            n_excluded_liquidity += 1
            continue

        # Gate: must have implied move
        implied = rec.get("implied_event_move")
        if implied is None or (isinstance(implied, float) and (implied != implied)):  # NaN check
            n_excluded_missing_implied += 1
            continue
        implied = float(implied)
        if implied <= 0:
            n_excluded_missing_implied += 1
            continue

        # Gate: must have realized return
        realized = rec.get("realized_1d_return")
        if realized is None or (isinstance(realized, float) and (realized != realized)):
            continue
        realized = float(realized)

        outcome = rec.get("outcome", "")
        if outcome not in ("HIT", "MISS", "MIXED"):
            continue

        family = _infer_family(rec)
        phase = _phase_bucket(rec.get("phase", ""))
        key = f"{family}|{phase}|{outcome}"

        buckets_raw.setdefault(key, []).append(
            {
                "ticker": rec.get("ticker", ""),
                "implied": implied,
                "realized": realized,
                "realized_abs": abs(realized),
            }
        )

    # Compute statistics per bucket
    buckets: Dict[str, Dict[str, Any]] = {}
    for key, obs in buckets_raw.items():
        n = len(obs)
        implied_values = [o["implied"] for o in obs]
        realized_abs_values = [o["realized_abs"] for o in obs]
        realized_signed_values = [o["realized"] for o in obs]
        tickers = [o["ticker"] for o in obs]

        implied_p50 = statistics.median(implied_values)
        realized_abs_p50 = statistics.median(realized_abs_values)
        realized_signed_p50 = statistics.median(realized_signed_values)

        ratio = realized_abs_p50 / implied_p50 if implied_p50 > 0 else 1.0

        buckets[key] = {
            "implied_p50": round(implied_p50, 4),
            "realized_abs_p50": round(realized_abs_p50, 4),
            "realized_signed_p50": round(realized_signed_p50, 4),
            "ratio": round(ratio, 4),
            "n": n,
            "usable": n >= min_n,
            "tickers": tickers,
        }

    n_included = sum(b["n"] for b in buckets.values())

    return {
        "buckets": buckets,
        "meta": {
            "n_total": n_total,
            "n_included": n_included,
            "n_excluded_liquidity": n_excluded_liquidity,
            "n_excluded_missing_implied": n_excluded_missing_implied,
            "min_n": min_n,
        },
    }


class CalibrationLookup:
    """Provides calibration adjustments for the payoff engine.

    Usage:
        lookup = CalibrationLookup(calibration_table)
        adj = lookup.get_adjustment("REGULATORY", "phase3", "HIT")
        if adj:
            adjusted_move = implied_move * adj["ratio"]
    """

    def __init__(self, table: Dict[str, Any]) -> None:
        self._buckets = table.get("buckets", {})

    def get_adjustment(
        self,
        family: str,
        phase_bucket: str,
        outcome: str,
    ) -> Optional[Dict[str, Any]]:
        """Get calibration adjustment for a bucket.

        Returns None if the bucket doesn't exist or isn't usable.
        """
        key = f"{family}|{phase_bucket}|{outcome}"
        bucket = self._buckets.get(key)
        if bucket is None or not bucket.get("usable"):
            return None
        return bucket

    def has_usable_data(self, family: str, phase_bucket: str) -> bool:
        """Check if any outcome bucket is usable for this family/phase."""
        for outcome in ("HIT", "MISS", "MIXED"):
            key = f"{family}|{phase_bucket}|{outcome}"
            bucket = self._buckets.get(key)
            if bucket and bucket.get("usable"):
                return True
        return False


def compute_options_adjusted_move(
    static_move: float,
    implied_event_move: float,
    calibration_ratio: float,
    blend_weight: float = 0.5,
) -> float:
    """Blend static prior move with options-implied move.

    The options-implied move is scaled by the calibration ratio
    (how much realized moves historically exceed/trail implied moves),
    then blended with the static prior.

    Args:
        static_move: Move from static empirical priors (percentage points)
        implied_event_move: Options-implied move (decimal, e.g. 0.15)
        calibration_ratio: realized_abs / implied historical ratio
        blend_weight: Weight on options-adjusted estimate [0, 1].
            0 = pure static, 1 = pure options.

    Returns:
        Blended move estimate in percentage points.
    """
    # Convert implied move to percentage points and apply calibration
    options_move_pct = implied_event_move * 100.0 * calibration_ratio

    # Preserve sign from static prior (options implied is always positive)
    if static_move < 0:
        options_move_pct = -options_move_pct

    return static_move * (1.0 - blend_weight) + options_move_pct * blend_weight


def make_forward_log_entry(
    ticker: str,
    event_type: str,
    event_family: str,
    phase: str,
    implied_event_move: float,
    catalyst_days: int,
    opt_liquidity_state: str,
    snapshot_date: str,
) -> Dict[str, Any]:
    """Create a forward-logging entry for future calibration updates.

    Called during each production run to log the options-implied state
    for pending catalysts. When the catalyst resolves, this entry
    gets matched to realized returns to grow the calibration table.
    """
    return {
        "ticker": ticker,
        "event_type": event_type,
        "event_family": event_family,
        "phase": phase,
        "phase_bucket": _phase_bucket(phase),
        "implied_event_move": implied_event_move,
        "catalyst_days": catalyst_days,
        "opt_liquidity_state": opt_liquidity_state,
        "snapshot_date": snapshot_date,
        "status": "pending",
    }
