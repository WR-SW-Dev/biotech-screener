"""Massive chain analytics — skew, straddle pricing, OI concentration.

Consumes the per-strike chain snapshot from options_history_massive.py
to compute analytics that Tastytrade diagnostics cannot provide:
  - 25-delta risk reversal (RR_25d)
  - put/call skew from chain
  - ATM straddle actual pricing
  - OI concentration metrics
  - volume distribution by expiry bucket
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def find_25delta_contracts(
    contracts: List[Dict[str, Any]],
    expiry: str,
) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Find the 25-delta put and 25-delta call for a specific expiry.

    Returns (put_contract, call_contract) or (None, None) if not found.
    """
    puts = [
        c
        for c in contracts
        if c.get("expiration_date") == expiry and c.get("contract_type") == "put" and c.get("delta") is not None
    ]
    calls = [
        c
        for c in contracts
        if c.get("expiration_date") == expiry and c.get("contract_type") == "call" and c.get("delta") is not None
    ]

    # 25-delta put: delta closest to -0.25
    best_put = None
    best_put_dist = float("inf")
    for p in puts:
        dist = abs(p["delta"] - (-0.25))
        if dist < best_put_dist:
            best_put_dist = dist
            best_put = p

    # 25-delta call: delta closest to +0.25
    best_call = None
    best_call_dist = float("inf")
    for c in calls:
        dist = abs(c["delta"] - 0.25)
        if dist < best_call_dist:
            best_call_dist = dist
            best_call = c

    # Reject if delta is too far from target (> 0.15 away)
    if best_put and best_put_dist > 0.15:
        best_put = None
    if best_call and best_call_dist > 0.15:
        best_call = None

    return best_put, best_call


def compute_rr_25d(
    put_contract: Optional[Dict],
    call_contract: Optional[Dict],
) -> Optional[float]:
    """Compute 25-delta risk reversal.

    RR_25d = IV(25d call) - IV(25d put)
    Positive = call skew (market pricing upside)
    Negative = put skew (market pricing downside)
    """
    if put_contract is None or call_contract is None:
        return None
    put_iv = put_contract.get("implied_volatility")
    call_iv = call_contract.get("implied_volatility")
    if put_iv is None or call_iv is None:
        return None
    return call_iv - put_iv


def compute_put_call_skew(
    put_contract: Optional[Dict],
    call_contract: Optional[Dict],
) -> Optional[float]:
    """Compute put/call skew: (put_iv - call_iv) / avg_iv.

    Positive = put premium (bearish sentiment / protection buying).
    """
    if put_contract is None or call_contract is None:
        return None
    put_iv = put_contract.get("implied_volatility")
    call_iv = call_contract.get("implied_volatility")
    if put_iv is None or call_iv is None:
        return None
    avg_iv = (put_iv + call_iv) / 2
    if avg_iv <= 0:
        return None
    return (put_iv - call_iv) / avg_iv


