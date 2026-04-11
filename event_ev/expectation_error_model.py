"""Expectation Error Model — Jane Street 6-mistake framework.

Detects structured expectation errors in market pricing:
    1. Base-rate neglect: implied move vs historical realised distribution
    2. Mispriced conditionals: scenario-weighted EV vs implied move
    3. Thin-book slippage: execution friction penalty
    4. Platform divergence: option surface vs realised vol
    5. Favourite bias: crowding / short-interest distortion
    6. Time decay: expensive implied moves with uncertain timing

Policy: OVERLAY-ONLY. Diagnostic for operator review.
        Does NOT affect ranking or selection.

Inputs (all from rankings.csv — no new data dependencies):
    - priced_move_pct
    - short_interest_pct
    - market_cap_mm
    - close_price
    - catalyst_family
    - lead_program_phase
    - clinical_days_precision
    - implied_event_move (realised-vol proxy)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from .data_contracts import ExpectationErrorScore

logger = logging.getLogger(__name__)

EPS = 1e-6

# ── Sub-score weights for the composite EES ──────────────────────────────
_DEFAULT_WEIGHTS = {
    "base_rate_gap": 0.30,
    "conditional_misprice": 0.20,
    "divergence": 0.10,
    "crowding_bias": 0.15,
    "slippage_penalty": 0.15,  # subtracted
    "timing_decay_risk": 0.10,  # subtracted
}

# ── Historical base-rate move distributions (abs %, by family|phase) ─────
# Source: payoff_engine.py _DEFAULT_MOVE_PRIORS, blended HIT/MISS via
# outcome-model priors.  Keyed by "FAMILY|phase_bucket".
# p50 = median abs realised move, iqr = p75 - p25.
_BASE_RATE_TABLE: Dict[str, Dict[str, float]] = {
    "CLINICAL|phase3": {"p50": 35.0, "iqr": 37.0},  # HIT +20, MISS -50 → abs blend
    "CLINICAL|phase2": {"p50": 35.0, "iqr": 40.0},
    "CLINICAL|early": {"p50": 25.0, "iqr": 38.0},
    "REGULATORY|phase3": {"p50": 19.0, "iqr": 27.0},
    "REGULATORY|phase2": {"p50": 23.5, "iqr": 30.0},
    "REGULATORY|early": {"p50": 20.0, "iqr": 30.0},
    "SAFETY|any": {"p50": 20.0, "iqr": 35.0},
}

# ── Conditional scenario trees (family|phase → weighted expected abs move) ─
# Derived from payoff_engine priors × outcome-model Wong priors.
# expected_conditional_move = p_hit * |hit_p50| + p_miss * |miss_p50| + p_mixed * |mixed_p50|
_CONDITIONAL_MOVE_TABLE: Dict[str, float] = {
    "CLINICAL|phase3": 0.58 * 20.0 + 0.35 * 50.0 + 0.07 * 2.0,  # ≈29.2
    "CLINICAL|phase2": 0.31 * 30.0 + 0.58 * 40.0 + 0.11 * 2.0,  # ≈32.7
    "CLINICAL|early": 0.63 * 25.0 + 0.30 * 25.0 + 0.07 * 2.0,  # ≈23.4
    "REGULATORY|phase3": 0.58 * 8.0 + 0.35 * 30.0 + 0.07 * 0.0,  # ≈15.1
    "REGULATORY|phase2": 0.31 * 12.0 + 0.58 * 35.0 + 0.11 * 0.0,  # ≈24.0
    "REGULATORY|early": 0.63 * 15.0 + 0.30 * 25.0 + 0.07 * 0.0,  # ≈17.0
}

# ── Timing uncertainty factors ───────────────────────────────────────────
_TIMING_UNCERTAINTY: Dict[str, float] = {
    "DAY": 0.0,
    "WEEK": 0.25,
    "MONTH": 0.60,
    "QUARTER": 1.0,
    "HALF_YEAR": 1.0,
    "YEAR": 1.0,
    "UNKNOWN": 1.0,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_float(v: Any) -> Optional[float]:
    """Safe float extraction from CSV row values."""
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _phase_bucket(phase_str: str) -> str:
    """Map lead_program_phase to coarse bucket."""
    try:
        p = float(phase_str)
    except (ValueError, TypeError):
        return "early"
    if p >= 3:
        return "phase3"
    if p >= 2:
        return "phase2"
    return "early"


# ═════════════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════════════


class ExpectationErrorModel:
    """Computes structured expectation-error scores for a universe.

    Usage:
        model = ExpectationErrorModel()
        results = model.score_batch(csv_rows, as_of_date)
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        base_rate_table: Optional[Dict[str, Dict[str, float]]] = None,
        conditional_move_table: Optional[Dict[str, float]] = None,
    ) -> None:
        self.weights = weights or dict(_DEFAULT_WEIGHTS)
        self.base_rate_table = base_rate_table or dict(_BASE_RATE_TABLE)
        self.conditional_move_table = conditional_move_table or dict(_CONDITIONAL_MOVE_TABLE)

    # ── Single-row scoring ───────────────────────────────────────────

    def score_row(
        self,
        row: Dict[str, Any],
        as_of_date: str,
        si_p50: float = 0.0,
        si_p90: float = 1.0,
    ) -> ExpectationErrorScore:
        """Score a single ticker row from rankings.csv.

        Args:
            row: dict with CSV field values
            as_of_date: snapshot date (ISO)
            si_p50: cross-sectional P50 of short_interest_pct
            si_p90: cross-sectional P90 of short_interest_pct
        """
        ticker = row.get("ticker", "?")
        features: Dict[str, Any] = {}

        # Extract inputs
        pm = _safe_float(row.get("priced_move_pct"))
        si = _safe_float(row.get("short_interest_pct"))
        mcap = _safe_float(row.get("market_cap_mm"))
        px = _safe_float(row.get("close_price"))
        iem = _safe_float(row.get("implied_event_move"))
        family = (row.get("catalyst_family") or "CLINICAL").upper()
        phase = _phase_bucket(row.get("lead_program_phase", ""))
        precision = (row.get("clinical_days_precision") or "UNKNOWN").upper()

        features["inputs"] = {
            "priced_move_pct": pm,
            "short_interest_pct": si,
            "market_cap_mm": mcap,
            "close_price": px,
            "implied_event_move": iem,
            "catalyst_family": family,
            "phase_bucket": phase,
            "timing_precision": precision,
        }

        # ── A) Base-rate gap ─────────────────────────────────────────
        B = self._base_rate_gap(pm, family, phase)
        features["base_rate_gap_detail"] = {
            "key": f"{family}|{phase}",
            "priced_move_pct": pm,
        }

        # ── B) Conditional misprice ──────────────────────────────────
        C = self._conditional_misprice(pm, family, phase)

        # ── C) Slippage penalty ──────────────────────────────────────
        S = self._slippage_penalty(mcap, px)

        # ── D) Divergence ────────────────────────────────────────────
        D = self._divergence(pm, iem)

        # ── E) Crowding bias ─────────────────────────────────────────
        F = self._crowding_bias(si, si_p50, si_p90)

        # ── F) Timing decay risk ─────────────────────────────────────
        T = self._timing_decay_risk(pm, precision)

        # ── Composite ────────────────────────────────────────────────
        w = self.weights
        ees = (
            w["base_rate_gap"] * B
            + w["conditional_misprice"] * C
            + w["divergence"] * D
            + w["crowding_bias"] * F
            - w["slippage_penalty"] * S
            - w["timing_decay_risk"] * T
        )

        # ── Confidence ───────────────────────────────────────────────
        tf = _TIMING_UNCERTAINTY.get(precision, 1.0)
        conf = 1.0
        if pm is None:
            conf *= 0.75
        if si is None:
            conf *= 0.80
        if mcap is None:
            conf *= 0.80
        conf *= 1.0 - 0.20 * tf
        conf = _clamp(conf, 0.0, 1.0)

        # ── Notes ────────────────────────────────────────────────────
        notes_parts: List[str] = []
        if B > 0.5:
            notes_parts.append("implied >> base rate")
        elif B < -0.5:
            notes_parts.append("implied << base rate")
        if C > 0.3:
            notes_parts.append("scenario EV underpriced")
        elif C < -0.3:
            notes_parts.append("scenario EV overpriced")
        if F > 0.5:
            notes_parts.append("crowded")
        if S > 0.5:
            notes_parts.append("thin liquidity")
        if T > 0.5:
            notes_parts.append("high timing decay risk")
        if D > 0.5:
            notes_parts.append("option-stock divergence")

        return ExpectationErrorScore(
            ticker=ticker,
            as_of_date=as_of_date,
            base_rate_gap_score=round(B, 4),
            conditional_misprice_score=round(C, 4),
            slippage_penalty_score=round(S, 4),
            divergence_score=round(D, 4),
            crowding_bias_score=round(F, 4),
            timing_decay_risk_score=round(T, 4),
            expectation_error_score=round(ees, 4),
            expectation_confidence=round(conf, 4),
            expectation_notes="; ".join(notes_parts) if notes_parts else "",
            features_used=features,
        )

    # ── Batch scoring (cross-sectional) ──────────────────────────────

    def score_batch(
        self,
        csv_rows: List[Dict[str, Any]],
        as_of_date: str,
    ) -> List[ExpectationErrorScore]:
        """Score all rows, computing cross-sectional anchors first.

        Returns one ExpectationErrorScore per row (same order).
        """
        # Compute SI cross-sectional percentiles
        si_vals = []
        for row in csv_rows:
            v = _safe_float(row.get("short_interest_pct"))
            if v is not None:
                si_vals.append(v)

        si_vals_sorted = sorted(si_vals)
        n = len(si_vals_sorted)
        if n >= 2:
            si_p50 = si_vals_sorted[n // 2]
            si_p90 = si_vals_sorted[min(int(n * 0.90), n - 1)]
        else:
            si_p50 = 0.0
            si_p90 = 1.0

        results = []
        for row in csv_rows:
            results.append(self.score_row(row, as_of_date, si_p50, si_p90))

        n_scored = len(results)
        n_high_conf = sum(1 for r in results if r.expectation_confidence >= 0.6)
        logger.info(
            "[EES] Scored %d tickers (%d high-confidence), SI anchors P50=%.1f P90=%.1f",
            n_scored,
            n_high_conf,
            si_p50,
            si_p90,
        )

        return results

    # ═════════════════════════════════════════════════════════════════
    # Sub-score implementations
    # ═════════════════════════════════════════════════════════════════

    def _base_rate_gap(self, priced_move_pct: Optional[float], family: str, phase: str) -> float:
        """Detect base-rate neglect: implied vs historical realised."""
        if priced_move_pct is None:
            return 0.0

        key = f"{family}|{phase}"
        cell = self.base_rate_table.get(key) or self.base_rate_table.get(f"{family}|any")
        if not cell:
            return 0.0

        hist_med = cell["p50"]
        hist_iqr = cell["iqr"]
        return _clamp((priced_move_pct - hist_med) / (hist_iqr + EPS), -1.0, 1.0)

    def _conditional_misprice(self, priced_move_pct: Optional[float], family: str, phase: str) -> float:
        """Detect mispriced conditionals: scenario EV vs implied."""
        if priced_move_pct is None or priced_move_pct < EPS:
            return 0.0

        key = f"{family}|{phase}"
        cond_ev = self.conditional_move_table.get(key)
        if cond_ev is None:
            return 0.0

        return _clamp((cond_ev - priced_move_pct) / (priced_move_pct + EPS), -1.0, 1.0)

    def _slippage_penalty(self, market_cap_mm: Optional[float], close_price: Optional[float]) -> float:
        """Execution friction from thin books / penny stocks."""
        s = 0.0
        if close_price is not None and close_price < 5.0:
            s += 0.30
        if market_cap_mm is not None:
            if market_cap_mm < 100:
                s += 0.70
            elif market_cap_mm < 300:
                s += 0.30
        return _clamp(s, 0.0, 1.0)

    def _divergence(
        self,
        priced_move_pct: Optional[float],
        implied_event_move: Optional[float],
    ) -> float:
        """Option surface vs stock-behaviour divergence.

        Uses implied_event_move (from pos_divergence module) as a
        realised-vol proxy when available.
        """
        if priced_move_pct is None or implied_event_move is None:
            return 0.0
        if implied_event_move < EPS:
            return 0.0

        return _clamp(
            (priced_move_pct - implied_event_move) / (implied_event_move + EPS),
            -1.0,
            1.0,
        )

    def _crowding_bias(
        self,
        short_interest_pct: Optional[float],
        si_p50: float,
        si_p90: float,
    ) -> float:
        """Favourite bias via short-interest crowding."""
        if short_interest_pct is None:
            return 0.0

        denom = si_p90 - si_p50 + EPS
        return _clamp((short_interest_pct - si_p50) / denom, -1.0, 1.0)

    def _timing_decay_risk(self, priced_move_pct: Optional[float], precision: str) -> float:
        """Penalise expensive setups with uncertain catalyst timing."""
        if priced_move_pct is None:
            return 0.0

        tf = _TIMING_UNCERTAINTY.get(precision, 1.0)
        return _clamp(priced_move_pct * tf / 20.0, 0.0, 1.0)


# ═════════════════════════════════════════════════════════════════════════
# Utility: inject EES into csv_rows (called from run_screen.py)
# ═════════════════════════════════════════════════════════════════════════

EES_CSV_COLUMNS = [
    "base_rate_gap_score",
    "conditional_misprice_score",
    "slippage_penalty_score",
    "divergence_score",
    "crowding_bias_score",
    "timing_decay_risk_score",
    "expectation_error_score",
    "expectation_confidence",
    "expectation_notes",
]


def enrich_csv_rows(
    csv_rows: List[Dict[str, Any]],
    as_of_date: str,
) -> List[ExpectationErrorScore]:
    """Compute EES for all rows and inject columns in-place.

    Returns the list of ExpectationErrorScore objects (for sidecar writing).
    """
    model = ExpectationErrorModel()
    scores = model.score_batch(csv_rows, as_of_date)

    for row, ees in zip(csv_rows, scores):
        row["base_rate_gap_score"] = ees.base_rate_gap_score
        row["conditional_misprice_score"] = ees.conditional_misprice_score
        row["slippage_penalty_score"] = ees.slippage_penalty_score
        row["divergence_score"] = ees.divergence_score
        row["crowding_bias_score"] = ees.crowding_bias_score
        row["timing_decay_risk_score"] = ees.timing_decay_risk_score
        row["expectation_error_score"] = ees.expectation_error_score
        row["expectation_confidence"] = ees.expectation_confidence
        row["expectation_notes"] = ees.expectation_notes

    return scores
