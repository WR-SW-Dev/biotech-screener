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

# ── Sub-score weights for the v1 composite EES (DEPRECATED, retained for compat) ─
_DEFAULT_WEIGHTS = {
    "base_rate_gap": 0.30,
    "conditional_misprice": 0.20,
    "divergence": 0.10,
    "crowding_bias": 0.15,
    "slippage_penalty": 0.00,  # DEAD — look-ahead bias (PIT audit 2026-04-12)
    "timing_decay_risk": 0.10,  # subtracted
}

# ── v2 overlay weights (PIT-safe re-validation 2026-04-12) ───────────────
# Quality: timing decay only (IC +0.078 at 63d, t=18.1 — PIT-safe)
# NOTE: slippage (market_cap) was look-ahead bias — removed from quality.
_V2_QUALITY_W_TIMING = 1.0
# Trap: avoid fake edge (IC +0.077 at 63d, t=18.5 — PIT-safe)
_V2_TRAP_W_BASE_RATE = 0.50
_V2_TRAP_W_CONDITIONAL = 0.50
# Combined: 50% quality + 50% trap (both ~equal IC, both PIT-safe)
_V2_W_QUALITY = 0.50
_V2_W_TRAP = 0.50

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

        # ── v1 Composite (retained for backwards compat) ─────────────
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

        # ── v2 overlays (PIT-safe re-validation 2026-04-12) ────────
        # Quality: timing discipline only (slippage was look-ahead bias)
        quality = -(_V2_QUALITY_W_TIMING * T)
        # Trap: penalise obvious cheap setups (higher = safer, less trap)
        trap = -(_V2_TRAP_W_BASE_RATE * B + _V2_TRAP_W_CONDITIONAL * C)
        # Combined: equal weight (both ~IC +0.077, both PIT-safe)
        v2 = _V2_W_QUALITY * quality + _V2_W_TRAP * trap

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
            quality_overlay_score=round(quality, 4),
            trap_overlay_score=round(trap, 4),
            ees_v2_score=round(v2, 4),
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

    # ── Gate computation ─────────────────────────────────────────────

    @staticmethod
    def compute_gates(
        scores: List[ExpectationErrorScore],
        quality_cut_pct: int = 15,
        trap_cut_pct: int = 20,
    ) -> Dict[str, Dict[str, Any]]:
        """Compute percentile-based gates for each ticker.

        Args:
            scores: output of score_batch
            quality_cut_pct: exclude bottom N% by quality (default 15)
            trap_cut_pct: exclude bottom N% by trap (default 20)

        Returns:
            {ticker: {"ees_quality_gate": bool, "ees_trap_gate": bool,
                       "ees_eligible": bool, "quality_pctile": float,
                       "trap_pctile": float}}
        """
        q_vals = sorted(s.quality_overlay_score for s in scores)
        t_vals = sorted(s.trap_overlay_score for s in scores)
        n = len(q_vals)

        if n < 5:
            return {s.ticker: _pass_all_gates() for s in scores}

        q_thresh = q_vals[min(int(n * quality_cut_pct / 100), n - 1)]
        t_thresh = t_vals[min(int(n * trap_cut_pct / 100), n - 1)]

        # Detect degenerate distributions (e.g. no priced_move_pct → all trap = 0)
        # When a gate can't differentiate, bypass it (all pass).
        q_degenerate = q_vals[0] == q_vals[-1]
        t_degenerate = t_vals[0] == t_vals[-1]
        # Also degenerate if > 80% of values are identical (ties dominate)
        if not t_degenerate:
            t_mode_count = max(t_vals.count(v) for v in set(t_vals))
            t_degenerate = t_mode_count > n * 0.80
        if not q_degenerate:
            q_mode_count = max(q_vals.count(v) for v in set(q_vals))
            q_degenerate = q_mode_count > n * 0.80

        result: Dict[str, Dict[str, Any]] = {}
        for s in scores:
            q_pass = True if q_degenerate else s.quality_overlay_score > q_thresh
            t_pass = True if t_degenerate else s.trap_overlay_score > t_thresh

            # Percentile rank (0-100)
            q_pctile = 50.0 if q_degenerate else sum(1 for v in q_vals if v <= s.quality_overlay_score) / n * 100
            t_pctile = 50.0 if t_degenerate else sum(1 for v in t_vals if v <= s.trap_overlay_score) / n * 100

            result[s.ticker] = {
                "ees_quality_gate": q_pass,
                "ees_trap_gate": t_pass,
                "ees_eligible": q_pass and t_pass,
                "quality_pctile": round(q_pctile, 1),
                "trap_pctile": round(t_pctile, 1),
                "quality_threshold": round(q_thresh, 4),
                "trap_threshold": round(t_thresh, 4),
                "quality_degenerate": q_degenerate,
                "trap_degenerate": t_degenerate,
            }

        return result

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
        """DEPRECATED: was look-ahead bias (PIT audit 2026-04-12).

        Market_cap from PIT archives contained current prices, not historical.
        IC went from +0.106 to -0.088 under PIT-safe data (micro-caps outperform).
        Returns 0.0 always. Retained as interface stub for back-compat.
        """
        return 0.0

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


