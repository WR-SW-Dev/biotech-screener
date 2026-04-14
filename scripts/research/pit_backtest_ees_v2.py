#!/usr/bin/env python3
"""PIT Backtest: Updated EES + Conditional Model — strict point-in-time integrity.

Recomputes all EES and conditional model scores on-the-fly from historical
PIT snapshots. Uses only data available as of each snapshot date.

Key design:
  - If priced_move_pct is missing → EES components requiring it are NaN (not backfilled)
  - Forward returns from price_history.csv with next-trading-day anchor
  - Event-level analysis: only rows with identified catalysts
  - Newey-West HAC standard errors for t-stats
  - Full transparency on missing data at every step

Usage:
    cd /mnt/c/Projects/biotech_screener/biotech-screener
    python -m scripts.research.pit_backtest_ees_v2
    python -m scripts.research.pit_backtest_ees_v2 --horizon 42 --output results.json
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots_pit_v2"
DEFAULT_PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
DEFAULT_TRIAL_RECORDS = PROJECT_ROOT / "production_data" / "trial_records.json"

HORIZONS = [21, 42, 63]

# Signals to test (all recomputed on-the-fly)
# Group A: require priced_move_pct (will be NaN when missing)
# Group B: do NOT require priced_move_pct (always computable)
SIGNALS_GROUP_A = [
    "conditional_gap_score",
    "base_rate_gap_score",
    "conditional_misprice_score",
    "timing_decay_risk_score",
    "divergence_score",
    "trap_overlay_score",
    "quality_overlay_score",
    "ees_v2_score",
]
SIGNALS_GROUP_B = [
    "conditional_base_rate",
    "conditional_expected_move",
    "conditional_confidence",
    "crowding_bias_score",
]
ALL_SIGNALS = SIGNALS_GROUP_A + SIGNALS_GROUP_B


# ═════════════════════════════════════════════════════════════════════════
# Utilities
# ═════════════════════════════════════════════════════════════════════════


def _sf(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _avg_ranks(values: List[float]) -> List[float]:
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
    n = len(signal)
    if n < 5 or len(returns) != n:
        return None
    # Check degeneracy
    if len(set(round(s, 8) for s in signal)) < 3:
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


# ═════════════════════════════════════════════════════════════════════════
# Newey-West HAC estimator
# ═════════════════════════════════════════════════════════════════════════


def _newey_west_tstat(series: List[float], max_lag: Optional[int] = None) -> Dict[str, Any]:
    """Newey-West HAC t-stat for testing mean = 0.

    Uses Bartlett kernel with automatic lag selection: floor(4*(T/100)^(2/9)).
    """
    n = len(series)
    if n < 5:
        return {"mean": None, "t_nw": 0.0, "se_nw": None, "lag": 0, "n": n}

    mean = sum(series) / n
    demeaned = [s - mean for s in series]

    # Automatic lag selection (Newey-West 1994)
    if max_lag is None:
        max_lag = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    max_lag = max(0, min(max_lag, n - 2))

    # Gamma_0 (variance)
    gamma_0 = sum(d * d for d in demeaned) / n

    # HAC variance with Bartlett kernel
    hac_var = gamma_0
    for lag in range(1, max_lag + 1):
        gamma_j = sum(demeaned[t] * demeaned[t - lag] for t in range(lag, n)) / n
        weight = 1.0 - lag / (max_lag + 1.0)  # Bartlett
        hac_var += 2.0 * weight * gamma_j

    se = math.sqrt(max(hac_var / n, 1e-20))
    t_nw = mean / se if se > 1e-12 else 0.0

    return {
        "mean": round(mean, 6),
        "t_nw": round(t_nw, 2),
        "se_nw": round(se, 6),
        "lag": max_lag,
        "n": n,
    }


# ═════════════════════════════════════════════════════════════════════════
# Effective sample size
# ═════════════════════════════════════════════════════════════════════════


def _effective_n(series: List[float]) -> Dict[str, Any]:
    n = len(series)
    if n < 5:
        return {"n_raw": n, "rho1": None, "n_eff": n}

    m = sum(series) / n
    demeaned = [s - m for s in series]
    var = sum(d * d for d in demeaned) / n
    if var < 1e-12:
        return {"n_raw": n, "rho1": 0.0, "n_eff": n}

    cov1 = sum(demeaned[i] * demeaned[i + 1] for i in range(n - 1)) / (n - 1)
    rho1 = cov1 / var
    denom = max(0.1, 1 + rho1)
    n_eff = max(3, n * (1 - rho1) / denom)

    return {"n_raw": n, "rho1": round(rho1, 3), "n_eff": round(n_eff, 1)}


# ═════════════════════════════════════════════════════════════════════════
# Data loaders
# ═════════════════════════════════════════════════════════════════════════


def _discover_snapshot_dates(snapshots_dir: Path) -> List[str]:
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
    return series


def _resolve_trade_date(sorted_dates: List[str], snap_date: str) -> Optional[str]:
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
# Pre-enrichment: recover PIT-safe fields from available data
# ═════════════════════════════════════════════════════════════════════════


def _pre_enrich_snapshot(
    rows: List[Dict[str, Any]],
    snap_date: str,
    prices: Dict[str, Dict[str, float]],
    sorted_dates_by_ticker: Dict[str, List[str]],
) -> Dict[str, int]:
    """Inject recoverable fields into snapshot rows IN-PLACE before scoring.

    Recoveries (all PIT-safe):
      1. priced_move_pct ← implied_event_move × 100
         (implied_event_move is the ATM-straddle-implied move in decimal;
          EES tables use percentage points, so multiply by 100.
          In the live pipeline: priced_move_pct = straddle_price = implied_event_move.
          This column was simply never written to PIT snapshots.)
      2. close_price ← price_history.csv (most recent close on or before snap_date)

    Fields NOT recovered (no PIT-safe historical source):
      - short_interest_pct (only one point-in-time snapshot exists)
      - market_cap_mm (slippage_penalty is deprecated anyway)

    Returns recovery counts.
    """
    counts = {
        "priced_move_recovered": 0,
        "close_price_recovered": 0,
        "priced_move_already_set": 0,
        "close_price_already_set": 0,
    }

    for row in rows:
        tk = row.get("ticker", "")

        # ── 1. priced_move_pct from implied_event_move ──────────────
        pm = _sf(row.get("priced_move_pct"))
        if pm is not None:
            counts["priced_move_already_set"] += 1
        else:
            iem = _sf(row.get("implied_event_move"))
            if iem is not None and iem > 0:
                # Convert decimal → percentage points to match EES tables
                row["priced_move_pct"] = round(iem * 100.0, 4)
                counts["priced_move_recovered"] += 1

        # ── 2. close_price from price_history.csv ───────────────────
        cp = _sf(row.get("close_price"))
        if cp is not None:
            counts["close_price_already_set"] += 1
        else:
            tk_dates = sorted_dates_by_ticker.get(tk)
            if tk_dates:
                # Find most recent price on or before snap_date (PIT-safe)
                best_date = None
                for d in tk_dates:
                    if d <= snap_date:
                        best_date = d
                    else:
                        break
                if best_date:
                    px = prices[tk].get(best_date)
                    if px and px > 0:
                        row["close_price"] = px
                        counts["close_price_recovered"] += 1

    return counts


# ═════════════════════════════════════════════════════════════════════════
# On-the-fly scoring with strict PIT integrity
# ═════════════════════════════════════════════════════════════════════════


def _score_snapshot_strict(
    rows: List[Dict[str, Any]],
    snap_date: str,
    cond_model: Any,
    ees_model: Any,
) -> List[Dict[str, Any]]:
    """Recompute scores with strict PIT handling.

    Assumes _pre_enrich_snapshot has already been called to inject
    recoverable fields (priced_move_pct from implied_event_move, etc.).

    Rules:
      - If priced_move_pct is STILL missing after enrichment → NaN
      - No forward-fill, no synthetic imputation
      - Track exactly which fields were available
    """
    # EES batch (computes cross-sectional SI anchors internally)
    ees_scores = ees_model.score_batch(rows, snap_date)
    ees_map = {s.ticker: s for s in ees_scores}

    # Conditional batch
    cond_scores = cond_model.score_batch(rows, snap_date)
    cond_map = {s.ticker: s for s in cond_scores}

    enriched = []
    for row in rows:
        tk = row.get("ticker", "")
        ees = ees_map.get(tk)
        cond = cond_map.get(tk)

        # Field availability AFTER pre-enrichment
        has_priced_move = _sf(row.get("priced_move_pct")) is not None
        has_short_interest = _sf(row.get("short_interest_pct")) is not None
        has_implied_event_move = _sf(row.get("implied_event_move")) is not None
        has_catalyst_days = _sf(row.get("catalyst_days")) is not None

        rec: Dict[str, Any] = {
            "ticker": tk,
            "snap_date": snap_date,
            # Event context
            "has_catalyst": has_catalyst_days,
            "catalyst_family": row.get("catalyst_family", ""),
            "catalyst_days": _sf(row.get("catalyst_days")),
            "lead_program_phase": row.get("lead_program_phase", ""),
            # Data availability flags
            "has_priced_move": has_priced_move,
            "has_short_interest": has_short_interest,
            "has_implied_event_move": has_implied_event_move,
        }

        # EES sub-scores (mark NaN when input missing)
        if ees:
            rec["base_rate_gap_score"] = ees.base_rate_gap_score if has_priced_move else float("nan")
            rec["conditional_misprice_score"] = ees.conditional_misprice_score if has_priced_move else float("nan")
            rec["divergence_score"] = (
                ees.divergence_score if (has_priced_move and has_implied_event_move) else float("nan")
            )
            rec["crowding_bias_score"] = ees.crowding_bias_score if has_short_interest else float("nan")
            rec["timing_decay_risk_score"] = ees.timing_decay_risk_score if has_priced_move else float("nan")
            rec["slippage_penalty_score"] = 0.0  # DEPRECATED

            # Composites: NaN if any required input missing
            rec["trap_overlay_score"] = ees.trap_overlay_score if has_priced_move else float("nan")
            rec["quality_overlay_score"] = ees.quality_overlay_score if has_priced_move else float("nan")
            rec["ees_v2_score"] = ees.ees_v2_score if has_priced_move else float("nan")
        else:
            for sig in SIGNALS_GROUP_A:
                if sig not in ("conditional_gap_score",):
                    rec[sig] = float("nan")

        # Conditional model (base_rate and expected_move do NOT need priced_move)
        if cond:
            rec["conditional_base_rate"] = cond.conditional_base_rate
            rec["conditional_expected_move"] = cond.conditional_expected_move
            rec["conditional_confidence"] = cond.conditional_confidence
            rec["conditional_gap_score"] = cond.conditional_gap_score if has_priced_move else float("nan")
            rec["conditional_bucket"] = cond.conditional_bucket
            rec["fallback_level"] = cond.fallback_level
            rec["bucket_n"] = cond.bucket_n
        else:
            rec["conditional_base_rate"] = float("nan")
            rec["conditional_expected_move"] = float("nan")
            rec["conditional_confidence"] = float("nan")
            rec["conditional_gap_score"] = float("nan")
            rec["conditional_bucket"] = ""
            rec["fallback_level"] = 3
            rec["bucket_n"] = 0

        enriched.append(rec)

    return enriched


# ═════════════════════════════════════════════════════════════════════════
# Core analysis functions
# ═════════════════════════════════════════════════════════════════════════


def _compute_ic_series(
    date_records: Dict[str, List[Dict[str, Any]]],
    signal_key: str,
) -> List[Tuple[str, float, int]]:
    """Compute per-date Spearman IC for a signal. Returns [(date, ic, n), ...]."""
    ic_series = []
    for dt, records in sorted(date_records.items()):
        sigs = []
        rets = []
        for r in records:
            s = r.get(signal_key)
            if s is None or (isinstance(s, float) and math.isnan(s)):
                continue
            sigs.append(s)
            rets.append(r["fwd_return"])

        if len(sigs) < 5:
            continue

        ic = _spearman_ic(sigs, rets)
        if ic is not None:
            ic_series.append((dt, ic, len(sigs)))

    return ic_series


def _decile_analysis(
    date_records: Dict[str, List[Dict[str, Any]]],
    signal_key: str,
) -> Dict[str, Any]:
    """Decile spread and hit rate analysis."""
    spreads: List[float] = []
    quintile_hit_rates: Dict[int, List[float]] = defaultdict(list)  # 1-5

    for dt, records in sorted(date_records.items()):
        valid = [
            r
            for r in records
            if not (isinstance(r.get(signal_key), float) and math.isnan(r.get(signal_key, float("nan"))))
            and r.get(signal_key) is not None
        ]
        if len(valid) < 10:
            continue

        sorted_recs = sorted(valid, key=lambda r: r[signal_key])
        n = len(sorted_recs)
        d = max(1, n // 10)

        # Decile spread
        bottom = sorted_recs[:d]
        top = sorted_recs[-d:]
        top_ret = statistics.mean(r["fwd_return"] for r in top)
        bot_ret = statistics.mean(r["fwd_return"] for r in bottom)
        spreads.append(top_ret - bot_ret)

        # Quintile hit rates
        q_size = max(1, n // 5)
        for q in range(5):
            start = q * q_size
            end = start + q_size if q < 4 else n
            q_recs = sorted_recs[start:end]
            if q_recs:
                hr = sum(1 for r in q_recs if r["fwd_return"] > 0) / len(q_recs)
                quintile_hit_rates[q + 1].append(hr)

    if not spreads:
        return {"mean_spread_pp": None, "t_nw": 0.0, "n_periods": 0}

    nw = _newey_west_tstat(spreads)
    q_summary = {}
    for q in range(1, 6):
        rates = quintile_hit_rates.get(q, [])
        q_summary[f"Q{q}"] = round(statistics.mean(rates), 3) if rates else None

    return {
        "mean_spread_pp": round(statistics.mean(spreads) * 100, 2),
        "t_nw": nw["t_nw"],
        "hit_rate_spread_positive": round(sum(1 for s in spreads if s > 0) / len(spreads), 3),
        "quintile_hit_rates": q_summary,
        "n_periods": len(spreads),
    }


def _rolling_ic(
    ic_series: List[Tuple[str, float, int]],
    window: int = 6,
) -> List[Dict[str, Any]]:
    """Rolling window IC (by count of periods, not calendar months)."""
    results = []
    for i in range(window, len(ic_series) + 1):
        chunk = ic_series[i - window : i]
        ics = [c[1] for c in chunk]
        results.append(
            {
                "end_date": chunk[-1][0],
                "mean_ic": round(statistics.mean(ics), 4),
                "n_periods": window,
            }
        )
    return results


def _correlation_matrix(
    date_records: Dict[str, List[Dict[str, Any]]],
    signals: List[str],
) -> Dict[str, Dict[str, Optional[float]]]:
    """Cross-sectional correlation matrix between signal components."""
    # Pool all observations
    pooled: Dict[str, List[float]] = {s: [] for s in signals}
    for records in date_records.values():
        for r in records:
            valid = True
            for s in signals:
                v = r.get(s)
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    valid = False
                    break
            if valid:
                for s in signals:
                    pooled[s].append(r[s])

    matrix: Dict[str, Dict[str, Optional[float]]] = {}
    for s1 in signals:
        matrix[s1] = {}
        for s2 in signals:
            if s1 == s2:
                matrix[s1][s2] = 1.0
            elif len(pooled[s1]) >= 10:
                c = _pearson(pooled[s1], pooled[s2])
                matrix[s1][s2] = round(c, 3) if c is not None else None
            else:
                matrix[s1][s2] = None

    return matrix


# ═════════════════════════════════════════════════════════════════════════
# Main backtest
# ═════════════════════════════════════════════════════════════════════════


def run_backtest(
    snapshots_dir: Path,
    price_csv: Path,
    trial_records_path: Path,
    horizon: int = 63,
) -> Dict[str, Any]:

    # ── Load models ─────────────────────────────────────────────────
    sys.path.insert(0, str(PROJECT_ROOT))
    from event_ev.conditional_model import ConditionalModel
    from event_ev.expectation_error_model import ExpectationErrorModel

    cond_model = ConditionalModel(trial_records_path=trial_records_path)
    ees_model = ExpectationErrorModel()

    prices = _load_prices(price_csv)
    sorted_dates_by_ticker: Dict[str, List[str]] = {tk: sorted(px.keys()) for tk, px in prices.items()}

    snap_dates = _discover_snapshot_dates(snapshots_dir)
    logger.info("Found %d snapshot dates", len(snap_dates))

    # ── Score + forward returns ─────────────────────────────────────
    # Tracking counters
    n_total_rows = 0
    n_event_rows = 0
    n_with_fwd_return = 0
    n_with_priced_move = 0
    n_with_gap_computable = 0
    recovery_totals: Dict[str, int] = defaultdict(int)
    yearly_coverage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    date_records: Dict[str, List[Dict[str, Any]]] = {}

    for snap_date in snap_dates:
        rows = _load_snapshot(snapshots_dir, snap_date)
        if not rows:
            continue

        # Pre-enrich: recover priced_move_pct from implied_event_move,
        # close_price from price_history.csv — all PIT-safe
        recovery = _pre_enrich_snapshot(rows, snap_date, prices, sorted_dates_by_ticker)
        for k, v in recovery.items():
            recovery_totals[k] += v

        enriched = _score_snapshot_strict(rows, snap_date, cond_model, ees_model)
        year = snap_date[:4]

        event_enriched = []
        for rec in enriched:
            n_total_rows += 1
            yearly_coverage[year]["total"] += 1

            # Event filter: must have catalyst_days (identified event)
            if not rec["has_catalyst"]:
                continue
            n_event_rows += 1
            yearly_coverage[year]["events"] += 1

            if rec["has_priced_move"]:
                n_with_priced_move += 1
                yearly_coverage[year]["priced_move"] += 1
            if not math.isnan(rec.get("conditional_gap_score", float("nan"))):
                n_with_gap_computable += 1
                yearly_coverage[year]["gap_computable"] += 1

            # Forward return
            tk = rec["ticker"]
            tk_dates = sorted_dates_by_ticker.get(tk)
            if not tk_dates:
                continue
            trade_date = _resolve_trade_date(tk_dates, snap_date)
            if not trade_date:
                continue
            fwd_ret = _forward_return(prices[tk], tk_dates, trade_date, horizon)
            if fwd_ret is None:
                continue

            rec["fwd_return"] = fwd_ret
            n_with_fwd_return += 1
            yearly_coverage[year]["with_fwd"] += 1
            event_enriched.append(rec)

        if len(event_enriched) >= 5:
            date_records[snap_date] = event_enriched

    logger.info(
        "Pipeline: %d total → %d events → %d with fwd returns across %d dates",
        n_total_rows,
        n_event_rows,
        n_with_fwd_return,
        len(date_records),
    )

    if not date_records:
        return {"error": "no_data"}

    # ═════════════════════════════════════════════════════════════════
    # 1. CORE PERFORMANCE — per signal
    # ═════════════════════════════════════════════════════════════════

    signal_perf: Dict[str, Dict[str, Any]] = {}

    for sig in ALL_SIGNALS:
        ic_series = _compute_ic_series(date_records, sig)
        ics = [x[1] for x in ic_series]

        if not ics:
            signal_perf[sig] = {
                "ic": {"mean_ic": None, "t_nw": 0.0, "n_periods": 0},
                "effective_n": {"n_raw": 0, "n_eff": 0},
                "decile": {"mean_spread_pp": None, "n_periods": 0},
                "degenerate": True,
                "note": "signal degenerate (all NaN or <3 unique values)",
            }
            continue

        nw = _newey_west_tstat(ics)
        eff = _effective_n(ics)
        decile = _decile_analysis(date_records, sig)

        signal_perf[sig] = {
            "ic": {
                "mean_ic": nw["mean"],
                "t_nw": nw["t_nw"],
                "se_nw": nw["se_nw"],
                "nw_lag": nw["lag"],
                "hit_rate": round(sum(1 for ic in ics if ic > 0) / len(ics), 3),
                "n_periods": len(ics),
            },
            "effective_n": eff,
            "decile": decile,
            "degenerate": False,
        }

    # ═════════════════════════════════════════════════════════════════
    # 2. COMPONENT ATTRIBUTION — correlation matrix
    # ═════════════════════════════════════════════════════════════════

    # Only include non-degenerate signals in correlation matrix
    active_signals = [s for s in ALL_SIGNALS if not signal_perf[s].get("degenerate")]
    corr_matrix = _correlation_matrix(date_records, active_signals) if len(active_signals) >= 2 else {}

    # ═════════════════════════════════════════════════════════════════
    # 3. MISSING DATA DIAGNOSTICS
    # ═════════════════════════════════════════════════════════════════

    yearly_table = []
    for year in sorted(yearly_coverage.keys()):
        yc = yearly_coverage[year]
        n_ev = yc.get("events", 0)
        yearly_table.append(
            {
                "year": year,
                "total_rows": yc.get("total", 0),
                "event_rows": n_ev,
                "with_priced_move": yc.get("priced_move", 0),
                "pct_priced_move": round(yc["priced_move"] / n_ev * 100, 1) if n_ev else 0,
                "gap_computable": yc.get("gap_computable", 0),
                "pct_gap_computable": round(yc["gap_computable"] / n_ev * 100, 1) if n_ev else 0,
                "with_fwd_return": yc.get("with_fwd", 0),
            }
        )

    missing_diag = {
        "total_rows": n_total_rows,
        "event_rows": n_event_rows,
        "with_forward_return": n_with_fwd_return,
        "with_priced_move": n_with_priced_move,
        "pct_priced_move": round(n_with_priced_move / n_event_rows * 100, 1) if n_event_rows else 0,
        "gap_computable": n_with_gap_computable,
        "pct_gap_computable": round(n_with_gap_computable / n_event_rows * 100, 1) if n_event_rows else 0,
        "recovery": {
            "priced_move_from_iem": recovery_totals.get("priced_move_recovered", 0),
            "close_price_from_history": recovery_totals.get("close_price_recovered", 0),
            "note": "priced_move_pct = implied_event_move * 100 (same source, unit conversion)",
        },
        "by_year": yearly_table,
    }

    # ═════════════════════════════════════════════════════════════════
    # 4. STABILITY CHECKS
    # ═════════════════════════════════════════════════════════════════

    stability: Dict[str, Any] = {}

    stability_signals = [
        "conditional_expected_move",
        "conditional_base_rate",
        "conditional_gap_score",
        "trap_overlay_score",
        "ees_v2_score",
    ]
    for sig in stability_signals:
        ic_series = _compute_ic_series(date_records, sig)
        if not ic_series:
            stability[sig] = {"rolling_6m": [], "subsample_split": {}}
            continue

        # Rolling 6-period IC
        rolling = _rolling_ic(ic_series, window=6)

        # Subsample split (early vs late)
        mid = len(ic_series) // 2
        early_ics = [x[1] for x in ic_series[:mid]]
        late_ics = [x[1] for x in ic_series[mid:]]

        early_nw = _newey_west_tstat(early_ics)
        late_nw = _newey_west_tstat(late_ics)

        stability[sig] = {
            "rolling_6m": rolling,
            "subsample_split": {
                "early": {
                    "period": f"{ic_series[0][0]} to {ic_series[mid-1][0]}" if mid > 0 else "N/A",
                    "mean_ic": early_nw["mean"],
                    "t_nw": early_nw["t_nw"],
                    "n": early_nw["n"],
                },
                "late": {
                    "period": f"{ic_series[mid][0]} to {ic_series[-1][0]}" if mid < len(ic_series) else "N/A",
                    "mean_ic": late_nw["mean"],
                    "t_nw": late_nw["t_nw"],
                    "n": late_nw["n"],
                },
            },
        }

    # ═════════════════════════════════════════════════════════════════
    # 5. FAILURE MODE CHECK — full vs priced_move-only
    # ═════════════════════════════════════════════════════════════════

    # Split records into (A) full sample and (B) only events with priced_move
    date_records_pm_only: Dict[str, List[Dict[str, Any]]] = {}
    for dt, records in date_records.items():
        pm_recs = [r for r in records if r["has_priced_move"]]
        if len(pm_recs) >= 5:
            date_records_pm_only[dt] = pm_recs

    failure_mode: Dict[str, Any] = {
        "full_sample_dates": len(date_records),
        "priced_move_only_dates": len(date_records_pm_only),
        "full_sample_obs": sum(len(v) for v in date_records.values()),
        "priced_move_only_obs": sum(len(v) for v in date_records_pm_only.values()),
    }

    # Compare key signals across both samples
    for sig in [
        "conditional_expected_move",
        "conditional_base_rate",
        "conditional_gap_score",
        "trap_overlay_score",
        "quality_overlay_score",
        "ees_v2_score",
        "base_rate_gap_score",
        "timing_decay_risk_score",
    ]:
        # Full sample
        full_ics = [x[1] for x in _compute_ic_series(date_records, sig)]
        full_nw = _newey_west_tstat(full_ics) if full_ics else {"mean": None, "t_nw": 0.0, "n": 0}

        # Priced-move only
        pm_ics = [x[1] for x in _compute_ic_series(date_records_pm_only, sig)]
        pm_nw = _newey_west_tstat(pm_ics) if pm_ics else {"mean": None, "t_nw": 0.0, "n": 0}

        failure_mode[sig] = {
            "full_sample": {"mean_ic": full_nw["mean"], "t_nw": full_nw["t_nw"], "n": full_nw["n"]},
            "priced_move_only": {"mean_ic": pm_nw["mean"], "t_nw": pm_nw["t_nw"], "n": pm_nw["n"]},
            "signal_survives_restriction": (pm_nw.get("mean") or 0) > 0 and abs(pm_nw.get("t_nw", 0)) > 1.0,
        }

    # ═════════════════════════════════════════════════════════════════
    # Assemble report
    # ═════════════════════════════════════════════════════════════════

    sorted_dates_list = sorted(date_records.keys())

    report = {
        "schema": "pit_backtest_ees_v2.v1",
        "horizon_trading_days": horizon,
        "n_snapshot_dates": len(date_records),
        "n_observations": n_with_fwd_return,
        "date_range": {
            "first": sorted_dates_list[0] if sorted_dates_list else None,
            "last": sorted_dates_list[-1] if sorted_dates_list else None,
        },
        "filter_funnel": {
            "total_snapshot_rows": n_total_rows,
            "after_event_filter": n_event_rows,
            "after_fwd_return": n_with_fwd_return,
            "pct_retained": round(n_with_fwd_return / n_total_rows * 100, 1) if n_total_rows else 0,
        },
        "core_performance": signal_perf,
        "component_correlation": corr_matrix,
        "missing_data": missing_diag,
        "stability": stability,
        "failure_mode": failure_mode,
    }

    return report


# ═════════════════════════════════════════════════════════════════════════
# Multi-horizon runner
# ═════════════════════════════════════════════════════════════════════════


def run_multi_horizon(
    snapshots_dir: Path,
    price_csv: Path,
    trial_records_path: Path,
) -> Dict[str, Any]:
    results = {}
    for h in HORIZONS:
        logger.info("═══ Horizon %dd ═══", h)
        results[f"{h}d"] = run_backtest(snapshots_dir, price_csv, trial_records_path, h)

    # Cross-horizon summary table
    summary_rows = []
    for sig in ALL_SIGNALS:
        row_data = {"signal": sig}
        for h_key, report in results.items():
            perf = report.get("core_performance", {}).get(sig, {})
            ic = perf.get("ic", {})
            row_data[f"{h_key}_ic"] = ic.get("mean_ic")
            row_data[f"{h_key}_t"] = ic.get("t_nw", 0)
            row_data[f"{h_key}_n"] = ic.get("n_periods", 0)
        summary_rows.append(row_data)

    return {"horizons": results, "cross_horizon_summary": summary_rows}


# ═════════════════════════════════════════════════════════════════════════
# Pretty-print summary
# ═════════════════════════════════════════════════════════════════════════


def _print_summary(report: Dict[str, Any]) -> None:
    if "cross_horizon_summary" in report:
        _print_multi_summary(report)
    else:
        _print_single_summary(report)


def _print_single_summary(report: Dict[str, Any]) -> None:
    h = report.get("horizon_trading_days", "?")
    print(f"\n{'=' * 72}")
    print(f"PIT BACKTEST: EES v2 + CONDITIONAL MODEL — {h}d HORIZON")
    print(f"{'=' * 72}")

    ff = report.get("filter_funnel", {})
    print("\nFilter funnel:")
    print(f"  {ff.get('total_snapshot_rows', 0):>6,} total snapshot rows")
    print(f"  {ff.get('after_event_filter', 0):>6,} after event filter")
    print(f"  {ff.get('after_fwd_return', 0):>6,} with forward returns ({ff.get('pct_retained', 0):.1f}% retained)")

    md = report.get("missing_data", {})
    print("\nMissing data:")
    print(f"  priced_move_pct:        {md.get('pct_priced_move', 0):.1f}% of events")
    print(f"  conditional_gap_score:  {md.get('pct_gap_computable', 0):.1f}% computable")

    print(f"\n{'Signal':<30} {'IC':>7} {'t(NW)':>7} {'Hit%':>6} {'Decile':>8} {'Degen':>6}")
    print("-" * 72)
    perf = report.get("core_performance", {})
    for sig in ALL_SIGNALS:
        p = perf.get(sig, {})
        if p.get("degenerate"):
            print(f"  {sig:<28} {'---':>7} {'---':>7} {'---':>6} {'---':>8} {'YES':>6}")
            continue
        ic = p.get("ic", {})
        dec = p.get("decile", {})
        ic_val = ic.get("mean_ic")
        ic_str = f"{ic_val:+.4f}" if ic_val is not None else "---"
        t_str = f"{ic.get('t_nw', 0):+.2f}"
        hr_str = f"{ic.get('hit_rate', 0):.1%}" if ic.get("hit_rate") else "---"
        dec_str = f"{dec.get('mean_spread_pp', 0):+.1f}pp" if dec.get("mean_spread_pp") is not None else "---"
        print(f"  {sig:<28} {ic_str:>7} {t_str:>7} {hr_str:>6} {dec_str:>8} {'no':>6}")

    md = report.get("missing_data", {})
    rec = md.get("recovery", {})
    if rec:
        print(
            f"\nRecovery: priced_move from iem={rec.get('priced_move_from_iem', 0):,}, "
            f"close_price from history={rec.get('close_price_from_history', 0):,}"
        )

    fm = report.get("failure_mode", {})
    print("\nFailure mode analysis (full vs priced_move-only):")
    print(f"  {'Signal':<30} {'Full IC':>8} {'Full t':>7} | {'PM IC':>8} {'PM t':>7} {'Surv':>5}")
    print("  " + "-" * 68)
    for sig in [
        "conditional_expected_move",
        "conditional_base_rate",
        "conditional_gap_score",
        "trap_overlay_score",
        "ees_v2_score",
        "base_rate_gap_score",
    ]:
        fmd = fm.get(sig, {})
        full = fmd.get("full_sample", {})
        pm = fmd.get("priced_move_only", {})
        f_ic = f"{full.get('mean_ic', 0):+.4f}" if full.get("mean_ic") is not None else "---"
        f_t = f"{full.get('t_nw', 0):+.2f}"
        p_ic = f"{pm.get('mean_ic', 0):+.4f}" if pm.get("mean_ic") is not None else "---"
        p_t = f"{pm.get('t_nw', 0):+.2f}"
        surv = "YES" if fmd.get("signal_survives_restriction") else "NO"
        print(f"  {sig:<30} {f_ic:>8} {f_t:>7} | {p_ic:>8} {p_t:>7} {surv:>5}")

    print(f"\n{'=' * 72}")


def _print_multi_summary(report: Dict[str, Any]) -> None:
    print(f"\n{'=' * 80}")
    print("PIT BACKTEST: EES v2 + CONDITIONAL MODEL — MULTI-HORIZON")
    print(f"{'=' * 80}")

    # Print filter funnel from first horizon
    first_h = next(iter(report.get("horizons", {}).values()), {})
    ff = first_h.get("filter_funnel", {})
    md = first_h.get("missing_data", {})
    print(
        f"\nFilter funnel: {ff.get('total_snapshot_rows', 0):,} → "
        f"{ff.get('after_event_filter', 0):,} events → "
        f"{ff.get('after_fwd_return', 0):,} with fwd ret"
    )
    print(
        f"Missing: priced_move={md.get('pct_priced_move', 0):.1f}%, "
        f"gap_computable={md.get('pct_gap_computable', 0):.1f}%"
    )

    rows = report.get("cross_horizon_summary", [])
    h_keys = [f"{h}d" for h in HORIZONS]

    print(f"\n{'Signal':<30}", end="")
    for h in h_keys:
        print(f" | {'IC':>7} {'t(NW)':>6}", end="")
    print()
    print("-" * (30 + len(h_keys) * 17))

    for row in rows:
        sig = row["signal"]
        print(f"  {sig:<28}", end="")
        for h in h_keys:
            ic = row.get(f"{h}_ic")
            t = row.get(f"{h}_t", 0)
            if ic is None:
                print(f" | {'---':>7} {'---':>6}", end="")
            else:
                print(f" | {ic:+.4f} {t:+.1f}", end="")
        print()

    # Failure mode from 63d (most standard horizon)
    h63 = report.get("horizons", {}).get("63d", {})
    md = h63.get("missing_data", {})
    rec = md.get("recovery", {})
    if rec:
        print(
            f"\nRecovery: priced_move from iem={rec.get('priced_move_from_iem', 0):,}, "
            f"close_price from history={rec.get('close_price_from_history', 0):,}"
        )

    fm = h63.get("failure_mode", {})
    if fm:
        print(
            f"\nFailure mode (63d): full={fm.get('full_sample_obs', 0):,} obs, "
            f"PM-only={fm.get('priced_move_only_obs', 0):,} obs"
        )
        for sig in [
            "conditional_expected_move",
            "conditional_base_rate",
            "conditional_gap_score",
            "trap_overlay_score",
            "ees_v2_score",
        ]:
            fmd = fm.get(sig, {})
            full = fmd.get("full_sample", {})
            pm = fmd.get("priced_move_only", {})
            surv = "SURVIVES" if fmd.get("signal_survives_restriction") else "FAILS"
            f_ic = full.get("mean_ic")
            p_ic = pm.get("mean_ic")
            f_str = f"IC={f_ic:+.4f} t={full.get('t_nw', 0):+.1f}" if f_ic is not None else "degenerate"
            p_str = f"IC={p_ic:+.4f} t={pm.get('t_nw', 0):+.1f}" if p_ic is not None else "degenerate"
            print(f"  {sig}: full({f_str}) vs PM({p_str}) → {surv}")

    print(f"\n{'=' * 80}")


# ═════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(description="PIT backtest: EES v2 + conditional model (strict PIT integrity)")
    parser.add_argument("--snapshots-dir", type=Path, default=DEFAULT_SNAPSHOTS_DIR)
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICE_CSV)
    parser.add_argument("--trials", type=Path, default=DEFAULT_TRIAL_RECORDS)
    parser.add_argument("--horizon", type=int, default=None, help="Single horizon (default: run 21/42/63)")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.horizon:
        report = run_backtest(args.snapshots_dir, args.prices, args.trials, args.horizon)
    else:
        report = run_multi_horizon(args.snapshots_dir, args.prices, args.trials)

    _print_summary(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Full report written to %s", args.output)


if __name__ == "__main__":
    main()