def find_atm_contracts(
    contracts: List[Dict[str, Any]],
    underlying_price: float,
    expiry: str,
) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Find ATM call and put for a specific expiry.

    ATM = strike closest to underlying_price.
    """
    expiry_contracts = [c for c in contracts if c.get("expiration_date") == expiry]
    if not expiry_contracts or underlying_price <= 0:
        return None, None

    # Find the strike closest to underlying price
    strikes = sorted(set(c.get("strike_price", 0) for c in expiry_contracts if c.get("strike_price")))
    if not strikes:
        return None, None
    atm_strike = min(strikes, key=lambda s: abs(s - underlying_price))

    atm_call = None
    atm_put = None
    for c in expiry_contracts:
        if c.get("strike_price") == atm_strike:
            if c.get("contract_type") == "call":
                atm_call = c
            elif c.get("contract_type") == "put":
                atm_put = c

    return atm_call, atm_put


def compute_atm_straddle(
    contracts: List[Dict[str, Any]],
    underlying_price: float,
    expiry: str,
) -> Dict[str, Any]:
    """Compute actual ATM straddle price from chain snapshot.

    Returns dict with straddle_price, implied_move, atm_strike,
    atm_call_close, atm_put_close.
    """
    empty: Dict[str, Any] = {
        "straddle_price": None,
        "actual_implied_move": None,
        "atm_strike": None,
        "atm_call_close": None,
        "atm_put_close": None,
    }

    atm_call, atm_put = find_atm_contracts(contracts, underlying_price, expiry)
    if atm_call is None or atm_put is None:
        return empty

    call_price = atm_call.get("day_close")
    put_price = atm_put.get("day_close")
    if call_price is None or put_price is None or call_price <= 0 or put_price <= 0:
        return empty

    straddle = call_price + put_price
    implied_move = straddle / underlying_price if underlying_price > 0 else None

    return {
        "straddle_price": round(straddle, 4),
        "actual_implied_move": round(implied_move, 4) if implied_move else None,
        "atm_strike": atm_call.get("strike_price"),
        "atm_call_close": round(call_price, 4),
        "atm_put_close": round(put_price, 4),
    }


def compute_oi_concentration(
    contracts: List[Dict[str, Any]],
    expiry: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute open interest concentration metrics.

    Returns:
        total_oi, max_oi_strike, oi_concentration (max/total),
        put_oi, call_oi, put_call_oi_ratio.
    """
    filtered = contracts
    if expiry:
        filtered = [c for c in contracts if c.get("expiration_date") == expiry]

    total_oi = 0
    max_oi = 0
    max_oi_strike = None
    put_oi = 0
    call_oi = 0

    for c in filtered:
        oi = c.get("open_interest") or 0
        total_oi += oi
        if oi > max_oi:
            max_oi = oi
            max_oi_strike = c.get("strike_price")
        if c.get("contract_type") == "put":
            put_oi += oi
        elif c.get("contract_type") == "call":
            call_oi += oi

    return {
        "total_oi": total_oi,
        "max_oi": max_oi,
        "max_oi_strike": max_oi_strike,
        "oi_concentration": round(max_oi / total_oi, 4) if total_oi > 0 else None,
        "put_oi": put_oi,
        "call_oi": call_oi,
        "put_call_oi_ratio": round(put_oi / call_oi, 4) if call_oi > 0 else None,
    }


def compute_volume_by_expiry_bucket(
    contracts: List[Dict[str, Any]],
    as_of_date: str,
) -> Dict[str, int]:
    """Aggregate volume by expiry time bucket.

    Returns: {near_0_30d: vol, mid_31_90d: vol, far_91_180d: vol, core_180d_plus: vol}
    """
    from datetime import date

    try:
        ref = date.fromisoformat(as_of_date)
    except (ValueError, TypeError):
        return {}

    buckets: Dict[str, int] = {
        "near_0_30d": 0,
        "mid_31_90d": 0,
        "far_91_180d": 0,
        "core_180d_plus": 0,
    }

    for c in contracts:
        vol = c.get("day_volume") or 0
        if vol <= 0:
            continue
        exp_str = c.get("expiration_date", "")
        try:
            exp = date.fromisoformat(exp_str)
        except (ValueError, TypeError):
            continue
        days = (exp - ref).days
        if days <= 30:
            buckets["near_0_30d"] += vol
        elif days <= 90:
            buckets["mid_31_90d"] += vol
        elif days <= 180:
            buckets["far_91_180d"] += vol
        else:
            buckets["core_180d_plus"] += vol

    return buckets


