#!/usr/bin/env python3
"""Backfill regime detection history from 2020-01-01 to present.

Downloads historical market data (VIX, SPY, XBI, HYG, TNX, IRX) via yfinance,
fetches HY OAS from FRED, then runs both regime classifiers for each weekly
date to produce a complete regime history.

Outputs:
    artifacts/regime_shadow/history.jsonl — one row per date
    artifacts/regime_shadow/history_summary.csv — condensed CSV for analysis

Usage:
    python3 scripts/backfill_regime_history.py
    python3 scripts/backfill_regime_history.py --start 2022-01-01
    python3 scripts/backfill_regime_history.py --freq daily
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "regime_shadow"
HISTORY_JSONL = OUTPUT_DIR / "history.jsonl"
HISTORY_CSV = OUTPUT_DIR / "history_summary.csv"
CACHE_DIR = PROJECT_ROOT / "data" / "regime_backfill_cache"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("regime_backfill")


# ---------------------------------------------------------------------------
# Data fetching (cached)
# ---------------------------------------------------------------------------


def _fetch_yfinance_history(ticker: str, start: str, end: str) -> Dict[str, Dict[str, float]]:
    """Fetch daily OHLCV from yfinance. Returns {date_str: {close, volume}}."""
    cache_path = CACHE_DIR / f"{ticker.replace('^', '_')}_{start}_{end}.json"
    if cache_path.exists():
        log.info("Cache hit: %s", cache_path.name)
        return json.loads(cache_path.read_text())

    import yfinance as yf

    log.info("Fetching %s from %s to %s...", ticker, start, end)
    t = yf.Ticker(ticker)
    h = t.history(start=start, end=end)
    if h.empty:
        log.warning("No data for %s", ticker)
        return {}

    result = {}
    for dt, row in h.iterrows():
        d = dt.strftime("%Y-%m-%d")
        result[d] = {"close": float(row["Close"]), "volume": float(row.get("Volume", 0))}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result))
    log.info("Cached %s: %d dates", ticker, len(result))
    return result


def _fetch_fred_hy_oas_history(start: str, end: str) -> Dict[str, float]:
    """Fetch ICE BofA HY OAS history from FRED. Returns {date: oas_bps}."""
    cache_path = CACHE_DIR / f"BAMLH0A0HYM2_{start}_{end}.json"
    if cache_path.exists():
        log.info("Cache hit: %s", cache_path.name)
        return json.loads(cache_path.read_text())

    import urllib.request

    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        log.warning("No FRED_API_KEY — skipping HY OAS")
        return {}

    # FRED API limits to 100k observations per request, plenty for our range
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id=BAMLH0A0HYM2"
        f"&observation_start={start}&observation_end={end}"
        f"&sort_order=asc&file_type=json&api_key={api_key}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WakeRobin/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        result = {}
        for obs in data.get("observations", []):
            val = obs.get("value", ".")
            if val != ".":
                result[obs["date"]] = float(val) * 100  # % to bps

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result))
        log.info("FRED HY OAS: %d dates", len(result))
        return result
    except Exception as exc:
        log.warning("FRED fetch failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Market metric computation (mirrors refresh_market_snapshot.py)
# ---------------------------------------------------------------------------


def _get_return(prices: Dict[str, Dict], dt: str, lookback: int) -> Optional[float]:
    """Get return over lookback trading days ending on dt."""
    sorted_dates = sorted(d for d in prices if d <= dt)
    if len(sorted_dates) < lookback + 1:
        return None
    p_now = prices[sorted_dates[-1]]["close"]
    p_then = prices[sorted_dates[-(lookback + 1)]]["close"]
    if p_then <= 0:
        return None
    return (p_now / p_then - 1) * 100


def _get_realized_vol(prices: Dict[str, Dict], dt: str, window: int = 20) -> Optional[float]:
    """Annualized realized vol ending on dt."""
    sorted_dates = sorted(d for d in prices if d <= dt)
    if len(sorted_dates) < window + 2:
        return None
    recent = sorted_dates[-(window + 1) :]
    log_rets = []
    for i in range(1, len(recent)):
        p0 = prices[recent[i - 1]]["close"]
        p1 = prices[recent[i]]["close"]
        if p0 > 0 and p1 > 0:
            log_rets.append(math.log(p1 / p0))
    if len(log_rets) < 15:
        return None
    mean_r = sum(log_rets) / len(log_rets)
    var_r = sum((r - mean_r) ** 2 for r in log_rets) / (len(log_rets) - 1)
    return math.sqrt(var_r) * math.sqrt(252) * 100


def _find_closest_value(lookup: Dict[str, float], dt: str, max_gap: int = 5) -> Optional[float]:
    """Find value on dt or up to max_gap days before."""
    d = date.fromisoformat(dt)
    for offset in range(max_gap + 1):
        key = (d - timedelta(days=offset)).isoformat()
        if key in lookup:
            return lookup[key]
    return None


def _compute_volume_flow_proxy(
    xbi: Dict[str, Dict],
    ibb: Optional[Dict[str, Dict]],
    dt: str,
    lookback: int = 5,
    avg_window: int = 20,
) -> Optional[float]:
    """Estimate weekly ETF flows ($MM) from volume anomaly for backfill.

    Mirrors refresh_market_snapshot._compute_volume_flow_proxy but uses cached data.
    Excess volume (vs avg_window mean) × close × sign(return) summed over lookback days.
    """
    total_flow = 0.0
    for data in (xbi, ibb):
        if data is None:
            continue
        sorted_dates = sorted(d for d in data if d <= dt)
        if len(sorted_dates) < avg_window + lookback + 1:
            continue
        # 20d average volume (excluding last 5 days)
        avg_dates = sorted_dates[-(avg_window + lookback) : -lookback]
        avg_vol = sum(data[d].get("volume", 0) for d in avg_dates) / len(avg_dates) if avg_dates else 0
        if avg_vol <= 0:
            continue
        recent = sorted_dates[-lookback:]
        for i, d in enumerate(recent):
            vol = data[d].get("volume", 0)
            close = data[d].get("close", 0)
            prev_d = sorted_dates[sorted_dates.index(d) - 1]
            prev_close = data[prev_d].get("close", 0)
            if prev_close <= 0 or close <= 0:
                continue
            daily_ret = (close / prev_close) - 1
            excess_vol = max(vol - avg_vol, 0)
            dollar_excess = excess_vol * close
            if daily_ret > 0.001:
                total_flow += dollar_excess
            elif daily_ret < -0.001:
                total_flow -= dollar_excess

    return round(total_flow / 1e6, 1) if total_flow != 0 else 0.0


def compute_market_inputs(
    dt: str,
    xbi: Dict,
    spy: Dict,
    vix: Dict,
    hyg: Dict,
    tnx: Dict,
    irx: Dict,
    hy_oas: Dict,
    ibb: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Compute all regime engine inputs for a given date."""
    vix_val = _find_closest_value({d: v["close"] for d, v in vix.items()}, dt)
    xbi_30d = _get_return(xbi, dt, 21)
    spy_30d = _get_return(spy, dt, 21)
    xbi_vs_spy = (xbi_30d - spy_30d) if (xbi_30d is not None and spy_30d is not None) else None
    xbi_mom_10d = _get_return(xbi, dt, 7)

    # HYG credit proxy
    hyg_30d = _get_return(hyg, dt, 21)
    credit_change = -hyg_30d / 10 if hyg_30d is not None else None

    # Treasury yields
    tnx_val = _find_closest_value({d: v["close"] for d, v in tnx.items()}, dt)
    irx_val = _find_closest_value({d: v["close"] for d, v in irx.items()}, dt)
    yield_curve = (tnx_val - irx_val) * 100 if (tnx_val is not None and irx_val is not None) else None

    # Fed rate change
    irx_dates = sorted(d for d in irx if d <= dt)
    fed_change = None
    if len(irx_dates) >= 50:
        irx_now = irx[irx_dates[-1]]["close"]
        irx_3m = irx[irx_dates[-min(63, len(irx_dates))]]["close"]
        fed_change = irx_now - irx_3m

    # HY OAS from FRED
    hy_oas_val = _find_closest_value(hy_oas, dt)

    # Biotech ETF fund flows (volume proxy)
    fund_flows = _compute_volume_flow_proxy(xbi, ibb, dt)

    return {
        "vix": vix_val,
        "xbi_vs_spy_30d": xbi_vs_spy,
        "xbi_momentum_10d": xbi_mom_10d,
        "fed_rate_change_3m": fed_change,
        "yield_curve_slope": yield_curve,
        "credit_spread_change": credit_change,
        "hy_credit_spread": hy_oas_val,
        "biotech_fund_flows": fund_flows,
    }


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------


