#!/usr/bin/env python3
"""PIT Backtest: EES v3 vs v2 composite — strict point-in-time integrity.

Extends pit_backtest_ees_v2.py methodology to include:
  - ees_v3_score: recomputed on-the-fly from v3 model
  - final_score:  read from stored PIT snapshot (production ranker output)

Uses same snapshot range, event filter, forward returns, and NW HAC t-stats
as the original v2 backtest. Output is directly comparable.

Governance: DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE

Usage:
    cd /mnt/c/Projects/biotech_screener/biotech-screener
    python -m scripts.research.pit_backtest_ees_v3
    python -m scripts.research.pit_backtest_ees_v3 --output artifacts/research/ees_v3_pit_backtest_$(date +%Y%m%d).json
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

# v2 signals (recomputed on-the-fly) — same as original backtest
SIGNALS_V2_GROUP_A = [
    "conditional_gap_score",
    "base_rate_gap_score",
    "conditional_misprice_score",
    "trap_overlay_score",
    "ees_v2_score",
]
SIGNALS_V2_GROUP_B = [
    "conditional_base_rate",
    "conditional_expected_move",
]

# v3 signals — ees_v3_score recomputed, final_score stored
SIGNALS_V3 = ["ees_v3_score"]
SIGNALS_STORED = ["final_score"]

ALL_SIGNALS = SIGNALS_V2_GROUP_A + SIGNALS_V2_GROUP_B + SIGNALS_V3 + SIGNALS_STORED


# ═════════════════════════════════════════════════════════════════════════
# Utilities (copied from pit_backtest_ees_v2 for self-containment)
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
# Pre-enrichment (same as v2 backtest)
# ═════════════════════════════════════════════════════════════════════════


def _pre_enrich_snapshot(
    rows: List[Dict[str, Any]],
    snap_date: str,
    prices: Dict[str, Dict[str, float]],
    sorted_dates_by_ticker: Dict[str, List[str]],
) -> None:
    for row in rows:
        tk = row.get("ticker", "")
        # priced_move_pct from implied_event_move
        if _sf(row.get("priced_move_pct")) is None:
            iem = _sf(row.get("implied_event_move"))
            if iem is not None and iem > 0:
                row["priced_move_pct"] = round(iem * 100.0, 4)
        # close_price from price_history.csv
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


# ═════════════════════════════════════════════════════════════════════════
# Scoring: recompute v2+conditional+v3 on-the-fly
# ═════════════════════════════════════════════════════════════════════════


def _score_snapshot(
    rows: List[Dict[str, Any]],
    snap_date: str,
    cond_model: Any,
    ees_model: Any,
    ees_v3_fn: Any,
) -> List[Dict[str, Any]]:
    # Recompute v2 + conditional
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
            # stored final_score (production ranker — read from snapshot)
            "final_score": _sf(row.get("final_score")),
        }

        # v2 recomputed
        if ees:
            rec["base_rate_gap_score"] = ees.base_rate_gap_score if has_priced_move else float("nan")
            rec["conditional_misprice_score"] = ees.conditional_misprice_score if has_priced_move else float("nan")
            rec["trap_overlay_score"] = ees.trap_overlay_score if has_priced_move else float("nan")
            rec["ees_v2_score"] = ees.ees_v2_score if has_priced_move else float("nan")
        else:
            for sig in ["base_rate_gap_score", "conditional_misprice_score", "trap_overlay_score", "ees_v2_score"]:
                rec[sig] = float("nan")

        # conditional recomputed
        if cond:
            rec["conditional_base_rate"] = cond.conditional_base_rate
            rec["conditional_expected_move"] = cond.conditional_expected_move
            rec["conditional_gap_score"] = cond.conditional_gap_score if has_priced_move else float("nan")
        else:
            rec["conditional_base_rate"] = float("nan")
            rec["conditional_expected_move"] = float("nan")
            rec["conditional_gap_score"] = float("nan")

        enriched.append(rec)

    # v3 recomputed from enriched conditional fields
    v3_results = ees_v3_fn(enriched, snap_date)
    v3_map = {r.ticker: r for r in v3_results}
    for rec in enriched:
        v3 = v3_map.get(rec["ticker"])
        rec["ees_v3_score"] = v3.ees_v3_score if v3 else float("nan")

    return enriched


# ═════════════════════════════════════════════════════════════════════════
# IC / decile analysis (same as v2 backtest)
# ═════════════════════════════════════════════════════════════════════════


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


def _decile_analysis(
    date_records: Dict[str, List[Dict[str, Any]]],
    signal_key: str,
) -> Dict[str, Any]:
    spreads: List[float] = []
    quintile_hit_rates: Dict[int, List[float]] = defaultdict(list)

    for dt, records in sorted(date_records.items()):
        valid = [
            r
            for r in records
            if r.get(signal_key) is not None
            and not (isinstance(r.get(signal_key), float) and math.isnan(r.get(signal_key, float("nan"))))
        ]
        if len(valid) < 10:
            continue
        sorted_recs = sorted(valid, key=lambda r: r[signal_key])
        n = len(sorted_recs)
        d = max(1, n // 10)
        top_ret = statistics.mean(r["fwd_return"] for r in sorted_recs[-d:])
        bot_ret = statistics.mean(r["fwd_return"] for r in sorted_recs[:d])
        spreads.append(top_ret - bot_ret)
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
    q_summary = {
        f"Q{q}": round(statistics.mean(rates), 3) for q in range(1, 6) if (rates := quintile_hit_rates.get(q, []))
    }
    return {
        "mean_spread_pp": round(statistics.mean(spreads) * 100, 2),
        "t_nw": nw["t_nw"],
        "hit_rate_spread_positive": round(sum(1 for s in spreads if s > 0) / len(spreads), 3),
        "quintile_hit_rates": q_summary,
        "n_periods": len(spreads),
    }


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


# ═════════════════════════════════════════════════════════════════════════
# Main backtest
# ═════════════════════════════════════════════════════════════════════════


def run_backtest(
    snapshots_dir: Path,
    price_csv: Path,
    trial_records_path: Path,
    horizon: int,
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
    logger.info("Horizon %dd | %d snapshot dates", horizon, len(snap_dates))

    date_records: Dict[str, List[Dict[str, Any]]] = {}
    n_total = n_events = n_with_fwd = 0

    for snap_date in snap_dates:
        rows = _load_snapshot(snapshots_dir, snap_date)
        if not rows:
            continue
        _pre_enrich_snapshot(rows, snap_date, prices, sorted_dates_by_ticker)
        enriched = _score_snapshot(rows, snap_date, cond_model, ees_model, compute_v3_scores)

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
        "%d total → %d events → %d with fwd return across %d dates",
        n_total,
        n_events,
        n_with_fwd,
        len(date_records),
    )
    if not date_records:
        return {"error": "no_data"}

    sorted_snap_dates = sorted(date_records.keys())

    # Per-signal IC + decile
    signal_perf: Dict[str, Dict[str, Any]] = {}
    for sig in ALL_SIGNALS:
        ic_series = _compute_ic_series(date_records, sig)
        ics = [x[1] for x in ic_series]
        if not ics:
            signal_perf[sig] = {"ic": {"mean_ic": None, "t_nw": 0.0, "n_periods": 0}, "degenerate": True}
            continue
        nw = _newey_west_tstat(ics)
        eff = _effective_n(ics)
        decile = _decile_analysis(date_records, sig)
        stability = _subsample_stability(ic_series)
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
            "stability": stability,
            "degenerate": False,
        }

    # v3 vs v2 comparison summary
    def _ic_verdict(perf: Dict[str, Any]) -> str:
        if perf.get("degenerate"):
            return "DEGENERATE"
        ic = perf["ic"]["mean_ic"]
        t = perf["ic"]["t_nw"]
        if ic is None:
            return "NO_DATA"
        if ic > 0 and abs(t) >= 2.0:
            return "POSITIVE_SIGNIFICANT"
        if ic > 0 and abs(t) >= 1.5:
            return "POSITIVE_MARGINAL"
        if ic > 0:
            return "POSITIVE_WEAK"
        if ic < 0 and abs(t) >= 2.0:
            return "NEGATIVE_SIGNIFICANT"
        if ic < 0 and abs(t) >= 1.5:
            return "NEGATIVE_MARGINAL"
        return "NEGATIVE_WEAK"

    comparison = {
        "ees_v2_score": _ic_verdict(signal_perf.get("ees_v2_score", {})),
        "ees_v3_score": _ic_verdict(signal_perf.get("ees_v3_score", {})),
        "final_score": _ic_verdict(signal_perf.get("final_score", {})),
        "v3_improves_over_v2": (
            (signal_perf.get("ees_v3_score", {}).get("ic", {}).get("mean_ic") or -999)
            > (signal_perf.get("ees_v2_score", {}).get("ic", {}).get("mean_ic") or -999)
        ),
    }

    return {
        "schema": "pit_backtest_ees_v3.v1",
        "governance": "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE",
        "horizon_trading_days": horizon,
        "n_snapshot_dates": len(date_records),
        "n_observations": n_with_fwd,
        "date_range": {
            "first": sorted_snap_dates[0],
            "last": sorted_snap_dates[-1],
        },
        "filter_funnel": {
            "total_snapshot_rows": n_total,
            "after_event_filter": n_events,
            "after_fwd_return": n_with_fwd,
            "pct_retained": round(n_with_fwd / n_total * 100, 1) if n_total else 0,
        },
        "core_performance": signal_perf,
        "comparison": comparison,
    }


def run_multi_horizon(
    snapshots_dir: Path,
    price_csv: Path,
    trial_records_path: Path,
) -> Dict[str, Any]:
    results = {}
    for h in HORIZONS:
        logger.info("═══ Horizon %dd ═══", h)
        results[f"{h}d"] = run_backtest(snapshots_dir, price_csv, trial_records_path, h)

    # Cross-horizon summary
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

    return {
        "schema": "pit_backtest_ees_v3.v1",
        "governance": "DIAGNOSTIC_ONLY | NO_PRODUCTION_CHANGES | FREEZE_ACTIVE",
        "horizons": results,
        "cross_horizon_summary": summary_rows,
    }


# ═════════════════════════════════════════════════════════════════════════
# Print summary
# ═════════════════════════════════════════════════════════════════════════


def _print_summary(report: Dict[str, Any]) -> None:
    if "cross_horizon_summary" not in report:
        _print_single(report)
        return

    print(f"\n{'=' * 80}")
    print("PIT BACKTEST: EES v3 vs v2 — MULTI-HORIZON RESULTS")
    print("Governance: DIAGNOSTIC_ONLY | FREEZE_ACTIVE")
    print(f"{'=' * 80}")

    first_h = next(iter(report.get("horizons", {}).values()), {})
    ff = first_h.get("filter_funnel", {})
    print(
        f"\nFilter funnel: {ff.get('total_snapshot_rows', 0):,} total → "
        f"{ff.get('after_event_filter', 0):,} events → "
        f"{ff.get('after_fwd_return', 0):,} with fwd return"
    )
    dr = first_h.get("date_range", {})
    print(
        f"Date range: {dr.get('first')} → {dr.get('last')}  " f"({first_h.get('n_snapshot_dates', 0)} snapshot dates)"
    )

    rows = report.get("cross_horizon_summary", [])
    h_keys = [f"{h}d" for h in HORIZONS]

    print(f"\n{'Signal':<35}", end="")
    for h in h_keys:
        print(f" | {h + ' IC':>8} {'t(NW)':>6}", end="")
    print()
    print("-" * (35 + len(h_keys) * 18))

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
    ordered = [s for s in priority_signals if s in ALL_SIGNALS]
    ordered += [s for s in ALL_SIGNALS if s not in ordered]

    for sig in ordered:
        row = next((r for r in rows if r["signal"] == sig), None)
        if not row:
            continue
        marker = "►" if sig in ("ees_v3_score", "ees_v2_score") else " "
        print(f"{marker} {sig:<33}", end="")
        for h in h_keys:
            ic = row.get(f"{h}_ic")
            t = row.get(f"{h}_t", 0)
            if ic is None:
                print(f" | {'---':>8} {'---':>6}", end="")
            else:
                flag = " ✓" if ic > 0 and abs(t) >= 1.5 else (" ✗" if ic < 0 and abs(t) >= 1.5 else "  ")
                print(f" | {ic:+.4f}{flag} {t:+.1f}", end="")
        print()

    # Comparison verdicts per horizon
    print(f"\n{'─' * 60}")
    print("VERDICT per horizon:")
    for h_key, h_report in report.get("horizons", {}).items():
        comp = h_report.get("comparison", {})
        v2v = comp.get("ees_v2_score", "N/A")
        v3v = comp.get("ees_v3_score", "N/A")
        imp = "YES" if comp.get("v3_improves_over_v2") else "NO"
        print(f"  {h_key}: v2={v2v:<28} v3={v3v:<28} v3_better={imp}")

    print(f"\n{'=' * 80}")


def _print_single(report: Dict[str, Any]) -> None:
    h = report.get("horizon_trading_days", "?")
    print(f"\nHorizon {h}d | n_obs={report.get('n_observations', 0):,} | " f"dates={report.get('n_snapshot_dates', 0)}")
    perf = report.get("core_performance", {})
    for sig in ALL_SIGNALS:
        p = perf.get(sig, {})
        ic = p.get("ic", {})
        ic_val = ic.get("mean_ic")
        t_val = ic.get("t_nw", 0)
        if ic_val is not None:
            print(f"  {sig:<35} IC={ic_val:+.4f}  t={t_val:+.2f}  hit={ic.get('hit_rate', 0):.3f}")


# ═════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(description="PIT backtest: EES v3 vs v2 (strict PIT integrity, diagnostic only)")
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
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Full report written to %s", args.output)


if __name__ == "__main__":
    main()
