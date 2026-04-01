"""Construction v2 compare pack: EW Top-30 control + three experimental variants.

Candidates:
  1. EW Top-30 (control)
  2. Rank-Weighted Top-30
  3. Dynamic Caps Top-30 (bucket metadata as soft caps, no fixed budgets)
  4. Regime-Conditioned (bear: Top-20 concentrated, bull: Top-40 diversified)

All reported gross and net of transaction costs.

Usage:
    python scripts/research/construction_v2_compare.py
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from common.rebalance_cost_model import estimate_historical_cost_drag

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
PRICE_PATH = REPO_ROOT / "production_data" / "price_history.csv"
SHADOW_PERF_PATH = REPO_ROOT / "artifacts" / "live_shadow" / "performance.csv"
OUTPUT_DIR = REPO_ROOT / "output" / "benchmarks"

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("v2_compare")


# ---------------------------------------------------------------------------
# Data loading (shared with earlier benchmarks)
# ---------------------------------------------------------------------------


def load_price_map(price_path: Path) -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = defaultdict(dict)
    with open(price_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tk = row.get("ticker", "").strip()
            dt = row.get("date", "").strip()
            cl = row.get("close", "").strip()
            if tk and dt and cl:
                try:
                    prices[dt][tk] = float(cl)
                except ValueError:
                    pass
    return dict(prices)


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


def xbi_return(pp: dict, cp: dict) -> float:
    p0 = pp.get("XBI")
    p1 = cp.get("XBI")
    if p0 and p1 and p0 > 0:
        return ((p1 / p0) - 1.0) * 100
    return 0.0


def compute_return(positions: list[dict], pp: dict, cp: dict) -> float:
    if not positions:
        return 0.0
    tw = sum(p["weight_pct"] for p in positions)
    if tw == 0:
        return 0.0
    ret = 0.0
    for p in positions:
        w = p["weight_pct"] / tw
        p0 = pp.get(p["ticker"])
        p1 = cp.get(p["ticker"])
        if p0 and p1 and p0 > 0:
            ret += w * ((p1 / p0) - 1.0)
    return ret * 100


def compute_turnover(prior: list[dict], current: list[dict]) -> float:
    pt = set(p["ticker"] for p in prior)
    ct = set(p["ticker"] for p in current)
    if not pt:
        return 0.0
    return 1.0 - len(pt & ct) / len(pt)


def load_shadow_perf() -> dict[str, dict]:
    if not SHADOW_PERF_PATH.exists():
        return {}
    result = {}
    with open(SHADOW_PERF_PATH, encoding="utf-8") as f:
        for line in csv.reader(f):
            if len(line) >= 10 and line[0] == "live_shadow_perf.v1":
                try:
                    result[line[1]] = {
                        "pnl_pct": float(line[4]) if line[4] else 0,
                        "xbi_pct": float(line[5]) if line[5] else 0,
                    }
                except (ValueError, IndexError):
                    pass
    return result


# ---------------------------------------------------------------------------
# Portfolio construction variants
# ---------------------------------------------------------------------------


def build_ew_topn(rankings: list[dict], n: int = 30) -> list[dict]:
    """Candidate 1: Equal-weight top-N."""
    sel = rankings[:n]
    if not sel:
        return []
    w = 100.0 / len(sel)
    return [{"ticker": r["ticker"].upper(), "weight_pct": w, "bucket": classify_bucket(r)} for r in sel]


def build_rank_weighted(rankings: list[dict], n: int = 30) -> list[dict]:
    """Candidate 2: Rank-weighted top-N (inverse rank)."""
    sel = rankings[:n]
    if not sel:
        return []
    raw = [n - i for i in range(len(sel))]
    total = sum(raw)
    return [
        {"ticker": r["ticker"].upper(), "weight_pct": (rw / total) * 100, "bucket": classify_bucket(r)}
        for r, rw in zip(sel, raw)
    ]


def build_dynamic_caps(rankings: list[dict], n: int = 30) -> list[dict]:
    """Candidate 3: EW top-N with dynamic soft caps from bucket metadata.

    No fixed budget. Equal weight baseline, but:
    - binary_0_30 names capped at 2% (near-term event risk)
    - binary_91_180 names capped at 4% (avoid over-concentration in far bucket)
    - Excess weight redistributed to uncapped names
    """
    sel = rankings[:n]
    if not sel:
        return []

    SOFT_CAPS = {
        "binary_0_30": 2.0,
        "binary_31_90": 5.0,  # effectively uncapped
        "binary_91_180": 4.0,
        "less_binary": 5.0,  # effectively uncapped
    }

    positions = []
    for r in sel:
        bucket = classify_bucket(r)
        positions.append(
            {
                "ticker": r["ticker"].upper(),
                "weight_pct": 100.0 / len(sel),
                "bucket": bucket,
                "cap": SOFT_CAPS.get(bucket, 5.0),
            }
        )

    # Iterative redistribution (2 passes)
    for _ in range(3):
        excess = 0.0
        uncapped_count = 0
        for p in positions:
            if p["weight_pct"] > p["cap"]:
                excess += p["weight_pct"] - p["cap"]
                p["weight_pct"] = p["cap"]
            else:
                uncapped_count += 1

        if excess > 0 and uncapped_count > 0:
            boost = excess / uncapped_count
            for p in positions:
                if p["weight_pct"] < p["cap"]:
                    p["weight_pct"] += boost

    # Clean up
    for p in positions:
        del p["cap"]

    return positions


def build_regime_conditioned(
    rankings: list[dict],
    is_bear: bool,
) -> list[dict]:
    """Candidate 4: Regime-conditioned construction.

    Bear regime: concentrated top-20 (let the selector run)
    Bull regime: diversified top-40 (wider net, less concentration)
    """
    if is_bear:
        return build_ew_topn(rankings, 20)
    else:
        return build_ew_topn(rankings, 40)


# ---------------------------------------------------------------------------
# XBI regime classifier
# ---------------------------------------------------------------------------


def classify_xbi_regime(
    all_prices: dict[str, dict[str, float]],
    current_date: str,
    lookback_days: int = 20,
) -> str:
    """Simple XBI trend regime classifier.

    Bear: XBI 20-day return <= 0
    Bull: XBI 20-day return > 0
    """
    # Find the date ~lookback_days ago
    sorted_dates = sorted(d for d in all_prices if d <= current_date)
    if len(sorted_dates) < lookback_days:
        return "bull"  # default to bull if insufficient history

    lookback_date = sorted_dates[-lookback_days]
    xbi_now = all_prices.get(current_date, {}).get("XBI")
    xbi_then = all_prices.get(lookback_date, {}).get("XBI")

    if xbi_now and xbi_then and xbi_then > 0:
        ret = (xbi_now / xbi_then) - 1.0
        return "bear" if ret <= 0 else "bull"
    return "bull"


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------

CANDIDATES = {
    "ew30": "EW Top-30 (control)",
    "rw30": "Rank-Weighted Top-30",
    "dc30": "Dynamic Caps Top-30",
    "regime": "Regime-Conditioned",
}


def run_compare():
    log.info("Loading prices...")
    all_prices = load_price_map(PRICE_PATH)

    dates = sorted(
        d.name
        for d in SNAPSHOT_DIR.iterdir()
        if d.is_dir() and d.name >= "2000-01-01" and (d / "rankings.csv").exists()
    )
    log.info("Found %d snapshot dates", len(dates))

    shadow_perf = load_shadow_perf()

    # Pre-build positions
    positions_by_date: dict[str, dict[str, list]] = {}
    regime_by_date: dict[str, str] = {}

    for d in dates:
        rankings = load_rankings(d)
        regime = classify_xbi_regime(all_prices, d)
        regime_by_date[d] = regime

        positions_by_date[d] = {
            "ew30": build_ew_topn(rankings, 30),
            "rw30": build_rank_weighted(rankings, 30),
            "dc30": build_dynamic_caps(rankings, 30),
            "regime": build_regime_conditioned(rankings, is_bear=(regime == "bear")),
        }

    # Compute period returns
    periods = []
    for i in range(1, len(dates)):
        prior = dates[i - 1]
        current = dates[i]
        pp = all_prices.get(prior, {})
        cp = all_prices.get(current, {})
        if not pp or not cp:
            continue

        xbi_ret = xbi_return(pp, cp)
        period = {
            "date": current,
            "prior_date": prior,
            "xbi_pct": round(xbi_ret, 4),
            "regime": regime_by_date.get(prior, "bull"),
        }

        for cid in CANDIDATES:
            ret = compute_return(positions_by_date[prior][cid], pp, cp)
            turnover = compute_turnover(
                positions_by_date[prior][cid],
                positions_by_date[current][cid] if current in positions_by_date else [],
            )
            period[f"{cid}_pnl_pct"] = round(ret, 4)
            period[f"{cid}_excess"] = round(ret - xbi_ret, 4)
            period[f"{cid}_turnover"] = round(turnover, 4)
            period[f"{cid}_n_held"] = len(positions_by_date[prior][cid])

        sh = shadow_perf.get(current)
        if sh:
            period["shadow_pnl_pct"] = sh["pnl_pct"]
            period["shadow_excess"] = round(sh["pnl_pct"] - sh["xbi_pct"], 4)

        periods.append(period)

    # Summaries by window
    windows = {
        "full": lambda p: True,
        "2024_2026": lambda p: p["date"] >= "2024-01-01",
        "2025_2026": lambda p: p["date"] >= "2025-01-01",
        "2026_ytd": lambda p: p["date"] >= "2026-01-01",
        "bear_regime": lambda p: p["regime"] == "bear",
        "bull_regime": lambda p: p["regime"] == "bull",
    }

    summaries = {}
    for wname, filt in windows.items():
        wp = [p for p in periods if filt(p)]
        if not wp:
            continue

        s = {"window": wname, "n_periods": len(wp), "date_range": f"{wp[0]['prior_date']} to {wp[-1]['date']}"}

        xbi_cum = sum(p["xbi_pct"] for p in wp)
        s["xbi_cumulative_pct"] = round(xbi_cum, 2)

        for cid in CANDIDATES:
            cum = sum(p.get(f"{cid}_pnl_pct", 0) for p in wp)
            excess = cum - xbi_cum
            wins = sum(1 for p in wp if p.get(f"{cid}_excess", 0) > 0)

            # Mean turnover
            turnovers = [p.get(f"{cid}_turnover", 0) for p in wp]
            mean_turnover = sum(turnovers) / max(len(turnovers), 1)

            # IR
            excesses = [p.get(f"{cid}_excess", 0) for p in wp]
            if len(excesses) > 1:
                mu = sum(excesses) / len(excesses)
                var = sum((x - mu) ** 2 for x in excesses) / (len(excesses) - 1)
                std = math.sqrt(var) if var > 0 else 1e-9
                ir = mu / std * math.sqrt(252)
            else:
                ir = 0

            # Cost drag
            cost_periods = [{"turnover": t, "n_held": 30} for t in turnovers]
            drag = estimate_historical_cost_drag(cost_periods, avg_cost_bps=50)

            s[f"{cid}_gross_excess_pct"] = round(excess, 2)
            s[f"{cid}_cost_drag_pct"] = round(drag["total_cost_drag_pct"], 2)
            s[f"{cid}_net_excess_pct"] = round(excess - drag["total_cost_drag_pct"], 2)
            s[f"{cid}_win_rate"] = round(wins / max(len(wp), 1), 3)
            s[f"{cid}_ir"] = round(ir, 2)
            s[f"{cid}_mean_turnover"] = round(mean_turnover, 3)

        # Shadow
        swp = [p for p in wp if "shadow_pnl_pct" in p]
        if swp:
            sh_cum = sum(p["shadow_pnl_pct"] for p in swp)
            sh_xbi = sum(p["xbi_pct"] for p in swp)
            s["shadow_n_periods"] = len(swp)
            s["shadow_excess_pct"] = round(sh_cum - sh_xbi, 2)

        summaries[wname] = s

    # Regime distribution
    n_bear = sum(1 for p in periods if p["regime"] == "bear")
    n_bull = sum(1 for p in periods if p["regime"] == "bull")

    return {
        "schema": "construction_v2_compare.v1",
        "generated_at": datetime.now().isoformat(),
        "candidates": CANDIDATES,
        "regime_distribution": {"bear": n_bear, "bull": n_bull},
        "summaries": summaries,
        "periods": periods,
    }


def print_results(result: dict):
    candidates = result["candidates"]
    rd = result["regime_distribution"]
    print(
        f"\nRegime distribution: bear={rd['bear']} ({100*rd['bear']/(rd['bear']+rd['bull']):.0f}%), "
        f"bull={rd['bull']} ({100*rd['bull']/(rd['bear']+rd['bull']):.0f}%)"
    )

    for wname, s in result["summaries"].items():
        print(f"\n{'='*80}")
        print(f"WINDOW: {wname} ({s['n_periods']} periods, {s['date_range']})")
        print(f"{'='*80}")

        header = f"{'Candidate':<28} {'Gross':<9} {'Cost':<8} {'Net':<9} {'Win%':<7} {'IR':<7} {'Turn':<7} {'N':<4}"
        print(header)
        print("-" * len(header))

        for cid, label in candidates.items():
            gross = s.get(f"{cid}_gross_excess_pct", 0)
            cost = s.get(f"{cid}_cost_drag_pct", 0)
            net = s.get(f"{cid}_net_excess_pct", 0)
            wr = s.get(f"{cid}_win_rate", 0)
            ir = s.get(f"{cid}_ir", 0)
            turn = s.get(f"{cid}_mean_turnover", 0)
            # Avg n_held from periods
            wp = [
                p
                for p in result["periods"]
                if (
                    wname == "full"
                    or (wname == "2024_2026" and p["date"] >= "2024-01-01")
                    or (wname == "2025_2026" and p["date"] >= "2025-01-01")
                    or (wname == "2026_ytd" and p["date"] >= "2026-01-01")
                    or (wname == "bear_regime" and p["regime"] == "bear")
                    or (wname == "bull_regime" and p["regime"] == "bull")
                )
            ]
            avg_n = sum(p.get(f"{cid}_n_held", 30) for p in wp) / max(len(wp), 1)

            marker = " <--" if cid == "ew30" else ""
            print(
                f"{label:<28} {gross:>+6.1f}%  {cost:>5.1f}%  {net:>+6.1f}%  {wr:>5.1%}  {ir:>5.1f}  {turn:>5.1%}  {avg_n:>3.0f}{marker}"
            )

        if "shadow_excess_pct" in s:
            print(f"{'Shadow (legacy)':<28} {s['shadow_excess_pct']:>+6.1f}%")

        print(f"{'XBI':<28} {s['xbi_cumulative_pct']:>+6.1f}%")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = run_compare()

    output_path = OUTPUT_DIR / "construction_v2_compare.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", output_path)

    print_results(result)


if __name__ == "__main__":
    main()
