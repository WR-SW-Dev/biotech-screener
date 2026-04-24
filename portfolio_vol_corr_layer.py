"""Portfolio volatility and correlation layer.

Computes portfolio-level volatility and return-based correlation metrics
for the risk layer (C6: vol targeting, C7: correlation cluster limit).

Stdlib-only. Reuses common.clustering for pairwise correlations and
connected-component clustering.

Inputs:
    - price_history.csv (daily OHLCV)
    - Portfolio tickers + weights

Outputs:
    - VolCorrSnapshot dataclass consumed by portfolio_risk_layer.apply_risk_layer()
      and tools/build_risk_monitor.py
"""

from __future__ import annotations

import csv
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from common.clustering import (
    DEFAULT_CORR_THRESHOLD,
    build_corr_clusters,
    compute_cluster_stats,
    compute_correlation,
    compute_pairwise_correlations,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Data contracts
# ─────────────────────────────────────────────────────────────────────


@dataclass
class VolCorrSnapshot:
    """Pre-computed vol and correlation metrics for the risk layer."""

    # Portfolio vol
    portfolio_vol_annualized: float
    gross_exposure_scalar: float  # min(1.0, target / vol)
    vol_target: float
    vol_breach: bool  # vol > target

    # Correlation clusters
    correlation_clusters: Dict[str, int] = field(default_factory=dict)
    cluster_sizes: Dict[int, int] = field(default_factory=dict)
    max_cluster_size: int = 0
    avg_pairwise_corr: float = 0.0
    high_corr_pairs: List[Tuple[str, str, float]] = field(default_factory=list)

    # Coverage / diagnostics
    lookback_days: int = 60
    n_tickers_with_data: int = 0
    n_tickers_imputed: int = 0


# ─────────────────────────────────────────────────────────────────────
# Price / return loading
# ─────────────────────────────────────────────────────────────────────


def load_returns_from_csv(
    price_csv_path: Path,
    tickers: List[str],
    lookback_days: int = 60,
    as_of_date: Optional[str] = None,
) -> Tuple[Dict[str, List[Optional[float]]], List[str]]:
    """Load daily log returns aligned by date.

    Returns:
        (returns_by_ticker, dates) where returns_by_ticker maps
        ticker -> list of daily log returns (None for missing days),
        and dates is the sorted list of trading dates in the window.
    """
    ticker_set = set(tickers)

    # Parse as_of
    if as_of_date:
        cutoff = datetime.strptime(as_of_date, "%Y-%m-%d").date()
    else:
        cutoff = date.today()

    # We need lookback_days of *returns*, so load lookback_days + 1 prices
    earliest = cutoff - timedelta(days=int(lookback_days * 2.0))

    # Read prices: {ticker: {date_str: close}}
    prices: Dict[str, Dict[str, float]] = {t: {} for t in tickers}
    all_dates: set = set()

    with open(price_csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tk = row.get("ticker", "").strip()
            if tk not in ticker_set:
                continue
            dt_str = row.get("date", "").strip()
            if not dt_str:
                continue
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if dt < earliest or dt > cutoff:
                continue
            try:
                close = float(row["close"])
            except (KeyError, ValueError):
                continue
            if close > 0:
                prices[tk][dt_str] = close
                all_dates.add(dt_str)

    # Sort dates descending, take the most recent lookback_days + 1
    sorted_dates = sorted(all_dates, reverse=True)[: lookback_days + 1]
    sorted_dates.reverse()  # ascending

    if len(sorted_dates) < 2:
        return {t: [] for t in tickers}, []

    # Compute log returns for each date pair
    return_dates = sorted_dates[1:]  # N-1 return dates
    returns_by_ticker: Dict[str, List[Optional[float]]] = {}

    for tk in tickers:
        tk_prices = prices.get(tk, {})
        rets: List[Optional[float]] = []
        for i in range(1, len(sorted_dates)):
            prev_dt = sorted_dates[i - 1]
            curr_dt = sorted_dates[i]
            p0 = tk_prices.get(prev_dt)
            p1 = tk_prices.get(curr_dt)
            if p0 and p1 and p0 > 0 and p1 > 0:
                rets.append(math.log(p1 / p0))
            else:
                rets.append(None)
        returns_by_ticker[tk] = rets

    return returns_by_ticker, return_dates


# ─────────────────────────────────────────────────────────────────────
# Portfolio vol estimation
# ─────────────────────────────────────────────────────────────────────


def _ticker_vol(returns: List[Optional[float]], min_obs: int = 10) -> Optional[float]:
    """Annualized volatility for a single ticker."""
    clean = [r for r in returns if r is not None]
    if len(clean) < min_obs:
        return None
    mean = sum(clean) / len(clean)
    var = sum((r - mean) ** 2 for r in clean) / len(clean)
    if var <= 1e-20:
        return None
    return math.sqrt(var * 252)


def compute_portfolio_vol(
    returns_by_ticker: Dict[str, List[Optional[float]]],
    weights: Dict[str, float],
    min_overlap: int = 30,
    default_imputed_corr: float = 0.50,
) -> Tuple[float, int]:
    """Estimate annualized portfolio volatility from return covariance.

    For each pair (i, j):
        cov(i,j) = corr(i,j) * vol(i) * vol(j)

    Portfolio variance:
        sigma_p^2 = sum_i sum_j w_i * w_j * cov(i,j)

    Args:
        returns_by_ticker: {ticker: [daily_log_returns]}
        weights: {ticker: weight} (should sum to ~1.0)
        min_overlap: Minimum overlapping obs for pairwise correlation
        default_imputed_corr: Correlation used when data is insufficient

    Returns:
        (annualized_portfolio_vol, n_imputed_tickers)
    """
    tickers = sorted(weights.keys())
    n = len(tickers)
    if n == 0:
        return 0.0, 0

    # Step 1: individual vols
    vols: Dict[str, Optional[float]] = {}
    for tk in tickers:
        rets = returns_by_ticker.get(tk, [])
        vols[tk] = _ticker_vol(rets)

    # Impute missing vols with median of observed vols (75th pctl as conservative)
    observed_vols = sorted([v for v in vols.values() if v is not None])
    if not observed_vols:
        return 0.0, n  # No data at all

    # Use 75th percentile as conservative impute for biotech
    p75_idx = min(int(len(observed_vols) * 0.75), len(observed_vols) - 1)
    impute_vol = observed_vols[p75_idx]

    n_imputed = 0
    for tk in tickers:
        if vols[tk] is None:
            vols[tk] = impute_vol
            n_imputed += 1

    # Step 2: pairwise correlations
    corr_cache: Dict[Tuple[str, str], float] = {}
    for i, t_a in enumerate(tickers):
        rets_a = returns_by_ticker.get(t_a, [])
        for t_b in tickers[i + 1 :]:
            rets_b = returns_by_ticker.get(t_b, [])
            c = compute_correlation(rets_a, rets_b, min_overlap)
            if c is not None:
                corr_cache[(t_a, t_b)] = c
                corr_cache[(t_b, t_a)] = c
            else:
                # Impute
                corr_cache[(t_a, t_b)] = default_imputed_corr
                corr_cache[(t_b, t_a)] = default_imputed_corr

    # Step 3: portfolio variance = w^T Cov w
    port_var = 0.0
    for i, t_i in enumerate(tickers):
        w_i = weights.get(t_i, 0.0)
        v_i = vols[t_i]
        for t_j in tickers:
            w_j = weights.get(t_j, 0.0)
            v_j = vols[t_j]
            if t_i == t_j:
                corr_ij = 1.0
            else:
                corr_ij = corr_cache.get((t_i, t_j), default_imputed_corr)
            # cov(i,j) = corr * vol_i * vol_j / 252 (daily) then * 252 for annualized
            # Actually: vol is already annualized, so cov_annual = corr * vol_i * vol_j
            port_var += w_i * w_j * corr_ij * v_i * v_j

    port_vol = math.sqrt(max(port_var, 0.0))
    return port_vol, n_imputed


# ─────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────


def build_vol_corr_snapshot(
    price_csv_path: Path,
    portfolio_tickers: List[str],
    weights: Dict[str, float],
    vol_target: float = 0.50,
    corr_threshold: float = DEFAULT_CORR_THRESHOLD,
    lookback_days: int = 60,
    as_of_date: Optional[str] = None,
    min_overlap: int = 30,
    default_imputed_corr: float = 0.50,
) -> VolCorrSnapshot:
    """Compute all vol/corr metrics for a portfolio.

    Args:
        price_csv_path: Path to price_history.csv
        portfolio_tickers: Tickers currently in portfolio
        weights: {ticker: weight} (should sum to ~1.0)
        vol_target: Annualized vol target (e.g. 0.50 for 50%)
        corr_threshold: Correlation threshold for clustering
        lookback_days: Trading days of return history
        as_of_date: YYYY-MM-DD cutoff (None = today)
        min_overlap: Min overlapping obs for pairwise correlation
        default_imputed_corr: Correlation imputed for insufficient data

    Returns:
        VolCorrSnapshot with all metrics populated
    """
    # Load returns
    returns_by_ticker, return_dates = load_returns_from_csv(
        price_csv_path, portfolio_tickers, lookback_days, as_of_date
    )

    n_with_data = sum(1 for tk in portfolio_tickers if _ticker_vol(returns_by_ticker.get(tk, [])) is not None)

    # Portfolio vol
    port_vol, n_imputed = compute_portfolio_vol(returns_by_ticker, weights, min_overlap, default_imputed_corr)

    # Vol target scalar
    if port_vol > 0 and vol_target > 0:
        scalar = min(1.0, vol_target / port_vol)
    else:
        scalar = 1.0
    vol_breach = port_vol > vol_target

    # Correlation clustering (reuse clustering.py)
    corr_pairs = compute_pairwise_correlations(returns_by_ticker, tickers=portfolio_tickers, min_overlap=min_overlap)

    cluster_map = build_corr_clusters(portfolio_tickers, corr_pairs, threshold=corr_threshold)
    cluster_stats = compute_cluster_stats(cluster_map)
    cluster_sizes = {cid: info["size"] for cid, info in cluster_stats.items()}
    max_cluster = max(cluster_sizes.values()) if cluster_sizes else 0

    # High-corr pairs (above threshold)
    high_pairs = sorted(
        [(a, b, c) for a, b, c in corr_pairs if c >= corr_threshold],
        key=lambda x: -x[2],
    )

    # Average pairwise correlation
    if corr_pairs:
        avg_corr = sum(c for _, _, c in corr_pairs) / len(corr_pairs)
    else:
        avg_corr = 0.0

    snapshot = VolCorrSnapshot(
        portfolio_vol_annualized=round(port_vol, 4),
        gross_exposure_scalar=round(scalar, 4),
        vol_target=vol_target,
        vol_breach=vol_breach,
        correlation_clusters=cluster_map,
        cluster_sizes=cluster_sizes,
        max_cluster_size=max_cluster,
        avg_pairwise_corr=round(avg_corr, 4),
        high_corr_pairs=high_pairs[:20],  # top 20 for diagnostics
        lookback_days=lookback_days,
        n_tickers_with_data=n_with_data,
        n_tickers_imputed=n_imputed,
    )

    logger.info(
        "VolCorrSnapshot: vol=%.1f%%, target=%.1f%%, scalar=%.3f, "
        "clusters=%d (max=%d), avg_corr=%.2f, imputed=%d/%d",
        port_vol * 100,
        vol_target * 100,
        scalar,
        len(cluster_stats),
        max_cluster,
        avg_corr,
        n_imputed,
        len(portfolio_tickers),
    )

    return snapshot
