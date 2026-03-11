"""Options-implied vol/skew diagnostics from tastytrade.

Passive diagnostic output — does not affect rankings, weights, portfolio
construction, gates, or execution decisions.

Computes a compact set of options diagnostics for catalyst-relevant tickers
using tastytrade market metrics and option chain data.

Required environment variables:
    TT_SECRET   — tastytrade OAuth provider secret
    TT_REFRESH  — tastytrade refresh token

To disable: do not set env vars. The module degrades gracefully to empty
diagnostics with a logged warning.

Output columns (all prefixed ``opt_``):
    opt_has_data          — 1 if options data retrieved, 0 otherwise
    opt_quote_ts          — ISO timestamp of last quote update
    opt_nearest_expiry    — nearest liquid expiry date (YYYY-MM-DD)
    opt_dte               — days to nearest expiry
    opt_atm_iv            — at-the-money implied volatility (annualized)
    opt_front_iv          — front-month expiry IV
    opt_back_iv           — back-month expiry IV (next expiry after front)
    opt_term_slope        — (back_iv - front_iv) / front_iv; positive = contango
    opt_put_call_skew     — (ATM put IV - ATM call IV) / ATM IV;
                            positive = puts more expensive (fear premium)
    opt_rr_25d            — reserved for 25-delta risk reversal; empty in pilot
                            (requires per-strike greeks not in metrics API)
    opt_diagnostic_basis  — short note on data source / fallback reason

Operator flags (derived from raw diagnostics + catalyst context):
    opt_iv_regime         — NORMAL / ELEVATED / EXTREME / "" based on ATM IV
    opt_event_premium     — YES / NO / "" — front > back by > 10% (backwardation)
    opt_liquidity_ok      — 1 / 0 — chain quality sufficient for judgment
    opt_use_for_judgment  — YES / NO / "" — composite: has data + liquid + not extreme junk
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date as _date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

OPTIONS_DIAGNOSTIC_COLUMNS = [
    "opt_has_data",
    "opt_quote_ts",
    "opt_nearest_expiry",
    "opt_dte",
    "opt_atm_iv",
    "opt_front_iv",
    "opt_back_iv",
    "opt_term_slope",
    "opt_put_call_skew",
    "opt_rr_25d",
    "opt_diagnostic_basis",
    # Operator flags
    "opt_iv_regime",
    "opt_event_premium",
    "opt_liquidity_ok",
    "opt_use_for_judgment",
]

_EMPTY_DIAGNOSTICS: Dict[str, Any] = {col: "" for col in OPTIONS_DIAGNOSTIC_COLUMNS}
_EMPTY_DIAGNOSTICS["opt_has_data"] = "0"
_EMPTY_DIAGNOSTICS["opt_liquidity_ok"] = "0"


def empty_diagnostics(reason: str = "") -> Dict[str, Any]:
    """Return empty diagnostic row with optional reason."""
    result = dict(_EMPTY_DIAGNOSTICS)
    result["opt_diagnostic_basis"] = reason
    return result


# ---------------------------------------------------------------------------
# Tastytrade session management
# ---------------------------------------------------------------------------

# Minimum liquidity rating to trust the chain (tastytrade scale: 1-5, 5=best)
MIN_LIQUIDITY_RATING = 1

# Maximum number of symbols per get_market_metrics batch
_METRICS_BATCH_SIZE = 50


def _has_credentials() -> bool:
    """Check if tastytrade credentials are available in environment."""
    return bool(os.environ.get("TT_SECRET") and os.environ.get("TT_REFRESH"))


async def _create_session(is_test: bool = False):
    """Create a tastytrade session. Returns None on failure."""
    try:
        from tastytrade import Session

        session = Session(is_test=is_test)
        return session
    except Exception as exc:
        logger.warning("tastytrade session creation failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Per-expiry IV extraction and term structure
# ---------------------------------------------------------------------------


def select_front_back_expiries(
    expiry_ivs: List[Dict[str, Any]],
    as_of_date: _date,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Select front and back expiry from a list of {expiration_date, iv} dicts.

    Front = nearest future expiry with IV data and DTE >= 7 (skip weeklies
    expiring within a week — too noisy).
    Back = next expiry after front with IV data.

    Returns (front, back) — either may be None.
    """
    # Filter to future expiries with IV
    candidates = []
    for item in expiry_ivs:
        exp_date = item.get("expiration_date")
        iv = item.get("implied_volatility")
        if exp_date is None or iv is None:
            continue
        if isinstance(exp_date, str):
            try:
                exp_date = _date.fromisoformat(exp_date)
            except (ValueError, TypeError):
                continue
        dte = (exp_date - as_of_date).days
        if dte < 7:
            continue
        candidates.append({"expiration_date": exp_date, "implied_volatility": iv, "dte": dte})

    candidates.sort(key=lambda x: x["dte"])

    front = candidates[0] if candidates else None
    back = candidates[1] if len(candidates) > 1 else None
    return front, back