def _pass_all_gates() -> Dict[str, Any]:
    return {
        "ees_quality_gate": True,
        "ees_trap_gate": True,
        "ees_eligible": True,
        "quality_pctile": 50.0,
        "trap_pctile": 50.0,
        "quality_threshold": 0.0,
        "trap_threshold": 0.0,
    }


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
    "quality_overlay_score",
    "trap_overlay_score",
    "ees_v2_score",
    "ees_quality_gate",
    "ees_trap_gate",
    "ees_eligible",
]

# Default gate thresholds (PIT-safe re-calibration 2026-04-12)
# Trap is the primary gate. Quality/timing off by default.
DEFAULT_QUALITY_CUT_PCT = 0
DEFAULT_TRAP_CUT_PCT = 20

# ── Regime modes (PIT-safe re-calibration 2026-04-12) ────────────────────
# Trap is the primary gate (Sharpe 0.384). Timing is optional stabiliser.
GATE_MODES: Dict[str, Dict[str, int]] = {
    "normal": {"quality_cut_pct": 0, "trap_cut_pct": 20},
    "conservative": {"quality_cut_pct": 15, "trap_cut_pct": 20},
}


def resolve_gate_mode(mode: str = "normal") -> Dict[str, int]:
    """Return gate thresholds for a named mode.

    Args:
        mode: "normal" (Q15/T20) or "conservative" (Q20/T30)
    """
    return dict(GATE_MODES.get(mode, GATE_MODES["normal"]))


