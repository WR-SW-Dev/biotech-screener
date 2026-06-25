#!/usr/bin/env python3
"""PIT Backtest: EES v3 coverage-robustness test.

Runs two parallel passes over the same 76 PIT snapshots:
  - FULL:     all snapshot dates (no coverage filter) — baseline, matches v3 memo
  - FILTERED: only dates where priced_move_pct coverage >= 50%

Comparison answers the operator question:
  "Is v3's positive signal driven by sparse/missing priced_move_pct eras,
  or does it hold when the misprice factor has adequate representation?"

Pass condition:
  - v3 remains positive at 42d/63d in the filtered sample
  - No catastrophic degradation vs full-sample v3 (IC delta < 50% drop)
  - Result not driven exclusively by low-coverage eras

Governance: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE

Usage:
    cd /mnt/c/Projects/biotech_screener/biotech-screener
    python3 -m scripts.research.pit_backtest_ees_v3_coverage_filtered
    python3 -m scripts.research.pit_backtest_ees_v3_coverage_filtered \\
        --min-coverage 0.50 \\
        --output artifacts/research/ees_v3_coverage_robustness_$(date +%Y%m%d).json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
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
MIN_COVERAGE_DEFAULT = 0.50

# Signals — same set as pit_backtest_ees_v3.py
ALL_SIGNALS = [
    "ees_v3_score",
    "ees_v2_score",
    "final_score",
    "conditional_misprice_score",
    "conditional_expected_move",
    "conditional_base_rate",
    "conditional_gap_score",
    "trap_overlay_score",
    "base_rate_gap_score",
]


# ═══════════════════════════════════════════════════════════════════
# Utilities (identical to pit_backtest_ees_v3.py)
# ═══════════════════════════════════════════════════════════════════


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


def _newey_west_tstat(series: List[float], max_lag: Optional[int] = None) -> Dict[str, Any]:
    n = len(series)
    if n < 5:
        return {"mean": None, "t_nw": 0.0, "se_nw": None, "lag": 0, "n": n}
    mean = sum(series) / n
    demeaned = [s - mean for s in series]
    if max_lag is None:
        max_lag = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    max_lag = max(0, min(max_lag, n - 2))
    gamma_0 = sum(d * d for d in demeaned) / n
    hac_var = gamma_0
    for lag in range(1, max_lag + 1):
        gamma_j = sum(demeaned[t] * demeaned[t - lag] for t in range(lag, n)) / n
        weight = 1.0 - lag / (max_lag + 1.0)
        hac_var += 2.0 * weight * gamma_j
    se = math.sqrt(max(hac_var / n, 1e-20))
    t_nw = mean / se if se > 1e-12 else 0.0
    return {"mean": round(mean, 6), "t_nw": round(t_nw, 2), "se_nw": round(se, 6), "lag": max_lag, "n": n}


# ═══════════════════════════════════════════════════════════════════
# Data loaders
# ═══════════════════════════════════════════════════════════════════


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


def _pre_enrich_snapshot(
    rows: List[Dict[str, Any]],
    snap_date: str,
    prices: Dict[str, Dict[str, float]],
    sorted_dates_by_ticker: Dict[str, List[str]],
) -> None:
    for row in rows:
        tk = row.get("ticker", "")
        if _sf(row.get("priced_move_pct")) is None:
            iem = _sf(row.get("implied_event_move"))
            if iem is not None and iem > 0:
                row["priced_move_pct"] = round(iem * 100.0, 4)
        if _sf(row.get("close_price")) is None:
            tk_dates = sorted_dates_by_ticker.get(tk)
            if tk_dates:
                best_date = None
                for d in tk_dates:
                    if d <= snap_date:
                        best_date = d
                    else:
                        break
                if best_date:
                    px = prices.get(tk, {}).get(best_date)
                    if px and px > 0:
                        row["close_price"] = px


def _score_snapshot(
    rows: List[Dict[str, Any]],
    snap_date: str,
    cond_model: Any,
    ees_model: Any,
    ees_v3_fn: Any,
) -> List[Dict[str, Any]]:
    ees_scores = ees_model.score_batch(rows, snap_date)
    ees_map = {s.ticker: s for s in ees_scores}
    cond_scores = cond_model.score_batch(rows, snap_date)
    cond_map = {s.ticker: s for s in cond_scores}

    enriched = []
    for row in rows:
        tk = row.get("ticker", "")
        ees = ees_map.get(tk)
        cond = cond_map.get(tk)

        has_priced_move = _sf(row.get("priced_move_pct")) is not None
        has_catalyst_days = _sf(row.get("catalyst_days")) is not None

        rec: Dict[str, Any] = {
            "ticker": tk,
            "snap_date": snap_date,
            "has_catalyst": has_catalyst_days,
            "catalyst_days": _sf(row.get("catalyst_days")),
            "has_priced_move": has_priced_move,
            "final_score": _sf(row.get("final_score")),
        }

        if ees:
            rec["base_rate_gap_score"] = ees.base_rate_gap_score if has_priced_move else float("nan")
            rec["conditional_misprice_score"] = ees.conditional_misprice_score if has_priced_move else float("nan")
            rec["trap_overlay_score"] = ees.trap_overlay_score if has_priced_move else float("nan")
            rec["ees_v2_score"] = ees.ees_v2_score if has_priced_move else float("nan")
        else:
            for sig in ["base_rate_gap_score", "conditional_misprice_score", "trap_overlay_score", "ees_v2_score"]:
                rec[sig] = float("nan")

        if cond:
            rec["conditional_base_rate"] = cond.conditional_base_rate
            rec["conditional_expected_move"] = cond.conditional_expected_move
            rec["conditional_gap_score"] = cond.conditional_gap_score if has_priced_move else float("nan")
        else:
            rec["conditional_base_rate"] = float("nan")
            rec["conditional_expected_move"] = float("nan")
            rec["conditional_gap_score"] = float("nan")

        enriched.append(rec)

    v3_results = ees_v3_fn(enriched, snap_date)
    v3_map = {r.ticker: r for r in v3_results}
    for rec in enriched:
        v3 = v3_map.get(rec["ticker"])
        rec["ees_v3_score"] = v3.ees_v3_score if v3 else float("nan")

    return enriched


# ═══════════════════════════════════════════════════════════════════
# Coverage measurement
# ═══════════════════════════════════════════════════════════════════


def _compute_priced_move_coverage(enriched: List[Dict[str, Any]]) -> Tuple[float, int, int]:
    """Coverage among event-filtered rows only (rows with catalyst_days)."""
    event_rows = [r for r in enriched if r.get("has_catalyst")]
    if not event_rows:
        return 0.0, 0, 0
    n_with = sum(1 for r in event_rows if r.get("has_priced_move"))
    coverage = n_with / len(event_rows)
    return coverage, n_with, len(event_rows)


# ═══════════════════════════════════════════════════════════════════
# IC / statistics (identical to pit_backtest_ees_v3.py)
# ═══════════════════════════════════════════════════════════════════


def _compute_ic_series(
    date_records: Dict[str, List[Dict[str, Any]]],
    signal_key: str,
) -> List[Tuple[str, float, int]]:
    ic_series = []
    for dt, records in sorted(date_records.items()):
        sigs, rets = [], []
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


def _subsample_stability(ic_series: List[Tuple[str, float, int]]) -> Dict[str, Any]:
    if not ic_series:
        return {}
    mid = len(ic_series) // 2
    early = [x[1] for x in ic_series[:mid]]
    late = [x[1] for x in ic_series[mid:]]
    early_nw = _newey_west_tstat(early)
    late_nw = _newey_west_tstat(late)
    return {
        "early": {
            "period": f"{ic_series[0][0]}→{ic_series[mid - 1][0]}" if mid > 0 else "N/A",
            "mean_ic": early_nw["mean"],
            "t_nw": early_nw["t_nw"],
            "n": early_nw["n"],
        },
        "late": {
            "period": f"{ic_series[mid][0]}→{ic_series[-1][0]}" if mid < len(ic_series) else "N/A",
            "mean_ic": late_nw["mean"],
            "t_nw": late_nw["t_nw"],
            "n": late_nw["n"],
        },
    }


def _ic_verdict(mean_ic: Optional[float], t_nw: float) -> str:
    if mean_ic is None:
        return "NO_DATA"
    if mean_ic > 0 and abs(t_nw) >= 2.0:
        return "POSITIVE_SIGNIFICANT"
    if mean_ic > 0 and abs(t_nw) >= 1.5:
        return "POSITIVE_MARGINAL"
    if mean_ic > 0:
        return "POSITIVE_WEAK"
    if mean_ic < 0 and abs(t_nw) >= 2.0:
        return "NEGATIVE_SIGNIFICANT"
    if mean_ic < 0 and abs(t_nw) >= 1.5:
        return "NEGATIVE_MARGINAL"
    return "NEGATIVE_WEAK"


# ═══════════════════════════════════════════════════════════════════
# Core: single-pass backtest with optional coverage gate
# ═══════════════════════════════════════════════════════════════════


def _run_pass(
    snap_dates: List[str],
    snapshots_dir: Path,
    prices: Dict[str, Dict[str, float]],
    sorted_dates_by_ticker: Dict[str, List[str]],
    cond_model: Any,
    ees_model: Any,
    ees_v3_fn: Any,
    horizon: int,
    min_coverage: float,
    label: str,
) -> Dict[str, Any]:
    date_records: Dict[str, List[Dict[str, Any]]] = {}
    n_total = n_events = n_with_fwd = 0
    n_dates_checked = 0
    n_dates_excluded_coverage = 0
    coverage_by_date: Dict[str, float] = {}

    for snap_date in snap_dates:
        rows = _load_snapshot(snapshots_dir, snap_date)
        if not rows:
            continue
        n_dates_checked += 1
        _pre_enrich_snapshot(rows, snap_date, prices, sorted_dates_by_ticker)
        enriched = _score_snapshot(rows, snap_date, cond_model, ees_model, ees_v3_fn)

        coverage, n_with_pm, n_event = _compute_priced_move_coverage(enriched)
        coverage_by_date[snap_date] = round(coverage, 3)

        if coverage < min_coverage:
            n_dates_excluded_coverage += 1
            logger.debug("  %s: coverage=%.1f%% < %.0f%% — excluded", snap_date, coverage * 100, min_coverage * 100)
            continue

        event_enriched = []
        for rec in enriched:
            n_total += 1
            if not rec["has_catalyst"]:
                continue
            n_events += 1
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
            n_with_fwd += 1
            event_enriched.append(rec)

        if len(event_enriched) >= 5:
            date_records[snap_date] = event_enriched

    logger.info(
        "[%s] %dd: %d dates checked, %d excluded (coverage<%.0f%%), %d included → %d obs",
        label,
        horizon,
        n_dates_checked,
        n_dates_excluded_coverage,
        min_coverage * 100,
        len(date_records),
        n_with_fwd,
    )

    if not date_records:
        return {"error": "no_data_after_coverage_filter", "label": label, "min_coverage": min_coverage}

    sorted_snap_dates = sorted(date_records.keys())

    # Coverage stats
    included_coverages = [v for k, v in coverage_by_date.items() if k in date_records]
    excluded_coverages = [v for k, v in coverage_by_date.items() if k not in date_records]

    coverage_stats = {
        "n_dates_total": n_dates_checked,
        "n_dates_included": len(date_records),
        "n_dates_excluded": n_dates_excluded_coverage,
        "included_coverage_mean": (
            round(sum(included_coverages) / len(included_coverages), 3) if included_coverages else None
        ),
        "included_coverage_min": round(min(included_coverages), 3) if included_coverages else None,
        "excluded_coverage_mean": (
            round(sum(excluded_coverages) / len(excluded_coverages), 3) if excluded_coverages else None
        ),
        "excluded_coverage_max": round(max(excluded_coverages), 3) if excluded_coverages else None,
        "first_included": sorted_snap_dates[0],
        "last_included": sorted_snap_dates[-1],
        "date_range_all": {
            "first": min(coverage_by_date.keys()),
            "last": max(coverage_by_date.keys()),
        },
    }

    # Per-signal IC analysis
    signal_perf: Dict[str, Dict[str, Any]] = {}
    for sig in ALL_SIGNALS:
        ic_series = _compute_ic_series(date_records, sig)
        ics = [x[1] for x in ic_series]
        if not ics:
            signal_perf[sig] = {"ic": {"mean_ic": None, "t_nw": 0.0, "n_periods": 0}, "degenerate": True}
            continue
        nw = _newey_west_tstat(ics)
        stability = _subsample_stability(ic_series)
        signal_perf[sig] = {
            "ic": {
                "mean_ic": nw["mean"],
                "t_nw": nw["t_nw"],
                "se_nw": nw["se_nw"],
                "hit_rate": round(sum(1 for ic in ics if ic > 0) / len(ics), 3),
                "n_periods": len(ics),
            },
            "verdict": _ic_verdict(nw["mean"], nw["t_nw"]),
            "stability": stability,
        }

    return {
        "label": label,
        "min_coverage_threshold": min_coverage,
        "horizon_trading_days": horizon,
        "n_observations": n_with_fwd,
        "coverage_stats": coverage_stats,
        "signals": signal_perf,
    }


# ═══════════════════════════════════════════════════════════════════
# Pass condition assessment
# ═══════════════════════════════════════════════════════════════════


def _assess_pass_conditions(
    full: Dict[str, Any],
    filtered: Dict[str, Any],
    horizon_key: str,
) -> Dict[str, Any]:
    """Evaluate operator-specified pass conditions for the coverage robustness test."""
    h = int(horizon_key.replace("d", ""))

    def _ic(pass_data: Dict[str, Any], sig: str) -> Optional[float]:
        return pass_data.get("signals", {}).get(sig, {}).get("ic", {}).get("mean_ic")

    def _t(pass_data: Dict[str, Any], sig: str) -> float:
        return pass_data.get("signals", {}).get(sig, {}).get("ic", {}).get("t_nw", 0.0) or 0.0

    def _verdict(pass_data: Dict[str, Any], sig: str) -> str:
        return pass_data.get("signals", {}).get(sig, {}).get("verdict", "NO_DATA")

    v3_full_ic = _ic(full, "ees_v3_score")
    v3_filt_ic = _ic(filtered, "ees_v3_score")
    v3_full_t = _t(full, "ees_v3_score")
    v3_filt_t = _t(filtered, "ees_v3_score")

    # Condition 1: v3 remains positive at 42d/63d in filtered sample
    # (only relevant for those horizons; 21d is nice-to-have)
    if h >= 42:
        cond1 = (v3_filt_ic or -999) > 0 and v3_filt_t >= 1.5
        cond1_label = "PASS" if cond1 else "FAIL"
    else:
        cond1 = (v3_filt_ic or -999) > 0
        cond1_label = "PASS" if cond1 else "FAIL"

    # Condition 2: no catastrophic degradation (IC drop < 50% of full-sample IC)
    if v3_full_ic and abs(v3_full_ic) > 1e-6 and v3_filt_ic is not None:
        degradation_pct = (v3_full_ic - v3_filt_ic) / abs(v3_full_ic) * 100
        cond2 = degradation_pct < 50.0
        cond2_label = "PASS" if cond2 else "FAIL"
    else:
        degradation_pct = None
        cond2 = None
        cond2_label = "INSUFFICIENT_DATA"

    # Condition 3: result not driven only by sparse eras
    # Test: full IC > 0 AND filtered IC > 0 → signal present in both regimes
    cond3 = (v3_full_ic or -999) > 0 and (v3_filt_ic or -999) > 0
    cond3_label = "PASS" if cond3 else "FAIL"

    # Overall
    all_pass = cond1 and cond2 and cond3 if (cond2 is not None) else (cond1 and cond3)

    return {
        "horizon": horizon_key,
        "conditions": {
            "c1_v3_positive_in_filtered": {
                "description": f"v3 positive{'+ marginal/significant' if h >= 42 else ''} at {h}d in coverage-filtered sample",
                "full_sample": f"IC={v3_full_ic:+.4f} t={v3_full_t:+.2f}" if v3_full_ic is not None else "N/A",
                "filtered_sample": f"IC={v3_filt_ic:+.4f} t={v3_filt_t:+.2f}" if v3_filt_ic is not None else "N/A",
                "result": cond1_label,
            },
            "c2_no_catastrophic_degradation": {
                "description": "Filtered IC not < 50% drop from full-sample IC",
                "degradation_pct": round(degradation_pct, 1) if degradation_pct is not None else None,
                "result": cond2_label,
            },
            "c3_signal_present_in_both_regimes": {
                "description": "v3 IC positive in both full and filtered samples",
                "full_verdict": _verdict(full, "ees_v3_score"),
                "filtered_verdict": _verdict(filtered, "ees_v3_score"),
                "result": cond3_label,
            },
        },
        "overall": "PASS" if all_pass else "FAIL",
    }


# ═══════════════════════════════════════════════════════════════════
# Run coverage comparison
# ═══════════════════════════════════════════════════════════════════


def run_coverage_comparison(
    snapshots_dir: Path,
    price_csv: Path,
    trial_records_path: Path,
    min_coverage: float = MIN_COVERAGE_DEFAULT,
) -> Dict[str, Any]:
    sys.path.insert(0, str(PROJECT_ROOT))
    from event_ev.conditional_model import ConditionalModel
    from event_ev.ees_v3 import compute_v3_scores
    from event_ev.expectation_error_model import ExpectationErrorModel

    cond_model = ConditionalModel(trial_records_path=trial_records_path)
    ees_model = ExpectationErrorModel()

    prices = _load_prices(price_csv)
    sorted_dates_by_ticker: Dict[str, List[str]] = {tk: sorted(px.keys()) for tk, px in prices.items()}
    snap_dates = _discover_snapshot_dates(snapshots_dir)
    logger.info("Coverage robustness test: %d snapshot dates, min_coverage=%.0f%%", len(snap_dates), min_coverage * 100)

    horizons_full: Dict[str, Any] = {}
    horizons_filtered: Dict[str, Any] = {}

    for h in HORIZONS:
        logger.info("═══ Horizon %dd — FULL pass ═══", h)
        horizons_full[f"{h}d"] = _run_pass(
            snap_dates,
            snapshots_dir,
            prices,
            sorted_dates_by_ticker,
            cond_model,
            ees_model,
            compute_v3_scores,
            h,
            0.0,
            "FULL",
        )
        logger.info("═══ Horizon %dd — FILTERED pass (>= %.0f%% coverage) ═══", h, min_coverage * 100)
        horizons_filtered[f"{h}d"] = _run_pass(
            snap_dates,
            snapshots_dir,
            prices,
            sorted_dates_by_ticker,
            cond_model,
            ees_model,
            compute_v3_scores,
            h,
            min_coverage,
            f"FILTERED_{int(min_coverage*100)}pct",
        )

    # Pass condition assessment per horizon
    pass_conditions: Dict[str, Any] = {}
    for h_key in [f"{h}d" for h in HORIZONS]:
        full_h = horizons_full.get(h_key, {})
        filt_h = horizons_filtered.get(h_key, {})
        if "error" not in full_h and "error" not in filt_h:
            pass_conditions[h_key] = _assess_pass_conditions(full_h, filt_h, h_key)

    # Coverage-filtered dates at 42d (reference horizon)
    h42_filt = horizons_filtered.get("42d", {})
    cs = h42_filt.get("coverage_stats", {})

    # Cross-horizon summary table
    summary_rows = []
    for sig in ALL_SIGNALS:
        row: Dict[str, Any] = {"signal": sig}
        for h in HORIZONS:
            h_key = f"{h}d"
            full_h = horizons_full.get(h_key, {})
            filt_h = horizons_filtered.get(h_key, {})

            full_ic = full_h.get("signals", {}).get(sig, {}).get("ic", {}).get("mean_ic")
            full_t = full_h.get("signals", {}).get(sig, {}).get("ic", {}).get("t_nw", 0)
            filt_ic = filt_h.get("signals", {}).get(sig, {}).get("ic", {}).get("mean_ic")
            filt_t = filt_h.get("signals", {}).get(sig, {}).get("ic", {}).get("t_nw", 0)

            row[f"{h_key}_full_ic"] = full_ic
            row[f"{h_key}_full_t"] = full_t
            row[f"{h_key}_filt_ic"] = filt_ic
            row[f"{h_key}_filt_t"] = filt_t

        summary_rows.append(row)

    return {
        "schema": "pit_backtest_ees_v3_coverage_robustness.v1",
        "governance": "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE",
        "min_coverage_threshold": min_coverage,
        "n_snapshot_dates_total": len(snap_dates),
        "n_dates_included_at_42d": cs.get("n_dates_included"),
        "n_dates_excluded_at_42d": cs.get("n_dates_excluded"),
        "included_date_range_at_42d": {
            "first": cs.get("first_included"),
            "last": cs.get("last_included"),
        },
        "pass_conditions": pass_conditions,
        "horizons_full": horizons_full,
        "horizons_filtered": horizons_filtered,
        "cross_horizon_summary": summary_rows,
    }


# ═══════════════════════════════════════════════════════════════════
# Print summary
# ═══════════════════════════════════════════════════════════════════


def _print_summary(report: Dict[str, Any]) -> None:
    min_cov_pct = int(report.get("min_coverage_threshold", 0.5) * 100)
    n_total = report.get("n_snapshot_dates_total", 0)
    n_incl = report.get("n_dates_included_at_42d", "?")
    n_excl = report.get("n_dates_excluded_at_42d", "?")
    dr = report.get("included_date_range_at_42d", {})

    print(f"\n{'=' * 90}")
    print("PIT BACKTEST: EES v3 Coverage Robustness Test")
    print(f"Coverage filter: priced_move_pct >= {min_cov_pct}%  |  Governance: DIAGNOSTIC_ONLY | FREEZE_ACTIVE")
    print(f"{'=' * 90}")
    print(f"\nSnapshot universe: {n_total} total dates")
    print(f"After coverage filter (≥{min_cov_pct}%): {n_incl} included, {n_excl} excluded")
    print(f"Included date range: {dr.get('first')} → {dr.get('last')}")

    rows = report.get("cross_horizon_summary", [])
    priority_signals = [
        "ees_v3_score",
        "ees_v2_score",
        "final_score",
        "conditional_misprice_score",
        "conditional_gap_score",
        "conditional_base_rate",
        "conditional_expected_move",
        "trap_overlay_score",
        "base_rate_gap_score",
    ]
    h_keys = ["21d", "42d", "63d"]

    print(f"\n{'Signal':<35}", end="")
    for h in h_keys:
        print(f" │  {h} FULL         {h} FILT{min_cov_pct}%", end="")
    print()
    print("─" * (35 + len(h_keys) * 28))

    for sig in priority_signals:
        row = next((r for r in rows if r["signal"] == sig), None)
        if not row:
            continue
        marker = "►" if sig in ("ees_v3_score", "ees_v2_score") else " "
        print(f"{marker} {sig:<33}", end="")
        for h in h_keys:
            full_ic = row.get(f"{h}_full_ic")
            full_t = row.get(f"{h}_full_t", 0)
            filt_ic = row.get(f"{h}_filt_ic")
            filt_t = row.get(f"{h}_filt_t", 0)

            def _fmt(ic: Optional[float], t: float) -> str:
                if ic is None:
                    return "  ---    --- "
                flag = "✓" if ic > 0 and abs(t) >= 1.5 else ("✗" if ic < 0 and abs(t) >= 1.5 else " ")
                return f"{ic:+.4f}{flag} {t:+.1f}"

            print(f" │  {_fmt(full_ic, full_t)}   {_fmt(filt_ic, filt_t)}", end="")
        print()

    # Pass condition table
    print(f"\n{'─' * 90}")
    print("PASS CONDITIONS (operator spec):")
    pc = report.get("pass_conditions", {})
    for h_key in h_keys:
        conds = pc.get(h_key, {})
        overall = conds.get("overall", "N/A")
        flag = "✓" if overall == "PASS" else ("✗" if overall == "FAIL" else "?")
        print(f"\n  {h_key}: OVERALL = {overall} {flag}")
        for cname, cd in conds.get("conditions", {}).items():
            r = cd.get("result", "?")
            r_flag = "✓" if r == "PASS" else ("✗" if r == "FAIL" else "?")
            print(f"    [{r_flag}] {cname}: {r}", end="")
            if "degradation_pct" in cd and cd["degradation_pct"] is not None:
                print(f" (degradation={cd['degradation_pct']:+.1f}%)", end="")
            if "full_sample" in cd:
                print(f"  full={cd['full_sample']}  filtered={cd['filtered_sample']}", end="")
            print()

    print(f"\n{'=' * 90}")
    print("Governance: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE")
    print(f"{'=' * 90}")


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(
        description="EES v3 PIT coverage robustness test — full vs coverage-filtered comparison"
    )
    parser.add_argument("--snapshots-dir", type=Path, default=DEFAULT_SNAPSHOTS_DIR)
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICE_CSV)
    parser.add_argument("--trials", type=Path, default=DEFAULT_TRIAL_RECORDS)
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=MIN_COVERAGE_DEFAULT,
        help="Min priced_move_pct coverage fraction to include a snapshot (default: 0.50)",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = run_coverage_comparison(args.snapshots_dir, args.prices, args.trials, args.min_coverage)

    _print_summary(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Full report written to %s", args.output)
    else:
        default_out = PROJECT_ROOT / "artifacts" / "research" / "ees_v3_coverage_robustness_20260625.json"
        default_out.parent.mkdir(parents=True, exist_ok=True)
        with open(default_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Full report written to %s", default_out)


if __name__ == "__main__":
    main()
