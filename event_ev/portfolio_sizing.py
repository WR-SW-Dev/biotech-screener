"""Portfolio sizing module — conviction-weighted, liquidity-capped.

Architecture: Trap gate → B6 rank → size by conviction + trap strength.

Position sizing formula:
    weight_i ∝ (B6_percentile ** α) × trap_strength × liquidity_cap

Capital allocation:
    alloc = base_capital × sqrt(coverage / target)

Policy: production-ready. Uses only PIT-safe, certified inputs.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────

DEFAULT_ALPHA = 1.5  # concentration exponent (higher = more top-heavy)
DEFAULT_MAX_SINGLE_PCT = 0.10  # max 10% in one name
DEFAULT_MIN_WEIGHT_PCT = 0.005  # drop positions < 0.5%
DEFAULT_LIQUIDITY_K = 0.02  # max 2% of 20d avg dollar volume (NOT used in alpha sizing)
DEFAULT_TARGET_COVERAGE = 0.70  # expected coverage fraction

# Execution guardrails (applied post-sizing, not in alpha weights)
DEFAULT_MAX_PARTICIPATION_PCT = 0.05  # scale down if trade > 5% ADV
DEFAULT_SKIP_PARTICIPATION_PCT = 0.20  # skip trade entirely if > 20% ADV


# ═════════════════════════════════════════════════════════════════════════
# Position sizing
# ═════════════════════════════════════════════════════════════════════════


def compute_weights(
    tickers: List[str],
    b6_scores: Dict[str, float],
    trap_scores: Dict[str, float],
    dollar_volumes: Optional[Dict[str, float]] = None,
    portfolio_value: float = 1_000_000,
    alpha: float = DEFAULT_ALPHA,
    max_single_pct: float = DEFAULT_MAX_SINGLE_PCT,
    min_weight_pct: float = DEFAULT_MIN_WEIGHT_PCT,
    liquidity_k: float = DEFAULT_LIQUIDITY_K,
) -> Dict[str, float]:
    """Compute conviction-weighted, liquidity-capped portfolio weights.

    Args:
        tickers: ordered list (best first by B6 rank)
        b6_scores: {ticker: selector_score} (0-1 percentile)
        trap_scores: {ticker: trap_overlay_score}
        dollar_volumes: {ticker: 20d avg dollar volume} (optional)
        portfolio_value: total capital
        alpha: concentration exponent
        max_single_pct: max single-name weight
        min_weight_pct: minimum position threshold
        liquidity_k: fraction of dollar volume as max position

    Returns:
        {ticker: weight} normalized to sum=1.0
    """
    if not tickers:
        return {}

    # Step 1: B6 conviction weight (rank-based, power-law)
    raw_weights: Dict[str, float] = {}
    for t in tickers:
        b6 = b6_scores.get(t, 0.5)
        raw_weights[t] = max(b6, 0.01) ** alpha

    # Step 2: Trap strength scaling (barely-passing = scale down)
    trap_vals = [trap_scores.get(t, 0) for t in tickers]
    if trap_vals:
        trap_min = min(trap_vals)
        trap_range = max(trap_vals) - trap_min
        if trap_range > 0:
            for t in tickers:
                trap_norm = (trap_scores.get(t, 0) - trap_min) / trap_range
                raw_weights[t] *= 0.5 + 0.5 * trap_norm

    # Step 3: Liquidity cap
    if dollar_volumes:
        for t in tickers:
            dv = dollar_volumes.get(t)
            if dv and dv > 0:
                max_position = liquidity_k * dv
                max_weight = max_position / portfolio_value
                raw_weights[t] = min(raw_weights[t], max_weight)

    # Step 4: Normalize
    total = sum(raw_weights.values())
    if total <= 0:
        # Equal weight fallback
        w = 1.0 / len(tickers)
        return {t: w for t in tickers}

    weights = {t: raw_weights[t] / total for t in tickers}

    # Step 5: Apply max single-name cap (iterative)
    for _ in range(5):
        capped = False
        for t in tickers:
            if weights[t] > max_single_pct:
                weights[t] = max_single_pct
                capped = True
        if not capped:
            break
        # Re-normalize uncapped names
        capped_total = sum(w for w in weights.values() if w >= max_single_pct)
        uncapped_tickers = [t for t in tickers if weights[t] < max_single_pct]
        remaining = 1.0 - capped_total
        uncapped_total = sum(weights[t] for t in uncapped_tickers)
        if uncapped_total > 0 and remaining > 0:
            scale = remaining / uncapped_total
            for t in uncapped_tickers:
                weights[t] *= scale

    # Step 6: Drop dust positions
    weights = {t: w for t, w in weights.items() if w >= min_weight_pct}
    total = sum(weights.values())
    if total > 0:
        weights = {t: w / total for t, w in weights.items()}

    return weights


# ═════════════════════════════════════════════════════════════════════════
# Capital allocation
# ═════════════════════════════════════════════════════════════════════════


def compute_capital_allocation(
    coverage: float,
    base_capital: float = 1_000_000,
    target_coverage: float = DEFAULT_TARGET_COVERAGE,
    min_alloc_pct: float = 0.30,
) -> float:
    """Compute capital allocation based on opportunity-set coverage.

    Uses concave (sqrt) scaling: protects against over-scaling
    when coverage is low.

    Args:
        coverage: fraction of universe passing gates (0-1)
        base_capital: full-deployment capital
        target_coverage: expected normal coverage
        min_alloc_pct: floor (always deploy at least this fraction)

    Returns:
        Capital to deploy.
    """
    if coverage <= 0:
        return base_capital * min_alloc_pct

    ratio = min(coverage / target_coverage, 1.0)
    scale = math.sqrt(ratio)
    alloc_pct = min_alloc_pct + (1.0 - min_alloc_pct) * scale

    return base_capital * alloc_pct


# ═════════════════════════════════════════════════════════════════════════
# Full portfolio construction
# ═════════════════════════════════════════════════════════════════════════


def construct_portfolio(
    eligible_tickers: List[str],
    b6_scores: Dict[str, float],
    trap_scores: Dict[str, float],
    universe_size: int,
    top_n: int = 30,
    dollar_volumes: Optional[Dict[str, float]] = None,
    base_capital: float = 1_000_000,
    alpha: float = DEFAULT_ALPHA,
) -> Dict[str, Any]:
    """Full portfolio construction: rank, size, allocate.

    Args:
        eligible_tickers: tickers passing trap gate
        b6_scores: {ticker: selector_score}
        trap_scores: {ticker: trap_overlay_score}
        universe_size: total universe size (for coverage calc)
        top_n: number of positions
        dollar_volumes: optional liquidity data
        base_capital: total capital
        alpha: concentration exponent

    Returns:
        Dict with positions, weights, capital, diagnostics.
    """
    # Rank by B6
    ranked = sorted(
        [t for t in eligible_tickers if t in b6_scores],
        key=lambda t: b6_scores[t],
        reverse=True,
    )[:top_n]

    # Coverage
    coverage = len(eligible_tickers) / max(universe_size, 1)

    # Capital allocation
    capital = compute_capital_allocation(coverage, base_capital)

    # Weights
    weights = compute_weights(
        ranked,
        b6_scores,
        trap_scores,
        dollar_volumes=dollar_volumes,
        portfolio_value=capital,
        alpha=alpha,
    )

    # Build positions
    positions = []
    for t in ranked:
        w = weights.get(t, 0)
        if w <= 0:
            continue
        positions.append(
            {
                "ticker": t,
                "weight": round(w, 6),
                "capital": round(capital * w, 2),
                "b6_score": round(b6_scores.get(t, 0), 4),
                "trap_score": round(trap_scores.get(t, 0), 4),
            }
        )

    # Diagnostics
    weight_vals = [p["weight"] for p in positions]
    ew_weight = 1.0 / len(positions) if positions else 0
    hhi = sum(w**2 for w in weight_vals) if weight_vals else 0

    return {
        "n_positions": len(positions),
        "coverage": round(coverage, 4),
        "capital_deployed": round(capital, 2),
        "capital_pct": round(capital / base_capital, 4),
        "top_weight": round(max(weight_vals), 4) if weight_vals else 0,
        "bottom_weight": round(min(weight_vals), 4) if weight_vals else 0,
        "ew_equivalent": round(ew_weight, 4),
        "hhi": round(hhi, 6),
        "effective_n": round(1.0 / hhi, 1) if hhi > 0 else 0,
        "positions": positions,
    }


# ═════════════════════════════════════════════════════════════════════════
# Execution guardrails (post-sizing, not in alpha weights)
# ═════════════════════════════════════════════════════════════════════════


def apply_execution_guardrails(
    positions: List[Dict[str, Any]],
    dollar_volumes: Dict[str, float],
    capital: float,
    max_participation: float = DEFAULT_MAX_PARTICIPATION_PCT,
    skip_participation: float = DEFAULT_SKIP_PARTICIPATION_PCT,
) -> Dict[str, Any]:
    """Apply execution guardrails to a constructed portfolio.

    Does NOT change alpha weights. Instead:
    1. Skips names where trade > skip_participation of ADV (default 20%)
    2. Scales down names where trade > max_participation of ADV (default 5%)
    3. Re-normalizes remaining weights

    Args:
        positions: list from construct_portfolio()["positions"]
        dollar_volumes: {ticker: 20d avg dollar volume}
        capital: deployed capital
        max_participation: scale down above this (fraction of ADV)
        skip_participation: skip entirely above this

    Returns:
        Dict with adjusted positions, skipped names, and diagnostics.
    """
    adjusted = []
    skipped = []
    scaled = []

    for pos in positions:
        ticker = pos["ticker"]
        weight = pos["weight"]
        trade_dollars = capital * weight
        dv = dollar_volumes.get(ticker, 0)

        if dv <= 0:
            # Unknown liquidity = worst-case: skip the trade
            skipped.append(
                {
                    "ticker": ticker,
                    "weight": weight,
                    "participation": None,
                    "reason": "no_volume_data",
                }
            )
            continue

        participation = trade_dollars / dv

        if participation > skip_participation:
            skipped.append(
                {
                    "ticker": ticker,
                    "weight": weight,
                    "participation": round(participation, 4),
                    "reason": f">{skip_participation:.0%} ADV",
                }
            )
            continue

        if participation > max_participation:
            # Scale down to max_participation
            new_trade = dv * max_participation
            new_weight = new_trade / capital
            scaled.append(
                {
                    "ticker": ticker,
                    "original_weight": weight,
                    "new_weight": round(new_weight, 6),
                    "participation_before": round(participation, 4),
                    "participation_after": round(max_participation, 4),
                }
            )
            adjusted.append(
                {
                    **pos,
                    "weight": round(new_weight, 6),
                    "capital": round(new_trade, 2),
                    "participation": round(max_participation, 4),
                    "guardrail": "scaled_down",
                }
            )
        else:
            adjusted.append(
                {
                    **pos,
                    "participation": round(participation, 4),
                    "guardrail": "none",
                }
            )

    # Re-normalize
    total_w = sum(p["weight"] for p in adjusted)
    if total_w > 0:
        for p in adjusted:
            p["weight"] = round(p["weight"] / total_w, 6)
            p["capital"] = round(capital * p["weight"], 2)

    return {
        "n_positions": len(adjusted),
        "n_skipped": len(skipped),
        "n_scaled": len(scaled),
        "skipped": skipped,
        "scaled": scaled,
        "positions": adjusted,
    }


# ═════════════════════════════════════════════════════════════════════════
# Execution stress report
# ═════════════════════════════════════════════════════════════════════════


def build_execution_stress_report(
    positions: List[Dict[str, Any]],
    dollar_volumes: Dict[str, float],
    capital: float,
    forward_returns: Optional[Dict[str, float]] = None,
    stress_factor: float = 1.0,
) -> Dict[str, Any]:
    """Build execution stress report for a portfolio.

    Identifies the worst trades by participation, measures their
    PnL contribution, and estimates guardrail impact.

    Args:
        positions: from construct_portfolio()["positions"]
        dollar_volumes: {ticker: 20d avg dollar volume}
        capital: deployed capital
        forward_returns: {ticker: realized return} (optional, for PnL attribution)
        stress_factor: multiply participation by this (1.5-2.0 for stress scenarios)

    Returns:
        Dict with top stress trades, tail concentration, guardrail impact.
    """
    trades = []
    for pos in positions:
        ticker = pos["ticker"]
        weight = pos["weight"]
        trade_dollars = capital * weight
        dv = dollar_volumes.get(ticker, 0)
        participation = (trade_dollars / dv * stress_factor) if dv > 0 else None

        ret = forward_returns.get(ticker) if forward_returns else None
        pnl_contribution = weight * ret if ret is not None else None

        trades.append(
            {
                "ticker": ticker,
                "weight": round(weight, 4),
                "trade_dollars": round(trade_dollars, 0),
                "dollar_volume": round(dv, 0) if dv else None,
                "participation": round(participation, 4) if participation is not None else None,
                "forward_return": round(ret, 4) if ret is not None else None,
                "pnl_contribution": round(pnl_contribution, 6) if pnl_contribution is not None else None,
            }
        )

    # Sort by participation (worst first)
    with_participation = [t for t in trades if t["participation"] is not None]
    with_participation.sort(key=lambda t: t["participation"], reverse=True)

    # Tail concentration: capital in top 3 highest-participation trades
    top3_weight = sum(t["weight"] for t in with_participation[:3])

    # Trades above thresholds
    n_above_5 = sum(1 for t in with_participation if t["participation"] > 0.05)
    n_above_10 = sum(1 for t in with_participation if t["participation"] > 0.10)
    n_above_20 = sum(1 for t in with_participation if t["participation"] > 0.20)

    # PnL attribution (if returns available)
    pnl_before_guardrails = None
    pnl_after_guardrails = None
    if forward_returns:
        pnl_before = sum(t["pnl_contribution"] for t in trades if t["pnl_contribution"] is not None)
        pnl_before_guardrails = round(pnl_before * 100, 4)

        # Simulate guardrails: skip >20%, scale >5%
        pnl_after = 0.0
        total_adj_w = 0.0
        for t in trades:
            p = t["participation"]
            ret = t["forward_return"]
            w = t["weight"]
            if p is None or p > 0.20:
                continue  # skipped
            if p > 0.05:
                w = w * (0.05 / p)  # scaled
            total_adj_w += w
            if ret is not None:
                pnl_after += w * ret

        if total_adj_w > 0:
            pnl_after = pnl_after / total_adj_w  # re-normalized
            pnl_after_guardrails = round(pnl_after * 100, 4)

    return {
        "stress_factor": stress_factor,
        "n_positions": len(trades),
        "top_10_stress": with_participation[:10],
        "tail_concentration": {
            "top3_participation_weight_pct": round(top3_weight * 100, 1),
            "n_above_5pct_adv": n_above_5,
            "n_above_10pct_adv": n_above_10,
            "n_above_20pct_adv": n_above_20,
        },
        "pnl_before_guardrails_pct": pnl_before_guardrails,
        "pnl_after_guardrails_pct": pnl_after_guardrails,
    }