def compute_term_slope(front_iv: float, back_iv: float) -> Optional[float]:
    """Compute term structure slope: (back - front) / front.

    Positive = contango (normal), negative = backwardation (event premium).
    Returns None if front_iv is zero or missing.
    """
    if not front_iv or front_iv <= 0:
        return None
    return round((back_iv - front_iv) / front_iv, 4)


# ---------------------------------------------------------------------------
# Operator flags — derived from raw diagnostics + catalyst context
# ---------------------------------------------------------------------------

# IV regime thresholds (annualized)
_IV_ELEVATED_THRESHOLD = 0.60
_IV_EXTREME_THRESHOLD = 2.00

# Event premium: term slope below this = meaningful backwardation
_EVENT_PREMIUM_SLOPE_THRESHOLD = -0.10

# Liquidity: tastytrade rating >= this is considered usable
# Scale is 1 (worst) to 5 (best); 3+ gives reasonable bid-ask spreads
_LIQUIDITY_OK_THRESHOLD = 3

# IV cap for "use for judgment" — above this, chain is likely too wide to trust
_IV_JUNK_CAP = 5.00


def classify_iv_regime(atm_iv: Optional[float]) -> str:
    """Classify ATM IV into operator-readable regime.

    NORMAL   — IV < 60% (typical for liquid large-cap biotech)
    ELEVATED — 60% <= IV < 200% (catalyst premium, small-cap vol)
    EXTREME  — IV >= 200% (micro-cap, illiquid, or imminent binary event)
    """
    if atm_iv is None:
        return ""
    if atm_iv >= _IV_EXTREME_THRESHOLD:
        return "EXTREME"
    if atm_iv >= _IV_ELEVATED_THRESHOLD:
        return "ELEVATED"
    return "NORMAL"


def classify_event_premium(term_slope: Optional[float]) -> str:
    """Detect event premium from term structure backwardation.

    YES — front IV > back IV by > 10% (slope < -0.10)
    NO  — flat or contango term structure
    """
    if term_slope is None:
        return ""
    return "YES" if term_slope < _EVENT_PREMIUM_SLOPE_THRESHOLD else "NO"


def classify_liquidity_ok(liquidity_rating: Optional[int]) -> str:
    """Return '1' if chain quality is sufficient for operator judgment."""
    if liquidity_rating is None:
        return "0"
    return "1" if liquidity_rating >= _LIQUIDITY_OK_THRESHOLD else "0"


def classify_use_for_judgment(
    has_data: bool,
    liquidity_ok: bool,
    atm_iv: Optional[float],
) -> str:
    """Composite gate: should the operator use this for judgment?

    YES requires: has data + liquid chain + IV not in junk territory (>500%).
    Junk IV means the chain is so wide that the numbers are noise.
    """
    if not has_data:
        return "NO"
    if not liquidity_ok:
        return "NO"
    if atm_iv is not None and atm_iv >= _IV_JUNK_CAP:
        return "NO"
    return "YES"


def compute_operator_flags(
    diag: Dict[str, Any],
    liquidity_rating: Optional[int] = None,
) -> Dict[str, str]:
    """Derive operator flags from raw diagnostics.

    Mutates nothing — returns a dict of flag columns to merge.
    """
    has_data = diag.get("opt_has_data") == "1"
    atm_iv = diag.get("opt_atm_iv")
    if isinstance(atm_iv, str) and atm_iv == "":
        atm_iv = None
    elif atm_iv is not None:
        atm_iv = float(atm_iv)

    term_slope = diag.get("opt_term_slope")
    if isinstance(term_slope, str) and term_slope == "":
        term_slope = None
    elif term_slope is not None:
        term_slope = float(term_slope)

    liq_ok = classify_liquidity_ok(liquidity_rating)

    return {
        "opt_iv_regime": classify_iv_regime(atm_iv),
        "opt_event_premium": classify_event_premium(term_slope),
        "opt_liquidity_ok": liq_ok,
        "opt_use_for_judgment": classify_use_for_judgment(has_data, liq_ok == "1", atm_iv),
    }