def enrich_csv_rows(
    csv_rows: List[Dict[str, Any]],
    as_of_date: str,
    gate_mode: str = "normal",
    quality_cut_pct: Optional[int] = None,
    trap_cut_pct: Optional[int] = None,
) -> List[ExpectationErrorScore]:
    """Compute EES scores and gates for all rows, inject columns in-place.

    Args:
        gate_mode: "normal" (Q15/T20) or "conservative" (Q20/T30)
        quality_cut_pct: override mode's quality threshold
        trap_cut_pct: override mode's trap threshold

    Returns the list of ExpectationErrorScore objects (for sidecar writing).
    """
    mode_cfg = resolve_gate_mode(gate_mode)
    if quality_cut_pct is None:
        quality_cut_pct = mode_cfg["quality_cut_pct"]
    if trap_cut_pct is None:
        trap_cut_pct = mode_cfg["trap_cut_pct"]

    ees_model = ExpectationErrorModel()
    scores = ees_model.score_batch(csv_rows, as_of_date)

    # Compute percentile-based gates
    gates = ExpectationErrorModel.compute_gates(scores, quality_cut_pct, trap_cut_pct)

    n_q_fail = 0
    n_t_fail = 0
    n_eligible = 0

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
        row["quality_overlay_score"] = ees.quality_overlay_score
        row["trap_overlay_score"] = ees.trap_overlay_score
        row["ees_v2_score"] = ees.ees_v2_score

        g = gates.get(ees.ticker, _pass_all_gates())
        row["ees_quality_gate"] = g["ees_quality_gate"]
        row["ees_trap_gate"] = g["ees_trap_gate"]
        row["ees_eligible"] = g["ees_eligible"]

        if not g["ees_quality_gate"]:
            n_q_fail += 1
        if not g["ees_trap_gate"]:
            n_t_fail += 1
        if g["ees_eligible"]:
            n_eligible += 1

    # Gate telemetry — first ticker's thresholds are representative
    first_gate = next(iter(gates.values()), {})
    logger.info(
        "[EES] Gates applied: Q%d/T%d thresholds (q=%.4f, t=%.4f) | " "%d eligible, %d Q-fail, %d T-fail out of %d",
        quality_cut_pct,
        trap_cut_pct,
        first_gate.get("quality_threshold", 0),
        first_gate.get("trap_threshold", 0),
        n_eligible,
        n_q_fail,
        n_t_fail,
        len(scores),
    )

    return scores


# ═════════════════════════════════════════════════════════════════════════
# Gate diagnostics (written as sidecar JSON per snapshot)
# ═════════════════════════════════════════════════════════════════════════


