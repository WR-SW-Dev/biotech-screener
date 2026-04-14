#!/usr/bin/env python3
"""Backtest: Conditional Gap Score — PIT-safe validation.

Recomputes conditional model scores on-the-fly from historical snapshot
raw columns + trial_records.json, then validates against forward returns
from price_history.csv.

Tests:
  1. Standalone IC by horizon (21d, 42d, 63d)
  2. Incremental FM regression: future_return ~ trap + conditional_gap
  3. Subgroup validation: selected vs unselected, validated vs novel
  4. Bucket sparsity report: n per bucket, shrinkage usage rate
  5. Decile spread (top vs bottom bucket returns)

Success threshold:
  - Positive PIT-safe incremental value after trap
  - Not just correlated with trap

Usage:
    cd /mnt/c/Projects/biotech_screener/biotech-screener
    python -m scripts.research.backtest_conditional_gap
    python -m scripts.research.backtest_conditional_gap --horizon 42 --output results.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import statistics
import sys
from collections import defaultdict
from datetime import date as dt_date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════
# Paths
# ═════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots_pit_v2"
DEFAULT_PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
DEFAULT_TRIAL_RECORDS = PROJECT_ROOT / "production_data" / "trial_records.json"

# ═════════════════════════════════════════════════════════════════════════
# Utilities
# ═════════════════════════════════════════════════════════════════════════


def _sf(v: Any) -> Optional[float]:
    """Safe float extraction."""
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _avg_ranks(values: List[float]) -> List[float]:
    """Average-rank with tie handling (1-based)."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[indexed[j + 1]] == values[indexed[j]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def _spearman_ic(signal: List[float], returns: List[float]) -> Optional[float]:
    """Spearman rank correlation. Returns None if n < 5."""
    n = len(signal)
    if n < 5 or len(returns) != n:
        return None
    rx = _avg_ranks(signal)
    ry = _avg_ranks(returns)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    sx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    sy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if sx < 1e-12 or sy < 1e-12:
        return None
    return cov / (sx * sy)


def _pearson(x: List[float], y: List[float]) -> Optional[float]:
    n = len(x)
    if n < 5 or len(y) != n:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if sx < 1e-12 or sy < 1e-12:
        return None
    return cov / (sx * sy)


def _t_stat_from_ics(ics: List[float]) -> float:
    """Fama-MacBeth t-stat: mean(IC) / (std(IC) / sqrt(n))."""
    if len(ics) < 3:
        return 0.0
    m = statistics.mean(ics)
    s = statistics.stdev(ics)
    if s < 1e-12:
        return 0.0
    return m / (s / math.sqrt(len(ics)))


def _ic_summary(ics: List[float]) -> Dict[str, Any]:
    if not ics:
        return {"mean_ic": None, "t_stat": 0.0, "hit_rate": 0.0, "n_periods": 0}
    m = statistics.mean(ics)
    t = _t_stat_from_ics(ics)
    hr = sum(1 for ic in ics if ic > 0) / len(ics)
    return {
        "mean_ic": round(m, 4),
        "t_stat": round(t, 2),
        "hit_rate": round(hr, 3),
        "n_periods": len(ics),
    }


# ═════════════════════════════════════════════════════════════════════════
# Data loaders
# ═════════════════════════════════════════════════════════════════════════


