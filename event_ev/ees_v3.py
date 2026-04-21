"""EES v3 — Conditional Mispricing + Expected Move model.

Replaces the v2 trap/quality overlay with a two-factor model derived
from PIT-validated backtest (2020-2025, 72 monthly periods, 6,686 events):

  Factor 1: conditional_misprice_score (primary alpha)
    - IC +0.089, NW t=2.07, decile +6.9pp
    - Measures scenario-EV vs market-priced move
    - Requires priced_move_pct (from implied_event_move)

  Factor 2: conditional_expected_move (stability overlay)
    - IC +0.026, NW t=1.83, decile +4.2pp
    - Orthogonal to Factor 1 (|r| < 0.15)
    - Stable across halves (early +0.024, late +0.029)
    - Does NOT require priced_move_pct

Key corrections from v2:
  - base_rate_gap_score is ANTI-predictive (IC -0.090). Market is RIGHT
    to price above base rates for selected names. Removed from alpha.
  - trap_overlay_score is dead (IC ~0). base_rate and misprice cancel.
  - quality_overlay_score = -timing_decay only. Marginal at best.

Model:
  ees_v3_score = w_misprice * z(conditional_misprice_score)
               + w_expected * z(conditional_expected_move)

  Default: w_misprice=0.70, w_expected=0.30

Policy: DIAGNOSTIC OVERLAY until Checklist v2 validation passes.
        Does NOT affect ranking or selection yet.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EPS = 1e-6

# ═════════════════════════════════════════════════════════════════════════
# Config
# ═════════════════════════════════════════════════════════════════════════

DEFAULT_W_MISPRICE = 0.70
DEFAULT_W_EXPECTED = 0.30

# Gate: exclude bottom N% by v3 score
DEFAULT_V3_CUT_PCT = 20

# ═════════════════════════════════════════════════════════════════════════
# Data contract
# ═════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class EESV3Overlay:
    """EES v3 combined score for a single ticker.

    Policy: DIAGNOSTIC OVERLAY. Not in ranking or selection yet.
    """

    ticker: str
    as_of_date: str

    # Inputs (already computed by EES v2 + conditional model)
    conditional_misprice_z: float  # z-scored misprice
    conditional_expected_move_z: float  # z-scored expected move

    # Combined score
    ees_v3_score: float  # weighted combination
    ees_v3_gate: bool  # passes bottom-N% gate
    ees_v3_pctile: float  # percentile rank [0, 100]

    # Diagnostics
    misprice_available: bool  # True if conditional_misprice_score was non-NaN
    model_version: str = "ees_v3.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "as_of_date": self.as_of_date,
            "conditional_misprice_z": round(self.conditional_misprice_z, 4),
            "conditional_expected_move_z": round(self.conditional_expected_move_z, 4),
            "ees_v3_score": round(self.ees_v3_score, 4),
            "ees_v3_gate": self.ees_v3_gate,
            "ees_v3_pctile": round(self.ees_v3_pctile, 1),
            "misprice_available": self.misprice_available,
            "model_version": self.model_version,
        }


# ═════════════════════════════════════════════════════════════════════════
# Cross-sectional z-score
# ═════════════════════════════════════════════════════════════════════════


def _z_score_values(
    values: List[Optional[float]],
) -> List[float]:
    """Cross-sectional z-score. NaN/None → 0.0 (neutral)."""
    valid = [v for v in values if v is not None and not math.isnan(v)]
    if len(valid) < 3:
        return [0.0] * len(values)
    m = statistics.mean(valid)
    s = statistics.stdev(valid)
    if s < EPS:
        return [0.0] * len(values)
    result = []
    for v in values:
        if v is None or math.isnan(v):
            result.append(0.0)
        else:
            result.append((v - m) / s)
    return result


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


# ═════════════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════════════


def compute_v3_scores(
    csv_rows: List[Dict[str, Any]],
    as_of_date: str,
    w_misprice: float = DEFAULT_W_MISPRICE,
    w_expected: float = DEFAULT_W_EXPECTED,
    gate_cut_pct: int = DEFAULT_V3_CUT_PCT,
) -> List[EESV3Overlay]:
    """Compute EES v3 scores from pre-computed EES + conditional fields.

    Reads from csv_rows (already enriched by EES v2 + conditional model):
      - conditional_misprice_score (from EES v2)
      - conditional_expected_move (from conditional model)

    Returns one EESV3Overlay per row (same order).
    """
    n = len(csv_rows)

    # Extract raw signals
    misprice_raw: List[Optional[float]] = []
    expected_raw: List[Optional[float]] = []
    for row in csv_rows:
        misprice_raw.append(_safe_float(row.get("conditional_misprice_score")))
        expected_raw.append(_safe_float(row.get("conditional_expected_move")))

    # Cross-sectional z-score
    misprice_z = _z_score_values(misprice_raw)
    expected_z = _z_score_values(expected_raw)

    # Combined score
    scores: List[float] = []
    for i in range(n):
        s = w_misprice * misprice_z[i] + w_expected * expected_z[i]
        scores.append(s)

    # Gate: percentile-based bottom cut
    sorted_scores = sorted(scores)
    n_s = len(sorted_scores)
    if n_s >= 5:
        threshold = sorted_scores[min(int(n_s * gate_cut_pct / 100), n_s - 1)]
        # Degeneracy check
        mode_count = max(sorted_scores.count(v) for v in set(sorted_scores))
        degenerate = mode_count > n_s * 0.80
    else:
        threshold = -999.0
        degenerate = True

    results: List[EESV3Overlay] = []
    for i, row in enumerate(csv_rows):
        ticker = row.get("ticker", "")
        s = scores[i]

        # Percentile
        if degenerate:
            pctile = 50.0
            gate = True
        else:
            pctile = sum(1 for v in sorted_scores if v <= s) / n_s * 100
            gate = s > threshold

        results.append(
            EESV3Overlay(
                ticker=ticker,
                as_of_date=as_of_date,
                conditional_misprice_z=misprice_z[i],
                conditional_expected_move_z=expected_z[i],
                ees_v3_score=round(s, 4),
                ees_v3_gate=gate,
                ees_v3_pctile=pctile,
                misprice_available=misprice_raw[i] is not None,
            )
        )

    n_with_misprice = sum(1 for r in results if r.misprice_available)
    n_pass = sum(1 for r in results if r.ees_v3_gate)

    # Distribution diagnostics — detect saturation / compression
    mp_valid = [v for v in misprice_raw if v is not None]
    n_mp_at_ceil = sum(1 for v in mp_valid if abs(v) >= 0.99)
    n_mp_unique = len(set(round(v, 4) for v in mp_valid)) if mp_valid else 0

    logger.info(
        "[EES v3] Scored %d tickers: %d with misprice data (%.0f%%), %d pass gate (cut=%d%%)",
        n,
        n_with_misprice,
        n_with_misprice / n * 100 if n else 0,
        n_pass,
        gate_cut_pct,
    )
    if mp_valid:
        logger.info(
            "[EES v3] Distribution: misprice unique=%d, at_ceiling=%d (%.0f%%), v3 unique=%d",
            n_mp_unique,
            n_mp_at_ceil,
            n_mp_at_ceil / len(mp_valid) * 100,
            len(set(round(s, 4) for s in scores)),
        )
        if n_mp_at_ceil > len(mp_valid) * 0.20:
            logger.warning(
                "[EES v3] SATURATION: %.0f%% of misprice scores at ceiling — check priced_move_pct units",
                n_mp_at_ceil / len(mp_valid) * 100,
            )

    return results


# ═════════════════════════════════════════════════════════════════════════
# CSV enrichment (called from run_screen.py)
# ═════════════════════════════════════════════════════════════════════════

EES_V3_CSV_COLUMNS = [
    "ees_v3_score",
    "ees_v3_gate",
    "ees_v3_pctile",
    "conditional_misprice_z",
    "conditional_expected_move_z",
    "ees_v3_misprice_available",
]


def enrich_csv_rows(
    csv_rows: List[Dict[str, Any]],
    as_of_date: str,
    w_misprice: float = DEFAULT_W_MISPRICE,
    w_expected: float = DEFAULT_W_EXPECTED,
    gate_cut_pct: int = DEFAULT_V3_CUT_PCT,
) -> List[EESV3Overlay]:
    """Compute v3 scores and inject columns in-place.

    MUST be called AFTER both EES v2 and conditional model enrichment,
    since it reads their output columns.

    Returns the list of EESV3Overlay objects (for sidecar writing).
    """
    overlays = compute_v3_scores(csv_rows, as_of_date, w_misprice, w_expected, gate_cut_pct)

    for row, ov in zip(csv_rows, overlays):
        row["ees_v3_score"] = ov.ees_v3_score
        row["ees_v3_gate"] = ov.ees_v3_gate
        row["ees_v3_pctile"] = ov.ees_v3_pctile
        row["conditional_misprice_z"] = ov.conditional_misprice_z
        row["conditional_expected_move_z"] = ov.conditional_expected_move_z
        row["ees_v3_misprice_available"] = "1" if ov.misprice_available else "0"

    return overlays
