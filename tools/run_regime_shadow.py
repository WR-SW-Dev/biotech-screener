"""Regime shadow — daily comparison of simple vs rich regime classifiers.

Runs both classifiers on the same market data and produces a shadow artifact.
Does NOT affect construction, scoring, or execution. Diagnostic only.

Classifiers compared:
  1. simple: XBI 20d return with hysteresis (from construction_v2_shadow.py)
  2. rich:   RegimeDetectionEngine with VIX, XBI, rates, macro (from regime_engine.py)

Output:
    artifacts/regime_shadow/{date}.json

Usage:
    python tools/run_regime_shadow.py --as-of-date 2026-04-01
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
MARKET_SNAPSHOT = PROJECT_ROOT / "data" / "market_snapshot.json"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "regime_shadow"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("regime_shadow")


# ---------------------------------------------------------------------------
# Price loading
# ---------------------------------------------------------------------------


def _load_xbi_prices() -> Dict[str, float]:
    """Load XBI closing prices from price_history.csv."""
    prices: Dict[str, float] = {}
    with open(PRICE_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker") == "XBI":
                try:
                    prices[row["date"]] = float(row["close"])
                except (ValueError, KeyError):
                    pass
    return prices


def _load_all_prices_for_simple() -> Dict[str, Dict[str, float]]:
    """Load price map in the format the simple classifier expects: {date: {ticker: price}}."""
    result: Dict[str, Dict[str, float]] = {}
    with open(PRICE_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("date", "")
            t = row.get("ticker", "")
            c = row.get("close", "")
            if d and t and c:
                try:
                    result.setdefault(d, {})[t] = float(c)
                except ValueError:
                    pass
    return result


def _load_market_snapshot() -> Dict[str, Any]:
    """Load static market snapshot (VIX, rates, etc)."""
    if not MARKET_SNAPSHOT.exists():
        return {}
    return json.loads(MARKET_SNAPSHOT.read_text())


# ---------------------------------------------------------------------------
# Compute market inputs from price data
# ---------------------------------------------------------------------------


def _compute_xbi_metrics(xbi_prices: Dict[str, float], as_of_date: str) -> Dict[str, Optional[float]]:
    """Compute XBI-derived regime inputs from price history."""
    sorted_dates = sorted(d for d in xbi_prices if d <= as_of_date)
    if len(sorted_dates) < 31:
        return {"xbi_return_20d": None, "xbi_return_30d": None, "xbi_momentum_10d": None}

    p_now = xbi_prices.get(sorted_dates[-1])

    # 20-day return
    p_20d = xbi_prices.get(sorted_dates[-21]) if len(sorted_dates) >= 21 else None
    ret_20d = ((p_now / p_20d) - 1) * 100 if p_now and p_20d and p_20d > 0 else None

    # 30-day return (used as proxy for xbi_vs_spy_30d when SPY unavailable)
    p_30d = xbi_prices.get(sorted_dates[-31]) if len(sorted_dates) >= 31 else None
    ret_30d = ((p_now / p_30d) - 1) * 100 if p_now and p_30d and p_30d > 0 else None

    # 10-day momentum
    p_10d = xbi_prices.get(sorted_dates[-11]) if len(sorted_dates) >= 11 else None
    mom_10d = ((p_now / p_10d) - 1) * 100 if p_now and p_10d and p_10d > 0 else None

    # 20-day realized volatility (annualized)
    if len(sorted_dates) >= 22:
        import math

        recent = sorted_dates[-22:]
        log_returns = []
        for i in range(1, len(recent)):
            p0 = xbi_prices.get(recent[i - 1], 0)
            p1 = xbi_prices.get(recent[i], 0)
            if p0 > 0 and p1 > 0:
                log_returns.append(math.log(p1 / p0))
        if len(log_returns) >= 15:
            mean_r = sum(log_returns) / len(log_returns)
            var_r = sum((r - mean_r) ** 2 for r in log_returns) / (len(log_returns) - 1)
            xbi_vol_20d = math.sqrt(var_r) * math.sqrt(252) * 100
        else:
            xbi_vol_20d = None
    else:
        xbi_vol_20d = None

    return {
        "xbi_close": p_now,
        "xbi_return_20d": round(ret_20d, 2) if ret_20d is not None else None,
        "xbi_return_30d": round(ret_30d, 2) if ret_30d is not None else None,
        "xbi_momentum_10d": round(mom_10d, 2) if mom_10d is not None else None,
        "xbi_vol_20d_ann": round(xbi_vol_20d, 1) if xbi_vol_20d is not None else None,
    }


# ---------------------------------------------------------------------------
# Regime classifiers
# ---------------------------------------------------------------------------


def _run_simple_classifier(all_prices: Dict, as_of_date: str) -> Dict[str, Any]:
    """Run the simple XBI hysteresis classifier."""
    from tools.construction_v2_shadow import RegimeClassifier

    clf = RegimeClassifier()
    # Warm up the classifier with historical data
    sorted_dates = sorted(d for d in all_prices if d <= as_of_date)
    for d in sorted_dates:
        clf.classify(all_prices, d)

    regime = clf.classify(all_prices, as_of_date)
    return {
        "regime": regime.upper(),
        "classifier": "simple_xbi_hysteresis",
        "detail": clf.to_dict(),
    }


def _run_rich_classifier(
    xbi_metrics: Dict,
    market_snapshot: Dict,
    as_of_date: str,
) -> Dict[str, Any]:
    """Run the full RegimeDetectionEngine."""
    try:
        from regime_engine import RegimeDetectionEngine
    except ImportError:
        return {"regime": "UNAVAILABLE", "error": "regime_engine not importable"}

    engine = RegimeDetectionEngine()

    # Build inputs from XBI metrics + market snapshot
    vix = market_snapshot.get("vix", "20")
    xbi_30d = xbi_metrics.get("xbi_return_30d")
    if xbi_30d is None:
        xbi_30d = 0
    fed_rate = market_snapshot.get("fed_rate_change_3m", "0")
    xbi_mom = xbi_metrics.get("xbi_momentum_10d")

    # Determine data staleness
    snap_date_str = market_snapshot.get("provenance", {}).get("as_of_date", "")
    data_as_of = None
    if snap_date_str:
        try:
            data_as_of = date.fromisoformat(snap_date_str)
        except ValueError:
            pass

    # Optional macro inputs
    yield_curve_bps = market_snapshot.get("yield_curve_slope_bps")
    credit_change = market_snapshot.get("credit_spread_change")

    try:
        kwargs = dict(
            vix_current=Decimal(str(vix)),
            xbi_vs_spy_30d=Decimal(str(xbi_30d)),
            fed_rate_change_3m=Decimal(str(fed_rate)),
            xbi_momentum_10d=Decimal(str(xbi_mom)) if xbi_mom is not None else None,
            as_of_date=date.fromisoformat(as_of_date),
            data_as_of_date=data_as_of,
            use_ensemble=False,
        )
        if yield_curve_bps and yield_curve_bps != "0":
            kwargs["yield_curve_slope"] = Decimal(str(yield_curve_bps))
        if credit_change and credit_change != "0":
            kwargs["credit_spread_change"] = Decimal(str(credit_change))

        result = engine.detect_regime(**kwargs)

        # Serialize Decimals for JSON
        def _dec(v):
            if isinstance(v, Decimal):
                return float(v)
            if isinstance(v, dict):
                return {k: _dec(vv) for k, vv in v.items()}
            if isinstance(v, list):
                return [_dec(vv) for vv in v]
            return v

        return {
            "regime": result.get("regime", "UNKNOWN"),
            "confidence": float(result.get("confidence", 0)),
            "classifier": "regime_detection_engine",
            "staleness": _dec(result.get("staleness")),
            "signal_adjustments": _dec(result.get("signal_adjustments")),
            "regime_scores": _dec(result.get("regime_scores")),
            "indicators": _dec(result.get("indicators")),
            "flags": result.get("flags", []),
        }
    except Exception as exc:
        log.warning("Rich regime classifier failed: %s", exc)
        return {"regime": "ERROR", "error": str(exc), "classifier": "regime_detection_engine"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _load_prior_shadow(as_of_date: str) -> Dict[str, Any]:
    """Load the most recent regime shadow artifact before as_of_date."""
    if not OUTPUT_DIR.exists():
        return {}
    prior_files = sorted(f for f in OUTPUT_DIR.glob("*.json") if f.stem < as_of_date and f.stem[:4].isdigit())
    if not prior_files:
        return {}
    try:
        return json.loads(prior_files[-1].read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def run_regime_shadow(as_of_date: str) -> Dict[str, Any]:
    """Run both regime classifiers and produce comparison artifact."""
    log.info("Running regime shadow for %s", as_of_date)

    # Load data
    xbi_prices = _load_xbi_prices()
    all_prices = _load_all_prices_for_simple()
    market_snapshot = _load_market_snapshot()
    xbi_metrics = _compute_xbi_metrics(xbi_prices, as_of_date)

    log.info("XBI prices: %d dates, latest metrics: %s", len(xbi_prices), xbi_metrics)

    # Run classifiers
    simple = _run_simple_classifier(all_prices, as_of_date)
    rich = _run_rich_classifier(xbi_metrics, market_snapshot, as_of_date)

    # Compare
    simple_regime = simple.get("regime", "UNKNOWN")
    rich_regime = rich.get("regime", "UNKNOWN")
    rich_conf = rich.get("confidence", 0)

    # Agreement: both say bull, or both say non-bull (risk-off)
    agree = (simple_regime == "BULL" and rich_regime == "BULL") or (simple_regime != "BULL" and rich_regime != "BULL")

    # --- Switching policy ---
    # Load prior artifact for persistence tracking
    prior = _load_prior_shadow(as_of_date)
    prior_recommendation = prior.get("switching_policy", {}).get("recommendation", "ew30")

    # Count consecutive days of agreement/disagreement
    disagree_streak = prior.get("switching_policy", {}).get("disagree_streak", 0)
    if not agree:
        disagree_streak += 1
    else:
        disagree_streak = 0

    # Count consecutive days rich engine says bear/stress
    rich_bear_streak = prior.get("switching_policy", {}).get("rich_bear_streak", 0)
    if rich_regime in ("BEAR", "VOLATILITY_SPIKE", "CREDIT_CRISIS", "RECESSION_RISK"):
        rich_bear_streak += 1
    else:
        rich_bear_streak = 0

    # Switching rules (conservative):
    # 1. Default = EW Top-30 (no regime adjustment)
    # 2. Switch to Top-20 concentration only if:
    #    a. BOTH classifiers agree on non-bull AND
    #    b. Rich confidence >= 0.60 AND
    #    c. Rich has said bear/stress for >= 3 consecutive days
    # 3. If classifiers disagree, always default to EW Top-30
    # 4. If rich confidence < 0.50, always default to EW Top-30

    MIN_BEAR_PERSISTENCE = 3  # days
    MIN_SWITCH_CONFIDENCE = 0.60

    recommendation = "ew30"
    switch_reasons = []

    if not agree:
        recommendation = "ew30"
        switch_reasons.append(f"classifiers_disagree(simple={simple_regime},rich={rich_regime})")
    elif rich_conf < MIN_SWITCH_CONFIDENCE:
        recommendation = "ew30"
        switch_reasons.append(f"low_confidence({rich_conf:.2f}<{MIN_SWITCH_CONFIDENCE})")
    elif rich_regime in ("BEAR", "VOLATILITY_SPIKE", "CREDIT_CRISIS", "RECESSION_RISK"):
        if rich_bear_streak >= MIN_BEAR_PERSISTENCE:
            recommendation = "top20_concentrate"
            switch_reasons.append(f"confirmed_bear(rich={rich_regime},streak={rich_bear_streak}d,conf={rich_conf:.2f})")
        else:
            recommendation = "ew30"
            switch_reasons.append(f"bear_not_confirmed(streak={rich_bear_streak}d<{MIN_BEAR_PERSISTENCE}d)")
    else:
        recommendation = "ew30"
        switch_reasons.append("default_ew30")

    # Would-switch flag: what would change if we followed the recommendation
    would_switch = recommendation != prior_recommendation

    # Estimated turnover if we switched today
    if recommendation == "top20_concentrate":
        estimated_turnover_names = 10  # dropping 10 of 30 names
    else:
        estimated_turnover_names = 0

    return {
        "schema": "regime_shadow.v2",
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "xbi_metrics": xbi_metrics,
        "market_snapshot_date": market_snapshot.get("provenance", {}).get("as_of_date", ""),
        "simple_classifier": simple,
        "rich_classifier": rich,
        "agreement": agree,
        "disagreement_note": (f"simple={simple_regime}, rich={rich_regime}" if not agree else ""),
        "switching_policy": {
            "recommendation": recommendation,
            "reasons": switch_reasons,
            "would_switch": would_switch,
            "prior_recommendation": prior_recommendation,
            "disagree_streak": disagree_streak,
            "rich_bear_streak": rich_bear_streak,
            "estimated_turnover_names": estimated_turnover_names,
            "min_bear_persistence": MIN_BEAR_PERSISTENCE,
            "min_switch_confidence": MIN_SWITCH_CONFIDENCE,
        },
    }


def print_report(result: Dict):
    print(f"\n{'='*60}")
    print(f"REGIME SHADOW — {result['as_of_date']}")
    print(f"{'='*60}")

    xbi = result.get("xbi_metrics", {})
    print(
        f"  XBI: ${xbi.get('xbi_close', '?'):.2f}  20d={xbi.get('xbi_return_20d', '?')}%  "
        f"30d={xbi.get('xbi_return_30d', '?')}%  vol={xbi.get('xbi_vol_20d_ann', '?')}%"
    )
    print(f"  Market snapshot: {result.get('market_snapshot_date', 'none')}")

    s = result["simple_classifier"]
    r = result["rich_classifier"]
    print(f"\n  Simple:  {s['regime']}")
    print(f"  Rich:    {r['regime']}  (conf={r.get('confidence', '?')})")

    if r.get("staleness"):
        print(f"  Stale:   {r['staleness']}")
    if r.get("flags"):
        print(f"  Flags:   {r['flags']}")

    agree = result["agreement"]
    print(f"\n  Agreement: {'YES' if agree else 'NO — ' + result.get('disagreement_note', '')}")

    sp = result.get("switching_policy", {})
    if sp:
        print("\n  Switching policy:")
        print(f"    Recommendation:  {sp.get('recommendation', '?')}")
        print(f"    Reasons:         {', '.join(sp.get('reasons', []))}")
        print(f"    Would switch:    {sp.get('would_switch', False)}")
        print(f"    Bear streak:     {sp.get('rich_bear_streak', 0)}d")
        print(f"    Disagree streak: {sp.get('disagree_streak', 0)}d")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    result = run_regime_shadow(args.as_of_date)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{args.as_of_date}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    log.info("Wrote %s", out_path)

    print_report(result)


if __name__ == "__main__":
    main()