# ---------------------------------------------------------------------------
# Put/call skew from option chain
# ---------------------------------------------------------------------------


def select_atm_strike(
    strikes: List[Dict[str, Any]],
    spot_price: float,
) -> Optional[Dict[str, Any]]:
    """Select the at-the-money strike nearest to spot price.

    Each strike dict has: strike_price, call (symbol), put (symbol).
    Returns the nearest strike dict, or None.
    """
    if not strikes or not spot_price or spot_price <= 0:
        return None

    best = None
    best_dist = float("inf")
    for s in strikes:
        sp = s.get("strike_price")
        if sp is None:
            continue
        try:
            dist = abs(float(sp) - spot_price)
        except (ValueError, TypeError):
            continue
        if dist < best_dist:
            best_dist = dist
            best = s

    return best


def compute_put_call_skew(
    put_iv: Optional[float],
    call_iv: Optional[float],
) -> Optional[float]:
    """Compute put/call skew at ATM: (put_iv - call_iv) / avg(put_iv, call_iv).

    Positive = puts more expensive than calls (fear premium).
    Returns None if either IV is missing.
    """
    if put_iv is None or call_iv is None:
        return None
    if put_iv <= 0 and call_iv <= 0:
        return None
    avg = (put_iv + call_iv) / 2.0
    if avg <= 0:
        return None
    return round((put_iv - call_iv) / avg, 4)


# ---------------------------------------------------------------------------
# Core async diagnostics fetcher
# ---------------------------------------------------------------------------


async def _fetch_metrics_batch(
    session,
    symbols: List[str],
) -> Dict[str, Any]:
    """Fetch market metrics for a batch of symbols.

    Returns {symbol: MarketMetricInfo} dict.
    """
    from tastytrade.metrics import get_market_metrics

    result = {}
    # Batch in chunks
    for i in range(0, len(symbols), _METRICS_BATCH_SIZE):
        batch = symbols[i : i + _METRICS_BATCH_SIZE]
        try:
            metrics = await get_market_metrics(session, batch)
            for m in metrics:
                result[m.symbol] = m
        except Exception as exc:
            logger.warning("tastytrade metrics batch failed for %d symbols: %s", len(batch), exc)
    return result


async def _fetch_option_chain_skew(
    session,
    symbol: str,
    spot_price: float,
    front_expiry: _date,
) -> Optional[float]:
    """Fetch ATM put/call skew for a symbol at the front expiry.

    Reserved for future implementation.  The REST MarketData endpoint does
    not expose per-option IV; computing skew requires either:
    - The DXLink streaming greeks feed, or
    - A Black-Scholes solver applied to bid/ask mid prices.

    Returns None in the pilot.
    """
    # Placeholder: skew requires streaming greeks or BS solver.
    # See compute_put_call_skew() for the math once IV is available.
    return None