def run_regime_for_date(
    dt: str,
    all_prices: Dict[str, Dict[str, float]],
    market: Dict[str, Any],
) -> Dict[str, Any]:
    """Run both classifiers for a single date."""
    from regime_engine import RegimeDetectionEngine
    from tools.construction_v2_shadow import RegimeClassifier

    # Simple classifier
    clf = RegimeClassifier()
    sorted_dates = sorted(d for d in all_prices if d <= dt)
    for d in sorted_dates[-60:]:  # warm up with last 60 dates
        clf.classify(all_prices, d)
    simple_regime = clf.classify(all_prices, dt).upper()

    # Rich classifier
    engine = RegimeDetectionEngine()
    vix = market.get("vix")
    xbi_spy = market.get("xbi_vs_spy_30d")

    if vix is None or xbi_spy is None:
        return {
            "date": dt,
            "simple": simple_regime,
            "rich": "INSUFFICIENT_DATA",
            "rich_confidence": 0,
            "agreement": False,
        }

    kwargs = dict(
        vix_current=Decimal(str(vix)),
        xbi_vs_spy_30d=Decimal(str(xbi_spy)),
        fed_rate_change_3m=Decimal(str(market.get("fed_rate_change_3m") or 0)),
        as_of_date=date.fromisoformat(dt),
        use_ensemble=False,
    )
    mom = market.get("xbi_momentum_10d")
    if mom is not None:
        kwargs["xbi_momentum_10d"] = Decimal(str(mom))
    yc = market.get("yield_curve_slope")
    if yc is not None:
        kwargs["yield_curve_slope"] = Decimal(str(yc))
    cc = market.get("credit_spread_change")
    if cc is not None:
        kwargs["credit_spread_change"] = Decimal(str(cc))
    hy = market.get("hy_credit_spread")
    if hy is not None:
        kwargs["hy_credit_spread"] = Decimal(str(hy))
    ff = market.get("biotech_fund_flows")
    if ff is not None:
        kwargs["biotech_fund_flows"] = Decimal(str(ff))

    try:
        result = engine.detect_regime(**kwargs)
        rich_regime = result.get("regime", "UNKNOWN")
        rich_conf = float(result.get("confidence", 0))
        scores = {k: float(v) for k, v in result.get("regime_scores", {}).items()}
        credit_env = result.get("indicators", {}).get("credit_environment", "UNKNOWN")
    except Exception as exc:
        log.warning("Rich classifier failed for %s: %s", dt, exc)
        rich_regime = "ERROR"
        rich_conf = 0
        scores = {}
        credit_env = "UNKNOWN"

    agree = (simple_regime == "BULL" and rich_regime == "BULL") or (simple_regime != "BULL" and rich_regime != "BULL")

    return {
        "date": dt,
        "simple": simple_regime,
        "rich": rich_regime,
        "rich_confidence": round(rich_conf, 3),
        "agreement": agree,
        "scores": scores,
        "vix": round(vix, 2) if vix else None,
        "xbi_vs_spy_30d": round(xbi_spy, 2) if xbi_spy else None,
        "xbi_momentum_10d": round(mom, 2) if mom else None,
        "hy_oas_bps": round(hy, 0) if hy else None,
        "yield_curve_bps": round(yc, 0) if yc else None,
        "credit_environment": credit_env,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def get_target_dates(start: str, end: str, freq: str = "weekly") -> List[str]:
    """Generate target dates (every Monday for weekly, or every trading day)."""
    d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    dates = []
    if freq == "weekly":
        # Align to Monday
        while d.weekday() != 0:
            d += timedelta(days=1)
        while d <= end_d:
            dates.append(d.isoformat())
            d += timedelta(days=7)
    else:
        while d <= end_d:
            if d.weekday() < 5:  # Mon-Fri
                dates.append(d.isoformat())
            d += timedelta(days=1)
    return dates


def main():
    parser = argparse.ArgumentParser(description="Backfill regime detection history")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--freq", default="weekly", choices=["weekly", "daily"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target_dates = get_target_dates(args.start, args.end, args.freq)
    log.info("Target dates: %d (%s to %s, %s)", len(target_dates), args.start, args.end, args.freq)

    if args.dry_run:
        for d in target_dates[:5]:
            print(f"  {d}")
        print(f"  ... ({len(target_dates)} total)")
        return

    # Load existing results to skip completed dates
    existing = set()
    if HISTORY_JSONL.exists():
        with open(HISTORY_JSONL, encoding="utf-8") as f:
            for line in f:
                try:
                    existing.add(json.loads(line.strip()).get("date", ""))
                except (json.JSONDecodeError, AttributeError):
                    pass
    remaining = [d for d in target_dates if d not in existing]
    log.info("Already done: %d, remaining: %d", len(existing), len(remaining))

    if not remaining:
        log.info("All dates already backfilled")
        return

    # Fetch all historical data (cached after first run)
    # Use 30d buffer before start for lookback calculations
    fetch_start = (date.fromisoformat(args.start) - timedelta(days=100)).isoformat()
    fetch_end = args.end

    xbi = _fetch_yfinance_history("XBI", fetch_start, fetch_end)
    spy = _fetch_yfinance_history("SPY", fetch_start, fetch_end)
    vix = _fetch_yfinance_history("^VIX", fetch_start, fetch_end)
    hyg = _fetch_yfinance_history("HYG", fetch_start, fetch_end)
    tnx = _fetch_yfinance_history("^TNX", fetch_start, fetch_end)
    irx = _fetch_yfinance_history("^IRX", fetch_start, fetch_end)
    ibb = _fetch_yfinance_history("IBB", fetch_start, fetch_end)
    hy_oas = _fetch_fred_hy_oas_history(fetch_start, fetch_end)

    log.info(
        "Data loaded — XBI:%d SPY:%d VIX:%d HYG:%d TNX:%d IRX:%d IBB:%d HY_OAS:%d",
        len(xbi),
        len(spy),
        len(vix),
        len(hyg),
        len(tnx),
        len(irx),
        len(ibb),
        len(hy_oas),
    )

    # Build price map for simple classifier: {date: {ticker: close}}
    all_price_dates = sorted(set(xbi.keys()) & set(spy.keys()))
    all_prices: Dict[str, Dict[str, float]] = {}
    for d in all_price_dates:
        all_prices[d] = {"XBI": xbi[d]["close"]}
        if d in spy:
            all_prices[d]["SPY"] = spy[d]["close"]

    # Process each date
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for i, dt in enumerate(remaining):
        if (i + 1) % 50 == 0 or i == 0:
            log.info("Processing %d/%d: %s", i + 1, len(remaining), dt)

        market = compute_market_inputs(dt, xbi, spy, vix, hyg, tnx, irx, hy_oas, ibb=ibb)
        row = run_regime_for_date(dt, all_prices, market)
        results.append(row)

        # Append to JSONL incrementally
        with open(HISTORY_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")

    # Rebuild summary CSV from full JSONL
    all_rows = []
    with open(HISTORY_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                all_rows.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                pass
    all_rows.sort(key=lambda r: r["date"])

    csv_fields = [
        "date",
        "simple",
        "rich",
        "rich_confidence",
        "agreement",
        "vix",
        "xbi_vs_spy_30d",
        "xbi_momentum_10d",
        "hy_oas_bps",
        "yield_curve_bps",
        "credit_environment",
    ]
    with open(HISTORY_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(all_rows)

    # Summary stats
    n_agree = sum(1 for r in all_rows if r.get("agreement"))
    n_bull = sum(1 for r in all_rows if r.get("simple") == "BULL")
    n_bear_rich = sum(1 for r in all_rows if r.get("rich") in ("BEAR", "CREDIT_CRISIS", "RECESSION_RISK"))

    log.info("\n%s", "=" * 60)
    log.info("REGIME BACKFILL COMPLETE")
    log.info("  Dates: %d total (%d new)", len(all_rows), len(results))
    log.info("  Range: %s to %s", all_rows[0]["date"], all_rows[-1]["date"])
    log.info("  Agreement rate: %.1f%%", 100 * n_agree / len(all_rows))
    log.info("  Simple BULL: %.1f%%", 100 * n_bull / len(all_rows))
    log.info("  Rich BEAR/CRISIS/RECESSION: %.1f%%", 100 * n_bear_rich / len(all_rows))
    log.info("  Saved: %s", HISTORY_CSV)


if __name__ == "__main__":
    main()