def _discover_snapshot_dates(snapshots_dir: Path) -> List[str]:
    """Return sorted YYYY-MM-DD snapshot date strings."""
    dates = []
    for d in sorted(snapshots_dir.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if len(name) != 10 or name[4] != "-" or name[7] != "-":
            continue
        try:
            dt_date.fromisoformat(name)
        except ValueError:
            continue
        dates.append(name)
    return dates


def _load_snapshot(snapshots_dir: Path, snap_date: str) -> List[Dict[str, Any]]:
    csv_path = snapshots_dir / snap_date / "rankings.csv"
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_prices(price_csv: Path) -> Dict[str, Dict[str, float]]:
    """Load price_history.csv -> {ticker: {date_str: close}}."""
    series: Dict[str, Dict[str, float]] = {}
    with open(price_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("ticker", "")
            d = row.get("date", "")
            c = row.get("close", "")
            if t and d and c:
                try:
                    series.setdefault(t, {})[d] = float(c)
                except (ValueError, TypeError):
                    pass
    logger.info("Loaded prices for %d tickers", len(series))
    return series


def _resolve_trade_date(sorted_dates: List[str], snap_date: str) -> Optional[str]:
    """First trading date AFTER snap_date (PIT-safe: trade after info)."""
    for d in sorted_dates:
        if d > snap_date:
            return d
    return None


def _forward_return(
    ticker_prices: Dict[str, float],
    sorted_dates: List[str],
    trade_date: str,
    horizon: int,
) -> Optional[float]:
    """Return from trade_date to trade_date + horizon trading days."""
    try:
        idx = sorted_dates.index(trade_date)
    except ValueError:
        return None
    end_idx = idx + horizon
    if end_idx >= len(sorted_dates):
        return None
    p0 = ticker_prices.get(sorted_dates[idx])
    p1 = ticker_prices.get(sorted_dates[end_idx])
    if p0 and p1 and p0 > 0:
        return (p1 / p0) - 1.0
    return None


# ═════════════════════════════════════════════════════════════════════════
# On-the-fly scoring
# ═════════════════════════════════════════════════════════════════════════


def _score_snapshot(
    rows: List[Dict[str, Any]],
    snap_date: str,
    cond_model: Any,
    ees_model: Any,
) -> List[Dict[str, Any]]:
    """Recompute conditional + EES scores for a snapshot's rows.

    Returns enriched records with conditional_gap_score, trap_overlay_score, etc.
    """
    # Compute EES scores (need cross-sectional SI anchors)
    ees_scores = ees_model.score_batch(rows, snap_date)
    ees_map = {s.ticker: s for s in ees_scores}

    # Compute conditional scores
    cond_scores = cond_model.score_batch(rows, snap_date)
    cond_map = {s.ticker: s for s in cond_scores}

    enriched = []
    for row in rows:
        tk = row.get("ticker", "")
        cond = cond_map.get(tk)
        ees = ees_map.get(tk)

        enriched.append(
            {
                "ticker": tk,
                # Conditional model
                "conditional_gap_score": cond.conditional_gap_score if cond else 0.0,
                "conditional_base_rate": cond.conditional_base_rate if cond else 0.0,
                "conditional_expected_move": cond.conditional_expected_move if cond else 0.0,
                "conditional_confidence": cond.conditional_confidence if cond else 0.0,
                "conditional_bucket": cond.conditional_bucket if cond else "",
                "fallback_level": cond.fallback_level if cond else 3,
                "shrinkage_applied": cond.shrinkage_applied if cond else 1.0,
                "bucket_n": cond.bucket_n if cond else 0,
                # EES trap
                "trap_overlay_score": ees.trap_overlay_score if ees else 0.0,
                "quality_overlay_score": ees.quality_overlay_score if ees else 0.0,
                "ees_v2_score": ees.ees_v2_score if ees else 0.0,
            }
        )

    return enriched


# ═════════════════════════════════════════════════════════════════════════
# FM Incremental Regression
# ═════════════════════════════════════════════════════════════════════════


def _standardize(vals: List[float]) -> List[float]:
    """Z-score standardize. Returns zeros if degenerate."""
    if len(vals) < 3:
        return [0.0] * len(vals)
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    if s < 1e-12:
        return [0.0] * len(vals)
    return [(v - m) / s for v in vals]


def _ols_2var(y: List[float], x1: List[float], x2: List[float]) -> Tuple[float, float]:
    """Simple 2-variable OLS: y = a + b1*x1 + b2*x2. Returns (b1, b2).

    Uses normal equations with minimal dependencies.
    """
    n = len(y)
    if n < 5:
        return (0.0, 0.0)

    # Design matrix: X = [x1, x2] (no intercept — inputs are standardized)
    s11 = sum(x1[i] * x1[i] for i in range(n))
    s22 = sum(x2[i] * x2[i] for i in range(n))
    s12 = sum(x1[i] * x2[i] for i in range(n))
    sy1 = sum(y[i] * x1[i] for i in range(n))
    sy2 = sum(y[i] * x2[i] for i in range(n))

    det = s11 * s22 - s12 * s12
    if abs(det) < 1e-12:
        return (0.0, 0.0)

    b1 = (s22 * sy1 - s12 * sy2) / det
    b2 = (s11 * sy2 - s12 * sy1) / det
    return (b1, b2)


def _fm_incremental_regression(
    date_records: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Fama-MacBeth cross-sectional regression per date.

    Model: fwd_return = b1*trap + b2*conditional_gap (both standardized).
    Aggregates betas across dates.
    """
    b1_series: List[float] = []
    b2_series: List[float] = []

    for dt, records in sorted(date_records.items()):
        if len(records) < 10:
            continue

        rets = [r["fwd_return"] for r in records]
        traps = [r["trap_overlay_score"] for r in records]
        gaps = [r["conditional_gap_score"] for r in records]

        # Check signal has variation
        trap_uniq = len(set(round(t, 6) for t in traps))
        gap_uniq = len(set(round(g, 6) for g in gaps))
        if trap_uniq < 3 or gap_uniq < 3:
            continue

        rets_z = _standardize(rets)
        traps_z = _standardize(traps)
        gaps_z = _standardize(gaps)

        b1, b2 = _ols_2var(rets_z, traps_z, gaps_z)
        b1_series.append(b1)
        b2_series.append(b2)

    if len(b1_series) < 3:
        return {
            "trap_beta": None,
            "conditional_gap_beta": None,
            "trap_t_stat": 0.0,
            "conditional_gap_t_stat": 0.0,
            "n_periods": len(b1_series),
        }

    return {
        "trap_beta": round(statistics.mean(b1_series), 4),
        "conditional_gap_beta": round(statistics.mean(b2_series), 4),
        "trap_t_stat": round(_t_stat_from_ics(b1_series), 2),
        "conditional_gap_t_stat": round(_t_stat_from_ics(b2_series), 2),
        "n_periods": len(b1_series),
    }


# ═════════════════════════════════════════════════════════════════════════
# Decile spread
# ═════════════════════════════════════════════════════════════════════════


def _decile_spread(
    date_records: Dict[str, List[Dict[str, Any]]],
    signal_key: str,
) -> Dict[str, Any]:
    """Mean return of top decile minus bottom decile, aggregated across dates."""
    spreads: List[float] = []

    for dt, records in sorted(date_records.items()):
        if len(records) < 10:
            continue
        sorted_recs = sorted(records, key=lambda r: r[signal_key])
        n = len(sorted_recs)
        d = max(1, n // 10)
        bottom = sorted_recs[:d]
        top = sorted_recs[-d:]

        top_ret = statistics.mean(r["fwd_return"] for r in top)
        bot_ret = statistics.mean(r["fwd_return"] for r in bottom)
        spreads.append(top_ret - bot_ret)

    if not spreads:
        return {"mean_spread_pp": None, "t_stat": 0.0, "n_periods": 0}

    return {
        "mean_spread_pp": round(statistics.mean(spreads) * 100, 2),
        "t_stat": round(_t_stat_from_ics(spreads), 2),
        "hit_rate": round(sum(1 for s in spreads if s > 0) / len(spreads), 3),
        "n_periods": len(spreads),
    }


# ═════════════════════════════════════════════════════════════════════════
# Block bootstrap CI
# ═════════════════════════════════════════════════════════════════════════


def _block_bootstrap_ci(
    ics: List[float],
    n_boot: int = 2000,
    block_size: int = 5,
    ci: float = 0.95,
) -> Dict[str, Any]:
    """Block bootstrap confidence interval for mean IC."""
    import random

    if len(ics) < block_size * 2:
        return {"ci_lower": None, "ci_upper": None, "excludes_zero": None}

    n = len(ics)
    n_blocks = max(1, n // block_size)
    boot_means: List[float] = []

    random.seed(42)
    for _ in range(n_boot):
        sample: List[float] = []
        for _ in range(n_blocks):
            start = random.randint(0, n - block_size)
            sample.extend(ics[start : start + block_size])
        boot_means.append(statistics.mean(sample[:n]))

    boot_means.sort()
    alpha = (1 - ci) / 2
    lo = boot_means[int(n_boot * alpha)]
    hi = boot_means[int(n_boot * (1 - alpha))]

    return {
        "ci_lower": round(lo, 4),
        "ci_upper": round(hi, 4),
        "excludes_zero": lo > 0 or hi < 0,
    }


# ═════════════════════════════════════════════════════════════════════════
# Effective sample size (autocorrelation adjustment)
# ═════════════════════════════════════════════════════════════════════════


def _effective_n(ics: List[float]) -> Dict[str, Any]:
    """Lag-1 autocorrelation adjusted effective sample size."""
    n = len(ics)
    if n < 5:
        return {"n_raw": n, "rho1": None, "n_eff": n, "t_adj": 0.0}

    m = statistics.mean(ics)
    demeaned = [ic - m for ic in ics]
    var = sum(d * d for d in demeaned) / n
    if var < 1e-12:
        return {"n_raw": n, "rho1": 0.0, "n_eff": n, "t_adj": 0.0}

    cov1 = sum(demeaned[i] * demeaned[i + 1] for i in range(n - 1)) / (n - 1)
    rho1 = cov1 / var

    # Effective n: n * (1 - rho1) / (1 + rho1)
    denom = 1 + rho1
    if denom < 0.1:
        denom = 0.1  # floor to avoid blowup
    n_eff = max(3, n * (1 - rho1) / denom)

    s = statistics.stdev(ics)
    t_adj = m / (s / math.sqrt(n_eff)) if s > 1e-12 else 0.0

    return {
        "n_raw": n,
        "rho1": round(rho1, 3),
        "n_eff": round(n_eff, 1),
        "t_adj": round(t_adj, 2),
    }


# ═════════════════════════════════════════════════════════════════════════
# Main backtest
# ═════════════════════════════════════════════════════════════════════════


def run_backtest(
    snapshots_dir: Path,
    price_csv: Path,
    trial_records_path: Path,
    horizon_days: int = 63,
) -> Dict[str, Any]:
    """Run full conditional gap backtest with on-the-fly scoring."""

    # ── Load models ─────────────────────────────────────────────────
    sys.path.insert(0, str(PROJECT_ROOT))
    from event_ev.conditional_model import ConditionalModel
    from event_ev.expectation_error_model import ExpectationErrorModel

    cond_model = ConditionalModel(trial_records_path=trial_records_path)
    ees_model = ExpectationErrorModel()

    # ── Load prices ─────────────────────────────────────────────────
    prices = _load_prices(price_csv)

    # Pre-compute sorted trading dates per ticker
    sorted_dates_by_ticker: Dict[str, List[str]] = {}
    for tk, px_map in prices.items():
        sorted_dates_by_ticker[tk] = sorted(px_map.keys())

    # ── Discover snapshots ──────────────────────────────────────────
    snap_dates = _discover_snapshot_dates(snapshots_dir)
    logger.info("Found %d snapshot dates", len(snap_dates))

    # ── Score + compute forward returns per date ────────────────────
    # Signals tested:
    #   - conditional_gap_score (primary: expected vs priced)
    #   - conditional_base_rate (secondary: raw base rate)
    #   - conditional_expected_move (secondary: weighted expected move)
    SIGNALS = [
        "conditional_gap_score",
        "conditional_base_rate",
        "conditional_expected_move",
    ]

    date_records: Dict[str, List[Dict[str, Any]]] = {}
    skipped_no_data = 0
    skipped_no_fwd = 0

    for snap_date in snap_dates:
        rows = _load_snapshot(snapshots_dir, snap_date)
        if not rows:
            skipped_no_data += 1
            continue

        # Recompute scores on-the-fly
        enriched = _score_snapshot(rows, snap_date, cond_model, ees_model)

        # Compute forward returns from price_history.csv
        records_with_fwd: List[Dict[str, Any]] = []
        for rec in enriched:
            tk = rec["ticker"]
            tk_dates = sorted_dates_by_ticker.get(tk)
            if not tk_dates:
                continue

            trade_date = _resolve_trade_date(tk_dates, snap_date)
            if not trade_date:
                continue

            fwd_ret = _forward_return(prices[tk], tk_dates, trade_date, horizon_days)
            if fwd_ret is None:
                continue

            rec["fwd_return"] = fwd_ret
            rec["trade_date"] = trade_date
            records_with_fwd.append(rec)

        if len(records_with_fwd) >= 10:
            date_records[snap_date] = records_with_fwd
        else:
            skipped_no_fwd += 1

    logger.info(
        "Scored %d dates with sufficient data (%d no-data, %d insufficient-fwd)",
        len(date_records),
        skipped_no_data,
        skipped_no_fwd,
    )

    if not date_records:
        return {"error": "no_data", "hint": "Check snapshot path and price_history.csv"}

    # ── 1. Standalone IC per signal ─────────────────────────────────
    signal_results: Dict[str, Dict[str, Any]] = {}

    for sig in SIGNALS:
        per_date_ic: List[float] = []
        for dt, records in sorted(date_records.items()):
            sigs = [r[sig] for r in records]
            rets = [r["fwd_return"] for r in records]

            # Check for degeneracy
            uniq = len(set(round(s, 6) for s in sigs))
            if uniq < 3:
                continue

            ic = _spearman_ic(sigs, rets)
            if ic is not None:
                per_date_ic.append(ic)

        signal_results[sig] = {
            "ic": _ic_summary(per_date_ic),
            "bootstrap_ci": _block_bootstrap_ci(per_date_ic),
            "effective_n": _effective_n(per_date_ic),
            "decile_spread": _decile_spread(date_records, sig),
        }

    # ── 2. Trap standalone IC (for comparison) ──────────────────────
    trap_ics: List[float] = []
    for dt, records in sorted(date_records.items()):
        traps = [r["trap_overlay_score"] for r in records]
        rets = [r["fwd_return"] for r in records]
        uniq = len(set(round(t, 6) for t in traps))
        if uniq < 3:
            continue
        ic = _spearman_ic(traps, rets)
        if ic is not None:
            trap_ics.append(ic)

    trap_standalone = _ic_summary(trap_ics)

    # ── 3. Gap-trap correlation ─────────────────────────────────────
    all_gaps: List[float] = []
    all_traps: List[float] = []
    for records in date_records.values():
        for r in records:
            all_gaps.append(r["conditional_gap_score"])
            all_traps.append(r["trap_overlay_score"])
    gap_trap_corr = _pearson(all_gaps, all_traps)

    # ── 4. FM Incremental regression ────────────────────────────────
    fm_regression = _fm_incremental_regression(date_records)

    # ── 5. Subgroup analysis ────────────────────────────────────────
    subgroup_pools: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for records in date_records.values():
        for r in records:
            bucket = r["conditional_bucket"]
            parts = bucket.split("|")

            # Selection status
            if len(parts) >= 3:
                sel = parts[2]
                subgroup_pools[f"sel_{sel}"].append((r["conditional_gap_score"], r["fwd_return"]))
            # Mechanism class
            if len(parts) >= 4:
                mech = parts[3]
                subgroup_pools[f"mech_{mech}"].append((r["conditional_gap_score"], r["fwd_return"]))
            # Event family
            if parts:
                subgroup_pools[f"fam_{parts[0]}"].append((r["conditional_gap_score"], r["fwd_return"]))
            # Phase
            if len(parts) >= 2:
                subgroup_pools[f"phase_{parts[1]}"].append((r["conditional_gap_score"], r["fwd_return"]))

    subgroup_ics: Dict[str, Dict[str, Any]] = {}
    for name, pairs in sorted(subgroup_pools.items()):
        if len(pairs) < 20:
            subgroup_ics[name] = {"n": len(pairs), "ic": None, "note": "insufficient"}
            continue
        gs, rs = zip(*pairs)
        sg_ic = _spearman_ic(list(gs), list(rs))
        subgroup_ics[name] = {
            "n": len(pairs),
            "ic": round(sg_ic, 4) if sg_ic is not None else None,
            "mean_return_pp": round(statistics.mean(rs) * 100, 2),
        }

    # ── 6. Bucket sparsity ──────────────────────────────────────────
    bucket_counts: Dict[str, int] = defaultdict(int)
    bucket_fallback_counts: Dict[int, int] = defaultdict(int)
    shrinkage_values: List[float] = []

    for records in date_records.values():
        for r in records:
            bucket_counts[r["conditional_bucket"]] += 1
            bucket_fallback_counts[r["fallback_level"]] += 1
            shrinkage_values.append(r["shrinkage_applied"])

    n_obs = sum(bucket_counts.values())
    sparse_buckets = {k: v for k, v in sorted(bucket_counts.items(), key=lambda x: x[1]) if v < 30}
    avg_shrinkage = statistics.mean(shrinkage_values) if shrinkage_values else 1.0

    # ── 7. LOSO half-year stability ─────────────────────────────────
    sorted_dates_list = sorted(date_records.keys())
    mid = len(sorted_dates_list) // 2
    halves = [sorted_dates_list[:mid], sorted_dates_list[mid:]]
    loso_results = []
    for half_idx, half_dates in enumerate(halves):
        half_ics: List[float] = []
        for dt in half_dates:
            records = date_records[dt]
            sigs = [r["conditional_gap_score"] for r in records]
            rets = [r["fwd_return"] for r in records]
            uniq = len(set(round(s, 6) for s in sigs))
            if uniq < 3:
                continue
            ic = _spearman_ic(sigs, rets)
            if ic is not None:
                half_ics.append(ic)
        loso_results.append(
            {
                "half": f"H{half_idx + 1}",
                "dates": f"{half_dates[0]} to {half_dates[-1]}" if half_dates else "empty",
                **_ic_summary(half_ics),
            }
        )

    # ── Assemble report ─────────────────────────────────────────────
    gap_ic = signal_results.get("conditional_gap_score", {}).get("ic", {})
    gap_mean_ic = gap_ic.get("mean_ic") or 0
    incr_t = fm_regression.get("conditional_gap_t_stat", 0)

    report = {
        "schema": "backtest_conditional_gap.v2",
        "horizon_days": horizon_days,
        "n_dates": len(date_records),
        "n_observations": n_obs,
        "date_range": {
            "first": sorted_dates_list[0] if sorted_dates_list else None,
            "last": sorted_dates_list[-1] if sorted_dates_list else None,
        },
        "signal_results": signal_results,
        "trap_standalone": trap_standalone,
        "gap_trap_correlation": round(gap_trap_corr, 4) if gap_trap_corr else None,
        "fm_incremental_regression": fm_regression,
        "subgroup_ics": subgroup_ics,
        "bucket_sparsity": {
            "total_buckets": len(bucket_counts),
            "sparse_buckets_lt30": len(sparse_buckets),
            "avg_shrinkage": round(avg_shrinkage, 3),
            "fallback_distribution": {f"L{k}": v for k, v in sorted(bucket_fallback_counts.items())},
            "sparse_detail": sparse_buckets,
        },
        "loso_stability": loso_results,
        "pass_fail": {
            "standalone_ic_positive": gap_mean_ic > 0,
            "standalone_ic_significant": abs(gap_ic.get("t_stat", 0)) >= 1.96,
            "incremental_after_trap": (fm_regression.get("conditional_gap_beta") or 0) > 0,
            "incremental_t_significant": abs(incr_t) >= 1.65,
            "not_trap_proxy": abs(gap_trap_corr or 0) < 0.70,
            "sufficient_data": n_obs >= 500,
            "loso_both_halves_positive": all((h.get("mean_ic") or 0) > 0 for h in loso_results),
        },
    }

    return report


# ═════════════════════════════════════════════════════════════════════════
# Multi-horizon runner
# ═════════════════════════════════════════════════════════════════════════


def run_multi_horizon(
    snapshots_dir: Path,
    price_csv: Path,
    trial_records_path: Path,
    horizons: List[int] = (21, 42, 63),
) -> Dict[str, Any]:
    """Run backtest across multiple forward-return horizons."""
    results = {}
    for h in horizons:
        logger.info("═══ Horizon %dd ═══", h)
        results[f"{h}d"] = run_backtest(snapshots_dir, price_csv, trial_records_path, h)

    # Cross-horizon summary
    summary = {}
    for h_key, report in results.items():
        gap_ic = report.get("signal_results", {}).get("conditional_gap_score", {}).get("ic", {})
        fm = report.get("fm_incremental_regression", {})
        pf = report.get("pass_fail", {})
        summary[h_key] = {
            "mean_ic": gap_ic.get("mean_ic"),
            "t_stat": gap_ic.get("t_stat"),
            "incr_beta": fm.get("conditional_gap_beta"),
            "incr_t": fm.get("conditional_gap_t_stat"),
            "passes": sum(1 for v in pf.values() if v),
            "total_checks": len(pf),
        }

    return {"horizons": results, "summary": summary}


# ═════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest conditional gap score (PIT-safe, on-the-fly scoring)")
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=DEFAULT_SNAPSHOTS_DIR,
        help="Directory containing dated snapshot subdirectories",
    )
    parser.add_argument(
        "--prices",
        type=Path,
        default=DEFAULT_PRICE_CSV,
        help="Path to price_history.csv",
    )
    parser.add_argument(
        "--trials",
        type=Path,
        default=DEFAULT_TRIAL_RECORDS,
        help="Path to trial_records.json",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=None,
        help="Single forward return horizon in trading days (default: run 21/42/63)",
    )
    parser.add_argument("--output", type=Path, default=None, help="Output JSON path")
    args = parser.parse_args()

    if args.horizon:
        report = run_backtest(args.snapshots_dir, args.prices, args.trials, args.horizon)
    else:
        report = run_multi_horizon(args.snapshots_dir, args.prices, args.trials)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Report written to %s", args.output)
    else:
        print(json.dumps(report, indent=2, default=str))

    # ── Summary ─────────────────────────────────────────────────────
    if "summary" in report:
        # Multi-horizon mode
        print("\n" + "=" * 60)
        print("CONDITIONAL GAP — MULTI-HORIZON SUMMARY")
        print("=" * 60)
        for h_key, s in report["summary"].items():
            status = "PASS" if s["passes"] == s["total_checks"] else "FAIL"
            print(
                f"  {h_key}: IC={s['mean_ic'] or 'N/A':>7}  t={s['t_stat'] or 0:>5.1f}  "
                f"incr_beta={s['incr_beta'] or 'N/A':>7}  incr_t={s['incr_t'] or 0:>5.1f}  "
                f"[{s['passes']}/{s['total_checks']} {status}]"
            )
    else:
        # Single-horizon mode
        pf = report.get("pass_fail", {})
        passes = sum(1 for v in pf.values() if v)
        total = len(pf)
        print(f"\nPass/fail: {passes}/{total}")

        if not pf.get("sufficient_data"):
            logger.warning("INSUFFICIENT DATA")
        elif passes == total:
            logger.info("ALL CHECKS PASSED — conditional_gap_score is a promotion candidate")
        else:
            failed = [k for k, v in pf.items() if not v]
            logger.warning("FAILED: %s", ", ".join(failed))


if __name__ == "__main__":
    main()