async def _fetch_diagnostics_async(
    symbols: List[str],
    as_of_date: str,
    is_test: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Fetch options diagnostics for a list of symbols.

    Returns {symbol: diagnostics_dict}.
    """
    if not symbols:
        return {}

    session = await _create_session(is_test=is_test)
    if session is None:
        return {s: empty_diagnostics("no_session") for s in symbols}

    try:
        ref_date = _date.fromisoformat(as_of_date)
    except (ValueError, TypeError):
        ref_date = _date.today()

    async with session:
        # Batch fetch market metrics
        metrics = await _fetch_metrics_batch(session, symbols)

        result: Dict[str, Dict[str, Any]] = {}
        for symbol in symbols:
            m = metrics.get(symbol)
            if m is None:
                result[symbol] = empty_diagnostics("no_metrics")
                continue

            # Check liquidity
            liq = m.liquidity_rating
            if liq is not None and liq < MIN_LIQUIDITY_RATING:
                result[symbol] = empty_diagnostics(f"low_liquidity_{liq}")
                continue

            # Extract per-expiry IV
            expiry_ivs = []
            if m.option_expiration_implied_volatilities:
                for oiv in m.option_expiration_implied_volatilities:
                    if oiv.implied_volatility is not None:
                        expiry_ivs.append(
                            {
                                "expiration_date": oiv.expiration_date,
                                "implied_volatility": float(oiv.implied_volatility),
                            }
                        )

            front, back = select_front_back_expiries(expiry_ivs, ref_date)

            if not front:
                result[symbol] = empty_diagnostics("no_liquid_expiry")
                continue

            atm_iv = float(m.implied_volatility_index) if m.implied_volatility_index is not None else None
            front_iv = front["implied_volatility"]
            back_iv = back["implied_volatility"] if back else None
            term_slope = compute_term_slope(front_iv, back_iv) if back_iv else None

            quote_ts = ""
            if m.implied_volatility_updated_at:
                quote_ts = m.implied_volatility_updated_at.isoformat()
            elif m.updated_at:
                quote_ts = m.updated_at.isoformat()

            diag: Dict[str, Any] = {
                "opt_has_data": "1",
                "opt_quote_ts": quote_ts,
                "opt_nearest_expiry": front["expiration_date"].isoformat(),
                "opt_dte": front["dte"],
                "opt_atm_iv": round(atm_iv, 4) if atm_iv is not None else round(front_iv, 4),
                "opt_front_iv": round(front_iv, 4),
                "opt_back_iv": round(back_iv, 4) if back_iv is not None else "",
                "opt_term_slope": term_slope if term_slope is not None else "",
                "opt_put_call_skew": "",  # requires streaming greeks; reserved
                "opt_rr_25d": "",  # requires per-strike delta; reserved
                "opt_diagnostic_basis": "tt_market_metrics",
            }
            # Derive operator flags
            diag.update(compute_operator_flags(diag, liquidity_rating=liq))
            result[symbol] = diag

        return result


# ---------------------------------------------------------------------------
# Public synchronous API
# ---------------------------------------------------------------------------


def fetch_options_diagnostics(
    symbols: List[str],
    as_of_date: str,
    is_test: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Fetch options diagnostics for a list of symbols (synchronous wrapper).

    Non-blocking: returns empty diagnostics on any failure.

    Parameters
    ----------
    symbols : list of ticker symbols (uppercase)
    as_of_date : evaluation date (YYYY-MM-DD)
    is_test : use tastytrade sandbox

    Returns
    -------
    {symbol: {opt_has_data, opt_quote_ts, ...}} for each symbol.
    Symbols without data get empty diagnostics with reason.
    """
    if not _has_credentials():
        logger.info("tastytrade credentials not set (TT_SECRET / TT_REFRESH) — options diagnostics disabled")
        return {s: empty_diagnostics("no_credentials") for s in symbols}

    if not symbols:
        return {}

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_fetch_diagnostics_async(symbols, as_of_date, is_test))
        finally:
            loop.close()
    except Exception as exc:
        logger.warning("Options diagnostics fetch failed: %s", exc)
        return {s: empty_diagnostics(f"fetch_error: {exc}") for s in symbols}


def select_catalyst_tickers(
    rankings: List[Dict[str, Any]],
    max_tickers: int = 200,
) -> List[str]:
    """Select tickers eligible for options diagnostics from rankings.

    Criteria (in priority order):
    1. Has an actionable_rank (in action list)
    2. Has catalyst_days <= 180 (upcoming catalyst)
    3. Cap at max_tickers (soft safety limit; API batches at 50/request)

    Returns sorted list of uppercase ticker symbols.
    """
    scored: List[Tuple[float, str]] = []
    for row in rankings:
        ticker = (row.get("ticker") or "").upper()
        if not ticker:
            continue

        # Priority: lower = more important
        ar = row.get("actionable_rank", "")
        cat_days = row.get("catalyst_days", "")

        try:
            ar_val = float(ar) if ar != "" else 999
        except (ValueError, TypeError):
            ar_val = 999

        try:
            cd_val = float(cat_days) if cat_days != "" else 999
        except (ValueError, TypeError):
            cd_val = 999

        # Skip tickers with no catalyst relevance
        if ar_val >= 999 and cd_val > 180:
            continue

        # Score: actionable names first, then by catalyst proximity
        priority = ar_val * 0.1 + cd_val * 0.01
        scored.append((priority, ticker))

    scored.sort()
    tickers = [t for _, t in scored[:max_tickers]]
    return sorted(set(tickers))
