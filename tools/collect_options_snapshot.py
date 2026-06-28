#!/usr/bin/env python3
"""Daily options IV snapshot collector — tastytrade market metrics.

Fetches ATM IV, IV rank, term structure, event premium, and liquidity state
for all active universe tickers via tastytrade market metrics API.

Writes dated snapshot to:
    production_data/options_snapshot_{as_of_date}.json

Also writes/overwrites the rolling latest:
    production_data/options_snapshot_latest.json

Governance:
    OBSERVABILITY_ONLY / NO_MODEL_CHANGE / NO_RANKER_CHANGE /
    NO_SELECTOR_CHANGE / NO_SCORING_CHANGE / NO_TRADING_CHANGE

Usage:
    python3 tools/collect_options_snapshot.py
    python3 tools/collect_options_snapshot.py --date 2026-06-28
    python3 tools/collect_options_snapshot.py --batch-size 100 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")


def _d(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_term(exp_ivs, today: date):
    """Return (front_iv, back_iv, term_slope, event_premium) from expiry list."""
    if not exp_ivs:
        return None, None, None, None
    future = [
        (e.expiration_date, _d(e.implied_volatility))
        for e in exp_ivs
        if e.expiration_date >= today and _d(e.implied_volatility) is not None
    ]
    if not future:
        return None, None, None, None
    future.sort()
    front_date, front_iv = future[0]
    back_iv = None
    for exp_date, iv in future[1:]:
        if (exp_date - front_date).days >= 14:
            back_iv = iv
            break
    slope = event_prem = None
    if front_iv and back_iv:
        slope = round((back_iv - front_iv) / front_iv, 6)
        event_prem = "YES" if (front_iv - back_iv) / back_iv > 0.10 else "NO"
    return front_iv, back_iv, slope, event_prem


def _iv_regime(atm_iv: float | None) -> str | None:
    if atm_iv is None:
        return None
    if atm_iv > 2.0:
        return "EXTREME"
    if atm_iv > 1.0:
        return "ELEVATED"
    if atm_iv > 0.4:
        return "NORMAL"
    return "LOW"


def _liq_state(liq: float | None) -> str:
    if liq is None or liq == 0:
        return "absent"
    if liq > 0.005:
        return "liquid"
    if liq > 0.0002:
        return "thin"
    return "absent"


def load_universe_tickers(universe_path: Path) -> list[str]:
    u = json.loads(universe_path.read_text())
    items = u if isinstance(u, list) else u.get("universe", u.get("tickers", []))
    tickers = []
    for item in items:
        if isinstance(item, dict):
            t = item.get("ticker", "")
            s = item.get("status", "active")
            if t and not t.startswith("_") and s != "delisted":
                tickers.append(t)
        elif isinstance(item, str) and not item.startswith("_"):
            tickers.append(item)
    return tickers


async def _fetch(tickers: list[str], batch_size: int, verbose: bool) -> dict:
    from tastytrade import Session
    from tastytrade.metrics import get_market_metrics

    session = Session(is_test=False)
    snapshot: dict = {}
    today = date.today()
    fetch_ts = datetime.now(timezone.utc).isoformat()
    n_batches = math.ceil(len(tickers) / batch_size)

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        bn = i // batch_size + 1
        if verbose:
            print(f"  Batch {bn}/{n_batches} ({len(batch)} tickers)...", end=" ", flush=True)
        try:
            metrics = await get_market_metrics(session, batch)
            for m in metrics:
                sym = m.symbol
                front_iv, back_iv, slope, event_prem = _parse_term(
                    m.option_expiration_implied_volatilities or [], today
                )
                atm_iv = _d(m.implied_volatility_index)
                liq = _d(m.liquidity_rank)
                ls = _liq_state(liq)
                regime = _iv_regime(atm_iv)
                usable = "YES" if (atm_iv is not None and ls != "absent" and regime != "EXTREME") else "NO"
                snapshot[sym] = {
                    "opt_has_data": 1 if atm_iv is not None else 0,
                    "opt_quote_ts": fetch_ts,
                    "opt_atm_iv": atm_iv,
                    "opt_iv_rank_tos": _d(m.tos_implied_volatility_index_rank),
                    "opt_iv_rank_tw": _d(m.tw_implied_volatility_index_rank),
                    "opt_iv_percentile": (
                        float(m.implied_volatility_percentile) if m.implied_volatility_percentile else None
                    ),
                    "opt_iv_5d_change": _d(m.implied_volatility_index_5_day_change),
                    "opt_iv_30d": _d(m.implied_volatility_30_day),
                    "opt_hv_30d": _d(m.historical_volatility_30_day),
                    "opt_hv_60d": _d(m.historical_volatility_60_day),
                    "opt_hv_90d": _d(m.historical_volatility_90_day),
                    "opt_iv_hv_spread": _d(m.iv_hv_30_day_difference),
                    "opt_front_iv": front_iv,
                    "opt_back_iv": back_iv,
                    "opt_term_slope": slope,
                    "opt_event_premium": event_prem,
                    "opt_iv_regime": regime,
                    "opt_liquidity_rank": liq,
                    "opt_liquidity_state": ls,
                    "opt_use_for_judgment": usable,
                }
            if verbose:
                print(f"OK ({len(metrics)} returned)")
        except Exception as e:
            if verbose:
                print(f"FAIL: {str(e)[:100]}")

    return snapshot


def build_output(snapshot: dict, tickers: list[str], as_of_date: str) -> dict:
    fetch_ts = next((v["opt_quote_ts"] for v in snapshot.values()), datetime.now(timezone.utc).isoformat())
    has_data = sum(1 for v in snapshot.values() if v["opt_has_data"])
    liquid = sum(1 for v in snapshot.values() if v["opt_liquidity_state"] == "liquid")
    thin = sum(1 for v in snapshot.values() if v["opt_liquidity_state"] == "thin")
    usable = sum(1 for v in snapshot.values() if v["opt_use_for_judgment"] == "YES")
    extreme = sum(1 for v in snapshot.values() if v["opt_iv_regime"] == "EXTREME")
    elevated = sum(1 for v in snapshot.values() if v["opt_iv_regime"] == "ELEVATED")
    event_p = sum(1 for v in snapshot.values() if v["opt_event_premium"] == "YES")
    return {
        "metadata": {
            "fetch_timestamp": fetch_ts,
            "as_of_date": as_of_date,
            "source": "tastytrade_market_metrics",
            "universe_count": len(tickers),
            "returned_count": len(snapshot),
            "has_options_data": has_data,
            "liquid_count": liquid,
            "thin_count": thin,
            "usable_for_judgment": usable,
            "iv_regime_extreme": extreme,
            "iv_regime_elevated": elevated,
            "event_premium_detected": event_p,
        },
        "tickers": snapshot,
    }


def run(as_of_date: str, batch_size: int, dry_run: bool, verbose: bool) -> dict:
    data_dir = REPO_ROOT / "production_data"
    universe_path = data_dir / "universe.json"

    tickers = load_universe_tickers(universe_path)
    if verbose:
        print(f"Universe tickers: {len(tickers)}")

    snapshot = asyncio.run(_fetch(tickers, batch_size, verbose))
    output = build_output(snapshot, tickers, as_of_date)

    if not dry_run:
        dated = data_dir / f"options_snapshot_{as_of_date}.json"
        latest = data_dir / "options_snapshot_latest.json"
        text = json.dumps(output, indent=2, default=str)
        dated.write_text(text)
        latest.write_text(text)
        if verbose:
            print(f"Written: {dated} ({dated.stat().st_size / 1e6:.2f} MB)")
            print(f"Written: {latest}")

    meta = output["metadata"]
    if verbose:
        print(
            f"\nSummary: {meta['returned_count']}/{meta['universe_count']} fetched | "
            f"liquid={meta['liquid_count']} thin={meta['thin_count']} | "
            f"usable={meta['usable_for_judgment']} | "
            f"event_premium={meta['event_premium_detected']}"
        )

    return output


def main():
    parser = argparse.ArgumentParser(description="Daily options IV snapshot — tastytrade")
    parser.add_argument("--date", default=date.today().isoformat(), help="As-of date (YYYY-MM-DD)")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not write files")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    run(args.date, args.batch_size, args.dry_run, verbose=not args.quiet)


if __name__ == "__main__":
    main()
