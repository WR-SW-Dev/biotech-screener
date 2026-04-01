"""Construction v2 benchmark pack: test simpler portfolio variants.

Candidates:
  A: EW top-20, no sleeves (pure selection)
  B: EW top-20, loose sleeves (no fixed budget, natural bucket distribution)
  C: EW top-30, no sleeves (wider selection)
  D: Rank-weighted top-20 (higher weight to higher-ranked names)
  E: Current shadow (baseline)

Also runs regime-sliced comparison:
  - Full history
  - 2024-2026
  - 2025-2026
  - Bull vs risk-off biotech (XBI monthly return > 0 vs <= 0)

Usage:
    python scripts/research/construction_v2_benchmark.py
"""

from __future__ import annotations

import csv
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
PRICE_PATH = REPO_ROOT / "production_data" / "price_history.csv"
SHADOW_PERF_PATH = REPO_ROOT / "artifacts" / "live_shadow" / "performance.csv"
OUTPUT_DIR = REPO_ROOT / "output" / "benchmarks"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("construction_v2")


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


# ---------------------------------------------------------------------------
# Portfolio variants
# ---------------------------------------------------------------------------


def build_candidate_a(rankings: list[dict]) -> list[dict]:
    """Candidate A: EW top-20, no sleeves."""
    sel = rankings[:20]
    if not sel:
        return []
    w = 100.0 / len(sel)
    return [{"ticker": r["ticker"].upper(), "weight_pct": w} for r in sel]


def build_candidate_b(rankings: list[dict]) -> list[dict]:
    """Candidate B: EW top-20, loose sleeves (natural distribution, no forced budget)."""
    sel = rankings[:20]
    if not sel:
        return []
    # Assign buckets but don't force budget allocation
    w = 100.0 / len(sel)
    return [{"ticker": r["ticker"].upper(), "weight_pct": w, "bucket": classify_bucket(r)} for r in sel]


def build_candidate_c(rankings: list[dict]) -> list[dict]:
    """Candidate C: EW top-30, no sleeves."""
    sel = rankings[:30]
    if not sel:
        return []
    w = 100.0 / len(sel)
    return [{"ticker": r["ticker"].upper(), "weight_pct": w} for r in sel]


def build_candidate_d(rankings: list[dict]) -> list[dict]:
    """Candidate D: Rank-weighted top-20 (inverse rank weight, more to #1)."""
    sel = rankings[:20]
    if not sel:
        return []
    # Inverse rank weighting: rank 1 gets weight 20, rank 2 gets 19, etc.
    n = len(sel)
    raw_weights = [n - i for i in range(n)]
    total = sum(raw_weights)
    return [{"ticker": r["ticker"].upper(), "weight_pct": (rw / total) * 100} for r, rw in zip(sel, raw_weights)]


CANDIDATES = {
    "A_ew20": ("EW Top-20 (no sleeves)", build_candidate_a),
    "B_ew20_loose": ("EW Top-20 (loose sleeves)", build_candidate_b),
    "C_ew30": ("EW Top-30 (no sleeves)", build_candidate_c),
    "D_rank_wt20": ("Rank-Weighted Top-20", build_candidate_d),
}


# ---------------------------------------------------------------------------
# Return computation
# ---------------------------------------------------------------------------


def compute_return(
    positions: list[dict],
    prior_prices: dict[str, float],
    current_prices: dict[str, float],
) -> float:
    """Compute weighted portfolio return (pct)."""
    if not positions:
        return 0.0
    total_w = sum(p["weight_pct"] for p in positions)
    if total_w == 0:
        return 0.0
    ret = 0.0
    for p in positions:
        tk = p["ticker"]
        w = p["weight_pct"] / total_w
        p0 = prior_prices.get(tk)
        p1 = current_prices.get(tk)
        if p0 and p1 and p0 > 0:
            ret += w * ((p1 / p0) - 1.0)
    return ret * 100


