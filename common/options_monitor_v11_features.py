"""Options Monitor v1.1 — Catalyst-aware orthogonal factor features.

Converts raw options chain/surface data into 4 orthogonal factor scores,
a chain quality score, confidence modifier, and catalyst-weighted composite.

Factors:
  F_EP: Event Premium — rich implied vol relative to realized + peers
  F_SR: Surface Repricing — sudden repricing of the options surface
  F_SK: Skew / Tail Stress — asymmetric demand for protection
  F_DV: Stock-Options Divergence — mismatch between price and vol paths

All features are PIT-safe, Decimal-based for CCFT determinism, and
designed to be research-only until backtested and promoted.

Usage:
    from common.options_monitor_v11_features import compute_v11_features
    features = compute_v11_features(row, trailing_data, peer_data)
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Dict, List, Optional

_D = Decimal
_D0 = _D("0")
_D1 = _D("1")


def _d(val: Any, default: Decimal = _D0) -> Decimal:
    """Convert any value to Decimal via str intermediary."""
    if val is None or val == "":
        return default
    try:
        v = float(val)
        if v != v:  # NaN
            return default
        return _D(str(v))
    except (ValueError, TypeError, ArithmeticError):
        return default


def _clip01(x: Decimal) -> Decimal:
    return max(_D0, min(_D1, x))


def _normz(z: Decimal) -> Decimal:
    """Map robust z-score from ~[-2, +2] into [0, 1]."""
    return _clip01((z + _D("2")) / _D("4"))


# ---------------------------------------------------------------------------
# Robust z-score (median/MAD based, PIT-safe)
# ---------------------------------------------------------------------------


def robust_z(current: float, history: List[float]) -> Optional[float]:
    """Compute robust z-score: (x - median) / MAD.

    Uses median absolute deviation for outlier resistance.
    Returns None if insufficient history.
    """
    if not history or len(history) < 10:
        return None
    sorted_h = sorted(history)
    n = len(sorted_h)
    median = sorted_h[n // 2] if n % 2 else (sorted_h[n // 2 - 1] + sorted_h[n // 2]) / 2
    abs_devs = sorted(abs(v - median) for v in sorted_h)
    mad = abs_devs[n // 2] if n % 2 else (abs_devs[n // 2 - 1] + abs_devs[n // 2]) / 2

    if mad < 1e-8:
        return 0.0
    return (current - median) / (mad * 1.4826)  # scale MAD to σ equivalent


def cross_sectional_z(current: float, peer_values: List[float]) -> Optional[float]:
    """Compute cross-sectional z-score vs peer cohort."""
    if not peer_values or len(peer_values) < 5:
        return None
    sorted_p = sorted(peer_values)
    n = len(sorted_p)
    median = sorted_p[n // 2] if n % 2 else (sorted_p[n // 2 - 1] + sorted_p[n // 2]) / 2
    abs_devs = sorted(abs(v - median) for v in sorted_p)
    mad = abs_devs[n // 2] if n % 2 else (abs_devs[n // 2 - 1] + abs_devs[n // 2]) / 2

    if mad < 1e-8:
        return 0.0
    return (current - median) / (mad * 1.4826)


# ---------------------------------------------------------------------------
# Factor computation
# ---------------------------------------------------------------------------

# Catalyst-class weights for factor combination
CATALYST_WEIGHTS = {
    "regulatory": {"EP": _D("0.35"), "SR": _D("0.25"), "SK": _D("0.25"), "DV": _D("0.15")},
    "clinical_topline": {"EP": _D("0.25"), "SR": _D("0.35"), "SK": _D("0.20"), "DV": _D("0.20")},
    "clinical_safety": {"EP": _D("0.20"), "SR": _D("0.25"), "SK": _D("0.30"), "DV": _D("0.25")},
    "earnings": {"EP": _D("0.40"), "SR": _D("0.25"), "SK": _D("0.15"), "DV": _D("0.20")},
    "financing": {"EP": _D("0.10"), "SR": _D("0.20"), "SK": _D("0.35"), "DV": _D("0.35")},
    "other": {"EP": _D("0.25"), "SR": _D("0.25"), "SK": _D("0.25"), "DV": _D("0.25")},
}


def compute_factor_ep(
    z_event_premium_ts: Optional[float],
    z_event_premium_xs: Optional[float],
    z_term_slope_ts: Optional[float],
    iv_ramp_persist_3: float = 0.0,
) -> Decimal:
    """Event Premium factor [0, 1]."""
    ep = _D0
    n_avail = 0
    total_w = _D0

    if z_event_premium_ts is not None:
        ep += _D("0.40") * _normz(_d(z_event_premium_ts))
        total_w += _D("0.40")
        n_avail += 1
    if z_event_premium_xs is not None:
        ep += _D("0.25") * _normz(_d(z_event_premium_xs))
        total_w += _D("0.25")
        n_avail += 1
    if z_term_slope_ts is not None:
        ep += _D("0.20") * _normz(_d(z_term_slope_ts))
        total_w += _D("0.20")
        n_avail += 1

    ep += _D("0.15") * _clip01(_d(iv_ramp_persist_3))
    total_w += _D("0.15")

    if total_w > _D0 and n_avail > 0:
        return _clip01(ep / total_w * (_D1 + _D("0.15")))  # redistribute missing weight
    return _D0


def compute_factor_sr(
    z_iv_change_3d_ts: Optional[float],
    z_iv_change_3d_xs: Optional[float],
    z_surface_move_ts: Optional[float],
    iv_accel_3: float = 0.0,
) -> Decimal:
    """Surface Repricing factor [0, 1]."""
    sr = _D0
    total_w = _D0

    if z_iv_change_3d_ts is not None:
        sr += _D("0.35") * _normz(_d(z_iv_change_3d_ts))
        total_w += _D("0.35")
    if z_iv_change_3d_xs is not None:
        sr += _D("0.20") * _normz(_d(z_iv_change_3d_xs))
        total_w += _D("0.20")
    if z_surface_move_ts is not None:
        sr += _D("0.25") * _normz(_d(z_surface_move_ts))
        total_w += _D("0.25")

    sr += _D("0.20") * _normz(_d(iv_accel_3))
    total_w += _D("0.20")

    return _clip01(sr / total_w) if total_w > _D0 else _D0


def compute_factor_sk(
    z_skew_ts: Optional[float],
    z_skew_change_ts: Optional[float],
    skew_persist_3: float = 0.0,
    backwardation_flag: bool = False,
) -> Decimal:
    """Skew / Tail Stress factor [0, 1]."""
    sk = _D0
    total_w = _D0

    if z_skew_ts is not None:
        sk += _D("0.45") * _normz(_d(z_skew_ts))
        total_w += _D("0.45")
    if z_skew_change_ts is not None:
        sk += _D("0.25") * _normz(_d(z_skew_change_ts))
        total_w += _D("0.25")

    sk += _D("0.15") * _clip01(_d(skew_persist_3))
    total_w += _D("0.15")
    sk += _D("0.15") * (_D1 if backwardation_flag else _D0)
    total_w += _D("0.15")

    return _clip01(sk / total_w) if total_w > _D0 else _D0


def compute_factor_dv(
    stock_down_iv_up: bool = False,
    stock_up_iv_down: bool = False,
    quiet_before_catalyst: bool = False,
    z_stock_ret_xs: Optional[float] = None,
    z_iv_change_ts: Optional[float] = None,
) -> Decimal:
    """Stock-Options Divergence factor [0, 1]."""
    dv = _D0
    dv += _D("0.30") * (_D1 if stock_down_iv_up else _D0)
    dv += _D("0.20") * (_D1 if stock_up_iv_down else _D0)
    dv += _D("0.30") * (_D1 if quiet_before_catalyst else _D0)

    # Interaction: large stock move + large IV change in same direction = less divergent
    if z_stock_ret_xs is not None and z_iv_change_ts is not None:
        interaction = _normz(_d(abs(z_stock_ret_xs))) * _normz(_d(z_iv_change_ts))
        dv += _D("0.20") * interaction
    else:
        dv += _D("0.20") * _D("0.5")  # neutral when missing

    return _clip01(dv)


# ---------------------------------------------------------------------------
# Chain quality and confidence
# ---------------------------------------------------------------------------


def compute_chain_quality(
    bid_ask_pct_median: float = 0.0,
    open_interest_total: int = 0,
    volume_total: int = 0,
    strike_coverage_score: float = 0.0,
    surface_fit_r2: float = 0.0,
    stale_quote_pct: float = 0.0,
) -> Decimal:
    """Chain quality score Q [0, 1]."""
    q = _D0
    q += _D("0.30") * _clip01(_D1 - _d(bid_ask_pct_median) / _D("0.20"))
    q += _D("0.20") * _clip01(_d(math.log(1 + open_interest_total)) / _D("8"))
    q += _D("0.15") * _clip01(_d(math.log(1 + volume_total)) / _D("7"))
    q += _D("0.15") * _clip01(_d(strike_coverage_score))
    q += _D("0.10") * _clip01(_d(surface_fit_r2))
    q += _D("0.10") * _clip01(_D1 - _d(stale_quote_pct))
    return _clip01(q)


def compute_confidence(
    chain_quality: Decimal,
    event_window_flag: bool = False,
    hard_catalyst_flag: bool = False,
) -> Decimal:
    """Confidence modifier C [0, 1]."""
    c = chain_quality
    c = c * (_D("0.7") + _D("0.3") * (_D1 if event_window_flag else _D0))
    c = c * (_D("0.8") + _D("0.2") * (_D1 if hard_catalyst_flag else _D0))
    return _clip01(c)


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def compute_composite(
    f_ep: Decimal,
    f_sr: Decimal,
    f_sk: Decimal,
    f_dv: Decimal,
    confidence: Decimal,
    catalyst_class: str = "other",
) -> Decimal:
    """Catalyst-weighted composite S_final [0, 1]."""
    weights = CATALYST_WEIGHTS.get(catalyst_class, CATALYST_WEIGHTS["other"])

    s_raw = weights["EP"] * f_ep + weights["SR"] * f_sr + weights["SK"] * f_sk + weights["DV"] * f_dv
    s_adj = s_raw * confidence

    # Orthogonality cap: reduce triple-counting
    max_factor = max(f_ep, f_sr, f_sk, f_dv)
    s_final = _D("0.85") * s_adj + _D("0.15") * max_factor

    return _clip01(s_final.quantize(_D("0.0001")))


# ---------------------------------------------------------------------------
# Monitor verdict
# ---------------------------------------------------------------------------


def classify_monitor_verdict(s_final: Decimal) -> str:
    """Map composite to monitor verdict."""
    if s_final >= _D("0.70"):
        return "HIGH"
    if s_final >= _D("0.50"):
        return "WATCH"
    return "NONE"


def identify_primary_factor(
    f_ep: Decimal,
    f_sr: Decimal,
    f_sk: Decimal,
    f_dv: Decimal,
) -> str:
    """Identify which factor dominates."""
    factors = {"EP": f_ep, "SR": f_sr, "SK": f_sk, "DV": f_dv}
    return max(factors, key=factors.get)


# ---------------------------------------------------------------------------
# Full feature computation (Sprint 1 entry point)
# ---------------------------------------------------------------------------


def compute_v11_features(
    *,
    # Z-scores (caller computes from trailing/peer data)
    z_event_premium_ts: Optional[float] = None,
    z_event_premium_xs: Optional[float] = None,
    z_term_slope_ts: Optional[float] = None,
    z_iv_change_3d_ts: Optional[float] = None,
    z_iv_change_3d_xs: Optional[float] = None,
    z_surface_move_ts: Optional[float] = None,
    z_skew_ts: Optional[float] = None,
    z_skew_change_ts: Optional[float] = None,
    z_stock_ret_xs: Optional[float] = None,
    z_iv_change_ts: Optional[float] = None,
    # Persistence/acceleration (caller computes from trailing)
    iv_ramp_persist_3: float = 0.0,
    iv_accel_3: float = 0.0,
    skew_persist_3: float = 0.0,
    # Binary flags
    backwardation_flag: bool = False,
    stock_down_iv_up: bool = False,
    stock_up_iv_down: bool = False,
    quiet_before_catalyst: bool = False,
    event_window_flag: bool = False,
    hard_catalyst_flag: bool = False,
    # Chain quality inputs
    bid_ask_pct_median: float = 0.0,
    open_interest_total: int = 0,
    volume_total: int = 0,
    strike_coverage_score: float = 0.0,
    surface_fit_r2: float = 0.0,
    stale_quote_pct: float = 0.0,
    # Catalyst context
    catalyst_class: str = "other",
) -> Dict[str, Any]:
    """Compute all v1.1 features for one ticker.

    Returns dict with all om11_* fields ready for artifact/CSV injection.
    """
    f_ep = compute_factor_ep(z_event_premium_ts, z_event_premium_xs, z_term_slope_ts, iv_ramp_persist_3)
    f_sr = compute_factor_sr(z_iv_change_3d_ts, z_iv_change_3d_xs, z_surface_move_ts, iv_accel_3)
    f_sk = compute_factor_sk(z_skew_ts, z_skew_change_ts, skew_persist_3, backwardation_flag)
    f_dv = compute_factor_dv(stock_down_iv_up, stock_up_iv_down, quiet_before_catalyst, z_stock_ret_xs, z_iv_change_ts)

    q = compute_chain_quality(
        bid_ask_pct_median, open_interest_total, volume_total, strike_coverage_score, surface_fit_r2, stale_quote_pct
    )
    c = compute_confidence(q, event_window_flag, hard_catalyst_flag)

    s_final = compute_composite(f_ep, f_sr, f_sk, f_dv, c, catalyst_class)
    verdict = classify_monitor_verdict(s_final)
    primary = identify_primary_factor(f_ep, f_sr, f_sk, f_dv)

    return {
        "om11_factor_event_premium": str(f_ep.quantize(_D("0.0001"))),
        "om11_factor_surface_repricing": str(f_sr.quantize(_D("0.0001"))),
        "om11_factor_skew_tail": str(f_sk.quantize(_D("0.0001"))),
        "om11_factor_divergence": str(f_dv.quantize(_D("0.0001"))),
        "om11_chain_quality": str(q.quantize(_D("0.0001"))),
        "om11_confidence": str(c.quantize(_D("0.0001"))),
        "om11_score_final": str(s_final),
        "om11_primary_factor": primary,
        "om11_monitor_verdict": verdict,
        "om11_catalyst_class": catalyst_class,
        "om11_event_window_flag": "1" if event_window_flag else "0",
    }
