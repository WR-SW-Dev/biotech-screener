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

    try:
        result = engine.detect_regime(
            vix_current=Decimal(str(vix)),
            xbi_vs_spy_30d=Decimal(str(xbi_30d)),
            fed_rate_change_3m=Decimal(str(fed_rate)),
            xbi_momentum_10d=Decimal(str(xbi_mom)) if xbi_mom is not None else None,
            as_of_date=date.fromisoformat(as_of_date),
            data_as_of_date=data_as_of,
            use_ensemble=False,
        )

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

    # Map to common labels for agreement check
    simple_mapped = simple_regime  # Already BULL/BEAR
    rich_mapped = rich_regime  # Could be BULL/BEAR/VOLATILITY_SPIKE/etc

    # Agreement: both say bull, or both say non-bull
    agree = (simple_mapped == "BULL" and rich_mapped == "BULL") or (simple_mapped != "BULL" and rich_mapped != "BULL")

    return {
        "schema": "regime_shadow.v1",
        "as_of_date": as_of_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "xbi_metrics": xbi_metrics,
        "market_snapshot_date": market_snapshot.get("provenance", {}).get("as_of_date", ""),
        "simple_classifier": simple,
        "rich_classifier": rich,
        "agreement": agree,
        "disagreement_note": (f"simple={simple_mapped}, rich={rich_mapped}" if not agree else ""),
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