def xbi_return(prior_prices: dict[str, float], current_prices: dict[str, float]) -> float:
    p0 = prior_prices.get("XBI")
    p1 = current_prices.get("XBI")
    if p0 and p1 and p0 > 0:
        return ((p1 / p0) - 1.0) * 100
    return 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_benchmarks() -> dict:
    log.info("Loading prices...")
    all_prices = load_price_map(PRICE_PATH)

    dates = sorted(
        d.name
        for d in SNAPSHOT_DIR.iterdir()
        if d.is_dir() and d.name >= "2000-01-01" and (d / "rankings.csv").exists()
    )
    log.info("Found %d snapshot dates", len(dates))

    shadow_perf = load_shadow_perf()

    # Pre-build positions for all candidates and dates
    positions_by_date: dict[str, dict[str, list]] = {}
    for d in dates:
        rankings = load_rankings(d)
        positions_by_date[d] = {}
        for cid, (_, builder) in CANDIDATES.items():
            positions_by_date[d][cid] = builder(rankings)

    # Compute period returns
    periods = []
    for i in range(1, len(dates)):
        prior = dates[i - 1]
        current = dates[i]
        pp = all_prices.get(prior, {})
        cp = all_prices.get(current, {})
        if not pp or not cp:
            continue

        period: dict = {
            "date": current,
            "prior_date": prior,
            "xbi_pct": round(xbi_return(pp, cp), 4),
        }

        for cid in CANDIDATES:
            ret = compute_return(positions_by_date[prior][cid], pp, cp)
            period[f"{cid}_pnl_pct"] = round(ret, 4)
            period[f"{cid}_excess"] = round(ret - period["xbi_pct"], 4)

        sh = shadow_perf.get(current)
        if sh:
            period["shadow_pnl_pct"] = sh["pnl_pct"]
            period["shadow_excess"] = round(sh["pnl_pct"] - sh["xbi_pct"], 4)

        periods.append(period)

    # Compute summaries for different windows
    windows = {
        "full": lambda p: True,
        "2024_2026": lambda p: p["date"] >= "2024-01-01",
        "2025_2026": lambda p: p["date"] >= "2025-01-01",
        "2026_ytd": lambda p: p["date"] >= "2026-01-01",
        "bull_xbi": lambda p: p["xbi_pct"] > 0,
        "bear_xbi": lambda p: p["xbi_pct"] <= 0,
    }

    summaries = {}
    for window_name, filt in windows.items():
        wp = [p for p in periods if filt(p)]
        if not wp:
            continue

        s: dict = {
            "window": window_name,
            "n_periods": len(wp),
            "date_range": f"{wp[0]['prior_date']} to {wp[-1]['date']}",
        }

        xbi_cum = sum(p["xbi_pct"] for p in wp)
        s["xbi_cumulative_pct"] = round(xbi_cum, 2)

        for cid, (label, _) in CANDIDATES.items():
            cum = sum(p.get(f"{cid}_pnl_pct", 0) for p in wp)
            excess = cum - xbi_cum
            wins = sum(1 for p in wp if p.get(f"{cid}_excess", 0) > 0)
            s[f"{cid}_cumulative_pct"] = round(cum, 2)
            s[f"{cid}_excess_pct"] = round(excess, 2)
            s[f"{cid}_win_rate"] = round(wins / max(len(wp), 1), 3)

            # Sharpe-like ratio (excess return / vol of excess)
            excesses = [p.get(f"{cid}_excess", 0) for p in wp]
            if len(excesses) > 1:
                mu = sum(excesses) / len(excesses)
                var = sum((x - mu) ** 2 for x in excesses) / (len(excesses) - 1)
                std = math.sqrt(var) if var > 0 else 1e-9
                s[f"{cid}_ir"] = round(mu / std * math.sqrt(252), 2)  # annualized

        # Shadow (only for periods with shadow data)
        shadow_wp = [p for p in wp if "shadow_pnl_pct" in p]
        if shadow_wp:
            sh_cum = sum(p["shadow_pnl_pct"] for p in shadow_wp)
            sh_xbi = sum(p["xbi_pct"] for p in shadow_wp)
            sh_wins = sum(1 for p in shadow_wp if p.get("shadow_excess", 0) > 0)
            s["shadow_n_periods"] = len(shadow_wp)
            s["shadow_cumulative_pct"] = round(sh_cum, 2)
            s["shadow_excess_pct"] = round(sh_cum - sh_xbi, 2)
            s["shadow_win_rate"] = round(sh_wins / max(len(shadow_wp), 1), 3)

        summaries[window_name] = s

    # Turnover analysis for each candidate
    turnover_stats = {}
    for cid in CANDIDATES:
        turnovers = []
        for i in range(1, len(dates)):
            prior_pos = positions_by_date[dates[i - 1]][cid]
            curr_pos = positions_by_date[dates[i]][cid]
            prior_tks = set(p["ticker"] for p in prior_pos)
            curr_tks = set(p["ticker"] for p in curr_pos)
            if prior_tks:
                overlap = len(prior_tks & curr_tks)
                turnovers.append(1.0 - overlap / len(prior_tks))
        if turnovers:
            turnover_stats[cid] = {
                "mean_turnover": round(sum(turnovers) / len(turnovers), 4),
                "max_turnover": round(max(turnovers), 4),
                "periods_with_change": sum(1 for t in turnovers if t > 0),
            }

    return {
        "schema": "construction_v2_benchmark.v1",
        "generated_at": datetime.now().isoformat(),
        "candidates": {cid: label for cid, (label, _) in CANDIDATES.items()},
        "summaries": summaries,
        "turnover": turnover_stats,
        "periods": periods,
    }


def print_summary(result: dict):
    summaries = result["summaries"]
    candidates = result["candidates"]

    for window_name, s in summaries.items():
        print(f"\n{'='*75}")
        print(f"WINDOW: {window_name} ({s['n_periods']} periods, {s['date_range']})")
        print(f"{'='*75}")

        header = f"{'Variant':<28} {'Cumul':<10} {'Excess':<10} {'Win%':<8} {'IR':<8}"
        print(header)
        print("-" * len(header))

        for cid, label in candidates.items():
            cum = s.get(f"{cid}_cumulative_pct", 0)
            exc = s.get(f"{cid}_excess_pct", 0)
            wr = s.get(f"{cid}_win_rate", 0)
            ir = s.get(f"{cid}_ir", "—")
            ir_str = f"{ir}" if isinstance(ir, (int, float)) else ir
            print(f"{label:<28} {cum:>+7.1f}%  {exc:>+7.1f}%  {wr:>5.1%}  {ir_str:>6}")

        if "shadow_cumulative_pct" in s:
            print(
                f"{'Shadow (constructed)':<28} {s['shadow_cumulative_pct']:>+7.1f}%  {s['shadow_excess_pct']:>+7.1f}%  {s['shadow_win_rate']:>5.1%}"
            )

        print(f"{'XBI':<28} {s['xbi_cumulative_pct']:>+7.1f}%")

    # Turnover
    print(f"\n{'='*75}")
    print("TURNOVER ANALYSIS")
    print(f"{'='*75}")
    for cid, label in candidates.items():
        ts = result["turnover"].get(cid, {})
        print(f"  {label:<28} mean={ts.get('mean_turnover',0):.1%}  max={ts.get('max_turnover',0):.1%}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = run_benchmarks()

    output_path = OUTPUT_DIR / "construction_v2_benchmark.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Wrote %s", output_path)

    print_summary(result)


if __name__ == "__main__":
    main()
