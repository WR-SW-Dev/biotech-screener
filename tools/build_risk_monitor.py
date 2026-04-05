#!/usr/bin/env python3
"""Portfolio risk monitor — drawdown, correlation, regime alerts.

Watches the shadow portfolio for:
  1. Drawdown breach (absolute and relative to XBI)
  2. Concentration risk (single name > threshold)
  3. Correlation spike (portfolio corr to XBI too high = no diversification)
  4. Regime shift (bull regime where model has negative IR)
  5. Earnings cluster risk (too many names reporting same week)

Usage:
    python tools/build_risk_monitor.py --as-of-date 2026-04-02
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

PRICE_CSV = REPO_ROOT / "production_data" / "price_history.csv"
SNAPSHOTS_DIR = REPO_ROOT / "data" / "snapshots"
SHADOW_PERF = REPO_ROOT / "artifacts" / "live_shadow" / "performance.csv"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "risk_monitor"

SCHEMA = "risk_monitor.v2"

# Thresholds
DD_ABS_WARN = -0.10  # -10% absolute drawdown
DD_ABS_CRIT = -0.20  # -20% absolute drawdown
DD_REL_WARN = -0.05  # -5% vs XBI
CORR_HIGH = 0.85  # portfolio too correlated to XBI
EARNINGS_CLUSTER_WARN = 5  # >5 names reporting same week
BULL_XBI_THRESHOLD = 0.02  # XBI > +2% = bull regime (model weakness)

# C6/C7 thresholds
VOL_TARGET = 0.50  # 50% annualized portfolio vol target
VOL_ALERT_BUFFER = 1.10  # alert when vol > target * 1.10
CORR_CLUSTER_THRESHOLD = 0.70
CORR_CLUSTER_MAX = 3


def load_prices(lookback_days: int = 63) -> dict[str, list[tuple[str, float]]]:
    cutoff = (date.today() - timedelta(days=lookback_days * 2)).isoformat()
    series: dict[str, list[tuple[str, float]]] = {}
    with open(PRICE_CSV) as f:
        for row in csv.DictReader(f):
            d, t, c = row.get("date", ""), row.get("ticker", ""), row.get("close", "")
            if d >= cutoff and t and c:
                try:
                    series.setdefault(t, []).append((d, float(c)))
                except ValueError:
                    pass
    for t in series:
        series[t].sort()
    return series


def _returns(prices: list[tuple[str, float]], n: int) -> list[float]:
    rets = []
    for i in range(max(0, len(prices) - n), len(prices)):
        if i > 0 and prices[i - 1][1] > 0:
            rets.append(prices[i][1] / prices[i - 1][1] - 1)
    return rets


def _drawdown(prices: list[tuple[str, float]]) -> float:
    if not prices:
        return 0
    peak = prices[0][1]
    max_dd = 0
    for _, p in prices:
        peak = max(peak, p)
        dd = p / peak - 1 if peak > 0 else 0
        max_dd = min(max_dd, dd)
    return max_dd


def _correlation(x: list[float], y: list[float]) -> float:
    n = min(len(x), len(y))
    if n < 10:
        return 0
    x, y = x[-n:], y[-n:]
    mx, my = statistics.mean(x), statistics.mean(y)
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / n
    sx = (sum((xi - mx) ** 2 for xi in x) / n) ** 0.5
    sy = (sum((yi - my) ** 2 for yi in y) / n) ** 0.5
    if sx < 1e-9 or sy < 1e-9:
        return 0
    return cov / (sx * sy)


def build_risk_report(as_of_date: str) -> dict[str, Any]:
    rankings_path = SNAPSHOTS_DIR / as_of_date / "rankings.csv"
    if not rankings_path.exists():
        return {"error": f"No rankings for {as_of_date}"}

    with open(rankings_path) as f:
        rows = list(csv.DictReader(f))

    # Get top-20 (pruned portfolio)
    ranked = [r for r in rows if r.get("actionable_rank", "").strip()]
    ranked.sort(key=lambda r: int(float(r["actionable_rank"])))

    for r in ranked:
        r["_idz"] = float(r.get("inst_delta_z", "0")) if r.get("inst_delta_z", "") not in ("", "nan") else 0

    top30 = ranked[:30]
    idz_sorted = sorted(top30, key=lambda r: r["_idz"], reverse=True)
    portfolio_tickers = [r["ticker"] for r in idz_sorted[:20]]

    prices = load_prices()
    xbi_prices = prices.get("XBI", [])
    alerts: list[dict] = []

    # 1. Portfolio drawdown (equal-weight average of constituent drawdowns)
    constituent_dds = []
    for t in portfolio_tickers:
        tp = prices.get(t, [])
        if len(tp) >= 20:
            dd = _drawdown(tp[-63:])
            constituent_dds.append(dd)

    avg_dd = statistics.mean(constituent_dds) if constituent_dds else 0
    worst_dd = min(constituent_dds) if constituent_dds else 0
    worst_ticker = ""
    for t in portfolio_tickers:
        tp = prices.get(t, [])
        if len(tp) >= 20 and _drawdown(tp[-63:]) == worst_dd:
            worst_ticker = t
            break

    if avg_dd < DD_ABS_CRIT:
        alerts.append({"level": "CRITICAL", "type": "drawdown", "detail": f"Avg DD {avg_dd:.1%} < {DD_ABS_CRIT:.0%}"})
    elif avg_dd < DD_ABS_WARN:
        alerts.append({"level": "WARN", "type": "drawdown", "detail": f"Avg DD {avg_dd:.1%} < {DD_ABS_WARN:.0%}"})

    # 2. XBI relative drawdown
    xbi_dd = _drawdown(xbi_prices[-63:]) if len(xbi_prices) >= 20 else 0
    rel_dd = avg_dd - xbi_dd
    if rel_dd < DD_REL_WARN:
        alerts.append({"level": "WARN", "type": "rel_drawdown", "detail": f"Relative DD {rel_dd:.1%} vs XBI"})

    # 3. Correlation to XBI
    xbi_rets = _returns(xbi_prices, 30)
    port_rets = []
    for i in range(min(30, len(xbi_rets))):
        daily_rets = []
        for t in portfolio_tickers:
            tp = prices.get(t, [])
            tr = _returns(tp, 30)
            if i < len(tr):
                daily_rets.append(tr[i])
        if daily_rets:
            port_rets.append(statistics.mean(daily_rets))

    corr = _correlation(port_rets, xbi_rets[: len(port_rets)])
    if corr > CORR_HIGH:
        alerts.append(
            {"level": "WARN", "type": "correlation", "detail": f"Portfolio-XBI corr {corr:.2f} > {CORR_HIGH}"}
        )

    # 4. Regime check (bull = model weakness)
    xbi_30d_ret = 0
    if len(xbi_prices) >= 22:
        xbi_30d_ret = xbi_prices[-1][1] / xbi_prices[-22][1] - 1

    regime = (
        "bear" if xbi_30d_ret < -BULL_XBI_THRESHOLD else ("bull" if xbi_30d_ret > BULL_XBI_THRESHOLD else "neutral")
    )
    if regime == "bull":
        alerts.append(
            {
                "level": "WARN",
                "type": "regime",
                "detail": f"Bull regime (XBI 30d: {xbi_30d_ret:+.1%}). Model IR is -0.13 in bull.",
            }
        )

    # 5. Earnings cluster
    as_of_d = date.fromisoformat(as_of_date)
    week_end = as_of_d + timedelta(days=7)
    earnings_this_week = []
    for r in ranked:
        if r["ticker"] not in portfolio_tickers:
            continue
        ed = r.get("next_earnings_date", "")
        if ed:
            try:
                edate = date.fromisoformat(ed)
                if as_of_d <= edate <= week_end:
                    earnings_this_week.append(r["ticker"])
            except ValueError:
                pass

    if len(earnings_this_week) >= EARNINGS_CLUSTER_WARN:
        alerts.append(
            {
                "level": "WARN",
                "type": "earnings_cluster",
                "detail": f"{len(earnings_this_week)} names reporting this week: {', '.join(earnings_this_week)}",
            }
        )

    # 6. Portfolio vol estimate + correlation clusters (v2)
    vol_metrics: dict[str, Any] = {}
    try:
        from portfolio_vol_corr_layer import build_vol_corr_snapshot

        ew_weight = 1.0 / max(len(portfolio_tickers), 1)
        weights = {t: ew_weight for t in portfolio_tickers}
        vcs = build_vol_corr_snapshot(
            PRICE_CSV,
            portfolio_tickers,
            weights,
            vol_target=VOL_TARGET,
            corr_threshold=CORR_CLUSTER_THRESHOLD,
            lookback_days=60,
            as_of_date=as_of_date,
        )
        vol_metrics = {
            "portfolio_vol_60d_annualized": vcs.portfolio_vol_annualized,
            "vol_target": vcs.vol_target,
            "vol_breach": vcs.vol_breach,
            "gross_exposure_scalar": vcs.gross_exposure_scalar,
            "avg_pairwise_corr_60d": vcs.avg_pairwise_corr,
            "max_cluster_size": vcs.max_cluster_size,
            "n_high_corr_pairs": len(vcs.high_corr_pairs),
            "top_high_corr_pairs": [(a, b, round(c, 3)) for a, b, c in vcs.high_corr_pairs[:5]],
            "n_tickers_imputed": vcs.n_tickers_imputed,
        }

        if vcs.portfolio_vol_annualized > VOL_TARGET * VOL_ALERT_BUFFER:
            alerts.append(
                {
                    "level": "WARN",
                    "type": "vol_breach",
                    "detail": f"Portfolio vol {vcs.portfolio_vol_annualized:.0%} > target {VOL_TARGET:.0%}",
                }
            )

        if vcs.max_cluster_size > CORR_CLUSTER_MAX:
            alerts.append(
                {
                    "level": "WARN",
                    "type": "corr_concentration",
                    "detail": f"Correlation cluster of {vcs.max_cluster_size} names (limit {CORR_CLUSTER_MAX})",
                }
            )
    except Exception as e:
        vol_metrics = {"error": str(e)}

    # Overall risk level
    n_crit = sum(1 for a in alerts if a["level"] == "CRITICAL")
    n_warn = sum(1 for a in alerts if a["level"] == "WARN")
    risk_level = "CRITICAL" if n_crit > 0 else ("ELEVATED" if n_warn >= 2 else ("WATCH" if n_warn > 0 else "NORMAL"))

    return {
        "schema": SCHEMA,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "risk_level": risk_level,
        "n_alerts": len(alerts),
        "alerts": alerts,
        "portfolio_size": len(portfolio_tickers),
        "metrics": {
            "avg_drawdown_63d": round(avg_dd, 4),
            "worst_drawdown_63d": round(worst_dd, 4),
            "worst_drawdown_ticker": worst_ticker,
            "xbi_drawdown_63d": round(xbi_dd, 4),
            "relative_drawdown": round(rel_dd, 4),
            "portfolio_xbi_corr_30d": round(corr, 4),
            "xbi_30d_return": round(xbi_30d_ret, 4),
            "regime": regime,
            "earnings_this_week": earnings_this_week,
            **vol_metrics,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Portfolio risk monitor")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    args = parser.parse_args()

    result = build_risk_report(args.as_of_date)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{args.as_of_date}_risk.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    m = result["metrics"]
    print(f"RISK MONITOR — {args.as_of_date}")
    print(f"  Level: {result['risk_level']} ({result['n_alerts']} alerts)")
    print(f"  Regime: {m['regime']} (XBI 30d: {m['xbi_30d_return']:+.1%})")
    print(
        f"  Drawdown: avg {m['avg_drawdown_63d']:.1%}, worst {m['worst_drawdown_63d']:.1%} ({m['worst_drawdown_ticker']})"
    )
    print(f"  Relative DD: {m['relative_drawdown']:+.1%} vs XBI")
    print(f"  Correlation: {m['portfolio_xbi_corr_30d']:.2f}")
    if m["earnings_this_week"]:
        print(f"  Earnings this week: {', '.join(m['earnings_this_week'])}")

    for a in result["alerts"]:
        print(f"  [{a['level']}] {a['type']}: {a['detail']}")

    print(f"\n  Saved: {out_path}")


if __name__ == "__main__":
    main()
