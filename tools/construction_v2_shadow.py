"""Construction v2 shadow portfolio — EW Top-30 + regime overlay.

Runs daily alongside the legacy shadow. Produces:
  - artifacts/construction_v2/positions/{date}.json
  - artifacts/construction_v2/performance.csv

Three tracked variants:
  1. ew30: EW Top-30 (default control)
  2. regime: Regime-conditioned (bear=Top-20, bull=Top-30)
  3. legacy: pointer to existing shadow for comparison

Usage:
    python tools/construction_v2_shadow.py --as-of-date 2026-04-01
    python tools/construction_v2_shadow.py --backfill --start-date 2026-03-01
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
PRICE_PATH = REPO_ROOT / "production_data" / "price_history.csv"
SHADOW_PERF_PATH = REPO_ROOT / "artifacts" / "live_shadow" / "performance.csv"
V2_DIR = REPO_ROOT / "artifacts" / "construction_v2"
V2_POSITIONS_DIR = V2_DIR / "positions"
V2_PERF_PATH = V2_DIR / "performance.csv"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("construction_v2")

ACCOUNT_USD = 500_000


# ---------------------------------------------------------------------------
# Regime classifier
# ---------------------------------------------------------------------------


class RegimeClassifier:
    """Simple, ex-ante XBI regime classifier with hysteresis.

    Bear: XBI 20-day return <= bear_threshold AND confirmed for min_duration days
    Bull: otherwise

    Hysteresis: once in a regime, stay until the opposite threshold is crossed.
    This prevents whipsawing on noisy daily returns.
    """

    def __init__(
        self,
        lookback_days: int = 20,
        bear_threshold: float = -0.02,  # XBI 20d return <= -2% → bear
        bull_threshold: float = 0.02,  # XBI 20d return > +2% → bull (exit bear)
        min_duration_days: int = 5,  # stay in regime at least 5 days
    ):
        self.lookback_days = lookback_days
        self.bear_threshold = bear_threshold
        self.bull_threshold = bull_threshold
        self.min_duration_days = min_duration_days
        self._current_regime = "bull"
        self._regime_start_date = "2000-01-01"

    def classify(self, all_prices: dict[str, dict[str, float]], current_date: str) -> str:
        """Classify regime as of current_date. Returns 'bear' or 'bull'."""
        sorted_dates = sorted(d for d in all_prices if d <= current_date)
        if len(sorted_dates) < self.lookback_days + 1:
            return "bull"

        lookback_date = sorted_dates[-(self.lookback_days + 1)]
        xbi_now = all_prices.get(current_date, {}).get("XBI")
        xbi_then = all_prices.get(lookback_date, {}).get("XBI")

        if not xbi_now or not xbi_then or xbi_then <= 0:
            return self._current_regime

        xbi_ret = (xbi_now / xbi_then) - 1.0

        # Hysteresis: only flip if threshold crossed AND min duration met
        days_in_regime = _days_between(self._regime_start_date, current_date)

        if self._current_regime == "bull":
            if xbi_ret <= self.bear_threshold and days_in_regime >= self.min_duration_days:
                self._current_regime = "bear"
                self._regime_start_date = current_date
        else:  # bear
            if xbi_ret > self.bull_threshold and days_in_regime >= self.min_duration_days:
                self._current_regime = "bull"
                self._regime_start_date = current_date

        return self._current_regime

    def to_dict(self) -> dict:
        return {
            "current_regime": self._current_regime,
            "regime_start_date": self._regime_start_date,
            "lookback_days": self.lookback_days,
            "bear_threshold": self.bear_threshold,
            "bull_threshold": self.bull_threshold,
            "min_duration_days": self.min_duration_days,
        }


def _days_between(d1: str, d2: str) -> int:
    try:
        dt1 = datetime.strptime(d1, "%Y-%m-%d")
        dt2 = datetime.strptime(d2, "%Y-%m-%d")
        return (dt2 - dt1).days
    except (ValueError, TypeError):
        return 999


# ---------------------------------------------------------------------------
# Portfolio builders
# ---------------------------------------------------------------------------


def load_rankings(snapshot_date: str) -> list[dict]:
    rpath = SNAPSHOT_DIR / snapshot_date / "rankings.csv"
    if not rpath.exists():
        return []
    with open(rpath, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ranked = []
    for r in rows:
        ar = r.get("actionable_rank", "").strip()
        if ar:
            try:
                r["_rank"] = int(ar)
                ranked.append(r)
            except ValueError:
                pass
    ranked.sort(key=lambda r: r["_rank"])
    return ranked


def classify_bucket(row: dict) -> str:
    cd_raw = row.get("catalyst_days", "").strip()
    try:
        cd = float(cd_raw)
    except (ValueError, TypeError):
        return "less_binary"
    if cd <= 0:
        return "less_binary"
    elif cd <= 30:
        return "binary_0_30"
    elif cd <= 90:
        return "binary_31_90"
    elif cd <= 180:
        return "binary_91_180"
    return "less_binary"


def build_ew_positions(rankings: list[dict], n: int) -> list[dict]:
    sel = rankings[:n]
    if not sel:
        return []
    w = 100.0 / len(sel)
    return [
        {
            "ticker": r["ticker"].upper(),
            "weight_pct": round(w, 4),
            "target_dollars": round(ACCOUNT_USD * w / 100, 2),
            "rank": r["_rank"],
            "tier": r.get("tier_any", ""),
            "bucket": classify_bucket(r),
            "catalyst_days": r.get("catalyst_days", ""),
        }
        for r in sel
    ]


# ---------------------------------------------------------------------------
# Performance tracking
# ---------------------------------------------------------------------------


def load_price_map_for_dates(dates: list[str]) -> dict[str, dict[str, float]]:
    """Load only the dates we need from price_history.csv."""
    date_set = set(dates)
    prices: dict[str, dict[str, float]] = defaultdict(dict)
    with open(PRICE_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dt = row.get("date", "").strip()
            if dt not in date_set:
                continue
            tk = row.get("ticker", "").strip()
            cl = row.get("close", "").strip()
            if tk and cl:
                try:
                    prices[dt][tk] = float(cl)
                except ValueError:
                    pass
    return dict(prices)


def compute_variant_return(
    positions: list[dict],
    prior_prices: dict[str, float],
    current_prices: dict[str, float],
) -> dict:
    if not positions:
        return {"pnl_pct": 0.0, "pnl_dollars": 0.0, "n_held": 0}
    tw = sum(p["weight_pct"] for p in positions)
    if tw == 0:
        return {"pnl_pct": 0.0, "pnl_dollars": 0.0, "n_held": 0}

    weighted_ret = 0.0
    for p in positions:
        w = p["weight_pct"] / tw
        p0 = prior_prices.get(p["ticker"])
        p1 = current_prices.get(p["ticker"])
        if p0 and p1 and p0 > 0:
            weighted_ret += w * ((p1 / p0) - 1.0)

    pnl_pct = weighted_ret * 100
    pnl_dollars = ACCOUNT_USD * weighted_ret
    return {"pnl_pct": round(pnl_pct, 4), "pnl_dollars": round(pnl_dollars, 2), "n_held": len(positions)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_for_date(
    as_of_date: str,
    all_prices: dict[str, dict[str, float]],
    regime_classifier: RegimeClassifier,
) -> dict | None:
    """Build positions and compute performance for one date."""
    rankings = load_rankings(as_of_date)
    if not rankings:
        return None

    regime = regime_classifier.classify(all_prices, as_of_date)

    # Build variants
    ew30_positions = build_ew_positions(rankings, 30)
    regime_n = 20 if regime == "bear" else 30
    regime_positions = build_ew_positions(rankings, regime_n)

    return {
        "as_of_date": as_of_date,
        "regime": regime,
        "regime_detail": regime_classifier.to_dict(),
        "variants": {
            "ew30": {
                "label": "EW Top-30",
                "n_positions": len(ew30_positions),
                "positions": ew30_positions,
            },
            "regime": {
                "label": f"Regime Top-{regime_n} ({regime})",
                "n_positions": len(regime_positions),
                "positions": regime_positions,
            },
        },
    }


def run_shadow(as_of_date: str, backfill: bool = False, start_date: str = ""):
    """Main entry point."""
    V2_POSITIONS_DIR.mkdir(parents=True, exist_ok=True)

    # Get dates to process
    if backfill and start_date:
        dates = sorted(
            d.name
            for d in SNAPSHOT_DIR.iterdir()
            if d.is_dir() and d.name >= start_date and d.name <= as_of_date and (d / "rankings.csv").exists()
        )
    else:
        dates = [as_of_date]

    log.info("Processing %d date(s): %s to %s", len(dates), dates[0] if dates else "?", dates[-1] if dates else "?")

    # Load prices for all needed dates (plus one prior for return computation)
    all_snapshot_dates = sorted(d.name for d in SNAPSHOT_DIR.iterdir() if d.is_dir() and (d / "rankings.csv").exists())
    price_dates = set(dates)
    for d in dates:
        idx = all_snapshot_dates.index(d) if d in all_snapshot_dates else -1
        if idx > 0:
            price_dates.add(all_snapshot_dates[idx - 1])
    all_prices = load_price_map_for_dates(sorted(price_dates))

    regime_classifier = RegimeClassifier()

    # Process each date
    results = []
    for d in dates:
        result = run_for_date(d, all_prices, regime_classifier)
        if not result:
            continue

        # Save positions
        pos_path = V2_POSITIONS_DIR / f"{d}.json"
        with open(pos_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        results.append(result)
        log.info(
            "%s: regime=%s, ew30=%d names, regime_variant=%d names",
            d,
            result["regime"],
            result["variants"]["ew30"]["n_positions"],
            result["variants"]["regime"]["n_positions"],
        )

    # Compute performance for sequential dates
    if len(results) >= 2:
        perf_rows = []
        for i in range(1, len(results)):
            prior = results[i - 1]
            current = results[i]
            prior_date = prior["as_of_date"]
            current_date = current["as_of_date"]

            pp = all_prices.get(prior_date, {})
            cp = all_prices.get(current_date, {})
            if not pp or not cp:
                continue

            xbi_p0 = pp.get("XBI")
            xbi_p1 = cp.get("XBI")
            xbi_ret = ((xbi_p1 / xbi_p0) - 1.0) * 100 if xbi_p0 and xbi_p1 else 0

            row = {
                "date": current_date,
                "prior_date": prior_date,
                "regime": current["regime"],
                "xbi_pct": round(xbi_ret, 4),
            }

            for vid in ["ew30", "regime"]:
                prior_pos = prior["variants"][vid]["positions"]
                ret = compute_variant_return(prior_pos, pp, cp)
                row[f"{vid}_pnl_pct"] = ret["pnl_pct"]
                row[f"{vid}_pnl_dollars"] = ret["pnl_dollars"]
                row[f"{vid}_excess"] = round(ret["pnl_pct"] - xbi_ret, 4)
                row[f"{vid}_n_held"] = ret["n_held"]

            perf_rows.append(row)

        # Append to performance CSV
        write_header = not V2_PERF_PATH.exists()
        with open(V2_PERF_PATH, "a", encoding="utf-8") as f:
            if write_header:
                cols = list(perf_rows[0].keys())
                f.write(",".join(cols) + "\n")
            for row in perf_rows:
                f.write(",".join(str(row.get(c, "")) for c in perf_rows[0].keys()) + "\n")

        # Print summary
        cum_ew30 = sum(r["ew30_pnl_pct"] for r in perf_rows)
        cum_regime = sum(r["regime_pnl_pct"] for r in perf_rows)
        cum_xbi = sum(r["xbi_pct"] for r in perf_rows)
        log.info(
            "Performance (%d periods): EW30 cum=%+.2f%% (excess %+.2f%%), "
            "Regime cum=%+.2f%% (excess %+.2f%%), XBI=%+.2f%%",
            len(perf_rows),
            cum_ew30,
            cum_ew30 - cum_xbi,
            cum_regime,
            cum_regime - cum_xbi,
            cum_xbi,
        )

    log.info("Done. Positions: %s, Performance: %s", V2_POSITIONS_DIR, V2_PERF_PATH)


def main():
    parser = argparse.ArgumentParser(description="Construction v2 shadow portfolio")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--start-date", default="2026-03-01")
    args = parser.parse_args()

    run_shadow(args.as_of_date, args.backfill, args.start_date)


if __name__ == "__main__":
    main()
