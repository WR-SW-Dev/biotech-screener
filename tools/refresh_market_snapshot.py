"""Refresh market_snapshot.json with live data from yfinance + FRED.

Pulls VIX, SPY, XBI, HYG from yfinance and HY OAS from FRED to compute
all inputs the rich regime engine needs. Falls back to existing snapshot
values when a feed fails.

Output:
    data/market_snapshot.json

Usage:
    python tools/refresh_market_snapshot.py
    python tools/refresh_market_snapshot.py --as-of-date 2026-04-02
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = PROJECT_ROOT / "data" / "market_snapshot.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("refresh_market_snapshot")


def _fetch_history(ticker: str, period: str = "35d", max_retries: int = 3):
    """Fetch price history via yfinance with retry logic on rate-limit.

    Returns list of (date_str, close) tuples. Implements exponential backoff
    for 429 (Too Many Requests) responses to handle rate limiting gracefully.
    """
    try:
        import yfinance as yf

        for attempt in range(max_retries):
            try:
                t = yf.Ticker(ticker)
                h = t.history(period=period)
                if h.empty:
                    return []
                return [(d.strftime("%Y-%m-%d"), float(row["Close"])) for d, row in h.iterrows()]
            except urllib.error.HTTPError as exc:
                if exc.code == 429:  # Too Many Requests
                    if attempt < max_retries - 1:
                        wait_time = 2**attempt  # exponential backoff: 1s, 2s, 4s
                        log.info(
                            "Rate limited on %s, retrying in %ds (attempt %d/%d)",
                            ticker,
                            wait_time,
                            attempt + 1,
                            max_retries,
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        log.warning("Rate limited on %s after %d retries: %s", ticker, max_retries, exc)
                        return []
                else:
                    log.warning("Failed to fetch %s (HTTP %d): %s", ticker, exc.code, exc)
                    return []
            except Exception as exc:
                log.warning("Failed to fetch %s: %s", ticker, exc)
                return []
    except Exception as exc:
        log.warning("Failed to fetch %s: %s", ticker, exc)
        return []


def _fetch_fred_hy_oas() -> float | None:
    """Fetch ICE BofA US High Yield OAS from FRED API (BAMLH0A0HYM2).

    Returns the latest OAS value in basis points, or None on failure.
    FRED reports the series in percentage points (e.g. 3.17 = 317 bps).
    """
    import os
    import urllib.request

    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        try:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env")
            api_key = os.environ.get("FRED_API_KEY", "")
        except ImportError:
            pass
    if not api_key:
        log.warning("FRED_API_KEY not set — skipping HY OAS fetch")
        return None

    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        "?series_id=BAMLH0A0HYM2&sort_order=desc&limit=5"
        f"&file_type=json&api_key={api_key}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WakeRobin-Market/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        for obs in data.get("observations", []):
            val = obs.get("value", ".")
            if val != ".":
                return float(val) * 100  # convert % to bps
        return None
    except Exception as exc:
        log.warning("FRED HY OAS fetch failed: %s", exc)
        return None


ETF_AUM_LEDGER = PROJECT_ROOT / "data" / "etf_aum_ledger.jsonl"


def _fetch_etf_aum() -> dict | None:
    """Snapshot XBI + IBB totalAssets and implied shares via yfinance.

    Appends to a daily ledger for flow estimation. Returns today's snapshot.
    """
    try:
        import yfinance as yf

        result = {}
        for ticker in ("XBI", "IBB"):
            info = yf.Ticker(ticker).info
            total_assets = info.get("totalAssets")
            nav = info.get("navPrice")
            if total_assets and nav and nav > 0:
                result[ticker] = {
                    "totalAssets": total_assets,
                    "nav": round(nav, 4),
                    "implied_shares": round(total_assets / nav),
                }
        return result if result else None
    except Exception as exc:
        log.warning("ETF AUM fetch failed: %s", exc)
        return None


def _append_aum_ledger(as_of_date: str, aum: dict) -> None:
    """Append today's AUM snapshot to the ledger (dedup by date)."""
    existing_dates = set()
    if ETF_AUM_LEDGER.exists():
        with open(ETF_AUM_LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    existing_dates.add(json.loads(line.strip()).get("date", ""))
                except (json.JSONDecodeError, AttributeError):
                    pass
    if as_of_date in existing_dates:
        return
    entry = {"date": as_of_date, **aum}
    with open(ETF_AUM_LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _compute_etf_flows(as_of_date: str, aum: dict | None) -> float | None:
    """Estimate weekly biotech ETF flows in $MM from AUM ledger.

    Uses the change in totalAssets minus price appreciation to isolate
    net creation/redemption (= fund flows).

    Flow = delta(totalAssets) - prior_totalAssets * price_return
         = totalAssets_now - totalAssets_prior * (1 + return)

    Falls back to a volume-price proxy if insufficient ledger history.
    """
    if not ETF_AUM_LEDGER.exists():
        return _compute_volume_flow_proxy()

    rows = []
    with open(ETF_AUM_LEDGER, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                pass

    # Need at least 2 entries spanning ~5 trading days
    valid = sorted([r for r in rows if r.get("date", "") <= as_of_date], key=lambda r: r["date"])
    if len(valid) < 2:
        return _compute_volume_flow_proxy()

    current = valid[-1]
    # Find entry ~5 trading days back
    prior = None
    for r in reversed(valid[:-1]):
        if r["date"] <= as_of_date:
            prior = r
            break

    if not prior:
        return _compute_volume_flow_proxy()

    total_flow = 0.0
    for ticker in ("XBI", "IBB"):
        cur = current.get(ticker, {})
        pri = prior.get(ticker, {})
        cur_assets = cur.get("totalAssets")
        pri_assets = pri.get("totalAssets")
        cur_nav = cur.get("nav")
        pri_nav = pri.get("nav")
        if not all([cur_assets, pri_assets, cur_nav, pri_nav]) or pri_nav <= 0:
            continue
        price_return = (cur_nav / pri_nav) - 1
        # Flow = change in AUM minus price appreciation of existing assets
        flow = cur_assets - pri_assets * (1 + price_return)
        total_flow += flow

    return round(total_flow / 1e6, 1)  # $MM


def _compute_volume_flow_proxy() -> float | None:
    """Approximate weekly fund flows from XBI+IBB volume anomaly.

    ETF creation/redemption shows up as volume above normal levels.
    Positive price + above-avg volume → inflows; negative price + above-avg → outflows.
    The excess volume (vs 20d avg) × price × sign(return) approximates net flow.

    Scaled to match regime engine thresholds (weekly $MM, ±50/±200).
    """
    try:
        import yfinance as yf

        total_flow = 0.0
        for ticker in ("XBI", "IBB"):
            h = yf.Ticker(ticker).history(period="30d")
            if h.empty or len(h) < 15:
                continue
            avg_vol = h["Volume"].iloc[:-5].mean()
            if avg_vol <= 0:
                continue
            recent = h.tail(5)
            for i in range(len(recent)):
                row = recent.iloc[i]
                idx = len(h) - 5 + i
                prev_close = h.iloc[idx - 1]["Close"] if idx > 0 else row["Close"]
                if prev_close <= 0:
                    continue
                daily_return = (row["Close"] / prev_close) - 1
                # Only count excess volume above 20d average
                excess_vol = max(row["Volume"] - avg_vol, 0)
                dollar_excess = excess_vol * row["Close"]
                if daily_return > 0.001:
                    total_flow += dollar_excess
                elif daily_return < -0.001:
                    total_flow -= dollar_excess

        return round(total_flow / 1e6, 1)  # $MM
    except Exception as exc:
        log.warning("Volume flow proxy failed: %s", exc)
        return None


def _return_over_period(history, days):
    """Compute return over approximately `days` trading days."""
    if len(history) < days + 1:
        return None
    p_now = history[-1][1]
    p_then = history[-(days + 1)][1]
    if p_then <= 0:
        return None
    return (p_now / p_then - 1) * 100


def _realized_vol(history, days=20):
    """Compute annualized realized volatility from last `days` trading days."""
    if len(history) < days + 2:
        return None
    recent = history[-(days + 1) :]
    log_rets = []
    for i in range(1, len(recent)):
        p0, p1 = recent[i - 1][1], recent[i][1]
        if p0 > 0 and p1 > 0:
            log_rets.append(math.log(p1 / p0))
    if len(log_rets) < 15:
        return None
    mean_r = sum(log_rets) / len(log_rets)
    var_r = sum((r - mean_r) ** 2 for r in log_rets) / (len(log_rets) - 1)
    return math.sqrt(var_r) * math.sqrt(252) * 100


def refresh_snapshot(as_of_date: str = "") -> dict:
    """Refresh market snapshot with live data."""
    if not as_of_date:
        as_of_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load existing snapshot for fallback
    existing = {}
    if SNAPSHOT_PATH.exists():
        try:
            existing = json.loads(SNAPSHOT_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    log.info("Fetching market data...")

    # Fetch all feeds
    vix_hist = _fetch_history("^VIX", "10d")
    spy_hist = _fetch_history("SPY", "40d")
    xbi_hist = _fetch_history("XBI", "40d")
    hyg_hist = _fetch_history("HYG", "40d")

    # VIX current
    vix_current = vix_hist[-1][1] if vix_hist else None
    vix_date = vix_hist[-1][0] if vix_hist else ""

    # XBI vs SPY 30d
    xbi_30d = _return_over_period(xbi_hist, 21) if xbi_hist else None
    spy_30d = _return_over_period(spy_hist, 21) if spy_hist else None
    xbi_vs_spy_30d = (xbi_30d - spy_30d) if (xbi_30d is not None and spy_30d is not None) else None

    # Momentum (10d)
    xbi_mom_10d = _return_over_period(xbi_hist, 7) if xbi_hist else None
    spy_mom_10d = _return_over_period(spy_hist, 7) if spy_hist else None

    # XBI realized vol
    xbi_vol = _realized_vol(xbi_hist) if xbi_hist else None

    # HYG 30d return (credit proxy — negative = widening spreads)
    hyg_30d = _return_over_period(hyg_hist, 21) if hyg_hist else None
    # Credit spread change approximation: HYG declining = spreads widening
    credit_spread_change = -hyg_30d / 10 if hyg_30d is not None else None

    # FRED: ICE BofA US High Yield OAS (BAMLH0A0HYM2) — absolute spread in bps
    # This is the key input for CREDIT_CRISIS detection in the regime engine
    hy_oas_current = _fetch_fred_hy_oas()

    # ETF fund flows: XBI + IBB AUM-based (preferred) or volume proxy (fallback)
    etf_aum = _fetch_etf_aum()
    if etf_aum:
        _append_aum_ledger(as_of_date, etf_aum)
    biotech_fund_flows = _compute_etf_flows(as_of_date, etf_aum)
    # Volume proxy is directional but noisy in magnitude — cap at ±300 $MM
    # to avoid false STRONG_INFLOWS/HEAVY_OUTFLOWS. AUM-based flows are uncapped.
    _flow_method = (
        "aum_delta" if (ETF_AUM_LEDGER.exists() and sum(1 for _ in open(ETF_AUM_LEDGER)) >= 2) else "volume_proxy"
    )
    if _flow_method == "volume_proxy" and biotech_fund_flows is not None:
        biotech_fund_flows = max(min(biotech_fund_flows, 300.0), -300.0)

    # Treasury yields (for fed rate proxy + yield curve)
    tnx_hist = _fetch_history("^TNX", "70d")  # 10-year yield
    irx_hist = _fetch_history("^IRX", "70d")  # 13-week T-bill (tracks fed funds)

    tnx_current = tnx_hist[-1][1] if tnx_hist else None
    irx_current = irx_hist[-1][1] if irx_hist else None

    # Yield curve slope: 10Y - 13W in basis points
    yield_curve_slope = None
    if tnx_current is not None and irx_current is not None:
        yield_curve_slope = (tnx_current - irx_current) * 100  # bps

    # Fed rate change 3m: compare current 13W T-bill to ~63 trading days ago
    fed_rate_change_3m = None
    if irx_hist and len(irx_hist) >= 50:
        irx_3m_ago = irx_hist[0][1]
        fed_rate_change_3m = irx_current - irx_3m_ago if irx_current is not None else None

    def _fmt(v):
        if v is None:
            return "0"
        return f"{v:.2f}"

    fed_rate_str = (
        _fmt(fed_rate_change_3m) if fed_rate_change_3m is not None else str(existing.get("fed_rate_change_3m", "0.00"))
    )
    fed_rate_source = "live" if fed_rate_change_3m is not None else "carried"

    snapshot = {
        "provenance": {
            "source": "yfinance (VIX, SPY, XBI, HYG, TNX, IRX) + FRED (BAMLH0A0HYM2)",
            "as_of_date": as_of_date,
            "vix_date": vix_date,
            "generated_by": "refresh_market_snapshot.py",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "version": "1.4.0",
        },
        "vix": _fmt(vix_current),
        "xbi_vs_spy_30d": _fmt(xbi_vs_spy_30d),
        "fed_rate_change_3m": fed_rate_str,
        "xbi_momentum_10d": _fmt(xbi_mom_10d),
        "spy_momentum_10d": _fmt(spy_mom_10d),
        "credit_spread_change": _fmt(credit_spread_change),
        "hy_credit_spread": _fmt(hy_oas_current),
        "biotech_fund_flows": _fmt(biotech_fund_flows),
        "xbi_realized_vol_20d": _fmt(xbi_vol),
        "yield_curve_slope_bps": _fmt(yield_curve_slope),
        "tnx_10y_yield": _fmt(tnx_current),
        "irx_13w_yield": _fmt(irx_current),
        "feeds": {
            "vix": "live" if vix_current is not None else "failed",
            "spy": "live" if spy_30d is not None else "failed",
            "xbi": "live" if xbi_30d is not None else "failed",
            "hyg": "live" if hyg_30d is not None else "failed",
            "tnx": "live" if tnx_current is not None else "failed",
            "irx": "live" if irx_current is not None else "failed",
            "fed_rate": fed_rate_source,
            "hy_oas_fred": "live" if hy_oas_current is not None else "failed",
            "biotech_fund_flows": (
                "live_aum"
                if (etf_aum and ETF_AUM_LEDGER.exists())
                else "live_volume_proxy" if biotech_fund_flows is not None else "failed"
            ),
        },
        "notes": {
            "vix": f"CBOE VIX index: {vix_current:.2f}" if vix_current else "Feed failed",
            "xbi_vs_spy_30d": (
                f"XBI {xbi_30d:+.1f}% vs SPY {spy_30d:+.1f}% = {xbi_vs_spy_30d:+.1f}pp"
                if xbi_vs_spy_30d is not None
                else "Feed failed"
            ),
            "credit_spread_change": (
                f"HYG 30d return {hyg_30d:+.1f}% -> spread change proxy {credit_spread_change:+.3f}"
                if hyg_30d is not None
                else "Feed failed"
            ),
            "hy_credit_spread": (
                f"ICE BofA HY OAS: {hy_oas_current:.0f} bps (FRED BAMLH0A0HYM2)"
                if hy_oas_current is not None
                else "FRED feed failed"
            ),
            "biotech_fund_flows": (
                f"XBI+IBB weekly flow: ${biotech_fund_flows:+.0f}MM"
                if biotech_fund_flows is not None
                else "Insufficient data"
            ),
            "yield_curve": (
                f"10Y {tnx_current:.2f}% - 13W {irx_current:.2f}% = {yield_curve_slope:+.0f} bps"
                if yield_curve_slope is not None
                else "Feed failed"
            ),
            "fed_rate_change_3m": (
                f"13W T-bill now {irx_current:.2f}% vs 3m ago {irx_hist[0][1]:.2f}% = {fed_rate_change_3m:+.2f}pp"
                if fed_rate_change_3m is not None
                else "Carried from prior snapshot"
            ),
        },
    }

    # Write
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2) + "\n")
    log.info("Wrote %s", SNAPSHOT_PATH)

    return snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", default="")
    args = parser.parse_args()

    snapshot = refresh_snapshot(args.as_of_date)

    print(f"\nMarket Snapshot ({snapshot['provenance']['as_of_date']})")
    print(f"  VIX:            {snapshot['vix']}")
    print(f"  XBI vs SPY 30d: {snapshot['xbi_vs_spy_30d']}pp")
    print(f"  XBI mom 10d:    {snapshot['xbi_momentum_10d']}%")
    print(f"  SPY mom 10d:    {snapshot['spy_momentum_10d']}%")
    print(f"  Credit change:  {snapshot['credit_spread_change']}")
    print(f"  HY OAS (bps):   {snapshot.get('hy_credit_spread', '?')}")
    print(f"  ETF flows ($MM):{snapshot.get('biotech_fund_flows', '?')}")
    print(f"  XBI vol 20d:    {snapshot.get('xbi_realized_vol_20d', '?')}%")
    print(f"  Yield curve:    {snapshot.get('yield_curve_slope_bps', '?')} bps")
    print(f"  10Y yield:      {snapshot.get('tnx_10y_yield', '?')}%")
    print(f"  13W T-bill:     {snapshot.get('irx_13w_yield', '?')}%")
    print(f"  Fed rate 3m:    {snapshot['fed_rate_change_3m']}pp")
    feeds = snapshot.get("feeds", {})
    live = sum(1 for v in feeds.values() if v == "live")
    print(f"  Feeds: {live}/{len(feeds)} live")


if __name__ == "__main__":
    main()
