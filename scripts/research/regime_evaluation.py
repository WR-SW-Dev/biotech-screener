#!/usr/bin/env python3
"""Regime shadow evaluation harness.

Evaluates the regime detection shadow by computing:
  1. Classification accuracy (forward XBI returns by regime label)
  2. Switching payoff (hypothetical top-20 concentrate vs EW30)
  3. Bad-flip rate (regime changes that would have caused turnover for no benefit)
  4. Turnover-adjusted regret (cumulative cost of switching vs staying)
  5. Disagreement-period outcomes (when simple != rich, who was right?)
  6. Forward tracker for live shadow artifacts (daily accumulation)

Inputs:
    artifacts/regime_shadow/history.jsonl  — backfilled daily history
    artifacts/regime_shadow/*.json         — live daily shadow artifacts
    production_data/price_history.csv      — XBI prices for forward returns

Usage:
    python3 scripts/research/regime_evaluation.py
    python3 scripts/research/regime_evaluation.py --horizon 5     # 5-day forward
    python3 scripts/research/regime_evaluation.py --since 2024-01-01
    python3 scripts/research/regime_evaluation.py --live-only     # only daily artifacts
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

HISTORY_JSONL = PROJECT_ROOT / "artifacts" / "regime_shadow" / "history.jsonl"
SHADOW_DIR = PROJECT_ROOT / "artifacts" / "regime_shadow"
PRICE_CSV = PROJECT_ROOT / "production_data" / "price_history.csv"
OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "regime_evaluation"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_xbi_prices() -> Dict[str, float]:
    prices: Dict[str, float] = {}
    with open(PRICE_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("ticker") == "XBI":
                try:
                    prices[row["date"]] = float(row["close"])
                except (ValueError, KeyError):
                    pass
    return prices


def load_backfill_rows() -> List[Dict[str, Any]]:
    if not HISTORY_JSONL.exists():
        return []
    rows = []
    with open(HISTORY_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    rows.sort(key=lambda r: r.get("date", ""))
    return rows


def load_live_artifacts() -> List[Dict[str, Any]]:
    """Load daily shadow artifacts (v2 schema) into a flat format."""
    if not SHADOW_DIR.exists():
        return []
    rows = []
    for f in sorted(SHADOW_DIR.glob("2*.json")):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        simple = data.get("simple_classifier", {}).get("regime", "UNKNOWN")
        rich = data.get("rich_classifier", {})
        rich_regime = rich.get("regime", "UNKNOWN")
        rich_conf = rich.get("confidence", 0)
        agree = data.get("agreement", False)

        rows.append(
            {
                "date": data.get("as_of_date", f.stem),
                "simple": simple,
                "rich": rich_regime,
                "rich_confidence": rich_conf,
                "agreement": agree,
                "source": "live",
                "switching_recommendation": data.get("switching_policy", {}).get("recommendation", "ew30"),
                "rich_bear_streak": data.get("switching_policy", {}).get("rich_bear_streak", 0),
            }
        )
    return rows


def merge_rows(backfill: List[Dict], live: List[Dict]) -> List[Dict]:
    """Merge backfill + live, preferring live artifacts where dates overlap."""
    by_date: Dict[str, Dict] = {}
    for r in backfill:
        by_date[r["date"]] = r
    for r in live:
        by_date[r["date"]] = r  # live overwrites backfill
    return [by_date[d] for d in sorted(by_date)]


# ---------------------------------------------------------------------------
# Forward return computation
# ---------------------------------------------------------------------------


class ReturnCalculator:
    def __init__(self, prices: Dict[str, float]):
        self._prices = prices
        self._sorted = sorted(prices.keys())
        self._idx = {d: i for i, d in enumerate(self._sorted)}

    def forward_return(self, dt: str, horizon: int = 5) -> Optional[float]:
        """Forward return (%) from dt over horizon trading days."""
        # Find first trading day >= dt
        idx = None
        for i, d in enumerate(self._sorted):
            if d >= dt:
                idx = i
                break
        if idx is None:
            return None
        end = idx + horizon
        if end >= len(self._sorted):
            return None
        p0 = self._prices[self._sorted[idx]]
        p1 = self._prices[self._sorted[end]]
        if p0 <= 0:
            return None
        return (p1 / p0 - 1) * 100


# ---------------------------------------------------------------------------
# Evaluation metrics
# ---------------------------------------------------------------------------

BEAR_REGIMES = {"BEAR", "VOLATILITY_SPIKE", "CREDIT_CRISIS", "RECESSION_RISK"}


def _stats(vals: List[float]) -> Dict[str, Any]:
    if not vals:
        return {"n": 0, "mean": None, "t": None, "win_rate": None}
    n = len(vals)
    mean = sum(vals) / n
    if n > 1:
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
        t = mean / (std / math.sqrt(n)) if std > 0 else 0.0
    else:
        std = 0.0
        t = 0.0
    win = sum(1 for v in vals if v > 0) / n
    return {"n": n, "mean": round(mean, 4), "std": round(std, 4), "t": round(t, 2), "win_rate": round(win, 3)}


def evaluate_classification(rows: List[Dict], calc: ReturnCalculator, horizon: int) -> Dict[str, Any]:
    """Forward returns by regime label — does the label predict direction?"""
    buckets: Dict[str, List[float]] = defaultdict(list)

    for r in rows:
        fwd = calc.forward_return(r["date"], horizon)
        if fwd is None:
            continue
        buckets[f"simple={r['simple']}"].append(fwd)
        buckets[f"rich={r['rich']}"].append(fwd)
        agree = r.get(
            "agreement", r.get("agreement") == "True" if isinstance(r.get("agreement"), str) else r.get("agreement")
        )
        if isinstance(agree, str):
            agree = agree == "True"
        buckets[f"agree={'Y' if agree else 'N'}"].append(fwd)

        simple_bull = r["simple"] == "BULL"
        if agree and simple_bull:
            buckets["both_bullish"].append(fwd)
        elif agree and not simple_bull:
            buckets["both_bearish"].append(fwd)
        elif not agree and simple_bull:
            buckets["simple_bull_rich_bear"].append(fwd)
        else:
            buckets["simple_bear_rich_bull"].append(fwd)

    return {label: _stats(vals) for label, vals in sorted(buckets.items())}


def _compute_bear_streaks(rows: List[Dict]) -> List[int]:
    """Compute running bear streak for each row from the sequence itself."""
    streaks = []
    streak = 0
    for r in rows:
        if r["rich"] in BEAR_REGIMES:
            streak += 1
        else:
            streak = 0
        streaks.append(streak)
    return streaks


def _compute_recommendations(
    rows: List[Dict], min_bear_persistence: int = 3, min_confidence: float = 0.60
) -> List[str]:
    """Compute switching recommendation for each row, using computed bear streaks."""
    streaks = _compute_bear_streaks(rows)
    recs = []
    for i, r in enumerate(rows):
        agree = r.get("agreement")
        if isinstance(agree, str):
            agree = agree == "True"
        simple_bear = r["simple"] != "BULL"
        rich_bear = r["rich"] in BEAR_REGIMES
        rich_conf = float(r.get("rich_confidence", 0))
        bear_streak = streaks[i]

        if agree and simple_bear and rich_bear and rich_conf >= min_confidence and bear_streak >= min_bear_persistence:
            recs.append("top20_concentrate")
        else:
            recs.append("ew30")
    return recs


def evaluate_switching(
    rows: List[Dict], calc: ReturnCalculator, horizon: int, bear_reduction: float = 0.80, turnover_cost_bps: float = 50
) -> Dict[str, Any]:
    """Hypothetical switching payoff: concentrate in bear vs always-EW30.

    bear_reduction: exposure multiplier when in bear-concentrate mode (0.8 = 20% less exposure)
    turnover_cost_bps: one-way cost per switch (applied each time recommendation changes)
    """
    recs = _compute_recommendations(rows)
    ew30_rets: List[float] = []
    switch_rets: List[float] = []
    prev_rec = "ew30"
    n_switches = 0
    switch_costs = 0.0
    switch_dates: List[str] = []
    n_bear_days = 0

    for i, r in enumerate(rows):
        fwd = calc.forward_return(r["date"], horizon)
        if fwd is None:
            continue

        rec = recs[i]

        if rec != prev_rec:
            n_switches += 1
            switch_costs += turnover_cost_bps / 100
            switch_dates.append(r["date"])
        prev_rec = rec

        ew30_rets.append(fwd)
        if rec == "top20_concentrate":
            switch_rets.append(fwd * bear_reduction)
            n_bear_days += 1
        else:
            switch_rets.append(fwd)

    ew_cum = sum(ew30_rets)
    sw_cum = sum(switch_rets) - switch_costs

    return {
        "ew30_cumulative": round(ew_cum, 2),
        "switching_cumulative": round(sw_cum, 2),
        "delta": round(sw_cum - ew_cum, 2),
        "n_switches": n_switches,
        "switch_costs_pct": round(switch_costs, 2),
        "switch_dates": switch_dates,
        "n_observations": len(ew30_rets),
        "n_bear_days": n_bear_days,
        "bear_pct": round(100 * n_bear_days / len(ew30_rets), 1) if ew30_rets else 0,
    }


def evaluate_bad_flips(rows: List[Dict], calc: ReturnCalculator, horizon: int) -> Dict[str, Any]:
    """Regime changes that would have caused turnover for no benefit.

    A "bad flip" is a regime transition where:
      1. The recommendation changes, AND
      2. The forward return in the new regime is WORSE than staying
    """
    recs = _compute_recommendations(rows)
    flips: List[Dict] = []
    prev_rec = "ew30"

    for i, r in enumerate(rows):
        rec = recs[i]

        if rec != prev_rec:
            fwd = calc.forward_return(r["date"], horizon)
            if fwd is not None:
                # "Bad" = switched to bear-concentrate but market went up, or
                #         switched back to ew30 but market went down
                if rec == "top20_concentrate" and fwd > 0:
                    flips.append({"date": r["date"], "from": prev_rec, "to": rec, "fwd": round(fwd, 2), "bad": True})
                elif rec == "ew30" and prev_rec == "top20_concentrate" and fwd < 0:
                    flips.append({"date": r["date"], "from": prev_rec, "to": rec, "fwd": round(fwd, 2), "bad": True})
                else:
                    flips.append({"date": r["date"], "from": prev_rec, "to": rec, "fwd": round(fwd, 2), "bad": False})
        prev_rec = rec

    n_bad = sum(1 for f in flips if f["bad"])
    n_total = len(flips)
    return {
        "total_flips": n_total,
        "bad_flips": n_bad,
        "bad_flip_rate": round(n_bad / n_total, 3) if n_total > 0 else None,
        "flips": flips,
    }


def evaluate_disagreement(rows: List[Dict], calc: ReturnCalculator, horizon: int) -> Dict[str, Any]:
    """When simple and rich disagree, who was right?

    "Right" = the classifier whose label better predicted the forward return direction.
    """
    simple_right = 0
    rich_right = 0
    neither = 0
    disagreements: List[Dict] = []

    for r in rows:
        agree = r.get("agreement")
        if isinstance(agree, str):
            agree = agree == "True"
        if agree:
            continue

        fwd = calc.forward_return(r["date"], horizon)
        if fwd is None:
            continue

        simple_bull = r["simple"] == "BULL"
        rich_bull = r["rich"] == "BULL"
        market_up = fwd > 0

        simple_correct = simple_bull == market_up
        rich_correct = rich_bull == market_up

        if simple_correct and not rich_correct:
            simple_right += 1
            winner = "simple"
        elif rich_correct and not simple_correct:
            rich_right += 1
            winner = "rich"
        else:
            neither += 1
            winner = "both" if simple_correct else "neither"

        disagreements.append(
            {
                "date": r["date"],
                "simple": r["simple"],
                "rich": r["rich"],
                "fwd": round(fwd, 2),
                "winner": winner,
            }
        )

    total = simple_right + rich_right + neither
    return {
        "total_disagreements": total,
        "simple_right": simple_right,
        "rich_right": rich_right,
        "both_or_neither": neither,
        "simple_accuracy": round(simple_right / total, 3) if total > 0 else None,
        "rich_accuracy": round(rich_right / total, 3) if total > 0 else None,
        "recent_10": disagreements[-10:] if disagreements else [],
    }


def evaluate_persistence(rows: List[Dict]) -> Dict[str, Any]:
    """Regime persistence stats — how stable are the labels?"""
    rich_streaks: Dict[str, List[int]] = defaultdict(list)
    simple_streaks: Dict[str, List[int]] = defaultdict(list)

    # Rich
    if rows:
        curr = rows[0]["rich"]
        slen = 1
        for i in range(1, len(rows)):
            if rows[i]["rich"] == curr:
                slen += 1
            else:
                rich_streaks[curr].append(slen)
                curr = rows[i]["rich"]
                slen = 1
        rich_streaks[curr].append(slen)

        # Simple
        curr = rows[0]["simple"]
        slen = 1
        for i in range(1, len(rows)):
            if rows[i]["simple"] == curr:
                slen += 1
            else:
                simple_streaks[curr].append(slen)
                curr = rows[i]["simple"]
                slen = 1
        simple_streaks[curr].append(slen)

    def _streak_stats(streaks: List[int]) -> Dict:
        if not streaks:
            return {}
        s = sorted(streaks)
        return {
            "episodes": len(s),
            "median_days": s[len(s) // 2],
            "mean_days": round(sum(s) / len(s), 1),
            "max_days": max(s),
        }

    return {
        "rich": {k: _streak_stats(v) for k, v in sorted(rich_streaks.items(), key=lambda x: -len(x[1]))},
        "simple": {k: _streak_stats(v) for k, v in sorted(simple_streaks.items(), key=lambda x: -len(x[1]))},
    }


def evaluate_turnover_regret(rows: List[Dict], calc: ReturnCalculator, horizon: int) -> Dict[str, Any]:
    """Cumulative regret from switching vs staying in EW30.

    Regret = cumulative switching_return - cumulative ew30_return
    Tracks running regret over time to see if switching ever pays off.
    """
    recs = _compute_recommendations(rows)
    regret_series: List[Dict] = []
    cum_regret = 0.0
    prev_rec = "ew30"

    for i, r in enumerate(rows):
        fwd = calc.forward_return(r["date"], horizon)
        if fwd is None:
            continue

        rec = recs[i]

        # Regret = what switching costs vs doing nothing
        if rec == "top20_concentrate":
            period_regret = fwd * 0.80 - fwd  # = -0.20 * fwd
        else:
            period_regret = 0.0

        if rec != prev_rec:
            period_regret -= 0.50  # 50bps turnover cost

        cum_regret += period_regret
        prev_rec = rec

        regret_series.append(
            {
                "date": r["date"],
                "period_regret": round(period_regret, 4),
                "cumulative_regret": round(cum_regret, 4),
                "recommendation": rec,
            }
        )

    # Find worst and best regret points
    if regret_series:
        worst = min(regret_series, key=lambda x: x["cumulative_regret"])
        best = max(regret_series, key=lambda x: x["cumulative_regret"])
    else:
        worst = best = {}

    return {
        "final_regret": round(cum_regret, 2),
        "worst_regret": worst,
        "best_regret": best,
        "n_bear_days": sum(1 for s in regret_series if s["recommendation"] == "top20_concentrate"),
        "series_tail": regret_series[-20:] if regret_series else [],
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(results: Dict[str, Any], horizon: int):
    print(f"\n{'=' * 70}")
    print(f"REGIME SHADOW EVALUATION — {horizon}-day forward horizon")
    print(f"{'=' * 70}")

    # Classification accuracy
    clf = results["classification"]
    print(f"\n--- Classification Accuracy ({horizon}d forward XBI) ---")
    for label in [
        "simple=BULL",
        "simple=BEAR",
        "rich=BULL",
        "rich=BEAR",
        "rich=RECESSION_RISK",
        "rich=CREDIT_CRISIS",
        "rich=VOLATILITY_SPIKE",
        "agree=Y",
        "agree=N",
        "both_bullish",
        "both_bearish",
        "simple_bull_rich_bear",
        "simple_bear_rich_bull",
    ]:
        s = clf.get(label, {})
        if not s or s.get("n", 0) == 0:
            continue
        print(f"  {label:30s}: n={s['n']:4d}  mean={s['mean']:+.4f}%  t={s['t']:+.2f}  win={s['win_rate']:.0%}")

    # Switching payoff
    sw = results["switching"]
    print("\n--- Switching Payoff ---")
    print(f"  EW30 always:  {sw['ew30_cumulative']:+.2f}%")
    print(f"  Switching:    {sw['switching_cumulative']:+.2f}%")
    print(f"  Delta:        {sw['delta']:+.2f}%  ({sw['n_switches']} switches, {sw['switch_costs_pct']:.2f}% cost)")

    # Bad flips
    bf = results["bad_flips"]
    print("\n--- Bad Flips ---")
    print(f"  Total flips: {bf['total_flips']}, Bad: {bf['bad_flips']}, Rate: {bf['bad_flip_rate']}")
    if bf["flips"]:
        for fl in bf["flips"][-5:]:
            tag = "BAD " if fl["bad"] else "OK  "
            print(f"    {tag} {fl['date']} {fl['from']}->{fl['to']} fwd={fl['fwd']:+.2f}%")

    # Disagreement
    dis = results["disagreement"]
    print("\n--- Disagreement Analysis ---")
    print(f"  Total: {dis['total_disagreements']}")
    print(f"  Simple right: {dis['simple_right']} ({dis['simple_accuracy']})")
    print(f"  Rich right:   {dis['rich_right']} ({dis['rich_accuracy']})")
    print(f"  Both/neither:  {dis['both_or_neither']}")
    if dis["recent_10"]:
        print("  Recent disagreements:")
        for d in dis["recent_10"]:
            print(
                f"    {d['date']} simple={d['simple']:5s} rich={d['rich']:20s} fwd={d['fwd']:+.2f}% winner={d['winner']}"
            )

    # Persistence
    per = results["persistence"]
    print("\n--- Regime Persistence ---")
    print("  Rich classifier:")
    for reg, s in per["rich"].items():
        print(
            f"    {reg:20s}: {s['episodes']:3d} episodes, median={s['median_days']}d, mean={s['mean_days']}d, max={s['max_days']}d"
        )
    print("  Simple classifier:")
    for reg, s in per["simple"].items():
        print(
            f"    {reg:20s}: {s['episodes']:3d} episodes, median={s['median_days']}d, mean={s['mean_days']}d, max={s['max_days']}d"
        )

    # Turnover regret
    tr = results["turnover_regret"]
    print("\n--- Turnover-Adjusted Regret ---")
    print(f"  Final regret: {tr['final_regret']:+.2f}%")
    print(f"  Bear-mode days: {tr['n_bear_days']}")
    if tr.get("worst_regret"):
        print(
            f"  Worst point: {tr['worst_regret'].get('date', '?')} at {tr['worst_regret'].get('cumulative_regret', '?')}%"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_evaluation(horizon: int = 5, since: Optional[str] = None, live_only: bool = False) -> Dict[str, Any]:
    prices = load_xbi_prices()
    calc = ReturnCalculator(prices)

    if live_only:
        rows = load_live_artifacts()
    else:
        backfill = load_backfill_rows()
        live = load_live_artifacts()
        rows = merge_rows(backfill, live)

    if since:
        rows = [r for r in rows if r["date"] >= since]

    results = {
        "horizon": horizon,
        "n_observations": len(rows),
        "date_range": (rows[0]["date"], rows[-1]["date"]) if rows else (None, None),
        "classification": evaluate_classification(rows, calc, horizon),
        "switching": evaluate_switching(rows, calc, horizon),
        "bad_flips": evaluate_bad_flips(rows, calc, horizon),
        "disagreement": evaluate_disagreement(rows, calc, horizon),
        "persistence": evaluate_persistence(rows),
        "turnover_regret": evaluate_turnover_regret(rows, calc, horizon),
    }
    return results


def main():
    parser = argparse.ArgumentParser(description="Evaluate regime shadow detection")
    parser.add_argument("--horizon", type=int, default=5, help="Forward return horizon (trading days)")
    parser.add_argument("--since", default=None, help="Only evaluate from this date onward")
    parser.add_argument("--live-only", action="store_true", help="Only use live daily artifacts")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text report")
    args = parser.parse_args()

    results = run_evaluation(horizon=args.horizon, since=args.since, live_only=args.live_only)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"regime_eval_h{args.horizon}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print_report(results, args.horizon)
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
