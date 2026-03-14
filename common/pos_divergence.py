"""Market-implied probability of success (PoS) divergence computation.

Computes the divergence between the options market's implied assessment of
a binary catalyst event and the model's clinical quality signal. The spread
between the two is where alpha lives — when the model says high quality but
the market is pricing a small move, or vice versa.

Core signals:
    implied_event_move: ATM IV × sqrt(T) — the market's expected magnitude
    model_quality_z:    clinical_score_v2_z or composite z — model's view
    pos_divergence_z:   cross-sectional z of (model_z - market_z)

This module provides computation primitives only. The research study that
evaluates whether pos_divergence has predictive value lives in
scripts/research/eval_pos_divergence.py.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List


def compute_implied_event_move(
    atm_iv: float,
    catalyst_days: int,
) -> float:
    """Approximate the market's implied event move from ATM IV.

    For a binary catalyst, the ATM straddle value scales with:
        implied_move ≈ atm_iv × sqrt(days_to_event / 365)

    This is the annualized-IV-to-period-vol conversion — it tells us
    how large a move the options market is pricing around the event.

    Args:
        atm_iv: Annualized ATM implied volatility (e.g. 0.85 for 85%).
        catalyst_days: Days until the binary catalyst.

    Returns:
        Implied move as a fraction (e.g. 0.25 for 25% expected move).
        Returns NaN if inputs are invalid.
    """
    if math.isnan(atm_iv) or atm_iv <= 0 or catalyst_days <= 0:
        return float("nan")
    return atm_iv * math.sqrt(catalyst_days / 365.0)


def compute_iv_premium_ratio(
    atm_iv: float,
    realized_vol: float,
) -> float:
    """Ratio of implied to realized volatility.

    IV/RV > 2.0 → market pricing extreme move (elevated)
    IV/RV < 1.2 → market is complacent (compressed)

    Args:
        atm_iv: Annualized ATM implied volatility.
        realized_vol: Trailing realized volatility (same annualization).

    Returns:
        IV premium ratio, or NaN if inputs are invalid.
    """
    if math.isnan(atm_iv) or math.isnan(realized_vol) or realized_vol <= 0:
        return float("nan")
    return atm_iv / realized_vol


def z_score_array(values: List[float]) -> List[float]:
    """Cross-sectional z-score, skipping NaN values.

    Returns a list of same length with NaN preserved where input is NaN.
    """
    clean = [v for v in values if not math.isnan(v)]
    if len(clean) < 2:
        return [float("nan")] * len(values)
    mean = sum(clean) / len(clean)
    variance = sum((v - mean) ** 2 for v in clean) / len(clean)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return [0.0 if not math.isnan(v) else float("nan") for v in values]
    return [(v - mean) / std if not math.isnan(v) else float("nan") for v in values]


def compute_pos_divergence_panel(
    rows: List[Dict[str, Any]],
    model_signal_col: str = "composite_score",
    atm_iv_col: str = "opt_atm_iv",
    catalyst_days_col: str = "catalyst_days",
) -> List[Dict[str, Any]]:
    """Enrich a panel of rows with PoS divergence signals.

    For each row, computes:
        implied_event_move: market's expected absolute move
        implied_move_z:     cross-sectional z of implied_event_move
        model_signal_z:     cross-sectional z of model signal
        pos_divergence:     model_signal_z - implied_move_z (raw)
        pos_divergence_z:   cross-sectional z of pos_divergence

    A positive pos_divergence means the model is more optimistic than
    the market — the model thinks the name is high-quality but the
    options market is pricing a relatively small move.

    Args:
        rows: List of dicts with at least atm_iv, catalyst_days, and model signal.
        model_signal_col: Column name for the model's quality signal.
        atm_iv_col: Column name for ATM implied volatility.
        catalyst_days_col: Column name for days to catalyst.

    Returns:
        Same rows with added pos_divergence columns.
    """
    if not rows:
        return rows

    # Step 1: Compute implied event move for each row
    implied_moves = []
    for r in rows:
        atm_iv = _safe_float(r.get(atm_iv_col))
        cat_days = _safe_int(r.get(catalyst_days_col))
        implied_moves.append(compute_implied_event_move(atm_iv, cat_days))

    # Step 2: Extract model signals
    model_signals = [_safe_float(r.get(model_signal_col)) for r in rows]

    # Step 3: Cross-sectional z-scores
    implied_move_zs = z_score_array(implied_moves)
    model_signal_zs = z_score_array(model_signals)

    # Step 4: Raw divergence = model_z - market_z
    # Positive = model more bullish than market
    raw_divergences = []
    for mz, iz in zip(model_signal_zs, implied_move_zs):
        if math.isnan(mz) or math.isnan(iz):
            raw_divergences.append(float("nan"))
        else:
            raw_divergences.append(mz - iz)

    # Step 5: Z-score the divergence itself
    divergence_zs = z_score_array(raw_divergences)

    # Step 6: Enrich rows
    for i, r in enumerate(rows):
        r["implied_event_move"] = implied_moves[i]
        r["implied_move_z"] = implied_move_zs[i]
        r["model_signal_z"] = model_signal_zs[i]
        r["pos_divergence"] = raw_divergences[i]
        r["pos_divergence_z"] = divergence_zs[i]

    return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (ValueError, TypeError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return default
