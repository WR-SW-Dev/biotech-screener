"""Rolling options EV pilot summary — auto-updates as horizons mature.

Frozen study design (do not change definitions):
  - event-loaded vs flat (opt_event_premium YES/NO)
  - EPR terciles (front/back IV ratio)
  - IV regime buckets (NORMAL/ELEVATED/EXTREME)
  - hard vs soft catalyst
  - liquid vs thin chain
  - within-top-30 split (the strategically important cut)

Reports the same tables for h5, h20, h63 as each horizon matures.
Designed to run periodically and extend itself as new data arrives.

Usage:
    python scripts/research/rolling_options_ev_summary.py
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
PIT_CACHE_DIR = REPO_ROOT / "data" / "caches" / "price_pit" / "PIT"
OUTPUT_PATH = REPO_ROOT / "output" / "options" / "options_ev_pilot_summary.json"

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("rolling_ev")


def _sf(v) -> float:
    if v is None or v == "" or v == "None":
        return float("nan")
    try:
        return float(v)
    except (ValueError, TypeError):
        return float("nan")


def _cohort_stats(rets: list[float], label: str) -> dict:
    if len(rets) < 3:
        return {"label": label, "n": len(rets), "mean": None, "median": None, "pct_positive": None}
    return {
        "label": label,
        "n": len(rets),
        "mean": round(statistics.mean(rets), 5),
        "median": round(statistics.median(rets), 5),
        "pct_positive": round(sum(1 for r in rets if r > 0) / len(rets), 3),
    }


def load_obs_for_date(snapshot_date: str, horizon: str) -> list[dict]:
    """Load observations with options data and forward returns for one date."""
    rpath = SNAPSHOT_DIR / snapshot_date / "rankings.csv"
    pit_path = PIT_CACHE_DIR / snapshot_date / "prices.csv"
    if not rpath.exists() or not pit_path.exists():
        return []

    # Load returns for this horizon
    h_close_col = f"{horizon}_close"
    returns = {}
    with open(pit_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tk = row.get("ticker", "").upper()
            p0 = _sf(row.get("anchor_close"))
            ph = _sf(row.get(h_close_col))
            if not math.isnan(p0) and not math.isnan(ph) and p0 > 0 and abs(ph / p0 - 1) < 3:
                returns[tk] = ph / p0 - 1

    if not returns:
        return []

    # Load rankings with options
    with open(rpath, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    result = []
    for r in rows:
        tk = r.get("ticker", "").upper()
        ar = r.get("actionable_rank", "").strip()
        if not ar or tk not in returns or r.get("opt_has_data") != "1":
            continue

        front = _sf(r.get("opt_front_iv"))
        back = _sf(r.get("opt_back_iv"))
        epr = front / back if not math.isnan(front) and not math.isnan(back) and back > 0 else float("nan")

        result.append(
            {
                "ticker": tk,
                "date": snapshot_date,
                "rank": int(ar),
                "fwd_return": returns[tk],
                "event_premium": r.get("opt_event_premium") == "YES",
                "iv_regime": r.get("opt_iv_regime", ""),
                "liquid": r.get("opt_liquidity_ok") == "1",
                "is_hard": r.get("is_hard_catalyst") == "1",
                "family": (r.get("catalyst_family") or "").upper(),
                "epr": epr,
            }
        )
    return result


def run_studies(obs: list[dict], horizon: str) -> dict:
    """Run the frozen study design on a set of observations."""
    if not obs:
        return {"horizon": horizon, "n_obs": 0, "n_dates": 0}

    dates = sorted(set(o["date"] for o in obs))

    # --- Study 1: Event-loaded vs flat ---
    ep = [o["fwd_return"] for o in obs if o["event_premium"]]
    flat = [o["fwd_return"] for o in obs if not o["event_premium"]]
    study1 = {
        "event_loaded": _cohort_stats(ep, "event_loaded"),
        "flat": _cohort_stats(flat, "flat"),
    }
    if len(ep) >= 3 and len(flat) >= 3:
        study1["spread"] = round(statistics.mean(ep) - statistics.mean(flat), 5)

    # --- Study 2: EPR terciles ---
    epr_obs = sorted([o for o in obs if not math.isnan(o["epr"])], key=lambda o: o["epr"])
    study2 = {}
    if len(epr_obs) >= 9:
        n = len(epr_obs)
        t1 = [o["fwd_return"] for o in epr_obs[: n // 3]]
        t3 = [o["fwd_return"] for o in epr_obs[2 * n // 3 :]]
        study2["top_epr"] = _cohort_stats(t3, "top_epr_tercile")
        study2["bottom_epr"] = _cohort_stats(t1, "bottom_epr_tercile")
        study2["spread"] = round(statistics.mean(t3) - statistics.mean(t1), 5)

    # --- Study 3: IV regime ---
    study3 = {}
    for regime in ["NORMAL", "ELEVATED", "EXTREME"]:
        rets = [o["fwd_return"] for o in obs if o["iv_regime"] == regime]
        study3[regime] = _cohort_stats(rets, regime)

    # --- Study 4: Hard vs soft ---
    study4 = {
        "hard": _cohort_stats([o["fwd_return"] for o in obs if o["is_hard"]], "hard"),
        "soft": _cohort_stats([o["fwd_return"] for o in obs if not o["is_hard"]], "soft"),
    }

    # --- Study 5: Liquid vs thin ---
    study5 = {
        "liquid": _cohort_stats([o["fwd_return"] for o in obs if o["liquid"]], "liquid"),
        "thin": _cohort_stats([o["fwd_return"] for o in obs if not o["liquid"]], "thin"),
    }

    # --- Study 6: Within top-30 (THE KEY STUDY) ---
    top30 = [o for o in obs if o["rank"] <= 30]
    study6 = {}
    if top30:
        t30_ep = [o["fwd_return"] for o in top30 if o["event_premium"]]
        t30_flat = [o["fwd_return"] for o in top30 if not o["event_premium"]]
        study6["event_loaded"] = _cohort_stats(t30_ep, "top30_event_loaded")
        study6["flat"] = _cohort_stats(t30_flat, "top30_flat")
        if len(t30_ep) >= 3 and len(t30_flat) >= 3:
            study6["spread"] = round(statistics.mean(t30_ep) - statistics.mean(t30_flat), 5)

        # EPR within top-30
        t30_epr = sorted([o for o in top30 if not math.isnan(o["epr"])], key=lambda o: o["epr"])
        if len(t30_epr) >= 6:
            n = len(t30_epr)
            t30_hi = [o["fwd_return"] for o in t30_epr[n // 2 :]]
            t30_lo = [o["fwd_return"] for o in t30_epr[: n // 2]]
            study6["epr_top_half"] = _cohort_stats(t30_hi, "top30_epr_top_half")
            study6["epr_bottom_half"] = _cohort_stats(t30_lo, "top30_epr_bottom_half")
            study6["epr_spread"] = round(statistics.mean(t30_hi) - statistics.mean(t30_lo), 5)

    return {
        "horizon": horizon,
        "n_obs": len(obs),
        "n_dates": len(dates),
        "dates": dates,
        "event_loaded_vs_flat": study1,
        "epr_terciles": study2,
        "iv_regime": study3,
        "hard_vs_soft": study4,
        "liquid_vs_thin": study5,
        "within_top30": study6,
    }


def run_rolling_summary() -> dict:
    """Run the full rolling summary across all available data."""
    # Find dates with options data (March 15+ based on earlier analysis)
    all_dates = sorted(
        d.name
        for d in SNAPSHOT_DIR.iterdir()
        if d.is_dir()
        and d.name >= "2026-03-15"
        and (d / "rankings.csv").exists()
        and (PIT_CACHE_DIR / d.name / "prices.csv").exists()
    )
    log.info("Found %d candidate dates (2026-03-15+)", len(all_dates))

    results_by_horizon = {}
    for horizon in ["h5", "h20", "h63"]:
        all_obs = []
        for d in all_dates:
            obs = load_obs_for_date(d, horizon)
            all_obs.extend(obs)

        if all_obs:
            log.info("%s: %d observations across %d dates", horizon, len(all_obs), len(set(o["date"] for o in all_obs)))
        results_by_horizon[horizon] = run_studies(all_obs, horizon)

    return {
        "schema": "options_ev_pilot_summary.v1",
        "generated_at": datetime.now().isoformat(),
        "design_frozen": True,
        "design_version": "2026-04-01",
        "horizons": results_by_horizon,
    }


def print_summary(result: dict):
    print(f"\n{'='*70}")
    print("ROLLING OPTIONS EV PILOT SUMMARY")
    print(f"{'='*70}")

    for horizon, h in result["horizons"].items():
        if h["n_obs"] == 0:
            print(f"\n{horizon}: no observations yet")
            continue

        print(f"\n--- {horizon} ({h['n_obs']} obs, {h['n_dates']} dates: {h['dates'][0]} to {h['dates'][-1]}) ---")

        def _pr(study, key1, key2, spread_key="spread"):
            s1 = study.get(key1, {})
            s2 = study.get(key2, {})
            sp = study.get(spread_key)
            m1 = f"{s1['mean']:>+.4f}" if s1.get("mean") is not None else "—"
            m2 = f"{s2['mean']:>+.4f}" if s2.get("mean") is not None else "—"
            p1 = f"{s1['pct_positive']:.0%}" if s1.get("pct_positive") is not None else "—"
            p2 = f"{s2['pct_positive']:.0%}" if s2.get("pct_positive") is not None else "—"
            n1 = s1.get("n", 0)
            n2 = s2.get("n", 0)
            sp_str = f"{sp:>+.4f}" if sp is not None else "—"
            label1 = s1.get("label", key1)
            label2 = s2.get("label", key2)
            print(f"    {label1:<30} n={n1:<5} mean={m1}  %+={p1}")
            print(f"    {label2:<30} n={n2:<5} mean={m2}  %+={p2}")
            print(f"    {'SPREAD':<30}        {sp_str}")

        print("  Event-loaded vs flat:")
        _pr(h["event_loaded_vs_flat"], "event_loaded", "flat")

        if h.get("epr_terciles"):
            print("  EPR terciles:")
            _pr(h["epr_terciles"], "top_epr", "bottom_epr")

        print("  IV regime:")
        for regime in ["NORMAL", "ELEVATED", "EXTREME"]:
            s = h["iv_regime"].get(regime, {})
            m = f"{s['mean']:>+.4f}" if s.get("mean") is not None else "—"
            p = f"{s['pct_positive']:.0%}" if s.get("pct_positive") is not None else "—"
            print(f"    {regime:<30} n={s.get('n', 0):<5} mean={m}  %+={p}")

        if h.get("within_top30"):
            t30 = h["within_top30"]
            print("  ** WITHIN TOP-30 (key study):")
            if "event_loaded" in t30 and "flat" in t30:
                _pr(t30, "event_loaded", "flat")
            if "epr_top_half" in t30:
                _pr(t30, "epr_top_half", "epr_bottom_half", "epr_spread")


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result = run_rolling_summary()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", OUTPUT_PATH)

    print_summary(result)


if __name__ == "__main__":
    main()