def build_gate_diagnostics(
    scores: List[ExpectationErrorScore],
    csv_rows: List[Dict[str, Any]],
    as_of_date: str,
    gate_mode: str = "normal",
    quality_cut_pct: int = DEFAULT_QUALITY_CUT_PCT,
    trap_cut_pct: int = DEFAULT_TRAP_CUT_PCT,
) -> Dict[str, Any]:
    """Build daily gate diagnostics for monitoring and drift detection.

    Returns a dict suitable for writing to ees_gate_diagnostics.json.
    """
    n_total = len(scores)
    q_vals = [s.quality_overlay_score for s in scores]
    t_vals = [s.trap_overlay_score for s in scores]

    n_q_fail = sum(1 for r in csv_rows if r.get("ees_quality_gate") is False)
    n_t_fail = sum(1 for r in csv_rows if r.get("ees_trap_gate") is False)
    n_both_fail = sum(1 for r in csv_rows if r.get("ees_quality_gate") is False and r.get("ees_trap_gate") is False)
    n_eligible = sum(1 for r in csv_rows if r.get("ees_eligible") is True)

    # Correlation between quality and trap
    corr = _pearson(q_vals, t_vals)

    # Distribution stats
    def _dist(vals: List[float]) -> Dict[str, float]:
        s = sorted(vals)
        n = len(s)
        if n == 0:
            return {}
        return {
            "min": round(s[0], 4),
            "p10": round(s[min(int(n * 0.10), n - 1)], 4),
            "p25": round(s[min(int(n * 0.25), n - 1)], 4),
            "median": round(s[n // 2], 4),
            "p75": round(s[min(int(n * 0.75), n - 1)], 4),
            "p90": round(s[min(int(n * 0.90), n - 1)], 4),
            "max": round(s[-1], 4),
        }

    # Names filtered by each gate
    q_filtered = sorted([r.get("ticker", "") for r in csv_rows if r.get("ees_quality_gate") is False])
    t_filtered = sorted([r.get("ticker", "") for r in csv_rows if r.get("ees_trap_gate") is False])

    return {
        "as_of_date": as_of_date,
        "model_version": "ees_v2.0",
        "gate_mode": gate_mode,
        "quality_cut_pct": quality_cut_pct,
        "trap_cut_pct": trap_cut_pct,
        "universe": {
            "total": n_total,
            "post_quality_gate": n_total - n_q_fail,
            "post_trap_gate": n_total - n_t_fail,
            "eligible": n_eligible,
            "quality_fail": n_q_fail,
            "trap_fail": n_t_fail,
            "both_fail": n_both_fail,
            "pct_eligible": round(n_eligible / n_total * 100, 1) if n_total else 0,
        },
        "quality_trap_correlation": round(corr, 4) if corr is not None else None,
        "quality_distribution": _dist(q_vals),
        "trap_distribution": _dist(t_vals),
        "quality_filtered_names": q_filtered[:30],
        "trap_filtered_names": t_filtered[:30],
    }


def build_gate_performance(
    csv_rows: List[Dict[str, Any]],
    prior_rows: Optional[List[Dict[str, Any]]],
    as_of_date: str,
) -> Optional[Dict[str, Any]]:
    """Compare realized returns of gated-out vs eligible names.

    Uses close_price from current snapshot vs prior snapshot to compute
    short-term realized returns by gate bucket. Returns None if no
    prior snapshot available.
    """
    if not prior_rows:
        return None

    # Build prior price map
    prior_prices: Dict[str, float] = {}
    for r in prior_rows:
        ticker = r.get("ticker", "")
        px = _safe_float(r.get("close_price"))
        if ticker and px and px > 0:
            prior_prices[ticker] = px

    # Build current price map and gate status from prior snapshot's gates
    buckets: Dict[str, List[float]] = {
        "eligible": [],
        "quality_fail": [],
        "trap_fail": [],
        "both_fail": [],
    }

    for r in prior_rows:
        ticker = r.get("ticker", "")
        prior_px = prior_prices.get(ticker)
        if not prior_px:
            continue

        # Find current price
        current_row = next((cr for cr in csv_rows if cr.get("ticker") == ticker), None)
        if not current_row:
            continue
        current_px = _safe_float(current_row.get("close_price"))
        if not current_px or current_px <= 0:
            continue

        ret = current_px / prior_px - 1.0

        q_gate = str(r.get("ees_quality_gate", "")).strip().lower() != "false"
        t_gate = str(r.get("ees_trap_gate", "")).strip().lower() != "false"
        eligible = str(r.get("ees_eligible", "")).strip().lower() == "true"

        if not q_gate and not t_gate:
            buckets["both_fail"].append(ret)
        elif not q_gate:
            buckets["quality_fail"].append(ret)
        elif not t_gate:
            buckets["trap_fail"].append(ret)
        elif eligible:
            buckets["eligible"].append(ret)

    def _bucket_stats(rets: List[float]) -> Dict[str, Any]:
        if not rets:
            return {"n": 0, "mean_ret": None, "hit_rate": None}
        import statistics

        return {
            "n": len(rets),
            "mean_ret": round(statistics.mean(rets) * 100, 4),
            "hit_rate": round(sum(1 for r in rets if r > 0) / len(rets), 3),
        }

    return {
        "as_of_date": as_of_date,
        "lookback": "snapshot_to_snapshot",
        "eligible": _bucket_stats(buckets["eligible"]),
        "quality_fail": _bucket_stats(buckets["quality_fail"]),
        "trap_fail": _bucket_stats(buckets["trap_fail"]),
        "both_fail": _bucket_stats(buckets["both_fail"]),
    }


def suggest_gate_mode(
    diagnostics_history: List[Dict[str, Any]],
    performance_history: Optional[List[Dict[str, Any]]] = None,
    min_history: int = 5,
) -> str:
    """Suggest normal vs conservative mode based on diagnostics + outcomes.

    Input-side triggers (structural):
      - correlation(quality, trap) > 0.40 (edges converging)
      - eligible % < 50% (universe already tight)
      - trap fail rate > 35% (more traps than usual)

    Output-side triggers (outcome-based):
      - trap_fail mean return > -3% (trap gate not working)
      - eligible-vs-excluded gap < 1% (gates not separating)

    Args:
        diagnostics_history: list of gate_diagnostics dicts, newest last
        performance_history: list of gate_performance dicts, newest last
        min_history: minimum history length before switching

    Returns:
        "normal" or "conservative"
    """
    if len(diagnostics_history) < min_history:
        return "normal"

    recent = diagnostics_history[-min_history:]

    # ── Input-side signals ───────────────────────────────────────

    # Signal 1: correlation drift
    corrs = [d.get("quality_trap_correlation") for d in recent if d.get("quality_trap_correlation") is not None]
    avg_corr = sum(corrs) / len(corrs) if corrs else 0

    # Signal 2: eligible % dropping
    pct_eligible = [d.get("universe", {}).get("pct_eligible", 100) for d in recent]
    avg_eligible = sum(pct_eligible) / len(pct_eligible) if pct_eligible else 100

    # Signal 3: trap fail rate spiking
    trap_rates = []
    for d in recent:
        u = d.get("universe", {})
        total = u.get("total", 1)
        trap_fail = u.get("trap_fail", 0)
        if total > 0:
            trap_rates.append(trap_fail / total * 100)
    avg_trap_rate = sum(trap_rates) / len(trap_rates) if trap_rates else 20

    # ── Output-side signals ──────────────────────────────────────

    avg_trap_fail_ret = None
    avg_gap = None
    if performance_history and len(performance_history) >= min_history:
        recent_perf = performance_history[-min_history:]

        # Signal 4: trap_fail return not negative enough (trap not working)
        trap_rets = [
            p["trap_fail"]["mean_ret"] for p in recent_perf if p.get("trap_fail", {}).get("mean_ret") is not None
        ]
        if trap_rets:
            avg_trap_fail_ret = sum(trap_rets) / len(trap_rets)

        # Signal 5: eligible-vs-excluded gap shrinking
        gaps = []
        for p in recent_perf:
            e_ret = p.get("eligible", {}).get("mean_ret")
            # Weighted average of all excluded buckets
            excl_rets = []
            for bucket in ["quality_fail", "trap_fail", "both_fail"]:
                b = p.get(bucket, {})
                if b.get("mean_ret") is not None and b.get("n", 0) > 0:
                    excl_rets.extend([b["mean_ret"]] * b["n"])
            if e_ret is not None and excl_rets:
                excl_avg = sum(excl_rets) / len(excl_rets)
                gaps.append(e_ret - excl_avg)
        if gaps:
            avg_gap = sum(gaps) / len(gaps)

    # ── Decision logic ───────────────────────────────────────────

    if avg_corr > 0.40:
        logger.info("[EES] Regime: CONSERVATIVE (correlation drift %.3f > 0.40)", avg_corr)
        return "conservative"
    if avg_eligible < 50:
        logger.info("[EES] Regime: CONSERVATIVE (eligible %.1f%% < 50%%)", avg_eligible)
        return "conservative"
    if avg_trap_rate > 35:
        logger.info("[EES] Regime: CONSERVATIVE (trap rate %.1f%% > 35%%)", avg_trap_rate)
        return "conservative"
    if avg_trap_fail_ret is not None and avg_trap_fail_ret > -3.0:
        logger.info(
            "[EES] Regime: CONSERVATIVE (trap_fail return %.2f%% > -3%%, trap not working)",
            avg_trap_fail_ret,
        )
        return "conservative"
    if avg_gap is not None and avg_gap < 1.0:
        logger.info(
            "[EES] Regime: CONSERVATIVE (eligible-vs-excluded gap %.2f%% < 1%%, gates not separating)",
            avg_gap,
        )
        return "conservative"

    return "normal"


def _pearson(x: List[float], y: List[float]) -> Optional[float]:
    """Simple Pearson correlation, no dependencies."""
    n = len(x)
    if n < 3 or len(y) != n:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sx = math.sqrt(sum((x[i] - mx) ** 2 for i in range(n)))
    sy = math.sqrt(sum((y[i] - my) ** 2 for i in range(n)))
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)
