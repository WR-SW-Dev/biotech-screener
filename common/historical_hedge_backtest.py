"""Historical hedge backtest using Massive day-agg option closes.

Spec 028 scope — replaces BS-based monthly repricing in bioshort with
actual historical option closes from Massive flat files.

Design:
    1. For each backtest month, find the nearest-expiry contracts that
       match the hedge structure spec (strike offset, contract type).
    2. Price entry at the structure's entry-date day_close and exit at
       month-end/expiry day_close (whichever comes first).
    3. Fall back to BS theoretical pricing when a contract/date print is
       missing (common for illiquid deep OTM strikes).

Data source: ingest_day_aggs() from common/options_history_massive.py
    → S3 flat files: us_options_opra/day_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz
    → Schema: option_ticker, underlying_ticker, date, open, high, low,
              close, volume, transactions, source

Caching: day-agg files are cached locally after first download.
    Re-downloads are skipped unless force=True.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("historical_hedge_backtest")


# ---------------------------------------------------------------------------
# Contract matching
# ---------------------------------------------------------------------------


def _parse_option_ticker(ticker: str) -> Dict[str, Any]:
    """Parse O:XBI260320P00120000 → underlying, expiry, type, strike."""
    t = ticker
    if t.startswith("O:"):
        t = t[2:]
    if len(t) < 15:
        return {}
    i = 0
    while i < len(t) and t[i].isalpha():
        i += 1
    underlying = t[:i].upper()
    rest = t[i:]
    if len(rest) < 15:
        return {}
    try:
        yy, mm, dd = int(rest[:2]), int(rest[2:4]), int(rest[4:6])
        expiry = f"20{yy:02d}-{mm:02d}-{dd:02d}"
    except (ValueError, IndexError):
        return {}
    opt_type = "call" if rest[6] == "C" else "put" if rest[6] == "P" else ""
    try:
        strike = int(rest[7:15]) / 1000.0
    except (ValueError, IndexError):
        return {}
    return {
        "underlying": underlying,
        "expiry": expiry,
        "option_type": opt_type,
        "strike": strike,
    }


def find_best_contract(
    day_agg_records: List[Dict[str, Any]],
    underlying: str,
    target_strike: float,
    contract_type: str,
    min_expiry: str,
    max_expiry: str,
) -> Optional[Dict[str, Any]]:
    """Find the best-matching contract from day-agg records.

    Picks the contract closest to target_strike with expiry in
    [min_expiry, max_expiry] and non-zero close price.
    """
    candidates = []
    for rec in day_agg_records:
        if rec.get("underlying_ticker") != underlying:
            continue
        close = rec.get("close")
        if close is None or close <= 0:
            continue
        parsed = _parse_option_ticker(rec.get("option_ticker", ""))
        if not parsed:
            continue
        if parsed["option_type"] != contract_type:
            continue
        exp = parsed["expiry"]
        if exp < min_expiry or exp > max_expiry:
            continue
        candidates.append(
            {
                "option_ticker": rec["option_ticker"],
                "strike": parsed["strike"],
                "expiry": parsed["expiry"],
                "close": close,
                "volume": rec.get("volume") or 0,
            }
        )

    if not candidates:
        return None

    # Prefer the closest strike; break ties by higher volume
    candidates.sort(key=lambda c: (abs(c["strike"] - target_strike), -c["volume"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# Historical pricing for a structure
# ---------------------------------------------------------------------------


def price_structure_historical(
    struct_type: str,
    offsets: Dict[str, float],
    etf_price: float,
    underlying: str,
    entry_records: List[Dict[str, Any]],
    exit_records: List[Dict[str, Any]],
    min_expiry: str,
    max_expiry: str,
    contracts: int,
) -> Dict[str, Any]:
    """Price a hedge structure using actual historical option closes.

    Returns dict with entry_cost, exit_value, pnl, pricing_source,
    and per-leg detail.
    """
    legs: List[Dict[str, Any]] = []

    if struct_type == "straight_put":
        K = etf_price * (1 + offsets.get("put", -0.05))
        entry_leg = find_best_contract(entry_records, underlying, K, "put", min_expiry, max_expiry)
        exit_leg = find_best_contract(exit_records, underlying, K, "put", min_expiry, max_expiry)
        legs.append(_make_leg("buy_put", K, entry_leg, exit_leg))

    elif struct_type == "put_spread":
        K_buy = etf_price * (1 + offsets.get("buy_put", -0.05))
        K_sell = etf_price * (1 + offsets.get("sell_put", -0.15))
        entry_buy = find_best_contract(entry_records, underlying, K_buy, "put", min_expiry, max_expiry)
        exit_buy = find_best_contract(exit_records, underlying, K_buy, "put", min_expiry, max_expiry)
        entry_sell = find_best_contract(entry_records, underlying, K_sell, "put", min_expiry, max_expiry)
        exit_sell = find_best_contract(exit_records, underlying, K_sell, "put", min_expiry, max_expiry)
        legs.append(_make_leg("buy_put", K_buy, entry_buy, exit_buy))
        legs.append(_make_leg("sell_put", K_sell, entry_sell, exit_sell))

    elif struct_type == "collar":
        K_put = etf_price * (1 + offsets.get("put", -0.05))
        K_call = etf_price * (1 + offsets.get("call", 0.05))
        entry_put = find_best_contract(entry_records, underlying, K_put, "put", min_expiry, max_expiry)
        exit_put = find_best_contract(exit_records, underlying, K_put, "put", min_expiry, max_expiry)
        entry_call = find_best_contract(entry_records, underlying, K_call, "call", min_expiry, max_expiry)
        exit_call = find_best_contract(exit_records, underlying, K_call, "call", min_expiry, max_expiry)
        legs.append(_make_leg("buy_put", K_put, entry_put, exit_put))
        legs.append(_make_leg("sell_call", K_call, entry_call, exit_call))

    elif struct_type == "put_ratio":
        K_buy = etf_price * (1 + offsets.get("buy_put", -0.10))
        K_sell = etf_price * (1 + offsets.get("sell_put", -0.25))
        entry_buy = find_best_contract(entry_records, underlying, K_buy, "put", min_expiry, max_expiry)
        exit_buy = find_best_contract(exit_records, underlying, K_buy, "put", min_expiry, max_expiry)
        entry_sell = find_best_contract(entry_records, underlying, K_sell, "put", min_expiry, max_expiry)
        exit_sell = find_best_contract(exit_records, underlying, K_sell, "put", min_expiry, max_expiry)
        legs.append(_make_leg("buy_put", K_buy, entry_buy, exit_buy))
        legs.append(_make_leg("sell_put_2x", K_sell, entry_sell, exit_sell))

    # Compute total PnL
    total_entry = 0.0
    total_exit = 0.0
    all_historical = True
    any_historical = False

    for leg in legs:
        direction = leg["direction"]
        entry_px = leg.get("entry_close")
        exit_px = leg.get("exit_close")

        if entry_px is None or exit_px is None:
            all_historical = False
            continue

        any_historical = True
        multiplier = _leg_multiplier(direction)
        total_entry += entry_px * multiplier
        total_exit += exit_px * multiplier

    pnl = (total_exit - total_entry) * contracts * 100
    source = "historical" if all_historical else "historical_partial" if any_historical else "missing"

    return {
        "pnl": round(pnl, 0),
        "entry_cost": round(total_entry * contracts * 100, 0),
        "exit_value": round(total_exit * contracts * 100, 0),
        "pricing_source": source,
        "legs": legs,
        "contracts": contracts,
    }


def _make_leg(
    direction: str,
    target_strike: float,
    entry_match: Optional[Dict[str, Any]],
    exit_match: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a leg detail dict."""
    return {
        "direction": direction,
        "target_strike": round(target_strike, 2),
        "entry_ticker": entry_match["option_ticker"] if entry_match else None,
        "entry_strike": entry_match["strike"] if entry_match else None,
        "entry_close": entry_match["close"] if entry_match else None,
        "exit_ticker": exit_match["option_ticker"] if exit_match else None,
        "exit_strike": exit_match["strike"] if exit_match else None,
        "exit_close": exit_match["close"] if exit_match else None,
    }


