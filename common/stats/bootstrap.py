"""Block bootstrap and stationary bootstrap for portfolio returns.

Provides bootstrapped confidence intervals, P(strategy > 0), and
P(challenger > baseline) for portfolio backtests.

Usage:
    from common.stats.bootstrap import block_bootstrap, compare_strategies

    result = block_bootstrap(monthly_returns, block_length=6, n_bootstrap=10000)
    comparison = compare_strategies(returns_a, returns_b, block_length=6)
"""

from __future__ import annotations

from typing import Any

import numpy as np


def block_bootstrap(
    returns: list[float] | np.ndarray,
    block_length: int = 6,
    n_bootstrap: int = 10000,
    confidence_level: float = 0.95,
    seed: int = 42,
) -> dict[str, Any]:
    """Moving block bootstrap on a return series.

    Resamples contiguous blocks of length `block_length` to preserve
    serial dependence. Computes bootstrapped mean, CI, and P(mean > 0).

    Args:
        returns: monthly return series
        block_length: length of each resampled block
        n_bootstrap: number of bootstrap replications
        confidence_level: for confidence interval (default 95%)
        seed: random seed for reproducibility

    Returns:
        dict with boot_mean, ci_lower, ci_upper, prob_positive, n_obs
    """
    returns = np.asarray(returns, dtype=float)
    T = len(returns)
    if T < block_length:
        return {"error": f"series length {T} < block_length {block_length}"}

    rng = np.random.default_rng(seed)
    n_blocks = max(1, int(np.ceil(T / block_length)))
    n_starts = T - block_length + 1

    boot_means = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        # Sample block start indices
        starts = rng.integers(0, n_starts, size=n_blocks)
        # Concatenate blocks
        sample = np.concatenate([returns[s : s + block_length] for s in starts])[:T]  # trim to original length
        boot_means[b] = np.mean(sample)

    alpha = 1 - confidence_level
    ci_lower = float(np.percentile(boot_means, 100 * alpha / 2))
    ci_upper = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))
    prob_positive = float(np.mean(boot_means > 0))

    return {
        "original_mean": _round(float(np.mean(returns))),
        "boot_mean": _round(float(np.mean(boot_means))),
        "boot_se": _round(float(np.std(boot_means))),
        "ci_lower": _round(ci_lower),
        "ci_upper": _round(ci_upper),
        "prob_positive": _round(prob_positive),
        "confidence_level": confidence_level,
        "n_obs": T,
        "block_length": block_length,
        "n_bootstrap": n_bootstrap,
        "ci_excludes_zero": (ci_lower > 0 or ci_upper < 0),
    }


def stationary_bootstrap(
    returns: list[float] | np.ndarray,
    mean_block_length: float = 6.0,
    n_bootstrap: int = 10000,
    confidence_level: float = 0.95,
    seed: int = 42,
) -> dict[str, Any]:
    """Stationary bootstrap (Politis & Romano 1994).

    Like block bootstrap but with random block lengths drawn from
    a geometric distribution, producing stationary resampled series.

    Args:
        returns: monthly return series
        mean_block_length: expected block length (1/p for geometric dist)
        n_bootstrap: number of bootstrap replications
        confidence_level: for confidence interval
        seed: random seed

    Returns:
        dict with bootstrap stats
    """
    returns = np.asarray(returns, dtype=float)
    T = len(returns)
    if T < 3:
        return {"error": f"series too short (T={T})"}

    rng = np.random.default_rng(seed)
    p = 1.0 / mean_block_length  # probability of starting a new block

    boot_means = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        sample = np.empty(T)
        idx = rng.integers(0, T)
        for t in range(T):
            sample[t] = returns[idx % T]
            if rng.random() < p:
                idx = rng.integers(0, T)
            else:
                idx += 1
        boot_means[b] = np.mean(sample)

    alpha = 1 - confidence_level
    ci_lower = float(np.percentile(boot_means, 100 * alpha / 2))
    ci_upper = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))
    prob_positive = float(np.mean(boot_means > 0))

    return {
        "original_mean": _round(float(np.mean(returns))),
        "boot_mean": _round(float(np.mean(boot_means))),
        "boot_se": _round(float(np.std(boot_means))),
        "ci_lower": _round(ci_lower),
        "ci_upper": _round(ci_upper),
        "prob_positive": _round(prob_positive),
        "confidence_level": confidence_level,
        "n_obs": T,
        "mean_block_length": mean_block_length,
        "n_bootstrap": n_bootstrap,
        "ci_excludes_zero": (ci_lower > 0 or ci_upper < 0),
    }


def compare_strategies(
    returns_a: list[float] | np.ndarray,
    returns_b: list[float] | np.ndarray,
    labels: tuple[str, str] = ("strategy_a", "strategy_b"),
    block_length: int = 6,
    n_bootstrap: int = 10000,
    confidence_level: float = 0.95,
    seed: int = 42,
) -> dict[str, Any]:
    """Compare two strategies using block bootstrap on the difference series.

    Tests P(A > B) using the bootstrapped distribution of (A - B).

    Args:
        returns_a, returns_b: matched monthly return series (same length)
        labels: names for the two strategies
        block_length, n_bootstrap, confidence_level, seed: bootstrap params

    Returns:
        dict with comparison stats, P(A > B), CI on difference
    """
    a = np.asarray(returns_a, dtype=float)
    b = np.asarray(returns_b, dtype=float)

    if len(a) != len(b):
        return {"error": f"series length mismatch: {len(a)} vs {len(b)}"}

    diff = a - b
    diff_boot = block_bootstrap(
        diff,
        block_length=block_length,
        n_bootstrap=n_bootstrap,
        confidence_level=confidence_level,
        seed=seed,
    )

    return {
        "label_a": labels[0],
        "label_b": labels[1],
        "mean_a": _round(float(np.mean(a))),
        "mean_b": _round(float(np.mean(b))),
        "mean_diff": _round(float(np.mean(diff))),
        "diff_ci_lower": diff_boot.get("ci_lower"),
        "diff_ci_upper": diff_boot.get("ci_upper"),
        "prob_a_better": diff_boot.get("prob_positive"),
        "ci_excludes_zero": diff_boot.get("ci_excludes_zero"),
        "n_obs": len(a),
        "block_length": block_length,
        "n_bootstrap": n_bootstrap,
    }


def _round(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    return round(v, d)
