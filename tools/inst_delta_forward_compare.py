#!/usr/bin/env python3
"""inst_delta forward-shadow daily comparison.

Reads the T0 lock file at artifacts/audit/inst_delta_forward_shadow/T0_*_lock.json
and the latest production_data/price_history.csv, then computes mark-to-market
returns for the CURRENT and COUNTERFACTUAL portfolios at each cutoff
(top-10/20/30/40/50/60) and emits a checkpoint JSON.

Run daily ~19:30 ET. Writes:
  artifacts/audit/inst_delta_forward_shadow/checkpoint_{TODAY}.json
  artifacts/audit/inst_delta_forward_shadow/checkpoints.jsonl  (append)
  artifacts/audit/inst_delta_forward_shadow/verdict_h{N}d.md   (only when today matches a horizon)

Read-only. No production state modified. PIT-safe (T0 prices frozen in lock).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHADOW_DIR = REPO / "artifacts" / "audit" / "inst_delta_forward_shadow"
PRICE_FILE = REPO / "production_data" / "price_history.csv"


def _f(s):
    try:
        return float(s) if s not in ("", None, "nan") else None
    except (ValueError, TypeError):
        return None


def _trading_days_between(start_iso: str, end_iso: str) -> int:
    """Count weekdays between two ISO dates (exclusive of start, inclusive of end)."""
    s = date.fromisoformat(start_iso)
    e = date.fromisoformat(end_iso)
    if e <= s:
        return 0
    n = 0
    d = s
    while d < e:
        d = d + timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _load_price_series(tickers: set, t0_iso: str) -> dict:
    """Return {ticker: [(date_iso, close), ...]} for dates >= t0."""
    series: dict = {t: [] for t in tickers}
    with open(PRICE_FILE) as fh:
        for row in csv.DictReader(fh):
            t = row.get("ticker")
            d = row.get("date", "")[:10]
            if t in series and d >= t0_iso:
                p = _f(row.get("close"))
                if p is not None:
                    series[t].append((d, p))
    for t in series:
        series[t].sort()
    return series


def _eq_weighted_path(portfolio_records, price_series):
    """Build EW cumulative-return path for a portfolio.

    Returns (sorted_dates, [path_value at each date]) where path_value is
    the equal-weight average of (price_d / T0_close - 1) across portfolio
    members that have a close on that date.
    """
    t0_close = {r["ticker"]: r["T0_close"] for r in portfolio_records if r.get("T0_close")}
    dates_seen: set = set()
    for t in t0_close:
        for d, _ in price_series.get(t, []):
            dates_seen.add(d)
    sorted_dates = sorted(dates_seen)
    path = []
    for d in sorted_dates:
        rets = []
        for t, p0 in t0_close.items():
            close_d = next((c for dd, c in price_series.get(t, []) if dd == d), None)
            if close_d is not None and p0:
                rets.append(close_d / p0 - 1.0)
        path.append(sum(rets) / len(rets) if rets else None)
    return sorted_dates, path


def _portfolio_metrics(dates_iso, ew_path, xbi_path):
    """Compute summary metrics over the path. Returns dict."""
    if not ew_path or all(v is None for v in ew_path):
        return {"insufficient_data": True}
    cum = ew_path[-1]
    daily = []
    for i in range(1, len(ew_path)):
        a, b = ew_path[i - 1], ew_path[i]
        if a is None or b is None:
            continue
        daily.append((1 + b) / (1 + a) - 1)
    vol = statistics.stdev(daily) if len(daily) >= 2 else 0.0
    mean_daily = statistics.mean(daily) if daily else 0.0
    sharpe_ann = (mean_daily / vol * math.sqrt(252)) if vol > 0 else 0.0
    peak = -1.0
    max_dd = 0.0
    for v in ew_path:
        if v is None:
            continue
        peak = max(peak, v)
        if peak > -1:
            dd = (1 + v) / (1 + peak) - 1
            max_dd = min(max_dd, dd)
    excess_vs_xbi = None
    if xbi_path and xbi_path[-1] is not None and ew_path[-1] is not None:
        excess_vs_xbi = ew_path[-1] - xbi_path[-1]
    return {
        "cum_return": round(cum, 6) if cum is not None else None,
        "mean_daily_return": round(mean_daily, 6),
        "vol_daily": round(vol, 6),
        "vol_annualized": round(vol * math.sqrt(252), 6),
        "sharpe_annualized": round(sharpe_ann, 4),
        "max_drawdown": round(max_dd, 6),
        "excess_vs_xbi": round(excess_vs_xbi, 6) if excess_vs_xbi is not None else None,
        "n_observations": len([v for v in ew_path if v is not None]),
    }


def _per_ticker_returns(portfolio_records, price_series, as_of_iso):
    """Return list of (ticker, t0_close, latest_close, return) for portfolio members."""
    out = []
    for r in portfolio_records:
        t = r["ticker"]
        p0 = r.get("T0_close")
        latest = next((c for d, c in reversed(price_series.get(t, [])) if d <= as_of_iso), None)
        if latest is not None and p0:
            out.append((t, p0, latest, latest / p0 - 1.0))
        else:
            out.append((t, p0, None, None))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lock", default=None, help="Path to T0 lock file. Default: latest in shadow dir.")
    p.add_argument("--as-of", default=None, help="As-of date (YYYY-MM-DD). Default: today.")
    args = p.parse_args()

    if args.lock:
        lock_path = Path(args.lock)
    else:
        candidates = sorted(SHADOW_DIR.glob("T0_*_lock.json"))
        if not candidates:
            print(f"FATAL: no lock file in {SHADOW_DIR}", file=sys.stderr)
            return 2
        lock_path = candidates[-1]

    with open(lock_path) as fh:
        lock = json.load(fh)
    t0 = lock["T0"]
    cutoffs = lock["cutoffs"]
    portfolios = lock["portfolios"]
    artifact_tickers = lock["known_artifact_tickers"]
    horizons = lock["horizons_trading_days"]

    as_of = args.as_of or datetime.now().date().isoformat()
    days_since_t0 = _trading_days_between(t0, as_of)

    if days_since_t0 < 1:
        print(f"as_of={as_of} is not at least 1 trading day after T0={t0}; nothing to compare.")
        return 0

    # Pull price series for every ticker we care about + XBI
    needed = set(["XBI"])
    for k, recs in portfolios.items():
        for r in recs:
            needed.add(r["ticker"])
    series = _load_price_series(needed, t0)

    # XBI path
    xbi_t0 = lock.get("T0_xbi_close")
    xbi_path = []
    xbi_dates = sorted({d for d, _ in series.get("XBI", []) if d >= t0 and d <= as_of})
    for d in xbi_dates:
        c = next((c for dd, c in series.get("XBI", []) if dd == d), None)
        xbi_path.append(c / xbi_t0 - 1.0 if (c is not None and xbi_t0) else None)

    # Per-portfolio metrics
    portfolio_results = {}
    for name, recs in portfolios.items():
        # Filter recs to as_of-window prices only
        recs_with_t0 = [r for r in recs if r.get("T0_close")]
        dates_iso, ew_path = _eq_weighted_path(recs_with_t0, series)
        # Trim to as_of
        ew_path = [v for d, v in zip(dates_iso, ew_path) if d <= as_of]
        dates_iso = [d for d in dates_iso if d <= as_of]
        ew_metrics = _portfolio_metrics(dates_iso, ew_path, xbi_path)
        per_ticker = _per_ticker_returns(recs_with_t0, series, as_of)
        hit_rate = sum(1 for _, _, _, r in per_ticker if r is not None and r > 0) / max(
            1, sum(1 for _, _, _, r in per_ticker if r is not None)
        )
        ew_metrics["hit_rate"] = round(hit_rate, 4)
        ew_metrics["per_ticker_top5"] = sorted(
            [(t, r) for t, _, _, r in per_ticker if r is not None],
            key=lambda x: -x[1],
        )[:5]
        ew_metrics["per_ticker_bottom5"] = sorted(
            [(t, r) for t, _, _, r in per_ticker if r is not None],
            key=lambda x: x[1],
        )[:5]
        # Artifact-name contribution (CURRENT only meaningful)
        if name.startswith("current_"):
            artifact_rets = [r for t, _, _, r in per_ticker if t in artifact_tickers and r is not None]
            non_artifact_rets = [r for t, _, _, r in per_ticker if t not in artifact_tickers and r is not None]
            ew_metrics["artifact_member_count"] = len(artifact_rets)
            ew_metrics["artifact_mean_return"] = round(statistics.mean(artifact_rets), 6) if artifact_rets else None
            ew_metrics["non_artifact_mean_return"] = (
                round(statistics.mean(non_artifact_rets), 6) if non_artifact_rets else None
            )
        portfolio_results[name] = ew_metrics

    # Diff: CURRENT vs COUNTERFACTUAL at each cutoff
    diffs = {}
    for cutoff in cutoffs:
        cur = portfolio_results.get(f"current_top{cutoff}", {})
        cf = portfolio_results.get(f"counterfactual_top{cutoff}", {})
        if cur.get("cum_return") is None or cf.get("cum_return") is None:
            continue
        diffs[f"top{cutoff}"] = {
            "current_cum": cur["cum_return"],
            "counterfactual_cum": cf["cum_return"],
            "current_minus_cf": round(cur["cum_return"] - cf["cum_return"], 6),
            "current_sharpe": cur.get("sharpe_annualized"),
            "cf_sharpe": cf.get("sharpe_annualized"),
            "current_max_dd": cur.get("max_drawdown"),
            "cf_max_dd": cf.get("max_drawdown"),
            "current_hit_rate": cur.get("hit_rate"),
            "cf_hit_rate": cf.get("hit_rate"),
            "current_excess_vs_xbi": cur.get("excess_vs_xbi"),
            "cf_excess_vs_xbi": cf.get("excess_vs_xbi"),
            "current_artifact_mean": cur.get("artifact_mean_return"),
            "current_non_artifact_mean": cur.get("non_artifact_mean_return"),
        }

    checkpoint = {
        "as_of": as_of,
        "T0": t0,
        "trading_days_since_T0": days_since_t0,
        "is_horizon_milestone": days_since_t0 in horizons,
        "horizon_label": f"h{days_since_t0}d" if days_since_t0 in horizons else None,
        "xbi_cum_return": xbi_path[-1] if xbi_path else None,
        "portfolio_metrics": portfolio_results,
        "current_vs_counterfactual": diffs,
    }

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SHADOW_DIR / f"checkpoint_{as_of}.json"
    with open(out_path, "w") as fh:
        json.dump(checkpoint, fh, indent=2, default=str)

    # Append to running JSONL
    with open(SHADOW_DIR / "checkpoints.jsonl", "a") as fh:
        fh.write(json.dumps(checkpoint, default=str) + "\n")

    # Console summary
    print(f"=== inst_delta forward shadow checkpoint — as_of={as_of}, T0={t0}, td_since_T0={days_since_t0} ===")
    print(f"XBI cum_return: {xbi_path[-1]:+.4f}" if xbi_path else "XBI: n/a")
    print()
    print(
        f"{'cutoff':>8}  {'CUR':>8}  {'CF':>8}  {'Δ':>8}  {'CUR_SR':>7}  {'CF_SR':>7}  {'CUR_DD':>7}  {'CF_DD':>7}  {'art_μ':>7}  {'non_μ':>7}"
    )
    for cutoff in cutoffs:
        d = diffs.get(f"top{cutoff}")
        if not d:
            continue

        def fmt(v, w, p=4):
            return f"{v:>{w}.{p}f}" if v is not None else " " * w

        print(
            f"{'top'+str(cutoff):>8}  {fmt(d['current_cum'], 8)}  {fmt(d['counterfactual_cum'], 8)}  "
            f"{fmt(d['current_minus_cf'], 8)}  {fmt(d['current_sharpe'], 7, 3)}  {fmt(d['cf_sharpe'], 7, 3)}  "
            f"{fmt(d['current_max_dd'], 7, 3)}  {fmt(d['cf_max_dd'], 7, 3)}  "
            f"{fmt(d['current_artifact_mean'], 7, 3)}  {fmt(d['current_non_artifact_mean'], 7, 3)}"
        )
    print()
    if checkpoint["is_horizon_milestone"]:
        print(f"  *** HORIZON MILESTONE: h{days_since_t0}d ***")
    print(f"artifact: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