def _leg_multiplier(direction: str) -> float:
    """Sign multiplier: buy=+1, sell=-1, sell_2x=-2."""
    if direction.startswith("buy"):
        return 1.0
    if direction == "sell_put_2x":
        return -2.0
    return -1.0


# ---------------------------------------------------------------------------
# Load day-aggs with caching
# ---------------------------------------------------------------------------

# In-memory cache: {date_str: [records]}
_day_agg_cache: Dict[str, List[Dict[str, Any]]] = {}


def load_day_aggs_for_date(
    dt: date,
    underlying_filter: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Load day-aggs for a date, filtered to specific underlyings.

    Uses in-memory cache to avoid re-downloading within a session.
    """
    key = dt.isoformat()
    if key not in _day_agg_cache:
        try:
            from common.options_history_massive import ingest_day_aggs

            all_records = ingest_day_aggs(dt)
            _day_agg_cache[key] = all_records
        except Exception as exc:
            logger.warning("Failed to load day aggs for %s: %s", dt, exc)
            _day_agg_cache[key] = []

    records = _day_agg_cache[key]
    if underlying_filter:
        uf = set(u.upper() for u in underlying_filter)
        return [r for r in records if r.get("underlying_ticker") in uf]
    return records


def find_nearest_trading_date(
    target: date,
    direction: str = "backward",
    max_tries: int = 5,
    underlying_filter: Optional[List[str]] = None,
) -> Optional[date]:
    """Find the nearest date with actual day-agg data.

    Searches backward (or forward) from target, skipping weekends.
    Returns None if no data found within max_tries business days.
    """
    delta = -1 if direction == "backward" else 1
    dt = target
    for _ in range(max_tries):
        if dt.weekday() < 5:  # skip weekends
            records = load_day_aggs_for_date(dt, underlying_filter)
            if records:
                return dt
        dt += timedelta(days=delta)
    return None


# ---------------------------------------------------------------------------
# Full historical backtest
# ---------------------------------------------------------------------------


def run_historical_backtest(
    structure: Dict[str, Any],
    offsets: Dict[str, float],
    etf_ticker: str,
    etf_prices: Dict[str, float],
    portfolio_returns_monthly: List[Dict[str, Any]],
    hedge_notional: float,
    contracts: int,
) -> Dict[str, Any]:
    """Run historical options-priced backtest for a hedge structure.

    For each month:
      1. Download entry-date and exit-date day aggs
      2. Match structure legs to actual contracts
      3. Price from historical closes
      4. Fall back to BS for missing prints

    Returns same shape as the existing backtest_structure() output.
    """
    struct_type = structure["type"]
    months = portfolio_returns_monthly
    results = []
    total_hedge_pnl = 0.0
    historical_months = 0
    bs_fallback_months = 0

    for m in months:
        month_start = m["start_date"]
        month_end = m["end_date"]
        port_ret = m["portfolio_return"]

        etf_start = etf_prices.get(month_start, 0)
        etf_end = etf_prices.get(month_end, 0)
        if etf_start <= 0 or etf_end <= 0:
            continue

        etf_ret = (etf_end - etf_start) / etf_start
        dte = max((date.fromisoformat(month_end) - date.fromisoformat(month_start)).days, 1)

        # Expiry window: prefer contracts expiring 7-60 days after entry
        entry_dt = date.fromisoformat(month_start)
        min_exp = (entry_dt + timedelta(days=7)).isoformat()
        max_exp = (entry_dt + timedelta(days=60)).isoformat()

        # Load day aggs
        entry_data_dt = find_nearest_trading_date(entry_dt, "backward", 5, [etf_ticker])
        exit_data_dt = find_nearest_trading_date(date.fromisoformat(month_end), "backward", 5, [etf_ticker])

        pricing_source = "bs_fallback"
        hedge_pnl = 0.0

        if entry_data_dt and exit_data_dt:
            entry_records = load_day_aggs_for_date(entry_data_dt, [etf_ticker])
            exit_records = load_day_aggs_for_date(exit_data_dt, [etf_ticker])

            hist_result = price_structure_historical(
                struct_type,
                offsets,
                etf_start,
                etf_ticker,
                entry_records,
                exit_records,
                min_exp,
                max_exp,
                contracts,
            )

            if hist_result["pricing_source"] in ("historical", "historical_partial"):
                hedge_pnl = hist_result["pnl"]
                pricing_source = hist_result["pricing_source"]
                historical_months += 1
            else:
                # Fall back to BS
                hedge_pnl = _bs_fallback_pnl(
                    struct_type,
                    offsets,
                    etf_start,
                    etf_end,
                    dte,
                    contracts,
                )
                pricing_source = "bs_fallback"
                bs_fallback_months += 1
        else:
            hedge_pnl = _bs_fallback_pnl(
                struct_type,
                offsets,
                etf_start,
                etf_end,
                dte,
                contracts,
            )
            bs_fallback_months += 1

        results.append(
            {
                "month_start": month_start,
                "month_end": month_end,
                "portfolio_return": round(port_ret, 4),
                "etf_return": round(etf_ret, 4),
                "hedge_pnl": round(hedge_pnl, 0),
                "pricing_source": pricing_source,
            }
        )
        total_hedge_pnl += hedge_pnl

    if not results:
        return {"months": [], "summary": {}}

    # Summary stats (same shape as existing)
    port_rets = [r["portfolio_return"] for r in results]
    hedged_rets = [r["portfolio_return"] + r["hedge_pnl"] / hedge_notional for r in results]

    payoff_months = sum(1 for r in results if r["portfolio_return"] < 0 and r["hedge_pnl"] > 0)
    cost_months = sum(1 for r in results if r["portfolio_return"] > 0 and r["hedge_pnl"] < 0)

    def _max_dd(rets: List[float]) -> float:
        peak = cum = 1.0
        max_dd = 0.0
        for r in rets:
            cum *= 1 + r
            peak = max(peak, cum)
            max_dd = max(max_dd, (peak - cum) / peak)
        return max_dd

    def _sharpe(rets: List[float]) -> Optional[float]:
        if len(rets) < 3:
            return None
        m = sum(rets) / len(rets)
        v = sum((r - m) ** 2 for r in rets) / len(rets)
        if v <= 0:
            return None
        return m / math.sqrt(v) * math.sqrt(12)

    summary = {
        "total_months": len(results),
        "payoff_months": payoff_months,
        "cost_months": cost_months,
        "total_hedge_pnl": round(total_hedge_pnl, 0),
        "total_return_unhedged": round(sum(port_rets), 4),
        "total_return_hedged": round(sum(hedged_rets), 4),
        "worst_month_unhedged": round(min(port_rets), 4),
        "worst_month_hedged": round(min(hedged_rets), 4),
        "max_drawdown_unhedged": round(_max_dd(port_rets), 4),
        "max_drawdown_hedged": round(_max_dd(hedged_rets), 4),
        "sharpe_unhedged": round(_sharpe(port_rets), 2) if _sharpe(port_rets) else None,
        "sharpe_hedged": round(_sharpe(hedged_rets), 2) if _sharpe(hedged_rets) else None,
        "historical_months": historical_months,
        "bs_fallback_months": bs_fallback_months,
        "backtest_pricing": "historical" if bs_fallback_months == 0 else "mixed",
    }

    return {"months": results, "summary": summary}


def _bs_fallback_pnl(
    struct_type: str,
    offsets: Dict[str, float],
    etf_start: float,
    etf_end: float,
    dte: int,
    contracts: int,
    sigma: float = 0.30,
) -> float:
    """BS-based PnL fallback (same logic as existing _simulate_structure_pnl)."""
    from tools.biotech_hedge_report import _simulate_structure_pnl  # noqa: F811

    T = dte / 365.0
    return _simulate_structure_pnl(
        struct_type,
        offsets,
        etf_start,
        etf_end,
        T,
        sigma,
        0,
        contracts,
    )
