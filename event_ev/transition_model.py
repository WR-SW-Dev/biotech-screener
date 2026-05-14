"""Markov Chain State Transition Model — runway financing risk probabilities.

Framework:
  Four independent Markov chains model state transitions for:
    1. Runway severity (Phase 1)
    2. Dilution pressure (Phase 2)
    3. Catalyst timing (Phase 3)
    4. Expectation regime (Phase 4)
    5. Hidden regime inference via HMM (Phase 5, research-only)

Design:
  - Observable Markov (v0), not HMM.
  - Walk-forward estimation: train only on data <= as_of_date.
  - Shadow columns only: no ranking/selector/truth-gate mutations.
  - Pooled cross-sectional fallback for sparse tickers (< 20 transitions observed).
  - Minimum transition count = 5 per (state_i, state_j) cell for reliability.

Phase 1 (Runway Chain):
  States: SAFE → WATCH → STRESSED → FINANCING_LIKELY → DISTRESS
  Inputs: runway_buffer_months, ev_severity_score, months_to_cash_out
  Outputs: p_runway_worse_60d, p_financing_90d, p_distress_90d

Policy:
  - DIAGNOSTIC OVERLAY only. No effect on ranking/selector/truth gate in v0.
  - Forward-only emission (no historical rankings.csv mutation).
  - PIT-safe: uses only data available at as_of_date.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

EPS = 1e-9

# ═════════════════════════════════════════════════════════════════════════
# Phase 1: Runway State Definition
# ═════════════════════════════════════════════════════════════════════════

RUNWAY_STATES = {
    0: "SAFE",
    1: "WATCH",
    2: "STRESSED",
    3: "FINANCING_LIKELY",
    4: "DISTRESS",
}

STATE_TO_IDX = {v: k for k, v in RUNWAY_STATES.items()}
N_STATES = len(RUNWAY_STATES)


def label_runway_state(
    runway_buffer_months: Optional[float],
    months_to_cash_out: Optional[float],
    ev_severity_score: Optional[float],
    has_shelf_or_atm: bool = False,
) -> int:
    """Label a single observation into one of {0, 1, 2, 3, 4}.

    State definition:
      0 = SAFE:              buffer >= 9 months, severity < 0.40
      1 = WATCH:            buffer 3–9 months, severity 0.15–0.40
      2 = STRESSED:         buffer 0–3 months, severity 0.40–0.70
      3 = FINANCING_LIKELY: buffer < 0 months OR severity >= 0.70 (but not DISTRESS)
      4 = DISTRESS:         buffer < 0 AND cash_out < 4 AND no decisive catalyst nearby

    Returns: integer state index [0, 4]
    """
    # Defaults for missing data: assume WATCH (middle state)
    if runway_buffer_months is None and months_to_cash_out is None:
        return STATE_TO_IDX["WATCH"]

    if months_to_cash_out is None:
        months_to_cash_out = 12.0  # conservative default

    if runway_buffer_months is None:
        runway_buffer_months = months_to_cash_out - 6.0

    if ev_severity_score is None:
        ev_severity_score = 0.35  # middle of range

    # Distress: < 4 months to cash out and high severity
    if months_to_cash_out < 4 and ev_severity_score > 0.80:
        return STATE_TO_IDX["DISTRESS"]

    # Financing likely: buffer < 0 or severity >= 0.70
    if runway_buffer_months < 0 or ev_severity_score >= 0.70:
        return STATE_TO_IDX["FINANCING_LIKELY"]

    # Stressed: buffer 0–3 months
    if 0 <= runway_buffer_months < 3:
        return STATE_TO_IDX["STRESSED"]

    # Watch: buffer 3–9 months
    if 3 <= runway_buffer_months < 9:
        return STATE_TO_IDX["WATCH"]

    # Safe: buffer >= 9 months
    return STATE_TO_IDX["SAFE"]


# ═════════════════════════════════════════════════════════════════════════
# Data Contracts
# ═════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RunwayTransitionOverlay:
    """Runway chain state and transition probabilities for one ticker."""

    ticker: str
    as_of_date: str
    current_state: str  # e.g., "SAFE"
    current_state_idx: int

    # Transition probabilities: P(next_state | current_state)
    p_1step: Dict[str, float]  # {state_name: probability}

    # Multi-step forecasts
    p_runway_worse_30d: float  # P(STRESSED | FINANCING | DISTRESS at T+30d)
    p_runway_worse_60d: float  # P(STRESSED | FINANCING | DISTRESS at T+60d)
    p_financing_90d: float  # P(FINANCING_LIKELY | DISTRESS at T+90d)
    p_distress_90d: float  # P(DISTRESS at T+90d)

    # Metadata
    transition_count: int  # observed transitions for this ticker in training window
    is_pooled_estimate: bool  # True if using cross-sectional fallback
    model_version: str = "transition_model_v0.1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "as_of_date": self.as_of_date,
            "current_state": self.current_state,
            "p_1step": {k: round(v, 4) for k, v in self.p_1step.items()},
            "p_runway_worse_30d": round(self.p_runway_worse_30d, 4),
            "p_runway_worse_60d": round(self.p_runway_worse_60d, 4),
            "p_financing_90d": round(self.p_financing_90d, 4),
            "p_distress_90d": round(self.p_distress_90d, 4),
            "transition_count": self.transition_count,
            "is_pooled_estimate": self.is_pooled_estimate,
            "model_version": self.model_version,
        }


# ═════════════════════════════════════════════════════════════════════════
# Transition Matrix Estimation
# ═════════════════════════════════════════════════════════════════════════


def _normalize_transition_matrix(counts: np.ndarray) -> np.ndarray:
    """Normalize transition count matrix to probabilities.

    Each row sums to 1.0. If a row has zero counts, use uniform distribution.
    """
    P = np.zeros_like(counts, dtype=float)
    for i in range(counts.shape[0]):
        row_sum = counts[i].sum()
        if row_sum > 0:
            P[i] = counts[i] / row_sum
        else:
            P[i] = 1.0 / counts.shape[1]  # uniform fallback
    return P


def _transition_matrix_power(P: np.ndarray, n: int) -> np.ndarray:
    """Compute P^n (n-step transition probabilities).

    Uses iterative multiplication, which is stable for small matrices.
    """
    if n <= 0:
        return np.eye(P.shape[0])
    if n == 1:
        return P.copy()

    result = P.copy()
    for _ in range(n - 1):
        result = result @ P
    return result


def estimate_transition_matrix_for_ticker(
    ticker_history: List[Tuple[str, int]],  # [(date, state_idx), ...]
    min_transitions: int = 5,
) -> Tuple[np.ndarray, int]:
    """Estimate transition matrix for one ticker from its state history.

    Arguments:
        ticker_history: list of (date, state_idx) tuples, sorted by date
        min_transitions: if fewer than this, return None and fallback count

    Returns:
        (P, n_transitions) where P is the transition matrix or None if sparse
    """
    if len(ticker_history) < 2:
        return None, 0

    counts = np.zeros((N_STATES, N_STATES), dtype=int)
    n_trans = 0

    for i in range(len(ticker_history) - 1):
        current_state = ticker_history[i][1]
        next_state = ticker_history[i + 1][1]
        if 0 <= current_state < N_STATES and 0 <= next_state < N_STATES:
            counts[current_state, next_state] += 1
            n_trans += 1

    if n_trans < min_transitions:
        return None, n_trans

    return _normalize_transition_matrix(counts), n_trans


# ═════════════════════════════════════════════════════════════════════════
# Main Model
# ═════════════════════════════════════════════════════════════════════════


class RunwayTransitionModel:
    """Markov Chain model for runway financing transitions (Phase 1).

    Walk-forward estimation: always train on data up to (and including)
    as_of_date, never future data.
    """

    def __init__(
        self,
        lookback_window: int = 252,  # trading days for rolling estimation
        min_ticker_transitions: int = 5,  # sparse ticker threshold
    ):
        self.lookback_window = lookback_window
        self.min_ticker_transitions = min_ticker_transitions
        self.pooled_transition_matrix: Optional[np.ndarray] = None
        self.ticker_histories: Dict[str, List[Tuple[str, int]]] = defaultdict(list)

    def load_snapshot_history(
        self,
        snap_dir: Path,
        as_of_date: str,
    ) -> None:
        """Load all snapshots up to as_of_date and build ticker state histories.

        Arguments:
            snap_dir: path to data/snapshots/
            as_of_date: exclude snapshots after this date (YYYY-MM-DD)
        """
        snapshots = sorted(snap_dir.glob("20??-??-??"))
        snapshots = [s for s in snapshots if s.name <= as_of_date]

        for snap_path in snapshots:
            try:
                snap_date = snap_path.name
                rankings_csv = snap_path / "rankings.csv"
                if not rankings_csv.exists():
                    continue

                df = pd.read_csv(rankings_csv, dtype={"ticker": str})
                for _, row in df.iterrows():
                    ticker = str(row.get("ticker", "")).strip()
                    if not ticker:
                        continue

                    state_idx = label_runway_state(
                        runway_buffer_months=_safe_float(row.get("runway_buffer_months")),
                        months_to_cash_out=_safe_float(row.get("months_to_cash_out")),
                        ev_severity_score=_safe_float(row.get("ev_severity_score")),
                        has_shelf_or_atm=False,  # TODO: wire from rankings
                    )
                    self.ticker_histories[ticker].append((snap_date, state_idx))

            except Exception as e:
                logger.warning(f"Failed to load snapshot {snap_path.name}: {e}")

        logger.info(
            "[RunwayTransition] Loaded state histories for %d tickers from %d snapshots",
            len(self.ticker_histories),
            len(snapshots),
        )

    def estimate_pooled_matrix(self) -> np.ndarray:
        """Estimate transition matrix from all ticker histories (cross-sectional pool)."""
        counts = np.zeros((N_STATES, N_STATES), dtype=int)

        for ticker, history in self.ticker_histories.items():
            if len(history) >= 2:
                for i in range(len(history) - 1):
                    current_state = history[i][1]
                    next_state = history[i + 1][1]
                    if 0 <= current_state < N_STATES and 0 <= next_state < N_STATES:
                        counts[current_state, next_state] += 1

        P = _normalize_transition_matrix(counts)
        return P

    def score_row(
        self,
        row: Dict[str, Any],
        ticker_matrix: Optional[np.ndarray],
    ) -> RunwayTransitionOverlay:
        """Compute transition probabilities for one row.

        Uses ticker-specific matrix if available, else pooled matrix.
        """
        ticker = str(row.get("ticker", "")).strip() or "?"
        as_of_date = row.get("as_of_date", "?")

        current_state_idx = label_runway_state(
            runway_buffer_months=_safe_float(row.get("runway_buffer_months")),
            months_to_cash_out=_safe_float(row.get("months_to_cash_out")),
            ev_severity_score=_safe_float(row.get("ev_severity_score")),
            has_shelf_or_atm=False,
        )
        current_state = RUNWAY_STATES[current_state_idx]

        # Choose matrix: ticker-specific or pooled
        P = ticker_matrix if ticker_matrix is not None else self.pooled_transition_matrix
        if P is None:
            # Fallback: uniform (should rarely happen)
            P = np.ones((N_STATES, N_STATES)) / N_STATES

        # 1-step probabilities
        p_1step = {RUNWAY_STATES[i]: float(P[current_state_idx, i]) for i in range(N_STATES)}

        # Multi-step: P^n gives n-step transition probabilities
        # T+30d ≈ 5 weeks ≈ 1 month
        # T+60d ≈ 12 weeks ≈ 2 months
        # T+90d ≈ 18 weeks ≈ 3 months
        # For trading days: 252 per year → ~21 per month
        P_30d = _transition_matrix_power(P, 20)  # ~1 month
        P_60d = _transition_matrix_power(P, 40)  # ~2 months
        P_90d = _transition_matrix_power(P, 60)  # ~3 months

        # P(worse) = P(STRESSED | FINANCING_LIKELY | DISTRESS)
        worse_states = {STATE_TO_IDX["STRESSED"], STATE_TO_IDX["FINANCING_LIKELY"], STATE_TO_IDX["DISTRESS"]}
        p_worse_30d = sum(P_30d[current_state_idx, j] for j in worse_states)
        p_worse_60d = sum(P_60d[current_state_idx, j] for j in worse_states)

        # P(financing) = P(FINANCING_LIKELY | DISTRESS)
        financing_states = {STATE_TO_IDX["FINANCING_LIKELY"], STATE_TO_IDX["DISTRESS"]}
        p_financing_90d = sum(P_90d[current_state_idx, j] for j in financing_states)

        # P(distress) = P(DISTRESS)
        p_distress_90d = P_90d[current_state_idx, STATE_TO_IDX["DISTRESS"]]

        # Transition count for metadata
        trans_count = 0
        if ticker in self.ticker_histories:
            trans_count = len(self.ticker_histories[ticker]) - 1

        is_pooled = ticker_matrix is None

        return RunwayTransitionOverlay(
            ticker=ticker,
            as_of_date=as_of_date,
            current_state=current_state,
            current_state_idx=current_state_idx,
            p_1step=p_1step,
            p_runway_worse_30d=max(0.0, min(1.0, p_worse_30d)),
            p_runway_worse_60d=max(0.0, min(1.0, p_worse_60d)),
            p_financing_90d=max(0.0, min(1.0, p_financing_90d)),
            p_distress_90d=max(0.0, min(1.0, p_distress_90d)),
            transition_count=trans_count,
            is_pooled_estimate=is_pooled,
        )

    def score_batch(
        self,
        csv_rows: List[Dict[str, Any]],
    ) -> List[RunwayTransitionOverlay]:
        """Score all rows using estimated matrices."""
        results = []

        for row in csv_rows:
            # In v0, always use pooled matrix (walk-forward not yet wired)
            # TODO: wire walk-forward per ticker when snapshot loading is integrated
            overlay = self.score_row(row, ticker_matrix=None)
            results.append(overlay)

        return results


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════


def _safe_float(v: Any) -> Optional[float]:
    """Safely convert to float, handling None, NaN, 'None' strings."""
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


# ═════════════════════════════════════════════════════════════════════════
# CSV Enrichment
# ═════════════════════════════════════════════════════════════════════════

TRANSITION_CSV_COLUMNS = [
    "transition_runway_state",
    "transition_p_runway_worse_60d",
    "transition_p_financing_90d",
    "transition_p_distress_90d",
]


def enrich_csv_rows(
    csv_rows: List[Dict[str, Any]],
    as_of_date: str,
    snap_dir: Optional[Path] = None,
) -> List[RunwayTransitionOverlay]:
    """Compute runway transitions and inject shadow columns in-place.

    Arguments:
        csv_rows: list of row dicts from rankings.csv
        as_of_date: current snapshot date (YYYY-MM-DD)
        snap_dir: path to data/snapshots/ for historical loading
                  (if None, uses pooled estimate only — v0 behavior)

    Returns:
        List of RunwayTransitionOverlay objects for sidecar writing.

    Side effects:
        Adds shadow columns to csv_rows in-place:
          - transition_runway_state
          - transition_p_runway_worse_60d
          - transition_p_financing_90d
          - transition_p_distress_90d
    """
    model = RunwayTransitionModel()

    # Load history if snap_dir provided (future: walk-forward logic)
    if snap_dir is not None:
        try:
            model.load_snapshot_history(snap_dir, as_of_date)
            model.pooled_transition_matrix = model.estimate_pooled_matrix()
            logger.info(
                "[RunwayTransition] Estimated pooled matrix from %d tickers",
                len(model.ticker_histories),
            )
        except Exception as e:
            logger.warning("[RunwayTransition] Failed to load historical data, using fallback: %s", e)
            # Fallback: use uniform matrix
            model.pooled_transition_matrix = np.ones((N_STATES, N_STATES)) / N_STATES

    else:
        # v0 behavior: no history loading, use uniform fallback
        model.pooled_transition_matrix = np.ones((N_STATES, N_STATES)) / N_STATES

    # Add as_of_date to rows for overlay tracking
    for row in csv_rows:
        row["as_of_date"] = as_of_date

    # Score batch
    overlays = model.score_batch(csv_rows)

    # Inject shadow columns in-place
    for row, overlay in zip(csv_rows, overlays):
        row["transition_runway_state"] = overlay.current_state
        row["transition_p_runway_worse_60d"] = overlay.p_runway_worse_60d
        row["transition_p_financing_90d"] = overlay.p_financing_90d
        row["transition_p_distress_90d"] = overlay.p_distress_90d

    n = len(overlays)
    state_dist = {}
    for ov in overlays:
        state_dist[ov.current_state] = state_dist.get(ov.current_state, 0) + 1
    n_pooled = sum(1 for ov in overlays if ov.is_pooled_estimate)

    logger.info(
        "[RunwayTransition] Scored %d tickers: %s | %d using pooled estimate",
        n,
        " ".join(f"{k}={v}" for k, v in sorted(state_dist.items())),
        n_pooled,
    )

    return overlays