def compute_chain_analytics(
    chain_snapshot: List[Dict[str, Any]],
    underlying_price: float,
    as_of_date: str = "",
    target_expiry: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute full chain analytics from a Massive chain snapshot.

    If target_expiry is provided, analytics are computed for that expiry.
    Otherwise, uses the nearest expiry with sufficient contracts.

    Returns dict with all analytics fields.
    """
    if not chain_snapshot or underlying_price <= 0:
        return {"status": "no_data"}

    # Determine expiry
    expiries = sorted(set(c.get("expiration_date", "") for c in chain_snapshot if c.get("expiration_date")))
    if not expiries:
        return {"status": "no_expiries"}

    expiry = target_expiry if target_expiry and target_expiry in expiries else expiries[0]

    # Skew
    put_25d, call_25d = find_25delta_contracts(chain_snapshot, expiry)
    rr_25d = compute_rr_25d(put_25d, call_25d)
    skew = compute_put_call_skew(put_25d, call_25d)

    # Straddle
    straddle = compute_atm_straddle(chain_snapshot, underlying_price, expiry)

    # OI
    oi = compute_oi_concentration(chain_snapshot, expiry)

    # Volume by bucket
    vol_buckets = compute_volume_by_expiry_bucket(chain_snapshot, as_of_date) if as_of_date else {}
    total_vol = sum(vol_buckets.values())
    near_share = round(vol_buckets.get("near_0_30d", 0) / total_vol, 4) if total_vol > 0 else None

    return {
        "status": "ok",
        "expiry_used": expiry,
        "n_contracts": len([c for c in chain_snapshot if c.get("expiration_date") == expiry]),
        # Skew
        "rr_25d": round(rr_25d, 4) if rr_25d is not None else None,
        "put_call_skew": round(skew, 4) if skew is not None else None,
        "put_25d_iv": put_25d.get("implied_volatility") if put_25d else None,
        "call_25d_iv": call_25d.get("implied_volatility") if call_25d else None,
        # Straddle
        **straddle,
        # OI
        **oi,
        # Volume distribution
        "volume_by_bucket": vol_buckets,
        "near_term_volume_share": near_share,
        "total_chain_volume": total_vol,
    }


# ---------------------------------------------------------------------------
# Persistence + warm pass
# ---------------------------------------------------------------------------


def save_chain_snapshot(
    chain: List[Dict[str, Any]],
    snap_dir: Path,
    ticker: str,
) -> Path:
    """Persist raw chain snapshot to disk for downstream consumers."""
    chains_dir = snap_dir / "chains"
    chains_dir.mkdir(parents=True, exist_ok=True)
    path = chains_dir / f"{ticker.upper()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(chain, f, default=str)
        f.write("\n")
    return path


def load_chain_snapshot(snap_dir: Path, ticker: str) -> List[Dict[str, Any]]:
    """Load a persisted chain snapshot from disk."""
    path = snap_dir / "chains" / f"{ticker.upper()}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def warm_chain_analytics(
    tickers: List[str],
    snap_dir: Path,
    as_of_date: str,
    prices: Optional[Dict[str, float]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Fetch chain snapshots and compute analytics for a list of tickers.

    Args:
        tickers: List of underlying tickers to fetch.
        snap_dir: Snapshot directory to persist chains into.
        as_of_date: Date string for volume bucketing.
        prices: {ticker: last_close} for underlying prices. If None, ATM
                straddle and delta-based analytics may be less accurate.

    Returns:
        {ticker: analytics_dict} for each ticker with data.
    """
    try:
        from common.options_history_massive import fetch_chain_snapshot
    except ImportError:
        logger.warning("options_history_massive not available")
        return {}

    results: Dict[str, Dict[str, Any]] = {}
    n_fetched = 0
    n_failed = 0

    for ticker in tickers:
        try:
            chain = fetch_chain_snapshot(ticker.upper(), limit=250)
            if not chain:
                n_failed += 1
                continue

            # Persist raw chain
            save_chain_snapshot(chain, snap_dir, ticker)

            # Compute analytics
            underlying_price = (prices or {}).get(ticker.upper(), 0.0)
            analytics = compute_chain_analytics(chain, underlying_price, as_of_date)
            results[ticker.upper()] = analytics
            n_fetched += 1
        except Exception as exc:
            logger.debug("Chain fetch failed for %s: %s", ticker, exc)
            n_failed += 1

    logger.info(
        "[MASSIVE_CHAIN] Warmed %d/%d tickers (%d failed)",
        n_fetched,
        len(tickers),
        n_failed,
    )
    return results
