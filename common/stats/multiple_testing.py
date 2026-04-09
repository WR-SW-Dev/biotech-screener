"""Multiple-testing correction framework.

Provides Benjamini-Hochberg FDR and White's Reality Check for families
of hypothesis tests in signal mining.

Usage:
    from common.stats.multiple_testing import benjamini_hochberg, whites_reality_check

    adjusted = benjamini_hochberg(raw_p_values, alpha=0.10)
    wrc = whites_reality_check(test_statistics, n_bootstrap=10000)
"""

from __future__ import annotations

from typing import Any

import numpy as np


def benjamini_hochberg(
    p_values: dict[str, float] | list[float],
    alpha: float = 0.10,
) -> dict[str, Any]:
    """Benjamini-Hochberg FDR correction.

    Controls the expected proportion of false discoveries at level alpha.

    Args:
        p_values: either {name: p_value} dict or list of p_values
        alpha: FDR level (default 0.10)

    Returns:
        dict with adjusted p-values (q-values), rejected set, summary
    """
    # Normalize input
    if isinstance(p_values, dict):
        names = list(p_values.keys())
        pvals = np.array([p_values[n] for n in names])
    else:
        pvals = np.array(p_values)
        names = [f"test_{i}" for i in range(len(pvals))]

    m = len(pvals)
    if m == 0:
        return {"error": "no p-values provided"}

    # Sort by p-value
    order = np.argsort(pvals)
    sorted_pvals = pvals[order]

    # BH procedure: q_i = p_i * m / rank_i, then enforce monotonicity
    ranks = np.arange(1, m + 1)
    q_values = np.minimum(sorted_pvals * m / ranks, 1.0)

    # Enforce monotonicity (cumulative min from the end)
    for i in range(m - 2, -1, -1):
        q_values[i] = min(q_values[i], q_values[i + 1])

    # Build results in original order
    results = {}
    for i, idx in enumerate(order):
        name = names[idx]
        results[name] = {
            "raw_p": _round(float(pvals[idx])),
            "q_value": _round(float(q_values[i])),
            "rank": int(i + 1),
            "rejected": bool(q_values[i] <= alpha),
        }

    n_rejected = sum(1 for v in results.values() if v["rejected"])

    return {
        "method": "benjamini_hochberg",
        "alpha": alpha,
        "n_tests": m,
        "n_rejected": n_rejected,
        "results": results,
        "rejected_names": [n for n, v in results.items() if v["rejected"]],
    }


def whites_reality_check(
    test_stats: dict[str, list[float]],
    n_bootstrap: int = 10000,
    block_length: int = 6,
    seed: int = 42,
) -> dict[str, Any]:
    """White's Reality Check (2000) for multiple strategy comparison.

    Tests whether the best strategy's performance is significantly better
    than the benchmark, accounting for data snooping across all strategies.

    Args:
        test_stats: {strategy_name: [monthly_excess_returns]}
            Each list is the same length (matched time periods).
        n_bootstrap: number of bootstrap replications
        block_length: for block bootstrap
        seed: random seed

    Returns:
        dict with max-stat distribution, p-value for best strategy
    """
    names = list(test_stats.keys())
    if not names:
        return {"error": "no strategies provided"}

    # Stack into matrix: (T, K)
    T = len(test_stats[names[0]])
    for name in names:
        if len(test_stats[name]) != T:
            return {"error": f"strategy {name} length mismatch"}

    data = np.array([test_stats[n] for n in names]).T  # (T, K)
    K = len(names)

    # Observed mean excess returns
    observed_means = np.mean(data, axis=0)  # (K,)
    observed_max = float(np.max(observed_means))
    best_idx = int(np.argmax(observed_means))

    # Block bootstrap under the null (demean each strategy)
    demeaned = data - observed_means  # center under null
    rng = np.random.default_rng(seed)
    n_starts = T - block_length + 1
    if n_starts < 1:
        return {"error": f"T={T} too short for block_length={block_length}"}
    n_blocks = max(1, int(np.ceil(T / block_length)))

    boot_max_stats = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        starts = rng.integers(0, n_starts, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_length) for s in starts])[:T]
        boot_sample = demeaned[indices]  # (T, K)
        boot_means = np.mean(boot_sample, axis=0)
        boot_max_stats[b] = np.max(boot_means)

    # p-value: fraction of bootstrap max-stats >= observed max
    p_value = float(np.mean(boot_max_stats >= observed_max))

    return {
        "method": "whites_reality_check",
        "n_strategies": K,
        "n_periods": T,
        "n_bootstrap": n_bootstrap,
        "block_length": block_length,
        "best_strategy": names[best_idx],
        "best_mean": _round(observed_max),
        "all_means": {names[i]: _round(float(observed_means[i])) for i in range(K)},
        "wrc_p_value": _round(p_value),
        "significant_at_05": p_value < 0.05,
        "significant_at_10": p_value < 0.10,
    }


def hansen_spa(
    benchmark_returns: list[float] | np.ndarray,
    strategy_returns: dict[str, list[float]],
    n_bootstrap: int = 10000,
    block_length: int = 6,
    seed: int = 42,
) -> dict[str, Any]:
    """Hansen's Superior Predictive Ability (SPA) test.

    More powerful than White's RC by recentering only strategies with
    positive sample means.

    Args:
        benchmark_returns: benchmark return series
        strategy_returns: {name: return_series} for challengers
        n_bootstrap, block_length, seed: bootstrap parameters

    Returns:
        dict with SPA p-values for each strategy
    """
    bench = np.asarray(benchmark_returns)
    T = len(bench)
    names = list(strategy_returns.keys())
    K = len(names)

    # Compute excess over benchmark
    excess = {}
    for name in names:
        s = np.asarray(strategy_returns[name])
        if len(s) != T:
            return {"error": f"length mismatch for {name}"}
        excess[name] = s - bench

    excess_matrix = np.array([excess[n] for n in names]).T  # (T, K)
    obs_means = np.mean(excess_matrix, axis=0)
    obs_max = float(np.max(obs_means))

    # SPA recentering: only demean strategies with negative means
    centered = excess_matrix.copy()
    for k in range(K):
        if obs_means[k] > 0:
            centered[:, k] -= obs_means[k]
        # strategies with negative means: already centered (they're under null)

    rng = np.random.default_rng(seed)
    n_starts = T - block_length + 1
    if n_starts < 1:
        return {"error": "T too short"}
    n_blocks = max(1, int(np.ceil(T / block_length)))

    boot_max = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        starts = rng.integers(0, n_starts, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_length) for s in starts])[:T]
        boot_means = np.mean(centered[indices], axis=0)
        boot_max[b] = np.max(boot_means)

    p_value = float(np.mean(boot_max >= obs_max))

    return {
        "method": "hansen_spa",
        "n_strategies": K,
        "n_periods": T,
        "best_strategy": names[int(np.argmax(obs_means))],
        "best_excess": _round(obs_max),
        "spa_p_value": _round(p_value),
        "significant_at_05": p_value < 0.05,
        "significant_at_10": p_value < 0.10,
        "strategy_means": {names[i]: _round(float(obs_means[i])) for i in range(K)},
    }


def _round(v, d=4):
    if v is None:
        return None
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    return round(v, d)
