"""Liquidity-gated options EV pilot — hard catalyst / regulatory names.

Questions answered:
  1. Do event-loaded surfaces outperform flat ones?
  2. Do skew-extreme names resolve differently by catalyst type?
  3. Is implied-vs-realized mispricing systematic in regulatory names?
  4. Does event premium ratio predict forward return direction?

Scope: liquid-chain, hard-catalyst, regulatory-family names with
PIT options data and forward returns from price cache.

Usage:
    python scripts/research/options_ev_pilot.py
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
PIT_CACHE_DIR = REPO_ROOT / "data" / "caches" / "price_pit" / "PIT"
OUTPUT_DIR = REPO_ROOT / "output" / "options"

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("options_ev_pilot")


def _sf(v) -> float:
    if v is None or v == "" or v == "None":
        return float("nan")
    try:
        return float(v)
    except (ValueError, TypeError):
        return float("nan")


def load_snapshot_with_returns(snapshot_date: str) -> list[dict]:
    """Load ranked names with options fields + forward returns."""
    rpath = SNAPSHOT_DIR / snapshot_date / "rankings.csv"
    pit_path = PIT_CACHE_DIR / snapshot_date / "prices.csv"
    if not rpath.exists() or not pit_path.exists():
        return []

    # Load returns
    returns = {}
    with open(pit_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tk = row.get("ticker", "").upper()
            p0 = _sf(row.get("anchor_close"))
            p20 = _sf(row.get("h20_close"))
            if tk and not math.isnan(p0) and not math.isnan(p20) and p0 > 0:
                ret = (p20 / p0) - 1.0
                if abs(ret) < 3.0:
                    returns[tk] = ret

    # Load rankings + options
    with open(rpath, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    result = []
    for r in rows:
        tk = r.get("ticker", "").upper()
        ar = r.get("actionable_rank", "").strip()
        if not ar or tk not in returns:
            continue

        front_iv = _sf(r.get("opt_front_iv"))
        back_iv = _sf(r.get("opt_back_iv"))
        epr = (
            (front_iv / back_iv)
            if (not math.isnan(front_iv) and not math.isnan(back_iv) and back_iv > 0)
            else float("nan")
        )

        result.append(
            {
                "ticker": tk,
                "snapshot_date": snapshot_date,
                "actionable_rank": int(ar),
                "return_h20": returns[tk],
                # Catalyst
                "is_hard_catalyst": r.get("is_hard_catalyst") == "1",
                "catalyst_family": (r.get("catalyst_family") or "").upper(),
                "catalyst_days": _sf(r.get("catalyst_days")),
                "catalyst_event_type": r.get("catalyst_event_type", ""),
                # Options
                "opt_has_data": r.get("opt_has_data") == "1",
                "opt_liquidity_ok": r.get("opt_liquidity_ok") == "1",
                "opt_atm_iv": _sf(r.get("opt_atm_iv")),
                "opt_rr_25d": _sf(r.get("opt_rr_25d")),
                "opt_term_slope": _sf(r.get("opt_term_slope")),
                "opt_event_premium": r.get("opt_event_premium", "") == "YES",
                "opt_iv_regime": r.get("opt_iv_regime", ""),
                "event_premium_ratio": epr,
                "actual_implied_move_pctile": _sf(r.get("actual_implied_move_pctile")),
            }
        )

    return result


def _cohort_return_stats(names: list[dict], label: str) -> dict:
    """Compute return stats for a cohort."""
    rets = [n["return_h20"] for n in names]
    if not rets:
        return {"label": label, "n": 0}
    return {
        "label": label,
        "n": len(rets),
        "mean_return": round(statistics.mean(rets), 4),
        "median_return": round(statistics.median(rets), 4),
        "pct_positive": round(sum(1 for r in rets if r > 0) / len(rets), 3),
        "std": round(statistics.stdev(rets), 4) if len(rets) > 1 else 0,
    }


def run_pilot() -> dict:
    # Find all dates with both snapshots and PIT caches
    cache_dates = sorted(
        d.name for d in PIT_CACHE_DIR.iterdir() if d.is_dir() and (SNAPSHOT_DIR / d.name / "rankings.csv").exists()
    )
    log.info("Found %d dates with PIT caches + rankings", len(cache_dates))

    all_names = []
    for d in cache_dates:
        names = load_snapshot_with_returns(d)
        all_names.extend(names)
    log.info("Total name-date observations: %d", len(all_names))

    # Filter to liquid options names
    liquid = [n for n in all_names if n["opt_has_data"] and n["opt_liquidity_ok"]]
    log.info("Liquid chain observations: %d", len(liquid))

    # --- Study 1: Event-loaded vs flat surfaces ---
    event_loaded = [n for n in liquid if n["opt_event_premium"]]
    flat_surface = [n for n in liquid if not n["opt_event_premium"]]

    study1 = {
        "question": "Do event-loaded surfaces outperform flat ones?",
        "event_loaded": _cohort_return_stats(event_loaded, "event_loaded"),
        "flat_surface": _cohort_return_stats(flat_surface, "flat"),
    }
    spread1 = (study1["event_loaded"].get("mean_return", 0) or 0) - (study1["flat_surface"].get("mean_return", 0) or 0)
    study1["spread"] = round(spread1, 4)

    # --- Study 2: Skew-extreme resolution by catalyst type ---
    # Split by RR quartiles
    rr_vals = [n["opt_rr_25d"] for n in liquid if not math.isnan(n["opt_rr_25d"])]
    if rr_vals:
        rr_sorted = sorted(rr_vals)
        q25 = rr_sorted[len(rr_sorted) // 4]
        q75 = rr_sorted[3 * len(rr_sorted) // 4]

        rr_high = [n for n in liquid if not math.isnan(n["opt_rr_25d"]) and n["opt_rr_25d"] >= q75]
        rr_low = [n for n in liquid if not math.isnan(n["opt_rr_25d"]) and n["opt_rr_25d"] <= q25]
        rr_mid = [n for n in liquid if not math.isnan(n["opt_rr_25d"]) and q25 < n["opt_rr_25d"] < q75]

        study2 = {
            "question": "Do skew-extreme names resolve differently?",
            "rr_q75_plus": _cohort_return_stats(rr_high, "RR >= Q75 (puts expensive)"),
            "rr_q25_minus": _cohort_return_stats(rr_low, "RR <= Q25 (calls expensive)"),
            "rr_middle": _cohort_return_stats(rr_mid, "RR middle"),
            "q25": round(q25, 4),
            "q75": round(q75, 4),
        }
    else:
        study2 = {"question": "Do skew-extreme names resolve differently?", "n": 0}

    # --- Study 3: Event premium ratio predictiveness ---
    epr_names = [n for n in liquid if not math.isnan(n["event_premium_ratio"])]
    if epr_names:
        epr_sorted = sorted(epr_names, key=lambda n: n["event_premium_ratio"])
        n = len(epr_sorted)
        q1 = epr_sorted[: n // 3]
        q3 = epr_sorted[2 * n // 3 :]

        study3 = {
            "question": "Does event premium ratio predict forward returns?",
            "high_epr_tercile": _cohort_return_stats(q3, "EPR top tercile (most event-loaded)"),
            "low_epr_tercile": _cohort_return_stats(q1, "EPR bottom tercile (least event-loaded)"),
            "spread": round(
                (_cohort_return_stats(q3, "")["mean_return"] or 0) - (_cohort_return_stats(q1, "")["mean_return"] or 0),
                4,
            ),
        }
    else:
        study3 = {"question": "Does event premium ratio predict forward returns?", "n": 0}

    # --- Study 4: Hard catalyst + regulatory subset ---
    hard_reg = [n for n in liquid if n["is_hard_catalyst"] and n["catalyst_family"] == "REGULATORY"]
    hard_clin = [n for n in liquid if n["is_hard_catalyst"] and n["catalyst_family"] == "CLINICAL"]
    soft = [n for n in liquid if not n["is_hard_catalyst"]]

    study4 = {
        "question": "Hard regulatory vs clinical vs soft — return profiles?",
        "hard_regulatory": _cohort_return_stats(hard_reg, "hard_regulatory"),
        "hard_clinical": _cohort_return_stats(hard_clin, "hard_clinical"),
        "soft": _cohort_return_stats(soft, "soft_catalyst"),
    }

    # --- Study 5: IV regime and returns ---
    by_regime = defaultdict(list)
    for n in liquid:
        regime = n.get("opt_iv_regime", "UNKNOWN") or "UNKNOWN"
        by_regime[regime].append(n)

    study5 = {
        "question": "Does IV regime predict return distribution?",
        "regimes": {k: _cohort_return_stats(v, k) for k, v in sorted(by_regime.items())},
    }

    # --- Study 6: Implied move percentile and returns ---
    aim_names = [n for n in liquid if not math.isnan(n["actual_implied_move_pctile"])]
    if aim_names:
        aim_sorted = sorted(aim_names, key=lambda n: n["actual_implied_move_pctile"])
        n = len(aim_sorted)
        aim_hi = aim_sorted[2 * n // 3 :]
        aim_lo = aim_sorted[: n // 3]

        study6 = {
            "question": "Does actual_implied_move_pctile predict returns? (IC=0.202 was the headline)",
            "high_aim_tercile": _cohort_return_stats(aim_hi, "AIM top tercile (high implied move)"),
            "low_aim_tercile": _cohort_return_stats(aim_lo, "AIM bottom tercile (low implied move)"),
            "spread": round(
                (_cohort_return_stats(aim_hi, "")["mean_return"] or 0)
                - (_cohort_return_stats(aim_lo, "")["mean_return"] or 0),
                4,
            ),
        }
    else:
        study6 = {"question": "Does actual_implied_move_pctile predict returns?", "n": 0}

    return {
        "schema": "options_ev_pilot.v1",
        "n_total": len(all_names),
        "n_liquid": len(liquid),
        "n_dates": len(cache_dates),
        "studies": {
            "event_loaded_vs_flat": study1,
            "skew_extreme_resolution": study2,
            "event_premium_ratio_predictiveness": study3,
            "hard_reg_vs_clinical_vs_soft": study4,
            "iv_regime_returns": study5,
            "implied_move_pctile_returns": study6,
        },
    }


def print_results(result: dict):
    print(f"\n{'='*70}")
    print(f"OPTIONS EV PILOT — Liquid Chain Names Only")
    print(f"{'='*70}")
    print(f"Dates: {result['n_dates']}, Total obs: {result['n_total']}, Liquid: {result['n_liquid']}")

    for study_name, study in result["studies"].items():
        print(f"\n--- {study['question']} ---")
        for k, v in study.items():
            if k == "question":
                continue
            if isinstance(v, dict) and "n" in v:
                ret = v.get("mean_return")
                pct = v.get("pct_positive")
                ret_str = f"{ret:>+.4f}" if ret is not None else "—"
                pct_str = f"{pct:.0%}" if pct is not None else "—"
                print(f"  {v.get('label', k):<40} n={v['n']:<5} mean={ret_str}  %+={pct_str}")
            elif k == "spread":
                print(f"  {'SPREAD':<40} {v:>+.4f}")
            elif isinstance(v, dict):
                for kk, vv in v.items():
                    if isinstance(vv, dict) and "n" in vv:
                        ret = vv.get("mean_return")
                        pct = vv.get("pct_positive")
                        ret_str = f"{ret:>+.4f}" if ret is not None else "—"
                        pct_str = f"{pct:.0%}" if pct is not None else "—"
                        print(f"  {vv.get('label', kk):<40} n={vv['n']:<5} mean={ret_str}  %+={pct_str}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = run_pilot()

    output_path = OUTPUT_DIR / "options_ev_pilot.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", output_path)

    print_results(result)


if __name__ == "__main__":
    main()
